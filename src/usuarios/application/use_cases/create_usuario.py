from src.auth.infrastructure.persistence.models.user import UserModel
from src.usuarios.application.services.user_service import UserService
from src.usuarios.infrastructure.http.schemas import UserCreate


class CreateUsuario:
    def __init__(self, service: UserService) -> None:
        self.service = service

    def execute(self, data: UserCreate, actor: UserModel):
        return self.service.create(data, actor)
