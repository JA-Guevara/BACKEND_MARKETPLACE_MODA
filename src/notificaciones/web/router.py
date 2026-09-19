"""Avisos del cliente, para la campanita de la barra superior."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.web.dependencies import get_current_user
from src.infrastructure.database.session import get_db
from src.notificaciones.application.use_cases.consultar_avisos import ConsultarAvisos
from src.shared.responses.api_response import ApiResponse

router = APIRouter(prefix="/notifications", tags=["notifications"])
User = Annotated[UserModel, Depends(get_current_user)]


@router.get("")
def avisos(user: User, db: Session = Depends(get_db), limit: int = Query(20, ge=1, le=50)):
    """Lo que le paso a esta persona: pedidos, reservas y devoluciones.

    Se deriva del historial que ya guarda cada operacion, asi que no hay estado
    que mantener sincronizado ni tabla nueva que migrar.
    """
    return ApiResponse(
        message="Operacion completada.",
        data=jsonable_encoder(ConsultarAvisos(db).execute(user, limit)),
    )
