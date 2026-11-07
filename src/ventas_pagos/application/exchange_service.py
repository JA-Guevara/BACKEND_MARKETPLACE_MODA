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

        from src.ventas_pagos.application.returns_service import ReturnsService
        from src.ventas_pagos.domain import returns
        ya_cambiados = returns.unidades_comprometidas(ReturnsService(self.db, tenant_id).compromisos(order))
        prev_exchanges = []
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
                "unit_price": returns.paid_credit(order,vid,1,ReturnsService(self.db,tenant_id).compromisos(order)) if disponible_cambio else Decimal(0),
                "subtotal": Decimal(str(it.get("subtotal", 0))),
            })

        return {
            "order_id": str(order.id),
            "order_number": order.number,
            "purchase_date": fecha_compra.isoformat(),
            "deadline_days": dias_permitidos,
            "remaining_days": dias_restantes,
            "can_exchange": order.payment_status == "paid" and order.status in {"delivered","completed"} and dias_restantes >= 0 and any(it["available_for_exchange"] > 0 for it in items_cambiables),
            "customer_email": order.customer_email,
            "branch_id": str(order.branch_id),
            "items": items_cambiables,
        }

    def calcular_cambio(
        self,
        tenant_id: UUID,
        branch_id: UUID,
        lineas_raw: List[Dict[str, Any]],
        order_id: UUID | None = None,
    ) -> ResultadoCalculoCambio:
        lineas_calculo: List[LineaCambioCalculo] = []
        from src.ventas_pagos.application.service import CommerceService
        from src.ventas_pagos.application.returns_service import ReturnsService
        from src.ventas_pagos.domain import returns
        order=CommerceService(self.db,tenant_id).order(order_id) if order_id else None
        if order and order.branch_id!=branch_id:
            raise ValidationError('La sucursal no corresponde al pedido.')
        commitments=ReturnsService(self.db,tenant_id).compromisos(order) if order else []
        if order:
            try:
                returns.armar_detalle(order,commitments,[(str(row['original_variant_id']),int(row['returned_quantity'])) for row in lineas_raw])
            except ValueError as error:
                raise ValidationError(str(error)) from error

        for item in lineas_raw:
            orig_vid = UUID(str(item["original_variant_id"]))
            ret_qty = int(item["returned_quantity"])
            orig_price = Decimal(str(item["original_unit_price"]))

            new_vid = UUID(str(item["new_variant_id"]))
            deliv_qty = int(item["delivered_quantity"])
            from src.ventas_pagos.application.service import CommerceService
            commerce = CommerceService(self.db, tenant_id)
            commerce.branch(branch_id)
            commerce.variant(orig_vid)
            variant = commerce.variant(new_vid)
            from src.ventas_pagos.application.pricing_service import PricingService
            new_price = PricingService(self.db,tenant_id).precio(variant,canal='ONLINE').final

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
                    original_credit=returns.paid_credit(order,orig_vid,ret_qty,commitments) if order else None,
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
        from src.ventas_pagos.application.counter_exchange import execute
        return execute(self, tenant_id, branch_id, actor_id, data)

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
                "returned_total": l.new_unit_price * l.delivered_quantity - l.price_difference,
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
