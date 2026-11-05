from datetime import datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.plataforma_saas.application.entitlement_service import EntitlementService
from src.plataforma_saas.domain.estados import LIMITES
from src.plataforma_saas.domain.exceptions import (
    ModuleNotReviewedError,
    ModuleRetiredError,
    PermissionOutOfScopeError,
)
from src.plataforma_saas.domain.modulos import Lifecycle, puede_pasar_a
from src.plataforma_saas.infrastructure.models.module import (
    PlatformModuleModel,
    module_permissions,
)
from src.plataforma_saas.infrastructure.models.plan import PlanFeatureModel, PlanModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.plataforma_saas.web.schemas.governance import (
    ModuleDetail,
    ModuleMatrix,
    ModuleMatrixPlan,
    ModuleOut,
    ModulePermissionSummary,
    ModuleUpdate,
)
from src.roles.infrastructure.persistence.models.permission import PermissionModel
from src.shared.exceptions.domain_exception import NotFoundError, ValidationError


class ModuleService:
    def __init__(self, db: Session, actor) -> None:
        self.db = db
        self.actor = actor

    def _get_module(self, code: str) -> PlatformModuleModel:
        mod = self.db.get(PlatformModuleModel, code)
        if not mod:
            raise NotFoundError(f"Módulo '{code}' no encontrado.")
        return mod

    def listar(self) -> list[ModuleOut]:
        mods = self.db.scalars(
            select(PlatformModuleModel).order_by(PlatformModuleModel.sort_order, PlatformModuleModel.code)
        ).all()

        # Conteo de planes por módulo
        plan_counts = dict(
            self.db.execute(
                select(PlanFeatureModel.feature_code, func.count(PlanFeatureModel.plan_id))
                .where(PlanFeatureModel.enabled.is_(True))
                .group_by(PlanFeatureModel.feature_code)
            ).all()
        )

        # Conteo de permisos por módulo
        perm_counts = dict(
            self.db.execute(
                select(module_permissions.c.module_code, func.count(module_permissions.c.permission_id))
                .group_by(module_permissions.c.module_code)
            ).all()
        )

        # Empresas activas
        active_tenants = self.db.scalars(
            select(TenantModel).where(TenantModel.status == "ACTIVA")
        ).all()
        entitlement_svc = EntitlementService(self.db)
        tenant_counts: dict[str, int] = {}
        for mod in mods:
            tenant_counts[mod.code] = sum(
                1 for t in active_tenants if entitlement_svc.tiene(t.id, mod.code)
            )

        return [
            ModuleOut(
                code=m.code,
                name=m.name,
                description=m.description,
                category=m.category,
                icon=m.icon,
                kind=m.kind,
                lifecycle=m.lifecycle,
                depends_on=m.depends_on or [],
                web_routes=m.web_routes or [],
                sort_order=m.sort_order or 0,
                plans_count=plan_counts.get(m.code, 0),
                tenants_count=tenant_counts.get(m.code, 0),
                permissions_count=perm_counts.get(m.code, 0),
                last_preview_at=m.last_preview_at,
                created_at=m.created_at,
                updated_at=m.updated_at,
            )
            for m in mods
        ]

    def obtener(self, code: str) -> ModuleDetail:
        m = self._get_module(code)
        perms_stmt = (
            select(PermissionModel)
            .join(module_permissions, module_permissions.c.permission_id == PermissionModel.id)
            .where(module_permissions.c.module_code == code)
            .order_by(PermissionModel.code)
        )
        perms = self.db.scalars(perms_stmt).all()

        # Planes que lo incluyen
        plans_stmt = (
            select(PlanModel.id, PlanModel.code, PlanModel.name)
            .join(PlanFeatureModel, PlanFeatureModel.plan_id == PlanModel.id)
            .where(PlanFeatureModel.feature_code == code, PlanFeatureModel.enabled.is_(True))
        )
        plans = [
            {"id": str(p_id), "code": p_code, "name": p_name}
            for p_id, p_code, p_name in self.db.execute(plans_stmt).all()
        ]

        # Empresas activas que lo tienen
        active_tenants = self.db.scalars(
            select(TenantModel).where(TenantModel.status == "ACTIVA")
        ).all()
        entitlement_svc = EntitlementService(self.db)
        tenants = [
            {"id": str(t.id), "slug": t.slug, "trade_name": t.trade_name}
            for t in active_tenants
            if entitlement_svc.tiene(t.id, code)
        ]

        return ModuleDetail(
            code=m.code,
            name=m.name,
            description=m.description,
            category=m.category,
            icon=m.icon,
            kind=m.kind,
            lifecycle=m.lifecycle,
            depends_on=m.depends_on or [],
            web_routes=m.web_routes or [],
            sort_order=m.sort_order or 0,
            plans_count=len(plans),
            tenants_count=len(tenants),
            permissions_count=len(perms),
            last_preview_at=m.last_preview_at,
            created_at=m.created_at,
            updated_at=m.updated_at,
            permissions=[
                ModulePermissionSummary(
                    id=p.id,
                    code=p.code,
                    name=p.name,
                    description=p.description,
                )
                for p in perms
            ],
            plans=plans,
            active_tenants=tenants,
            history=[{"id": str(event.id), "action": event.action, "description": event.description,
                      "created_at": event.created_at, "actor_name": event.actor_name}
                     for event in self.db.scalars(select(AuditEventModel).where(
                         AuditEventModel.entity_type == "platform_module", AuditEventModel.entity_id == code
                     ).order_by(AuditEventModel.created_at.desc()).limit(20)).all()],
        )

    def actualizar(self, code: str, data: ModuleUpdate) -> ModuleDetail:
        mod = self._get_module(code)
        before = self.obtener(code).model_dump(mode="json")

        if data.depends_on is not None:
            graph = {module.code: module.depends_on or [] for module in self.db.scalars(select(PlatformModuleModel))}
            unknown = set(data.depends_on) - set(graph)
            if unknown:
                raise ValidationError("Las dependencias deben existir en el catálogo.", details={"modules": sorted(unknown)})
            graph[code] = list(dict.fromkeys(data.depends_on))
            def visit(node, path):
                if node in path:
                    raise ValidationError("Las dependencias de módulos no pueden formar ciclos.")
                for dependency in graph.get(node, []):
                    visit(dependency, path | {node})
            visit(code, set())

        if data.lifecycle and data.lifecycle != mod.lifecycle:
            current_lc = Lifecycle(mod.lifecycle)
            new_lc = Lifecycle(data.lifecycle)
            err = puede_pasar_a(current_lc, new_lc, revisado=bool(mod.last_preview_at))
            if err == "module_not_reviewed":
                raise ModuleNotReviewedError()
            if err == "module_retired":
                raise ModuleRetiredError()
            mod.lifecycle = new_lc.value

        for field in ("name", "description", "category", "icon", "depends_on", "web_routes", "sort_order"):
            val = getattr(data, field)
            if val is not None:
                setattr(mod, field, val)

        mod.updated_at = datetime.now(timezone.utc)
        self.db.flush()
        EntitlementService.invalidate(self.db)

        RecordAuditEvent(self.db).execute(
            actor_user_id=self.actor.id,
            action="platform.module_updated",
            entity_type="platform_module",
            entity_id=code,
            description=f"Módulo '{code}' actualizado.",
            metadata={"before": before, "after": self.obtener(code).model_dump(mode="json")},
        )
        self.db.commit()
        return self.obtener(code)

    def asignar_permisos(self, code: str, permission_codes: list[str]) -> ModuleDetail:
        mod = self._get_module(code)

        # Validar permisos
        permissions = self.db.scalars(
            select(PermissionModel).where(PermissionModel.code.in_(permission_codes))
        ).all()
        if len(permissions) != len(set(permission_codes)):
            raise NotFoundError("Uno o más códigos de permiso no existen.")

        for p in permissions:
            if getattr(p, "scope", "tenant") != "tenant":
                raise PermissionOutOfScopeError(
                    f"El permiso '{p.code}' es de alcance plataforma y no puede asignarse a un módulo de empresa."
                )

        # Quitar permisos existentes del módulo
        self.db.execute(
            module_permissions.delete().where(module_permissions.c.module_code == code)
        )

        # Asignar los nuevos permisos (asegurando que no pertenezcan a otro módulo)
        for p in permissions:
            self.db.execute(
                module_permissions.delete().where(module_permissions.c.permission_id == p.id)
            )
            self.db.execute(
                module_permissions.insert().values(module_code=code, permission_id=p.id)
            )

        self.db.flush()
        EntitlementService.invalidate(self.db)
        RecordAuditEvent(self.db).execute(
            actor_user_id=self.actor.id,
            action="platform.module_permissions_updated",
            entity_type="platform_module",
            entity_id=code,
            description=f"Permisos del módulo '{code}' actualizados ({len(permission_codes)} asignados).",
            metadata={"permissions": permission_codes},
        )
        self.db.commit()
        return self.obtener(code)

    def matriz(self) -> ModuleMatrix:
        modules = self.listar()
        plans_raw = self.db.scalars(
            select(PlanModel).where(PlanModel.is_active.is_(True)).order_by(PlanModel.reference_price)
        ).all()

        matrix_plans: list[ModuleMatrixPlan] = []
        for p in plans_raw:
            feat_map = {f.feature_code: f for f in p.features}
            modules_enabled = {m.code: m.kind == "BASE" or (bool(feat_map[m.code].enabled) if m.code in feat_map else False) for m in modules}
            limits = {
                code: feat_map[code].limit_value
                for code in LIMITES
                if code in feat_map and feat_map[code].limit_value is not None
            }
            matrix_plans.append(
                ModuleMatrixPlan(
                    id=p.id,
                    code=p.code,
                    name=p.name,
                    modules=modules_enabled,
                    limits=limits,
                )
            )

        return ModuleMatrix(modules=modules, plans=matrix_plans)
