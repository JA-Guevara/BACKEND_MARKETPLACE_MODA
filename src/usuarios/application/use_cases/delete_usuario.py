import uuid

from src.auth.infrastructure.persistence.models.user import UserModel
from src.usuarios.application.services.user_service import UserService


class DeleteUsuario:
    def __init__(self, service: UserService) -> None:
        self.service = service

    def execute(self, user_id: uuid.UUID, actor: UserModel) -> None:
        self.service.delete(user_id, actor)
