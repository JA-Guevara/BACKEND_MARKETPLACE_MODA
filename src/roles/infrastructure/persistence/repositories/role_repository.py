import uuid

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from src.auth.infrastructure.persistence.models.user import UserModel
from src.roles.infrastructure.persistence.models.permission import PermissionModel
from src.roles.infrastructure.persistence.models.role import RoleModel, user_roles


class RoleRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_roles(self, include_inactive: bool = False) -> list[RoleModel]:
        stmt = select(RoleModel).options(selectinload(RoleModel.permissions)).order_by(RoleModel.name)
        if not include_inactive:
            stmt = stmt.where(RoleModel.is_active.is_(True))
        return list(self.db.scalars(stmt).unique())

    def list_visible(self, tenant_id: uuid.UUID | None, include_inactive: bool = False) -> list[RoleModel]:
        if tenant_id is not None:
            stmt = (
                select(RoleModel)
                .options(selectinload(RoleModel.permissions))
                .where(
                    or_(
                        RoleModel.tenant_id == tenant_id,
                        and_(
                            RoleModel.tenant_id.is_(None),
                            RoleModel.code.notin_(["platform_admin", "client"]),
                        ),
                    )
                )
                .order_by(RoleModel.is_system.desc(), RoleModel.name)
            )
            if not include_inactive:
                stmt = stmt.where(RoleModel.is_active.is_(True))
            roles = list(self.db.scalars(stmt).unique())

            stmt_counts = (
                select(user_roles.c.role_id, func.count(user_roles.c.user_id))
                .select_from(user_roles.join(UserModel, UserModel.id == user_roles.c.user_id))
                .where(UserModel.tenant_id == tenant_id, UserModel.deleted_at.is_(None))
                .group_by(user_roles.c.role_id)
            )
            counts = dict(self.db.execute(stmt_counts).all())
            for role in roles:
                role.users_count = counts.get(role.id, 0)
            return roles

        stmt = select(RoleModel).options(selectinload(RoleModel.permissions)).order_by(RoleModel.name)
        if not include_inactive:
            stmt = stmt.where(RoleModel.is_active.is_(True))
        roles = list(self.db.scalars(stmt).unique())
        stmt_counts = (
            select(user_roles.c.role_id, func.count(user_roles.c.user_id))
            .select_from(user_roles.join(UserModel, UserModel.id == user_roles.c.user_id))
            .where(UserModel.deleted_at.is_(None))
            .group_by(user_roles.c.role_id)
        )
        counts = dict(self.db.execute(stmt_counts).all())
        for role in roles:
            role.users_count = counts.get(role.id, 0)
        return roles

    def get_role(self, role_id: uuid.UUID) -> RoleModel | None:
        return self.db.scalar(
            select(RoleModel).options(selectinload(RoleModel.permissions)).where(RoleModel.id == role_id)
        )

    def get_role_by_code(self, code: str, tenant_id: uuid.UUID | None = None) -> RoleModel | None:
        stmt = (
            select(RoleModel)
            .options(selectinload(RoleModel.permissions))
            .where(
                func.lower(RoleModel.code) == code.strip().lower()
            )
        )
        if tenant_id is not None:
            stmt = stmt.where(RoleModel.tenant_id == tenant_id)
        else:
            stmt = stmt.where(RoleModel.tenant_id.is_(None))
        return self.db.scalar(stmt)

    def list_permissions(self, include_inactive: bool = False) -> list[PermissionModel]:
        stmt = select(PermissionModel).order_by(PermissionModel.module, PermissionModel.name)
        if not include_inactive:
            stmt = stmt.where(PermissionModel.is_active.is_(True))
        return list(self.db.scalars(stmt))

    def permissions_by_scope(self, scope: str, include_inactive: bool = False) -> list[PermissionModel]:
        stmt = (
            select(PermissionModel)
            .where(PermissionModel.scope == scope)
            .order_by(PermissionModel.module, PermissionModel.name)
        )
        if not include_inactive:
            stmt = stmt.where(PermissionModel.is_active.is_(True))
        return list(self.db.scalars(stmt))

    def get_permission(self, permission_id: uuid.UUID) -> PermissionModel | None:
        return self.db.get(PermissionModel, permission_id)

    def get_permission_by_code(self, code: str) -> PermissionModel | None:
        return self.db.scalar(
            select(PermissionModel).where(func.lower(PermissionModel.code) == code.strip().lower())
        )

    def add(self, entity: RoleModel | PermissionModel) -> RoleModel | PermissionModel:
        self.db.add(entity)
        self.db.flush()
        return entity
