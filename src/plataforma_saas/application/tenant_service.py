from datetime import date, timedelta, datetime, timezone
from math import ceil
from uuid import UUID
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from src.auth.application.services.auth_service import AuthService
from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.infrastructure.persistence.models.refresh_token import RefreshTokenModel
from src.auth.infrastructure.persistence.repositories.user_repository import UserRepository
from src.auth.domain.exceptions import EmailAlreadyExistsError
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.roles.infrastructure.persistence.models.role import RoleModel
from src.plataforma_saas.application.plan_guard import PlanGuard
from src.plataforma_saas.domain.exceptions import TenantNotFoundError, TenantSlugTakenError, TenantTaxIdTakenError
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.plataforma_saas.infrastructure.models.plan import PlanModel
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel
from src.plataforma_saas.infrastructure.repositories.saas_repository import SaasRepository
from src.plataforma_saas.web.schemas.tenants import TenantResponse, TenantStats, ActivityItem
from src.shared.exceptions.domain_exception import ConflictError, NotFoundError
from src.shared.responses.pagination import Page


class TenantService:
    def __init__(self, db: Session, actor: UserModel):
        self.db, self.actor = db, actor
        self.repository = SaasRepository(db)

    def _tenant(self, tenant_id):
        tenant = self.repository.get_tenant(tenant_id)
        if not tenant:
            raise TenantNotFoundError()
        return tenant

    def _response(self, tenant):
        response = TenantResponse.model_validate(tenant)
        subscription = self.repository.open_subscription(tenant.id)
        if subscription:
            summary = PlanGuard(self.db).resumen(tenant.id)
            response.plan_code, response.plan_name = summary.plan_code, summary.plan_name
            response.subscription_status, response.end_date = summary.status, summary.end_date
        response.active_branches = self.repository.count_active_branches(tenant.id)
        admin = self.db.scalar(select(UserModel).join(UserModel.roles).where(UserModel.tenant_id == tenant.id,
            RoleModel.code == "admin", UserModel.deleted_at.is_(None)).order_by(UserModel.created_at))
        if admin:
            response.admin_email, response.admin_password_set = admin.email, admin.is_verified
        return response

    def listar(self, *, search=None, status=None, plan_code=None, page=1, page_size=20, subscription_status=None, expiring_7d=False):
        query = select(TenantModel).outerjoin(SubscriptionModel, (SubscriptionModel.tenant_id == TenantModel.id) & SubscriptionModel.closed_at.is_(None)).outerjoin(PlanModel, PlanModel.id == SubscriptionModel.plan_id)
        if search:
            term = f"%{search.strip()}%"
            query = query.where(or_(TenantModel.trade_name.ilike(term), TenantModel.legal_name.ilike(term), TenantModel.tax_id.ilike(term), TenantModel.slug.ilike(term)))
        if status in ("ACTIVA", "INACTIVA"):
            query = query.where(TenantModel.status == status)
        elif status:
            subscription_status = status
        if subscription_status == "VENCIDA":
            query = query.where(or_(SubscriptionModel.status == "VENCIDA", (SubscriptionModel.status == "ACTIVA") & (SubscriptionModel.end_date < date.today())))
        elif subscription_status:
            query = query.where(SubscriptionModel.status == subscription_status)
        if plan_code:
            query = query.where(PlanModel.code == plan_code)
        if expiring_7d:
            query = query.where(SubscriptionModel.status == "ACTIVA", SubscriptionModel.end_date.between(date.today(), date.today()+timedelta(days=7)))
        total = self.db.scalar(select(func.count()).select_from(query.subquery())) or 0
        tenants = self.db.scalars(query.order_by(TenantModel.created_at.desc()).offset((page-1)*page_size).limit(page_size)).all()
        result = Page(items=[self._response(t) for t in tenants], total=total, page=page, page_size=page_size, pages=ceil(total/page_size))
        self.db.commit()
        return result

    def estadisticas(self):
        rows = self.db.execute(select(SubscriptionModel.status, SubscriptionModel.end_date, PlanModel.code).join(PlanModel).where(SubscriptionModel.closed_at.is_(None))).all()
        today = date.today()
        return TenantStats(active=self.db.scalar(select(func.count()).select_from(TenantModel).where(TenantModel.status == "ACTIVA")) or 0,
            professional=sum(code == "PROFESIONAL" for _, _, code in rows),
            expiring_7d=sum(status == "ACTIVA" and today <= end <= today+timedelta(days=7) for status, end, _ in rows),
            suspended=sum(status == "SUSPENDIDA" for status, _, _ in rows))

    def obtener(self, tenant_id):
        response = self._response(self._tenant(tenant_id))
        self.db.commit()
        return response

    def _audit(self, tenant, action, description):
        RecordAuditEvent(self.db).execute(actor_user_id=self.actor.id, action=action, entity_type="tenant", entity_id=str(tenant.id), description=description)

    def registrar(self, data):
        if self.db.scalar(select(TenantModel.id).where(TenantModel.tax_id == data.tax_id)):
            raise TenantTaxIdTakenError()
        if self.repository.find_tenant_by_slug(data.slug):
            raise TenantSlugTakenError()
        if UserRepository(self.db).get_by_email(str(data.admin.email), include_deleted=True):
            raise EmailAlreadyExistsError()
        plan = self.repository.get_plan_by_code(data.plan_code)
        if not plan or not plan.is_active:
            raise NotFoundError("Plan no disponible.")
        role = self.db.scalar(select(RoleModel).where(RoleModel.code == "admin"))
        if not role:
            raise ConflictError("El rol de administrador no está configurado.")
        auth = AuthService(self.db)
        tenant = TenantModel(**data.model_dump(exclude={"admin", "plan_code", "start_date"}), status="ACTIVA")
        try:
            self.repository.add(tenant)
            admin = UserModel(tenant_id=tenant.id, email=str(data.admin.email).lower(), first_name=data.admin.first_name,
                last_name=data.admin.last_name, password_hash=auth.create_unusable_password_hash(), roles=[role], is_verified=False)
            self.repository.add(admin)
            start = data.start_date or date.today()
            self.repository.add(SubscriptionModel(tenant_id=tenant.id, plan_id=plan.id, start_date=start,
                end_date=start+timedelta(days=plan.duration_days-1), status="ACTIVA", changed_by=self.actor.id))
            token = auth.issue_password_setup_token(admin)
            self._audit(tenant, "tenants.created", "Empresa y administrador inicial registrados.")
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            if self.db.scalar(select(TenantModel.id).where(TenantModel.tax_id == data.tax_id)):
                raise TenantTaxIdTakenError() from exc
            if self.repository.find_tenant_by_slug(data.slug):
                raise TenantSlugTakenError() from exc
            raise EmailAlreadyExistsError() from exc
        self._send_invitation(auth, admin, token, tenant)
        return tenant

    def _send_invitation(self, auth, admin, token, tenant):
        try:
            sent = auth.email.send_tenant_invitation(admin.email, token, tenant.trade_name)
        except Exception:
            # El alta ya está confirmada; el operador puede reenviar el enlace.
            sent = False
        RecordAuditEvent(self.db).execute(actor_user_id=self.actor.id,
            action='tenants.invitation_sent' if sent else 'tenants.invitation_failed',
            entity_type='tenant', entity_id=str(tenant.id),
            description='Invitación enviada.' if sent else 'Invitación pendiente de entrega; puede reenviarse.',
            metadata={'delivered': bool(sent)})
        self.db.commit()
        return sent

    def actualizar(self, tenant_id, data):
        tenant = self._tenant(tenant_id)
        for key, value in data.model_dump(exclude_unset=True).items():
            if value is None and key != "phone":
                raise ConflictError("Los datos obligatorios no pueden quedar vacíos.")
            setattr(tenant, key, value)
        self._audit(tenant, "tenants.updated", "Datos de la empresa actualizados.")
        self.db.commit()
        return tenant

    def desactivar(self, tenant_id, reason):
        tenant = self._tenant(tenant_id)
        tenant.status, tenant.deactivation_reason = "INACTIVA", reason
        users = select(UserModel.id).where(UserModel.tenant_id == tenant_id)
        self.db.execute(update(RefreshTokenModel).where(RefreshTokenModel.user_id.in_(users), RefreshTokenModel.revoked_at.is_(None)).values(revoked_at=datetime.now(timezone.utc)))
        self._audit(tenant, "tenants.deactivated", f"Empresa desactivada: {reason}")
        self.db.commit()
        return tenant

    def activar(self, tenant_id):
        tenant = self._tenant(tenant_id)
        tenant.status, tenant.deactivation_reason = "ACTIVA", None
        self._audit(tenant, "tenants.activated", "Empresa reactivada.")
        self.db.commit()
        return tenant

    def reenviar_invitacion(self, tenant_id):
        tenant = self._tenant(tenant_id)
        admin = self.db.scalar(select(UserModel).join(UserModel.roles).where(UserModel.tenant_id == tenant_id, RoleModel.code == "admin", UserModel.deleted_at.is_(None)).order_by(UserModel.created_at))
        if not admin or admin.is_verified:
            raise ConflictError("El administrador ya activó su cuenta o no está disponible.")
        auth = AuthService(self.db)
        token = auth.issue_password_setup_token(admin)
        self._audit(tenant, "tenants.invitation_resent", "Nuevo enlace de activación solicitado.")
        self.db.commit()
        return self._send_invitation(auth, admin, token, tenant)

    def actividad(self, tenant_id, limit=20):
        self._tenant(tenant_id)
        rows = self.db.scalars(select(AuditEventModel).where(AuditEventModel.entity_type == "tenant", AuditEventModel.entity_id == str(tenant_id)).order_by(AuditEventModel.created_at.desc()).limit(limit))
        return [ActivityItem.model_validate(row) for row in rows]
