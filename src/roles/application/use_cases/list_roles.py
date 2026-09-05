from src.roles.infrastructure.persistence.repositories.role_repository import RoleRepository


class ListRoles:
    def __init__(self, repository: RoleRepository) -> None:
        self.repository = repository

    def execute(self, *, include_inactive: bool = False):
        return self.repository.list_roles(include_inactive)
