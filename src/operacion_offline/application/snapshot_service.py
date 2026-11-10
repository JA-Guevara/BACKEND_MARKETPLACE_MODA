from datetime import datetime, timedelta, timezone
from uuid import UUID
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload
from src.auth.infrastructure.http.schemas import TenantSummary
from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.infrastructure.security.authorization import get_permission_codes
from src.inventario_sucursales.infrastructure.models.organization import BranchModel, CashPointModel
from src.inventario_sucursales.application.services.user_branch_service import UserBranchService
from src.infrastructure.config.settings import settings
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.operacion_offline.web.schemas import OfflineSnapshot, SnapshotProduct, SnapshotVariant, SnapshotCustomer, SnapshotRemoved
from src.usuarios_catalogo.infrastructure.models.catalog import ProductModel, ProductVariantModel, ProductImageModel
from src.roles.infrastructure.persistence.models.role import RoleModel
from src.ventas_pagos.infrastructure.models import StockModel
from src.ventas_pagos.application.pricing_service import PricingService
from src.shared.exceptions.domain_exception import NotFoundError, ValidationError


class SnapshotService:
    def __init__(self, db, ctx):
        self.db, self.ctx = db, ctx

    def generar(self, branch_id=None, since=None):
        generated = datetime.now(timezone.utc)
        if since:
            since = since.replace(tzinfo=timezone.utc) if since.tzinfo is None else since.astimezone(timezone.utc)
            if since > generated:
                raise ValidationError("La versión de la instantánea no puede estar en el futuro.")
        branches = list(self.db.scalars(select(BranchModel).where(BranchModel.tenant_id == self.ctx.tenant_id,
            BranchModel.is_active.is_(True), BranchModel.deleted_at.is_(None)).order_by(BranchModel.name, BranchModel.id)))
        permissions = get_permission_codes(self.ctx.user)
        if {"commerce.write", "reservations.write"} & permissions and not getattr(self.ctx, "support_session_id", None):
            branches = UserBranchService(self.db, self.ctx.tenant_id).autorizadas(self.ctx.user)
        branch_ids = [branch.id for branch in branches]
        if branch_id and not any(branch.id == branch_id for branch in branches):
            raise NotFoundError("Sucursal no encontrada.")
        query = select(ProductModel).where(ProductModel.tenant_id == self.ctx.tenant_id).options(selectinload(ProductModel.variants), selectinload(ProductModel.images))
        # Los cambios de imágenes y variantes no actualizan por sí solos al padre.
        if since:
            query = query.where(or_(ProductModel.updated_at > since, ProductModel.variants.any(ProductVariantModel.updated_at > since), ProductModel.images.any(ProductImageModel.updated_at > since)))
        products = list(self.db.scalars(query))
        available = [p for p in products if p.is_active and not p.deleted_at]
        variants = [variant for product in available for variant in product.variants if variant.is_active]
        stock_query = select(StockModel).join(BranchModel, BranchModel.id == StockModel.branch_id).join(ProductVariantModel, ProductVariantModel.id == StockModel.variant_id).join(ProductModel, ProductModel.id == ProductVariantModel.product_id).where(
            BranchModel.tenant_id == self.ctx.tenant_id, ProductModel.tenant_id == self.ctx.tenant_id,
            BranchModel.is_active.is_(True), BranchModel.deleted_at.is_(None), ProductModel.is_active.is_(True), ProductModel.deleted_at.is_(None), ProductVariantModel.is_active.is_(True))
        stock_query = stock_query.where(StockModel.branch_id.in_(branch_ids))
        if branch_id:
            stock_query = stock_query.where(StockModel.branch_id == branch_id)
        stock = list(self.db.scalars(stock_query))
        customers = []
        if "reservations.write" in get_permission_codes(self.ctx.user):
            rows = self.db.scalars(select(UserModel).join(UserModel.roles).where(UserModel.tenant_id == self.ctx.tenant_id,
                UserModel.is_active.is_(True), UserModel.deleted_at.is_(None), RoleModel.code == "client")).unique()
            customers = [SnapshotCustomer(id=u.id, name=f"{u.first_name} {u.last_name}".strip(),
                document_tail=u.document_number[-3:] if u.document_number else None, phone=u.phone) for u in rows]
        removed_products = [p.id for p in products if not p.is_active or p.deleted_at] if since else []
        removed_variants = [v.id for p in products for v in p.variants if not v.is_active or p.id in removed_products] if since else []
        if since:
            deleted = self.db.scalars(select(AuditEventModel.entity_id).join(UserModel, UserModel.id == AuditEventModel.actor_user_id).where(
                UserModel.tenant_id == self.ctx.tenant_id, AuditEventModel.action == "catalog.variant_deleted", AuditEventModel.created_at > since))
            removed_variants.extend(UUID(value) for value in deleted if value)
        tenant = self.db.get(TenantModel, self.ctx.tenant_id)
        pricing = PricingService(self.db, self.ctx.tenant_id)
        product_dtos = []
        for p in available:
            off_p, off_id, off_until = self._info_oferta(p, pricing)
            product_dtos.append(SnapshotProduct(
                id=p.id, name=p.name, slug=p.slug, category=p.category.name, brand=p.brand,
                base_price=p.base_price, offer_price=off_p, offer_id=off_id, offer_valid_until=off_until,
                image_url=next((i.url for i in p.images if i.is_primary), p.images[0].url if p.images else None),
                is_featured=p.is_featured,
            ))
        snapshot = OfflineSnapshot(version=generated.isoformat(), generated_at=generated, full=since is None,
            tenant=TenantSummary.model_validate(tenant), branches=branches,
            cash_points=list(self.db.scalars(select(CashPointModel).where(
                CashPointModel.tenant_id == self.ctx.tenant_id,
                CashPointModel.branch_id.in_(branch_ids),
                CashPointModel.is_active.is_(True), CashPointModel.deleted_at.is_(None),
            ))),
            price_valid_until=generated + timedelta(hours=settings.offline_price_validity_hours),
            products=product_dtos,
            variants=[SnapshotVariant(id=v.id, product_id=v.product_id, sku=v.sku, size=v.size.name, color=v.color.name,
                color_hex=v.color.hex_code, price=v.price_override, is_active=v.is_active) for v in variants],
            stock=stock, customers=customers, removed=SnapshotRemoved(products=removed_products, variants=list(set(removed_variants))))
        self.db.commit()
        return snapshot

    def _info_oferta(self, product, pricing):
        best_p = None
        best_off_id = None
        best_ends_at = None
        for v in product.variants:
            if not v.is_active:
                continue
            pv = pricing.precio(v, canal='OFFLINE')
            if pv.has_offer:
                if best_p is None or pv.final < best_p:
                    best_p = pv.final
                    best_off_id = UUID(pv.offer_id) if pv.offer_id else None
                    best_ends_at = pv.offer_ends_at
        return best_p, best_off_id, best_ends_at

    def _precio_oferta(self, product):
        return None
