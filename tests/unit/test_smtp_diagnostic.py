from types import SimpleNamespace
from unittest.mock import MagicMock
import smtplib

from scripts.test_smtp import diagnose


def config(**changes):
    values = dict(smtp_host='smtp.gmail.com', smtp_port=587, smtp_use_tls=True,
                  smtp_username='sender@example.com', smtp_password='test-secret',
                  smtp_from_email='sender@example.com')
    values.update(changes)
    return SimpleNamespace(**values)


def setup_server(monkeypatch):
    server = MagicMock()
    server.ehlo.return_value = (250, b'OK')
    factory = MagicMock(return_value=server)
    monkeypatch.setattr('scripts.test_smtp.smtplib.SMTP', factory)
    return factory, server


def test_default_authenticates_without_sending(monkeypatch):
    _, server = setup_server(monkeypatch)
    lines = []
    assert diagnose(config(), output=lines.append) == 0
    server.starttls.assert_called_once()
    server.login.assert_called_once_with('sender@example.com', 'test-secret')
    server.send_message.assert_not_called()
    server.close.assert_called_once()
    assert 'test-secret' not in '\n'.join(lines)


def test_missing_password_stops_before_network(monkeypatch):
    factory, _ = setup_server(monkeypatch)
    assert diagnose(config(smtp_password=''), output=lambda _: None) == 2
    factory.assert_not_called()


def test_auth_error_is_actionable_without_leaking_response(monkeypatch):
    _, server = setup_server(monkeypatch)
    server.login.side_effect = smtplib.SMTPAuthenticationError(535, b'test-secret')
    lines = []
    assert diagnose(config(), output=lines.append) == 1
    assert '535' in '\n'.join(lines)
    assert 'test-secret' not in '\n'.join(lines)
    server.send_message.assert_not_called()
    server.close.assert_called_once()


def test_send_requires_explicit_recipient(monkeypatch):
    _, server = setup_server(monkeypatch)
    server.send_message.return_value = {}
    assert diagnose(config(), send_to='receiver@example.com', output=lambda _: None) == 0
    message = server.send_message.call_args.args[0]
    assert message['To'] == 'receiver@example.com'
    assert 'test-secret' not in message.as_string()


def test_google_app_password_requirement_is_identified(monkeypatch):
    _, server = setup_server(monkeypatch)
    server.login.side_effect = smtplib.SMTPAuthenticationError(
        534, b'5.7.9 Application-specific password required. test-secret')
    lines = []
    assert diagnose(config(), output=lines.append) == 1
    assert 'Gmail exige una contrasena de aplicacion' in '\n'.join(lines)
    assert 'test-secret' not in '\n'.join(lines)


def test_recipient_rejection_is_not_success(monkeypatch):
    _, server = setup_server(monkeypatch)
    server.send_message.side_effect = smtplib.SMTPRecipientsRefused({'receiver@example.com': (550, b'no')})
    assert diagnose(config(), send_to='receiver@example.com', output=lambda _: None) == 1


def test_implicit_tls_port_is_not_supported_by_current_sender(monkeypatch):
    factory, _ = setup_server(monkeypatch)
    assert diagnose(config(smtp_port=465), output=lambda _: None) == 2
    factory.assert_not_called()


def test_tls_failure_does_not_authenticate(monkeypatch):
    _, server = setup_server(monkeypatch)
    server.starttls.side_effect = smtplib.SMTPNotSupportedError('unavailable')
    assert diagnose(config(), output=lambda _: None) == 1
    server.login.assert_not_called()
    server.close.assert_called_once()
