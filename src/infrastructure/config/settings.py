from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    app_name: str = "FashionStore API"
    app_env: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql://postgres:postgres@localhost:5432/fashionstore"
    jwt_secret_key: str = Field(default="development-only-secret-key-change-me-now", min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    verification_token_expire_hours: int = 24
    password_reset_token_expire_minutes: int = 30
    max_login_attempts: int = 5
    account_lock_minutes: int = 15
    frontend_url: str = "http://localhost:4200"
    cors_origins: list[str] = ["http://localhost:4200"]
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str = "no-reply@fashionstore.local"
    smtp_use_tls: bool = True
    # Casilla que recibe los avisos de reserva cuando la sucursal todavia
    # no tiene correo propio cargado (RF11).
    operations_email: str | None = None
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    commerce_currency: str = "bob"
    ai_api_key: str = ""
    ai_model: str = "gpt-4.1-mini"
    # Modelo separado para convertir audios breves del asistente a texto.
    # Se puede reemplazar desde `AI_TRANSCRIPTION_MODEL` sin tocar el código.
    ai_transcription_model: str = "gpt-4o-mini-transcribe"
    ai_timeout: int = 30
    ai_max_tokens: int = 600
    report_export_max_rows: int = 10000
    low_stock_threshold: int = 5
    media_storage_dir: str = "uploads/images"
    media_public_base_url: str = "http://localhost:8000/api/v1/media/files"
    media_max_upload_mb: int = 5
    # Foto IA realista del probador (Fase 3). `tryon_provider` puede ser
    # "none" (no configurado), "mock" (composición local, sin red) o "fashn".
    tryon_provider: str = "none"
    tryon_api_key: str = ""
    tryon_max_active_jobs: int = 3
    tryon_result_expiration_hours: int = 48

    @field_validator("api_v1_prefix")
    @classmethod
    def validate_prefix(cls, value: str) -> str:
        return "/" + value.strip("/")

    @model_validator(mode="after")
    def validate_production_secret(self) -> "Settings":
        if self.app_env.lower() == "production" and self.jwt_secret_key.startswith("development-only"):
            raise ValueError("JWT_SECRET_KEY must be replaced in production.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
