import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.web.dependencies import get_current_user
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_permissions
from src.shared.responses.api_response import ApiResponse
from src.shared.responses.pagination import Page
from src.usuarios.application.services.user_service import UserService
from src.usuarios.infrastructure.http.schemas import (
    AddressCreate,
    AddressResponse,
    AddressUpdate,
    AssignRolesRequest,
    UserCreate,
    UserResponse,
    UserUpdate,
)


router = APIRouter(prefix="/users", tags=['PAQ-01 · Usuarios y catálogo'])
UserReader = Annotated[UserModel, Depends(require_permissions("users.read"))]
UserWriter = Annotated[UserModel, Depends(require_permissions("users.write"))]


@router.get("", response_model=ApiResponse[Page[UserResponse]])
def list_users(
    actor: UserReader,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = None,
    is_active: bool | None = None,
    role_code: str | None = None,
    include_deleted: bool = False,
):
    result = UserService(db).list(
        page=page,
        page_size=page_size,
        search=search,
        is_active=is_active,
        role_code=role_code,
        include_deleted=include_deleted,
    )
    return ApiResponse(message="Usuarios obtenidos.", data=result)


@router.post("", response_model=ApiResponse[UserResponse], status_code=status.HTTP_201_CREATED)
def create_user(data: UserCreate, actor: UserWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Usuario creado.", data=UserService(db).create(data, actor))


@router.get("/{user_id}", response_model=ApiResponse[UserResponse])
def get_user(user_id: uuid.UUID, actor: UserReader, db: Session = Depends(get_db)):
    return ApiResponse(message="Usuario obtenido.", data=UserService(db).get(user_id, include_deleted=True))


@router.patch("/{user_id}", response_model=ApiResponse[UserResponse])
def update_user(user_id: uuid.UUID, data: UserUpdate, actor: UserWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Usuario actualizado.", data=UserService(db).update(user_id, data, actor))


@router.put("/{user_id}/roles", response_model=ApiResponse[UserResponse])
def set_roles(user_id: uuid.UUID, data: AssignRolesRequest, actor: UserWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Roles actualizados.", data=UserService(db).set_roles(user_id, data.role_ids, actor))


@router.post("/{user_id}/deactivate", response_model=ApiResponse[UserResponse])
def deactivate(user_id: uuid.UUID, actor: UserWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Usuario desactivado.", data=UserService(db).deactivate(user_id, actor))


@router.post("/{user_id}/activate", response_model=ApiResponse[UserResponse])
def activate(user_id: uuid.UUID, actor: UserWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Usuario activado.", data=UserService(db).activate(user_id, actor))


@router.post("/{user_id}/unlock", response_model=ApiResponse[UserResponse])
def unlock(user_id: uuid.UUID, actor: UserWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Usuario desbloqueado.", data=UserService(db).unlock(user_id, actor))


@router.delete("/{user_id}", response_model=ApiResponse[None])
def delete_user(user_id: uuid.UUID, actor: UserWriter, db: Session = Depends(get_db)):
    UserService(db).delete(user_id, actor)
    return ApiResponse(message="Usuario eliminado.")


@router.post("/{user_id}/restore", response_model=ApiResponse[UserResponse])
def restore_user(user_id: uuid.UUID, actor: UserWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Usuario restaurado.", data=UserService(db).restore(user_id, actor))


@router.get("/me/addresses", response_model=ApiResponse[list[AddressResponse]])
def my_addresses(user: UserModel = Depends(get_current_user), db: Session = Depends(get_db)):
    return ApiResponse(message="Direcciones obtenidas.", data=UserService(db).list_addresses(user.id))


@router.post("/me/addresses", response_model=ApiResponse[AddressResponse], status_code=status.HTTP_201_CREATED)
def add_my_address(data: AddressCreate, user: UserModel = Depends(get_current_user), db: Session = Depends(get_db)):
    return ApiResponse(message="Direccion creada.", data=UserService(db).add_address(user.id, data, user))


@router.patch("/me/addresses/{address_id}", response_model=ApiResponse[AddressResponse])
def update_my_address(address_id: uuid.UUID, data: AddressUpdate, user: UserModel = Depends(get_current_user), db: Session = Depends(get_db)):
    return ApiResponse(message="Direccion actualizada.", data=UserService(db).update_address(user.id, address_id, data, user))


@router.delete("/me/addresses/{address_id}", response_model=ApiResponse[None])
def delete_my_address(address_id: uuid.UUID, user: UserModel = Depends(get_current_user), db: Session = Depends(get_db)):
    UserService(db).delete_address(user.id, address_id, user)
    return ApiResponse(message="Direccion eliminada.")

