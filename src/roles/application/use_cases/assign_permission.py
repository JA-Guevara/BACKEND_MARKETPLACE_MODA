import uuid

from src.auth.infrastructure.persistence.models.user import UserModel
from src.roles.application.services.role_service import RoleService


class AssignPermissions:
    def __init__(self, service: RoleService) -> None:
        self.service = service

    def execute(self, role_id: uuid.UUID, permission_ids: list[uuid.UUID], actor: UserModel):
        return self.service.set_permissions(role_id, permission_ids, actor)
