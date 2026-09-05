import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from src.roles.infrastructure.persistence.models.permission import PermissionModel
from src.roles.infrastructure.persistence.models.role import RoleModel


class RoleRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_roles(self, include_inactive: bool = False) -> list[RoleModel]:
        stmt = select(RoleModel).options(selectinload(RoleModel.permissions)).order_by(RoleModel.name)
        if not include_inactive:
            stmt = stmt.where(RoleModel.is_active.is_(True))
        return list(self.db.scalars(stmt).unique())

    def get_role(self, role_id: uuid.UUID) -> RoleModel | None:
        return self.db.scalar(
            select(RoleModel).options(selectinload(RoleModel.permissions)).where(RoleModel.id == role_id)
        )

    def get_role_by_code(self, code: str) -> RoleModel | None:
        return self.db.scalar(
            select(RoleModel).options(selectinload(RoleModel.permissions)).where(
                func.lower(RoleModel.code) == code.strip().lower()
            )
        )

    def list_permissions(self, include_inactive: bool = False) -> list[PermissionModel]:
        stmt = select(PermissionModel).order_by(PermissionModel.module, PermissionModel.name)
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
