import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.inventario_sucursales.infrastructure.models.organization import BranchModel, CashPointModel, CityModel, SupplierModel
from src.inventario_sucursales.infrastructure.repositories.organization_repository import OrganizationRepository
from src.inventario_sucursales.web.schemas.organization import BranchCreate, BranchUpdate, CashPointCreate, CashPointUpdate, CityCreate, CityUpdate, SupplierCreate, SupplierUpdate
from src.shared.exceptions.domain_exception import ConflictError, NotFoundError


class OrganizationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = OrganizationRepository(db)
        self.audit = RecordAuditEvent(db)

    def create_city(self, data: CityCreate, actor: UserModel) -> CityModel:
        if self.repository.find_city(data.name, data.department, data.country):
            raise ConflictError("La ciudad ya esta registrada.")
        city = CityModel(**self._trimmed(data.model_dump()))
        self.repository.add(city)
        self._audit(actor, "branches.city_created", city, "Ciudad creada.")
        self.db.commit()
        self.db.refresh(city)
        return city

    def update_city(self, entity_id: uuid.UUID, data: CityUpdate, actor: UserModel) -> CityModel:
        city = self.require_city(entity_id)
        self._update(city, data.model_dump(exclude_unset=True))
        duplicate = self.repository.find_city(city.name, city.department, city.country)
        if duplicate and duplicate.id != city.id:
            raise ConflictError("La ciudad ya esta registrada.")
        self._audit(actor, "branches.city_updated", city, "Ciudad actualizada.")
        self.db.commit()
        return city

    def set_city_active(self, entity_id: uuid.UUID, active: bool, actor: UserModel) -> CityModel:
        city = self.require_city(entity_id)
        city.is_active = active
        self._audit(actor, "branches.city_status_changed", city, "Estado de ciudad actualizado.")
        self.db.commit()
        return city

    def delete_city(self, entity_id: uuid.UUID, actor: UserModel) -> None:
        city = self.require_city(entity_id)
        if city.branches:
            raise ConflictError("No se puede eliminar una ciudad con sucursales asociadas.")
        self._audit(actor, "branches.city_deleted", city, "Ciudad eliminada.")
        self.db.delete(city)
        self.db.commit()

    def create_supplier(self, data: SupplierCreate, actor: UserModel) -> SupplierModel:
        if self.repository.find_supplier_by_tax_id(data.tax_id):
            raise ConflictError("El NIT o identificador fiscal ya esta registrado.")
        supplier = SupplierModel(**self._trimmed(data.model_dump()))
        self.repository.add(supplier)
        self._audit(actor, "suppliers.create", supplier, "Proveedor creado.")
        self.db.commit()
        self.db.refresh(supplier)
        return supplier

    def update_supplier(self, entity_id: uuid.UUID, data: SupplierUpdate, actor: UserModel) -> SupplierModel:
        supplier = self.require_supplier(entity_id)
        changes = data.model_dump(exclude_unset=True)
        if changes.get("tax_id"):
            changes["tax_id"] = changes["tax_id"].strip().upper()
            duplicate = self.repository.find_supplier_by_tax_id(changes["tax_id"])
            if duplicate and duplicate.id != supplier.id:
                raise ConflictError("El NIT o identificador fiscal ya esta registrado.")
        self._update(supplier, changes)
        self._audit(actor, "suppliers.update", supplier, "Proveedor actualizado.")
        self.db.commit()
        return supplier

    def set_supplier_active(self, entity_id: uuid.UUID, active: bool, actor: UserModel) -> SupplierModel:
        supplier = self.require_supplier(entity_id, include_deleted=True)
        supplier.is_active = active
        if active:
            supplier.deleted_at = None
        self._audit(actor, "suppliers.status_changed", supplier, "Estado de proveedor actualizado.")
        self.db.commit()
        return supplier

    def delete_supplier(self, entity_id: uuid.UUID, actor: UserModel) -> None:
        supplier = self.require_supplier(entity_id)
        supplier.is_active = False
        supplier.deleted_at = datetime.now(timezone.utc)
        self._audit(actor, "suppliers.delete", supplier, "Proveedor eliminado logicamente.")
        self.db.commit()

    def create_branch(self, data: BranchCreate, actor: UserModel) -> BranchModel:
        city = self.require_city(data.city_id)
        if not city.is_active:
            raise ConflictError("La ciudad seleccionada esta inactiva.")
        if self.repository.find_branch_by_code(data.code):
            raise ConflictError("El codigo de sucursal ya existe.")
        branch = BranchModel(**self._trimmed(data.model_dump()))
        self.repository.add(branch)
        self._audit(actor, "branches.create", branch, "Sucursal creada.")
        self.db.commit()
        return self.repository.get_branch(branch.id) or branch

    def update_branch(self, entity_id: uuid.UUID, data: BranchUpdate, actor: UserModel) -> BranchModel:
        branch = self.require_branch(entity_id)
        changes = data.model_dump(exclude_unset=True)
        if changes.get("city_id"):
            city = self.require_city(changes["city_id"])
            if not city.is_active:
                raise ConflictError("La ciudad seleccionada esta inactiva.")
        if changes.get("code"):
            changes["code"] = changes["code"].strip().upper()
            duplicate = self.repository.find_branch_by_code(changes["code"])
            if duplicate and duplicate.id != branch.id:
                raise ConflictError("El codigo de sucursal ya existe.")
        self._update(branch, changes)
        self._audit(actor, "branches.update", branch, "Sucursal actualizada.")
        self.db.commit()
        return self.repository.get_branch(branch.id) or branch

    def set_branch_active(self, entity_id: uuid.UUID, active: bool, actor: UserModel) -> BranchModel:
        branch = self.require_branch(entity_id, include_deleted=True)
        branch.is_active = active
        if active:
            branch.deleted_at = None
        for cash_point in branch.cash_points:
            cash_point.is_active = active
        self._audit(actor, "branches.status_changed", branch, "Estado de sucursal actualizado.")
        self.db.commit()
        return branch

    def delete_branch(self, entity_id: uuid.UUID, actor: UserModel) -> None:
        branch = self.require_branch(entity_id)
        branch.is_active = False
        branch.deleted_at = datetime.now(timezone.utc)
        for cash_point in branch.cash_points:
            cash_point.is_active = False
        self._audit(actor, "branches.delete", branch, "Sucursal eliminada logicamente.")
        self.db.commit()

    def create_cash_point(self, data: CashPointCreate, actor: UserModel) -> CashPointModel:
        branch = self.require_branch(data.branch_id)
        if not branch.is_active:
            raise ConflictError("La sucursal esta inactiva.")
        if self.repository.find_cash_point(data.branch_id, data.code):
            raise ConflictError("El codigo de caja ya existe en la sucursal.")
        cash_point = CashPointModel(**self._trimmed(data.model_dump()))
        self.repository.add(cash_point)
        self._audit(actor, "branches.cash_point_created", cash_point, "Punto de caja creado.")
        self.db.commit()
        self.db.refresh(cash_point)
        return cash_point

    def update_cash_point(self, entity_id: uuid.UUID, data: CashPointUpdate, actor: UserModel) -> CashPointModel:
        cash_point = self.require_cash_point(entity_id)
        changes = data.model_dump(exclude_unset=True)
        target_branch = changes.get("branch_id", cash_point.branch_id)
        self.require_branch(target_branch)
        if changes.get("code"):
            changes["code"] = changes["code"].strip().upper()
        duplicate = self.repository.find_cash_point(target_branch, changes.get("code", cash_point.code))
        if duplicate and duplicate.id != cash_point.id:
            raise ConflictError("El codigo de caja ya existe en la sucursal.")
        self._update(cash_point, changes)
        self._audit(actor, "branches.cash_point_updated", cash_point, "Punto de caja actualizado.")
        self.db.commit()
        return cash_point

    def set_cash_point_active(self, entity_id: uuid.UUID, active: bool, actor: UserModel) -> CashPointModel:
        cash_point = self.require_cash_point(entity_id, include_deleted=True)
        if active and not self.require_branch(cash_point.branch_id).is_active:
            raise ConflictError("No se puede activar una caja de una sucursal inactiva.")
        cash_point.is_active = active
        if active:
            cash_point.deleted_at = None
        self._audit(actor, "branches.cash_point_status_changed", cash_point, "Estado de punto de caja actualizado.")
        self.db.commit()
        return cash_point

    def delete_cash_point(self, entity_id: uuid.UUID, actor: UserModel) -> None:
        cash_point = self.require_cash_point(entity_id)
        cash_point.is_active = False
        cash_point.deleted_at = datetime.now(timezone.utc)
        self._audit(actor, "branches.cash_point_deleted", cash_point, "Punto de caja eliminado logicamente.")
        self.db.commit()

    def require_city(self, entity_id: uuid.UUID) -> CityModel:
        entity = self.repository.get_city(entity_id)
        if not entity:
            raise NotFoundError("Ciudad no encontrada.")
        return entity

    def require_supplier(self, entity_id: uuid.UUID, include_deleted: bool = False) -> SupplierModel:
        entity = self.repository.get_supplier(entity_id, include_deleted)
        if not entity:
            raise NotFoundError("Proveedor no encontrado.")
        return entity

    def require_branch(self, entity_id: uuid.UUID, include_deleted: bool = False) -> BranchModel:
        entity = self.repository.get_branch(entity_id, include_deleted)
        if not entity:
            raise NotFoundError("Sucursal no encontrada.")
        return entity

    def require_cash_point(self, entity_id: uuid.UUID, include_deleted: bool = False) -> CashPointModel:
        entity = self.repository.get_cash_point(entity_id, include_deleted)
        if not entity:
            raise NotFoundError("Punto de caja no encontrado.")
        return entity

    @staticmethod
    def _trimmed(values: dict) -> dict:
        return {key: value.strip() if isinstance(value, str) else value for key, value in values.items()}

    def _update(self, entity, changes: dict) -> None:
        for field, value in self._trimmed(changes).items():
            setattr(entity, field, value)

    def _audit(self, actor: UserModel, action: str, entity, description: str) -> None:
        self.audit.execute(actor_user_id=actor.id, action=action, entity_type=entity.__tablename__, entity_id=str(entity.id), description=description)
