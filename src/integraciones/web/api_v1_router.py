from datetime import datetime, timezone
import base64, json
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, or_, and_
from sqlalchemy.orm import Session
from src.infrastructure.database.session import get_db
from src.integraciones.application.api_keys_service import require_api_key
from src.inventario_sucursales.infrastructure.models.organization import BranchModel
from src.usuarios_catalogo.infrastructure.models.catalog import ProductModel, ProductVariantModel
from src.ventas_pagos.infrastructure.models import OrderModel, StockModel
from src.plataforma_saas.web.schemas.stripe_saas import IntegrationSalesOut, IntegrationStockOut
from src.shared.responses.api_response import ApiResponse
from src.shared.exceptions.domain_exception import ValidationError

router = APIRouter(prefix="/integrations/v1", tags=["Integraciones · API v1"])


@router.get("/sales", response_model=ApiResponse[IntegrationSalesOut])
def sales(since: str | None = Query(default=None, max_length=300), limit: int = Query(default=100, ge=1, le=500),
          ctx=Depends(require_api_key("sales:read")), db: Session = Depends(get_db)):
    query = select(OrderModel, BranchModel.code).join(BranchModel, BranchModel.id == OrderModel.branch_id).where(
        OrderModel.tenant_id == ctx.tenant_id, BranchModel.tenant_id == ctx.tenant_id,
        OrderModel.payment_status == "paid", OrderModel.paid_at.is_not(None))
    if since is not None:
        try:
            if since.startswith("v1."):
                timestamp, last_id = json.loads(base64.urlsafe_b64decode(since[3:] + "=" * (-len(since[3:]) % 4)))
                moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                last_id = UUID(last_id)
                query = query.where(or_(OrderModel.paid_at > moment,
                    and_(OrderModel.paid_at == moment, OrderModel.id > last_id)))
            else:
                moment = datetime.fromisoformat(since.replace("Z", "+00:00"))
                query = query.where(OrderModel.paid_at > moment)
            if moment.tzinfo is None:
                raise ValueError("El cursor requiere zona horaria")
        except (ValueError, TypeError, KeyError, UnicodeDecodeError, AttributeError):
            raise ValidationError("El cursor since no es válido.") from None
    rows = db.execute(query.order_by(OrderModel.paid_at, OrderModel.id).limit(limit)).all()
    items = [{"id": order.id, "number": order.number, "channel": order.sales_channel,
              "branch_code": branch_code, "total": str(order.total), "currency": order.currency,
              "confirmed_at": order.paid_at.replace(tzinfo=timezone.utc) if order.paid_at.tzinfo is None else order.paid_at}
             for order, branch_code in rows]
    next_since = None
    if items:
        cursor = json.dumps([items[-1]["confirmed_at"].isoformat(), str(items[-1]["id"])], separators=(",", ":"))
        next_since = "v1." + base64.urlsafe_b64encode(cursor.encode()).decode().rstrip("=")
    return ApiResponse(data={"items": items, "next_since": next_since})


@router.get("/stock", response_model=ApiResponse[IntegrationStockOut])
def stock(branch_code: str | None = Query(default=None, max_length=50),
          ctx=Depends(require_api_key("stock:read")), db: Session = Depends(get_db)):
    query = select(ProductVariantModel.sku, BranchModel.code, StockModel.quantity).select_from(StockModel).join(
        ProductVariantModel, ProductVariantModel.id == StockModel.variant_id).join(
        ProductModel, ProductModel.id == ProductVariantModel.product_id).join(
        BranchModel, BranchModel.id == StockModel.branch_id).where(
        ProductModel.tenant_id == ctx.tenant_id, BranchModel.tenant_id == ctx.tenant_id,
        ProductModel.deleted_at.is_(None), BranchModel.deleted_at.is_(None))
    if branch_code:
        query = query.where(BranchModel.code == branch_code)
    rows = db.execute(query.order_by(ProductVariantModel.sku, BranchModel.code)).all()
    return ApiResponse(data={"items": [{"sku": sku, "branch_code": code, "quantity": qty} for sku, code, qty in rows]})
