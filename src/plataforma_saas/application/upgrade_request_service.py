"""Servicio de solicitudes de ampliación de plan, límites y módulos (RS-3)."""
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.plataforma_saas.domain.exceptions import UpgradeRequestOpenError
from src.plataforma_saas.infrastructure.models.storefront import UpgradeRequestModel
from src.plataforma_saas.web.schemas.storefront import UpgradeRequestIn, UpgradeRequestOut
from src.shared.exceptions.domain_exception import NotFoundError


class UpgradeRequestService:
    def __init__(self, db: Session):
        self.db = db

    def crear(
        self, tenant_id: UUID, actor: UserModel, data: UpgradeRequestIn
    ) -> UpgradeRequestOut:
        # Verificar si ya existe una abierta del mismo tipo
        existente = self.db.scalar(
            select(UpgradeRequestModel).where(
                UpgradeRequestModel.tenant_id == tenant_id,
                UpgradeRequestModel.kind == data.kind,
                UpgradeRequestModel.status == "ABIERTA",
            )
        )
        if existente:
            raise UpgradeRequestOpenError("Ya tienes una solicitud de ampliación abierta de este tipo.")

        req = UpgradeRequestModel(
            tenant_id=tenant_id,
            requested_by=actor.id,
            kind=data.kind,
            target=data.target,
            message=data.message,
            status="ABIERTA",
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(req)
        self.db.flush()

        RecordAuditEvent(self.db).execute(
            actor_user_id=actor.id,
            action="tenant.upgrade_requested",
            entity_type="upgrade_request",
            entity_id=str(req.id),
            description=f"Solicitud de ampliación ({data.kind}: {data.target}) registrada.",
            metadata={"kind": data.kind, "target": data.target},
        )

        self.db.commit()
        return UpgradeRequestOut.model_validate(req)

    def listar_plataforma(self, status: str | None = None) -> list[UpgradeRequestOut]:
        query = select(UpgradeRequestModel)
        if status:
            query = query.where(UpgradeRequestModel.status == status)
        items = self.db.scalars(query.order_by(UpgradeRequestModel.created_at.desc())).all()
        return [UpgradeRequestOut.model_validate(x) for x in items]

    def listar_tenant(self, tenant_id: UUID) -> list[UpgradeRequestOut]:
        items = self.db.scalars(
            select(UpgradeRequestModel)
            .where(UpgradeRequestModel.tenant_id == tenant_id)
            .order_by(UpgradeRequestModel.created_at.desc())
        ).all()
        return [UpgradeRequestOut.model_validate(x) for x in items]

    def atender(self, req_id: UUID | str, actor: UserModel, response_msg: str) -> UpgradeRequestOut:
        req = self.db.get(UpgradeRequestModel, UUID(str(req_id)))
        if req is None:
            raise NotFoundError("Solicitud de ampliación no encontrada.")

        req.status = "ATENDIDA"
        req.handled_by = actor.id
        req.handled_at = datetime.now(timezone.utc)
        req.response = response_msg

        RecordAuditEvent(self.db).execute(
            actor_user_id=actor.id,
            action="platform.upgrade_request_handled",
            entity_type="upgrade_request",
            entity_id=str(req.id),
            description=f"Solicitud de ampliación {req.id} atendida.",
            metadata={"response": response_msg},
        )

        self.db.commit()
        return UpgradeRequestOut.model_validate(req)

    def rechazar(self, req_id: UUID, actor: UserModel, response_msg: str) -> UpgradeRequestOut:
        req = self.db.get(UpgradeRequestModel, req_id)
        if req is None:
            raise NotFoundError("Solicitud de ampliación no encontrada.")

        req.status = "RECHAZADA"
        req.handled_by = actor.id
        req.handled_at = datetime.now(timezone.utc)
        req.response = response_msg

        RecordAuditEvent(self.db).execute(
            actor_user_id=actor.id,
            action="platform.upgrade_request_rejected",
            entity_type="upgrade_request",
            entity_id=str(req.id),
            description=f"Solicitud de ampliación {req.id} rechazada.",
            metadata={"response": response_msg},
        )

        self.db.commit()
        return UpgradeRequestOut.model_validate(req)
