import uuid
from math import ceil
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.web.dependencies import get_current_user
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_permissions
from src.reservas.application.use_cases.cancel_reserva import CancelarReserva
from src.reservas.application.use_cases.confirm_reserva import ActualizarEstadoReserva
from src.reservas.application.use_cases.create_reserva import CrearReserva
from src.reservas.application.use_cases.get_reserva import ObtenerReserva
from src.reservas.application.use_cases.list_reservas import ListarReservas
from src.reservas.infrastructure.http.schemas import CrearReservaRequest, EstadoReservaUpdate
from src.reservas.infrastructure.persistence.models.reserva import ReservationModel
from src.shared.responses.api_response import ApiResponse
from src.shared.responses.pagination import Page

router = APIRouter(prefix="/reservations", tags=["reservations"])
User = Annotated[UserModel, Depends(get_current_user)]
Reader = Annotated[UserModel, Depends(require_permissions("reservations.read"))]
Writer = Annotated[UserModel, Depends(require_permissions("reservations.write"))]


def reserva_data(reserva: ReservationModel) -> dict:
    return {
        "id": reserva.id,
        "user_id": reserva.user_id,
        "branch_id": reserva.branch_id,
        "status": reserva.status,
        "scheduled_at": reserva.scheduled_at,
        "items": reserva.items,
        "notes": reserva.notes,
        "tracking": reserva.tracking,
        "created_at": reserva.created_at,
        "updated_at": reserva.updated_at,
    }


@router.post("", status_code=201)
def create_reservation(data: CrearReservaRequest, user: User, db: Session = Depends(get_db)):
    reserva = CrearReserva(db).execute(user, data)
    return ApiResponse(message="Reserva registrada.", data=reserva_data(reserva))


@router.get("", response_model=ApiResponse[Page[dict]])
def list_my_reservations(
    user: User,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
):
    items, total = ListarReservas(db).execute(page=page, page_size=page_size, user_id=user.id, status=status)
    result = Page(items=[reserva_data(r) for r in items], total=total, page=page, page_size=page_size, pages=ceil(total / page_size) if total else 0)
    return ApiResponse(message="Reservas obtenidas.", data=result)


@router.get("/{reservation_id}")
def get_reservation(reservation_id: uuid.UUID, user: User, db: Session = Depends(get_db)):
    reserva = ObtenerReserva(db).execute(reservation_id, user_id=user.id)
    return ApiResponse(message="Reserva obtenida.", data=reserva_data(reserva))


@router.post("/{reservation_id}/cancel")
def cancel_reservation(reservation_id: uuid.UUID, user: User, db: Session = Depends(get_db)):
    reserva = ObtenerReserva(db).execute(reservation_id, user_id=user.id)
    reserva = CancelarReserva(db).execute(reserva, user)
    return ApiResponse(message="Reserva cancelada.", data=reserva_data(reserva))


@router.get("/admin/all", response_model=ApiResponse[Page[dict]])
def list_all_reservations(
    user: Reader,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    branch_id: uuid.UUID | None = None,
    status: str | None = None,
):
    items, total = ListarReservas(db).execute(page=page, page_size=page_size, branch_id=branch_id, status=status)
    result = Page(items=[reserva_data(r) for r in items], total=total, page=page, page_size=page_size, pages=ceil(total / page_size) if total else 0)
    return ApiResponse(message="Reservas obtenidas.", data=result)


@router.patch("/admin/{reservation_id}/status")
def update_reservation_status(reservation_id: uuid.UUID, data: EstadoReservaUpdate, user: Writer, db: Session = Depends(get_db)):
    reserva = ObtenerReserva(db).execute(reservation_id)
    reserva = ActualizarEstadoReserva(db).execute(reserva, data.status, user, data.note)
    return ApiResponse(message="Estado de la reserva actualizado.", data=reserva_data(reserva))
