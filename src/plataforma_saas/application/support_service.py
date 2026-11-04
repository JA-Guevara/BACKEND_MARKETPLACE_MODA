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
from src.shared.exceptions.domain_exception import AuthorizationError, NotFoundError
from src.shared.responses.pagination import Page


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
        ip: str | None = None,
        ua: str | None = None,
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

        expires_at = now + timedelta(minutes=duration_minutes)
        session = SupportSessionModel(
            tenant_id=tenant_id,
            platform_user_id=self.actor.id,
            reason=clean_reason,
            duration_minutes=duration_minutes,
            started_at=now,
            expires_at=expires_at,
            ip_address=ip,
            user_agent=ua,
        )
        self.db.add(session)
        self.db.flush()

        token, expires_in = JWTService().create_support_token(
            str(self.actor.id), str(tenant_id), str(session.id), expires_at
        )

        audit_event = self.audit.execute(
            actor_user_id=self.actor.id,
            action="support.session_started",
            entity_type="support_session",
            entity_id=str(session.id),
            description=f"Sesión de soporte iniciada para {tenant.legal_name}.",
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

        token, expires_in = JWTService().create_support_token(
            str(self.actor.id), str(session.tenant_id), str(session.id), session.expires_at
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
        sub_summary = PlanGuard(self.db).resumen(session.tenant_id) if tenant else None
        permissions = sorted(list(tenant_scope_permissions(self.db)))

        return SupportSessionStart(
            session=self._to_response(session),
            access_token=token,
            token_type="bearer",
            expires_in=expires_in,
            tenant=tenant_summary,
            subscription=sub_summary,
            permissions=permissions,
        )

    def terminar(self, session_id: uuid.UUID, reason: str = "manual") -> SupportSessionResponse:
        session = self.db.get(SupportSessionModel, session_id)
        if not session:
            raise NotFoundError("Sesión de soporte no encontrada.")

        now = datetime.now(timezone.utc)
        if session.ended_at is None:
            session.ended_at = now
            session.end_reason = reason
            audit_event = self.audit.execute(
                actor_user_id=self.actor.id,
                action="support.session_ended",
                entity_type="support_session",
                entity_id=str(session.id),
                description="Sesión de soporte finalizada.",
                tenant_id=session.tenant_id,
            )
            audit_event.support_session_id = session.id
            self.db.commit()

        return self._to_response(session)

    def listar(
        self,
        *,
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
            started_at=session.started_at,
            expires_at=session.expires_at,
            ended_at=session.ended_at,
            end_reason=session.end_reason,
            actions_count=actions_count,
            is_active=session.is_active(now),
        )
