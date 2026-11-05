from sqlalchemy import func, select

from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.plataforma_saas.application.entitlement_service import EntitlementService
from src.plataforma_saas.domain.estados import FUNCIONES, LIMITES
from src.plataforma_saas.domain.exceptions import (
    ModuleInBetaError,
    PlanCodeTakenError,
    PlanLimitInvalidError,
    TemplateImpactConfirmationError,
)
from src.plataforma_saas.infrastructure.models.module import PlatformModuleModel
from src.plataforma_saas.infrastructure.models.plan import PlanFeatureModel, PlanModel
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.plataforma_saas.infrastructure.repositories.saas_repository import SaasRepository
from src.plataforma_saas.web.schemas.plans import (
    FeatureCatalogItem,
    PlanResponse,
    PlanSaveResult,
)
from src.shared.exceptions.domain_exception import ConflictError, NotFoundError, ValidationError

LABELS = {
    "products": "Catálogo y prendas",
    "inventory": "Inventario",
    "sales": "Ventas y caja",
    "reservations": "Reservas",
    "offline": "Operación sin conexión",
    "conventional_reports": "Reportes convencionales",
    "ai_reports": "Reportes con IA",
    "ml_analytics": "Analítica predictiva (ML)",
    "promotions": "Ofertas y promociones",
    "virtual_tryon": "Probador virtual (RA)",
    "exchanges": "Cambios de prendas",
    "devices_audit": "Dispositivos y auditoría",
    "max_active_branches": "Sucursales activas",
}


