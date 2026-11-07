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
        if order and order.tenant_id != tenant_id:
            raise ValidationError('El pedido no pertenece a esta empresa.')
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

    def consultar_disponibilidad_multisucursal(
        self, tenant_id: UUID, variant_id: UUID
    ) -> List[Dict[str, Any]]:
        """Consulta el stock de una variante en todas las sucursales activas de la empresa (CU-12/CU-26)."""
        from src.inventario_sucursales.infrastructure.models.organization import BranchModel
        variant = self.db.get(ProductVariantModel, variant_id)
        if not variant or variant.product.tenant_id != tenant_id:
            raise NotFoundError("Variante no encontrada en esta empresa.")

        branches = self.db.scalars(
            select(BranchModel)
            .where(BranchModel.tenant_id == tenant_id, BranchModel.is_active.is_(True))
            .order_by(BranchModel.name)
        ).all()

        stocks = {
            s.branch_id: s.quantity
            for s in self.db.scalars(
                select(StockModel).where(StockModel.variant_id == variant_id)
            ).all()
        }

        return [
            {
                "branch_id": str(b.id),
                "branch_name": b.name,
                "city": b.city or "Central",
                "address": b.address or "",
                "phone": b.phone or "",
                "available_quantity": stocks.get(b.id, 0),
                "can_transfer": stocks.get(b.id, 0) > 0,
            }
            for b in branches
        ]

    def transferir_prenda_intersucursal(
        self,
        tenant_id: UUID,
        variant_id: UUID,
        from_branch_id: UUID,
        to_branch_id: UUID,
        quantity: int,
        actor_id: Optional[UUID],
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Ejecuta un traslado de prendas entre sucursales de la misma empresa con trazabilidad de kardex (CU-26/CU-38)."""
        if from_branch_id == to_branch_id:
            raise ValidationError("La sucursal de origen y destino deben ser distintas.")
        if quantity <= 0:
            raise ValidationError("La cantidad a trasladar debe ser mayor a 0.")

        from src.inventario_sucursales.infrastructure.models.organization import BranchModel
        from src.ventas_pagos.application.stock_service import StockService
        from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent

        from_branch = self.db.scalar(
            select(BranchModel).where(BranchModel.id == from_branch_id, BranchModel.tenant_id == tenant_id)
        )
        to_branch = self.db.scalar(
            select(BranchModel).where(BranchModel.id == to_branch_id, BranchModel.tenant_id == tenant_id)
        )
        if not from_branch or not to_branch:
            raise NotFoundError("Una de las sucursales no pertenece a esta empresa.")

        variant = self.db.get(ProductVariantModel, variant_id)
        if not variant or variant.product.tenant_id != tenant_id:
            raise NotFoundError("Variante no encontrada en esta empresa.")

        inventory = StockService(self.db, tenant_id)
        inventory.locked_stock(variant_id, from_branch_id)
        inventory.locked_stock(variant_id, to_branch_id)

        current_from_stock = self.db.scalar(
            select(StockModel.quantity).where(
                StockModel.variant_id == variant_id, StockModel.branch_id == from_branch_id
            )
        ) or 0

        if current_from_stock < quantity:
            raise ValidationError(
                f"Stock insuficiente en '{from_branch.name}'. Disponible: {current_from_stock}, solicitado: {quantity}."
            )

        ref_note = notes or f"Traslado intersucursal de {from_branch.name} a {to_branch.name} para cambio/reposición."
        inventory.change(
            variant_id,
            from_branch_id,
            -quantity,
            "transfer_out",
            f"Salida por traslado intersucursal hacia {to_branch.name}.",
            reference=ref_note,
            actor_id=actor_id,
        )
        inventory.change(
            variant_id,
            to_branch_id,
            quantity,
            "transfer_in",
            f"Entrada por traslado intersucursal desde {from_branch.name}.",
            reference=ref_note,
            actor_id=actor_id,
        )

        RecordAuditEvent(self.db).execute(
            action="inventory.interbranch_transfer",
            entity_type="product_variant",
            entity_id=str(variant_id),
            description=f"Traslado de {quantity} unidad(es) de {from_branch.name} a {to_branch.name}.",
            actor_user_id=actor_id,
            metadata={
                "variant_id": str(variant_id),
                "from_branch_id": str(from_branch_id),
                "to_branch_id": str(to_branch_id),
                "quantity": quantity,
            },
        )
        self.db.commit()

        new_to_stock = self.db.scalar(
            select(StockModel.quantity).where(
                StockModel.variant_id == variant_id, StockModel.branch_id == to_branch_id
            )
        ) or 0

        return {
            "variant_id": str(variant_id),
            "product_name": variant.product.name,
            "size": variant.size.name if variant.size else "",
            "color": variant.color.name if variant.color else "",
            "from_branch_id": str(from_branch_id),
            "from_branch_name": from_branch.name,
            "to_branch_id": str(to_branch_id),
            "to_branch_name": to_branch.name,
            "transferred_quantity": quantity,
            "destination_available_stock": new_to_stock,
            "message": f"Traslado de {quantity} unidad(es) completado exitosamente hacia {to_branch.name}.",
        }
