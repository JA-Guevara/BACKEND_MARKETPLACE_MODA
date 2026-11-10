"""Pruebas unitarias del servicio centralizado de IA (AIService)."""
import httpx
import pytest

from src.infrastructure.config.settings import settings
from src.infrastructure.services.ai_client import AIService, FALLBACK_MODELS


def test_ai_service_is_configured(monkeypatch):
    monkeypatch.setattr(settings, "ai_api_key", "")
    assert AIService.is_configured() is False
    monkeypatch.setattr(settings, "ai_api_key", "secret-test-key")
    assert AIService.is_configured() is True


def test_ai_service_candidate_models(monkeypatch):
    monkeypatch.setattr(settings, "ai_model", "custom-model")
    candidates = AIService.get_candidate_models()
    assert candidates[0] == "custom-model"
    for fb in FALLBACK_MODELS:
        assert fb in candidates
    assert len(candidates) == len(set(candidates))


def test_ai_service_raises_when_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "ai_api_key", "")
    with pytest.raises(ValueError, match="AI_API_KEY no configurada"):
        AIService.generate("Hola")


def test_ai_service_generate_native_gemini_success(monkeypatch):
    monkeypatch.setattr(settings, "ai_api_key", "fake-key")
    monkeypatch.setattr(settings, "ai_base_url", "https://generativelanguage.googleapis.com/v1beta/openai")
    monkeypatch.setattr(settings, "ai_model", "gemini-3.5-flash-lite")

    def mock_post(url, json=None, timeout=None):
        assert "gemini-3.5-flash-lite:generateContent" in url
        req = httpx.Request("POST", url)
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "Respuesta simulada"}]}}]},
            request=req,
        )

    monkeypatch.setattr(httpx, "post", mock_post)
    output = AIService.generate("Prueba", system_instruction="Instruccion")
    assert output == "Respuesta simulada"


def test_ai_service_fallback_on_503(monkeypatch):
    monkeypatch.setattr(settings, "ai_api_key", "fake-key")
    monkeypatch.setattr(settings, "ai_base_url", "https://generativelanguage.googleapis.com/v1beta/openai")
    monkeypatch.setattr(settings, "ai_model", "gemini-3.8-flash")

    attempted_models = []

    def mock_post(url, json=None, timeout=None):
        for m in ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-flash-lite-latest"]:
            if f"{m}:generateContent" in url:
                attempted_models.append(m)
                break
        req = httpx.Request("POST", url)
        if "gemini-3.8-flash" in url:
            # Simula modelo saturado (503 Service Unavailable)
            return httpx.Response(503, json={"error": {"code": 503, "message": "Overloaded"}}, request=req)
        # Siguiente modelo responde exitosamente
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "Recuperado tras fallback"}]}}]},
            request=req,
        )

    monkeypatch.setattr(httpx, "post", mock_post)
    output = AIService.generate("Prueba con fallo inicial")
    assert output == "Recuperado tras fallback"
    assert "gemini-3.8-flash" in attempted_models
    assert "gemini-3.5-flash-lite" in attempted_models


def test_assistant_role_extraction_from_user():
    """Valida que la logica de extraccion de roles no falla con UserModel."""
    from src.auth.infrastructure.persistence.models.user import UserModel
    from src.roles.infrastructure.persistence.models.role import RoleModel

    user = UserModel(first_name="Admin", last_name="User")
    user.roles = [RoleModel(code="admin", name="Administrador")]
    roles = getattr(user, "roles", []) or []
    role_names = [r.name for r in roles if hasattr(r, "name")]
    is_staff = any(name.lower() not in ["cliente"] for name in role_names) if role_names else False
    role_name = role_names[0] if role_names else ("Personal de tienda" if is_staff else "Cliente")
    assert is_staff is True
    assert role_name == "Administrador"

    client_user = UserModel(first_name="Juan", last_name="Perez")
    client_user.roles = [RoleModel(code="client", name="Cliente")]
    roles = getattr(client_user, "roles", []) or []
    role_names = [r.name for r in roles if hasattr(r, "name")]
    is_staff = any(name.lower() not in ["cliente"] for name in role_names) if role_names else False
    role_name = role_names[0] if role_names else ("Personal de tienda" if is_staff else "Cliente")
    assert is_staff is False
    assert role_name == "Cliente"

    empty_user = UserModel(first_name="Sin", last_name="Roles")
    roles = getattr(empty_user, "roles", []) or []
    role_names = [r.name for r in roles if hasattr(r, "name")]
    is_staff = any(name.lower() not in ["cliente"] for name in role_names) if role_names else False
    role_name = role_names[0] if role_names else ("Personal de tienda" if is_staff else "Cliente")
    assert is_staff is False
    assert role_name == "Cliente"
