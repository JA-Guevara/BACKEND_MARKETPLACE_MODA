import uuid

from sqlalchemy.orm import Session

from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.bitacora.infrastructure.persistence.repositories.bitacora_repository import AuditRepository


class RecordAuditEvent:
    def __init__(self, db: Session) -> None:
        self.repository = AuditRepository(db)

    def execute(
        self,
        *,
        action: str,
        entity_type: str,
        description: str,
        actor_user_id: uuid.UUID | None = None,
        entity_id: str | None = None,
        metadata: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditEventModel:
        return self.repository.record(
            AuditEventModel(
                actor_user_id=actor_user_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                description=description,
                metadata_=metadata,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
