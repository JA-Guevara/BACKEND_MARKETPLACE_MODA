"""Envío de un aviso por correo, registrado en bitácora.

Un aviso no puede tumbar la operación que lo origina: si el servidor de correo
está caído o sin configurar, el pedido igual se registra. Por eso el envío es
"lo mejor posible" y lo único obligatorio es dejar rastro de si salió o no.
"""
import uuid

from sqlalchemy.orm import Session

from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.notificaciones.domain.plantillas import Mensaje
from src.notificaciones.infrastructure.email.email_sender import EmailSender


class EnviarCorreo:
    def __init__(self, db: Session, sender: EmailSender | None = None) -> None:
        self.db = db
        self.sender = sender or EmailSender()

    def execute(
        self,
        *,
        destinatario: str | None,
        mensaje: Mensaje,
        entidad: str,
        entidad_id: str | None = None,
        actor_id: uuid.UUID | None = None,
        contexto: dict | None = None,
    ) -> bool:
        if not destinatario:
            return False
        try:
            enviado = self.sender.send(
                to=destinatario, subject=mensaje.asunto, body=mensaje.texto, html=mensaje.html
            )
        except Exception:  # noqa: BLE001 - el aviso nunca interrumpe la operación
            enviado = False
        try:
            RecordAuditEvent(self.db).execute(
                action="notificaciones.email_enviado" if enviado else "notificaciones.email_fallido",
                entity_type=entidad,
                entity_id=entidad_id,
                description=mensaje.asunto,
                actor_user_id=actor_id,
                # El destinatario queda en bitácora para poder auditar el aviso;
                # el cuerpo no, porque repetiría datos del pedido sin aportar.
                metadata={"to": destinatario, "sent": enviado, **(contexto or {})},
            )
            self.db.commit()
        except Exception:  # noqa: BLE001
            self.db.rollback()
        return enviado
