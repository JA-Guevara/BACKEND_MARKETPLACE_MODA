from datetime import datetime, timezone
import hashlib
import os
import secrets
from typing import Any
import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.integraciones.infrastructure.models import ApiKeyModel
from src.shared.exceptions.domain_exception import AuthenticationError, AuthorizationError, NotFoundError, ValidationError


class ApiKeyInvalidError(AuthenticationError):
    status_code = 401
    code = "api_key_invalid"

    def __init__(self, message: str = "Clave de API inexistente o revocada.") -> None:
        super().__init__(message)


class ApiKeyScopeError(AuthorizationError):
    status_code = 403
    code = "api_key_scope"

    def __init__(self, message: str = "Scope insuficiente para realizar esta operación.") -> None:
        super().__init__(message)


ALLOWED_INTEGRATION_SCOPES = {
    "sales.read",
    "orders.read",
    "stock.read",
    "catalog.read",
    "customers.read",
    "reservations.read",
}


def hash_api_key(raw_key: str) -> str:
    pepper = os.getenv("API_KEY_PEPPER", "fashionstore-api-key-pepper-2026")
    return hashlib.sha256(f"{pepper}:{raw_key}".encode("utf-8")).hexdigest()


class ApiKeysService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def crear(
        self,
        tenant_id: uuid.UUID,
        name: str,
        scopes: list[str],
        created_by: uuid.UUID | None = None,
    ) -> tuple[ApiKeyModel, str]:
        # Formato: fs_live_ + 32 bytes aleatorios en formato hex
        token_body = secrets.token_hex(24)
        raw_key = f"fs_live_{token_body}"
        prefix = raw_key[:12]
        key_hash = hash_api_key(raw_key)

        # Filtrar o validar scopes permitidos
        valid_scopes = [s.replace(":", ".") for s in scopes if s.replace(":", ".") in ALLOWED_INTEGRATION_SCOPES or s in ("all", "*")]
        if not valid_scopes or len(valid_scopes) != len(scopes):
            raise ValidationError("Indica únicamente scopes de integración permitidos.")

        key_model = ApiKeyModel(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            name=name.strip() or "Clave de API",
            prefix=prefix,
            key_hash=key_hash,
            scopes=valid_scopes,
            created_by=created_by,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(key_model)
        self.db.commit()
        self.db.refresh(key_model)
        return key_model, raw_key

    def listar(self, tenant_id: uuid.UUID) -> list[ApiKeyModel]:
        return list(
            self.db.scalars(
                select(ApiKeyModel)
                .where(ApiKeyModel.tenant_id == tenant_id)
                .order_by(ApiKeyModel.created_at.desc())
            ).all()
        )

    def revocar(self, tenant_id: uuid.UUID, key_id: uuid.UUID) -> bool:
        stmt = (
            update(ApiKeyModel)
            .where(
                ApiKeyModel.id == key_id,
                ApiKeyModel.tenant_id == tenant_id,
                ApiKeyModel.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(timezone.utc))
        )
        res = self.db.execute(stmt)
        self.db.commit()
        return (res.rowcount or 0) > 0

    def autenticar(self, auth_header_or_key: str) -> tuple[ApiKeyModel, uuid.UUID, list[str]]:
        raw_key = auth_header_or_key.strip()
        if raw_key.lower().startswith("bearer "):
            raw_key = raw_key[7:].strip()

        if not raw_key.startswith("fs_live_"):
            raise ApiKeyInvalidError()

        kh = hash_api_key(raw_key)
        key_model = self.db.scalar(
            select(ApiKeyModel).where(
                ApiKeyModel.key_hash == kh,
                ApiKeyModel.revoked_at.is_(None),
            )
        )
        if not key_model:
            raise ApiKeyInvalidError()

        # Actualizar último uso
        key_model.last_used_at = datetime.now(timezone.utc)
        self.db.commit()
        return key_model, key_model.tenant_id, key_model.scopes

    @staticmethod
    def verificar_scope(key_scopes: list[str], required_scope: str) -> None:
        if (
            required_scope.replace(":", ".") not in {s.replace(":", ".") for s in key_scopes}
            and "all" not in key_scopes
            and "*" not in key_scopes
        ):
            raise ApiKeyScopeError(f"Se requiere el scope '{required_scope}'.")


def require_api_key(required_scope: str):
    from dataclasses import dataclass
    from fastapi import Depends, Header
    from src.infrastructure.database.session import get_db, set_rls_context
    from src.plataforma_saas.infrastructure.models.tenant import TenantModel

    @dataclass(frozen=True)
    class ApiTenantContext:
        tenant_id: uuid.UUID
        key_id: uuid.UUID

    def dependency(authorization: str | None = Header(default=None),
                   x_api_key: str | None = Header(default=None, alias="X-API-Key"),
                   db: Session = Depends(get_db)):
        model, tenant_id, scopes = ApiKeysService(db).autenticar(x_api_key or authorization or "")
        ApiKeysService.verificar_scope(scopes, required_scope)
        tenant = db.get(TenantModel, tenant_id)
        if tenant is None or tenant.status != "ACTIVA":
            raise ApiKeyInvalidError()
        set_rls_context(db, tenant_id=tenant_id)
        return ApiTenantContext(tenant_id, model.id)
    return dependency
