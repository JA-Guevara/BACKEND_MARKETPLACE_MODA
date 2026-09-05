import uuid

from src.usuarios.application.services.user_service import UserService


class GetUsuario:
    def __init__(self, service: UserService) -> None:
        self.service = service

    def execute(self, user_id: uuid.UUID, *, include_deleted: bool = False):
        return self.service.get(user_id, include_deleted=include_deleted)