class PlanService:
    def __init__(self, db, actor):
        self.db = db
        self.actor = actor

    def _plan(self, plan_id):
        plan = self.db.get(PlanModel, plan_id)
        if not plan:
            raise NotFoundError("Plan no encontrado.")
        return plan

    def _response(self, plan):
        features = {f.feature_code: f for f in plan.features}
        count = self.db.scalar(
            select(func.count())
            .select_from(SubscriptionModel)
            .where(SubscriptionModel.plan_id == plan.id, SubscriptionModel.closed_at.is_(None))
        ) or 0
        return PlanResponse(
            id=plan.id,
            code=plan.code,
            name=plan.name,
            reference_price=plan.reference_price,
            duration_days=plan.duration_days,
            is_active=plan.is_active,
            tenants_count=count,
            features={code: info["kind"] == "BASE" or (features[code].enabled if code in features else False)
                      for code, info in EntitlementService(self.db)._get_catalog().items()},
            limits={code: features[code].limit_value for code in LIMITES if code in features and features[code].limit_value is not None},
        )

    def listar(self, include_inactive=False):
        query = select(PlanModel).order_by(PlanModel.reference_price, PlanModel.name)
        if not include_inactive:
            query = query.where(PlanModel.is_active.is_(True))
        return [self._response(plan) for plan in self.db.scalars(query)]

    def catalogo(self):
        catalog = EntitlementService(self.db)._get_catalog()
        return [FeatureCatalogItem(code=code, label=info["name"], kind="feature")
                for code, info in catalog.items()] + [
                    FeatureCatalogItem(code=code, label=LABELS.get(code, code), kind="limit") for code in LIMITES]

    def _validar_limites(self, features):
        codes = [feature.feature_code for feature in features]
        if len(set(codes)) != len(codes) or "max_active_branches" not in codes:
            raise PlanLimitInvalidError()
        catalog = EntitlementService(self.db)._get_catalog()
        unknown = set(codes) - set(catalog) - set(LIMITES)
        if unknown:
            raise ValidationError("Funcionalidad desconocida.", details={"features": sorted(unknown)})
        for feature in features:
            if feature.feature_code in LIMITES:
                if feature.limit_value is None or feature.limit_value <= 0:
                    raise PlanLimitInvalidError()
                continue
            module = catalog[feature.feature_code]
            if feature.limit_value is not None:
                raise PlanLimitInvalidError()
            if module["kind"] == "BASE" and not feature.enabled:
                raise ConflictError("Un módulo base no se puede quitar del plan.")
            if feature.enabled and module["lifecycle"] != "GA":
                raise ModuleInBetaError()

    def _audit(self, plan, action, before, reason=None):
        RecordAuditEvent(self.db).execute(
            actor_user_id=self.actor.id,
            action=action,
            entity_type="plan",
            entity_id=str(plan.id),
            description="Configuración del plan actualizada.",
            metadata={"before": before, "after": self._response(plan).model_dump(mode="json"), "reason": reason},
        )

    def crear(self, data):
        if self.db.scalar(select(PlanModel.id).where(PlanModel.code == data.code)):
            raise PlanCodeTakenError()
        self._validar_limites(data.features)

        plan = PlanModel(
            **data.model_dump(exclude={"features"}),
            features=[PlanFeatureModel(**f.model_dump()) for f in data.features],
        )
        self.db.add(plan)
        self.db.flush()
        self._audit(plan, "plans.created", None)
        self.db.commit()
        return PlanSaveResult(plan=self._response(plan), exceeded_tenants=[])

    def actualizar(self, plan_id, data):
        plan = self._plan(plan_id)
        before = self._response(plan).model_dump(mode="json")
        changes = data.model_dump(exclude_unset=True, exclude={"features", "reason", "confirm"})
        if any(value is None for value in changes.values()) or ("features" in data.model_fields_set and data.features is None):
            raise ConflictError("Los campos del plan no pueden quedar vacíos.")

        if data.features is not None:
            self._validar_limites(data.features)

            new_features_map = {feature.feature_code: feature.enabled for feature in data.features
                                if feature.feature_code not in LIMITES}
            impact = EntitlementService(self.db).impacto_plan(plan.id, new_features_map)
            if impact.modules_removed and impact.affected_tenants > 0 and not data.confirm:
                raise TemplateImpactConfirmationError(
                    "Se requiere confirmación de impacto para actualizar el plan.",
                    details=impact.model_dump(mode="json"))
            old_modules = {feature.feature_code for feature in plan.features
                           if feature.enabled and feature.feature_code not in LIMITES}
            new_modules = {code for code, enabled in new_features_map.items() if enabled}
            if old_modules != new_modules and not (data.reason or "").strip():
                raise ValidationError("Indica un motivo para cambiar los módulos del plan.")

            plan.features.clear()
            self.db.flush()
            plan.features = [PlanFeatureModel(**f.model_dump()) for f in data.features]

        for key, value in changes.items():
            setattr(plan, key, value)
        self.db.flush()
        EntitlementService.invalidate(self.db)

        limit = self._response(plan).limits.get("max_active_branches", 0)
        tenants = self.db.scalars(
            select(TenantModel)
            .join(SubscriptionModel)
            .where(SubscriptionModel.plan_id == plan.id, SubscriptionModel.closed_at.is_(None))
        ).all()
        repo = SaasRepository(self.db)
        exceeded = [tenant.trade_name for tenant in tenants if repo.count_active_branches(tenant.id) > limit]
        self._audit(plan, "plans.updated", before, reason=data.reason)
        self.db.commit()
        return PlanSaveResult(plan=self._response(plan), exceeded_tenants=exceeded)

    def _set_active(self, plan_id, active):
        plan = self._plan(plan_id)
        before = self._response(plan).model_dump(mode="json")
        plan.is_active = active
        self._audit(plan, "plans.activated" if active else "plans.deactivated", before)
        self.db.commit()
        return self._response(plan)

    def activar(self, plan_id):
        return self._set_active(plan_id, True)

    def desactivar(self, plan_id):
        return self._set_active(plan_id, False)

    def eliminar(self, plan_id):
        plan = self._plan(plan_id)
        subs_count = self.db.scalar(
            select(func.count()).select_from(SubscriptionModel).where(SubscriptionModel.plan_id == plan.id)
        ) or 0
        if subs_count > 0:
            raise ConflictError(
                f"No se puede eliminar el plan '{plan.name}' porque tiene {subs_count} suscripciones asociadas. Puedes desactivarlo."
            )
        before = self._response(plan).model_dump(mode="json")
        self.db.delete(plan)
        self._audit(plan, "plans.deleted", before, reason="Plan eliminado por el administrador.")
        self.db.commit()
        return True
