from sqlalchemy import func, select
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.plataforma_saas.domain.estados import FUNCIONES, LIMITES
from src.plataforma_saas.domain.exceptions import PlanCodeTakenError, PlanLimitInvalidError
from src.plataforma_saas.infrastructure.models.plan import PlanModel, PlanFeatureModel
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.plataforma_saas.infrastructure.repositories.saas_repository import SaasRepository
from src.plataforma_saas.web.schemas.plans import PlanResponse, PlanSaveResult, FeatureCatalogItem
from src.shared.exceptions.domain_exception import ConflictError, NotFoundError

LABELS = {"products": "Productos", "sales": "Ventas", "reservations": "Reservas", "offline": "Operación sin conexión",
          "conventional_reports": "Reportes convencionales", "ai_reports": "Reportes con IA", "ml_analytics": "Analítica predictiva",
          "max_active_branches": "Sucursales activas"}


class PlanService:
    def __init__(self, db, actor):
        self.db, self.actor = db, actor

    def _plan(self, plan_id):
        plan = self.db.get(PlanModel, plan_id)
        if not plan:
            raise NotFoundError("Plan no encontrado.")
        return plan

    def _response(self, plan):
        features = {f.feature_code: f for f in plan.features}
        count = self.db.scalar(select(func.count()).select_from(SubscriptionModel).where(SubscriptionModel.plan_id == plan.id, SubscriptionModel.closed_at.is_(None))) or 0
        return PlanResponse(id=plan.id, code=plan.code, name=plan.name, reference_price=plan.reference_price,
            duration_days=plan.duration_days, is_active=plan.is_active, tenants_count=count,
            features={code: features[code].enabled if code in features else False for code in FUNCIONES},
            limits={code: features[code].limit_value for code in LIMITES if code in features and features[code].limit_value is not None})

    def listar(self, include_inactive=False):
        query = select(PlanModel).order_by(PlanModel.reference_price, PlanModel.name)
        if not include_inactive:
            query = query.where(PlanModel.is_active.is_(True))
        return [self._response(plan) for plan in self.db.scalars(query)]

    def catalogo(self):
        return [FeatureCatalogItem(code=code, label=LABELS[code], kind="limit" if code in LIMITES else "feature") for code in (*FUNCIONES, *LIMITES)]

    def _validar_limites(self, features):
        codes = [f.feature_code for f in features]
        if len(set(codes)) != len(codes) or "max_active_branches" not in codes:
            raise PlanLimitInvalidError()
        if any(f.feature_code in LIMITES and (f.limit_value is None or f.limit_value <= 0) for f in features):
            raise PlanLimitInvalidError()
        if any(f.feature_code in FUNCIONES and f.limit_value is not None for f in features):
            raise PlanLimitInvalidError()

    def _audit(self, plan, action, before):
        RecordAuditEvent(self.db).execute(actor_user_id=self.actor.id, action=action, entity_type="plan", entity_id=str(plan.id),
            description="Configuración del plan actualizada.", metadata={"before": before, "after": self._response(plan).model_dump(mode="json")})

    def crear(self, data):
        if self.db.scalar(select(PlanModel.id).where(PlanModel.code == data.code)):
            raise PlanCodeTakenError()
        self._validar_limites(data.features)
        plan = PlanModel(**data.model_dump(exclude={"features"}), features=[PlanFeatureModel(**f.model_dump()) for f in data.features])
        self.db.add(plan)
        self.db.flush()
        self._audit(plan, "plans.created", None)
        self.db.commit()
        return PlanSaveResult(plan=self._response(plan), exceeded_tenants=[])

    def actualizar(self, plan_id, data):
        plan = self._plan(plan_id)
        before = self._response(plan).model_dump(mode="json")
        changes = data.model_dump(exclude_unset=True, exclude={"features"})
        if any(value is None for value in changes.values()) or ("features" in data.model_fields_set and data.features is None):
            raise ConflictError("Los campos del plan no pueden quedar vacíos.")
        if data.features is not None:
            self._validar_limites(data.features)
            # Vaciar y flush evita colisiones de la clave (plan_id, feature_code).
            plan.features.clear()
            self.db.flush()
            plan.features = [PlanFeatureModel(**f.model_dump()) for f in data.features]
        for key, value in changes.items():
            setattr(plan, key, value)
        self.db.flush()
        limit = self._response(plan).limits.get("max_active_branches", 0)
        tenants = self.db.scalars(select(TenantModel).join(SubscriptionModel).where(SubscriptionModel.plan_id == plan.id, SubscriptionModel.closed_at.is_(None))).all()
        repo = SaasRepository(self.db)
        exceeded = [tenant.trade_name for tenant in tenants if repo.count_active_branches(tenant.id) > limit]
        self._audit(plan, "plans.updated", before)
        self.db.commit()
        return PlanSaveResult(plan=self._response(plan), exceeded_tenants=exceeded)

    def _set_active(self, plan_id, active):
        plan = self._plan(plan_id)
        before = self._response(plan).model_dump(mode="json")
        plan.is_active = active
        self._audit(plan, "plans.activated" if active else "plans.deactivated", before)
        self.db.commit()
        return self._response(plan)

    def activar(self, plan_id): return self._set_active(plan_id, True)
    def desactivar(self, plan_id): return self._set_active(plan_id, False)
