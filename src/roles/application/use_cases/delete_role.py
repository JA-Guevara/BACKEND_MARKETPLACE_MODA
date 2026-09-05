import uuid

from src.auth.infrastructure.persistence.models.user import UserModel
from src.roles.application.services.role_service import RoleService


class DeleteRole:
    def __init__(self, service: RoleService) -> None:
        self.service = service

    def execute(self, role_id: uuid.UUID, actor: UserModel) -> None:
        self.service.delete_role(role_id, actor)
