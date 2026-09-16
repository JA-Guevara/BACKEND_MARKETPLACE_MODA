"""Contrato del borrador asistido de prendas (Etapa 4): la IA propone campos
pero NO crea nada; sin IA configurada el endpoint responde disponible=False sin
tocar datos; la categoria solo se acepta por coincidencia EXACTA normalizada.
Estas pruebas cubren la logica pura y el camino de "IA no disponible" (lo que se
puede probar sin llamar a la API de OpenAI)."""
from src.usuarios_catalogo.web.routers import catalog_router
from src.usuarios_catalogo.web.routers.catalog_router import _draft_unavailable, _normalize_name
from src.usuarios_catalogo.web.schemas.catalog import ProductDraftRequest


def test_normalize_name_quita_acentos_y_minusculas():
    assert _normalize_name("Cámperas Deportivas") == "camperas deportivas"
    assert _normalize_name("NIÑOS") == "ninos"


def test_draft_unavailable_no_fabrica_datos():
    result = _draft_unavailable("IA no configurada.")
    assert result.data["available"] is False
    assert result.data["category_id"] is None
    assert result.data["category_name"] == ""
    assert result.data["matched"] is False


def test_sin_ia_configurada_el_endpoint_no_toca_la_api(monkeypatch):
    from src.infrastructure.config import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "ai_api_key", "")
    calls = []
    original_post = catalog_router.httpx.post
    catalog_router.httpx.post = lambda *a, **k: calls.append(a)  # noqa: E731
    try:
        result = catalog_router.draft_product(
            ProductDraftRequest(message="registrame una campera de cuero a 450 bolivianos"),
            actor=object(),
            db=None,
        )
    finally:
        catalog_router.httpx.post = original_post
    assert result.data["available"] is False
    assert calls == []