from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import select

from src.plataforma_saas.application.entitlement_service import EntitlementService
from src.plataforma_saas.domain.estados import FUNCIONES, LIMITES, dias_restantes, estado_efectivo
from src.plataforma_saas.domain.exceptions import FeatureNotInPlanError, PlanLimitExceededError, SubscriptionInactiveError
from src.plataforma_saas.infrastructure.models.module import TenantLimitModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.plataforma_saas.infrastructure.repositories.saas_repository import SaasRepository


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
        self.exigir_activa(tenant_id)
        if not EntitlementService(self.db).tiene(tenant_id, feature_code):
            raise FeatureNotInPlanError(details={"module_code": feature_code})

    def bloquear_empresa(self, tenant_id: UUID):
        # El bloqueo de la empresa serializa altas/reactivaciones y cambios de plan.
        self.db.scalar(select(TenantModel).where(TenantModel.id == tenant_id).with_for_update())

    def exigir_limite(self, tenant_id: UUID, limit_code: str, uso_actual: int):
        subscription = self.exigir_activa(tenant_id)
        limits, sources = self._limites_efectivos(tenant_id, subscription)
        limit = limits.get(limit_code)
        source = sources.get(limit_code, "PLAN")
        if limit is None or uso_actual >= limit:
            raise PlanLimitExceededError(details={"limit_code": limit_code, "limit": limit, "current": uso_actual, "source": source})

    def _limites_efectivos(self, tenant_id: UUID, subscription):
        limits = {feature.feature_code: feature.limit_value for feature in subscription.plan.features
                  if feature.feature_code in LIMITES and feature.limit_value is not None}
        sources = {code: "PLAN" for code in limits}
        now = datetime.now(timezone.utc)
        overrides = self.db.scalars(select(TenantLimitModel).where(
            TenantLimitModel.tenant_id == tenant_id, TenantLimitModel.revoked_at.is_(None))).all()
        for override in overrides:
            expiry = override.expires_at
            if expiry is not None and expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if override.limit_code in LIMITES and (expiry is None or expiry > now):
                limits[override.limit_code] = override.value
                sources[override.limit_code] = "EMPRESA"
        return limits, sources

    def resumen(self, tenant_id: UUID):
        from src.auth.infrastructure.http.schemas import ModuleSummary, SubscriptionSummary

        subscription = self.vigente(tenant_id)
        entitlement_svc = EntitlementService(self.db)
        modulos_map = entitlement_svc.modulos(tenant_id)
        catalogo = entitlement_svc._get_catalog()

        all_codes = set(FUNCIONES).union(catalogo.keys())
        features = {c: entitlement_svc.tiene(tenant_id, c) for c in all_codes}

        modules = [
            ModuleSummary(
                code=m.code,
                name=catalogo.get(m.code, {}).get("name", m.code),
                origin=m.origen,
                expires_at=m.expira,
            )
            for m in modulos_map.values()
        ]

        limits, _ = self._limites_efectivos(tenant_id, subscription)
        return SubscriptionSummary(
            plan_code=subscription.plan.code,
            plan_name=subscription.plan.name,
            status=subscription.status,
            start_date=subscription.start_date,
            end_date=subscription.end_date,
            days_left=dias_restantes(subscription.end_date, date.today()),
            features=features,
            modules=modules,
            limits=limits,
        )
