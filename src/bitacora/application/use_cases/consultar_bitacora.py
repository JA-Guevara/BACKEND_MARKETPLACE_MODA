from src.bitacora.infrastructure.persistence.repositories.bitacora_repository import AuditRepository


class QueryAuditLog:
    def __init__(self, repository: AuditRepository) -> None:
        self.repository = repository

    def execute(self, **filters):
        return self.repository.list(**filters)
