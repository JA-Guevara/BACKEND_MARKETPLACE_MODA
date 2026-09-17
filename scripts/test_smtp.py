"""Diagnostico SMTP optativo: conectar y autenticar; enviar solo con --send-to.

Usa los mismos Settings del backend. No imprime contrasenas ni respuestas
SMTP sin filtrar. No lo ejecuta pytest como prueba de red.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import smtplib
import socket
import ssl
import sys
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

__test__ = False


def diagnose(config, *, send_to=None, timeout=10, output=print):
    """Retorna 0 si pasa, 1 por fallo de red/SMTP o 2 por configuracion."""
    host = (config.smtp_host or '').strip()
    user = (config.smtp_username or '').strip()
    password = config.smtp_password or ''
    sender = config.smtp_from_email or ''
    output(f'Servidor: {host or "NO CONFIGURADO"}:{config.smtp_port}')
    output(f'STARTTLS: {config.smtp_use_tls}')
    output(f'Usuario: {user or "NO CONFIGURADO"}')
    output(f'Remitente: {sender or "NO CONFIGURADO"}')
    output('Contrasena: ' + ('configurada (oculta)' if password.strip() else 'NO CONFIGURADA'))

    if not host:
        output('ERROR: falta SMTP_HOST; el backend no intentara enviar.')
        return 2
    if config.smtp_port == 465:
        output('ERROR: el remitente actual usa SMTP con STARTTLS, no SMTP_SSL. '
               'Para Gmail usa puerto 587 y SMTP_USE_TLS=true.')
        return 2
    if bool(user) != bool(password.strip()):
        output('ERROR: SMTP_USERNAME y SMTP_PASSWORD deben estar completos. '
               'Con Gmail usa una contrasena de aplicacion.')
        return 2
    if host.lower() == 'smtp.gmail.com' and (not user or not config.smtp_use_tls):
        output('ERROR: Gmail requiere usuario, contrasena de aplicacion y STARTTLS en este cliente.')
        return 2
    if user and not config.smtp_use_tls:
        output('ERROR: no se enviaran credenciales mediante una conexion sin cifrar.')
        return 2
    if sender.endswith('.local'):
        output('AVISO: SMTP_FROM_EMAIL usa .local. Para Gmail configura tu correo '
               'autenticado o un alias autorizado.')
    if host.lower() == 'smtp.gmail.com' and sender.casefold() != user.casefold():
        output('AVISO: el remitente difiere del usuario; debe ser un alias autorizado.')
    if send_to and (not sender or '\n' in send_to or '\r' in send_to or '@' not in send_to):
        output('ERROR: revisa el remitente y la direccion indicada en --send-to.')
        return 2

    server = None
    stage = 'conexion TCP y saludo SMTP'
    try:
        output(f'Probando {stage}...')
        server = smtplib.SMTP(host, config.smtp_port, timeout=timeout)
        code, _ = server.ehlo()
        if code != 250:
            output(f'ERROR: EHLO rechazado (codigo {code}).')
            return 1
        output('OK: conexion y saludo SMTP.')

        if config.smtp_use_tls:
            stage = 'negociacion STARTTLS'
            output(f'Probando {stage}...')
            server.starttls(context=ssl.create_default_context())
            code, _ = server.ehlo()
            if code != 250:
                output(f'ERROR: EHLO posterior a TLS rechazado (codigo {code}).')
                return 1
            output('OK: TLS y certificado del servidor.')

        if user:
            stage = 'autenticacion'
            output('Probando autenticacion...')
            server.login(user, password)
            output('OK: autenticacion.')
        else:
            output('Autenticacion omitida: relay sin credenciales configuradas.')

        if send_to:
            stage = 'envio'
            message = EmailMessage()
            message['From'] = sender
            message['To'] = send_to
            message['Subject'] = 'FashionStore - prueba SMTP'
            message['Date'] = formatdate(localtime=False)
            message['Message-ID'] = make_msgid()
            message.set_content('Este es un correo de prueba SMTP de FashionStore. '
                                'No contiene enlaces de acceso ni modifica tu cuenta.')
            refused = server.send_message(message)
            if refused:
                output('ERROR: el servidor rechazo el destinatario.')
                return 1
            output('OK: servidor acepto el correo. Revisa bandeja de entrada y spam; '
                   'la aceptacion SMTP no garantiza entrega final.')
        else:
            output('PRUEBA CORRECTA. No se envio ningun correo. '
                   'Para probar envio usa --send-to tu-correo@dominio.com.')
        return 0
    except smtplib.SMTPAuthenticationError as exc:
        output(f'ERROR de autenticacion SMTP (codigo {exc.smtp_code}). '
               'Revisa usuario, contrasena de aplicacion y politica de la cuenta institucional.')
        detail = exc.smtp_error
        if isinstance(detail, bytes):
            detail = detail.decode('utf-8', errors='replace')
        if 'application-specific password required' in str(detail).lower():
            output('DIAGNOSTICO: Gmail exige una contrasena de aplicacion. '
                   'Generala en la cuenta usada por SMTP_USERNAME y reemplaza SMTP_PASSWORD.')
    except smtplib.SMTPRecipientsRefused:
        output('ERROR: destinatario rechazado. Revisa la direccion y las restricciones de envio.')
    except smtplib.SMTPSenderRefused as exc:
        output(f'ERROR: remitente rechazado (codigo {exc.smtp_code}). Revisa SMTP_FROM_EMAIL.')
    except smtplib.SMTPNotSupportedError:
        output(f'ERROR en {stage}: el servidor no admite la operacion solicitada.')
    except smtplib.SMTPResponseException as exc:
        output(f'ERROR en {stage}: codigo SMTP {exc.smtp_code}. '
               'Revisa limites, remitente y politicas del proveedor.')
    except ssl.SSLCertVerificationError:
        output('ERROR: certificado TLS no valido. No desactives la verificacion del certificado.')
    except ssl.SSLError:
        output(f'ERROR TLS en {stage}. Revisa puerto y configuracion de cifrado.')
    except socket.gaierror:
        output('ERROR DNS: no se pudo resolver SMTP_HOST.')
    except (TimeoutError, socket.timeout):
        output(f'ERROR: tiempo agotado en {stage}. Revisa firewall y salida SMTP del entorno.')
    except ConnectionRefusedError:
        output('ERROR: conexion rechazada. Revisa host, puerto y restricciones de red.')
    except (OSError, smtplib.SMTPException) as exc:
        output(f'ERROR de conexion SMTP en {stage}: {type(exc).__name__} '
               f'(errno={getattr(exc, "errno", None)}, winerror={getattr(exc, "winerror", None)}). '
               'Revisa red, permisos del entorno y disponibilidad del proveedor.')
    except ValueError:
        output(f'ERROR de formato en {stage}. Revisa direcciones y configuracion.')
    finally:
        if server is not None:
            try:
                server.close()
            except OSError:
                pass
    return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send-to', help='Enviar UN correo de prueba a esta direccion.')
    parser.add_argument('--timeout', type=int, default=10, help='Espera por operacion, en segundos (1-60).')
    args = parser.parse_args()
    if not 1 <= args.timeout <= 60:
        parser.error('--timeout debe estar entre 1 y 60.')
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.chdir(root)
    try:
        from src.infrastructure.config.settings import settings
    except Exception:
        # ValidationError puede contener valores de configuracion sensibles.
        print('ERROR: no se pudo cargar Settings del backend. Revisa el formato de las '
              'variables de entorno y .env. Se omiten los valores por seguridad.')
        return 2
    print('Entorno: proceso local; variables del proceso prevalecen sobre .env del backend.')
    return diagnose(settings, send_to=args.send_to, timeout=args.timeout)


if __name__ == '__main__':
    raise SystemExit(main())
