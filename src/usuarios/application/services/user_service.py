from __future__ import annotations

import uuid
from datetime import datetime, timezone
from math import ceil

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.auth.domain.exceptions import EmailAlreadyExistsError
from src.auth.domain.password_policy import PasswordPolicy
from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.infrastructure.persistence.repositories.auth_token_repository import AuthTokenRepository
from src.auth.infrastructure.persistence.repositories.user_repository import UserRepository
from src.auth.infrastructure.security.password_hasher import PasswordHasher
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.roles.infrastructure.persistence.models.role import RoleModel
from src.roles.infrastructure.persistence.repositories.role_repository import RoleRepository
from src.shared.exceptions.domain_exception import ConflictError, NotFoundError
from src.shared.responses.pagination import Page
from src.usuarios.infrastructure.http.schemas import AddressCreate, AddressUpdate, UserCreate, UserResponse, UserUpdate
from src.usuarios.infrastructure.persistence.models.usuario import AddressModel


class UserService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserRepository(db)
        self.roles = RoleRepository(db)
        self.tokens = AuthTokenRepository(db)
        self.audit = RecordAuditEvent(db)
        self.passwords = PasswordHasher()

    def list(self, **filters) -> Page[UserResponse]:
        items, total = self.users.list(**filters)
        page = filters["page"]
        page_size = filters["page_size"]
        return Page(items=items, total=total, page=page, page_size=page_size, pages=ceil(total / page_size) if total else 0)

    def get(self, user_id: uuid.UUID, *, include_deleted: bool = False) -> UserModel:
        user = self.users.get_by_id(user_id, include_deleted=include_deleted)
        if not user:
            raise NotFoundError("Usuario no encontrado.")
        return user

    def create(self, data: UserCreate, actor: UserModel) -> UserModel:
        PasswordPolicy.validate(data.password, email=str(data.email))
        if self.users.get_by_email(str(data.email), include_deleted=True):
            raise EmailAlreadyExistsError()
        if data.document_number and self.users.get_by_document(data.document_number):
            raise ConflictError("El numero de documento ya esta registrado.")
        roles = self._resolve_roles(data.role_ids)
        user = UserModel(
            email=str(data.email).lower(),
            password_hash=self.passwords.hash(data.password),
            first_name=data.first_name.strip(),
            last_name=data.last_name.strip(),
            phone=data.phone,
            document_number=data.document_number,
            is_verified=data.is_verified,
            roles=roles,
        )
        self.users.add(user)
        self._audit(actor, "users.create", user, "Usuario creado.")
        self.db.commit()
        return self.get(user.id)

    def update(self, user_id: uuid.UUID, data: UserUpdate, actor: UserModel) -> UserModel:
        user = self.get(user_id)
        changes = data.model_dump(exclude_unset=True)
        if "email" in changes and changes["email"] != user.email:
            existing = self.users.get_by_email(changes["email"], include_deleted=True)
            if existing and existing.id != user.id:
                raise EmailAlreadyExistsError()
            user.is_verified = False
        if "document_number" in changes and changes["document_number"]:
            existing = self.users.get_by_document(changes["document_number"])
            if existing and existing.id != user.id:
                raise ConflictError("El numero de documento ya esta registrado.")
        for field, value in changes.items():
            setattr(user, field, value.strip() if isinstance(value, str) else value)
        self._audit(actor, "users.update", user, "Usuario actualizado.", {"fields": list(changes)})
        self.db.commit()
        return self.get(user.id)

    def set_roles(self, user_id: uuid.UUID, role_ids: list[uuid.UUID], actor: UserModel) -> UserModel:
        user = self.get(user_id)
        if user.id == actor.id and not role_ids:
            raise ConflictError("No puede retirarse todos sus propios roles.")
        user.roles = self._resolve_roles(role_ids)
        self._audit(actor, "users.roles_updated", user, "Roles del usuario actualizados.")
        self.db.commit()
        return self.get(user.id)

    def deactivate(self, user_id: uuid.UUID, actor: UserModel) -> UserModel:
        user = self.get(user_id)
        if user.id == actor.id:
            raise ConflictError("No puede desactivar su propia cuenta administrativa.")
        user.is_active = False
        self.tokens.revoke_all_for_user(user.id)
        self._audit(actor, "users.deactivate", user, "Usuario desactivado.")
        self.db.commit()
        return self.get(user.id)

    def activate(self, user_id: uuid.UUID, actor: UserModel) -> UserModel:
        user = self.get(user_id)
        user.is_active = True
        user.locked_until = None
        user.failed_login_attempts = 0
        self._audit(actor, "users.activate", user, "Usuario activado.")
        self.db.commit()
        return self.get(user.id)

    def unlock(self, user_id: uuid.UUID, actor: UserModel) -> UserModel:
        user = self.get(user_id)
        user.locked_until = None
        user.failed_login_attempts = 0
        self._audit(actor, "users.unlock", user, "Cuenta desbloqueada.")
        self.db.commit()
        return self.get(user.id)

    def delete(self, user_id: uuid.UUID, actor: UserModel) -> None:
        user = self.get(user_id)
        if user.id == actor.id:
            raise ConflictError("No puede eliminar su propia cuenta administrativa.")
        user.deleted_at = datetime.now(timezone.utc)
        user.is_active = False
        self.tokens.revoke_all_for_user(user.id)
        self._audit(actor, "users.delete", user, "Usuario eliminado logicamente.")
        self.db.commit()

    def restore(self, user_id: uuid.UUID, actor: UserModel) -> UserModel:
        user = self.get(user_id, include_deleted=True)
        user.deleted_at = None
        user.is_active = True
        self._audit(actor, "users.restore", user, "Usuario restaurado.")
        self.db.commit()
        return self.get(user.id)

    def list_addresses(self, user_id: uuid.UUID) -> list[AddressModel]:
        self.get(user_id)
        return list(self.db.scalars(select(AddressModel).where(AddressModel.user_id == user_id).order_by(AddressModel.created_at)))

    def add_address(self, user_id: uuid.UUID, data: AddressCreate, actor: UserModel) -> AddressModel:
        self.get(user_id)
        if data.is_default:
            self._clear_default_addresses(user_id)
        address = AddressModel(user_id=user_id, **data.model_dump())
        self.db.add(address)
        self.db.flush()
        self._audit(actor, "users.address_created", address, "Direccion creada.")
        self.db.commit()
        self.db.refresh(address)
        return address

    def update_address(self, user_id: uuid.UUID, address_id: uuid.UUID, data: AddressUpdate, actor: UserModel) -> AddressModel:
        address = self._get_address(user_id, address_id)
        changes = data.model_dump(exclude_unset=True)
        if changes.get("is_default"):
            self._clear_default_addresses(user_id)
        for field, value in changes.items():
            setattr(address, field, value)
        self._audit(actor, "users.address_updated", address, "Direccion actualizada.")
        self.db.commit()
        self.db.refresh(address)
        return address

    def delete_address(self, user_id: uuid.UUID, address_id: uuid.UUID, actor: UserModel) -> None:
        address = self._get_address(user_id, address_id)
        self._audit(actor, "users.address_deleted", address, "Direccion eliminada.")
        self.db.delete(address)
        self.db.commit()

    def _resolve_roles(self, role_ids: list[uuid.UUID]) -> list[RoleModel]:
        roles = [self.roles.get_role(role_id) for role_id in set(role_ids)]
        if any(role is None or not role.is_active for role in roles):
            raise NotFoundError("Uno o mas roles no existen o estan inactivos.")
        return list(roles)

    def _get_address(self, user_id: uuid.UUID, address_id: uuid.UUID) -> AddressModel:
        address = self.db.scalar(select(AddressModel).where(AddressModel.id == address_id, AddressModel.user_id == user_id))
        if not address:
            raise NotFoundError("Direccion no encontrada.")
        return address

    def _clear_default_addresses(self, user_id: uuid.UUID) -> None:
        self.db.execute(update(AddressModel).where(AddressModel.user_id == user_id).values(is_default=False))

    def _audit(self, actor: UserModel, action: str, entity, description: str, metadata: dict | None = None) -> None:
        self.audit.execute(
            actor_user_id=actor.id,
            action=action,
            entity_type="address" if isinstance(entity, AddressModel) else "user",
            entity_id=str(entity.id),
            description=description,
            metadata=metadata,
        )
