from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.plataforma_saas.domain.modulos import (
    ModuloEfectivo,
    Override,
    modulos_efectivos,
    permisos_bloqueados,
)
from src.plataforma_saas.infrastructure.models.module import (
    PlatformModuleModel,
    TenantModuleModel,
    module_permissions,
)
from src.plataforma_saas.infrastructure.models.plan import PlanFeatureModel, PlanModel
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.plataforma_saas.infrastructure.repositories.saas_repository import SaasRepository
from src.plataforma_saas.web.schemas.governance import PlanImpact
from src.roles.infrastructure.persistence.models.permission import PermissionModel, role_permissions
from src.roles.infrastructure.persistence.models.role import RoleModel, user_roles
from src.shared.context.audit_context import get_audit_request_id
from src.shared.exceptions.domain_exception import NotFoundError, ValidationError

DEFAULT_MODULE_PERMISSION_MAPPING = {
    "catalog.read": "products",
    "catalog.write": "products",
    "suppliers.read": "products",
    "suppliers.write": "products",
    "stock.read": "inventory",
    "stock.write": "inventory",
    "commerce.read": "sales",
    "commerce.write": "sales",
    "reservations.read": "reservations",
    "reservations.write": "reservations",
    "ai_reports.use": "ai_reports",
    "ai_reports.history": "ai_reports",
    "ml_dashboard.read": "ml_analytics",
    "promotions.read": "promotions",
    "promotions.write": "promotions",
    "exchanges.read": "exchanges",
    "exchanges.write": "exchanges",
    "devices.read": "devices_audit",
    "devices.write": "devices_audit",
}

DEFAULT_CATALOG = {
    "products": {"kind": "BASE", "lifecycle": "GA", "name": "Catálogo y prendas"},
    "inventory": {"kind": "ADDON", "lifecycle": "GA", "name": "Inventario"},
    "sales": {"kind": "ADDON", "lifecycle": "GA", "name": "Ventas y caja"},
    "reservations": {"kind": "ADDON", "lifecycle": "GA", "name": "Reservas"},
    "offline": {"kind": "ADDON", "lifecycle": "GA", "name": "Operación sin conexión"},
    "conventional_reports": {"kind": "ADDON", "lifecycle": "GA", "name": "Reportes convencionales"},
    "ai_reports": {"kind": "ADDON", "lifecycle": "GA", "name": "Reportes con IA"},
    "ml_analytics": {"kind": "ADDON", "lifecycle": "GA", "name": "Analítica predictiva (ML)"},
    "promotions": {"kind": "ADDON", "lifecycle": "GA", "name": "Ofertas y promociones"},
    "virtual_tryon": {"kind": "ADDON", "lifecycle": "GA", "name": "Probador virtual (RA)"},
    "exchanges": {"kind": "ADDON", "lifecycle": "GA", "name": "Cambios de prendas"},
    "devices_audit": {"kind": "ADDON", "lifecycle": "GA", "name": "Dispositivos y auditoría"},
}


