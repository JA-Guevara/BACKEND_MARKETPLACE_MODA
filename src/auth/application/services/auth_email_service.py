from src.auth.infrastructure.email.smtp_sender import SMTPEmailSender
from src.infrastructure.config.settings import settings


class AuthEmailService:
    def __init__(self, sender: SMTPEmailSender | None = None) -> None:
        self.sender = sender or SMTPEmailSender()

    def send_verification(self, email: str, token: str) -> bool:
        link = f"{settings.frontend_url}/verificar-correo?token={token}"
        return self.sender.send(
            to=email,
            subject="Verifica tu cuenta de FashionStore",
            body=f"Verifica tu correo ingresando al siguiente enlace:\n\n{link}",
        )

    def send_password_reset(self, email: str, token: str) -> bool:
        link = f"{settings.frontend_url}/recuperar-contrasena?token={token}"
        return self.sender.send(
            to=email,
            subject="Recupera tu contrasena de FashionStore",
            body=f"Puedes crear una nueva contrasena ingresando al siguiente enlace:\n\n{link}",
        )
