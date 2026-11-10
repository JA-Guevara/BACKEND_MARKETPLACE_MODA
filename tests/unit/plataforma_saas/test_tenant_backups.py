from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import json
from uuid import uuid4
import zipfile
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from src.infrastructure.config.settings import settings
from src.plataforma_saas.application.tenant_backup_service import TenantBackupService, process_backups, next_execution
from src.plataforma_saas.application.tenant_backup_archive import validate
from src.plataforma_saas.infrastructure.models.tenant_backup import TenantBackupPolicy, TenantBackupRun
from src.roles.infrastructure.persistence.models.permission import PermissionModel
from src.ventas_pagos.infrastructure.models import StockModel
from src.shared.exceptions.domain_exception import ValidationError


@pytest.fixture
def backup_world(world,monkeypatch):
    monkeypatch.setattr(settings,'tenant_backup_encryption_key',SecretStr(Fernet.generate_key().decode()))
    for code,role,scope in [('tenant.data_export',world.admin_role,'tenant'),
                            ('platform.ops.read',world.platform_role,'platform'),('platform.ops.write',world.platform_role,'platform')]:
        permission=PermissionModel(code=code,name=code,module='users',scope=scope)
        role.permissions.append(permission)
    world.db.commit()
    return world


def test_copy_rehearsal_download_and_tenant_isolation(backup_world):
    w=backup_world
    request={'request_id':str(uuid4())}
    first=w.client.post('/api/v1/tenant/backups',headers=w.headers(w.admin_a),json=request)
    assert first.status_code==202,first.text
    run_id=first.json()['data']['id']
    repeated=w.client.post('/api/v1/tenant/backups',headers=w.headers(w.admin_a),json=request)
    assert repeated.json()['data']['id']==run_id
    assert process_backups(sessionmaker(bind=w.engine,expire_on_commit=False))==1
    w.db.expire_all()
    result=w.client.get('/api/v1/tenant/backups',headers=w.headers(w.admin_a)).json()['data']
    assert result['items'][0]['status']=='verified'
    assert result['items'][0]['report']['restored']
    download=w.client.get(f'/api/v1/tenant/backups/{run_id}/download',headers=w.headers(w.admin_a))
    assert download.status_code==200
    assert download.headers['cache-control']=='no-store'
    archive=zipfile.ZipFile(BytesIO(download.content))
    data=json.loads(archive.read('data.json'))
    assert [row['id'] for row in data['tenants']]==[str(w.tenant_a.id)]
    assert [row['id'] for row in data['product_variants']]==[str(w.variant_a.id)]
    assert data['commerce_stock'][0]['quantity']==20
    assert all('password_hash' not in row for row in data['users'])
    assert str(w.tenant_b.id) not in archive.read('data.json').decode()
    assert w.client.get(f'/api/v1/tenant/backups/{run_id}/download',headers=w.headers(w.admin_b)).status_code==404
    assert w.client.get(f'/api/v1/platform/tenants/{w.tenant_a.id}/backups',headers=w.headers(w.admin_a)).status_code==403
    assert w.client.get(f'/api/v1/platform/tenants/{w.tenant_a.id}/backups',headers=w.headers(w.platform)).status_code==200
    assert w.client.post('/api/v1/tenant/backups',headers=w.headers(w.admin_a),json={**request,'tenant_id':str(w.tenant_b.id)}).status_code==422


def test_missing_key_disables_creation_without_touching_data(backup_world,monkeypatch):
    w=backup_world
    monkeypatch.setattr(settings,'tenant_backup_encryption_key',None)
    assert not w.client.get('/api/v1/tenant/backups',headers=w.headers(w.admin_a)).json()['data']['configured']
    response=w.client.post('/api/v1/tenant/backups',headers=w.headers(w.admin_a),json={'request_id':str(uuid4())})
    assert response.status_code==409
    assert process_backups(sessionmaker(bind=w.engine))==0
    assert w.db.scalars(select(TenantBackupRun)).all()==[]


def test_scheduled_copy_claim_is_idempotent_and_preserves_last_valid_copy(backup_world):
    w=backup_world
    svc=TenantBackupService(w.db,w.tenant_a.id,w.admin_a)
    svc.configure({'enabled':True,'frequency':'daily','hour':3,'timezone':'America/La_Paz','retention':1})
    policy=svc.policy();now=datetime.now(timezone.utc)
    policy.next_run_at=now-timedelta(hours=1);w.db.commit()
    factory=sessionmaker(bind=w.engine,expire_on_commit=False)
    assert process_backups(factory,now=now)==1
    assert process_backups(factory,now=now)==0
    w.db.expire_all()
    assert len(svc.status()['items'])==1
    policy=svc.policy();policy.next_run_at=now-timedelta(minutes=10);w.db.commit()
    assert process_backups(factory,now=now)==1
    w.db.expire_all()
    assert sorted(run.status for run in w.db.scalars(select(TenantBackupRun)))==['expired','verified']
    assert next_execution(policy,now)>now


def test_cross_tenant_reference_fails_without_partial_archive(backup_world):
    w=backup_world
    w.db.add(StockModel(branch_id=w.branch_a.id,variant_id=w.variant_b.id,quantity=2));w.db.commit()
    service=TenantBackupService(w.db,w.tenant_a.id,w.admin_a)
    run=service.enqueue(str(uuid4()))
    process_backups(sessionmaker(bind=w.engine,expire_on_commit=False))
    w.db.expire_all()
    run=service.run(run.id)
    assert run.status=='failed'
    assert run.artifact is None
    assert 'ajena' in run.error


def test_archive_manifest_detects_modified_rows():
    with pytest.raises(ValidationError):
        validate({'manifest':{'format':'fashionstore-business-v1','sha256':'0'*64},'data':{},'files':{}})


def test_platform_all_tenants_backups_overview(backup_world):
    w = backup_world
    res = w.client.get('/api/v1/platform/backups/tenants', headers=w.headers(w.platform))
    assert res.status_code == 200, res.text
    data = res.json()['data']
    assert 'summary' in data
    assert 'items' in data
    assert data['summary']['total_tenants'] >= 2
    assert data['summary']['configured'] is True

    # Check non-platform cannot access
    unauth = w.client.get('/api/v1/platform/backups/tenants', headers=w.headers(w.admin_a))
    assert unauth.status_code == 403

    # Process queue
    proc = w.client.post('/api/v1/platform/backups/process-queue', headers=w.headers(w.platform))
    assert proc.status_code == 200
    assert 'processed' in proc.json()['data']

