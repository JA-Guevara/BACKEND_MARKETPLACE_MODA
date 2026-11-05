from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.plataforma_saas.domain.exceptions import TemplateImpactConfirmationError
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.plataforma_saas.web.schemas.governance import (
    PermissionCatalogItem,
    PlatformRoleIn,
    RoleTemplateOut,
    TemplateImpact,
)
from src.roles.infrastructure.persistence.models.permission import PermissionModel
from src.roles.infrastructure.persistence.models.role import RoleModel, user_roles
from src.shared.exceptions.domain_exception import ConflictError, NotFoundError, ValidationError


class PlatformRolesService:
    def __init__(self, db: Session, actor=None) -> None:
        self.db = db
        self.actor = actor

    def _get_role(self, role_id: UUID) -> RoleModel:
        role = self.db.get(RoleModel, role_id)
        if not role:
            raise NotFoundError("Rol no encontrado.")
        return role

    def plantillas(self) -> list[RoleTemplateOut]:
        stmt = (
            select(RoleModel)
            .where(
                RoleModel.tenant_id.is_(None),
                RoleModel.audience == "TENANT",
            )
            .order_by(RoleModel.name)
        )
        templates = list(self.db.scalars(stmt).all())

        results: list[RoleTemplateOut] = []
        for r in templates:
            users_count = (
                self.db.scalar(
                    select(func.count(user_roles.c.user_id)).where(user_roles.c.role_id == r.id)
                )
                or 0
            )
            # Contar empresas distintas
            from src.auth.infrastructure.persistence.models.user import UserModel
            tenants_count = (
                self.db.scalar(
                    select(func.count(func.distinct(UserModel.tenant_id)))
                    .join(user_roles, user_roles.c.user_id == UserModel.id)
                    .where(user_roles.c.role_id == r.id, UserModel.tenant_id.is_not(None))
                )
                or 0
            )

            results.append(
                RoleTemplateOut(
                    id=r.id,
                    code=r.code,
                    name=r.name,
                    description=r.description,
                    is_system=r.is_system,
                    audience=r.audience,
                    tenants_count=tenants_count,
                    users_count=users_count,
                    permissions=[p.code for p in r.permissions],
                )
            )
        return results

    def impacto_plantilla(self, role_id: UUID, permission_codes: list[str]) -> TemplateImpact:
        role = self._get_role(role_id)
        if role.tenant_id is not None or role.audience != "TENANT":
            raise ValidationError("Solo se puede calcular impacto en plantillas de empresa.")

        current_codes = {p.code for p in role.permissions}
        new_codes = set(permission_codes)

        added = sorted(new_codes - current_codes)
        removed = sorted(current_codes - new_codes)

        from src.auth.infrastructure.persistence.models.user import UserModel
        users_count = (
            self.db.scalar(
                select(func.count(user_roles.c.user_id)).where(user_roles.c.role_id == role.id)
            )
            or 0
        )
        tenants_count = (
            self.db.scalar(
                select(func.count(func.distinct(UserModel.tenant_id)))
                .join(user_roles, user_roles.c.user_id == UserModel.id)
                .where(user_roles.c.role_id == role.id, UserModel.tenant_id.is_not(None))
            )
            or 0
        )

        return TemplateImpact(
            role_id=role.id,
            affected_tenants=tenants_count,
            affected_users=users_count,
            permissions_added=added,
            permissions_removed=removed,
        )

    def actualizar_plantilla(
        self,
        role_id: UUID,
        permission_codes: list[str],
        reason: str,
        confirm: bool = False,
    ) -> RoleTemplateOut:
        role = self._get_role(role_id)
        if role.tenant_id is not None or role.audience != "TENANT":
            raise ValidationError("Solo se pueden actualizar plantillas de empresa.")

        impact = self.impacto_plantilla(role_id, permission_codes)
        if not confirm:
            raise TemplateImpactConfirmationError(details={"impact": impact.model_dump(mode="json")})

        # Validar que todos los permisos pertenezcan al scope tenant
        perms = list(
            self.db.scalars(
                select(PermissionModel).where(PermissionModel.code.in_(permission_codes))
            ).all()
        )
        if len(perms) != len(set(permission_codes)):
            raise NotFoundError("Uno o más permisos no fueron encontrados.")

        for p in perms:
            if getattr(p, "scope", "tenant") != "tenant":
                raise ValidationError(
                    f"El permiso '{p.code}' tiene alcance de plataforma y no puede agregarse a una plantilla de empresa.",
                    code="permission_scope_mismatch",
                )

        role.permissions = perms
        RecordAuditEvent(self.db).execute(
            actor_user_id=self.actor.id if self.actor else None,
            action="platform.template_updated",
            entity_type="role",
            entity_id=str(role.id),
            description=f"Plantilla '{role.name}' actualizada: {len(perms)} permisos.",
            metadata={"permission_codes": permission_codes, "reason": reason, "impact": impact.model_dump(mode="json")},
        )
        self.db.commit()

        return RoleTemplateOut(
            id=role.id,
            code=role.code,
            name=role.name,
            description=role.description,
            is_system=role.is_system,
            audience=role.audience,
            tenants_count=impact.affected_tenants,
            users_count=impact.affected_users,
            permissions=[p.code for p in role.permissions],
        )

    def roles_equipo(self) -> list[RoleTemplateOut]:
        stmt = (
            select(RoleModel)
            .where(
                RoleModel.audience == "PLATFORM",
            )
            .order_by(RoleModel.name)
        )
        roles = list(self.db.scalars(stmt).all())
        results: list[RoleTemplateOut] = []
        for r in roles:
            users_count = (
                self.db.scalar(
                    select(func.count(user_roles.c.user_id)).where(user_roles.c.role_id == r.id)
                )
                or 0
            )
            results.append(
                RoleTemplateOut(
                    id=r.id,
                    code=r.code,
                    name=r.name,
                    description=r.description,
                    is_system=r.is_system,
                    audience=r.audience,
                    tenants_count=0,
                    users_count=users_count,
                    permissions=[p.code for p in r.permissions],
                )
            )
        return results

    def crear_rol_equipo(self, data: PlatformRoleIn) -> RoleTemplateOut:
        existing = self.db.scalar(
            select(RoleModel).where(RoleModel.code == data.code, RoleModel.audience == "PLATFORM")
        )
        if existing:
            raise ConflictError(f"Ya existe un rol de plataforma con código '{data.code}'.")

        perms = list(
            self.db.scalars(
                select(PermissionModel).where(PermissionModel.code.in_(data.permission_codes))
            ).all()
        )
        if len(perms) != len(set(data.permission_codes)):
            raise NotFoundError("Uno o más permisos no fueron encontrados.")

        for p in perms:
            if getattr(p, "scope", "tenant") != "platform":
                raise ValidationError(
                    f"El permiso '{p.code}' tiene alcance de empresa y no puede pertenecer a un rol de plataforma.",
                    code="permission_scope_mismatch",
                )

        role = RoleModel(
            code=data.code,
            name=data.name,
            description=data.description,
            audience="PLATFORM",
            is_system=False,
            tenant_id=None,
            permissions=perms,
        )
        self.db.add(role)
        self.db.flush()

        RecordAuditEvent(self.db).execute(
            actor_user_id=self.actor.id if self.actor else None,
            action="platform.role_created",
            entity_type="role",
            entity_id=str(role.id),
            description=f"Rol de equipo de plataforma '{role.name}' creado.",
            metadata={"code": data.code, "permissions": data.permission_codes},
        )
        self.db.commit()

        return RoleTemplateOut(
            id=role.id,
            code=role.code,
            name=role.name,
            description=role.description,
            is_system=role.is_system,
            audience=role.audience,
            tenants_count=0,
            users_count=0,
            permissions=[p.code for p in role.permissions],
        )

    def actualizar_rol_equipo(self, role_id: UUID, data: PlatformRoleIn) -> RoleTemplateOut:
        role = self._get_role(role_id)
        if role.code == "platform_admin" and role.is_system:
            raise ConflictError("El rol platform_admin no se puede modificar.")
        if role.audience != "PLATFORM":
            raise ValidationError("Solo se pueden actualizar roles de plataforma desde esta sección.")

        perms = list(
            self.db.scalars(
                select(PermissionModel).where(PermissionModel.code.in_(data.permission_codes))
            ).all()
        )
        if len(perms) != len(set(data.permission_codes)):
            raise NotFoundError("Uno o más permisos no fueron encontrados.")

        for p in perms:
            if getattr(p, "scope", "tenant") != "platform":
                raise ValidationError(
                    f"El permiso '{p.code}' tiene alcance de empresa y no puede pertenecer a un rol de plataforma.",
                    code="permission_scope_mismatch",
                )

        role.name = data.name
        role.description = data.description
        role.permissions = perms

        RecordAuditEvent(self.db).execute(
            actor_user_id=self.actor.id if self.actor else None,
            action="platform.role_updated",
            entity_type="role",
            entity_id=str(role.id),
            description=f"Rol de equipo '{role.name}' actualizado.",
            metadata={"code": role.code, "permissions": data.permission_codes},
        )
        self.db.commit()

        users_count = (
            self.db.scalar(
                select(func.count(user_roles.c.user_id)).where(user_roles.c.role_id == role.id)
            )
            or 0
        )
        return RoleTemplateOut(
            id=role.id,
            code=role.code,
            name=role.name,
            description=role.description,
            is_system=role.is_system,
            audience=role.audience,
            tenants_count=0,
            users_count=users_count,
            permissions=[p.code for p in role.permissions],
        )

    def desactivar_rol_equipo(self, role_id: UUID) -> RoleTemplateOut:
        role = self._get_role(role_id)
        if role.code == "platform_admin":
            raise ConflictError("El rol platform_admin no se puede desactivar.")

        role.is_active = False
        RecordAuditEvent(self.db).execute(
            actor_user_id=self.actor.id if self.actor else None,
            action="platform.role_deactivated",
            entity_type="role",
            entity_id=str(role.id),
            description=f"Rol de equipo '{role.name}' desactivado.",
        )
        self.db.commit()

        return RoleTemplateOut(
            id=role.id,
            code=role.code,
            name=role.name,
            description=role.description,
            is_system=role.is_system,
            audience=role.audience,
            tenants_count=0,
            users_count=0,
            permissions=[p.code for p in role.permissions],
        )

    def catalogo_permisos(self) -> list[PermissionCatalogItem]:
        stmt = select(PermissionModel).order_by(PermissionModel.scope, PermissionModel.code)
        return [PermissionCatalogItem.model_validate(p) for p in self.db.scalars(stmt).all()]

    def actualizar_permiso(
        self,
        permission_id: UUID,
        name: str | None = None,
        description: str | None = None,
        is_active: bool | None = None,
    ) -> PermissionCatalogItem:
        p = self.db.get(PermissionModel, permission_id)
        if not p:
            raise NotFoundError("Permiso no encontrado.")

        if name is not None:
            p.name = name.strip()
        if description is not None:
            p.description = description.strip()
        if is_active is not None:
            p.is_active = is_active

        RecordAuditEvent(self.db).execute(
            actor_user_id=self.actor.id if self.actor else None,
            action="platform.permission_updated",
            entity_type="permission",
            entity_id=str(p.id),
            description=f"Permiso '{p.code}' actualizado.",
        )
        self.db.commit()
        return PermissionCatalogItem.model_validate(p)
