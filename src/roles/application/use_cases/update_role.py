import uuid

from src.auth.infrastructure.persistence.models.user import UserModel
from src.roles.application.services.role_service import RoleService
from src.roles.infrastructure.http.schemas import RoleUpdate


class UpdateRole:
    def __init__(self, service: RoleService) -> None:
        self.service = service

    def execute(self, role_id: uuid.UUID, data: RoleUpdate, actor: UserModel):
        return self.service.update_role(role_id, data, actor)
