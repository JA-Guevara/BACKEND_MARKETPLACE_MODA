from datetime import date
from uuid import UUID
from sqlalchemy import select
from src.plataforma_saas.domain.estados import FUNCIONES, LIMITES, dias_restantes, estado_efectivo
from src.plataforma_saas.domain.exceptions import FeatureNotInPlanError, PlanLimitExceededError, SubscriptionInactiveError
from src.plataforma_saas.infrastructure.repositories.saas_repository import SaasRepository
from src.plataforma_saas.infrastructure.models.tenant import TenantModel


class PlanGuard:
    def __init__(self, db):
        self.db = db
        self.repository = SaasRepository(db)

    def vigente(self, tenant_id: UUID):
        subscription = self.repository.open_subscription(tenant_id)
        if not subscription:
            raise SubscriptionInactiveError()
        effective = estado_efectivo(subscription.status, subscription.end_date, date.today())
        if subscription.status != effective:
            subscription.status = effective.value
            self.db.flush()
        return subscription

    def exigir_activa(self, tenant_id: UUID):
        subscription = self.vigente(tenant_id)
        if subscription.status != "ACTIVA":
            raise SubscriptionInactiveError()
        return subscription

    def exigir_funcion(self, tenant_id: UUID, feature_code: str):
        subscription = self.exigir_activa(tenant_id)
        if not any(f.feature_code == feature_code and f.enabled for f in subscription.plan.features):
            raise FeatureNotInPlanError()

    def bloquear_empresa(self, tenant_id: UUID):
        # El bloqueo de la empresa serializa altas/reactivaciones y cambios de plan.
        self.db.scalar(select(TenantModel).where(TenantModel.id == tenant_id).with_for_update())

    def exigir_limite(self, tenant_id: UUID, limit_code: str, uso_actual: int):
        subscription = self.exigir_activa(tenant_id)
        limit = next((f.limit_value for f in subscription.plan.features if f.feature_code == limit_code), None)
        if limit is None or uso_actual >= limit:
            raise PlanLimitExceededError(details={"limit_code": limit_code, "limit": limit, "current": uso_actual})

    def resumen(self, tenant_id: UUID):
        from src.auth.infrastructure.http.schemas import SubscriptionSummary
        subscription = self.vigente(tenant_id)
        by_code = {f.feature_code: f for f in subscription.plan.features}
        return SubscriptionSummary(plan_code=subscription.plan.code, plan_name=subscription.plan.name,
            status=subscription.status, start_date=subscription.start_date, end_date=subscription.end_date,
            days_left=dias_restantes(subscription.end_date, date.today()),
            features={c: bool(by_code[c].enabled) if c in by_code else False for c in FUNCIONES},
            limits={c: by_code[c].limit_value for c in LIMITES if c in by_code and by_code[c].limit_value is not None})
