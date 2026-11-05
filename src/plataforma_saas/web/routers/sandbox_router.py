from typing import Annotated
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_platform_permissions
from src.plataforma_saas.application.sandbox_service import SandboxService
from src.plataforma_saas.web.schemas.governance import PreviewIn, SandboxOut
from src.plataforma_saas.web.schemas.support import SupportSessionStart
from src.shared.responses.api_response import ApiResponse

router = APIRouter(prefix="/platform/sandbox", tags=["PAQ-06 · Sandbox Empresa Demo"])
SandboxAdmin = Annotated[UserModel, Depends(require_platform_permissions("sandbox.manage"))]
SandboxViewer = Annotated[UserModel, Depends(require_platform_permissions("modules.read"))]


@router.get("", response_model=ApiResponse[SandboxOut])
def get_sandbox(
    actor: SandboxViewer,
    db: Session = Depends(get_db),
):
    service = SandboxService(db, actor=actor)
    return ApiResponse(
        message="Estado de la empresa demo obtenido.",
        data=service.estado(),
    )


@router.post(
    "/preview",
    response_model=ApiResponse[SupportSessionStart],
    status_code=status.HTTP_201_CREATED,
)
def preview_module(
    body: PreviewIn,
    actor: SandboxAdmin,
    db: Session = Depends(get_db),
):
    service = SandboxService(db, actor=actor)
    return ApiResponse(
        message="Vista previa iniciada en la empresa demo.",
        data=service.vista_previa(body.module_code),
    )


@router.post("/reset", response_model=ApiResponse[SandboxOut])
def reset_sandbox(
    actor: SandboxAdmin,
    db: Session = Depends(get_db),
    confirm: bool = True,
):
    service = SandboxService(db, actor=actor)
    return ApiResponse(
        message="Empresa demo restablecida.",
        data=service.restablecer(confirm=confirm),
    )
