from datetime import datetime, timezone
from typing import Literal
from uuid import UUID
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, joinedload

from src.auth.application.services.auth_service import AuthService
from src.auth.domain.exceptions import EmailAlreadyExistsError
from src.auth.infrastructure.persistence.models.refresh_token import RefreshTokenModel
from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.plataforma_saas.domain.exceptions import LastPlatformAdminError
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.plataforma_saas.web.schemas.console import GlobalUserResponse
from src.plataforma_saas.web.schemas.platform_users import PlatformAdminInvite
from src.roles.infrastructure.persistence.models.role import RoleModel
from src.shared.exceptions.domain_exception import ConflictError, NotFoundError
from src.shared.responses.pagination import Page


class PlatformUsersService:
    def __init__(self, db: Session, actor: UserModel | None = None) -> None:
        self.db = db
        self.actor = actor

    def _get_user(self, user_id: UUID) -> UserModel:
        user = self.db.get(UserModel, user_id)
        if not user or user.deleted_at is not None:
            raise NotFoundError("Usuario no encontrado.")
        return user

    def _audit(self, action: str, user: UserModel, description: str) -> None:
        event = AuditEventModel(
            tenant_id=user.tenant_id,
            support_session_id=None,
            actor_user_id=self.actor.id if self.actor else None,
            action=action,
            entity_type="user",
            entity_id=str(user.id),
            description=description,
        )
        self.db.add(event)

    def _to_response(self, user: UserModel) -> GlobalUserResponse:
        tenant_name = None
        if user.tenant_id:
            tenant = self.db.get(TenantModel, user.tenant_id)
            if tenant:
                tenant_name = tenant.trade_name
        return GlobalUserResponse(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            tenant_id=user.tenant_id,
            tenant_name=tenant_name,
            roles=[r.name for r in user.roles],
            is_active=user.is_active,
            is_verified=user.is_verified,
            locked_until=user.locked_until,
            last_login_at=user.last_login_at,
            created_at=user.created_at,
        )

    def buscar(
        self,
        *,
        search: str | None = None,
        tenant_id: UUID | None = None,
        status: Literal["active", "blocked", "unverified", "inactive"] | None = None,
        kind: Literal["platform", "tenant_admin", "staff", "client"] | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Page[GlobalUserResponse]:
        now = datetime.now(timezone.utc)
        stmt = (
            select(UserModel)
            .options(joinedload(UserModel.roles))
            .where(UserModel.deleted_at.is_(None))
        )

        if tenant_id is not None:
            stmt = stmt.where(UserModel.tenant_id == tenant_id)

        if search:
            s = f"%{search.strip()}%"
            stmt = stmt.where(
                UserModel.email.ilike(s)
                | UserModel.first_name.ilike(s)
                | UserModel.last_name.ilike(s)
            )

        if status == "active":
            stmt = stmt.where(
                UserModel.is_active.is_(True),
                UserModel.is_verified.is_(True),
                (UserModel.locked_until.is_(None)) | (UserModel.locked_until <= now),
            )
        elif status == "blocked":
            stmt = stmt.where(
                UserModel.locked_until.is_not(None),
                UserModel.locked_until > now,
            )
        elif status == "unverified":
            stmt = stmt.where(UserModel.is_verified.is_(False))
        elif status == "inactive":
            stmt = stmt.where(UserModel.is_active.is_(False))

        if kind == "platform":
            stmt = stmt.where(UserModel.tenant_id.is_(None))
        elif kind == "tenant_admin":
            stmt = stmt.where(
                UserModel.tenant_id.is_not(None),
                UserModel.roles.any(RoleModel.code == "admin"),
            )
        elif kind == "staff":
            stmt = stmt.where(
                UserModel.tenant_id.is_not(None),
                UserModel.roles.any(
                    RoleModel.code.in_(["store_manager", "cashier", "staff"])
                ),
            )
        elif kind == "client":
            stmt = stmt.where(
                UserModel.roles.any(RoleModel.code == "client")
            )

        total = self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        items_db = (
            self.db.execute(
                stmt.order_by(desc(UserModel.created_at))
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            .scalars()
            .unique()
            .all()
        )

        # Pre-cache tenant names
        tenant_ids = {u.tenant_id for u in items_db if u.tenant_id}
        tenants = (
            self.db.execute(select(TenantModel).where(TenantModel.id.in_(tenant_ids)))
            .scalars()
            .all()
            if tenant_ids
            else []
        )
        tenant_map = {t.id: t.trade_name for t in tenants}

        items = [
            GlobalUserResponse(
                id=u.id,
                first_name=u.first_name,
                last_name=u.last_name,
                email=u.email,
                tenant_id=u.tenant_id,
                tenant_name=tenant_map.get(u.tenant_id),
                roles=[r.name for r in u.roles],
                is_active=u.is_active,
                is_verified=u.is_verified,
                locked_until=u.locked_until,
                last_login_at=u.last_login_at,
                created_at=u.created_at,
            )
            for u in items_db
        ]

        pages = (total + page_size - 1) // page_size if page_size > 0 else 1
        return Page[GlobalUserResponse](
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )

    def desbloquear(self, user_id: UUID) -> GlobalUserResponse:
        user = self._get_user(user_id)
        user.locked_until = None
        user.failed_login_attempts = 0
        self._audit("platform.user_unlocked", user, f"Usuario {user.email} desbloqueado")
        self.db.commit()
        return self._to_response(user)

    def reenviar_verificacion(self, user_id: UUID) -> GlobalUserResponse:
        user = self._get_user(user_id)
        auth = AuthService(self.db)
        token = auth.issue_email_verification_token(user)
        try:
            auth.email.send_verification_email(user.email, token)
        except Exception:
            pass
        self._audit(
            "platform.user_verification_resent",
            user,
            f"Enlace de verificación reenviado a {user.email}",
        )
        self.db.commit()
        return self._to_response(user)

    def cerrar_sesiones(self, user_id: UUID) -> GlobalUserResponse:
        user = self._get_user(user_id)
        self.db.query(RefreshTokenModel).filter(
            RefreshTokenModel.user_id == user.id
        ).delete(synchronize_session=False)
        self._audit(
            "platform.user_sessions_revoked",
            user,
            f"Sesiones revocadas para {user.email}",
        )
        self.db.commit()
        return self._to_response(user)

    def desactivar(self, user_id: UUID) -> GlobalUserResponse:
        user = self._get_user(user_id)
        user.is_active = False
        self._audit("platform.user_deactivated", user, f"Usuario {user.email} desactivado")
        self.db.commit()
        return self._to_response(user)

    def activar(self, user_id: UUID) -> GlobalUserResponse:
        user = self._get_user(user_id)
        user.is_active = True
        self._audit("platform.user_activated", user, f"Usuario {user.email} activado")
        self.db.commit()
        return self._to_response(user)

    def listar_admins(self) -> list[GlobalUserResponse]:
        stmt = (
            select(UserModel)
            .options(joinedload(UserModel.roles))
            .where(
                UserModel.tenant_id.is_(None),
                UserModel.deleted_at.is_(None),
                UserModel.roles.any(RoleModel.code == "platform_admin"),
            )
            .order_by(UserModel.first_name)
        )
        admins = self.db.execute(stmt).scalars().unique().all()
        return [self._to_response(u) for u in admins]

    def invitar_admin(self, data: PlatformAdminInvite) -> GlobalUserResponse:
        existing = self.db.scalar(
            select(UserModel).where(
                func.lower(UserModel.email) == data.email.lower(),
                UserModel.deleted_at.is_(None),
            )
        )
        if existing:
            raise EmailAlreadyExistsError()

        role = self.db.scalar(
            select(RoleModel).where(RoleModel.code == "platform_admin")
        )
        if not role:
            role = RoleModel(code="platform_admin", name="Plataforma", is_system=True)
            self.db.add(role)
            self.db.flush()

        auth = AuthService(self.db)
        pwd_hash = auth.create_unusable_password_hash()
        user = UserModel(
            email=data.email.lower(),
            first_name=data.first_name.strip(),
            last_name=data.last_name.strip(),
            password_hash=pwd_hash,
            is_active=True,
            is_verified=True,
            tenant_id=None,
            roles=[role],
        )
        self.db.add(user)
        self.db.flush()

        token = auth.issue_password_setup_token(user)
        try:
            auth.email.send_tenant_invitation(user.email, token, "FashionStore")
        except Exception:
            pass

        self._audit(
            "platform.admin_invited",
            user,
            f"Super administrador invitado: {data.email}",
        )
        self.db.commit()
        return self._to_response(user)

    def desactivar_admin(self, user_id: UUID) -> GlobalUserResponse:
        if self.actor and self.actor.id == user_id:
            raise ConflictError("No puedes desactivar tu propia cuenta.")

        active_admins = (
            self.db.execute(
                select(UserModel).where(
                    UserModel.tenant_id.is_(None),
                    UserModel.deleted_at.is_(None),
                    UserModel.is_active.is_(True),
                    UserModel.roles.any(RoleModel.code == "platform_admin"),
                )
            )
            .scalars()
            .all()
        )
        if len(active_admins) <= 1 and any(u.id == user_id for u in active_admins):
            raise LastPlatformAdminError()

        user = self._get_user(user_id)
        user.is_active = False
        self._audit(
            "platform.admin_deactivated",
            user,
            f"Super administrador desactivado: {user.email}",
        )
        self.db.commit()
        return self._to_response(user)
