import math
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.auth.infrastructure.http.schemas import TenantSummary
from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.infrastructure.security.jwt_service import JWTService
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.infrastructure.security.access_context import tenant_scope_permissions
from src.plataforma_saas.application.plan_guard import PlanGuard
from src.plataforma_saas.domain.exceptions import (
    SupportLimitExceededError,
    SupportReasonInvalidError,
    SupportRejectedError,
    SupportRequestExpiredError,
    SupportSessionExpiredError,
    TenantInactiveError,
    TenantNotFoundError,
)
from src.plataforma_saas.infrastructure.models.support_session import SupportSessionModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.plataforma_saas.web.schemas.support import (
    SupportSessionResponse,
    SupportSessionStart,
)
from src.shared.exceptions.domain_exception import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from src.shared.responses.pagination import Page


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class SupportService:
    def __init__(self, db: Session, actor: UserModel) -> None:
        self.db = db
        self.actor = actor
        self.audit = RecordAuditEvent(db)

    def iniciar(
        self,
        tenant_id: uuid.UUID,
        reason: str,
        duration_minutes: int,
        mode: str = "WRITE",
        landing_module: str | None = None,
        ip: str | None = None,
        ua: str | None = None,
        require_consent: bool = True,
    ) -> SupportSessionStart:
        tenant = self.db.get(TenantModel, tenant_id)
        if not tenant:
            raise TenantNotFoundError()
        if tenant.status != "ACTIVA":
            raise TenantInactiveError()

        clean_reason = reason.strip()
        if len(clean_reason) < 10 or len(clean_reason) > 300:
            raise SupportReasonInvalidError("El motivo debe tener entre 10 y 300 caracteres.")

        now = datetime.now(timezone.utc)

        # Cierra cualquier otra sesión activa del mismo actor
        active_sessions = self.db.scalars(
            select(SupportSessionModel).where(
                SupportSessionModel.platform_user_id == self.actor.id,
                SupportSessionModel.ended_at.is_(None),
            )
        ).all()
        for s in active_sessions:
            if s.is_active(now):
                s.ended_at = now
                s.end_reason = "revoked"

        # PX0.2: Regla de consentimiento
        # si support_access_mode = require_approval o alcance ≠ solo lectura:
        # crea status=pending_approval, request_expires_at = ahora + 10 min
        # allow_read_only solo exime al alcance de solo lectura
        policy_mode = getattr(tenant, "support_access_mode", "require_approval")
        requires_approval = require_consent and (
            (policy_mode == "require_approval") or (mode != "READ_ONLY")
        )

        if requires_approval:
            status = "pending_approval"
            request_expires_at = now + timedelta(minutes=10)
            expires_at = now + timedelta(minutes=duration_minutes)
        else:
            status = "active"
            request_expires_at = None
            expires_at = now + timedelta(minutes=duration_minutes)

        session = SupportSessionModel(
            tenant_id=tenant_id,
            platform_user_id=self.actor.id,
            reason=clean_reason,
            duration_minutes=duration_minutes,
            mode=mode,
            landing_module=landing_module,
            started_at=now,
            expires_at=expires_at,
            ip_address=ip,
            user_agent=ua,
            status=status,
            request_expires_at=request_expires_at,
            is_emergency=False,
        )
        self.db.add(session)
        self.db.flush()

        action = "support.request_created" if requires_approval else "support.session_started"
        desc = (
            f"Solicitud de acceso de soporte enviada para {tenant.legal_name} (modo {mode})."
            if requires_approval
            else f"Sesión de soporte iniciada para {tenant.legal_name} (modo {mode})."
        )
        audit_event = self.audit.execute(
            actor_user_id=self.actor.id,
            action=action,
            entity_type="support_session",
            entity_id=str(session.id),
            description=desc,
            tenant_id=tenant_id,
            ip_address=ip,
            user_agent=ua,
        )
        audit_event.support_session_id = session.id
        self.db.commit()

        tenant_summary = TenantSummary.model_validate(tenant)
        sub_summary = PlanGuard(self.db).resumen(tenant_id)
        session_resp = self._to_response(session, actions_count=1)

        # Regla PX0.2: El token de soporte (RFC 8693) solo se emite para sesiones aprobadas o de emergencia
        # Una solicitud pendiente nunca da acceso
        if requires_approval:
            return SupportSessionStart(
                session=session_resp,
                access_token=None,
                token_type="bearer",
                expires_in=0,
                tenant=tenant_summary,
                subscription=sub_summary,
                permissions=[],
            )

        is_ro = (mode == "READ_ONLY")
        token, expires_in = JWTService().create_support_token(
            str(self.actor.id), str(tenant_id), str(session.id), expires_at, read_only=is_ro
        )
        permissions = sorted(list(tenant_scope_permissions(self.db)))

        return SupportSessionStart(
            session=session_resp,
            access_token=token,
            token_type="bearer",
            expires_in=expires_in,
            tenant=tenant_summary,
            subscription=sub_summary,
            permissions=permissions,
        )

    def pasar_a_escritura(
        self, session_id: uuid.UUID, reason: str, ip: str | None = None, ua: str | None = None
    ) -> SupportSessionStart:
        session = self.db.get(SupportSessionModel, session_id)
        if not session:
            raise NotFoundError("Sesión de soporte no encontrada.")
        if session.platform_user_id != self.actor.id:
            raise AuthorizationError("Solo el administrador que inició la sesión puede modificarla.")

        now = datetime.now(timezone.utc)
        if not session.is_active(now):
            raise SupportSessionExpiredError("La sesión de soporte ya ha expirado o finalizado.")

        session.ended_at = now
        session.end_reason = "upgraded"
        self.db.flush()

        return self.iniciar(
            tenant_id=session.tenant_id,
            reason=reason or f"Elevación a escritura desde sesión previa: {session.reason}",
            duration_minutes=session.duration_minutes,
            mode="WRITE",
            landing_module=session.landing_module,
            ip=ip,
            ua=ua,
        )

    def extender(self, session_id: uuid.UUID, minutes: int = 30) -> SupportSessionStart:
        session = self.db.get(SupportSessionModel, session_id)
        if not session:
            raise NotFoundError("Sesión de soporte no encontrada.")
        if session.platform_user_id != self.actor.id:
            raise AuthorizationError("Solo el administrador que inició la sesión puede extenderla.")

        now = datetime.now(timezone.utc)
        if not session.is_active(now):
            raise SupportSessionExpiredError("La sesión de soporte ya ha expirado o finalizado.")

        if session.duration_minutes + minutes > 240:
            raise SupportLimitExceededError("El tiempo total de la sesión no puede superar los 240 minutos.")

        session.duration_minutes += minutes
        session.expires_at = session.expires_at + timedelta(minutes=minutes)

        is_ro = (getattr(session, "mode", "WRITE") == "READ_ONLY")
        token, expires_in = JWTService().create_support_token(
            str(self.actor.id), str(session.tenant_id), str(session.id), session.expires_at, read_only=is_ro
        )

        audit_event = self.audit.execute(
            actor_user_id=self.actor.id,
            action="support.session_extended",
            entity_type="support_session",
            entity_id=str(session.id),
            description=f"Sesión de soporte extendida por {minutes} minutos.",
            tenant_id=session.tenant_id,
        )
        audit_event.support_session_id = session.id
        self.db.commit()

        tenant = self.db.get(TenantModel, session.tenant_id)
        tenant_summary = TenantSummary.model_validate(tenant) if tenant else None
        sub_summary = PlanGuard(self.db).resumen(session.tenant_id)
        permissions = sorted(list(tenant_scope_permissions(self.db)))

        session_resp = self._to_response(session)
        return SupportSessionStart(
            session=session_resp,
            access_token=token,
            token_type="bearer",
            expires_in=expires_in,
            tenant=tenant_summary,
            subscription=sub_summary,
            permissions=permissions,
        )

    def finalizar(self, session_id: uuid.UUID, reason: str = "manual") -> SupportSessionResponse:
        session = self.db.get(SupportSessionModel, session_id)
        if not session:
            raise NotFoundError("Sesión de soporte no encontrada.")
        if session.platform_user_id != self.actor.id:
            raise AuthorizationError("Solo el administrador que inició la sesión puede finalizarla.")

        now = datetime.now(timezone.utc)
        if session.ended_at is None:
            session.ended_at = now
            session.end_reason = reason

            audit_event = self.audit.execute(
                actor_user_id=self.actor.id,
                action="support.session_ended",
                entity_type="support_session",
                entity_id=str(session.id),
                description="Sesión de soporte finalizada manualmente.",
                tenant_id=session.tenant_id,
            )
            audit_event.support_session_id = session.id
            self.db.commit()

        return self._to_response(session)

    terminar = finalizar

    def revocar(self, session_id: uuid.UUID) -> SupportSessionResponse:
        session = self.db.get(SupportSessionModel, session_id)
        if not session:
            raise NotFoundError("Sesión de soporte no encontrada.")

        now = datetime.now(timezone.utc)
        if session.ended_at is None:
            session.ended_at = now
            session.end_reason = "revoked"

            audit_event = self.audit.execute(
                actor_user_id=self.actor.id,
                action="support.session_revoked",
                entity_type="support_session",
                entity_id=str(session.id),
                description="Sesión de soporte revocada.",
                tenant_id=session.tenant_id,
            )
            audit_event.support_session_id = session.id
            self.db.commit()

        return self._to_response(session)

    def listar(
        self,
        tenant_id: uuid.UUID | None = None,
        platform_user_id: uuid.UUID | None = None,
        active: bool | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Page[SupportSessionResponse]:
        now = datetime.now(timezone.utc)
        stmt = select(SupportSessionModel)
        count_stmt = select(func.count(SupportSessionModel.id))

        if tenant_id:
            stmt = stmt.where(SupportSessionModel.tenant_id == tenant_id)
            count_stmt = count_stmt.where(SupportSessionModel.tenant_id == tenant_id)
        if platform_user_id:
            stmt = stmt.where(SupportSessionModel.platform_user_id == platform_user_id)
            count_stmt = count_stmt.where(SupportSessionModel.platform_user_id == platform_user_id)
        if active is True:
            stmt = stmt.where(SupportSessionModel.ended_at.is_(None), SupportSessionModel.expires_at > now)
            count_stmt = count_stmt.where(SupportSessionModel.ended_at.is_(None), SupportSessionModel.expires_at > now)
        elif active is False:
            stmt = stmt.where(
                (SupportSessionModel.ended_at.is_not(None)) | (SupportSessionModel.expires_at <= now)
            )
            count_stmt = count_stmt.where(
                (SupportSessionModel.ended_at.is_not(None)) | (SupportSessionModel.expires_at <= now)
            )

        total = self.db.scalar(count_stmt) or 0
        pages = math.ceil(total / page_size) if total else 0

        stmt = stmt.order_by(SupportSessionModel.started_at.desc()).offset((page - 1) * page_size).limit(page_size)
        sessions = self.db.scalars(stmt).all()
        items = [self._to_response(s) for s in sessions]

        return Page(items=items, total=total, page=page, page_size=page_size, pages=pages)

    def _to_response(
        self, session: SupportSessionModel, actions_count: int | None = None
    ) -> SupportSessionResponse:
        tenant = self.db.get(TenantModel, session.tenant_id)
        tenant_name = (tenant.trade_name or tenant.legal_name) if tenant else "Empresa"
        user = self.db.get(UserModel, session.platform_user_id)
        platform_user_name = f"{user.first_name} {user.last_name}".strip() if user else "Super Administrador"

        if actions_count is None:
            actions_count = (
                self.db.scalar(
                    select(func.count(AuditEventModel.id)).where(
                        AuditEventModel.support_session_id == session.id
                    )
                )
                or 0
            )

        now = datetime.now(timezone.utc)
        return SupportSessionResponse(
            id=session.id,
            tenant_id=session.tenant_id,
            tenant_name=tenant_name,
            platform_user_id=session.platform_user_id,
            platform_user_name=platform_user_name,
            reason=session.reason,
            duration_minutes=session.duration_minutes,
            mode=getattr(session, "mode", "WRITE"),
            landing_module=getattr(session, "landing_module", None),
            started_at=session.started_at,
            expires_at=session.expires_at,
            ended_at=session.ended_at,
            end_reason=session.end_reason,
            actions_count=actions_count,
            is_active=session.is_active(now),
            status=getattr(session, "status", "active"),
            approved_by_user_id=getattr(session, "approved_by_user_id", None),
            approved_at=getattr(session, "approved_at", None),
            decision_reason=getattr(session, "decision_reason", None),
            request_expires_at=getattr(session, "request_expires_at", None),
            is_emergency=getattr(session, "is_emergency", False),
        )

    def obtener(self, session_id: uuid.UUID) -> SupportSessionResponse:
        session = self.db.get(SupportSessionModel, session_id)
        if not session:
            raise NotFoundError("Sesión de soporte no encontrada.")
        now = datetime.now(timezone.utc)
        if (
            getattr(session, "status", None) == "pending_approval"
            and session.request_expires_at
            and _as_utc(session.request_expires_at) < now
        ):
            session.status = "request_expired"
            self.db.commit()
        return self._to_response(session)

    def entrar(self, session_id: uuid.UUID) -> SupportSessionStart:
        session = self.db.get(SupportSessionModel, session_id)
        if not session:
            raise NotFoundError("Sesión de soporte no encontrada.")
        if session.platform_user_id != self.actor.id:
            raise AuthorizationError("Solo el administrador que solicitó el acceso puede ingresar a la sesión.")

        now = datetime.now(timezone.utc)
        status = getattr(session, "status", "active")
        if status == "pending_approval":
            if session.request_expires_at and _as_utc(session.request_expires_at) < now:
                session.status = "request_expired"
                self.db.commit()
                raise SupportRequestExpiredError("La solicitud de soporte expiró sin respuesta.")
            raise ConflictError("La solicitud aún espera la aprobación de la empresa.")

        if status == "rejected":
            raise SupportRejectedError(f"La empresa rechazó la solicitud: {session.decision_reason or 'Sin motivo'}")

        if status == "request_expired":
            raise SupportRequestExpiredError("La solicitud de soporte expiró.")

        if not session.is_active(now):
            raise SupportSessionExpiredError("La sesión de soporte ya ha expirado o finalizado.")

        is_ro = (session.mode == "READ_ONLY")
        token, expires_in = JWTService().create_support_token(
            str(self.actor.id), str(session.tenant_id), str(session.id), session.expires_at, read_only=is_ro
        )
        permissions = sorted(list(tenant_scope_permissions(self.db)))
        tenant = self.db.get(TenantModel, session.tenant_id)
        tenant_summary = TenantSummary.model_validate(tenant) if tenant else None
        sub_summary = PlanGuard(self.db).resumen(session.tenant_id)
        session_resp = self._to_response(session)

        return SupportSessionStart(
            session=session_resp,
            access_token=token,
            token_type="bearer",
            expires_in=expires_in,
            tenant=tenant_summary,
            subscription=sub_summary,
            permissions=permissions,
        )

    def aprobar(
        self, session_id: uuid.UUID, actor_empresa: UserModel, minutes: int = 30
    ) -> SupportSessionResponse:
        session = self.db.get(SupportSessionModel, session_id)
        if not session:
            raise NotFoundError("Solicitud de soporte no encontrada.")

        # Solo la empresa dueña (RN03)
        if str(session.tenant_id) != str(actor_empresa.tenant_id):
            raise AuthorizationError("No tiene permiso para aprobar solicitudes de otra empresa.")

        now = datetime.now(timezone.utc)
        if session.request_expires_at and _as_utc(session.request_expires_at) < now:
            session.status = "request_expired"
            self.db.commit()
            raise SupportRequestExpiredError("La solicitud de soporte expiró tras 10 minutos.")

        if session.status != "pending_approval":
            raise ConflictError(f"La solicitud ya no está pendiente (estado actual: {session.status}).")

        session.status = "approved"
        session.approved_by_user_id = actor_empresa.id
        session.approved_at = now
        session.duration_minutes = minutes
        session.started_at = now
        session.expires_at = now + timedelta(minutes=minutes)

        self.audit.execute(
            actor_user_id=actor_empresa.id,
            action="support.approved",
            entity_type="support_session",
            entity_id=str(session.id),
            description=f"Acceso de soporte aprobado por {minutes} minutos.",
            tenant_id=session.tenant_id,
        )
        self.db.commit()
        return self._to_response(session)

    def rechazar(
        self, session_id: uuid.UUID, actor_empresa: UserModel, reason: str
    ) -> SupportSessionResponse:
        session = self.db.get(SupportSessionModel, session_id)
        if not session:
            raise NotFoundError("Solicitud de soporte no encontrada.")

        # Solo la empresa dueña (RN03)
        if str(session.tenant_id) != str(actor_empresa.tenant_id):
            raise AuthorizationError("No tiene permiso para rechazar solicitudes de otra empresa.")

        now = datetime.now(timezone.utc)
        if session.status != "pending_approval":
            raise ConflictError(f"La solicitud ya no está pendiente (estado actual: {session.status}).")

        session.status = "rejected"
        session.decision_reason = reason.strip()
        session.ended_at = now
        session.end_reason = "rejected"

        self.audit.execute(
            actor_user_id=actor_empresa.id,
            action="support.rejected",
            entity_type="support_session",
            entity_id=str(session.id),
            description=f"Acceso de soporte rechazado: {reason.strip()}",
            tenant_id=session.tenant_id,
        )
        self.db.commit()
        return self._to_response(session)

    def emergencia(
        self,
        tenant_id: uuid.UUID,
        reason: str,
        minutes: int = 30,
        landing_module: str | None = None,
        ip: str | None = None,
        ua: str | None = None,
    ) -> SupportSessionStart:
        tenant = self.db.get(TenantModel, tenant_id)
        if not tenant:
            raise TenantNotFoundError()
        if tenant.status != "ACTIVA":
            raise TenantInactiveError()

        clean_reason = reason.strip()
        if len(clean_reason) < 20:
            raise SupportReasonInvalidError("El motivo de emergencia debe tener al menos 20 caracteres.")
        if minutes > 30:
            raise SupportLimitExceededError("El acceso de emergencia no puede superar los 30 minutos.")

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=minutes)

        session = SupportSessionModel(
            tenant_id=tenant_id,
            platform_user_id=self.actor.id,
            reason=clean_reason,
            duration_minutes=minutes,
            mode="WRITE",
            landing_module=landing_module,
            started_at=now,
            expires_at=expires_at,
            ip_address=ip,
            user_agent=ua,
            status="active",
            is_emergency=True,
        )
        self.db.add(session)
        self.db.flush()

        token, expires_in = JWTService().create_support_token(
            str(self.actor.id), str(tenant_id), str(session.id), expires_at, read_only=False
        )

        audit_event = self.audit.execute(
            actor_user_id=self.actor.id,
            action="support.emergency",
            entity_type="support_session",
            entity_id=str(session.id),
            description=f"Acceso de emergencia iniciado para {tenant.legal_name}: {clean_reason}",
            tenant_id=tenant_id,
            ip_address=ip,
            user_agent=ua,
        )
        audit_event.support_session_id = session.id
        self.db.commit()

        permissions = sorted(list(tenant_scope_permissions(self.db)))
        tenant_summary = TenantSummary.model_validate(tenant)
        sub_summary = PlanGuard(self.db).resumen(tenant_id)
        session_resp = self._to_response(session, actions_count=1)

        return SupportSessionStart(
            session=session_resp,
            access_token=token,
            token_type="bearer",
            expires_in=expires_in,
            tenant=tenant_summary,
            subscription=sub_summary,
            permissions=permissions,
        )

    def actualizar_politica(self, tenant_id: uuid.UUID, mode: str) -> dict:
        tenant = self.db.get(TenantModel, tenant_id)
        if not tenant:
            raise TenantNotFoundError()
        if mode not in ("require_approval", "allow_read_only"):
            raise ValidationError("Modo de política inválido. Debe ser 'require_approval' o 'allow_read_only'.")
        tenant.support_access_mode = mode
        self.db.commit()
        return {"support_access_mode": mode}

    def obtener_politica(self, tenant_id: uuid.UUID) -> dict:
        tenant = self.db.get(TenantModel, tenant_id)
        if not tenant:
            raise TenantNotFoundError()
        return {"support_access_mode": getattr(tenant, "support_access_mode", "require_approval")}
