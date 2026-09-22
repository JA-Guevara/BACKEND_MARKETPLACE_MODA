from datetime import datetime
import uuid
from math import ceil
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.web.dependencies import get_current_user
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_permissions
from src.inventario_sucursales.infrastructure.models.organization import BranchModel
from src.usuarios_catalogo.infrastructure.models.catalog import ProductVariantModel
from src.reservas.application.use_cases.cancel_reserva import CancelarReserva
from src.reservas.application.use_cases.confirm_reserva import ActualizarEstadoReserva
from src.reservas.application.use_cases.consultar_disponibilidad import ConsultarDisponibilidad
from src.reservas.application.use_cases.create_reserva import CrearReserva
from src.reservas.application.use_cases.get_reserva import ObtenerReserva
from src.reservas.application.use_cases.list_reservas import ListarReservas
from src.reservas.infrastructure.http.schemas import CrearReservaRequest, EstadoReservaUpdate
from src.reservas.infrastructure.persistence.models.reserva import ReservationModel
from src.shared.responses.api_response import ApiResponse
from src.shared.responses.pagination import Page

router = APIRouter(prefix="/reservations", tags=['PAQ-03 · Reservas y vestidor virtual'])
User = Annotated[UserModel, Depends(get_current_user)]
Reader = Annotated[UserModel, Depends(require_permissions("reservations.read"))]
Writer = Annotated[UserModel, Depends(require_permissions("reservations.write"))]


def _items_visibles(db: Session, reserva: ReservationModel) -> list[dict]:
    """Completa reservas históricas que solo guardaban el identificador.

    Las reservas actuales ya contienen el snapshot de cada prenda. Las más
    antiguas solo guardaban ``variant_id`` y el cliente veía una cantidad sin
    nombre, talla ni color. Esto completa la respuesta sin alterar el historial
    persistido de la reserva.
    """
    result = []
    for original in reserva.items or []:
        item = dict(original) if isinstance(original, dict) else {}
        variant_id = item.get("variant_id")
        if variant_id and not item.get("name"):
            try:
                variant = db.get(ProductVariantModel, uuid.UUID(str(variant_id)))
            except (TypeError, ValueError):
                variant = None
            if variant and variant.product:
                item.update({
                    "product_id": str(variant.product_id),
                    "name": variant.product.name,
                    "sku": variant.sku,
                    "size": variant.size.name if variant.size else "",
                    "color": variant.color.name if variant.color else "",
                    "image_url": variant.product.images[0].url if variant.product.images else None,
                })
        result.append(item)
    return result


def reserva_data(reserva: ReservationModel, db: Session, branch: BranchModel | None = None) -> dict:
    branch = branch or db.get(BranchModel, reserva.branch_id)
    return {
        "id": reserva.id,
        "user_id": reserva.user_id,
        "branch_id": reserva.branch_id,
        "status": reserva.status,
        "scheduled_at": reserva.scheduled_at,
        "items": _items_visibles(db, reserva),
        "notes": reserva.notes,
        "tracking": reserva.tracking,
        "created_at": reserva.created_at,
        "updated_at": reserva.updated_at,
        "inventory_held": reserva.inventory_held,
        "branch_name": branch.name if branch else None,
    }


def _user_data(users: dict, reservation: ReservationModel) -> dict:
    user = users.get(reservation.user_id)
    if not user:
        return {}
    return {
        "user_name": f"{user.first_name} {user.last_name}".strip(),
        "user_email": user.email,
    }


@router.post("", status_code=201)
def create_reservation(data: CrearReservaRequest, user: User, db: Session = Depends(get_db)):
    reserva = CrearReserva(db).execute(user, data)
    branch = db.get(BranchModel, reserva.branch_id)
    return ApiResponse(
        message="Reserva registrada.",
        data=reserva_data(reserva, db, branch),
    )


@router.get("/availability")
def check_availability(
    user: User,
    branch_id: uuid.UUID,
    variant_ids: Annotated[list[uuid.UUID], Query()],
    quantities: Annotated[list[int] | None, Query()] = None,
    db: Session = Depends(get_db),
):
    """Indica, por cada talla pedida, si la sucursal elegida alcanza para las
    cantidades solicitadas. ``quantities`` (opcional) viaja alineado y por la
    misma posición que ``variant_ids``."""
    datos = ConsultarDisponibilidad(db).execute(branch_id, variant_ids, quantities)
    return ApiResponse(message="Disponibilidad obtenida.", data=datos)


@router.get("", response_model=ApiResponse[Page[dict]])
def list_my_reservations(
    user: User,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
):
    items, total = ListarReservas(db).execute(page=page, page_size=page_size, user_id=user.id, status=status)
    branches = {b.id: b for b in db.query(BranchModel).filter(BranchModel.id.in_({r.branch_id for r in items})).all()} if items else {}
    result = Page(
        items=[reserva_data(r, db, branches.get(r.branch_id)) for r in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=ceil(total / page_size) if total else 0,
    )
    return ApiResponse(message="Reservas obtenidas.", data=result)


@router.get("/{reservation_id}")
def get_reservation(reservation_id: uuid.UUID, user: User, db: Session = Depends(get_db)):
    reserva = ObtenerReserva(db).execute(reservation_id, user_id=user.id)
    return ApiResponse(message="Reserva obtenida.", data=reserva_data(reserva, db))


@router.post("/{reservation_id}/cancel")
def cancel_reservation(reservation_id: uuid.UUID, user: User, db: Session = Depends(get_db)):
    reserva = ObtenerReserva(db).execute(reservation_id, user_id=user.id)
    reserva = CancelarReserva(db).execute(reserva, user)
    return ApiResponse(message="Reserva cancelada.", data=reserva_data(reserva, db))


@router.get("/admin/all", response_model=ApiResponse[Page[dict]])
def list_all_reservations(
    user: Reader,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    branch_id: uuid.UUID | None = None,
    status: str | None = None,
    q: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    order: str = Query("scheduled_at", pattern="^(scheduled_at|created_at)$"),
    direction: str = Query("desc", pattern="^(asc|desc)$"),
):
    items, total = ListarReservas(db).execute(
        page=page,
        page_size=page_size,
        branch_id=branch_id,
        status=status,
        q=q,
        date_from=date_from,
        date_to=date_to,
        order=order,
        direction=direction,
    )
    branches = {b.id: b for b in db.query(BranchModel).filter(BranchModel.id.in_({r.branch_id for r in items})).all()} if items else {}
    users = {u.id: u for u in db.query(UserModel).filter(UserModel.id.in_({r.user_id for r in items})).all()} if items else {}
    result = Page(
        items=[
            {
                **reserva_data(r, db, branches.get(r.branch_id)),
                **_user_data(users, r),
            }
            for r in items
        ],
        total=total,
        page=page,
        page_size=page_size,
        pages=ceil(total / page_size) if total else 0,
    )
    return ApiResponse(message="Reservas obtenidas.", data=result)


@router.patch("/admin/{reservation_id}/status")
def update_reservation_status(reservation_id: uuid.UUID, data: EstadoReservaUpdate, user: Writer, db: Session = Depends(get_db)):
    reserva = ObtenerReserva(db).execute(reservation_id)
    reserva = ActualizarEstadoReserva(db).execute(reserva, data.status, user, data.note)
    return ApiResponse(message="Estado de la reserva actualizado.", data=reserva_data(reserva, db))

