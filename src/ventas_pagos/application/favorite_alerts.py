"""Avisos de favoritos: se disparan solo por una reposición o una rebaja."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.infrastructure.config.settings import settings
from src.notificaciones.application.use_cases.send_email import EnviarCorreo
from src.notificaciones.domain.diseno import Mensaje, boton, envolver, nota
from src.ventas_pagos.infrastructure.engagement_models import FavoriteModel

#: Tope de avisos por evento. Guardar un precio no puede convertirse en una
#: tarea de tamaño desconocido: con la cola encolar es inmediato, pero mil
#: favoritos igual serían mil correos saliendo de un solo cambio. Lo que se
#: recorta queda en bitácora —un recorte silencioso sería peor que el problema—
#: y, como a esas filas no se les toca `observed_price`, siguen siendo
#: candidatas para la próxima rebaja.
TOPE_DESTINATARIOS = 200


class FavoriteAlerts:
    def __init__(self, db: Session): self.db = db

    def restocked(self, product, previous: int, current: int) -> None:
        if previous > 0 or current <= 0: return
        rows, usuarios = self._lote(product, FavoriteModel.stock_alert.is_(True))
        for row in rows:
            self._send(usuarios.get(row.user_id), product,
                "Volvió una prenda que guardaste", "Hay stock disponible nuevamente.", row)
            row.last_stock_alert_at = datetime.now(timezone.utc)
        # Este commit es el que baja a base las marcas del lote entero. Antes lo
        # adelantaba el envío de la fila siguiente; ahora el envío ya no toca
        # esta Session, así que este es el único que queda y sigue alcanzando.
        if rows: self.db.commit()

    def price_dropped(self, product, old_price) -> None:
        if product.base_price >= old_price: return
        rows, usuarios = self._lote(product, FavoriteModel.price_alert.is_(True),
            FavoriteModel.observed_price > product.base_price)
        for row in rows:
            self._send(usuarios.get(row.user_id), product,
                "Bajó el precio de un favorito", f"Ahora cuesta {product.base_price} BOB.", row)
            row.observed_price = product.base_price
            row.last_price_alert_at = datetime.now(timezone.utc)
        if rows: self.db.commit()

    def _lote(self, product, *condiciones) -> tuple[list[FavoriteModel], dict]:
        """Favoritos a avisar y sus usuarios, resueltos en una sola consulta.

        Antes el usuario se pedía dentro del bucle: con 20 favoritos eran 20
        viajes a la base además de los 20 correos. El orden es explícito para
        que el recorte del tope sea reproducible y avise primero a quien guardó
        la prenda antes.
        """
        rows = list(self.db.scalars(
            select(FavoriteModel)
            .where(FavoriteModel.product_id == product.id, *condiciones)
            .order_by(FavoriteModel.created_at, FavoriteModel.id)
        ))
        if len(rows) > TOPE_DESTINATARIOS:
            self._registrar_recorte(product, len(rows))
            rows = rows[:TOPE_DESTINATARIOS]
        if not rows:
            return [], {}
        usuarios = {user.id: user for user in self.db.scalars(
            select(UserModel).where(UserModel.id.in_([row.user_id for row in rows]))
        )}
        return rows, usuarios

    def _registrar_recorte(self, product, total: int) -> None:
        RecordAuditEvent(self.db).execute(
            action="notificaciones.favoritos_recortados",
            entity_type="product",
            entity_id=str(product.id),
            description="Aviso de favoritos limitado por el tope de destinatarios.",
            metadata={"total": total, "avisados": TOPE_DESTINATARIOS,
                "sin_aviso": total - TOPE_DESTINATARIOS},
        )

    def _send(self, user, product, subject: str, message: str, favorite) -> None:
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
