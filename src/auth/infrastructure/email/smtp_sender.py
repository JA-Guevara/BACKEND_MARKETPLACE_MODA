import smtplib
from email.message import EmailMessage

from src.infrastructure.config.settings import settings


class SMTPEmailSender:
    def send(self, *, to: str, subject: str, body: str) -> bool:
        if not settings.smtp_host:
            return False
        message = EmailMessage()
        message["From"] = settings.smtp_from_email
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                if settings.smtp_use_tls:
                    server.starttls()
                if settings.smtp_username and settings.smtp_password:
                    server.login(settings.smtp_username, settings.smtp_password)
                server.send_message(message)
            return True
        except (OSError, smtplib.SMTPException):
            return False
