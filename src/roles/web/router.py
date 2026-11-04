import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_permissions, require_platform_permissions
from src.infrastructure.security.tenancy import TenantScope
from src.roles.application.services.role_service import RoleService
from src.roles.infrastructure.http.schemas import (
    PermissionCreate,
    PermissionResponse,
    PermissionUpdate,
    RoleCreate,
    RoleResponse,
    RoleUpdate,
    SetPermissionsRequest,
)
from src.roles.infrastructure.persistence.repositories.role_repository import RoleRepository
from src.shared.responses.api_response import ApiResponse


router = APIRouter(prefix="/roles", tags=['PAQ-01 · Usuarios y catálogo'])
RoleReader = Annotated[UserModel, Depends(require_permissions("roles.read"))]
RoleWriter = Annotated[UserModel, Depends(require_permissions("roles.write"))]
PlatformRoleWriter = Annotated[UserModel, Depends(require_platform_permissions("tenants.write"))]


@router.get("", response_model=ApiResponse[list[RoleResponse]])
def list_roles(
    ctx: TenantScope,
    actor: RoleReader,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
):
    return ApiResponse(message="Roles obtenidos.", data=RoleService(db, ctx.tenant_id).list_roles(include_inactive))


@router.get("/permissions/all", response_model=ApiResponse[list[PermissionResponse]])
def list_permissions(
    ctx: TenantScope,
    actor: RoleReader,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
):
    repo = RoleRepository(db)
    if ctx.is_platform:
        perms = repo.list_permissions(include_inactive)
    else:
        perms = repo.permissions_by_scope("tenant", include_inactive)
    return ApiResponse(message="Permisos obtenidos.", data=perms)


@router.get("/{role_id}", response_model=ApiResponse[RoleResponse])
def get_role(
    role_id: uuid.UUID,
    ctx: TenantScope,
    actor: RoleReader,
    db: Session = Depends(get_db),
):
    return ApiResponse(message="Rol obtenido.", data=RoleService(db, ctx.tenant_id).get_role(role_id))


@router.post("", response_model=ApiResponse[RoleResponse], status_code=status.HTTP_201_CREATED)
def create_role(
    data: RoleCreate,
    ctx: TenantScope,
    actor: RoleWriter,
    db: Session = Depends(get_db),
):
    return ApiResponse(message="Rol creado.", data=RoleService(db, ctx.tenant_id).create_role(data, actor))


@router.patch("/{role_id}", response_model=ApiResponse[RoleResponse])
def update_role(
    role_id: uuid.UUID,
    data: RoleUpdate,
    ctx: TenantScope,
    actor: RoleWriter,
    db: Session = Depends(get_db),
):
    return ApiResponse(message="Rol actualizado.", data=RoleService(db, ctx.tenant_id).update_role(role_id, data, actor))


@router.put("/{role_id}/permissions", response_model=ApiResponse[RoleResponse])
def set_permissions(
    role_id: uuid.UUID,
    data: SetPermissionsRequest,
    ctx: TenantScope,
    actor: RoleWriter,
    db: Session = Depends(get_db),
):
    return ApiResponse(message="Permisos actualizados.", data=RoleService(db, ctx.tenant_id).set_permissions(role_id, data.permission_ids, actor))


@router.post("/{role_id}/deactivate", response_model=ApiResponse[RoleResponse])
def deactivate_role(
    role_id: uuid.UUID,
    ctx: TenantScope,
    actor: RoleWriter,
    db: Session = Depends(get_db),
):
    return ApiResponse(message="Rol desactivado.", data=RoleService(db, ctx.tenant_id).deactivate_role(role_id, actor))


@router.post("/{role_id}/activate", response_model=ApiResponse[RoleResponse])
def activate_role(
    role_id: uuid.UUID,
    ctx: TenantScope,
    actor: RoleWriter,
    db: Session = Depends(get_db),
):
    return ApiResponse(message="Rol activado.", data=RoleService(db, ctx.tenant_id).activate_role(role_id, actor))


@router.delete("/{role_id}", response_model=ApiResponse[None])
def delete_role(
    role_id: uuid.UUID,
    ctx: TenantScope,
    actor: RoleWriter,
    db: Session = Depends(get_db),
):
    RoleService(db, ctx.tenant_id).delete_role(role_id, actor)
    return ApiResponse(message="Rol eliminado.")


@router.post("/permissions", response_model=ApiResponse[PermissionResponse], status_code=status.HTTP_201_CREATED)
def create_permission(data: PermissionCreate, actor: PlatformRoleWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Permiso creado.", data=RoleService(db, None).create_permission(data, actor))


@router.patch("/permissions/{permission_id}", response_model=ApiResponse[PermissionResponse])
def update_permission(permission_id: uuid.UUID, data: PermissionUpdate, actor: PlatformRoleWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Permiso actualizado.", data=RoleService(db, None).update_permission(permission_id, data, actor))


@router.post("/permissions/{permission_id}/deactivate", response_model=ApiResponse[PermissionResponse])
def deactivate_permission(permission_id: uuid.UUID, actor: PlatformRoleWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Permiso desactivado.", data=RoleService(db, None).set_permission_active(permission_id, False, actor))


@router.post("/permissions/{permission_id}/activate", response_model=ApiResponse[PermissionResponse])
def activate_permission(permission_id: uuid.UUID, actor: PlatformRoleWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Permiso activado.", data=RoleService(db, None).set_permission_active(permission_id, True, actor))


@router.delete("/permissions/{permission_id}", response_model=ApiResponse[None])
def delete_permission(permission_id: uuid.UUID, actor: PlatformRoleWriter, db: Session = Depends(get_db)):
    RoleService(db, None).delete_permission(permission_id, actor)
    return ApiResponse(message="Permiso eliminado.")
