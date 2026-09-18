"""Salida de correo del módulo de notificaciones.

Reutiliza el remitente SMTP que ya usaba la verificación de cuenta en vez de
duplicar la conexión: un solo lugar donde ajustar credenciales, tiempo de
espera y TLS.
"""
from src.auth.infrastructure.email.smtp_sender import SMTPEmailSender


class EmailSender(SMTPEmailSender):
    """Envía un correo y devuelve si salió. Nunca levanta excepción."""