class EntitlementService:
    def __init__(self, db: Session) -> None:
        self.db = db
        # Las pruebas y otros consumidores pueden reutilizar una Session. El
        # identificador del middleware evita conservar derechos entre requests.
        request_id = get_audit_request_id()
        if db.info.get("entitlement_request_id") != request_id:
            self.invalidate(db)
            db.info["entitlement_request_id"] = request_id

    @staticmethod
    def invalidate(db: Session) -> None:
        for key in list(db.info):
            if key.startswith("entitlements_") or key in {"platform_catalog_cache", "module_permissions_map"}:
                db.info.pop(key, None)

    def _get_catalog(self) -> dict[str, dict]:
        if "platform_catalog_cache" not in self.db.info:
            mods = self.db.scalars(select(PlatformModuleModel).order_by(
                PlatformModuleModel.sort_order, PlatformModuleModel.code)).all()
            # Compatibilidad con fixtures anteriores a la semilla. Los errores
            # de consulta se propagan: una DB caída nunca habilita módulos.
            self.db.info["platform_catalog_cache"] = {
                m.code: {"kind": m.kind, "lifecycle": m.lifecycle, "name": m.name,
                         "depends_on": m.depends_on or []}
                for m in mods
            } if mods else {code: dict(value) for code, value in DEFAULT_CATALOG.items()}
        return self.db.info["platform_catalog_cache"]

    def _permission_mapping(self) -> dict[str, str]:
        if "module_permissions_map" not in self.db.info:
            rows = self.db.execute(
                select(PermissionModel.code, module_permissions.c.module_code)
                .select_from(module_permissions)
                .join(PermissionModel, PermissionModel.id == module_permissions.c.permission_id)
            ).all()
            # El catálogo persistido es autoritativo, incluso al desasignar el
            # último permiso. La semilla solo cubre fixtures sin catálogo.
            has_catalog = bool(self.db.scalar(select(PlatformModuleModel.code).limit(1)))
            self.db.info["module_permissions_map"] = dict(rows) if has_catalog else dict(DEFAULT_MODULE_PERMISSION_MAPPING)
        return self.db.info["module_permissions_map"]

    @staticmethod
    def _overrides(rows) -> list[Override]:
        return [Override(module_code=row.module_code, mode=row.mode, starts_at=row.starts_at,
                         expires_at=row.expires_at, revoked_at=row.revoked_at) for row in rows]

    def modulos(self, tenant_id: UUID) -> dict[str, ModuloEfectivo]:
        cache_key = f"entitlements_{tenant_id}"
        if cache_key not in self.db.info:
            tenant = self.db.get(TenantModel, tenant_id)
            if tenant is None:
                raise NotFoundError("Empresa no encontrada.")
            subscription = SaasRepository(self.db).open_subscription(tenant_id)
            plan_features = {feature.feature_code for feature in subscription.plan.features if feature.enabled} if subscription else set()
            overrides = self.db.scalars(select(TenantModuleModel).where(
                TenantModuleModel.tenant_id == tenant_id, TenantModuleModel.revoked_at.is_(None))).all()
            self.db.info[cache_key] = modulos_efectivos(self._get_catalog(), plan_features,
                self._overrides(overrides), sandbox=tenant.is_sandbox, now=datetime.now(timezone.utc))
        return self.db.info[cache_key]

    def tiene(self, tenant_id: UUID, code: str) -> bool:
        return code in self.modulos(tenant_id)

    def filtrar_permisos(self, tenant_id: UUID, permisos: frozenset[str]) -> frozenset[str]:
        blocked = permisos_bloqueados(set(permisos), self._permission_mapping(), set(self.modulos(tenant_id)))
        return frozenset(permisos - blocked)

    def impacto_plan(self, plan_id: UUID, features: dict[str, bool]) -> PlanImpact:
        plan = self.db.get(PlanModel, plan_id)
        if plan is None:
            raise NotFoundError("Plan no encontrado.")
        catalog = self._get_catalog()
        unknown = set(features) - set(catalog)
        if unknown:
            raise ValidationError("Funcionalidad desconocida.", details={"features": sorted(unknown)})
        previous = {feature.feature_code for feature in plan.features if feature.enabled}
        proposed = {code for code, enabled in features.items() if enabled}
        subscriptions = self.db.scalars(select(SubscriptionModel).where(
            SubscriptionModel.plan_id == plan_id, SubscriptionModel.closed_at.is_(None))).all()
        tenant_ids = {sub.tenant_id for sub in subscriptions}
        tenants = self.db.scalars(select(TenantModel).where(TenantModel.id.in_(tenant_ids))).all() if tenant_ids else []
        rows = self.db.scalars(select(TenantModuleModel).where(
            TenantModuleModel.tenant_id.in_(tenant_ids), TenantModuleModel.revoked_at.is_(None))).all() if tenant_ids else []
        by_tenant = {}
        for row in rows:
            by_tenant.setdefault(row.tenant_id, []).append(row)
        now = datetime.now(timezone.utc)
        mapping = self._permission_mapping()
        affected = set()
        old_plan_modules = set(modulos_efectivos(catalog, previous, [], False, now))
        new_plan_modules = set(modulos_efectivos(catalog, proposed, [], False, now))
        added, removed = new_plan_modules-old_plan_modules, old_plan_modules-new_plan_modules
        gained, lost = set(), set()
        user_conditions = []
        for tenant in tenants:
            overrides = self._overrides(by_tenant.get(tenant.id, []))
            before = set(modulos_efectivos(catalog, previous, overrides, tenant.is_sandbox, now))
            after = set(modulos_efectivos(catalog, proposed, overrides, tenant.is_sandbox, now))
            if before == after:
                continue
            affected.add(tenant.id)
            tenant_added, tenant_removed = after-before, before-after
            added.update(tenant_added); removed.update(tenant_removed)
            tenant_gained = {permission for permission, module in mapping.items() if module in tenant_added}
            tenant_lost = {permission for permission, module in mapping.items() if module in tenant_removed}
            gained.update(tenant_gained); lost.update(tenant_lost)
            if tenant_gained or tenant_lost:
                user_conditions.append(and_(UserModel.tenant_id == tenant.id,
                    PermissionModel.code.in_(tenant_gained | tenant_lost)))
        affected_users = 0
        if user_conditions:
            affected_users = self.db.scalar(select(func.count(func.distinct(UserModel.id)))
                .select_from(UserModel).join(user_roles, user_roles.c.user_id == UserModel.id)
                .join(RoleModel, RoleModel.id == user_roles.c.role_id)
                .join(role_permissions, role_permissions.c.role_id == RoleModel.id)
                .join(PermissionModel, PermissionModel.id == role_permissions.c.permission_id)
                .where(or_(*user_conditions), UserModel.deleted_at.is_(None), UserModel.is_active.is_(True),
                       RoleModel.is_active.is_(True), PermissionModel.is_active.is_(True))) or 0
        return PlanImpact(plan_id=plan_id, affected_tenants=len(affected), affected_users=affected_users,
            modules_added=sorted(added), modules_removed=sorted(removed),
            permissions_gained=sorted(gained), permissions_lost=sorted(lost))
