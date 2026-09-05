import uuid

from src.auth.infrastructure.persistence.repositories.user_repository import UserRepository
from src.shared.exceptions.domain_exception import NotFoundError


class GetCurrentUser:
    def __init__(self, repository: UserRepository) -> None:
        self.repository = repository

    def execute(self, user_id: uuid.UUID):
        user = self.repository.get_by_id(user_id)
        if not user:
            raise NotFoundError("Usuario no encontrado.")
        return user
