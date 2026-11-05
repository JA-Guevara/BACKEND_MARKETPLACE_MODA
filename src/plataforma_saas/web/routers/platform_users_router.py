from typing import Annotated, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.session import get_db
from src.infrastructure.security.access_context import AccessContext
from src.infrastructure.security.authorization import get_access_context, require_platform_permissions
from src.plataforma_saas.application.platform_users_service import PlatformUsersService
from src.plataforma_saas.web.schemas.console import BranchSummary, GlobalUserResponse
from src.plataforma_saas.web.schemas.governance import (
    BranchIdsIn,
    EffectivePermissions,
    GlobalUserCreate,
    GlobalUserUpdate,
    RoleIdsIn,
)
from src.plataforma_saas.web.schemas.platform_users import PlatformAdminInvite
from src.shared.exceptions.domain_exception import AuthorizationError
from src.shared.responses.api_response import ApiResponse
from src.shared.responses.pagination import Page

router = APIRouter(prefix="/platform", tags=["PAQ-06 · Consola SaaS"])

Reader = Annotated[UserModel, Depends(require_platform_permissions("platform_users.read"))]
Writer = Annotated[UserModel, Depends(require_platform_permissions("platform_users.write"))]


def get_user_writer(ctx: AccessContext = Depends(get_access_context)) -> UserModel:
    if not ctx.is_platform:
        raise AuthorizationError("Esta operación requiere un administrador de plataforma.")
    # Permite si tiene platform_users.write O tenant_users.write
    if "platform_users.write" not in ctx.permissions and "tenant_users.write" not in ctx.permissions:
        raise AuthorizationError("No tiene permisos para modificar usuarios.", details={"required": ["tenant_users.write"]})
    return ctx.user


UserWriter = Annotated[UserModel, Depends(get_user_writer)]


