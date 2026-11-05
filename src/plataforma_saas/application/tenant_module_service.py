from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.plataforma_saas.application.entitlement_service import EntitlementService
from src.plataforma_saas.domain.modulos import OverrideMode
from src.plataforma_saas.infrastructure.models.module import (
    PlatformModuleModel,
    TenantLimitModel,
    TenantModuleModel,
)
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.plataforma_saas.infrastructure.repositories.saas_repository import SaasRepository
from src.plataforma_saas.web.schemas.governance import (
    TenantLimitOut,
    TenantModuleOut,
)
from src.shared.exceptions.domain_exception import (
    ConflictError,
    NotFoundError,
    ValidationError,
)


class TenantModuleService:
    def __init__(self, db: Session, actor) -> None:
        self.db = db
        self.actor = actor

    def _get_tenant(self, tenant_id: UUID) -> TenantModel:
        tenant = self.db.get(TenantModel, tenant_id)
        if not tenant:
            raise NotFoundError("Empresa no encontrada.")
        return tenant

    def listar(self, tenant_id: UUID) -> list[TenantModuleOut]:
        self._get_tenant(tenant_id)
        entitlement_svc = EntitlementService(self.db)
        catalogo = entitlement_svc._get_catalog()
        efectivos = entitlement_svc.modulos(tenant_id)

        # Buscar overrides activos de esta empresa
        stmt = select(TenantModuleModel).where(
            TenantModuleModel.tenant_id == tenant_id,
            TenantModuleModel.revoked_at.is_(None),
        )
        active_overrides = {o.module_code: o for o in self.db.scalars(stmt).all()}

        result: list[TenantModuleOut] = []
        for code, info in catalogo.items():
            kind = info.get("kind", "ADDON")
            lifecycle = info.get("lifecycle", "GA")
            name = info.get("name", code)

            is_effective = code in efectivos
            efectivo_info = efectivos.get(code)
            origin = efectivo_info.origen if efectivo_info else "NONE"

            override = active_overrides.get(code)
            result.append(
                TenantModuleOut(
                    id=override.id if override else None,
                    module_code=code,
                    module_name=name,
                    kind=kind,
                    lifecycle=lifecycle,
                    effective=is_effective,
                    origin=origin,
                    mode=override.mode if override else None,
                    starts_at=override.starts_at if override else None,
                    expires_at=override.expires_at if override else (efectivo_info.expira if efectivo_info else None),
                    reason=override.reason if override else None,
                    is_blocked=(override.mode == "BLOQUEADO") if override else False,
                )
            )

        return result

    def habilitar(
        self,
        tenant_id: UUID,
        module_code: str,
        mode: str,
        days: int | None,
        reason: str,
    ) -> TenantModuleOut:
        tenant = self._get_tenant(tenant_id)
        mode_upper = mode.upper()
        if mode_upper not in (OverrideMode.EXTRA, OverrideMode.TRIAL, OverrideMode.BLOQUEADO):
            raise ValidationError(f"Modo inválido '{mode}'. Debe ser EXTRA, TRIAL o BLOQUEADO.")

        now = datetime.now(timezone.utc)
        entitlement_svc = EntitlementService(self.db)
        catalogo = entitlement_svc._get_catalog()
        if module_code not in catalogo:
            raise NotFoundError(f"Módulo '{module_code}' no existe en el catálogo.")

        mod_info = catalogo[module_code]
        if mod_info.get("kind") == "BASE" and mode_upper == OverrideMode.BLOQUEADO:
            raise ConflictError("El módulo base no puede ser bloqueado.")

        # Verificar dependencias si no es bloqueo
        if mode_upper != OverrideMode.BLOQUEADO:
            # Check dependencies from PlatformModuleModel if available
            db_mod = self.db.get(PlatformModuleModel, module_code)
            deps = db_mod.depends_on if db_mod and db_mod.depends_on else []
            for dep in deps:
                if not entitlement_svc.tiene(tenant_id, dep):
                    raise ConflictError(
                        f"No se puede habilitar el módulo porque requiere que esté activo el módulo dependiente '{dep}'."
                    )

        # Calcular expiración
        expires_at = None
        if mode_upper == OverrideMode.TRIAL:
            trial_days = days if days is not None else 7
            if trial_days < 1 or trial_days > 30:
                raise ValidationError("Una prueba (TRIAL) debe durar entre 1 y 30 días.")
            expires_at = now + timedelta(days=trial_days)
        elif days is not None and days > 0:
            expires_at = now + timedelta(days=days)

        # Revocar override anterior si existía
        prev_stmt = select(TenantModuleModel).where(
            TenantModuleModel.tenant_id == tenant_id,
            TenantModuleModel.module_code == module_code,
            TenantModuleModel.revoked_at.is_(None),
        )
        prev_overrides = self.db.scalars(prev_stmt).all()
        for po in prev_overrides:
            po.revoked_at = now
            po.revoked_by = self.actor.id
            po.revoke_reason = "Reemplazado por nuevo override"

        # Crear nuevo override
        new_ov = TenantModuleModel(
            tenant_id=tenant_id,
            module_code=module_code,
            mode=mode_upper,
            starts_at=now,
            expires_at=expires_at,
            reason=reason,
            granted_by=self.actor.id,
        )
        self.db.add(new_ov)
        self.db.flush()

        RecordAuditEvent(self.db).execute(
            actor_user_id=self.actor.id,
            action="platform.module_granted",
            entity_type="tenant_module",
            entity_id=str(new_ov.id),
            description=f"Módulo '{module_code}' otorgado a {tenant.trade_name} en modo {mode_upper}.",
            metadata={"tenant_id": str(tenant_id), "module_code": module_code, "mode": mode_upper, "reason": reason},
        )
        self.db.commit()

        # Invalida caché de permisos/entitlements
        self.db.info.pop(f"entitlements_{tenant_id}", None)

        items = self.listar(tenant_id)
        return next(i for i in items if i.module_code == module_code)

    def bloquear(self, tenant_id: UUID, module_code: str, reason: str) -> TenantModuleOut:
        return self.habilitar(tenant_id, module_code, mode=OverrideMode.BLOQUEADO, days=None, reason=reason)

    def revocar(self, override_id: UUID, reason: str) -> None:
        ov = self.db.get(TenantModuleModel, override_id)
        if not ov:
            raise NotFoundError("Asignación de módulo no encontrada.")
        if ov.revoked_at is not None:
            return

        now = datetime.now(timezone.utc)
        ov.revoked_at = now
        ov.revoked_by = self.actor.id
        ov.revoke_reason = reason
        self.db.flush()

        RecordAuditEvent(self.db).execute(
            actor_user_id=self.actor.id,
            action="platform.module_revoked",
            entity_type="tenant_module",
            entity_id=str(override_id),
            description=f"Asignación del módulo '{ov.module_code}' revocada.",
            metadata={"tenant_id": str(ov.tenant_id), "module_code": ov.module_code, "reason": reason},
        )
        self.db.commit()
        self.db.info.pop(f"entitlements_{ov.tenant_id}", None)

    def fijar_limite(
        self,
        tenant_id: UUID,
        limit_code: str,
        value: int,
        days: int | None,
        reason: str,
    ) -> TenantLimitOut:
        tenant = self._get_tenant(tenant_id)
        if value < 0:
            raise ValidationError("El valor del límite debe ser mayor o igual a cero.")

        # Si el límite es max_active_branches, verificar que no sea menor al uso actual
        if limit_code == "max_active_branches":
            repo = SaasRepository(self.db)
            uso_actual = repo.count_active_branches(tenant_id)
            if value < uso_actual:
                raise ConflictError(
                    f"El límite ({value}) no puede ser menor a las sucursales activas actuales ({uso_actual}).",
                    code="limit_below_usage",
                )

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=days) if days else None

        # Revocar límite activo anterior si existía
        prev_stmt = select(TenantLimitModel).where(
            TenantLimitModel.tenant_id == tenant_id,
            TenantLimitModel.limit_code == limit_code,
            TenantLimitModel.revoked_at.is_(None),
        )
        prev_limits = self.db.scalars(prev_stmt).all()
        for pl in prev_limits:
            pl.revoked_at = now

        limit = TenantLimitModel(
            tenant_id=tenant_id,
            limit_code=limit_code,
            value=value,
            expires_at=expires_at,
            reason=reason,
            granted_by=self.actor.id,
            created_at=now,
        )
        self.db.add(limit)
        self.db.flush()

        RecordAuditEvent(self.db).execute(
            actor_user_id=self.actor.id,
            action="platform.limit_granted",
            entity_type="tenant_limit",
            entity_id=str(limit.id),
            description=f"Límite '{limit_code}' fijado a {value} para {tenant.trade_name}.",
            metadata={"tenant_id": str(tenant_id), "limit_code": limit_code, "value": value, "reason": reason},
        )
        self.db.commit()

        return TenantLimitOut.model_validate(limit)

    def quitar_limite(self, limit_id: UUID, reason: str) -> None:
        limit = self.db.get(TenantLimitModel, limit_id)
        if not limit:
            raise NotFoundError("Límite no encontrado.")
        if limit.revoked_at is not None:
            return

        now = datetime.now(timezone.utc)
        limit.revoked_at = now
        self.db.flush()

        RecordAuditEvent(self.db).execute(
            actor_user_id=self.actor.id,
            action="platform.limit_revoked",
            entity_type="tenant_limit",
            entity_id=str(limit_id),
            description=f"Límite '{limit.limit_code}' revocado para la empresa.",
            metadata={"tenant_id": str(limit.tenant_id), "reason": reason},
        )
        self.db.commit()
