from datetime import datetime, timezone
from typing import Any
from decimal import Decimal
import hashlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.inventario_sucursales.infrastructure.models.organization import BranchModel, CashPointModel
from src.operacion_offline.infrastructure.models.sync import (
    SyncBatchModel,
    SyncConflictModel,
    SyncOperationModel,
)
from src.operacion_offline.web.sync_schemas import (
    ConflictType,
    OperationStatus,
    SyncBatchDetailOut,
    SyncBatchIn,
    SyncBatchLogOut,
    SyncBatchOut,
    SyncOperationIn,
    SyncOperationSummaryOut,
    SyncResultOut,
)
from src.reservas.application.use_cases.create_reserva import CrearReserva, ReservationStockError
from src.reservas.infrastructure.http.schemas import CrearReservaRequest
from src.infrastructure.security.authorization import get_permission_codes
from src.shared.exceptions.domain_exception import (
    AppException,
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from src.shared.context.audit_context import get_audit_request_id
from src.usuarios_catalogo.infrastructure.models.catalog import ProductModel, ProductVariantModel
from src.ventas_pagos.application.stock_service import StockService
from src.ventas_pagos.domain.promociones import precio_final, vigente_en
from src.ventas_pagos.infrastructure.engagement_models import PromotionModel, PromotionUseModel
from src.ventas_pagos.infrastructure.models import OrderModel, StockModel


class SyncConflictException(ConflictError):
    def __init__(self, conflict_type: ConflictType, message: str, detail: dict):
        super().__init__(message)
        self.conflict_type = conflict_type
        self.detail = detail


def _canonical_hash(op: SyncOperationIn) -> str:
    raw = {
        "client_request_id": str(op.client_request_id),
        "type": op.type,
        "branch_id": str(op.branch_id),
        "client_created_at": op.client_created_at.isoformat(),
        "payload": op.payload,
    }
    encoded = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class OfflineSaleService:
    def __init__(self, db: Session, tenant_id: uuid.UUID):
        self.db = db
        self.tenant_id = tenant_id

    def confirmar(
        self,
        op: SyncOperationIn,
        actor: UserModel,
        ajustes: dict[uuid.UUID, int] | None = None,
        precio_autorizado: bool = False,
    ) -> OrderModel:
        payload = op.payload
        branch_id = op.branch_id

        # 1. Validar sucursal
        branch = self.db.scalar(
            select(BranchModel).where(BranchModel.id == branch_id, BranchModel.tenant_id == self.tenant_id)
        )
        if not branch:
            raise NotFoundError(f"Sucursal {branch_id} no encontrada en la empresa.")

        # 2. Validar o resolver usuario/cajero
        user_id_val = payload.get("user_id")
        user_id = uuid.UUID(str(user_id_val)) if user_id_val else actor.id

        customer_id_val = payload.get("customer_id")
        customer_id = uuid.UUID(str(customer_id_val)) if customer_id_val else None

        # 3. Validar items, variantes, stock y precio
        items_in = payload.get("items", [])
        if not items_in:
            raise ValidationError("La venta no contiene prendas.")

        order_items = []
        stock_changes = []
        subtotal = Decimal("0.00")
        conflict_lines = []
        stock_conflict = False
        price_conflict = False
        applied_offer_uses = []

        for it in items_in:
            vid = uuid.UUID(str(it["variant_id"]))
            variant = self.db.get(ProductVariantModel, vid)
            if not variant:
                raise NotFoundError(f"Variante {vid} no encontrada.")

            product = self.db.get(ProductModel, variant.product_id)
            if not product or product.tenant_id != self.tenant_id or not variant.is_active:
                raise SyncConflictException(
                    "PRODUCT_INACTIVE",
                    f"La prenda {variant.sku} está inactiva o ya no pertenece al catálogo.",
                    {"variant_id": str(vid), "sku": variant.sku},
                )

            ajustes_map = {str(k): v for k, v in ajustes.items()} if ajustes is not None else None
            req_qty = ajustes_map.get(str(vid), it["quantity"]) if ajustes_map is not None else it["quantity"]
            if req_qty <= 0:
                continue

            # Stock disponible
            stock_row = self.db.scalar(
                select(StockModel).where(
                    StockModel.variant_id == vid,
                    StockModel.branch_id == branch_id,
                )
            )
            avail = stock_row.quantity if stock_row else 0

            # Precios
            server_reg = Decimal(str(variant.price_override if variant.price_override is not None else product.base_price))
            client_unit = Decimal(str(it.get("unit_price", server_reg)))
            offer_id_val = it.get("offer_id")

            if avail < req_qty:
                stock_conflict = True
                conflict_lines.append({
                    "variant_id": str(vid),
                    "product_name": product.name,
                    "requested_quantity": req_qty,
                    "available_quantity": avail,
                    "unit_price": str(client_unit),
                    "current_price": str(server_reg),
                })
            elif offer_id_val:
                try:
                    off_uuid = uuid.UUID(str(offer_id_val))
                    promo = self.db.get(PromotionModel, off_uuid)
                    c_time = getattr(op, "client_created_at", None)
                    if c_time and c_time.tzinfo is None:
                        c_time = c_time.replace(tzinfo=timezone.utc)
                    if promo and promo.tenant_id == self.tenant_id and vigente_en(promo, c_time):
                        exp_p = precio_final(server_reg, promo.discount_type, promo.discount_value)
                        if abs(exp_p - client_unit) > Decimal("0.01") and not precio_autorizado:
                            price_conflict = True
                            conflict_lines.append({
                                "variant_id": str(vid),
                                "product_name": product.name,
                                "requested_quantity": req_qty,
                                "available_quantity": avail,
                                "unit_price": str(client_unit),
                                "current_price": str(exp_p),
                            })
                        else:
                            applied_offer_uses.append((promo, (server_reg - client_unit) * req_qty))
                    else:
                        if not precio_autorizado:
                            price_conflict = True
                            conflict_lines.append({
                                "variant_id": str(vid),
                                "product_name": product.name,
                                "requested_quantity": req_qty,
                                "available_quantity": avail,
                                "unit_price": str(client_unit),
                                "current_price": str(server_reg),
                                "reason_code": "offer_expired",
                            })
                except Exception:
                    pass
            elif abs(server_reg - client_unit) > Decimal("0.01") and not precio_autorizado:
                price_conflict = True
                conflict_lines.append({
                    "variant_id": str(vid),
                    "product_name": product.name,
                    "requested_quantity": req_qty,
                    "available_quantity": avail,
                    "unit_price": str(client_unit),
                    "current_price": str(server_reg),
                })

            final_unit = client_unit if precio_autorizado else server_reg
            line_tot = (final_unit * Decimal(req_qty)).quantize(Decimal("0.01"))
            subtotal += line_tot

            order_items.append({
                "variant_id": str(vid),
                "sku": variant.sku,
                "product_name": product.name,
                "size": getattr(variant.size, "name", "") if variant.size else "",
                "color": getattr(variant.color, "name", "") if variant.color else "",
                "quantity": req_qty,
                "unit_price": str(final_unit),
                "regular_price": str(server_reg),
                "total": str(line_tot),
            })
            stock_changes.append((vid, req_qty))

        if stock_conflict:
            raise SyncConflictException(
                "STOCK",
                f"Stock insuficiente en {len(conflict_lines)} prenda(s).",
                {"lines": conflict_lines},
            )

        if price_conflict:
            raise SyncConflictException(
                "PRICE",
                "El precio de una o más prendas ha cambiado desde la descarga del catálogo.",
                {"lines": conflict_lines},
            )

        # 4. Descontar stock
        stock_svc = StockService(self.db)
        order_number = f"FS-{uuid.uuid4().hex[:6].upper()}"
        for vid, qty in stock_changes:
            stock_svc.change(
                variant_id=vid,
                branch_id=branch_id,
                delta=-qty,
                kind="pos_sale",
                reason=f"Venta sin conexión confirmada {order_number}",
                actor_id=actor.id,
                reference=order_number,
            )

        # 5. Crear orden
        discount_total = Decimal(str(payload.get("discount_total") or "0.00"))
        total = (subtotal - discount_total).quantize(Decimal("0.01"))
        cash_rec = Decimal(str(payload.get("cash_received") or total))

        order = OrderModel(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            number=order_number,
            user_id=customer_id or user_id,
            cashier_user_id=user_id,
            sales_channel="pos",
            cash_point_id=uuid.UUID(str(payload["cash_point_id"])) if payload.get("cash_point_id") else None,
            branch_id=branch_id,
            status="delivered",
            payment_status="paid",
            payment_method=payload.get("payment_method", "cash"),
            total=total,
            subtotal=subtotal,
            discount_total=discount_total,
            discounts=[],
            currency="BOB",
            address={"city": getattr(branch.city, "name", "Santa Cruz") if getattr(branch, "city", None) else "Santa Cruz", "address": branch.address or ""},
            customer_email=payload.get("customer_email") or "offline-pos@fashionstore.local",
            items=order_items,
            origin="OFFLINE",
            device_id=op.device_id,
            client_request_id=op.client_request_id,
            client_created_at=op.client_created_at,
            local_folio=payload.get("local_folio"),
            cash_received=cash_rec,
            price_authorized_by=actor.id if precio_autorizado else None,
            paid_at=op.client_created_at,
        )
        self.db.add(order)
        self.db.flush()
        for promo, disc_amt in applied_offer_uses:
            try:
                promo.uses_count += 1
                self.db.add(PromotionUseModel(
                    promotion_id=promo.id,
                    user_id=customer_id or user_id,
                    order_id=order.id,
                    amount=disc_amt,
                    channel="OFFLINE",
                ))
            except Exception:
                pass
        return order


class SyncService:
    def __init__(self, db: Session, ctx: Any):
        self.db = db
        self.ctx = ctx

    def procesar_lote(self, data: SyncBatchIn, client_ip: str | None) -> SyncBatchOut:
        started_at = datetime.now(timezone.utc)
        batch = SyncBatchModel(
            id=uuid.uuid4(),
            tenant_id=self.ctx.tenant_id,
            device_id=data.device_id,
            user_id=getattr(self.ctx.user, "id", None),
            started_at=started_at,
            client_version=data.client_version,
            client_ip=client_ip,
            request_id=get_audit_request_id() or str(uuid.uuid4()),
        )
        self.db.add(batch)
        self.db.flush()

        # Ordenar por client_created_at ascendente (gana la venta anterior)
        sorted_ops = sorted(data.operations, key=lambda x: x.client_created_at)

        results: list[SyncResultOut] = []
        confirmed_count = 0
        conflicts_count = 0
        rejected_count = 0
        replays_count = 0

        for op in sorted_ops:
            try:
                # Savepoint para cada operación individual
                with self.db.begin_nested():
                    res = self._procesar(op, batch)
                    results.append(res)
                    if res.replay:
                        replays_count += 1
                    elif res.status == "CONFIRMED":
                        confirmed_count += 1
                    elif res.status == "CONFLICT":
                        conflicts_count += 1
                    elif res.status == "REJECTED":
                        rejected_count += 1
                # Confirmar el savepoint
                self.db.commit()
            except IntegrityError:
                self.db.rollback()
                # Reintento simultáneo del mismo UUID: releer y responder como reenvío
                existing = self.db.scalar(
                    select(SyncOperationModel).where(
                        SyncOperationModel.tenant_id == self.ctx.tenant_id,
                        SyncOperationModel.client_request_id == op.client_request_id,
                    )
                )
                if existing:
                    replays_count += 1
                    results.append(
                        SyncResultOut(
                            client_request_id=op.client_request_id,
                            status=existing.status,  # type: ignore
                            server_ref=existing.server_ref,
                            server_number=existing.server_number,
                            reason_code=existing.reason_code,
                            message=existing.message,
                            replay=True,
                        )
                    )
            except Exception as e:
                self.db.rollback()
                results.append(
                    SyncResultOut(
                        client_request_id=op.client_request_id,
                        status="RETRY",
                        message=f"Error transaccional en el servidor: {str(e)}",
                        reason_code="server_error",
                    )
                )

        finished_at = datetime.now(timezone.utc)
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)

        batch.finished_at = finished_at
        batch.duration_ms = duration_ms
        batch.received = len(sorted_ops)
        batch.confirmed = confirmed_count
        batch.conflicts = conflicts_count
        batch.rejected = rejected_count
        batch.replays = replays_count
        self.db.commit()

        RecordAuditEvent(self.db).execute(
            action="sync.batch_received",
            entity_type="sync_batch",
            entity_id=str(batch.id),
            description=f"Lote de sincronización: {confirmed_count} confirmadas, {conflicts_count} conflictos, {rejected_count} rechazadas.",
            actor_user_id=getattr(self.ctx.user, "id", None),
            metadata={
                "device_id": data.device_id,
                "received": len(sorted_ops),
                "confirmed": confirmed_count,
                "conflicts": conflicts_count,
                "rejected": rejected_count,
            },
        )

        return SyncBatchOut(
            batch_id=batch.id,
            received_at=started_at,
            request_id=batch.request_id,
            results=results,
        )

    def _procesar(self, op: SyncOperationIn, batch: SyncBatchModel) -> SyncResultOut:
        phash = _canonical_hash(op)

        # 1. Comprobar existencia previa por empresa
        existing = self.db.scalar(
            select(SyncOperationModel).where(
                SyncOperationModel.tenant_id == self.ctx.tenant_id,
                SyncOperationModel.client_request_id == op.client_request_id,
            )
        )
        if existing:
            if existing.payload_hash != phash:
                return SyncResultOut(
                    client_request_id=op.client_request_id,
                    status="REJECTED",
                    reason_code="uuid_reused",
                    message="Ese identificador ya fue utilizado con otro contenido.",
                )
            conflict = None
            if existing.status == "CONFLICT":
                conflict = self.db.scalar(
                    select(SyncConflictModel).where(SyncConflictModel.operation_id == existing.id)
                )
            return SyncResultOut(
                client_request_id=op.client_request_id,
                status=existing.status,  # type: ignore
                server_ref=existing.server_ref,
                server_number=existing.server_number,
                conflict_id=conflict.id if conflict else None,
                conflict_type=conflict.type if conflict else None,
                reason_code=existing.reason_code,
                message=existing.message,
                replay=True,
            )

        # 2. Validar tipo y permisos
        user_perms = get_permission_codes(self.ctx.user) if getattr(self.ctx, "user", None) else set()
        if op.type == "SALE":
            if "commerce.write" not in user_perms and "sync.write" not in user_perms:
                return self._record_rejection(op, batch, "forbidden_operation_type", "No tiene permisos para sincronizar ventas.")
        elif op.type == "RESERVATION":
            if "reservations.write" not in user_perms and "sync.write" not in user_perms:
                return self._record_rejection(op, batch, "forbidden_operation_type", "No tiene permisos para sincronizar reservas.")

        # 3. Procesar según tipo
        if op.type == "SALE":
            svc = OfflineSaleService(self.db, self.ctx.tenant_id)
            try:
                order = svc.confirmar(op, self.ctx.user)
                rec = SyncOperationModel(
                    id=uuid.uuid4(),
                    tenant_id=self.ctx.tenant_id,
                    client_request_id=op.client_request_id,
                    type="SALE",
                    status="CONFIRMED",
                    branch_id=op.branch_id,
                    device_id=op.device_id,
                    user_id=uuid.UUID(str(op.payload.get("user_id"))) if op.payload.get("user_id") else getattr(self.ctx.user, "id", None),
                    batch_id=batch.id,
                    payload=op.payload,
                    payload_hash=phash,
                    server_ref=order.id,
                    server_number=order.number,
                    message="Venta sincronizada y confirmada exitosamente.",
                    submitted_by_user_id=getattr(self.ctx.user, "id", None),
                )
                self.db.add(rec)
                self.db.flush()
                return SyncResultOut(
                    client_request_id=op.client_request_id,
                    status="CONFIRMED",
                    server_ref=order.id,
                    server_number=order.number,
                    message=rec.message,
                )
            except SyncConflictException as ce:
                rec = SyncOperationModel(
                    id=uuid.uuid4(),
                    tenant_id=self.ctx.tenant_id,
                    client_request_id=op.client_request_id,
                    type="SALE",
                    status="CONFLICT",
                    branch_id=op.branch_id,
                    device_id=op.device_id,
                    user_id=uuid.UUID(str(op.payload.get("user_id"))) if op.payload.get("user_id") else getattr(self.ctx.user, "id", None),
                    batch_id=batch.id,
                    payload=op.payload,
                    payload_hash=phash,
                    message=str(ce),
                    submitted_by_user_id=getattr(self.ctx.user, "id", None),
                )
                self.db.add(rec)
                self.db.flush()
                conf = SyncConflictModel(
                    id=uuid.uuid4(),
                    tenant_id=self.ctx.tenant_id,
                    operation_id=rec.id,
                    branch_id=op.branch_id,
                    type=ce.conflict_type,
                    detail=ce.detail,
                    status="OPEN",
                )
                self.db.add(conf)
                self.db.flush()
                RecordAuditEvent(self.db).execute(
                    action="sync.conflict_created",
                    entity_type="sync_conflict",
                    entity_id=str(conf.id),
                    description=f"Conflicto de sincronización ({ce.conflict_type}): {str(ce)}",
                    actor_user_id=getattr(self.ctx.user, "id", None),
                )
                return SyncResultOut(
                    client_request_id=op.client_request_id,
                    status="CONFLICT",
                    conflict_id=conf.id,
                    conflict_type=conf.type,
                    message=str(ce),
                )
            except (ValidationError, NotFoundError) as ve:
                return self._record_rejection(op, batch, "validation_error", str(ve), phash)

        elif op.type == "RESERVATION":
            try:
                req = CrearReservaRequest(**op.payload)
                use_case = CrearReserva(self.db, tenant_id=self.ctx.tenant_id)
                reserva = use_case.execute(self.ctx.user, req, commit=False)
                rec = SyncOperationModel(
                    id=uuid.uuid4(),
                    tenant_id=self.ctx.tenant_id,
                    client_request_id=op.client_request_id,
                    type="RESERVATION",
                    status="CONFIRMED",
                    branch_id=op.branch_id,
                    device_id=op.device_id,
                    user_id=getattr(self.ctx.user, "id", None),
                    batch_id=batch.id,
                    payload=op.payload,
                    payload_hash=phash,
                    server_ref=reserva.id,
                    server_number=str(reserva.id)[:8].upper(),
                    message="Reserva sincronizada y confirmada exitosamente.",
                    submitted_by_user_id=getattr(self.ctx.user, "id", None),
                )
                self.db.add(rec)
                self.db.flush()
                return SyncResultOut(
                    client_request_id=op.client_request_id,
                    status="CONFIRMED",
                    server_ref=reserva.id,
                    server_number=rec.server_number,
                    message=rec.message,
                )
            except ReservationStockError as rse:
                rec = SyncOperationModel(
                    id=uuid.uuid4(),
                    tenant_id=self.ctx.tenant_id,
                    client_request_id=op.client_request_id,
                    type="RESERVATION",
                    status="CONFLICT",
                    branch_id=op.branch_id,
                    device_id=op.device_id,
                    user_id=getattr(self.ctx.user, "id", None),
                    batch_id=batch.id,
                    payload=op.payload,
                    payload_hash=phash,
                    message=str(rse),
                    submitted_by_user_id=getattr(self.ctx.user, "id", None),
                )
                self.db.add(rec)
                self.db.flush()
                conf = SyncConflictModel(
                    id=uuid.uuid4(),
                    tenant_id=self.ctx.tenant_id,
                    operation_id=rec.id,
                    branch_id=op.branch_id,
                    type="STOCK",
                    detail={"lines": getattr(rse, "lines", [])},
                    status="OPEN",
                )
                self.db.add(conf)
                self.db.flush()
                return SyncResultOut(
                    client_request_id=op.client_request_id,
                    status="CONFLICT",
                    conflict_id=conf.id,
                    conflict_type="STOCK",
                    message=str(rse),
                )
            except (ValidationError, NotFoundError) as ve:
                return self._record_rejection(op, batch, "validation_error", str(ve), phash)

        return self._record_rejection(op, batch, "unsupported_type", f"Tipo de operación {op.type} no soportado.", phash)

    def _record_rejection(
        self,
        op: SyncOperationIn,
        batch: SyncBatchModel,
        reason_code: str,
        message: str,
        phash: str | None = None,
    ) -> SyncResultOut:
        rec = SyncOperationModel(
            id=uuid.uuid4(),
            tenant_id=self.ctx.tenant_id,
            client_request_id=op.client_request_id,
            type=op.type,
            status="REJECTED",
            branch_id=op.branch_id,
            device_id=op.device_id,
            user_id=getattr(self.ctx.user, "id", None),
            batch_id=batch.id,
            payload=op.payload,
            payload_hash=phash or _canonical_hash(op),
            reason_code=reason_code,
            message=message,
            submitted_by_user_id=getattr(self.ctx.user, "id", None),
        )
        self.db.add(rec)
        self.db.flush()
        return SyncResultOut(
            client_request_id=op.client_request_id,
            status="REJECTED",
            reason_code=reason_code,
            message=message,
        )

    def estado(self, ids: list[uuid.UUID]) -> list[SyncResultOut]:
        ops = self.db.scalars(
            select(SyncOperationModel).where(
                SyncOperationModel.tenant_id == self.ctx.tenant_id,
                SyncOperationModel.client_request_id.in_(ids),
            )
        ).all()
        by_crid = {o.client_request_id: o for o in ops}

        results = []
        for crid in ids:
            op = by_crid.get(crid)
            if not op:
                results.append(
                    SyncResultOut(
                        client_request_id=crid,
                        status="UNKNOWN",
                        message="Operación no encontrada para esta empresa.",
                    )
                )
            else:
                conf = None
                if op.status == "CONFLICT":
                    conf = self.db.scalar(
                        select(SyncConflictModel).where(SyncConflictModel.operation_id == op.id)
                    )
                results.append(
                    SyncResultOut(
                        client_request_id=crid,
                        status=op.status,  # type: ignore
                        server_ref=op.server_ref,
                        server_number=op.server_number,
                        conflict_id=conf.id if conf else None,
                        conflict_type=conf.type if conf else None,
                        reason_code=op.reason_code,
                        message=op.message,
                        replay=False,
                    )
                )
        return results

    def detalle_lote(self, batch_id: uuid.UUID) -> SyncBatchDetailOut:
        batch = self.db.scalar(
            select(SyncBatchModel).where(
                SyncBatchModel.id == batch_id,
                SyncBatchModel.tenant_id == self.ctx.tenant_id,
            )
        )
        if not batch:
            raise NotFoundError("Lote de sincronización no encontrado.")

        ops = self.db.scalars(
            select(SyncOperationModel).where(SyncOperationModel.batch_id == batch.id)
        ).all()

        op_summaries = []
        for o in ops:
            conf_type = None
            if o.status == "CONFLICT":
                c = self.db.scalar(select(SyncConflictModel).where(SyncConflictModel.operation_id == o.id))
                if c:
                    conf_type = c.type
            op_summaries.append(
                SyncOperationSummaryOut(
                    client_request_id=o.client_request_id,
                    type=o.type,
                    status=o.status,
                    reason_code=o.reason_code,
                    conflict_type=conf_type,
                    server_number=o.server_number,
                )
            )

        user_name = None
        if batch.user_id:
            u = self.db.get(UserModel, batch.user_id)
            if u:
                user_name = f"{u.first_name} {u.last_name}".strip()

        branch_name = None
        if batch.branch_id:
            b = self.db.get(BranchModel, batch.branch_id)
            if b:
                branch_name = b.name

        return SyncBatchDetailOut(
            id=batch.id,
            device_id=batch.device_id,
            user_name=user_name,
            branch_name=branch_name,
            started_at=batch.started_at,
            duration_ms=batch.duration_ms,
            received=batch.received,
            confirmed=batch.confirmed,
            conflicts=batch.conflicts,
            rejected=batch.rejected,
            replays=batch.replays,
            error_summary=batch.error_summary,
            operations=op_summaries,
        )
