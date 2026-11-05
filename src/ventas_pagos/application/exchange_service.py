from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.shared.exceptions.domain_exception import NotFoundError, ValidationError
from src.usuarios_catalogo.infrastructure.models.catalog import (
    ColorModel,
    ProductModel,
    ProductVariantModel,
    SizeModel,
)
from src.ventas_pagos.domain.cambios import (
    CalculadoraCambio,
    ExchangeItemUnavailableError,
    ExchangeQuantityExceededError,
    LineaCambioCalculo,
    ResultadoCalculoCambio,
    VerificadorPlazoCambio,
)
from src.ventas_pagos.infrastructure.exchange_models import (
    GarmentExchangeLineModel,
    GarmentExchangeModel,
)
from src.ventas_pagos.infrastructure.models import (
    OrderModel,
    StockModel,
    StockMovementModel,
)


class ExchangeService:
    def __init__(self, db: Session):
        self.db = db

    def obtener_politica(self, tenant_id: UUID) -> Dict[str, Any]:
        tenant = self.db.get(TenantModel, tenant_id)
        if not tenant:
            raise NotFoundError("Empresa no encontrada.")
        days = getattr(tenant, "exchange_days", 15)
        return {"tenant_id": str(tenant_id), "exchange_days": days}

    def actualizar_politica(self, tenant_id: UUID, days: int) -> Dict[str, Any]:
        if days < 1 or days > 180:
            raise ValidationError("El plazo de cambio debe estar entre 1 y 180 días.")
        tenant = self.db.get(TenantModel, tenant_id)
        if not tenant:
            raise NotFoundError("Empresa no encontrada.")
        tenant.exchange_days = days
        self.db.commit()
        return {"tenant_id": str(tenant_id), "exchange_days": days}

    def buscar_orden_para_cambio(self, tenant_id: UUID, order_id_or_number: str) -> Dict[str, Any]:
        stmt = select(OrderModel).where(OrderModel.tenant_id == tenant_id)
        try:
            order_uuid = UUID(order_id_or_number)
            stmt = stmt.where(OrderModel.id == order_uuid)
        except ValueError:
            stmt = stmt.where(OrderModel.number == order_id_or_number.strip())

        order = self.db.scalar(stmt)
        if not order:
            raise NotFoundError(f"Pedido '{order_id_or_number}' no encontrado en esta empresa.")

        tenant = self.db.get(TenantModel, tenant_id)
        dias_permitidos = getattr(tenant, "exchange_days", 15) if tenant else 15

        fecha_compra = order.paid_at or order.created_at
        dias_restantes = VerificadorPlazoCambio.verificar(fecha_compra, dias_permitidos)

        # Buscar cambios previos de esta orden para descontar cantidades ya cambiadas
        prev_exchanges = self.db.scalars(
            select(GarmentExchangeModel)
            .where(
                GarmentExchangeModel.tenant_id == tenant_id,
                GarmentExchangeModel.original_order_id == order.id,
                GarmentExchangeModel.status != "CANCELLED",
            )
        ).all()

        ya_cambiados: Dict[str, int] = {}
        for ex in prev_exchanges:
            for line in ex.lines:
                vid_str = str(line.original_variant_id)
                ya_cambiados[vid_str] = ya_cambiados.get(vid_str, 0) + line.returned_quantity

        # Enriquecer líneas del pedido con tallas, colores y saldo cambiable
        items_cambiables = []
        for it in (order.items or []):
            vid = it.get("variant_id")
            original_qty = int(it.get("quantity", 1))
            cambiado = ya_cambiados.get(str(vid), 0)
            disponible_cambio = max(0, original_qty - cambiado)

            items_cambiables.append({
                "variant_id": str(vid),
                "product_id": it.get("product_id"),
                "product_name": it.get("name") or it.get("product_name") or "Prenda",
                "sku": it.get("sku"),
                "size": it.get("size"),
                "color": it.get("color"),
                "original_quantity": original_qty,
                "already_exchanged_quantity": cambiado,
                "available_for_exchange": disponible_cambio,
                "unit_price": Decimal(str(it.get("unit_price", 0))),
                "subtotal": Decimal(str(it.get("subtotal", 0))),
            })

        return {
            "order_id": str(order.id),
            "order_number": order.number,
            "purchase_date": fecha_compra.isoformat(),
            "deadline_days": dias_permitidos,
            "remaining_days": dias_restantes,
            "can_exchange": dias_restantes >= 0 and any(it["available_for_exchange"] > 0 for it in items_cambiables),
            "customer_email": order.customer_email,
            "branch_id": str(order.branch_id),
            "items": items_cambiables,
        }

    def calcular_cambio(
        self,
        tenant_id: UUID,
        branch_id: UUID,
        lineas_raw: List[Dict[str, Any]],
    ) -> ResultadoCalculoCambio:
        lineas_calculo: List[LineaCambioCalculo] = []

        for item in lineas_raw:
            orig_vid = UUID(str(item["original_variant_id"]))
            ret_qty = int(item["returned_quantity"])
            orig_price = Decimal(str(item["original_unit_price"]))

            new_vid = UUID(str(item["new_variant_id"]))
            deliv_qty = int(item["delivered_quantity"])
            new_price = Decimal(str(item["new_unit_price"]))

            # Verificar existencia del nuevo producto en la sucursal
            stock = self.db.scalar(
                select(StockModel).where(
                    StockModel.branch_id == branch_id,
                    StockModel.variant_id == new_vid,
                )
            )
            disponible = stock.quantity if stock else 0
            if disponible < deliv_qty:
                raise ExchangeItemUnavailableError(str(new_vid), disponible, deliv_qty)

            lineas_calculo.append(
                LineaCambioCalculo(
                    original_variant_id=orig_vid,
                    returned_quantity=ret_qty,
                    original_unit_price=orig_price,
                    new_variant_id=new_vid,
                    delivered_quantity=deliv_qty,
                    new_unit_price=new_price,
                )
            )

        return CalculadoraCambio.calcular(lineas_calculo)

    def ejecutar_cambio(
        self,
        tenant_id: UUID,
        branch_id: UUID,
        actor_id: Optional[UUID],
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        client_req_id = None
        if data.get("client_request_id"):
            client_req_id = UUID(str(data["client_request_id"]))
            existente = self.db.scalar(
                select(GarmentExchangeModel).where(
                    GarmentExchangeModel.client_request_id == client_req_id
                )
            )
            if existente:
                return self.obtener_cambio(tenant_id, existente.id)

        order_id = UUID(str(data["original_order_id"]))
        order = self.db.scalar(
            select(OrderModel).where(OrderModel.id == order_id, OrderModel.tenant_id == tenant_id)
        )
        if not order:
            raise NotFoundError("Pedido original no encontrado.")

        # Verificar plazo
        tenant = self.db.get(TenantModel, tenant_id)
        dias_permitidos = getattr(tenant, "exchange_days", 15) if tenant else 15
        fecha_compra = order.paid_at or order.created_at
        VerificadorPlazoCambio.verificar(fecha_compra, dias_permitidos)

        # Calcular y validar líneas
        resultado = self.calcular_cambio(tenant_id, branch_id, data["lines"])

        # Crear registro de cambio
        exchange = GarmentExchangeModel(
            id=uuid4(),
            tenant_id=tenant_id,
            branch_id=branch_id,
            original_order_id=order.id,
            user_id=actor_id,
            customer_id=order.user_id,
            difference_amount=resultado.difference_amount,
            payment_method=data.get("payment_method", "none"),
            cash_received=Decimal(str(data["cash_received"])) if data.get("cash_received") is not None else None,
            cash_returned=Decimal(str(data["cash_returned"])) if data.get("cash_returned") is not None else None,
            status="COMPLETED",
            notes=data.get("notes"),
            client_request_id=client_req_id,
        )
        self.db.add(exchange)
        self.db.flush()

        now = datetime.now(timezone.utc)

        # Movimientos duales de stock para cada línea
        for linea in resultado.lineas:
            # 1. Ingreso de la prenda devuelta (exchange_in)
            orig_stock = self.db.scalar(
                select(StockModel).where(
                    StockModel.branch_id == branch_id,
                    StockModel.variant_id == linea.original_variant_id,
                )
            )
            if not orig_stock:
                orig_stock = StockModel(
                    branch_id=branch_id,
                    variant_id=linea.original_variant_id,
                    quantity=0,
                )
                self.db.add(orig_stock)
                self.db.flush()

            q_before_in = orig_stock.quantity
            orig_stock.quantity += linea.returned_quantity
            q_after_in = orig_stock.quantity

            mov_in = StockMovementModel(
                branch_id=branch_id,
                variant_id=linea.original_variant_id,
                delta=linea.returned_quantity,
                quantity_before=q_before_in,
                quantity_after=q_after_in,
                kind="exchange_in",
                reason=f"Cambio de prenda #{str(exchange.id)[:8]} - Reingreso prenda devuelta",
                reference=str(exchange.id),
                actor_id=actor_id,
                actor_email=data.get("actor_email"),
            )
            self.db.add(mov_in)

            # 2. Salida de la nueva prenda entregada (exchange_out)
            new_stock = self.db.scalar(
                select(StockModel).where(
                    StockModel.branch_id == branch_id,
                    StockModel.variant_id == linea.new_variant_id,
                )
            )
            if not new_stock or new_stock.quantity < linea.delivered_quantity:
                raise ExchangeItemUnavailableError(
                    str(linea.new_variant_id),
                    new_stock.quantity if new_stock else 0,
                    linea.delivered_quantity,
                )

            q_before_out = new_stock.quantity
            new_stock.quantity -= linea.delivered_quantity
            q_after_out = new_stock.quantity

            mov_out = StockMovementModel(
                branch_id=branch_id,
                variant_id=linea.new_variant_id,
                delta=-linea.delivered_quantity,
                quantity_before=q_before_out,
                quantity_after=q_after_out,
                kind="exchange_out",
                reason=f"Cambio de prenda #{str(exchange.id)[:8]} - Salida prenda entregada",
                reference=str(exchange.id),
                actor_id=actor_id,
                actor_email=data.get("actor_email"),
            )
            self.db.add(mov_out)

            # 3. Guardar línea de cambio
            line_model = GarmentExchangeLineModel(
                id=uuid4(),
                exchange_id=exchange.id,
                original_variant_id=linea.original_variant_id,
                returned_quantity=linea.returned_quantity,
                original_unit_price=linea.original_unit_price,
                new_variant_id=linea.new_variant_id,
                delivered_quantity=linea.delivered_quantity,
                new_unit_price=linea.new_unit_price,
                price_difference=linea.difference,
            )
            self.db.add(line_model)

        self.db.commit()
        return self.obtener_cambio(tenant_id, exchange.id)

    def listar_cambios(
        self,
        tenant_id: UUID,
        branch_id: Optional[UUID] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        stmt = (
            select(GarmentExchangeModel)
            .where(GarmentExchangeModel.tenant_id == tenant_id)
            .order_by(GarmentExchangeModel.created_at.desc())
        )
        if branch_id:
            stmt = stmt.where(GarmentExchangeModel.branch_id == branch_id)

        count_stmt = select(func.count(GarmentExchangeModel.id)).where(
            GarmentExchangeModel.tenant_id == tenant_id
        )
        if branch_id:
            count_stmt = count_stmt.where(GarmentExchangeModel.branch_id == branch_id)

        total = self.db.scalar(count_stmt) or 0
        items = list(self.db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all())

        return {
            "items": [self._format_exchange_summary(e) for e in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def obtener_cambio(self, tenant_id: UUID, exchange_id: UUID) -> Dict[str, Any]:
        ex = self.db.scalar(
            select(GarmentExchangeModel).where(
                GarmentExchangeModel.id == exchange_id,
                GarmentExchangeModel.tenant_id == tenant_id,
            )
        )
        if not ex:
            raise NotFoundError("Cambio de prenda no encontrado.")

        lines_detail = []
        for l in ex.lines:
            orig_v = self.db.get(ProductVariantModel, l.original_variant_id)
            new_v = self.db.get(ProductVariantModel, l.new_variant_id)

            lines_detail.append({
                "id": str(l.id),
                "original_variant_id": str(l.original_variant_id),
                "original_sku": orig_v.sku if orig_v else None,
                "original_product_name": orig_v.product.name if orig_v and orig_v.product else None,
                "returned_quantity": l.returned_quantity,
                "original_unit_price": l.original_unit_price,
                "returned_total": l.original_unit_price * l.returned_quantity,
                "new_variant_id": str(l.new_variant_id),
                "new_sku": new_v.sku if new_v else None,
                "new_product_name": new_v.product.name if new_v and new_v.product else None,
                "delivered_quantity": l.delivered_quantity,
                "new_unit_price": l.new_unit_price,
                "delivered_total": l.new_unit_price * l.delivered_quantity,
                "price_difference": l.price_difference,
            })

        order = self.db.get(OrderModel, ex.original_order_id)

        return {
            "id": str(ex.id),
            "tenant_id": str(ex.tenant_id),
            "branch_id": str(ex.branch_id),
            "original_order_id": str(ex.original_order_id),
            "original_order_number": order.number if order else None,
            "difference_amount": ex.difference_amount,
            "payment_method": ex.payment_method,
            "cash_received": ex.cash_received,
            "cash_returned": ex.cash_returned,
            "status": ex.status,
            "notes": ex.notes,
            "created_at": ex.created_at.isoformat(),
            "lines": lines_detail,
        }

    def _format_exchange_summary(self, ex: GarmentExchangeModel) -> Dict[str, Any]:
        order = self.db.get(OrderModel, ex.original_order_id)
        return {
            "id": str(ex.id),
            "original_order_id": str(ex.original_order_id),
            "original_order_number": order.number if order else None,
            "branch_id": str(ex.branch_id),
            "difference_amount": ex.difference_amount,
            "payment_method": ex.payment_method,
            "status": ex.status,
            "lines_count": len(ex.lines),
            "created_at": ex.created_at.isoformat(),
        }
