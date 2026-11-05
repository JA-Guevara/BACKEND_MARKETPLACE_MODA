from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from src.infrastructure.database.session import get_db
from src.plataforma_saas.application.signup_service import (
    SignupRequest,
    SignupService,
    VerifyRequest,
)
from src.shared.responses.api_response import ApiResponse


router = APIRouter(prefix="/public/signup", tags=["Alta Autoservicio"])


@router.post("", response_model=ApiResponse[dict])
def solicitar_alta(
    data: SignupRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    client_ip = request.client.host if request.client else None
    service = SignupService(db)
    result = service.solicitar(data, client_ip=client_ip)
    return ApiResponse(
        message=result.get("message", "Solicitud procesada."),
        data=result,
    )


@router.post("/verify", response_model=ApiResponse[dict])
def verificar_alta(
    data: VerifyRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    client_ip = request.client.host if request.client else None
    service = SignupService(db)
    result = service.verificar(data.token, client_ip=client_ip)
    return ApiResponse(
        message=result.get("message", "Empresa verificada exitosamente."),
        data=result,
    )


@router.get("/slug", response_model=ApiResponse[dict])
def consultar_slug(
    name: str = "",
    db: Session = Depends(get_db),
):
    service = SignupService(db)
    slug, disponible, motivo = service.slug_disponible(name)
    return ApiResponse(
        data={
            "slug": slug,
            "available": disponible,
            "reason": motivo,
        }
    )
