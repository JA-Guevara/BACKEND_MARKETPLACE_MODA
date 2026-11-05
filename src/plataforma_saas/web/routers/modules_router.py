from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_platform_permissions
from src.plataforma_saas.application.entitlement_service import EntitlementService
from src.plataforma_saas.application.module_service import ModuleService
from src.plataforma_saas.application.sandbox_service import SandboxService
from src.plataforma_saas.application.tenant_module_service import TenantModuleService
from src.plataforma_saas.web.schemas.governance import (
    ModuleDetail,
    ModuleMatrix,
    ModuleOut,
    ModulePermissionsIn,
    ModuleUpdate,
    PlanImpact,
    PreviewIn,
    RevokeIn,
    SandboxOut,
    TenantLimitIn,
    TenantLimitOut,
    TenantModuleGrant,
    TenantModuleOut,
)
from src.plataforma_saas.web.schemas.support import SupportSessionStartResponse
from src.shared.responses.api_response import ApiResponse

router = APIRouter(tags=["PAQ-06 · Plataforma SaaS · Módulos y gobierno"])

ModulesReadUser = Annotated[UserModel, Depends(require_platform_permissions("modules.read"))]
ModulesWriteUser = Annotated[UserModel, Depends(require_platform_permissions("modules.write"))]
PlansWriteUser = Annotated[UserModel, Depends(require_platform_permissions("plans.write"))]
TenantsReadUser = Annotated[UserModel, Depends(require_platform_permissions("tenants.read"))]
SubscriptionsWriteUser = Annotated[UserModel, Depends(require_platform_permissions("subscriptions.write"))]
SandboxUser = Annotated[UserModel, Depends(require_platform_permissions("sandbox.manage"))]


# --- Módulos globales ---

@router.get("/platform/modules", response_model=ApiResponse[list[ModuleOut]])
def list_modules(
    actor: ModulesReadUser,
    db: Session = Depends(get_db),
):
    result = ModuleService(db, actor).listar()
    return ApiResponse(message="Catálogo de módulos obtenido.", data=result)


@router.get("/platform/modules/matrix", response_model=ApiResponse[ModuleMatrix])
def get_matrix(
    actor: ModulesReadUser,
    db: Session = Depends(get_db),
):
    result = ModuleService(db, actor).matriz()
    return ApiResponse(message="Matriz de módulos y planes obtenida.", data=result)


@router.get("/platform/modules/{code}", response_model=ApiResponse[ModuleDetail])
def get_module(
    code: str,
    actor: ModulesReadUser,
    db: Session = Depends(get_db),
):
    result = ModuleService(db, actor).obtener(code)
    return ApiResponse(message="Detalle del módulo obtenido.", data=result)


@router.patch("/platform/modules/{code}", response_model=ApiResponse[ModuleDetail])
def update_module(
    code: str,
    data: ModuleUpdate,
    actor: ModulesWriteUser,
    db: Session = Depends(get_db),
):
    result = ModuleService(db, actor).actualizar(code, data)
    return ApiResponse(message="Módulo actualizado correctamente.", data=result)


@router.put("/platform/modules/{code}/permissions", response_model=ApiResponse[ModuleDetail])
def assign_module_permissions(
    code: str,
    data: ModulePermissionsIn,
    actor: ModulesWriteUser,
    db: Session = Depends(get_db),
):
    result = ModuleService(db, actor).asignar_permisos(code, data.permission_codes)
    return ApiResponse(message="Permisos asignados al módulo.", data=result)


@router.post("/platform/plans/{plan_id}/impact", response_model=ApiResponse[PlanImpact])
def calculate_plan_impact(
    plan_id: UUID,
    features: dict[str, bool],
    actor: PlansWriteUser,
    db: Session = Depends(get_db),
):
    result = EntitlementService(db).impacto_plan(plan_id, features)
    return ApiResponse(message="Impacto de modificación de plan calculado.", data=result)


# --- Módulos por empresa ---

@router.get("/platform/tenants/{tenant_id}/modules", response_model=ApiResponse[list[TenantModuleOut]])
def list_tenant_modules(
    tenant_id: UUID,
    actor: TenantsReadUser,
    db: Session = Depends(get_db),
):
    result = TenantModuleService(db, actor).listar(tenant_id)
    return ApiResponse(message="Módulos de la empresa obtenidos.", data=result)


@router.post(
    "/platform/tenants/{tenant_id}/modules",
    response_model=ApiResponse[TenantModuleOut],
    status_code=status.HTTP_201_CREATED,
)
def grant_tenant_module(
    tenant_id: UUID,
    data: TenantModuleGrant,
    actor: SubscriptionsWriteUser,
    db: Session = Depends(get_db),
):
    result = TenantModuleService(db, actor).habilitar(
        tenant_id=tenant_id,
        module_code=data.module_code,
        mode=data.mode,
        days=data.days,
        reason=data.reason,
    )
    return ApiResponse(message=f"Módulo asignado en modo {data.mode}.", data=result)


@router.post("/platform/tenants/{tenant_id}/modules/{override_id}/revoke", response_model=ApiResponse[None])
def revoke_tenant_module(
    tenant_id: UUID,
    override_id: UUID,
    data: RevokeIn,
    actor: SubscriptionsWriteUser,
    db: Session = Depends(get_db),
):
    TenantModuleService(db, actor).revocar(override_id, reason=data.reason)
    return ApiResponse(message="Asignación del módulo revocada.")


# --- Límites por empresa ---

@router.post(
    "/platform/tenants/{tenant_id}/limits",
    response_model=ApiResponse[TenantLimitOut],
    status_code=status.HTTP_201_CREATED,
)
def set_tenant_limit(
    tenant_id: UUID,
    data: TenantLimitIn,
    actor: SubscriptionsWriteUser,
    db: Session = Depends(get_db),
):
    result = TenantModuleService(db, actor).fijar_limite(
        tenant_id=tenant_id,
        limit_code=data.limit_code,
        value=data.value,
        days=data.days,
        reason=data.reason,
    )
    return ApiResponse(message="Límite configurado para la empresa.", data=result)


@router.post("/platform/tenants/{tenant_id}/limits/{limit_id}/revoke", response_model=ApiResponse[None])
def revoke_tenant_limit(
    tenant_id: UUID,
    limit_id: UUID,
    data: RevokeIn,
    actor: SubscriptionsWriteUser,
    db: Session = Depends(get_db),
):
    TenantModuleService(db, actor).quitar_limite(limit_id, reason=data.reason)
    return ApiResponse(message="Límite revocado.")


# --- Sandbox / Empresa Demo ---

@router.get("/platform/sandbox", response_model=ApiResponse[SandboxOut])
def get_sandbox(
    actor: SandboxUser,
    db: Session = Depends(get_db),
):
    result = SandboxService(db, actor).estado()
    return ApiResponse(message="Estado de empresa demo obtenido.", data=result)


@router.post("/platform/sandbox/preview", response_model=ApiResponse[SupportSessionStartResponse])
def preview_sandbox(
    data: PreviewIn,
    actor: SandboxUser,
    db: Session = Depends(get_db),
):
    result = SandboxService(db, actor).vista_previa(data.module_code)
    return ApiResponse(message="Sesión de vista previa iniciada en empresa demo.", data=result)


@router.post("/platform/sandbox/reset", response_model=ApiResponse[SandboxOut])
def reset_sandbox(
    actor: SandboxUser,
    db: Session = Depends(get_db),
):
    result = SandboxService(db, actor).restablecer(confirm=True)
    return ApiResponse(message="Empresa demo restablecida.", data=result)
