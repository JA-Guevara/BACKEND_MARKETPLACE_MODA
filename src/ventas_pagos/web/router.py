import uuid
from collections import Counter
from decimal import Decimal
from typing import Annotated
import httpx
from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, delete, func
from sqlalchemy.orm import Session
from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.web.dependencies import get_current_user
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_permissions
from src.infrastructure.config.settings import settings
from src.shared.responses.api_response import ApiResponse
from src.usuarios_catalogo.infrastructure.models.catalog import ProductVariantModel, ProductModel
from src.inventario_sucursales.infrastructure.models.organization import BranchModel
from src.ventas_pagos.infrastructure.models import StockModel, CartItemModel, OrderModel
from src.ventas_pagos.infrastructure.gateways import verify_event
from src.ventas_pagos.application.service import CommerceService
from src.ventas_pagos.web.schemas import Quantity, StockQuantity, CheckoutOrder, TrackingUpdate, ManualPayment, ProfileUpdate

router = APIRouter(prefix="/commerce", tags=["commerce"])
analytics_router = APIRouter(prefix="/analytics", tags=["analytics"])
User = Annotated[UserModel, Depends(get_current_user)]
Reader = Annotated[UserModel, Depends(require_permissions("commerce.read"))]
Writer = Annotated[UserModel, Depends(require_permissions("commerce.write"))]
StockReader = Annotated[UserModel, Depends(require_permissions("stock.read"))]
StockWriter = Annotated[UserModel, Depends(require_permissions("stock.write"))]
Analyst = Annotated[UserModel, Depends(require_permissions("dashboard.read"))]


def response(data=None):
    return ApiResponse(message="Operacion completada.", data=jsonable_encoder(data))


def order_data(order):
    data = {column.name: getattr(order, column.name) for column in OrderModel.__table__.columns if column.name not in {"stripe_url", "stripe_session_id"}}
    data["total"] = str(order.total)
    return data


@router.get("/branches")
def branches(db: Session = Depends(get_db)):
    return response([{"id": row.id, "name": row.name, "address": row.address} for row in db.scalars(select(BranchModel).where(BranchModel.is_active.is_(True), BranchModel.deleted_at.is_(None))).all()])


@router.patch("/profile")
def profile(data: ProfileUpdate, user: User, db: Session = Depends(get_db)):
    for key, value in data.model_dump().items():
        setattr(user, key, value)
    db.commit()
    return response({"id": user.id, "email": user.email, "first_name": user.first_name, "last_name": user.last_name, "phone": user.phone})


@router.get("/cart")
def cart(user: User, branch_id: uuid.UUID | None = None, db: Session = Depends(get_db)):
    return response(CommerceService(db).cart(user, branch_id))


@router.put("/cart/items/{variant_id}")
def set_cart(variant_id: uuid.UUID, data: Quantity, user: User, db: Session = Depends(get_db)):
    CommerceService(db).set_cart(user, variant_id, data.quantity)
    return response()


@router.delete("/cart/items/{variant_id}")
def delete_cart(variant_id: uuid.UUID, user: User, db: Session = Depends(get_db)):
    db.execute(select(UserModel.id).where(UserModel.id == user.id).with_for_update())
    db.execute(delete(CartItemModel).where(CartItemModel.user_id == user.id, CartItemModel.variant_id == variant_id))
    db.commit()
    return response()


@router.post("/orders", status_code=201)
def create_order(data: CheckoutOrder, user: User, db: Session = Depends(get_db)):
    return response(order_data(CommerceService(db).create_order(user, data)))


