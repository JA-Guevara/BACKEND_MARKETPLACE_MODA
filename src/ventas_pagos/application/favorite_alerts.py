"""Avisos de favoritos: se disparan solo por una reposición o una rebaja."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.config.settings import settings
from src.notificaciones.application.use_cases.send_email import EnviarCorreo
from src.notificaciones.domain.diseno import Mensaje, boton, envolver, nota
from src.ventas_pagos.infrastructure.engagement_models import FavoriteModel


class FavoriteAlerts:
    def __init__(self, db: Session): self.db = db

    def restocked(self, product, previous: int, current: int) -> None:
        if previous > 0 or current <= 0: return
        rows = self.db.scalars(select(FavoriteModel).where(
            FavoriteModel.product_id == product.id, FavoriteModel.stock_alert.is_(True)
        )).all()
        for row in rows:
            self._send(row, product, "Volvió una prenda que guardaste", "Hay stock disponible nuevamente.")
            row.last_stock_alert_at = datetime.now(timezone.utc)
        if rows: self.db.commit()

    def price_dropped(self, product, old_price) -> None:
        if product.base_price >= old_price: return
        rows = self.db.scalars(select(FavoriteModel).where(
            FavoriteModel.product_id == product.id, FavoriteModel.price_alert.is_(True),
            FavoriteModel.observed_price > product.base_price,
        )).all()
        for row in rows:
            self._send(row, product, "Bajó el precio de un favorito", f"Ahora cuesta {product.base_price} BOB.")
            row.observed_price = product.base_price
            row.last_price_alert_at = datetime.now(timezone.utc)
        if rows: self.db.commit()

    def _send(self, favorite, product, subject: str, message: str) -> None:
        user = self.db.get(UserModel, favorite.user_id)
        if not user or not user.is_active: return
        link = f"{settings.frontend_url}/prendas/{product.slug}"
        email = Mensaje(
            asunto=f"{subject} · FashionStore",
            texto=f"{message}\n\n{product.name}\nMirá la prenda: {link}",
            html=envolver(titulo=subject, distintivo="Favoritos", tono="exito", entrada=message,
                contenido=nota(product.name) + boton("Ver prenda", link)),
        )
        EnviarCorreo(self.db).execute(destinatario=user.email, mensaje=email, entidad="favorite",
            entidad_id=str(favorite.id), actor_id=user.id, contexto={"product_id": str(product.id)})
