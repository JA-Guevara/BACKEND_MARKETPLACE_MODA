from datetime import date, datetime, timedelta, timezone
from sqlalchemy import select
from src.auth.infrastructure.http.schemas import TenantSummary
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.plataforma_saas.application.plan_guard import PlanGuard
from src.plataforma_saas.domain.estados import dias_restantes
from src.plataforma_saas.domain.exceptions import PlanLimitExceededError, TenantNotFoundError
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel
from src.plataforma_saas.infrastructure.repositories.saas_repository import SaasRepository
from src.plataforma_saas.web.schemas.subscriptions import SubscriptionDetail, SubscriptionUsage, SubscriptionView
from src.shared.exceptions.domain_exception import ConflictError, NotFoundError


class SubscriptionService:
    def __init__(self, db, actor):
        self.db, self.actor = db, actor
        self.guard, self.repository = PlanGuard(db), SaasRepository(db)

    def _view(self, row):
        return SubscriptionView(id=row.id, plan_code=row.plan.code, plan_name=row.plan.name, start_date=row.start_date,
            end_date=row.end_date, status=row.status, days_left=dias_restantes(row.end_date, date.today()), reason=row.reason,
            reference_price=row.plan.reference_price)

    def detalle(self, tenant_id):
        tenant = self.repository.get_tenant(tenant_id)
        if not tenant:
            raise TenantNotFoundError()
        current = self.guard.vigente(tenant_id)
        summary = self.guard.resumen(tenant_id)
        history = self.db.scalars(select(SubscriptionModel).where(SubscriptionModel.tenant_id == tenant_id, SubscriptionModel.closed_at.is_not(None)).order_by(SubscriptionModel.closed_at.desc())).all()
        result = SubscriptionDetail(tenant=TenantSummary.model_validate(tenant), current=self._view(current),
            usage=SubscriptionUsage(active_branches=self.repository.count_active_branches(tenant_id), max_active_branches=summary.limits.get("max_active_branches", 0)),
            features=summary.features, limits=summary.limits, history=[self._view(row) for row in history])
        # GET puede materializar el vencimiento; confirmar antes de cerrar Session.
        self.db.commit()
        return result

    def _replace(self, previous, *, plan_id, start_date, end_date, status, reason, action):
        previous.closed_at = datetime.now(timezone.utc)
        self.db.flush()
        row = SubscriptionModel(tenant_id=previous.tenant_id, plan_id=plan_id, start_date=start_date, end_date=end_date,
            status=status, reason=reason, changed_by=self.actor.id)
        self.repository.add(row)
        RecordAuditEvent(self.db).execute(actor_user_id=self.actor.id, action=action, entity_type="tenant", entity_id=str(previous.tenant_id),
            description=reason or "Suscripción renovada.", metadata={"previous_subscription_id": str(previous.id), "subscription_id": str(row.id), "status": status})
        self.db.commit()
        return self.detalle(previous.tenant_id)

    def cambiar_plan(self, tenant_id, data):
        self.guard.bloquear_empresa(tenant_id)
        current = self.guard.vigente(tenant_id)
        plan = self.repository.get_plan_by_code(data.plan_code)
        if not plan or not plan.is_active:
            raise NotFoundError("Plan no disponible.")
        used = self.repository.count_active_branches(tenant_id)
        limit = next((feature.limit_value for feature in plan.features if feature.feature_code == "max_active_branches"), 0) or 0
        if used > limit:
            raise PlanLimitExceededError(details={"active_branches": used, "limit": limit, "must_deactivate": used-limit})
        start = data.start_date or date.today()
        return self._replace(current, plan_id=plan.id, start_date=start, end_date=start+timedelta(days=plan.duration_days-1),
            status="ACTIVA", reason=data.reason, action="subscriptions.plan_changed")

    def renovar(self, tenant_id, data):
        self.guard.bloquear_empresa(tenant_id)
        current = self.guard.vigente(tenant_id)
        start = max(date.today(), current.end_date)+timedelta(days=1)
        return self._replace(current, plan_id=current.plan_id, start_date=start,
            end_date=start+timedelta(days=current.plan.duration_days-1), status="ACTIVA", reason=data.reason, action="subscriptions.renewed")

    def cambiar_estado(self, tenant_id, data):
        self.guard.bloquear_empresa(tenant_id)
        current = self.guard.vigente(tenant_id)
        if data.status == "ACTIVA" and current.end_date < date.today():
            raise ConflictError("La suscripción venció; renueva antes de activarla.")
        return self._replace(current, plan_id=current.plan_id, start_date=current.start_date, end_date=current.end_date,
            status=data.status, reason=data.reason, action="subscriptions.status_changed")