@router.get("/users", response_model=ApiResponse[Page[GlobalUserResponse]])
def search_users(
    actor: Reader,
    db: Session = Depends(get_db),
    search: str | None = None,
    tenant_id: UUID | None = None,
    status: Literal["active", "blocked", "unverified", "inactive"] | None = None,
    kind: Literal["platform", "tenant_admin", "staff", "client"] | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    service = PlatformUsersService(db, actor)
    return ApiResponse(
        message="Operación completada.",
        data=service.buscar(
            search=search,
            tenant_id=tenant_id,
            status=status,
            kind=kind,
            page=page,
            page_size=page_size,
        ),
    )


@router.post("/users", status_code=201, response_model=ApiResponse[GlobalUserResponse])
def create_global_user(
    body: GlobalUserCreate,
    actor: UserWriter,
    db: Session = Depends(get_db),
    ctx: AccessContext = Depends(get_access_context),
):
    if body.kind == "platform" and "platform_users.write" not in ctx.permissions:
        raise AuthorizationError(
            "Crear usuarios de plataforma requiere permiso platform_users.write.",
            details={"required": ["platform_users.write"]},
        )
    service = PlatformUsersService(db, actor)
    return ApiResponse(
        message="Usuario creado exitosamente.",
        data=service.crear(body),
    )


@router.patch("/users/{user_id}", response_model=ApiResponse[GlobalUserResponse])
def update_global_user(
    user_id: UUID,
    body: GlobalUserUpdate,
    actor: UserWriter,
    db: Session = Depends(get_db),
):
    service = PlatformUsersService(db, actor)
    return ApiResponse(
        message="Usuario actualizado exitosamente.",
        data=service.actualizar(user_id, body),
    )


@router.put("/users/{user_id}/roles", response_model=ApiResponse[GlobalUserResponse])
def assign_user_roles(
    user_id: UUID,
    body: RoleIdsIn,
    actor: UserWriter,
    db: Session = Depends(get_db),
):
    service = PlatformUsersService(db, actor)
    return ApiResponse(
        message="Roles actualizados exitosamente.",
        data=service.asignar_roles(user_id, body.role_ids),
    )


@router.put("/users/{user_id}/branches", response_model=ApiResponse[list[BranchSummary]])
def assign_user_branches(
    user_id: UUID,
    body: BranchIdsIn,
    actor: UserWriter,
    db: Session = Depends(get_db),
):
    service = PlatformUsersService(db, actor)
    return ApiResponse(
        message="Sucursales asignadas exitosamente.",
        data=service.asignar_sucursales(user_id, body.branch_ids, body.default_id),
    )


@router.get("/users/{user_id}/effective-permissions", response_model=ApiResponse[EffectivePermissions])
def get_effective_permissions(
    user_id: UUID,
    actor: Reader,
    db: Session = Depends(get_db),
):
    service = PlatformUsersService(db, actor)
    return ApiResponse(
        message="Permisos efectivos obtenidos.",
        data=service.permisos_efectivos(user_id),
    )


@router.post("/users/{user_id}/reset-password", response_model=ApiResponse[GlobalUserResponse])
def reset_user_password(
    user_id: UUID,
    actor: UserWriter,
    db: Session = Depends(get_db),
):
    service = PlatformUsersService(db, actor)
    return ApiResponse(
        message="Enlace de restablecimiento enviado.",
        data=service.restablecer_contrasena(user_id),
    )


@router.post("/users/{user_id}/force-password-change", response_model=ApiResponse[GlobalUserResponse])
def force_password_change(
    user_id: UUID,
    actor: UserWriter,
    db: Session = Depends(get_db),
):
    service = PlatformUsersService(db, actor)
    return ApiResponse(
        message="Cambio de contraseña forzado.",
        data=service.forzar_cambio(user_id),
    )


@router.post("/users/{user_id}/unlock", response_model=ApiResponse[GlobalUserResponse])
def unlock_user(user_id: UUID, actor: UserWriter, db: Session = Depends(get_db)):
    service = PlatformUsersService(db, actor)
    return ApiResponse(
        message="Usuario desbloqueado.",
        data=service.desbloquear(user_id),
    )


@router.post("/users/{user_id}/resend-verification", response_model=ApiResponse[GlobalUserResponse])
def resend_verification(user_id: UUID, actor: UserWriter, db: Session = Depends(get_db)):
    service = PlatformUsersService(db, actor)
    return ApiResponse(
        message="Enlace de verificación enviado.",
        data=service.reenviar_verificacion(user_id),
    )


@router.post("/users/{user_id}/revoke-sessions", response_model=ApiResponse[GlobalUserResponse])
def revoke_sessions(user_id: UUID, actor: UserWriter, db: Session = Depends(get_db)):
    service = PlatformUsersService(db, actor)
    return ApiResponse(
        message="Sesiones revocadas.",
        data=service.cerrar_sesiones(user_id),
    )


@router.post("/users/{user_id}/deactivate", response_model=ApiResponse[GlobalUserResponse])
def deactivate_user(user_id: UUID, actor: UserWriter, db: Session = Depends(get_db)):
    service = PlatformUsersService(db, actor)
    return ApiResponse(
        message="Usuario desactivado.",
        data=service.desactivar(user_id),
    )


@router.post("/users/{user_id}/activate", response_model=ApiResponse[GlobalUserResponse])
def activate_user(user_id: UUID, actor: UserWriter, db: Session = Depends(get_db)):
    service = PlatformUsersService(db, actor)
    return ApiResponse(
        message="Usuario activado.",
        data=service.activar(user_id),
    )


@router.get("/admins", response_model=ApiResponse[list[GlobalUserResponse]])
def list_admins(actor: Writer, db: Session = Depends(get_db)):
    service = PlatformUsersService(db, actor)
    return ApiResponse(
        message="Operación completada.",
        data=service.listar_admins(),
    )


@router.post("/admins", status_code=201, response_model=ApiResponse[GlobalUserResponse])
def invite_admin(
    data: PlatformAdminInvite,
    actor: Writer,
    db: Session = Depends(get_db),
):
    service = PlatformUsersService(db, actor)
    return ApiResponse(
        message="Administrador invitado exitosamente.",
        data=service.invitar_admin(data),
    )


@router.post("/admins/{user_id}/deactivate", response_model=ApiResponse[GlobalUserResponse])
def deactivate_admin(
    user_id: UUID,
    actor: Writer,
    db: Session = Depends(get_db),
):
    service = PlatformUsersService(db, actor)
    return ApiResponse(
        message="Administrador desactivado.",
        data=service.desactivar_admin(user_id),
    )


@router.post("/admins/{user_id}/activate", response_model=ApiResponse[GlobalUserResponse])
def activate_admin(
    user_id: UUID,
    actor: Writer,
    db: Session = Depends(get_db),
):
    service = PlatformUsersService(db, actor)
    return ApiResponse(
        message="Administrador reactivado exitosamente.",
        data=service.activar_admin(user_id),
    )


@router.patch("/admins/{user_id}", response_model=ApiResponse[GlobalUserResponse])
def update_admin(
    user_id: UUID,
    body: GlobalUserUpdate,
    actor: Writer,
    db: Session = Depends(get_db),
):
    service = PlatformUsersService(db, actor)
    return ApiResponse(
        message="Administrador actualizado exitosamente.",
        data=service.actualizar(user_id, body),
    )


@router.delete("/admins/{user_id}", response_model=ApiResponse[bool])
def delete_admin(
    user_id: UUID,
    actor: Writer,
    db: Session = Depends(get_db),
):
    service = PlatformUsersService(db, actor)
    return ApiResponse(
        message="Administrador eliminado exitosamente.",
        data=service.eliminar_admin(user_id),
    )


@router.post("/admins/{user_id}/reset-password", response_model=ApiResponse[GlobalUserResponse])
def reset_admin_password(
    user_id: UUID,
    actor: Writer,
    db: Session = Depends(get_db),
):
    service = PlatformUsersService(db, actor)
    return ApiResponse(
        message="Enlace de restablecimiento enviado.",
        data=service.restablecer_contrasena(user_id),
    )
