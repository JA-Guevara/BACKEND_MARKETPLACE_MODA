import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from src.inventario_sucursales.infrastructure.models.organization import BranchModel, CashPointModel, CityModel, SupplierModel


class OrganizationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_city(self, entity_id: uuid.UUID) -> CityModel | None:
        return self.db.get(CityModel, entity_id)

    def find_city(self, name: str, department: str, country: str) -> CityModel | None:
        return self.db.scalar(
            select(CityModel).where(
                func.lower(CityModel.name) == name.lower(),
                func.lower(CityModel.department) == department.lower(),
                func.lower(CityModel.country) == country.lower(),
            )
        )

    def list_cities(self, include_inactive: bool = False) -> list[CityModel]:
        stmt = select(CityModel).order_by(CityModel.country, CityModel.department, CityModel.name)
        if not include_inactive:
            stmt = stmt.where(CityModel.is_active.is_(True))
        return list(self.db.scalars(stmt))

    def get_supplier(self, entity_id: uuid.UUID, include_deleted: bool = False) -> SupplierModel | None:
        stmt = select(SupplierModel).where(SupplierModel.id == entity_id)
        if not include_deleted:
            stmt = stmt.where(SupplierModel.deleted_at.is_(None))
        return self.db.scalar(stmt)

    def find_supplier_by_tax_id(self, tax_id: str) -> SupplierModel | None:
        return self.db.scalar(select(SupplierModel).where(SupplierModel.tax_id == tax_id.upper()))

    def list_suppliers(self, search: str | None, include_inactive: bool, include_deleted: bool) -> list[SupplierModel]:
        stmt = select(SupplierModel)
        if search:
            term = f"%{search.strip()}%"
            stmt = stmt.where(or_(SupplierModel.business_name.ilike(term), SupplierModel.trade_name.ilike(term), SupplierModel.tax_id.ilike(term)))
        if not include_inactive:
            stmt = stmt.where(SupplierModel.is_active.is_(True))
        if not include_deleted:
            stmt = stmt.where(SupplierModel.deleted_at.is_(None))
        return list(self.db.scalars(stmt.order_by(SupplierModel.business_name)))

    def get_branch(self, entity_id: uuid.UUID, include_deleted: bool = False) -> BranchModel | None:
        stmt = select(BranchModel).options(selectinload(BranchModel.cash_points)).where(BranchModel.id == entity_id)
        if not include_deleted:
            stmt = stmt.where(BranchModel.deleted_at.is_(None))
        return self.db.scalar(stmt)

    def find_branch_by_code(self, code: str) -> BranchModel | None:
        return self.db.scalar(select(BranchModel).where(func.lower(BranchModel.code) == code.lower()))

    def list_branches(self, include_inactive: bool, include_deleted: bool) -> list[BranchModel]:
        stmt = select(BranchModel).options(selectinload(BranchModel.cash_points)).order_by(BranchModel.name)
        if not include_inactive:
            stmt = stmt.where(BranchModel.is_active.is_(True))
        if not include_deleted:
            stmt = stmt.where(BranchModel.deleted_at.is_(None))
        return list(self.db.scalars(stmt).unique())

    def get_cash_point(self, entity_id: uuid.UUID, include_deleted: bool = False) -> CashPointModel | None:
        stmt = select(CashPointModel).where(CashPointModel.id == entity_id)
        if not include_deleted:
            stmt = stmt.where(CashPointModel.deleted_at.is_(None))
        return self.db.scalar(stmt)

    def find_cash_point(self, branch_id: uuid.UUID, code: str) -> CashPointModel | None:
        return self.db.scalar(
            select(CashPointModel).where(CashPointModel.branch_id == branch_id, func.lower(CashPointModel.code) == code.lower())
        )

    def list_cash_points(self, branch_id: uuid.UUID | None, include_inactive: bool, include_deleted: bool) -> list[CashPointModel]:
        stmt = select(CashPointModel)
        if branch_id:
            stmt = stmt.where(CashPointModel.branch_id == branch_id)
        if not include_inactive:
            stmt = stmt.where(CashPointModel.is_active.is_(True))
        if not include_deleted:
            stmt = stmt.where(CashPointModel.deleted_at.is_(None))
        return list(self.db.scalars(stmt.order_by(CashPointModel.code)))

    def add(self, entity):
        self.db.add(entity)
        self.db.flush()
        return entity
