"""Endpoints del probador de foto IA realista (plan de evolución, Fase 3).

Los trabajos son de cliente autenticado: el usuario puede crear, consultar,
cancelar y eliminar sus fotos. La creación vuelve al instante con el trabajo en
`queued`; la generación ocurre cuando se consulta el estado.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.web.dependencies import get_current_user
from src.infrastructure.config.settings import settings
from src.infrastructure.database.session import get_db
from src.tryon_ai_jobs.application.use_cases.consultar_trabajo import ConsultarTrabajo
from src.tryon_ai_jobs.application.use_cases.crear_trabajo import CrearTrabajo
from src.tryon_ai_jobs.application.use_cases.gestionar_trabajos import (
    CancelarTrabajo,
    EliminarTrabajo,
    ListarTrabajos,
)
from src.tryon_ai_jobs.infrastructure.http.schemas import TryOnJobResponse
from src.shared.exceptions.domain_exception import ValidationError
from src.shared.responses.api_response import ApiResponse

router = APIRouter(prefix="/tryon-ai", tags=['PAQ-03 · Reservas y vestidor virtual'])
User = UserModel
Authenticated = Annotated[User, Depends(get_current_user)]


@router.post("/jobs", response_model=ApiResponse[TryOnJobResponse])
def crear_trabajo(
    user: Authenticated,
    db: Session = Depends(get_db),
    file: UploadFile = File(description="Foto de la persona (JPG o PNG)."),
    product_id: uuid.UUID = Form(),
    color_id: uuid.UUID | None = Form(default=None),
    privacy_consent: bool = Form(description="Consentimiento para procesar la foto."),
):
    """Pide una foto IA realista de la prenda. Devuelve el trabajo en `queued`;
    el estado se consulta en GET /tryon-ai/jobs/{id}, donde corre la generación.
    Este endpoint no bloquea la cámara: la foto vive en el servidor mientras el
    trabajo esté vigente y se borra al cancelar, expirar o eliminar."""
    if not file.content_type or not (file.content_type.startswith("image/")):
        raise ValidationError("La foto de la persona tiene que ser una imagen.")
    contenido = file.file.read()
    if not contenido:
        raise ValidationError("La foto de la persona viene vacía.")
    proveedor = settings.tryon_provider
    if proveedor not in ("none", "mock", "fashn"):
        proveedor = "none"
    trabajo = CrearTrabajo(db).execute(
        user,
        product_id,
        color_id,
        contenido,
        consentimiento=privacy_consent,
        proveedor=proveedor,
    )
    return ApiResponse(message="Foto IA en curso.", data=trabajo)


@router.get("/jobs", response_model=ApiResponse[list[TryOnJobResponse]])
def listar_trabajos(user: Authenticated, db: Session = Depends(get_db)):
    """Historial de fotos IA pedidas por el usuario, de más nuevas a más viejas."""
    trabajos = ListarTrabajos(db).execute(user)
    return ApiResponse(message="Trabajos obtenidos.", data=trabajos)


@router.get("/jobs/{job_id}", response_model=ApiResponse[TryOnJobResponse])
def consultar_trabajo(job_id: uuid.UUID, user: Authenticated, db: Session = Depends(get_db)):
    """Estado del trabajo: dispara la generación si estaba pendiente y marca
    como expirado (y borra las imágenes) si pasó el plazo."""
    trabajo = ConsultarTrabajo(db).execute(user, job_id)
    return ApiResponse(message="Trabajo obtenido.", data=trabajo)


@router.patch("/jobs/{job_id}/cancel", response_model=ApiResponse[TryOnJobResponse])
def cancelar_trabajo(job_id: uuid.UUID, user: Authenticated, db: Session = Depends(get_db)):
    """Cancela un trabajo en curso y elimina la foto de la persona del servidor."""
    trabajo = CancelarTrabajo(db).execute(user, job_id)
    return ApiResponse(message="Trabajo cancelado; la foto se eliminó.", data=trabajo)


@router.delete("/jobs/{job_id}", status_code=204)
def eliminar_trabajo(job_id: uuid.UUID, user: Authenticated, db: Session = Depends(get_db)):
    """Elimina el trabajo y sus imágenes del servidor sin dejar rastro en los
    archivos."""
    EliminarTrabajo(db).execute(user, job_id)
    return None
