import secrets
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, joinedload

from src.auth.application.services.auth_service import AuthService
from src.auth.domain.exceptions import EmailAlreadyExistsError
from src.auth.infrastructure.persistence.models.refresh_token import RefreshTokenModel
from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.inventario_sucursales.application.services.user_branch_service import UserBranchService
from src.plataforma_saas.application.entitlement_service import EntitlementService
from src.plataforma_saas.domain.exceptions import LastPlatformAdminError, RoleTenantMismatchError
from src.plataforma_saas.infrastructure.models.module import ModulePermissionModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.plataforma_saas.web.schemas.console import BranchSummary, GlobalUserResponse
from src.plataforma_saas.web.schemas.governance import (
    EffectivePermissionItem,
    EffectivePermissions,
    GlobalUserCreate,
    GlobalUserUpdate,
)
from src.plataforma_saas.web.schemas.platform_users import PlatformAdminInvite
from src.roles.infrastructure.persistence.models.permission import PermissionModel
from src.roles.infrastructure.persistence.models.role import RoleModel
from src.shared.exceptions.domain_exception import ConflictError, NotFoundError, ValidationError
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

    def _to_response(
        self,
        user: UserModel,
        temporary_password: str | None = None,
        must_change_password: bool | None = None,
    ) -> GlobalUserResponse:
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
            phone=user.phone,
            tenant_id=user.tenant_id,
            tenant_name=tenant_name,
            roles=[r.name for r in user.roles],
            is_active=user.is_active,
            is_verified=user.is_verified,
            must_change_password=must_change_password if must_change_password is not None else getattr(user, "must_change_password", False),
            temporary_password=temporary_password,
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
                phone=u.phone,
                tenant_id=u.tenant_id,
                tenant_name=tenant_map.get(u.tenant_id),
                roles=[r.name for r in u.roles],
                is_active=u.is_active,
                is_verified=u.is_verified,
                must_change_password=getattr(u, "must_change_password", False),
                locked_until=u.locked_until,
                last_login_at=u.last_login_at,
                created_at=u.created_at,
            )
            for u in items_db
        ]

        return Page(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=(total + page_size - 1) // page_size if total else 0,
        )

    def crear(self, data: GlobalUserCreate) -> GlobalUserResponse:
        existing = self.db.scalar(
            select(UserModel).where(
                func.lower(UserModel.email) == data.email.lower(),
                UserModel.deleted_at.is_(None),
            )
        )
        if existing:
            raise EmailAlreadyExistsError()

        roles = list(self.db.scalars(select(RoleModel).where(RoleModel.id.in_(data.role_ids))).all())
        if len(roles) != len(set(data.role_ids)):
            raise NotFoundError("Uno o más roles no fueron encontrados.")

        if data.kind == "tenant":
            if not data.tenant_id:
                raise ValidationError("tenant_id es obligatorio para usuarios de empresa.", code="tenant_required")
            tenant = self.db.get(TenantModel, data.tenant_id)
            if not tenant:
                raise NotFoundError("Empresa no encontrada.")
            for r in roles:
                if getattr(r, "audience", "TENANT") == "PLATFORM" or (r.tenant_id is not None and r.tenant_id != data.tenant_id):
                    raise RoleTenantMismatchError()
        elif data.kind == "platform":
            if data.tenant_id is not None:
                raise ValidationError("tenant_id debe ser None para usuarios de plataforma.", code="platform_tenant_not_allowed")
            for r in roles:
                if getattr(r, "audience", "TENANT") != "PLATFORM" or r.tenant_id is not None:
                    raise RoleTenantMismatchError()
        else:
            raise ValidationError(f"Tipo de usuario desconocido: '{data.kind}'")

        auth = AuthService(self.db)
        temp_pass: str | None = None
        must_change = False

        if data.access == "temporary_password":
            temp_pass = f"Tmp_{secrets.token_urlsafe(8)}!"
            pwd_hash = auth.passwords.hash(temp_pass)
            must_change = True
        else:
            pwd_hash = auth.create_unusable_password_hash()
            must_change = False

        user = UserModel(
            email=data.email.lower(),
            first_name=data.first_name.strip(),
            last_name=data.last_name.strip(),
            phone=data.phone.strip() if data.phone else None,
            password_hash=pwd_hash,
            is_active=True,
            is_verified=True,
            tenant_id=data.tenant_id,
            roles=roles,
        )
        user.must_change_password = must_change
        self.db.add(user)
        self.db.flush()

        if data.access == "invite":
            token = auth.issue_password_setup_token(user)
            try:
                auth.email.send_tenant_invitation(user.email, token, "FashionStore")
            except Exception:
                pass

        if data.branch_ids and data.tenant_id:
            UserBranchService(
                self.db, data.tenant_id, self.actor.id if self.actor else None
            ).asignar(user.id, data.branch_ids)

        self._audit(
            "platform.user_created",
            user,
            f"Usuario global creado: {user.email}",
        )
        if user.tenant_id:
            RecordAuditEvent(self.db).execute(
                tenant_id=user.tenant_id,
                actor_user_id=self.actor.id if self.actor else None,
                action="users.created",
                entity_type="user",
                entity_id=str(user.id),
                description=f"Usuario {user.email} dado de alta desde la consola de plataforma.",
            )

        self.db.commit()
        return self._to_response(user, temporary_password=temp_pass, must_change_password=must_change)

    def actualizar(self, user_id: UUID, data: GlobalUserUpdate) -> GlobalUserResponse:
        user = self._get_user(user_id)

        if data.first_name is not None:
            user.first_name = data.first_name.strip()
        if data.last_name is not None:
            user.last_name = data.last_name.strip()
        if data.phone is not None:
            user.phone = data.phone.strip() if data.phone else None
        if data.is_active is not None:
            user.is_active = data.is_active

        if data.email is not None and data.email.lower() != user.email.lower():
            existing = self.db.scalar(
                select(UserModel).where(
                    func.lower(UserModel.email) == data.email.lower(),
                    UserModel.id != user.id,
                    UserModel.deleted_at.is_(None),
                )
            )
            if existing:
                raise EmailAlreadyExistsError()
            user.email = data.email.lower()
            user.is_verified = False

        self._audit("platform.user_updated", user, f"Usuario {user.email} actualizado.")
        self.db.commit()
        return self._to_response(user)

    def asignar_roles(self, user_id: UUID, role_ids: list[UUID]) -> GlobalUserResponse:
        user = self._get_user(user_id)
        roles = list(self.db.scalars(select(RoleModel).where(RoleModel.id.in_(role_ids))).all())
        if len(roles) != len(set(role_ids)):
            raise NotFoundError("Uno o más roles no fueron encontrados.")

        if user.tenant_id:
            for r in roles:
                if getattr(r, "audience", "TENANT") == "PLATFORM" or (r.tenant_id is not None and r.tenant_id != user.tenant_id):
                    raise RoleTenantMismatchError()

            had_admin = any(r.code == "admin" for r in user.roles)
            will_have_admin = any(r.code == "admin" for r in roles)
            if had_admin and not will_have_admin:
                other_admins = self.db.scalars(
                    select(UserModel).where(
                        UserModel.tenant_id == user.tenant_id,
                        UserModel.id != user.id,
                        UserModel.is_active.is_(True),
                        UserModel.deleted_at.is_(None),
                        UserModel.roles.any(RoleModel.code == "admin"),
                    )
                ).all()
                if not other_admins:
                    raise ConflictError(
                        "No se puede quitar el rol admin al único administrador activo de la empresa.",
                        code="last_tenant_admin",
                    )
        else:
            for r in roles:
                if getattr(r, "audience", "TENANT") != "PLATFORM" or r.tenant_id is not None:
                    raise RoleTenantMismatchError()

            had_superadmin = any(r.code == "platform_admin" for r in user.roles)
            will_have_superadmin = any(r.code == "platform_admin" for r in roles)
            if had_superadmin and not will_have_superadmin:
                other_superadmins = self.db.scalars(
                    select(UserModel).where(
                        UserModel.tenant_id.is_(None),
                        UserModel.id != user.id,
                        UserModel.is_active.is_(True),
                        UserModel.deleted_at.is_(None),
                        UserModel.roles.any(RoleModel.code == "platform_admin"),
                    )
                ).all()
                if not other_superadmins:
                    raise LastPlatformAdminError()

        user.roles = roles
        self._audit(
            "platform.user_roles_updated",
            user,
            f"Roles asignados a {user.email}: {[r.name for r in roles]}",
        )
        self.db.commit()
        return self._to_response(user)

    def asignar_sucursales(
        self,
        user_id: UUID,
        branch_ids: list[UUID],
        default_id: UUID | None = None,
    ) -> list[BranchSummary]:
        user = self._get_user(user_id)
        if not user.tenant_id:
            raise ValidationError("Solo los usuarios de empresa pueden tener sucursales asignadas.")

        branches = UserBranchService(
            self.db, user.tenant_id, self.actor.id if self.actor else None
        ).asignar(user.id, branch_ids, default_id)

        return [
            BranchSummary(
                id=b.id,
                name=b.name,
                city_name=b.city.name if b.city else "",
                address=b.address,
                code=b.code,
                is_default=(b.id == default_id) if default_id else False,
                is_active=b.is_active,
            )
            for b in branches
        ]

    def permisos_efectivos(self, user_id: UUID) -> EffectivePermissions:
        user = self._get_user(user_id)

        # Mapear permisos otorgados por roles del usuario
        user_permission_map: dict[str, str] = {}
        for role in user.roles:
            for p in getattr(role, "permissions", []):
                if p.code not in user_permission_map:
                    user_permission_map[p.code] = role.name

        # Módulos y permisos
        mod_perms_rows = self.db.scalars(select(ModulePermissionModel)).all()
        perm_to_module = {mp.permission_code: mp.module_code for mp in mod_perms_rows}
        if not perm_to_module:
            from src.plataforma_saas.application.entitlement_service import DEFAULT_MODULE_PERMISSION_MAPPING
            perm_to_module = dict(DEFAULT_MODULE_PERMISSION_MAPPING)

        all_permissions = list(
            self.db.scalars(
                select(PermissionModel).where(PermissionModel.is_active.is_(True)).order_by(PermissionModel.code)
            ).all()
        )

        active_modules: dict[str, any] = {}
        if user.tenant_id:
            active_modules = EntitlementService(self.db).modulos(user.tenant_id)

        items: list[EffectivePermissionItem] = []
        for perm in all_permissions:
            granted_by = user_permission_map.get(perm.code)
            mod_code = perm_to_module.get(perm.code)

            if not granted_by:
                status = "SIN_ROL"
            elif not user.tenant_id:
                status = "PERMITIDO"
            elif mod_code:
                mod = active_modules.get(mod_code)
                if not mod:
                    status = "BLOQUEADO_MODULO"
                elif getattr(mod, "origen", "") == "TRIAL":
                    status = "PRUEBA"
                else:
                    status = "PERMITIDO"
            else:
                status = "PERMITIDO"

            items.append(
                EffectivePermissionItem(
                    code=perm.code,
                    name=perm.name,
                    module=mod_code,
                    granted_by_role=granted_by,
                    status=status,
                )
            )

        return EffectivePermissions(user_id=user.id, permissions=items)

    def restablecer_contrasena(self, user_id: UUID) -> GlobalUserResponse:
        user = self._get_user(user_id)
        auth = AuthService(self.db)
        token = auth.issue_password_setup_token(user)
        try:
            auth.email.send_password_reset(user.email, token)
        except Exception:
            pass

        self._audit("platform.password_reset_sent", user, f"Enlace de restablecimiento enviado a {user.email}")
        self.db.commit()
        return self._to_response(user)

    def forzar_cambio(self, user_id: UUID) -> GlobalUserResponse:
        user = self._get_user(user_id)
        user.must_change_password = True
        self._audit("platform.force_password_change", user, f"Se forzó cambio de contraseña para {user.email}")
        self.db.commit()
        return self._to_response(user)

    def desbloquear(self, user_id: UUID) -> GlobalUserResponse:
        user = self._get_user(user_id)
        user.locked_until = None
        user.failed_login_attempts = 0
        self._audit(
            "platform.user_unlocked",
            user,
            f"Usuario {user.email} desbloqueado.",
        )
        self.db.commit()
        return self._to_response(user)

    def reenviar_verificacion(self, user_id: UUID) -> GlobalUserResponse:
        user = self._get_user(user_id)
        auth = AuthService(self.db)
        token = auth.issue_verification_token(user)
        try:
            auth.email.send_verification_email(user.email, token)
        except Exception:
            pass
        self._audit(
            "platform.verification_resent",
            user,
            f"Verificación reenviada a {user.email}",
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
            role = RoleModel(code="platform_admin", name="Plataforma", is_system=True, audience="PLATFORM")
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

    def activar_admin(self, user_id: UUID) -> GlobalUserResponse:
        user = self._get_user(user_id)
        user.is_active = True
        self._audit("platform.admin_activated", user, f"Super administrador reactivado: {user.email}")
        self.db.commit()
        return self._to_response(user)

    def eliminar_admin(self, user_id: UUID) -> bool:
        if self.actor and self.actor.id == user_id:
            raise ConflictError("No puedes eliminar tu propia cuenta de super administrador.")
        active_admins = (
            self.db.execute(
                select(UserModel).where(
                    UserModel.tenant_id.is_(None),
                    UserModel.deleted_at.is_(None),
                    UserModel.is_active.is_(True),
                    UserModel.roles.any(RoleModel.code == "platform_admin"),
                )
            ).scalars().all()
        )
        if len(active_admins) <= 1 and any(u.id == user_id for u in active_admins):
            raise LastPlatformAdminError("No se puede eliminar el único super administrador activo de la plataforma.")
        user = self._get_user(user_id)
        user.deleted_at = datetime.now(timezone.utc)
        user.is_active = False
        self._audit("platform.admin_deleted", user, f"Super administrador eliminado: {user.email}")
        self.db.commit()
        return True
