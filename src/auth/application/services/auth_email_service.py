"""Avisos de la cuenta: verificar correo y recuperar contrasena.

Eran los unicos envios que no pasaban por `EnviarCorreo` y por lo tanto los
unicos que seguian ocurriendo dentro del request. Los tres puntos que los
disparan -registrarse, pedir el enlace de recuperacion y reenviar la
verificacion- pagaban el saludo TCP+TLS con el servidor de correo (1,45 s
medidos) antes de contestarle a la persona, y ademas retenian la conexion de
base todo ese rato. Ahora se encolan en la misma cola del modulo de
notificaciones.

Lo que NO cambia: estos avisos nunca dejaron evento de bitacora, asi que van con
`auditar=False` y el trabajo de fondo se limita al SMTP. El correo que llega es
el mismo (mismo asunto, mismo cuerpo, sin parte HTML, `html=""` es falso para el
remitente). Y si la cola esta llena o apagada, se envia en linea igual que antes.
"""
from src.auth.infrastructure.email.smtp_sender import SMTPEmailSender
from src.infrastructure.config.settings import settings
from src.notificaciones.domain.diseno import Mensaje
from src.notificaciones.infrastructure.email.cola import TrabajoCorreo, cola_de_correos


class AuthEmailService:
    def __init__(self, sender: SMTPEmailSender | None = None) -> None:
        self.sender = sender or SMTPEmailSender()

    def _entregar(self, *, email: str, asunto: str, cuerpo: str) -> bool:
        """True si el aviso quedo resuelto: enviado en linea, o aceptado por la cola.

        El valor de retorno lo descartan los tres llamadores de `AuthService`,
        asi que el cambio de significado en modo fondo no se observa desde
        ningun endpoint; en modo en linea sigue siendo el booleano real del SMTP.
        """
        trabajo = TrabajoCorreo(
            remitente=self.sender,
            destinatario=email,
            mensaje=Mensaje(asunto=asunto, texto=cuerpo, html=""),
            entidad="auth",
            auditar=False,
        )
        if settings.email_background and cola_de_correos().encolar(trabajo):
            return True
        # En linea se llama al remitente tal cual se lo llamaba antes, y no a
        # `enviar` de la cola: ese envuelve todo en try/except, o sea que una
        # excepcion inesperada pasaria de propagar a volverse un False silencioso.
        return self.sender.send(to=email, subject=asunto, body=cuerpo)

    def send_verification(self, email: str, token: str) -> bool:
        link = f"{settings.frontend_url}/verificar-correo?token={token}"
        return self._entregar(
            email=email,
            asunto="Verifica tu cuenta de FashionStore",
            cuerpo=f"Verifica tu correo ingresando al siguiente enlace:\n\n{link}",
        )

    def send_password_reset(self, email: str, token: str) -> bool:
        link = f"{settings.frontend_url}/recuperar-contrasena?token={token}"
        return self._entregar(
            email=email,
            asunto="Recupera tu contrasena de FashionStore",
            cuerpo=f"Puedes crear una nueva contrasena ingresando al siguiente enlace:\n\n{link}",
        )
