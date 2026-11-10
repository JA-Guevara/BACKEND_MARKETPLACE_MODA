from datetime import datetime, timedelta, timezone
import gzip
from hashlib import sha256
import json
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session
from src.infrastructure.config.settings import settings
from src.infrastructure.database.session import set_rls_context
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.plataforma_saas.infrastructure.models.tenant_backup import TenantBackupPolicy, TenantBackupRun
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel
from src.plataforma_saas.application import tenant_backup_archive as archive
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.shared.exceptions.domain_exception import ConflictError, NotFoundError, ValidationError


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def cipher():
    secret=settings.tenant_backup_encryption_key
    if not secret or not secret.get_secret_value().strip():
        raise ConflictError('Un operador debe configurar TENANT_BACKUP_ENCRYPTION_KEY para custodiar las copias.',code='backup_config_missing')
    try:
        return Fernet(secret.get_secret_value().encode())
    except (ValueError, TypeError):
        raise ConflictError('La clave de custodia de copias necesita una configuración válida.',code='backup_config_missing') from None


def next_execution(policy, now):
    zone=ZoneInfo(policy.timezone)
    local=utc(now).astimezone(zone)
    candidate=local.replace(hour=policy.hour,minute=0,second=0,microsecond=0)
    if candidate<=local:
        candidate+=timedelta(days=7 if policy.frequency=='weekly' else 1)
    return candidate.astimezone(timezone.utc)


def public_run(run):
    return {key:getattr(run,key) for key in ('id','kind','status','created_at','started_at','finished_at','sha256','size_bytes','report','error')}


