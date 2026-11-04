from typing import Annotated, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_platform_permissions
from src.plataforma_saas.application.platform_users_service import PlatformUsersService
from src.plataforma_saas.web.schemas.console import GlobalUserResponse
from src.plataforma_saas.web.schemas.platform_users import PlatformAdminInvite
from src.shared.responses.api_response import ApiResponse
from src.shared.responses.pagination import Page

router = APIRouter(prefix="/platform", tags=["PAQ-06 · Consola SaaS"])

Reader = Annotated[UserModel, Depends(require_platform_permissions("platform_users.read"))]
Writer = Annotated[UserModel, Depends(require_platform_permissions("platform_users.write"))]


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


@router.post("/users/{user_id}/unlock", response_model=ApiResponse[GlobalUserResponse])
def unlock_user(user_id: UUID, actor: Writer, db: Session = Depends(get_db)):
    service = PlatformUsersService(db, actor)
    return ApiResponse(
        message="Usuario desbloqueado.",
        data=service.desbloquear(user_id),
    )


@router.post("/users/{user_id}/resend-verification", response_model=ApiResponse[GlobalUserResponse])
def resend_verification(user_id: UUID, actor: Writer, db: Session = Depends(get_db)):
    service = PlatformUsersService(db, actor)
    return ApiResponse(
        message="Enlace de verificación enviado.",
        data=service.reenviar_verificacion(user_id),
    )


@router.post("/users/{user_id}/revoke-sessions", response_model=ApiResponse[GlobalUserResponse])
def revoke_sessions(user_id: UUID, actor: Writer, db: Session = Depends(get_db)):
    service = PlatformUsersService(db, actor)
    return ApiResponse(
        message="Sesiones revocadas.",
        data=service.cerrar_sesiones(user_id),
    )


@router.post("/users/{user_id}/deactivate", response_model=ApiResponse[GlobalUserResponse])
def deactivate_user(user_id: UUID, actor: Writer, db: Session = Depends(get_db)):
    service = PlatformUsersService(db, actor)
    return ApiResponse(
        message="Usuario desactivado.",
        data=service.desactivar(user_id),
    )


@router.post("/users/{user_id}/activate", response_model=ApiResponse[GlobalUserResponse])
def activate_user(user_id: UUID, actor: Writer, db: Session = Depends(get_db)):
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
        message="Super administrador invitado.",
        data=service.invitar_admin(data),
    )


@router.post("/admins/{user_id}/deactivate", response_model=ApiResponse[GlobalUserResponse])
def deactivate_admin(user_id: UUID, actor: Writer, db: Session = Depends(get_db)):
    service = PlatformUsersService(db, actor)
    return ApiResponse(
        message="Super administrador desactivado.",
        data=service.desactivar_admin(user_id),
    )
