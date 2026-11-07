"""Archivo de negocio por empresa. Importador controlado; nunca ejecuta SQL del archivo."""
import base64
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
from time import monotonic
from uuid import UUID
from urllib.parse import urlsplit
import zipfile

import sqlalchemy as sa
from src.infrastructure.database.base import Base
from src.infrastructure.config.settings import settings
from src.shared.exceptions.domain_exception import ValidationError

# Cada tabla incluida tiene un propietario conocido. Las tablas operativas,
# credenciales y contratos de plataforma no se importan como datos de negocio.
DIRECT = {
    'tenant_payment_methods','users','roles','categories','sizes','colors','seasons','collections','suppliers',
    'products','branches','cash_points','commerce_orders','commerce_order_returns',
    'commerce_promotions','commerce_garment_exchanges','reservations','user_branches',
    'sync_batches','sync_operations','sync_conflicts','virtual_tryon_assets',
}
CHILDREN = {
    'product_variants': ('product_id','products'), 'product_images': ('product_id','products'),
    'product_suppliers': ('product_id','products'), 'ar_assets': ('product_id','products'),
    'commerce_stock': ('branch_id','branches'), 'commerce_stock_movements': ('branch_id','branches'),
    'commerce_cart_items': ('user_id','users'), 'commerce_favorites': ('user_id','users'),
    'commerce_promotion_uses': ('promotion_id','commerce_promotions'),
    'promotion_targets': ('promotion_id','commerce_promotions'),
    'commerce_garment_exchange_lines': ('exchange_id','commerce_garment_exchanges'),
    'user_addresses': ('user_id','users'), 'user_roles': ('user_id','users'),
}
SECRET_FIELDS = {'password_hash','password','secret','access_token','refresh_token','api_key',
                 'mfa_secret','totp_secret','signing_secret','encrypted_secret'}
EXCLUDED = {'api_keys','audit_events','catalog_template_imports','catalog_templates',
    'commerce_webhook_events','devices','email_verification_tokens','integration_events','job_runs',
    'legal_acceptances','legal_documents','ml_anomalies','ml_customer_segments','ml_models',
    'ml_predictions','ml_training_runs','module_permissions','password_reset_tokens','plan_features',
    'plans','platform_backups','platform_modules','refresh_tokens','report_requests','stripe_events',
    'subscription_invoices','subscription_notices','subscriptions','support_sessions','tenant_limits',
    'tenant_modules','tenant_payment_accounts','tenant_signups','tryon_ai_jobs',
    'upgrade_requests','usage_alerts','webhook_deliveries','webhook_endpoints','tenant_backup_runs','tenant_backup_policies'}


def scrub(value):
    if isinstance(value, dict):
        return {key:scrub(item) for key,item in value.items() if key.lower() not in SECRET_FIELDS}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    return value


def encode(value):
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bytes):
        return {'__bytes__':base64.b64encode(value).decode('ascii')}
    raise TypeError('Tipo de dato no admitido en la copia.')


def canonical(value):
    return json.dumps(value, default=encode, sort_keys=True, separators=(',',':'), ensure_ascii=False).encode('utf-8')


