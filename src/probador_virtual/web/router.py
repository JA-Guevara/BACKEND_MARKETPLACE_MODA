from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.web.dependencies import get_current_user
from src.infrastructure.database.session import get_db
from src.probador_virtual.application.use_cases.iniciar_experiencia import IniciarExperiencia
from src.probador_virtual.infrastructure.http.schemas import ExperienciaVirtualResponse, IniciarExperienciaRequest
from src.shared.responses.api_response import ApiResponse

router = APIRouter(prefix="/vestidor", tags=["vestidor virtual"])
User = Annotated[UserModel, Depends(get_current_user)]


@router.post("/sessions", response_model=ApiResponse[ExperienciaVirtualResponse])
def start_session(data: IniciarExperienciaRequest, user: User, db: Session = Depends(get_db)):
    experiencia = IniciarExperiencia(db).execute(data.product_id, user)
    return ApiResponse(message="Vestidor virtual listo.", data=experiencia)
