from datetime import datetime, timezone
import base64
import json
from uuid import UUID
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, or_, and_
from sqlalchemy.orm import Session
from src.infrastructure.database.session import get_db
from src.integraciones.application.api_keys_service import require_api_key
from src.integraciones.application.webhooks_service import WebhooksService
from src.inventario_sucursales.infrastructure.models.organization import BranchModel
from src.usuarios_catalogo.infrastructure.models.catalog import (
    CategoryModel,
    ColorModel,
    ProductModel,
    ProductVariantModel,
    SizeModel,
)
from src.ventas_pagos.infrastructure.models import OrderModel, StockModel
from src.plataforma_saas.web.schemas.stripe_saas import IntegrationSalesOut, IntegrationStockOut
from src.shared.responses.api_response import ApiResponse
from src.shared.exceptions.domain_exception import ValidationError

router = APIRouter(prefix="/integrations/v1", tags=["Integraciones · API v1"])


# --- Schemas para Catálogo y Ajuste de Stock ---
class IntegrationCatalogVariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sku: str
    size: str | None = None
    color: str | None = None
    barcode: str | None = None
    price: str
    is_active: bool = True


class IntegrationCatalogProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    description: str | None = None
    brand: str | None = None
    gender: str | None = None
    category: str | None = None
    base_price: str
    is_active: bool = True
    variants: list[IntegrationCatalogVariantOut] = []


class IntegrationCatalogOut(BaseModel):
    items: list[IntegrationCatalogProductOut]
    total: int


class IntegrationStockAdjustItemIn(BaseModel):
    sku: str = Field(min_length=1, max_length=80)
    branch_code: str = Field(min_length=1, max_length=50)
    quantity: int = Field(ge=0)
    mode: str = Field(default="set", pattern="^(set|delta)$")


class IntegrationStockAdjustIn(BaseModel):
    items: list[IntegrationStockAdjustItemIn] = Field(min_length=1, max_length=500)


class IntegrationStockAdjustItemOut(BaseModel):
    sku: str
    branch_code: str
    previous_quantity: int
    new_quantity: int
    status: str = "updated"


class IntegrationStockAdjustOut(BaseModel):
    updated_count: int
    items: list[IntegrationStockAdjustItemOut]
    timestamp: datetime


# --- Endpoints Existentes: Ventas e Inventario ---
@router.get("/sales", response_model=ApiResponse[IntegrationSalesOut])
def sales(
    since: str | None = Query(default=None, max_length=300),
    limit: int = Query(default=100, ge=1, le=500),
    ctx=Depends(require_api_key("sales:read")),
    db: Session = Depends(get_db),
):
    query = (
        select(OrderModel, BranchModel.code)
        .join(BranchModel, BranchModel.id == OrderModel.branch_id)
        .where(
            OrderModel.tenant_id == ctx.tenant_id,
            BranchModel.tenant_id == ctx.tenant_id,
            OrderModel.payment_status == "paid",
            OrderModel.paid_at.is_not(None),
        )
    )
    if since is not None:
        try:
            if since.startswith("v1."):
                timestamp, last_id = json.loads(
                    base64.urlsafe_b64decode(since[3:] + "=" * (-len(since[3:]) % 4))
                )
                moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                last_id = UUID(last_id)
                query = query.where(
                    or_(
                        OrderModel.paid_at > moment,
                        and_(OrderModel.paid_at == moment, OrderModel.id > last_id),
                    )
                )
            else:
                moment = datetime.fromisoformat(since.replace("Z", "+00:00"))
                query = query.where(OrderModel.paid_at > moment)
            if moment.tzinfo is None:
                raise ValueError("El cursor requiere zona horaria")
        except (ValueError, TypeError, KeyError, UnicodeDecodeError, AttributeError):
            raise ValidationError("El cursor since no es válido.") from None
    rows = db.execute(query.order_by(OrderModel.paid_at, OrderModel.id).limit(limit)).all()
    items = [
        {
            "id": order.id,
            "number": order.number,
            "channel": order.sales_channel,
            "branch_code": branch_code,
            "total": str(order.total),
            "currency": order.currency,
            "confirmed_at": (
                order.paid_at.replace(tzinfo=timezone.utc)
                if order.paid_at.tzinfo is None
                else order.paid_at
            ),
        }
        for order, branch_code in rows
    ]
    next_since = None
    if items:
        cursor = json.dumps(
            [items[-1]["confirmed_at"].isoformat(), str(items[-1]["id"])],
            separators=(",", ":"),
        )
        next_since = "v1." + base64.urlsafe_b64encode(cursor.encode()).decode().rstrip("=")
    return ApiResponse(data={"items": items, "next_since": next_since})


@router.get("/stock", response_model=ApiResponse[IntegrationStockOut])
def stock(
    branch_code: str | None = Query(default=None, max_length=50),
    ctx=Depends(require_api_key("stock:read")),
    db: Session = Depends(get_db),
):
    query = (
        select(ProductVariantModel.sku, BranchModel.code, StockModel.quantity)
        .select_from(StockModel)
        .join(ProductVariantModel, ProductVariantModel.id == StockModel.variant_id)
        .join(ProductModel, ProductModel.id == ProductVariantModel.product_id)
        .join(BranchModel, BranchModel.id == StockModel.branch_id)
        .where(
            ProductModel.tenant_id == ctx.tenant_id,
            BranchModel.tenant_id == ctx.tenant_id,
            ProductModel.deleted_at.is_(None),
            BranchModel.deleted_at.is_(None),
        )
    )
    if branch_code:
        query = query.where(BranchModel.code == branch_code)
    rows = db.execute(query.order_by(ProductVariantModel.sku, BranchModel.code)).all()
    return ApiResponse(
        data={"items": [{"sku": sku, "branch_code": code, "quantity": qty} for sku, code, qty in rows]}
    )


