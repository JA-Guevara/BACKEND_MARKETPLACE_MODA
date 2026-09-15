from collections import Counter
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.inventario_sucursales.infrastructure.models.organization import BranchModel
from src.reservas.application.dto.reserva_dto import ReservaItemSnapshot
from src.reservas.application.use_cases.consultar_disponibilidad import ConsultarDisponibilidad
from src.reservas.domain.entities.horario import validar_horario
from src.reservas.infrastructure.http.schemas import CrearReservaRequest
from src.reservas.infrastructure.persistence.models.reserva import ReservationModel
from src.reservas.infrastructure.persistence.repositories.reserva_repository import ReservaRepository
from src.shared.exceptions.domain_exception import NotFoundError, ValidationError
from src.usuarios_catalogo.infrastructure.models.catalog import ProductVariantModel

MAX_ITEMS_AFTER_MERGE = 20


class CrearReserva:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = ReservaRepository(db)

    def _branch(self, branch_id) -> BranchModel:
        branch = self.db.get(BranchModel, branch_id)
        if not branch or not branch.is_active or branch.deleted_at:
            raise ValidationError("Sucursal no disponible.")
        return branch

    def _snapshot(self, variant_id, quantity: int) -> ReservaItemSnapshot:
        variant = self.db.get(ProductVariantModel, variant_id)
        if not variant or not variant.is_active or not variant.product.is_active or variant.product.deleted_at:
            raise NotFoundError("Una de las prendas seleccionadas ya no esta disponible.")
        return ReservaItemSnapshot(
            variant_id=str(variant.id),
            product_id=str(variant.product_id),
            name=variant.product.name,
            sku=variant.sku,
            size=variant.size.name,
            color=variant.color.name,
            image_url=variant.product.images[0].url if variant.product.images else None,
            quantity=quantity,
        )

    def _merge_items(self, items) -> list[dict]:
        """Suma las cantidades de una misma talla/color repetida y respeta los
        límites tras la fusión (RF09: hasta 20 variantes distintas, 1 a 10 que
        quedan por cada variante tras agrupar)."""
        cantidades: Counter = Counter()
        for item in items:
            cantidades[item.variant_id] += item.quantity
        if len(cantidades) > MAX_ITEMS_AFTER_MERGE:
            raise ValidationError("La reserva no puede incluir mas de 20 prendas distintas.")
        if any(quantity > 10 for quantity in cantidades.values()):
            raise ValidationError("No se puede reservar mas de 10 unidades de una misma talla.")
        return [
            {"variant_id": variant_id, "quantity": quantity}
            for variant_id, quantity in cantidades.items()
        ]

    def _validar_disponibilidad(self, branch_id, items) -> None:
        """La reserva sirve para probarse una talla puntual: si la sucursal no la
        tiene, o no alcanza para la cantidad pedida, se rechaza con el detalle
        en vez de hacer viajar al cliente."""
        disponibilidad = ConsultarDisponibilidad(self.db).execute(
            branch_id, [item["variant_id"] for item in items], [item["quantity"] for item in items]
        )
        faltantes = [d for d in disponibilidad if not d["available"]]
        if faltantes:
            detalle = ", ".join(
                f"{d['product']} talla {d['size']}" if d.get("product") else "una de las prendas"
                for d in faltantes
            )
            motivo = faltantes[0].get("reason") or "no la tiene disponible"
            raise ValidationError(
                f"La sucursal elegida no tiene disponible: {detalle}. Motivo: {motivo} "
                "Quitá esas prendas, reducí la cantidad o elegí otra sucursal."
            )

    def _same_payload(self, existing: ReservationModel, data: CrearReservaRequest) -> bool:
        """La clave idempotente reutiliza la reserva registrada SOLO cuando el
        detalle coincide; si llega la misma clave con prendas/horario distintos,
        se avisa en vez de devolver en silencio la reserva anterior."""
        if existing.branch_id != data.branch_id:
            return False
        if existing.scheduled_at != data.scheduled_at:
            return False
        try:
            merged = self._merge_items(data.items)
        except ValidationError:
            return False
        request_spec = sorted((str(i["variant_id"]), int(i["quantity"])) for i in merged)
        stored_spec = sorted((str(i["variant_id"]), int(i["quantity"])) for i in existing.items)
        return request_spec == stored_spec

    def _ensure_same_payload(self, existing: ReservationModel, data: CrearReservaRequest) -> None:
        if not self._same_payload(existing, data):
            raise ValidationError(
                "Ese intento ya corresponde a una reserva registrada con otras prendas u horario. "
                "Revisá Mis reservas o cancelá esa reserva para crear una nueva."
            )

    def execute(self, user: UserModel, data: CrearReservaRequest) -> ReservationModel:
        if data.client_key:
            existing = self.repository.get_by_client_key(user.id, data.client_key)
            if existing:
                self._ensure_same_payload(existing, data)
                return existing

        self._branch(data.branch_id)
        validar_horario(data.scheduled_at)
        items = self._merge_items(data.items)
        self._validar_disponibilidad(data.branch_id, items)
        snapshot = [self._snapshot(item["variant_id"], item["quantity"]).as_dict() for item in items]
        reserva = ReservationModel(
            user_id=user.id,
            branch_id=data.branch_id,
            status="pending",
            scheduled_at=data.scheduled_at,
            items=snapshot,
            notes=data.notes,
            client_key=data.client_key,
            tracking=[
                {
                    "status": "pending",
                    "note": "Reserva registrada; pendiente de confirmacion de la sucursal.",
                    "date": datetime.now(timezone.utc).isoformat(),
                }
            ],
        )
        try:
            self.repository.add(reserva)
            RecordAuditEvent(self.db).execute(
                action="reservas.created",
                entity_type="reservation",
                entity_id=str(reserva.id),
                description="Reserva de prendas registrada para probar en sucursal.",
                actor_user_id=user.id,
                metadata={"branch_id": str(data.branch_id), "items": len(snapshot), "scheduled_at": data.scheduled_at.isoformat()},
            )
            self.db.commit()
        except IntegrityError:
            # La colision cubre tambien el flush() de repository.add: dos hilos
            # con la misma clave idempotente pueden llegar a anotarse a la vez;
            # la restriccion unica gana y se devuelve la ya persistida.
            self.db.rollback()
            if data.client_key:
                existing = self.repository.get_by_client_key(user.id, data.client_key)
                if existing:
                    self._ensure_same_payload(existing, data)
                    return existing
            raise
        self.db.refresh(reserva)
        return reserva