import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.inventario_sucursales.infrastructure.models.organization import (
    BranchModel,
    UserBranchModel,
)
from src.shared.exceptions.domain_exception import NotFoundError, ValidationError


class UserBranchService:
    def __init__(self, db: Session, tenant_id: UUID, actor_id: UUID | None = None) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.actor_id = actor_id

    def autorizadas(self, user: UserModel) -> list[BranchModel]:
        # Si el usuario no tiene tenant_id o no coincide con este tenant, retorna vacío
        if not user.tenant_id or user.tenant_id != self.tenant_id:
            return []

        # Roles con acceso total a todas las sucursales de la empresa
        role_codes = {r.code for r in getattr(user, "roles", [])}
        is_admin = bool({"admin", "superadmin", "platform_admin"} & role_codes)

        if is_admin:
            stmt = (
                select(BranchModel)
                .where(
                    BranchModel.tenant_id == self.tenant_id,
                    BranchModel.is_active.is_(True),
                    BranchModel.deleted_at.is_(None),
                )
                .order_by(BranchModel.code)
            )
            return list(self.db.scalars(stmt).all())

        # Resto del personal: solo sucursales expresamente asignadas y activas
        stmt = (
            select(BranchModel)
            .join(UserBranchModel, UserBranchModel.branch_id == BranchModel.id)
            .where(
                UserBranchModel.tenant_id == self.tenant_id,
                UserBranchModel.user_id == user.id,
                BranchModel.is_active.is_(True),
                BranchModel.deleted_at.is_(None),
            )
            .order_by(UserBranchModel.is_default.desc(), BranchModel.code)
        )
        return list(self.db.scalars(stmt).all())

    def puede_operar(self, user: UserModel, branch_id: UUID) -> bool:
        return any(b.id == branch_id for b in self.autorizadas(user))

    def asignar(
        self,
        user_id: UUID,
        branch_ids: list[UUID],
        default_branch_id: UUID | None = None,
    ) -> list[BranchModel]:
        user = self.db.get(UserModel, user_id)
        if not user or user.deleted_at is not None or user.tenant_id != self.tenant_id:
            raise NotFoundError("Usuario no encontrado en esta empresa.")

        if default_branch_id and default_branch_id not in branch_ids:
            raise ValidationError("La sucursal predeterminada debe estar dentro de las sucursales asignadas.")

        branches: list[BranchModel] = []
        if branch_ids:
            stmt = select(BranchModel).where(
                BranchModel.tenant_id == self.tenant_id,
                BranchModel.id.in_(branch_ids),
                BranchModel.deleted_at.is_(None),
            )
            branches = list(self.db.scalars(stmt).all())
            if len(branches) != len(set(branch_ids)):
                raise NotFoundError("Una o más sucursales no fueron encontradas en esta empresa.")

        # Si no se pasó default_branch_id pero hay sucursales, la primera por código es la predeterminada
        if branch_ids and not default_branch_id:
            branches_sorted = sorted(branches, key=lambda b: b.code)
            default_branch_id = branches_sorted[0].id

        # Reemplazar sucursales asignadas
        self.db.execute(
            delete(UserBranchModel).where(
                UserBranchModel.tenant_id == self.tenant_id,
                UserBranchModel.user_id == user_id,
            )
        )

        now = datetime.now(timezone.utc)
        for b in branches:
            ub = UserBranchModel(
                tenant_id=self.tenant_id,
                user_id=user_id,
                branch_id=b.id,
                is_default=(b.id == default_branch_id),
                created_at=now,
            )
            self.db.add(ub)

        RecordAuditEvent(self.db).execute(
            actor_user_id=self.actor_id,
            action="users.branches_updated",
            entity_type="user",
            entity_id=str(user_id),
            description=f"Sucursales actualizadas para el usuario {user.email}",
            metadata={
                "tenant_id": str(self.tenant_id),
                "branch_ids": [str(b.id) for b in branches],
                "default_branch_id": str(default_branch_id) if default_branch_id else None,
            },
        )
        self.db.commit()
        return self.autorizadas(user)