# --- Nuevos Endpoints: Catálogo B2B y Ajuste Bidireccional de Inventario ---
@router.get("/catalog", response_model=ApiResponse[IntegrationCatalogOut])
def catalog(
    category: str | None = Query(default=None, max_length=100),
    brand: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    ctx=Depends(require_api_key("catalog:read")),
    db: Session = Depends(get_db),
):
    """Permite a sistemas externos (ERP, marketplace, facturadores) consultar el catálogo completo de la empresa."""
    query = (
        select(ProductModel)
        .where(
            ProductModel.tenant_id == ctx.tenant_id,
            ProductModel.deleted_at.is_(None),
        )
    )
    if category:
        query = query.join(CategoryModel, CategoryModel.id == ProductModel.category_id).where(
            or_(CategoryModel.slug == category, CategoryModel.name.ilike(f"%{category}%"))
        )
    if brand:
        query = query.where(ProductModel.brand.ilike(f"%{brand}%"))

    products = list(
        db.scalars(
            query.order_by(ProductModel.name.asc()).offset(offset).limit(limit)
        ).all()
    )

    items = []
    for prod in products:
        category_name = prod.category.name if prod.category else None
        variants_out = []
        for var in prod.variants:
            effective_price = (
                var.price_override if var.price_override is not None else prod.base_price
            )
            size_label = var.size.code if var.size else None
            color_label = var.color.name if var.color else None
            variants_out.append(
                IntegrationCatalogVariantOut(
                    id=var.id,
                    sku=var.sku,
                    size=size_label,
                    color=color_label,
                    barcode=var.barcode,
                    price=str(effective_price),
                    is_active=var.is_active,
                )
            )

        items.append(
            IntegrationCatalogProductOut(
                id=prod.id,
                name=prod.name,
                slug=prod.slug,
                description=prod.description,
                brand=prod.brand,
                gender=prod.gender,
                category=category_name,
                base_price=str(prod.base_price),
                is_active=prod.is_active,
                variants=variants_out,
            )
        )

    return ApiResponse(
        message="Catálogo consultado exitosamente.",
        data={"items": items, "total": len(items)},
    )


@router.post("/stock/adjust", response_model=ApiResponse[IntegrationStockAdjustOut])
def adjust_stock(
    payload: IntegrationStockAdjustIn,
    ctx=Depends(require_api_key("stock:write")),
    db: Session = Depends(get_db),
):
    """
    Permite a un ERP o almacén externo sincronizar y ajustar el stock físico en la plataforma SaaS.
    Emite webhooks 'stock.updated' y 'stock.low' cuando las existencias son bajas.
    """
    webhooks_svc = WebhooksService(db)
    updated_items = []

    for item in payload.items:
        # 1. Validar que la variante exista y pertenezca a un producto del tenant autenticado
        variant = db.scalar(
            select(ProductVariantModel)
            .join(ProductModel, ProductModel.id == ProductVariantModel.product_id)
            .where(
                ProductVariantModel.sku == item.sku,
                ProductModel.tenant_id == ctx.tenant_id,
                ProductModel.deleted_at.is_(None),
            )
        )
        if not variant:
            raise ValidationError(
                f"El SKU '{item.sku}' no existe o no pertenece a su empresa."
            )

        # 2. Validar que la sucursal exista y pertenezca al tenant autenticado
        branch = db.scalar(
            select(BranchModel).where(
                BranchModel.code == item.branch_code,
                BranchModel.tenant_id == ctx.tenant_id,
                BranchModel.deleted_at.is_(None),
            )
        )
        if not branch:
            raise ValidationError(
                f"La sucursal con código '{item.branch_code}' no existe o no pertenece a su empresa."
            )

        # 3. Buscar o inicializar registro de stock
        stock_rec = db.scalar(
            select(StockModel).where(
                StockModel.variant_id == variant.id,
                StockModel.branch_id == branch.id,
            )
        )
        if stock_rec:
            prev_qty = stock_rec.quantity
            if item.mode == "delta":
                new_qty = max(0, prev_qty + item.quantity)
            else:
                new_qty = max(0, item.quantity)
            stock_rec.quantity = new_qty
        else:
            prev_qty = 0
            new_qty = max(0, item.quantity)
            stock_rec = StockModel(
                variant_id=variant.id,
                branch_id=branch.id,
                quantity=new_qty,
            )
            db.add(stock_rec)

        updated_items.append(
            IntegrationStockAdjustItemOut(
                sku=item.sku,
                branch_code=item.branch_code,
                previous_quantity=prev_qty,
                new_quantity=new_qty,
                status="updated",
            )
        )

        # 4. Disparar webhooks automáticos si hay suscriptores
        webhooks_svc.publicar_si_hay_suscriptores(
            tenant_id=ctx.tenant_id,
            event_type="stock.updated",
            data={
                "sku": item.sku,
                "branch_code": item.branch_code,
                "previous_quantity": prev_qty,
                "new_quantity": new_qty,
                "mode": item.mode,
            },
        )
        if new_qty <= 5:
            webhooks_svc.publicar_si_hay_suscriptores(
                tenant_id=ctx.tenant_id,
                event_type="stock.low",
                data={
                    "sku": item.sku,
                    "branch_code": item.branch_code,
                    "quantity": new_qty,
                    "threshold": 5,
                },
            )

    db.commit()

    return ApiResponse(
        message=f"Se actualizaron {len(updated_items)} registro(s) de inventario.",
        data=IntegrationStockAdjustOut(
            updated_count=len(updated_items),
            items=updated_items,
            timestamp=datetime.now(timezone.utc),
        ),
    )
