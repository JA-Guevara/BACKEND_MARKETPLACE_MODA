"""API de promociones (gestión) y favoritos (cliente)."""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.web.dependencies import get_current_user
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_permissions
from src.shared.exceptions.domain_exception import NotFoundError
from src.shared.responses.api_response import ApiResponse
from src.usuarios_catalogo.infrastructure.models.catalog import CategoryModel, ProductModel
from src.ventas_pagos.infrastructure.engagement_models import FavoriteModel, PromotionModel

router = APIRouter(prefix="/commerce", tags=["promotions and favorites"])
User = Annotated[UserModel, Depends(get_current_user)]
PromotionReader = Annotated[UserModel, Depends(require_permissions("commerce.read"))]
PromotionWriter = Annotated[UserModel, Depends(require_permissions("commerce.write"))]


class PromotionInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    name: str = Field(min_length=3, max_length=160)
    code: str | None = Field(default=None, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    description: str | None = Field(default=None, max_length=500)
    discount_type: Literal["percent", "fixed", "free_shipping"]
    discount_value: Decimal = Field(default=Decimal(0), ge=0, le=1000000)
    minimum_order: Decimal = Field(default=Decimal(0), ge=0, le=1000000)
    category_id: uuid.UUID | None = None
    product_id: uuid.UUID | None = None
    customer_scope: Literal["all", "frequent"] = "all"
    minimum_paid_orders: int = Field(default=0, ge=0, le=1000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    max_uses: int | None = Field(default=None, ge=1, le=1000000)
    per_user_limit: int | None = Field(default=None, ge=1, le=1000)
    is_active: bool = True

    @model_validator(mode="after")
    def valid_rule(self):
        if self.category_id and self.product_id:
            raise ValueError("Elegí una categoría o una prenda, no ambas.")
        if self.discount_type == "percent" and not 0 < self.discount_value <= 100:
            raise ValueError("El porcentaje debe estar entre 0,01 y 100.")
        if self.discount_type == "fixed" and self.discount_value <= 0:
            raise ValueError("El descuento fijo debe ser mayor a cero.")
        if self.discount_type == "free_shipping" and self.discount_value != 0:
            raise ValueError("Envío gratis no lleva importe de descuento.")
        if self.ends_at and self.starts_at and self.ends_at <= self.starts_at:
            raise ValueError("La fecha final debe ser posterior a la inicial.")
        if self.customer_scope == "frequent" and self.minimum_paid_orders < 1:
            self.minimum_paid_orders = 2
        return self


class PromotionUpdate(PromotionInput):
    pass


class FavoriteInput(BaseModel):
    stock_alert: bool = True
    price_alert: bool = True


def promotion_data(row: PromotionModel) -> dict:
    return {
        "id": str(row.id), "name": row.name, "code": row.code, "description": row.description,
        "discount_type": row.discount_type, "discount_value": str(row.discount_value),
        "minimum_order": str(row.minimum_order), "category_id": str(row.category_id) if row.category_id else None,
        "product_id": str(row.product_id) if row.product_id else None, "customer_scope": row.customer_scope,
        "minimum_paid_orders": row.minimum_paid_orders, "starts_at": row.starts_at, "ends_at": row.ends_at,
        "max_uses": row.max_uses, "uses_count": row.uses_count, "per_user_limit": row.per_user_limit,
        "is_active": row.is_active, "created_at": row.created_at,
    }


def _validate_scope(db: Session, data: PromotionInput) -> None:
    if data.category_id and not db.get(CategoryModel, data.category_id):
        raise NotFoundError("La categoría seleccionada no existe.")
    if data.product_id and not db.get(ProductModel, data.product_id):
        raise NotFoundError("La prenda seleccionada no existe.")


@router.get("/admin/promotions")
def promotions(actor: PromotionReader, db: Session = Depends(get_db), active: bool | None = Query(None)):
    query = select(PromotionModel).order_by(PromotionModel.created_at.desc())
    if active is not None: query = query.where(PromotionModel.is_active.is_(active))
    return ApiResponse(message="Promociones obtenidas.", data=[promotion_data(row) for row in db.scalars(query)])


@router.post("/admin/promotions", status_code=status.HTTP_201_CREATED)
def create_promotion(data: PromotionInput, actor: PromotionWriter, db: Session = Depends(get_db)):
    _validate_scope(db, data)
    row = PromotionModel(**data.model_dump(), code=data.code.upper() if data.code else None, created_by=actor.id)
    db.add(row); db.commit(); db.refresh(row)
    return ApiResponse(message="Promoción creada.", data=promotion_data(row))


@router.patch("/admin/promotions/{promotion_id}")
def update_promotion(promotion_id: uuid.UUID, data: PromotionUpdate, actor: PromotionWriter, db: Session = Depends(get_db)):
    row = db.get(PromotionModel, promotion_id)
    if not row: raise NotFoundError("Promoción no encontrada.")
    _validate_scope(db, data)
    for key, value in data.model_dump().items(): setattr(row, key, value.upper() if key == "code" and value else value)
    db.commit(); db.refresh(row)
    return ApiResponse(message="Promoción actualizada.", data=promotion_data(row))


@router.get("/favorites")
def favorites(user: User, db: Session = Depends(get_db)):
    rows = db.scalars(select(FavoriteModel).where(FavoriteModel.user_id == user.id).order_by(FavoriteModel.created_at.desc())).all()
    result = []
    for row in rows:
        product = db.get(ProductModel, row.product_id)
        if not product or product.deleted_at: continue
        result.append({
            "id": str(row.id), "product_id": str(product.id), "slug": product.slug, "name": product.name,
            "base_price": str(product.base_price), "image_url": product.images[0].url if product.images else None,
            "stock_alert": row.stock_alert, "price_alert": row.price_alert,
        })
    return ApiResponse(message="Favoritos obtenidos.", data=result)


@router.get("/favorites/{product_id}")
def favorite(product_id: uuid.UUID, user: User, db: Session = Depends(get_db)):
    row = db.scalar(select(FavoriteModel).where(FavoriteModel.user_id == user.id, FavoriteModel.product_id == product_id))
    return ApiResponse(message="Favorito consultado.", data={
        "is_favorite": bool(row), "stock_alert": row.stock_alert if row else True, "price_alert": row.price_alert if row else True,
    })


@router.put("/favorites/{product_id}")
def save_favorite(product_id: uuid.UUID, data: FavoriteInput, user: User, db: Session = Depends(get_db)):
    product = db.get(ProductModel, product_id)
    if not product or not product.is_active or product.deleted_at: raise NotFoundError("Prenda no disponible.")
    row = db.scalar(select(FavoriteModel).where(FavoriteModel.user_id == user.id, FavoriteModel.product_id == product_id))
    if row is None:
        row = FavoriteModel(user_id=user.id, product_id=product.id, observed_price=product.base_price)
        db.add(row)
    row.stock_alert, row.price_alert = data.stock_alert, data.price_alert
    db.commit()
    return ApiResponse(message="Prenda guardada en favoritos.", data={"is_favorite": True, "stock_alert": row.stock_alert, "price_alert": row.price_alert})


@router.delete("/favorites/{product_id}")
def delete_favorite(product_id: uuid.UUID, user: User, db: Session = Depends(get_db)):
    row = db.scalar(select(FavoriteModel).where(FavoriteModel.user_id == user.id, FavoriteModel.product_id == product_id))
    if row: db.delete(row); db.commit()
    return ApiResponse(message="Prenda eliminada de favoritos.", data={"is_favorite": False})
