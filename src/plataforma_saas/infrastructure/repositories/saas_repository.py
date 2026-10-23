from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.plataforma_saas.infrastructure.models.plan import PlanModel
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel
from src.inventario_sucursales.infrastructure.models.organization import BranchModel


class SaasRepository:
    def __init__(self, db: Session): self.db = db
    def get_tenant(self, tenant_id: UUID): return self.db.get(TenantModel, tenant_id)
    def find_tenant_by_slug(self, slug: str): return self.db.scalar(select(TenantModel).where(TenantModel.slug == slug))
    def get_plan_by_code(self, code: str): return self.db.scalar(select(PlanModel).where(PlanModel.code == code))
    def open_subscription(self, tenant_id: UUID):
        return self.db.scalar(select(SubscriptionModel).where(SubscriptionModel.tenant_id == tenant_id, SubscriptionModel.closed_at.is_(None)))
    def count_active_branches(self, tenant_id: UUID):
        return self.db.scalar(select(func.count()).select_from(BranchModel).where(BranchModel.tenant_id == tenant_id, BranchModel.is_active.is_(True), BranchModel.deleted_at.is_(None))) or 0
    def add(self, entity):
        self.db.add(entity)
        self.db.flush()

