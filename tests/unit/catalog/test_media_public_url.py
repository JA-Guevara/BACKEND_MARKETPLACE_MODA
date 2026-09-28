from src.infrastructure.config.settings import Settings


def test_railway_media_url_uses_public_api_domain(monkeypatch):
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "api.example.up.railway.app")
    config = Settings(_env_file=None)
    assert config.media_public_base_url == (
        "https://api.example.up.railway.app/api/v1/media/files"
    )


def test_explicit_media_url_keeps_custom_storage(monkeypatch):
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "api.example.up.railway.app")
    config = Settings(
        _env_file=None,
        media_public_base_url="https://cdn.example.org/garments",
    )
    assert config.media_public_base_url == "https://cdn.example.org/garments"