def collect(connection, tenant_id):
    tables = Base.metadata.tables
    if set(tables)-(DIRECT|set(CHILDREN)|{'tenants','cities','permissions','role_permissions'}|EXCLUDED):
        raise ValidationError('Hay entidades nuevas pendientes de clasificar para el respaldo. Un operador debe actualizar su cobertura.')
    selected = {}
    def read(name, condition):
        result = [dict(row) for row in connection.execute(sa.select(tables[name]).where(condition).limit(20001)).mappings()]
        if len(result)>20000:
            raise ValidationError('Una entidad supera 20.000 registros. La copia requiere ampliar la capacidad del servicio.')
        selected[name] = result
    read('tenants', tables['tenants'].c.id == tenant_id)
    if not selected['tenants']:
        raise ValidationError('La empresa no está disponible.')
    for name in sorted(DIRECT):
        read(name, tables[name].c.tenant_id == tenant_id)
    remaining=dict(CHILDREN)
    while remaining:
        for name,(column,parent) in list(remaining.items()):
            if parent not in selected:
                continue
            read(name, tables[name].c[column].in_([row['id'] for row in selected[parent]]))
            del remaining[name]
    role_ids={row['role_id'] for row in selected['user_roles']}
    own_role_ids={row['id'] for row in selected['roles']}
    shared_roles=[dict(row) for row in connection.execute(sa.select(tables['roles']).where(
        tables['roles'].c.id.in_(role_ids-own_role_ids), tables['roles'].c.tenant_id.is_(None),
        tables['roles'].c.audience=='TENANT')).mappings()]
    selected['roles'] += shared_roles
    read('role_permissions', tables['role_permissions'].c.role_id.in_([row['id'] for row in selected['roles']]))
    permission_ids={row['permission_id'] for row in selected['role_permissions']}
    read('permissions', sa.and_(tables['permissions'].c.id.in_(permission_ids), tables['permissions'].c.scope=='tenant'))
    permitted={row['id'] for row in selected['permissions']}
    selected['role_permissions']=[row for row in selected['role_permissions'] if row['permission_id'] in permitted]
    read('cities', tables['cities'].c.id.in_({row['city_id'] for row in selected['branches']}))
    if sum(map(len,selected.values()))>50000:
        raise ValidationError('La empresa supera la capacidad de 50.000 registros por copia.')
    # Validar todas las relaciones: no incorporar la fila de otra empresa para
    # satisfacer una FK. Solo se omite la atribución opcional a actores externos.
    removed_references=0
    for name,rows in selected.items():
        for row in rows:
            for column in tables[name].c:
                for foreign in column.foreign_keys:
                    value=row.get(column.name)
                    if value is None:
                        continue
                    parent=foreign.column.table.name
                    allowed={str(item.get(foreign.column.name)) for item in selected.get(parent,[])}
                    if str(value) in allowed:
                        continue
                    if parent=='users' and column.nullable:
                        row[column.name]=None
                        removed_references+=1
                    else:
                        raise ValidationError('La copia detectó una relación incompleta o ajena a la empresa. Revisá la integridad antes de continuar.')
    data={name:[scrub(row) for row in rows] for name,rows in selected.items()}
    files={}
    external=[]
    media=Path(settings.media_storage_dir).resolve()
    base=settings.media_public_base_url.rstrip('/')+'/'
    urls=[row.get('url') for row in selected['product_images']]
    urls += [row.get(key) for row in selected['tenants'] for key in ('logo_url','banner_url')]
    urls += [row.get('qr_image_url') for row in selected['tenant_payment_methods']]
    file_bytes=0
    for image_url in urls:
        url=str(image_url or '')
        if not url.startswith(base):
            if url: external.append(url)
            continue
        filename=urlsplit(url).path.rsplit('/',1)[-1]
        if not re.fullmatch(r'[0-9a-f]{32}\.webp',filename):
            raise ValidationError('Una imagen propia tiene una referencia no admitida.')
        path=media/filename
        if not path.is_file():
            raise ValidationError('Falta una imagen propia. La copia no puede darse por completa.')
        if path.stat().st_size > settings.tenant_backup_max_mb*1024*1024:
            raise ValidationError('Una imagen supera la capacidad de la copia.')
        if filename in files:
            continue
        file_bytes += path.stat().st_size
        if file_bytes*4//3 > settings.tenant_backup_max_mb*1024*1024:
            raise ValidationError('Las imágenes de la empresa superan la capacidad configurada de la copia.')
        raw=path.read_bytes()
        files[filename]={'data':base64.b64encode(raw).decode('ascii'),'sha256':sha256(raw).hexdigest()}
    payload={'data':data,'files':files}
    digest=sha256(canonical(payload)).hexdigest()
    return {'manifest':{'schema_contract':schema_contract(),'format':'fashionstore-business-v1','tenant_id':str(tenant_id),
                        'created_at':datetime.now(timezone.utc).isoformat(),'sha256':digest,
                        'rows':{name:len(rows) for name,rows in data.items()},
                        'external_images':sorted(set(external)), 'own_images':len(files),
                        'omitted_actor_references':removed_references,
                        'excluded_tables':sorted(set(tables)-set(selected)),
                        'scope':'Datos de negocio y catálogo. Excluye credenciales, contratos de plataforma, integraciones y modelos regenerables. Las imágenes externas se conservan como referencias.',
                        'identity_policy':'Las cuentas restauradas quedan inactivas y necesitan activación segura.'},
            **payload}


