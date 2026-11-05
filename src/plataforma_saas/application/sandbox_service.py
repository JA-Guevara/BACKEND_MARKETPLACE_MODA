from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.inventario_sucursales.infrastructure.models.organization import BranchModel
from src.plataforma_saas.application.entitlement_service import EntitlementService
from src.plataforma_saas.domain.exceptions import SandboxOnlyError
from src.plataforma_saas.infrastructure.models.module import PlatformModuleModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.plataforma_saas.web.schemas.governance import SandboxOut
from src.plataforma_saas.web.schemas.support import SupportSessionStartResponse
from src.shared.exceptions.domain_exception import NotFoundError
from src.usuarios_catalogo.infrastructure.models.catalog import ProductModel as ProductoModel


class SandboxService:
    def __init__(self, db: Session, actor=None) -> None:
        self.db = db
        self.actor = actor

    def _demo_tenant(self) -> TenantModel | None:
        return self.db.scalars(
            select(TenantModel).where(TenantModel.is_sandbox.is_(True))
        ).first()

    def estado(self) -> SandboxOut:
        demo = self._demo_tenant()
        if not demo:
            return SandboxOut(
                tenant_id=None,
                slug="demo",
                trade_name="FashionStore Demo",
                is_active=False,
                modules=[],
                branches_count=0,
                products_count=0,
            )

        entitlement_svc = EntitlementService(self.db)
        mods_map = entitlement_svc.modulos(demo.id)
        catalogo = entitlement_svc._get_catalog()

        modules_list = [
            {
                "code": m.code,
                "name": catalogo.get(m.code, {}).get("name", m.code),
                "origin": m.origen,
                "lifecycle": catalogo.get(m.code, {}).get("lifecycle", "GA"),
            }
            for m in mods_map.values()
        ]

        b_count = self.db.scalar(
            select(func.count(BranchModel.id)).where(BranchModel.tenant_id == demo.id)
        ) or 0
        p_count = self.db.scalar(
            select(func.count(ProductoModel.id)).where(ProductoModel.tenant_id == demo.id)
        ) or 0

        return SandboxOut(
            tenant_id=demo.id,
            slug=demo.slug,
            trade_name=demo.trade_name,
            is_active=(demo.status == "ACTIVA"),
            modules=modules_list,
            branches_count=b_count,
            products_count=p_count,
        )

    def vista_previa(self, module_code: str) -> SupportSessionStartResponse:
        from src.plataforma_saas.application.support_service import SupportService

        demo = self._demo_tenant()
        if not demo:
            raise NotFoundError("No existe empresa demo configurada.")

        mod = self.db.get(PlatformModuleModel, module_code)
        now = datetime.now(timezone.utc)
        if mod and self.actor:
            mod.last_preview_at = now
            mod.last_preview_by = self.actor.id
            self.db.flush()

        support_svc = SupportService(self.db, actor=self.actor)
        return support_svc.iniciar(
            tenant_id=demo.id,
            reason=f"Vista previa del módulo '{module_code}' en empresa demo",
            duration_minutes=60,
            mode="WRITE",
            landing_module=module_code,
        )

    def restablecer(self, confirm: bool = False) -> SandboxOut:
        demo = self._demo_tenant()
        if not demo or not demo.is_sandbox:
            raise SandboxOnlyError()

        if self.actor:
            RecordAuditEvent(self.db).execute(
                actor_user_id=self.actor.id,
                action="platform.sandbox_reset",
                entity_type="tenant",
                entity_id=str(demo.id),
                description="Empresa demo restablecida a su estado inicial.",
                metadata={"tenant_id": str(demo.id), "slug": demo.slug},
            )
        self.db.commit()
        return self.estado()

    def reset(self, actor=None, tenant_id=None, confirm: bool = False) -> SandboxOut:
        if actor is not None:
            self.actor = actor
        if tenant_id is not None:
            tenant = self.db.get(TenantModel, tenant_id)
            if not tenant or not tenant.is_sandbox:
                raise SandboxOnlyError()
        return self.restablecer(confirm=confirm)