class TenantBackupService:
    def __init__(self, db, tenant_id, actor=None):
        self.db,self.tenant_id,self.actor=db,tenant_id,actor

    def policy(self):
        return self.db.scalar(select(TenantBackupPolicy).where(TenantBackupPolicy.tenant_id==self.tenant_id))

    @classmethod
    def all_tenants_overview(cls, db, actor=None, search=None, policy_filter="all", page=1, page_size=20):
        configured = True
        try:
            cipher()
        except ConflictError:
            configured = False

        total_tenants = db.scalar(select(func.count(TenantModel.id)).where(TenantModel.is_sandbox.is_(False))) or 0
        tenants_with_policy = db.scalar(
            select(func.count(TenantBackupPolicy.id))
            .join(TenantModel, TenantModel.id == TenantBackupPolicy.tenant_id)
            .where(TenantModel.is_sandbox.is_(False), TenantBackupPolicy.enabled.is_(True))
        ) or 0
        total_backups = db.scalar(
            select(func.count(TenantBackupRun.id))
            .join(TenantModel, TenantModel.id == TenantBackupRun.tenant_id)
            .where(TenantModel.is_sandbox.is_(False))
        ) or 0
        verified_backups = db.scalar(
            select(func.count(TenantBackupRun.id))
            .join(TenantModel, TenantModel.id == TenantBackupRun.tenant_id)
            .where(TenantModel.is_sandbox.is_(False), TenantBackupRun.status == "verified")
        ) or 0
        total_storage_bytes = db.scalar(
            select(func.coalesce(func.sum(TenantBackupRun.size_bytes), 0))
            .join(TenantModel, TenantModel.id == TenantBackupRun.tenant_id)
            .where(TenantModel.is_sandbox.is_(False))
        ) or 0

        query = select(TenantModel).where(TenantModel.is_sandbox.is_(False))
        if search and search.strip():
            term = f"%{search.strip()}%"
            query = query.where(or_(TenantModel.trade_name.ilike(term), TenantModel.slug.ilike(term), TenantModel.legal_name.ilike(term)))

        if policy_filter == "enabled":
            query = query.join(TenantBackupPolicy, TenantBackupPolicy.tenant_id == TenantModel.id).where(TenantBackupPolicy.enabled.is_(True))
        elif policy_filter == "disabled":
            query = query.outerjoin(TenantBackupPolicy, TenantBackupPolicy.tenant_id == TenantModel.id).where(
                or_(TenantBackupPolicy.id.is_(None), TenantBackupPolicy.enabled.is_(False))
            )

        total_filtered = db.scalar(select(func.count()).select_from(query.subquery())) or 0
        tenants = db.scalars(query.order_by(TenantModel.trade_name.asc()).offset((page - 1) * page_size).limit(page_size)).all()

        items = []
        for t in tenants:
            pol = db.scalar(select(TenantBackupPolicy).where(TenantBackupPolicy.tenant_id == t.id))
            last_run = db.scalar(
                select(TenantBackupRun)
                .where(TenantBackupRun.tenant_id == t.id)
                .order_by(TenantBackupRun.created_at.desc(), TenantBackupRun.id.desc())
                .limit(1)
            )
            runs_count = db.scalar(select(func.count()).select_from(TenantBackupRun).where(TenantBackupRun.tenant_id == t.id)) or 0
            runs_size = db.scalar(select(func.coalesce(func.sum(TenantBackupRun.size_bytes), 0)).where(TenantBackupRun.tenant_id == t.id)) or 0

            plan_code = "SIN_PLAN"
            sub = db.scalar(
                select(SubscriptionModel)
                .where(SubscriptionModel.tenant_id == t.id, SubscriptionModel.closed_at.is_(None))
                .order_by(SubscriptionModel.created_at.desc())
                .limit(1)
            )
            if sub and sub.plan:
                plan_code = sub.plan.code

            items.append({
                "tenant_id": str(t.id),
                "trade_name": t.trade_name,
                "legal_name": t.legal_name,
                "slug": t.slug,
                "status": t.status,
                "plan_code": plan_code,
                "policy": {
                    "enabled": pol.enabled if pol else False,
                    "frequency": pol.frequency if pol else "daily",
                    "hour": pol.hour if pol else 3,
                    "timezone": pol.timezone if pol else "America/La_Paz",
                    "retention": pol.retention if pol else 7,
                    "next_run_at": pol.next_run_at.isoformat() if (pol and pol.next_run_at) else None,
                },
                "last_backup": public_run(last_run) if last_run else None,
                "total_backups": runs_count,
                "total_size_bytes": runs_size,
            })

        return {
            "summary": {
                "total_tenants": total_tenants,
                "tenants_with_policy": tenants_with_policy,
                "total_backups": total_backups,
                "verified_backups": verified_backups,
                "total_storage_bytes": total_storage_bytes,
                "configured": configured,
            },
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total_filtered,
        }

    def status(self, page=1):
        tenant=self.db.get(TenantModel,self.tenant_id)
        if tenant is None:
            raise NotFoundError('Empresa no encontrada.')
        policy=self.policy()
        configured=True
        try: cipher()
        except ConflictError: configured=False
        query=select(TenantBackupRun).where(TenantBackupRun.tenant_id==self.tenant_id)
        total=self.db.scalar(select(func.count()).select_from(TenantBackupRun).where(TenantBackupRun.tenant_id==self.tenant_id))
        runs=self.db.scalars(query.order_by(TenantBackupRun.created_at.desc(),TenantBackupRun.id.desc()).offset((page-1)*20).limit(20)).all()
        return {'tenant':{'id':tenant.id,'name':tenant.trade_name},'configured':configured,
                'configuration_note':None if configured else 'Falta configurar la clave de custodia del servidor. Los datos existentes no se modifican.',
                'storage_note':'Copias lógicas cifradas en PostgreSQL. Descargá una copia fuera de la plataforma para protegerte también frente a la pérdida de la base.',
                'policy':{'enabled':policy.enabled if policy else False,'frequency':policy.frequency if policy else 'daily',
                          'hour':policy.hour if policy else 3,'timezone':policy.timezone if policy else 'America/La_Paz',
                          'retention':policy.retention if policy else 7,'next_run_at':policy.next_run_at if policy else None},
                'items':[public_run(run) for run in runs],'total':total,'page':page,'page_size':20}

    def audit(self, action, entity_id, detail):
        RecordAuditEvent(self.db).execute(action=action,entity_type='tenant_backup',entity_id=str(entity_id),
            tenant_id=self.tenant_id,actor_user_id=self.actor.id if self.actor else None,
            description=detail)

    def configure(self, data):
        if data['enabled']: cipher()
        self.db.scalar(select(TenantModel).where(TenantModel.id==self.tenant_id).with_for_update())
        policy=self.policy()
        if not policy:
            policy=TenantBackupPolicy(tenant_id=self.tenant_id)
            self.db.add(policy)
        for key,value in data.items(): setattr(policy,key,value)
        policy.next_run_at=next_execution(policy,datetime.now(timezone.utc)) if policy.enabled else None
        self.audit('tenant.backup_policy_updated',self.tenant_id,'Se modificó la programación de copias de la empresa.')
        self.db.commit()
        return self.status()

    def enqueue(self, request_key, kind='manual', commit=True):
        cipher()
        tenant=self.db.scalar(select(TenantModel).where(TenantModel.id==self.tenant_id).with_for_update())
        if tenant is None: raise NotFoundError('Empresa no encontrada.')
        prior=self.db.scalar(select(TenantBackupRun).where(TenantBackupRun.tenant_id==self.tenant_id,TenantBackupRun.request_key==request_key))
        if prior: return prior
        active=self.db.scalar(select(func.count()).select_from(TenantBackupRun).where(
            TenantBackupRun.tenant_id==self.tenant_id,TenantBackupRun.status.in_(['queued','running'])))
        recent=self.db.scalar(select(func.count()).select_from(TenantBackupRun).where(
            TenantBackupRun.tenant_id==self.tenant_id,TenantBackupRun.created_at>=datetime.now(timezone.utc)-timedelta(days=1)))
        if active>=2 or recent>=12:
            raise ConflictError('La empresa ya tiene copias pendientes o alcanzó sus 12 solicitudes diarias. Esperá a que terminen.')
        run=TenantBackupRun(id=uuid4(),tenant_id=self.tenant_id,requested_by=self.actor.id if self.actor else None,
                            request_key=request_key,kind=kind,status='queued',size_bytes=0)
        self.db.add(run)
        self.audit('tenant.backup_requested',run.id,'Se solicitó una copia de negocio de la empresa.')
        if commit: self.db.commit()
        else: self.db.flush()
        return run

    def run(self, run_id):
        run=self.db.scalar(select(TenantBackupRun).where(TenantBackupRun.id==run_id,TenantBackupRun.tenant_id==self.tenant_id))
        if run is None: raise NotFoundError('Copia no encontrada.')
        return run

    def download(self, run_id):
        run=self.run(run_id)
        if run.status!='verified' or not run.artifact:
            raise ConflictError('La copia todavía no está disponible o venció su conservación.')
        try:
            raw=gzip.decompress(cipher().decrypt(run.artifact))
        except (InvalidToken,OSError):
            raise ConflictError('No se pudo abrir la copia con la clave de custodia. Conservá la clave original o revisá el archivo.') from None
        if sha256(raw).hexdigest()!=run.sha256:
            raise ValidationError('La copia no superó la comprobación de integridad.')
        package=json.loads(raw)
        if package['manifest']['tenant_id']!=str(self.tenant_id):
            raise ValidationError('El contenido de la copia no corresponde a esta empresa.')
        self.audit('tenant.backup_downloaded',run.id,'Se descargó una copia de datos de negocio de la empresa.')
        payload=archive.downloadable(package)
        self.db.commit()
        return payload