def typed_row(table, row):
    result={}
    for key,value in row.items():
        if key not in table.c:
            raise ValidationError('El archivo no coincide con la estructura admitida.')
        kind=table.c[key].type
        if value is not None:
            if isinstance(kind,sa.Uuid): value=UUID(value)
            elif isinstance(kind,sa.DateTime): value=datetime.fromisoformat(value)
            elif isinstance(kind,sa.Date): value=date.fromisoformat(value)
            elif isinstance(kind,sa.Numeric): value=Decimal(value)
            elif isinstance(kind,sa.LargeBinary): value=base64.b64decode(value['__bytes__'],validate=True)
        result[key]=value
    if table.name=='users':
        result.update(password_hash='!backup-inactive',is_active=False,is_verified=False,must_change_password=True)
    return result


def restore_into_empty(connection, package):
    validate(package)
    allowed=set(DIRECT)|set(CHILDREN)|{'tenants','cities','permissions','role_permissions'}
    if set(package['data'])-allowed:
        raise ValidationError('El archivo contiene entidades no autorizadas.')
    if any(connection.scalar(sa.select(sa.func.count()).select_from(table)) for table in Base.metadata.sorted_tables):
        raise ValidationError('El ensayo de restauración requiere una base vacía.')
    if connection.dialect.name=='sqlite':
        connection.exec_driver_sql('PRAGMA defer_foreign_keys=ON')
    for table in Base.metadata.sorted_tables:
        for row in package['data'].get(table.name,[]):
            connection.execute(table.insert().values(**typed_row(table,row)))
    if connection.dialect.name=='sqlite' and connection.exec_driver_sql('PRAGMA foreign_key_check').fetchall():
        raise ValidationError('La restauración no conserva las relaciones de los datos.')


def schema_contract():
    return sha256(canonical({table.name:[(col.name,str(col.type),col.nullable) for col in table.columns]
                            for table in Base.metadata.sorted_tables})).hexdigest()


def validate(package):
    manifest=package['manifest']
    required=set(DIRECT)|set(CHILDREN)|{'tenants','cities','permissions','role_permissions'}
    if manifest.get('schema_contract') != schema_contract():
        raise ValidationError('La copia debe restaurarse con la misma versión de estructura de FashionStore.')
    if set(package['data']) != required or set(manifest['rows']) != required or sum(map(len,package['data'].values()))>50000:
        raise ValidationError('La copia no contiene todas las entidades requeridas.')
    if manifest['format']!='fashionstore-business-v1' or manifest['sha256']!=sha256(canonical({'data':package['data'],'files':package['files']})).hexdigest():
        raise ValidationError('La copia está incompleta o fue modificada.')
    tenant=str(manifest['tenant_id'])
    for name,rows in package['data'].items():
        if name not in Base.metadata.tables or len(rows)!=manifest['rows'].get(name):
            raise ValidationError('Las cantidades no coinciden con el manifiesto.')
        if name=='tenants' and (len(rows)!=1 or str(rows[0]['id'])!=tenant):
            raise ValidationError('La copia no corresponde a una sola empresa.')
        for row in rows:
            if row.get('tenant_id') is not None and str(row['tenant_id'])!=tenant:
                raise ValidationError('El archivo contiene datos de otra empresa.')
    for name,entry in package['files'].items():
        if not re.fullmatch(r'[0-9a-f]{32}\.webp',name) or sha256(base64.b64decode(entry['data'],validate=True)).hexdigest()!=entry['sha256']:
            raise ValidationError('Una imagen de la copia no superó la comprobación.')


def rehearse(package):
    start=monotonic()
    engine=sa.create_engine('sqlite+pysqlite:///:memory:')
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql('PRAGMA foreign_keys=ON')
            Base.metadata.create_all(connection)
            connection.commit()
            with connection.begin():
                restore_into_empty(connection,package)
        return {'restored':True,'target':'SQLite aislado con el esquema de la aplicación',
                'duration_seconds':round(monotonic()-start,3),
                'rows':package['manifest']['rows'],'own_images':package['manifest']['own_images'],
                'external_images':len(package['manifest']['external_images']),
                'note':'Ensayo de datos de negocio. No sustituye una recuperación global de PostgreSQL ni reactiva credenciales.'}
    finally:
        engine.dispose()


def downloadable(package):
    validate(package)
    output=BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json',canonical(package['manifest']))
        archive.writestr('data.json',canonical(package['data']))
        for name,entry in package['files'].items():
            archive.writestr('images/'+name,base64.b64decode(entry['data'],validate=True))
    return output.getvalue()
