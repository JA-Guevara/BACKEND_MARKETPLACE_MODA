from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_platform_permissions
from src.plataforma_saas.application.platform_roles_service import PlatformRolesService
from src.plataforma_saas.web.schemas.governance import (
    PermissionCatalogItem,
    PermissionUpdate,
    PlatformRoleIn,
    RoleTemplateOut,
    TemplateImpact,
    TemplatePermissionsIn,
)
from src.roles.application.services.role_service import RoleService
from src.roles.infrastructure.http.schemas import RoleCreate, RoleResponse, RoleUpdate
from src.shared.responses.api_response import ApiResponse

router = APIRouter(prefix="/platform", tags=["PAQ-06 · Consola SaaS"])

Reader = Annotated[UserModel, Depends(require_platform_permissions("platform_roles.read"))]
Writer = Annotated[UserModel, Depends(require_platform_permissions("platform_roles.write"))]


# --- Plantillas de empresa ---
@router.get("/roles/templates", response_model=ApiResponse[list[RoleTemplateOut]])
def list_role_templates(actor: Reader, db: Session = Depends(get_db)):
    service = PlatformRolesService(db, actor)
    return ApiResponse(
        message="Plantillas obtenidas.",
        data=service.plantillas(),
    )


@router.post("/roles/templates/{role_id}/impact", response_model=ApiResponse[TemplateImpact])
def calculate_template_impact(
    role_id: UUID,
    body: TemplatePermissionsIn,
    actor: Reader,
    db: Session = Depends(get_db),
):
    service = PlatformRolesService(db, actor)
    return ApiResponse(
        message="Impacto calculado.",
        data=service.impacto_plantilla(role_id, body.permission_codes),
    )


@router.put("/roles/templates/{role_id}/permissions", response_model=ApiResponse[RoleTemplateOut])
def update_template_permissions(
    role_id: UUID,
    body: TemplatePermissionsIn,
    actor: Writer,
    db: Session = Depends(get_db),
):
    service = PlatformRolesService(db, actor)
    return ApiResponse(
        message="Plantilla actualizada exitosamente.",
        data=service.actualizar_plantilla(
            role_id=role_id,
            permission_codes=body.permission_codes,
            reason=body.reason,
            confirm=body.confirm,
        ),
    )


# --- Roles del equipo de plataforma ---
@router.get("/roles/team", response_model=ApiResponse[list[RoleTemplateOut]])
def list_team_roles(actor: Reader, db: Session = Depends(get_db)):
    service = PlatformRolesService(db, actor)
    return ApiResponse(
        message="Roles de plataforma obtenidos.",
        data=service.roles_equipo(),
    )


@router.post("/roles/team", status_code=201, response_model=ApiResponse[RoleTemplateOut])
def create_team_role(
    body: PlatformRoleIn,
    actor: Writer,
    db: Session = Depends(get_db),
):
    service = PlatformRolesService(db, actor)
    return ApiResponse(
        message="Rol de plataforma creado.",
        data=service.crear_rol_equipo(body),
    )


@router.patch("/roles/team/{role_id}", response_model=ApiResponse[RoleTemplateOut])
def update_team_role(
    role_id: UUID,
    body: PlatformRoleIn,
    actor: Writer,
    db: Session = Depends(get_db),
):
    service = PlatformRolesService(db, actor)
    return ApiResponse(
        message="Rol de plataforma actualizado.",
        data=service.actualizar_rol_equipo(role_id, body),
    )


@router.post("/roles/team/{role_id}/deactivate", response_model=ApiResponse[RoleTemplateOut])
def deactivate_team_role(
    role_id: UUID,
    actor: Writer,
    db: Session = Depends(get_db),
):
    service = PlatformRolesService(db, actor)
    return ApiResponse(
        message="Rol de plataforma desactivado.",
        data=service.desactivar_rol_equipo(role_id),
    )


# --- Roles propios de una empresa gestionados desde consola ---
@router.get("/tenants/{tenant_id}/roles", response_model=ApiResponse[list[RoleResponse]])
def list_tenant_roles_from_console(
    tenant_id: UUID,
    actor: Reader,
    db: Session = Depends(get_db),
):
    service = RoleService(db, tenant_id=tenant_id)
    roles = service.list_roles()
    return ApiResponse(message="Roles de la empresa obtenidos.", data=[RoleResponse.model_validate(r) for r in roles])


@router.post("/tenants/{tenant_id}/roles", status_code=201, response_model=ApiResponse[RoleResponse])
def create_tenant_role_from_console(
    tenant_id: UUID,
    body: RoleCreate,
    actor: Writer,
    db: Session = Depends(get_db),
):
    service = RoleService(db, tenant_id=tenant_id)
    role = service.create_role(body, actor_id=actor.id)
    return ApiResponse(message="Rol de empresa creado.", data=RoleResponse.model_validate(role))


@router.patch("/tenants/{tenant_id}/roles/{role_id}", response_model=ApiResponse[RoleResponse])
def update_tenant_role_from_console(
    tenant_id: UUID,
    role_id: UUID,
    body: RoleUpdate,
    actor: Writer,
    db: Session = Depends(get_db),
):
    service = RoleService(db, tenant_id=tenant_id)
    role = service.update_role(role_id, body, actor_id=actor.id)
    return ApiResponse(message="Rol de empresa actualizado.", data=RoleResponse.model_validate(role))


# --- Catálogo de permisos ---
@router.get("/permissions", response_model=ApiResponse[list[PermissionCatalogItem]])
def list_permission_catalog(actor: Reader, db: Session = Depends(get_db)):
    service = PlatformRolesService(db, actor)
    return ApiResponse(
        message="Catálogo de permisos obtenido.",
        data=service.catalogo_permisos(),
    )


@router.patch("/permissions/{permission_id}", response_model=ApiResponse[PermissionCatalogItem])
def update_permission_item(
    permission_id: UUID,
    body: PermissionUpdate,
    actor: Writer,
    db: Session = Depends(get_db),
):
    service = PlatformRolesService(db, actor)
    return ApiResponse(
        message="Permiso actualizado.",
        data=service.actualizar_permiso(
            permission_id=permission_id,
            name=body.name,
            description=body.description,
            is_active=body.is_active,
        ),
    )
