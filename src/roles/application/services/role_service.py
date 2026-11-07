import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.roles.infrastructure.http.schemas import PermissionCreate, PermissionUpdate, RoleCreate, RoleUpdate
from src.roles.infrastructure.persistence.models.permission import PermissionModel
from src.roles.infrastructure.persistence.models.role import RoleModel, user_roles
from src.roles.infrastructure.persistence.repositories.role_repository import RoleRepository
from src.shared.exceptions.domain_exception import (
    ConflictError,
    NotFoundError,
    PermissionOutOfScopeError,
    SystemRoleLockedError,
)


class RoleService:
    def __init__(self, db: Session, tenant_id: uuid.UUID | None = None) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.repository = RoleRepository(db)
        self.audit = RecordAuditEvent(db)

    def list_roles(self, include_inactive: bool = False) -> list[RoleModel]:
        return self.repository.list_visible(self.tenant_id, include_inactive=include_inactive)

    def get_role(self, role_id: uuid.UUID) -> RoleModel:
        role = self._get_role(role_id)
        if self.tenant_id is not None:
            count_stmt = (
                select(func.count(user_roles.c.user_id))
                .select_from(user_roles.join(UserModel, UserModel.id == user_roles.c.user_id))
                .where(
                    user_roles.c.role_id == role.id,
                    UserModel.tenant_id == self.tenant_id,
                    UserModel.deleted_at.is_(None),
                )
            )
        else:
            count_stmt = (
                select(func.count(user_roles.c.user_id))
                .select_from(user_roles.join(UserModel, UserModel.id == user_roles.c.user_id))
                .where(
                    user_roles.c.role_id == role.id,
                    UserModel.deleted_at.is_(None),
                )
            )
        role.users_count = self.db.scalar(count_stmt) or 0
        return role

    def create_role(self, data: RoleCreate, actor: UserModel) -> RoleModel:
        if self.repository.get_role_by_code(data.code, tenant_id=self.tenant_id):
            raise ConflictError("Ya existe un rol con ese codigo.")
        permissions = self._resolve_permissions(data.permission_ids)
        if self.tenant_id is not None:
            for perm in permissions:
                if perm.scope != "tenant":
                    raise PermissionOutOfScopeError()
        role = RoleModel(
            tenant_id=self.tenant_id,
            code=data.code,
            name=data.name.strip(),
            description=data.description,
            permissions=permissions,
        )
        self.repository.add(role)
        self._audit(actor, "roles.create", "role", role.id, "Rol creado.")
        self.db.commit()
        role.users_count = 0
        return self.repository.get_role(role.id) or role

    def update_role(self, role_id: uuid.UUID, data: RoleUpdate, actor: UserModel) -> RoleModel:
        role = self._get_role(role_id)
        self._assert_editable(role)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(role, field, value.strip() if isinstance(value, str) else value)
        self._audit(actor, "roles.update", "role", role.id, "Rol actualizado.")
        self.db.commit()
        return self.get_role(role.id)

    def set_permissions(self, role_id: uuid.UUID, permission_ids: list[uuid.UUID], actor: UserModel) -> RoleModel:
        role = self._get_role(role_id)
        self._assert_editable(role)
        permissions = self._resolve_permissions(permission_ids)
        if self.tenant_id is not None:
            for perm in permissions:
                if perm.scope != "tenant":
                    raise PermissionOutOfScopeError()
        role.permissions = permissions
        self._audit(actor, "roles.permissions_updated", "role", role.id, "Permisos del rol actualizados.")
        self.db.commit()
        return self.get_role(role.id)

    def deactivate_role(self, role_id: uuid.UUID, actor: UserModel) -> RoleModel:
        role = self._get_role(role_id)
        self._assert_editable(role)
        role.is_active = False
        self._audit(actor, "roles.deactivate", "role", role.id, "Rol desactivado.")
        self.db.commit()
        return role

    def activate_role(self, role_id: uuid.UUID, actor: UserModel) -> RoleModel:
        role = self._get_role(role_id)
        self._assert_editable(role)
        role.is_active = True
        self._audit(actor, "roles.activate", "role", role.id, "Rol activado.")
        self.db.commit()
        return role

    def delete_role(self, role_id: uuid.UUID, actor: UserModel) -> None:
        role = self._get_role(role_id)
        self._assert_editable(role)
        if role.users:
            raise ConflictError("No se puede eliminar un rol asignado a usuarios.")
        self._audit(actor, "roles.delete", "role", role.id, "Rol eliminado.")
        self.db.delete(role)
        self.db.commit()

    def create_permission(self, data: PermissionCreate, actor: UserModel) -> PermissionModel:
        if self.repository.get_permission_by_code(data.code):
            raise ConflictError("Ya existe un permiso con ese codigo.")
        permission = PermissionModel(**data.model_dump())
        self.repository.add(permission)
        self._audit(actor, "permissions.create", "permission", permission.id, "Permiso creado.")
        self.db.commit()
        return permission

    def update_permission(self, permission_id: uuid.UUID, data: PermissionUpdate, actor: UserModel) -> PermissionModel:
        permission = self._get_permission(permission_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(permission, field, value.strip() if isinstance(value, str) else value)
        self._audit(actor, "permissions.update", "permission", permission.id, "Permiso actualizado.")
        self.db.commit()
        return permission

    def set_permission_active(self, permission_id: uuid.UUID, active: bool, actor: UserModel) -> PermissionModel:
        permission = self._get_permission(permission_id)
        permission.is_active = active
        action = "permissions.activate" if active else "permissions.deactivate"
        self._audit(actor, action, "permission", permission.id, "Estado del permiso actualizado.")
        self.db.commit()
        return permission

    def delete_permission(self, permission_id: uuid.UUID, actor: UserModel) -> None:
        permission = self._get_permission(permission_id)
        if permission.roles:
            raise ConflictError("No se puede eliminar un permiso asignado a roles.")
        self._audit(actor, "permissions.delete", "permission", permission.id, "Permiso eliminado.")
        self.db.delete(permission)
        self.db.commit()

    def _assert_editable(self, role: RoleModel) -> None:
        if role.is_template or role.is_system:
            raise SystemRoleLockedError()
        if self.tenant_id is not None and role.tenant_id != self.tenant_id:
            raise NotFoundError("Rol no encontrado.")

    def _resolve_permissions(self, permission_ids: list[uuid.UUID]) -> list[PermissionModel]:
        permissions = [self.repository.get_permission(permission_id) for permission_id in set(permission_ids)]
        if any(permission is None or not permission.is_active for permission in permissions):
            raise NotFoundError("Uno o mas permisos no existen o estan inactivos.")
        return list(permissions)

    def _get_role(self, role_id: uuid.UUID) -> RoleModel:
        role = self.repository.get_role(role_id)
        if not role:
            raise NotFoundError("Rol no encontrado.")
        if self.tenant_id is not None:
            if role.tenant_id is not None and role.tenant_id != self.tenant_id:
                raise NotFoundError("Rol no encontrado.")
            if role.tenant_id is None and (
                role.audience != "TENANT"
                or role.code in (
                    "platform_admin",
                    "client",
                    "superadmin",
                    "platform_support",
                    "platform_billing",
                    "platform_auditor",
                )
            ):
                raise NotFoundError("Rol no encontrado.")
        return role

    def _get_permission(self, permission_id: uuid.UUID) -> PermissionModel:
        permission = self.repository.get_permission(permission_id)
        if not permission:
            raise NotFoundError("Permiso no encontrado.")
        return permission

    def _audit(self, actor: UserModel, action: str, entity_type: str, entity_id: uuid.UUID, description: str) -> None:
        self.audit.execute(
            actor_user_id=actor.id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            description=description,
        )
