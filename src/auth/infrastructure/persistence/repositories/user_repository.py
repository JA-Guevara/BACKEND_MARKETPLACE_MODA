import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from src.auth.infrastructure.persistence.models.user import UserModel


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, user_id: uuid.UUID, *, include_deleted: bool = False) -> UserModel | None:
        stmt = select(UserModel).options(selectinload(UserModel.roles)).where(UserModel.id == user_id)
        if not include_deleted:
            stmt = stmt.where(UserModel.deleted_at.is_(None))
        return self.db.scalar(stmt)

    def get_by_email(self, email: str, *, include_deleted: bool = False) -> UserModel | None:
        stmt = select(UserModel).options(selectinload(UserModel.roles)).where(
            func.lower(UserModel.email) == email.strip().lower()
        )
        if not include_deleted:
            stmt = stmt.where(UserModel.deleted_at.is_(None))
        return self.db.scalar(stmt)

    def get_by_document(self, document_number: str) -> UserModel | None:
        return self.db.scalar(
            select(UserModel).where(UserModel.document_number == document_number.strip())
        )

    def list(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None = None,
        is_active: bool | None = None,
        role_code: str | None = None,
        include_deleted: bool = False,
    ) -> tuple[list[UserModel], int]:
        stmt = select(UserModel).options(selectinload(UserModel.roles))
        count_stmt = select(func.count(UserModel.id))
        conditions = []
        if not include_deleted:
            conditions.append(UserModel.deleted_at.is_(None))
        if search:
            term = f"%{search.strip()}%"
            conditions.append(
                or_(UserModel.email.ilike(term), UserModel.first_name.ilike(term), UserModel.last_name.ilike(term))
            )
        if is_active is not None:
            conditions.append(UserModel.is_active == is_active)
        if role_code:
            stmt = stmt.join(UserModel.roles).where(func.lower(RoleModel.code) == role_code.lower())
            count_stmt = count_stmt.join(UserModel.roles).where(func.lower(RoleModel.code) == role_code.lower())
        if conditions:
            stmt = stmt.where(*conditions)
            count_stmt = count_stmt.where(*conditions)
        total = self.db.scalar(count_stmt) or 0
        items = list(
            self.db.scalars(
                stmt.order_by(UserModel.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
            ).unique()
        )
        return items, total

    def add(self, user: UserModel) -> UserModel:
        self.db.add(user)
        self.db.flush()
        self.db.refresh(user)
        return user


from src.roles.infrastructure.persistence.models.role import RoleModel  # noqa: E402
