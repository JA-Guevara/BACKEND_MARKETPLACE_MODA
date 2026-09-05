import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from src.infrastructure.config.settings import settings
from src.shared.exceptions.domain_exception import AuthenticationError


class JWTService:
    def create_access_token(self, user_id: str) -> tuple[str, int]:
        expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
        token = self._encode(user_id, "access", expires_delta)
        return token, int(expires_delta.total_seconds())

    def create_refresh_token(self, user_id: str) -> tuple[str, str, datetime]:
        expires_delta = timedelta(days=settings.refresh_token_expire_days)
        expires_at = datetime.now(timezone.utc) + expires_delta
        jti = secrets.token_hex(16)
        return self._encode(user_id, "refresh", expires_delta, jti=jti), jti, expires_at

    def decode(self, token: str, expected_type: str) -> dict[str, Any]:
        try:
            payload = jwt.decode(
                token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError("Token invalido o expirado.") from exc
        if payload.get("type") != expected_type or not payload.get("sub"):
            raise AuthenticationError("Tipo de token invalido.")
        return payload

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def create_opaque_token() -> tuple[str, str]:
        token = secrets.token_urlsafe(48)
        return token, JWTService.hash_token(token)

    def _encode(
        self, subject: str, token_type: str, expires_delta: timedelta, *, jti: str | None = None
    ) -> str:
        now = datetime.now(timezone.utc)
        payload: dict[str, Any] = {
            "sub": subject,
            "type": token_type,
            "iat": now,
            "exp": now + expires_delta,
        }
        if jti:
            payload["jti"] = jti
        return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
