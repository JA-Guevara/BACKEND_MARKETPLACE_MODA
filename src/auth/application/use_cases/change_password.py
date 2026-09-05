from src.auth.application.services.auth_service import AuthService
from src.auth.infrastructure.persistence.models.user import UserModel


class ChangePassword:
    def __init__(self, service: AuthService) -> None:
        self.service = service

    def execute(self, user: UserModel, current_password: str, new_password: str) -> None:
        self.service.change_password(user, current_password, new_password)
