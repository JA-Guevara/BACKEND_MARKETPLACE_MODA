import uuid

from src.auth.infrastructure.persistence.models.user import UserModel
from src.usuarios.application.services.user_service import UserService
from src.usuarios.infrastructure.http.schemas import UserUpdate


class UpdateUsuario:
    def __init__(self, service: UserService) -> None:
        self.service = service

    def execute(self, user_id: uuid.UUID, data: UserUpdate, actor: UserModel):
        return self.service.update(user_id, data, actor)