@router.get("/orders")
def orders(user: User, db: Session = Depends(get_db), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    return response([order_data(o) for o in db.scalars(select(OrderModel).where(OrderModel.user_id == user.id).order_by(OrderModel.created_at.desc()).offset(offset).limit(limit))])


@router.get("/orders/{order_id}")
def get_order(order_id: uuid.UUID, user: User, db: Session = Depends(get_db)):
    return response(order_data(CommerceService(db).order(order_id, user)))


@router.post("/orders/{order_id}/checkout")
def checkout(order_id: uuid.UUID, user: User, db: Session = Depends(get_db)):
    service = CommerceService(db)
    return response(service.checkout(service.order(order_id, user)))


@router.post("/orders/{order_id}/cancel")
def cancel(order_id: uuid.UUID, user: User, db: Session = Depends(get_db)):
    service = CommerceService(db)
    return response(order_data(service.cancel(service.order(order_id, user))))


@router.get("/admin/orders")
def admin_orders(user: Reader, db: Session = Depends(get_db), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    return response([order_data(o) for o in db.scalars(select(OrderModel).order_by(OrderModel.created_at.desc()).offset(offset).limit(limit))])


@router.patch("/admin/orders/{order_id}/tracking")
def tracking(order_id: uuid.UUID, data: TrackingUpdate, user: Writer, db: Session = Depends(get_db)):
    service = CommerceService(db)
    return response(order_data(service.tracking(service.order(order_id), data)))


@router.post("/admin/orders/{order_id}/payment")
def payment(order_id: uuid.UUID, data: ManualPayment, user: Writer, db: Session = Depends(get_db)):
    service = CommerceService(db)
    return response(order_data(service.manual_payment(service.order(order_id), data)))


@router.get("/admin/stock")
def stock(user: StockReader, branch_id: uuid.UUID, db: Session = Depends(get_db)):
    service = CommerceService(db)
    service.branch(branch_id)
    variants = db.scalars(select(ProductVariantModel).where(ProductVariantModel.is_active.is_(True))).all()
    return response([{**service.snapshot(v, 1, branch_id), "branch_id": branch_id, "quantity": service.snapshot(v, 1, branch_id)["available"]} for v in variants if v.product.is_active and not v.product.deleted_at])


@router.put("/admin/stock/{variant_id}")
def update_stock(variant_id: uuid.UUID, data: StockQuantity, user: StockWriter, db: Session = Depends(get_db)):
    service = CommerceService(db)
    service.branch(data.branch_id)
    service.variant(variant_id)
    # Serialize inserts as well as updates by locking the existing variant.
    db.execute(select(ProductVariantModel.id).where(ProductVariantModel.id == variant_id).with_for_update())
    row = db.scalar(select(StockModel).where(StockModel.variant_id == variant_id, StockModel.branch_id == data.branch_id).with_for_update())
    if row:
        row.quantity = data.quantity
    else:
        db.add(StockModel(variant_id=variant_id, branch_id=data.branch_id, quantity=data.quantity))
    db.commit()
    return response({"variant_id": variant_id, **data.model_dump()})


@router.post("/stripe/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    return CommerceService(db).webhook(verify_event(body, request.headers.get("stripe-signature", "")))


def metrics(db):
    orders = db.scalars(select(OrderModel)).all()
    paid = [o for o in orders if o.payment_status == "paid"]
    products = db.scalar(select(func.count()).select_from(ProductModel).where(ProductModel.deleted_at.is_(None)))
    statuses = Counter(o.status for o in orders)
    daily = {}
    top = {}
    for order in paid:
        day = order.created_at.date().isoformat()
        daily[day] = daily.get(day, Decimal(0)) + order.total
        for item in order.items:
            top[item["name"]] = top.get(item["name"], 0) + item["quantity"]
    return {"orders": len(orders), "paid_orders": len(paid), "pending_orders": statuses.get("pending_payment", 0),
        "revenue": str(sum((o.total for o in paid), Decimal(0))), "currency": settings.commerce_currency,
        "products": products, "customers": db.scalar(select(func.count()).select_from(UserModel)),
        "low_stock": db.scalar(select(func.count()).select_from(StockModel).where(StockModel.quantity < 5)),
        "by_status": dict(statuses), "daily_sales": [{"date": key, "total": str(value)} for key, value in sorted(daily.items())[-30:]],
        "top_products": [{"name": key, "quantity": value} for key, value in sorted(top.items(), key=lambda x: -x[1])[:5]],
        "stripe_ready": settings.stripe_secret_key.startswith("sk_test_") and bool(settings.stripe_webhook_secret),
        "ai_ready": bool(settings.ai_api_key)}


@analytics_router.get("/dashboard")
def dashboard(user: Analyst, db: Session = Depends(get_db)):
    return response(metrics(db))


@analytics_router.post("/insights")
def insights(user: Analyst, db: Session = Depends(get_db)):
    if not settings.ai_api_key:
        return response({"available": False, "message": "Configure AI_API_KEY para habilitar recomendaciones. Las metricas reales ya estan disponibles."})
    try:
        result = httpx.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": "Bearer " + settings.ai_api_key},
            json={"model": settings.ai_model, "messages": [{"role": "system", "content": "Eres analista de FashionStore. Da 3 recomendaciones breves en español basadas solo en metricas agregadas. No inventes tendencias ni causalidad. Señala cuando faltan datos."},
            {"role": "user", "content": str(metrics(db))}], "max_tokens": 450}, timeout=25)
        result.raise_for_status()
        return response({"available": True, "message": result.json()["choices"][0]["message"]["content"]})
    except (httpx.HTTPError, KeyError, ValueError, IndexError):
        return response({"available": False, "message": "El servicio de IA no respondio. Puede continuar usando las metricas reales."})