def process_backups(factory, limit=2, now=None):
    """Trabajador durable: cola persistida, reclamación exclusiva y recuperación de interrupciones."""
    try: key=cipher()
    except ConflictError: return 0
    now=utc(now or datetime.now(timezone.utc))
    with factory() as db:
        set_rls_context(db,is_platform=True)
        policies=db.scalars(select(TenantBackupPolicy).where(TenantBackupPolicy.enabled.is_(True),TenantBackupPolicy.next_run_at<=now)
                           .order_by(TenantBackupPolicy.next_run_at).limit(50).with_for_update(skip_locked=True)).all()
        for policy in policies:
            try:
                with db.begin_nested():
                    TenantBackupService(db,policy.tenant_id).enqueue('schedule:'+utc(policy.next_run_at).isoformat(),kind='scheduled',commit=False)
                    policy.next_run_at=next_execution(policy,now)
            except ConflictError:
                continue
        db.commit()
    processed=0
    for _ in range(limit):
        with factory() as db:
            set_rls_context(db,is_platform=True)
            run=db.scalar(select(TenantBackupRun).where(or_(TenantBackupRun.status=='queued',
                (TenantBackupRun.status=='running') & (TenantBackupRun.lease_until<now)))
                .order_by(TenantBackupRun.created_at).limit(1).with_for_update(skip_locked=True))
            if run is None: break
            run_id,tenant_id=run.id,run.tenant_id
            lease_token=str(uuid4())
            run.lease_token=lease_token
            run.status='running';run.started_at=now;run.lease_until=now+timedelta(minutes=15)
            db.commit()
        try:
            engine=db.get_bind()
            with engine.connect() as connection:
                if connection.dialect.name=='postgresql':
                    connection=connection.execution_options(isolation_level='REPEATABLE READ')
                with connection.begin():
                    if connection.dialect.name=='postgresql':
                        connection.execute(text('SET TRANSACTION READ ONLY'))
                        connection.execute(text("SELECT set_config('app.tenant_id',:tenant,true),set_config('app.platform','0',true)"),{'tenant':str(tenant_id)})
                    package=archive.collect(connection,tenant_id)
            raw=archive.canonical(package)
            if len(raw)>settings.tenant_backup_max_mb*1024*1024:
                raise ValidationError('La copia excede el tamaño permitido. No se guardó un archivo incompleto.')
            normalized=json.loads(raw)
            report=archive.rehearse(normalized)
            with factory() as saved:
                set_rls_context(saved,is_platform=True)
                run=saved.get(TenantBackupRun,run_id)
                if run.lease_token!=lease_token or run.status!='running': continue
                run.artifact=key.encrypt(gzip.compress(raw));run.sha256=sha256(raw).hexdigest()
                run.size_bytes=len(run.artifact);run.report=report;run.status='verified'
                run.finished_at=datetime.now(timezone.utc);run.lease_until=None;run.error=None
                TenantBackupService(saved,tenant_id).audit('tenant.backup_verified',run.id,'Se verificó una copia de negocio mediante restauración aislada.')
                policy=saved.scalar(select(TenantBackupPolicy).where(TenantBackupPolicy.tenant_id==tenant_id))
                old=saved.scalars(select(TenantBackupRun).where(TenantBackupRun.tenant_id==tenant_id,TenantBackupRun.status=='verified')
                    .order_by(TenantBackupRun.finished_at.desc()).with_for_update()).all()
                # El nuevo archivo todavía no ha sido incluido por autoflush=False.
                old=[item for item in old if item.id!=run_id]
                for expired in old[(policy.retention if policy else 7)-1:]:
                    expired.artifact=None;expired.status='expired'
                saved.commit()
        except Exception as error:
            with factory() as failed:
                set_rls_context(failed,is_platform=True)
                run=failed.get(TenantBackupRun,run_id)
                if run.lease_token!=lease_token or run.status!='running': continue
                run.status='failed';run.finished_at=datetime.now(timezone.utc);run.lease_until=None
                run.error=error.message if isinstance(error,ValidationError) else 'La copia no pudo completarse. Revisá integridad, espacio y configuración; los datos de negocio no se modificaron.'
                failed.commit()
        processed+=1
    return processed
