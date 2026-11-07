from datetime import datetime, timezone
from decimal import Decimal
import uuid
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.inventario_sucursales.infrastructure.models.organization import BranchModel
from src.operacion_offline.infrastructure.models.sync import SyncConflictModel, SyncOperationModel
from src.operacion_offline.web.sync_schemas import (
    ConflictLineOut,
    ConflictOut,
    ConflictResolveIn,
    ConflictType,
    SyncOperationIn,
)
from src.shared.exceptions.domain_exception import ConflictError, NotFoundError, ValidationError
from src.usuarios_catalogo.infrastructure.models.catalog import ProductModel, ProductVariantModel
from src.ventas_pagos.infrastructure.models import StockModel


class ConflictService:
    def __init__(self, db: Session, ctx: Any, actor: UserModel) -> None:
        self.db = db
        self.ctx = ctx
        self.actor = actor
        self.tenant_id = ctx.tenant_id

    def listar(
        self,
        *,
        branch_id: uuid.UUID | None = None,
        status: Literal["OPEN", "RESOLVED"] = "OPEN",
        type: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        query = select(SyncConflictModel).where(
            SyncConflictModel.tenant_id == self.tenant_id,
            SyncConflictModel.status == status,
        )
        if branch_id:
            query = query.where(SyncConflictModel.branch_id == branch_id)
        if type:
            query = query.where(SyncConflictModel.type == type)

        total = len(self.db.scalars(query).all())
        offset = (page - 1) * page_size
        conflicts = self.db.scalars(query.order_by(SyncConflictModel.created_at.desc()).offset(offset).limit(page_size)).all()

        items = [self._to_out(c) for c in conflicts]
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if page_size else 1,
        }

    def obtener(self, conflict_id: uuid.UUID) -> ConflictOut:
        conflict = self.db.scalar(
            select(SyncConflictModel).where(
                SyncConflictModel.id == conflict_id,
                SyncConflictModel.tenant_id == self.tenant_id,
            )
        )
        if not conflict:
            raise NotFoundError("Conflicto no encontrado.")
        return self._to_out(conflict)

    def resolver(self, conflict_id: uuid.UUID, data: ConflictResolveIn) -> ConflictOut:
        conflict = self.db.scalar(
            select(SyncConflictModel).where(
                SyncConflictModel.id == conflict_id,
                SyncConflictModel.tenant_id == self.tenant_id,
            ).with_for_update().execution_options(populate_existing=True)
        )
        if not conflict:
            raise NotFoundError("Conflicto no encontrado.")
        if conflict.status == "RESOLVED":
            raise ConflictError("El conflicto ya fue resuelto previamente.")

        op = self.db.get(SyncOperationModel, conflict.operation_id)
        if not op:
            raise NotFoundError("Operación asociada no encontrada.")

        from src.operacion_offline.application.sync_service import OfflineSaleService

        now = datetime.now(timezone.utc)
        if data.action != "CANCEL":
            from src.plataforma_saas.application.plan_guard import PlanGuard
            PlanGuard(self.db).exigir_funcion(self.tenant_id, "offline")

        if op.type == "RESERVATION" and data.action in ("ADJUST", "RETRY"):
            from src.reservas.application.use_cases.create_reserva import CrearReserva
            from src.reservas.infrastructure.http.schemas import CrearReservaRequest
            if data.action == "ADJUST" and conflict.type != "STOCK":
                raise ValidationError("Solo se pueden ajustar cantidades en un conflicto de existencias.")
            payload = dict(op.payload)
            if data.action == "ADJUST":
                if not data.quantities:
                    raise ValidationError("Indicá las cantidades que querés conservar.")
                quantities = {str(key): value for key, value in data.quantities.items()}
                original = {item["variant_id"]: item["quantity"] for item in payload["items"]}
                if any(key not in original or value < 0 or value > original[key] for key, value in quantities.items()):
                    raise ValidationError("Las cantidades ajustadas deben estar dentro de la reserva original.")
                payload["items"] = [
                    {**item, "quantity": quantities.get(item["variant_id"], item["quantity"])}
                    for item in payload["items"]
                    if quantities.get(item["variant_id"], item["quantity"]) > 0
                ]
                if not payload["items"]:
                    raise ValidationError("Conservá al menos una prenda o rechazá la reserva.")
            customer = self.db.get(UserModel, op.user_id)
            if not customer or customer.tenant_id != self.tenant_id:
                raise NotFoundError("El responsable de la reserva no pertenece a esta empresa.")
            reservation = CrearReserva(self.db, tenant_id=self.tenant_id).execute(
                customer, CrearReservaRequest(**payload), commit=False
            )
            op.status, op.server_ref, op.server_number = "CONFIRMED", reservation.id, str(reservation.id)[:8].upper()
            op.resolved_at = now
            conflict.status, conflict.resolution = "RESOLVED", data.action
            conflict.resolution_note, conflict.resolved_by, conflict.resolved_at = data.note, self.actor.id, now
        elif data.action == "CANCEL":
            op.status = "REJECTED"
            op.reason_code = "cancelled_by_manager"
            op.message = f"Cancelado por el encargado: {data.note}"
            op.resolved_at = now

            conflict.status = "RESOLVED"
            conflict.resolution = "CANCEL"
            conflict.resolution_note = data.note
            conflict.resolved_by = self.actor.id
            conflict.resolved_at = now

        elif data.action == "AUTHORIZE_PRICE":
            if conflict.type != "PRICE":
                raise ValidationError("AUTHORIZE_PRICE solo aplica a conflictos de precio (PRICE).")
            sale_svc = OfflineSaleService(self.db, self.tenant_id)
            op_in = SyncOperationIn(
                client_request_id=op.client_request_id,
                type="SALE",
                branch_id=op.branch_id,  # type: ignore
                device_id=op.device_id,
                client_created_at=datetime.fromisoformat(op.payload["_client_created_at"]) if op.payload.get("_client_created_at") else op.first_received_at,
                payload=op.payload,
            )
            order = sale_svc.confirmar(op_in, self.actor, precio_autorizado=True)
            op.status = "CONFIRMED"
            op.server_ref = order.id
            op.server_number = order.number
            op.resolved_at = now

            conflict.status = "RESOLVED"
            conflict.resolution = "AUTHORIZE_PRICE"
            conflict.resolution_note = data.note
            conflict.resolved_by = self.actor.id
            conflict.resolved_at = now

        elif data.action == "ADJUST":
            if conflict.type != "STOCK":
                raise ValidationError("ADJUST solo aplica a conflictos de stock (STOCK).")
            if not data.quantities:
                raise ValidationError("ADJUST requiere el diccionario de cantidades ajustadas.")

            sale_svc = OfflineSaleService(self.db, self.tenant_id)
            op_in = SyncOperationIn(
                client_request_id=op.client_request_id,
                type="SALE",
                branch_id=op.branch_id,  # type: ignore
                device_id=op.device_id,
                client_created_at=datetime.fromisoformat(op.payload["_client_created_at"]) if op.payload.get("_client_created_at") else op.first_received_at,
                payload=op.payload,
            )
            order = sale_svc.confirmar(op_in, self.actor, ajustes=data.quantities)
            orig_total = Decimal(str(op.payload.get("total", "0.00")))
            refund = max(Decimal("0.00"), orig_total - order.total)
            order.offline_adjustment = {
                "original_total": str(orig_total),
                "adjusted_total": str(order.total),
                "refund_amount": str(refund),
                "note": data.note,
            }

            op.status = "CONFIRMED"
            op.server_ref = order.id
            op.server_number = order.number
            op.resolved_at = now

            conflict.status = "RESOLVED"
            conflict.resolution = "ADJUST"
            conflict.resolution_note = data.note
            conflict.resolved_by = self.actor.id
            conflict.resolved_at = now

        elif data.action == "RETRY":
            if conflict.type not in ("SUBSCRIPTION", "PRODUCT_INACTIVE"):
                raise ValidationError("RETRY solo aplica a conflictos de suscripción o producto inactivo.")
            # Reevaluar
            sale_svc = OfflineSaleService(self.db, self.tenant_id)
            op_in = SyncOperationIn(
                client_request_id=op.client_request_id,
                type="SALE",
                branch_id=op.branch_id,  # type: ignore
                device_id=op.device_id,
                client_created_at=datetime.fromisoformat(op.payload["_client_created_at"]) if op.payload.get("_client_created_at") else op.first_received_at,
                payload=op.payload,
            )
            order = sale_svc.confirmar(op_in, self.actor)
            op.status = "CONFIRMED"
            op.server_ref = order.id
            op.server_number = order.number
            op.resolved_at = now

            conflict.status = "RESOLVED"
            conflict.resolution = "RETRY"
            conflict.resolution_note = data.note
            conflict.resolved_by = self.actor.id
            conflict.resolved_at = now
        else:
            raise ValidationError(f"Acción {data.action} no soportada.")

        if op.status == "CONFIRMED":
            op.reason_code = None
            op.message = "Operación confirmada después de la revisión del encargado."
            if data.action == "ADJUST" and op.type == "SALE":
                op.message += f" Reintegro de efectivo pendiente: Bs {refund:.2f}."

        RecordAuditEvent(self.db).execute(
            action="sync.conflict_resolved",
            entity_type="sync_conflict",
            entity_id=str(conflict.id),
            description=f"Conflicto {conflict.id} resuelto con acción {data.action}.",
            actor_user_id=self.actor.id,
            metadata={"action": data.action, "note": data.note, "operation_id": str(op.id)},
        )
        self.db.commit()

        return self._to_out(conflict)

    def _to_out(self, c: SyncConflictModel) -> ConflictOut:
        op = self.db.get(SyncOperationModel, c.operation_id)
        branch = self.db.get(BranchModel, c.branch_id) if c.branch_id else None
        user = self.db.get(UserModel, op.user_id) if op and op.user_id else None
        resolver = self.db.get(UserModel, c.resolved_by) if c.resolved_by else None

        # Recalcular líneas con stock actual
        lines_out: list[ConflictLineOut] = []
        raw_lines = c.detail.get("lines", []) if isinstance(c.detail, dict) else []
        for line in raw_lines:
            vid_str = line.get("variant_id")
            if vid_str:
                vid = uuid.UUID(str(vid_str))
                stock_row = self.db.scalar(
                    select(StockModel).where(
                        StockModel.variant_id == vid,
                        StockModel.branch_id == c.branch_id,
                    )
                )
                variant = self.db.get(ProductVariantModel, vid)
                product = self.db.get(ProductModel, variant.product_id) if variant else None
                curr_price = variant.price_override if variant and variant.price_override is not None else (product.base_price if product else Decimal(0))
                avail = stock_row.quantity if stock_row else 0
                lines_out.append(
                    ConflictLineOut(
                        variant_id=vid,
                        product_name=line.get("product_name") or (product.name if product else "Prenda"),
                        requested_quantity=line.get("requested_quantity", 1),
                        available_quantity=avail,
                        unit_price=str(line.get("unit_price", curr_price)),
                        current_price=str(curr_price),
                    )
                )

        return ConflictOut(
            id=c.id,
            operation_id=c.operation_id,
            client_request_id=op.client_request_id if op else uuid.uuid4(),
            operation_type=op.type if op else "SALE",
            type=c.type,
            status=c.status,
            branch_id=c.branch_id,
            branch_name=branch.name if branch else None,
            cashier_name=f"{user.first_name} {user.last_name}".strip() if user else None,
            device_id=op.device_id if op else None,
            local_folio=op.payload.get("local_folio") if op and isinstance(op.payload, dict) else None,
            created_at=c.created_at,
            lines=lines_out,
            resolution=c.resolution,
            resolution_note=c.resolution_note,
            resolved_by_name=f"{resolver.first_name} {resolver.last_name}".strip() if resolver else None,
            resolved_at=c.resolved_at,
        )
