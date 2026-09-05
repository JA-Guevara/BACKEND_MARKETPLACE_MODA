from src.auth.infrastructure.persistence.models.user import UserModel
from src.roles.application.services.role_service import RoleService
from src.roles.infrastructure.http.schemas import RoleCreate


class CreateRole:
    def __init__(self, service: RoleService) -> None:
        self.service = service

    def execute(self, data: RoleCreate, actor: UserModel):
        return self.service.create_role(data, actor)
