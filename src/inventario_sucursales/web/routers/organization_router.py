import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_permissions
from src.inventario_sucursales.application.services.organization_service import OrganizationService
from src.inventario_sucursales.infrastructure.repositories.organization_repository import OrganizationRepository
from src.inventario_sucursales.web.schemas.organization import BranchCreate, BranchResponse, BranchUpdate, CashPointCreate, CashPointResponse, CashPointUpdate, CityCreate, CityResponse, CityUpdate, SupplierCreate, SupplierResponse, SupplierUpdate
from src.shared.responses.api_response import ApiResponse


router = APIRouter(tags=['PAQ-02 · Inventario y sucursales'])
BranchReader = Annotated[UserModel, Depends(require_permissions("branches.read"))]
BranchWriter = Annotated[UserModel, Depends(require_permissions("branches.write"))]
SupplierReader = Annotated[UserModel, Depends(require_permissions("suppliers.read"))]
SupplierWriter = Annotated[UserModel, Depends(require_permissions("suppliers.write"))]


@router.get("/public/branches", response_model=ApiResponse[list[BranchResponse]], tags=['PAQ-02 · Inventario y sucursales'])
def public_branches(db: Session = Depends(get_db)):
    return ApiResponse(message="Sucursales obtenidas.", data=OrganizationRepository(db).list_branches(False, False))


@router.get("/organization/cities", response_model=ApiResponse[list[CityResponse]])
def list_cities(actor: BranchReader, include_inactive: bool = False, db: Session = Depends(get_db)):
    return ApiResponse(message="Ciudades obtenidas.", data=OrganizationRepository(db).list_cities(include_inactive))


@router.get("/organization/cities/{entity_id}", response_model=ApiResponse[CityResponse])
def get_city(entity_id: uuid.UUID, actor: BranchReader, db: Session = Depends(get_db)):
    return ApiResponse(message="Ciudad obtenida.", data=OrganizationService(db).require_city(entity_id))


