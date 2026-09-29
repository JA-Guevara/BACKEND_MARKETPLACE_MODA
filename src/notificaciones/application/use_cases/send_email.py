"""Envío de un aviso por correo, registrado en bitácora.

Un aviso no puede tumbar la operación que lo origina: si el servidor de correo
está caído o sin configurar, el pedido igual se registra. Por eso el envío es
"lo mejor posible" y lo único obligatorio es dejar rastro de si salió o no.

Desde que existe la cola (`infrastructure/email/cola.py`) el envío ya no ocurre
dentro del request: acá se arma el trabajo con valores planos y se encola. Lo
que sí sigue pasando en el request es la decisión de a quién se le escribe y el
armado del mensaje, porque eso necesita la Session viva.
"""
import uuid

from sqlalchemy.orm import Session

from src.infrastructure.config.settings import settings
from src.notificaciones.domain.plantillas import Mensaje
from src.notificaciones.infrastructure.email.cola import (
    TrabajoCorreo, cola_de_correos, enviar, registrar,
)
from src.notificaciones.infrastructure.email.email_sender import EmailSender
from src.shared.context.audit_context import (
    get_audit_actor, get_audit_ip_address, get_audit_request_id, get_audit_user_agent,
)


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
        """Manda el aviso y devuelve si quedó resuelto.

        En línea (`EMAIL_BACKGROUND=false`) el booleano es el de siempre: si el
        correo salió de verdad. En segundo plano pasa a significar "el aviso
        quedó aceptado", porque el SMTP todavía no ocurrió. El cambio es seguro:
        en producción nadie lee ese valor —los atajos `notificar_*` lo descartan
        y ningún endpoint ni esquema de respuesta lo expone—, y el único caso que
        siempre tiene que responder False es la falta de destinatario, que se
        evalúa antes de encolar.
        """
        if not destinatario:
            return False
        trabajo = TrabajoCorreo(
            remitente=self.sender,
            destinatario=destinatario,
            mensaje=mensaje,
            entidad=entidad,
            entidad_id=entidad_id,
            # Los contextvars no cruzan al hilo: se resuelven acá, en el request.
            actor_id=actor_id or get_audit_actor(),
            contexto=dict(contexto or {}),
            ip_address=get_audit_ip_address(),
            user_agent=get_audit_user_agent(),
            request_id=get_audit_request_id(),
        )
        if settings.email_background and cola_de_correos().encolar(trabajo):
            return True
        # Cola llena o apagada: se envía en línea antes que perder el aviso.
        return self._en_linea(trabajo)

    def _en_linea(self, trabajo: TrabajoCorreo) -> bool:
        """El camino de siempre: SMTP y bitácora sobre la Session del request.

        Sigue confirmando esa Session igual que antes de existir la cola, así
        que ningún llamador que se apoyara en ese commit cambia de comportamiento.
        """
        enviado = enviar(trabajo)
        registrar(self.db, trabajo, enviado)
        return enviado