@router.post("/organization/cities", response_model=ApiResponse[CityResponse], status_code=status.HTTP_201_CREATED)
def create_city(data: CityCreate, actor: BranchWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Ciudad creada.", data=OrganizationService(db).create_city(data, actor))


@router.patch("/organization/cities/{entity_id}", response_model=ApiResponse[CityResponse])
def update_city(entity_id: uuid.UUID, data: CityUpdate, actor: BranchWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Ciudad actualizada.", data=OrganizationService(db).update_city(entity_id, data, actor))


@router.post("/organization/cities/{entity_id}/activate", response_model=ApiResponse[CityResponse])
def activate_city(entity_id: uuid.UUID, actor: BranchWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Ciudad activada.", data=OrganizationService(db).set_city_active(entity_id, True, actor))


@router.post("/organization/cities/{entity_id}/deactivate", response_model=ApiResponse[CityResponse])
def deactivate_city(entity_id: uuid.UUID, actor: BranchWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Ciudad desactivada.", data=OrganizationService(db).set_city_active(entity_id, False, actor))


@router.delete("/organization/cities/{entity_id}", response_model=ApiResponse[None])
def delete_city(entity_id: uuid.UUID, actor: BranchWriter, db: Session = Depends(get_db)):
    OrganizationService(db).delete_city(entity_id, actor)
    return ApiResponse(message="Ciudad eliminada.")


@router.get("/organization/suppliers", response_model=ApiResponse[list[SupplierResponse]])
def list_suppliers(actor: SupplierReader, search: str | None = None, include_inactive: bool = False, include_deleted: bool = False, db: Session = Depends(get_db)):
    return ApiResponse(message="Proveedores obtenidos.", data=OrganizationRepository(db).list_suppliers(search, include_inactive, include_deleted))


@router.get("/organization/suppliers/{entity_id}", response_model=ApiResponse[SupplierResponse])
def get_supplier(entity_id: uuid.UUID, actor: SupplierReader, include_deleted: bool = False, db: Session = Depends(get_db)):
    return ApiResponse(message="Proveedor obtenido.", data=OrganizationService(db).require_supplier(entity_id, include_deleted))


@router.post("/organization/suppliers", response_model=ApiResponse[SupplierResponse], status_code=status.HTTP_201_CREATED)
def create_supplier(data: SupplierCreate, actor: SupplierWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Proveedor creado.", data=OrganizationService(db).create_supplier(data, actor))


@router.patch("/organization/suppliers/{entity_id}", response_model=ApiResponse[SupplierResponse])
def update_supplier(entity_id: uuid.UUID, data: SupplierUpdate, actor: SupplierWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Proveedor actualizado.", data=OrganizationService(db).update_supplier(entity_id, data, actor))


@router.post("/organization/suppliers/{entity_id}/activate", response_model=ApiResponse[SupplierResponse])
def activate_supplier(entity_id: uuid.UUID, actor: SupplierWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Proveedor activado.", data=OrganizationService(db).set_supplier_active(entity_id, True, actor))


@router.post("/organization/suppliers/{entity_id}/deactivate", response_model=ApiResponse[SupplierResponse])
def deactivate_supplier(entity_id: uuid.UUID, actor: SupplierWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Proveedor desactivado.", data=OrganizationService(db).set_supplier_active(entity_id, False, actor))


@router.delete("/organization/suppliers/{entity_id}", response_model=ApiResponse[None])
def delete_supplier(entity_id: uuid.UUID, actor: SupplierWriter, db: Session = Depends(get_db)):
    OrganizationService(db).delete_supplier(entity_id, actor)
    return ApiResponse(message="Proveedor eliminado.")


@router.get("/organization/branches", response_model=ApiResponse[list[BranchResponse]])
def list_branches(actor: BranchReader, include_inactive: bool = False, include_deleted: bool = False, db: Session = Depends(get_db)):
    return ApiResponse(message="Sucursales obtenidas.", data=OrganizationRepository(db).list_branches(include_inactive, include_deleted))


@router.get("/organization/branches/{entity_id}", response_model=ApiResponse[BranchResponse])
def get_branch(entity_id: uuid.UUID, actor: BranchReader, include_deleted: bool = False, db: Session = Depends(get_db)):
    return ApiResponse(message="Sucursal obtenida.", data=OrganizationService(db).require_branch(entity_id, include_deleted))


@router.post("/organization/branches", response_model=ApiResponse[BranchResponse], status_code=status.HTTP_201_CREATED)
def create_branch(data: BranchCreate, actor: BranchWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Sucursal creada.", data=OrganizationService(db).create_branch(data, actor))


@router.patch("/organization/branches/{entity_id}", response_model=ApiResponse[BranchResponse])
def update_branch(entity_id: uuid.UUID, data: BranchUpdate, actor: BranchWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Sucursal actualizada.", data=OrganizationService(db).update_branch(entity_id, data, actor))


@router.post("/organization/branches/{entity_id}/activate", response_model=ApiResponse[BranchResponse])
def activate_branch(entity_id: uuid.UUID, actor: BranchWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Sucursal activada.", data=OrganizationService(db).set_branch_active(entity_id, True, actor))


@router.post("/organization/branches/{entity_id}/deactivate", response_model=ApiResponse[BranchResponse])
def deactivate_branch(entity_id: uuid.UUID, actor: BranchWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Sucursal desactivada.", data=OrganizationService(db).set_branch_active(entity_id, False, actor))


@router.delete("/organization/branches/{entity_id}", response_model=ApiResponse[None])
def delete_branch(entity_id: uuid.UUID, actor: BranchWriter, db: Session = Depends(get_db)):
    OrganizationService(db).delete_branch(entity_id, actor)
    return ApiResponse(message="Sucursal eliminada.")


@router.get("/organization/cash-points", response_model=ApiResponse[list[CashPointResponse]])
def list_cash_points(actor: BranchReader, branch_id: uuid.UUID | None = None, include_inactive: bool = False, include_deleted: bool = False, db: Session = Depends(get_db)):
    return ApiResponse(message="Puntos de caja obtenidos.", data=OrganizationRepository(db).list_cash_points(branch_id, include_inactive, include_deleted))


@router.get("/organization/cash-points/{entity_id}", response_model=ApiResponse[CashPointResponse])
def get_cash_point(entity_id: uuid.UUID, actor: BranchReader, include_deleted: bool = False, db: Session = Depends(get_db)):
    return ApiResponse(message="Punto de caja obtenido.", data=OrganizationService(db).require_cash_point(entity_id, include_deleted))


@router.post("/organization/cash-points", response_model=ApiResponse[CashPointResponse], status_code=status.HTTP_201_CREATED)
def create_cash_point(data: CashPointCreate, actor: BranchWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Punto de caja creado.", data=OrganizationService(db).create_cash_point(data, actor))


@router.patch("/organization/cash-points/{entity_id}", response_model=ApiResponse[CashPointResponse])
def update_cash_point(entity_id: uuid.UUID, data: CashPointUpdate, actor: BranchWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Punto de caja actualizado.", data=OrganizationService(db).update_cash_point(entity_id, data, actor))


@router.post("/organization/cash-points/{entity_id}/activate", response_model=ApiResponse[CashPointResponse])
def activate_cash_point(entity_id: uuid.UUID, actor: BranchWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Punto de caja activado.", data=OrganizationService(db).set_cash_point_active(entity_id, True, actor))


@router.post("/organization/cash-points/{entity_id}/deactivate", response_model=ApiResponse[CashPointResponse])
def deactivate_cash_point(entity_id: uuid.UUID, actor: BranchWriter, db: Session = Depends(get_db)):
    return ApiResponse(message="Punto de caja desactivado.", data=OrganizationService(db).set_cash_point_active(entity_id, False, actor))


@router.delete("/organization/cash-points/{entity_id}", response_model=ApiResponse[None])
def delete_cash_point(entity_id: uuid.UUID, actor: BranchWriter, db: Session = Depends(get_db)):
    OrganizationService(db).delete_cash_point(entity_id, actor)
    return ApiResponse(message="Punto de caja eliminado.")

