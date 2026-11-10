"""Servicio de gestión de tienda pública, marca y publicación (RS-3)."""
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.infrastructure.config.settings import settings
from src.infrastructure.security.access_context import is_platform_account
from src.shared.context.audit_context import get_audit_scope
from src.plataforma_saas.domain.exceptions import (
    InvalidBrandColorError,
    PublishRequirementsError,
    StoreNotPublishedError,
    TenantNotFoundError,
)
from src.plataforma_saas.domain.marca import (
    TenantSnapshot,
    color_oscuro,
    contraste,
    enmascarar_cuenta,
    requisitos_publicacion,
    tinta_sobre,
)
from src.plataforma_saas.infrastructure.models.storefront import TenantPaymentMethodModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.plataforma_saas.web.schemas.storefront import (
    PublicStoreBranch,
    PublicStoreCard,
    PublicStoreOut,
    StorefrontAdminOut,
    StorefrontUpdate,
)
from src.usuarios_catalogo.infrastructure.media_storage import store_image
from src.inventario_sucursales.infrastructure.models.organization import BranchModel
from src.usuarios_catalogo.infrastructure.models.catalog import ProductImageModel, ProductModel


class StorefrontService:
    def __init__(self, db: Session):
        self.db = db

    def _get_tenant(self, tenant_id: UUID) -> TenantModel:
        tenant = self.db.get(TenantModel, tenant_id)
        if tenant is None:
            raise TenantNotFoundError()
        return tenant

    def _evaluar_requisitos(self, tenant: TenantModel) -> list[str]:
        # 1. Sucursal activa
        has_branch = bool(
            self.db.scalar(
                select(func.count(BranchModel.id)).where(
                    BranchModel.tenant_id == tenant.id,
                    BranchModel.is_active.is_(True),
                    BranchModel.deleted_at.is_(None),
                    BranchModel.opening_hours.is_not(None),
                )
            )
        )

        # 2. Productos activos con foto
        products_with_photo = (
            self.db.scalar(
                select(func.count(func.distinct(ProductModel.id)))
                .join(ProductImageModel, ProductImageModel.product_id == ProductModel.id)
                .where(
                    ProductModel.tenant_id == tenant.id,
                    ProductModel.is_active.is_(True),
                    ProductModel.deleted_at.is_(None),
                )
            )
            or 0
        )

        # 3. Método de cobro activo
        has_payment = bool(
            self.db.scalar(
                select(func.count(TenantPaymentMethodModel.id)).where(
                    TenantPaymentMethodModel.tenant_id == tenant.id,
                    TenantPaymentMethodModel.is_active.is_(True),
                )
            )
        )

        from src.plataforma_saas.application.plan_guard import PlanGuard
        from src.plataforma_saas.application.jobs.suscripciones import calcular_lifecycle_state
        subscription=PlanGuard(self.db).repository.open_subscription(tenant.id)
        snap = TenantSnapshot(
            subscription_active=bool(subscription and calcular_lifecycle_state(subscription) in {'active','expiring','grace'}),
            has_branch_with_hours=has_branch,
            logo_url=tenant.logo_url,
            active_products_with_photo_count=products_with_photo,
            has_active_payment_method=has_payment,
        )
        return requisitos_publicacion(snap)

    def obtener(self, tenant_id: UUID) -> StorefrontAdminOut:
        tenant = self._get_tenant(tenant_id)
        missing = self._evaluar_requisitos(tenant)

        brand_color_dark = color_oscuro(tenant.brand_color) if tenant.brand_color else None
        ink = tinta_sobre(tenant.brand_color) if tenant.brand_color else None

        return StorefrontAdminOut(
            id=tenant.id,
            slug=tenant.slug,
            legal_name=tenant.legal_name,
            trade_name=tenant.trade_name,
            is_published=tenant.is_published,
            published_at=tenant.published_at,
            logo_url=tenant.logo_url,
            banner_url=tenant.banner_url,
            brand_color=tenant.brand_color,
            brand_color_dark=brand_color_dark,
            ink_on_brand=ink,
            slogan=tenant.slogan,
            about=tenant.about,
            whatsapp=tenant.whatsapp,
            social_links=tenant.social_links or {},
            shipping_policy=tenant.shipping_policy,
            seo_title=tenant.seo_title,
            seo_description=tenant.seo_description,
            city=tenant.city,
            is_featured=tenant.is_featured,
            missing_requirements=missing,
        )

    def actualizar(
        self, tenant_id: UUID, data: StorefrontUpdate, actor: UserModel | None = None
    ) -> StorefrontAdminOut:
        tenant = self._get_tenant(tenant_id)

        if data.brand_color is not None:
            # Validar contraste básico (no puede ser idéntico al blanco absoluto o negro absoluto sin legibilidad)
            if contraste(data.brand_color, "#FFFFFF") < 1.1 and contraste(data.brand_color, "#000000") < 1.1:
                raise InvalidBrandColorError()
            tenant.brand_color = data.brand_color

        if data.slogan is not None:
            tenant.slogan = data.slogan
        if data.about is not None:
            tenant.about = data.about
        if data.whatsapp is not None:
            tenant.whatsapp = data.whatsapp
        if data.social_links is not None:
            tenant.social_links = data.social_links
        if data.shipping_policy is not None:
            tenant.shipping_policy = data.shipping_policy
        if data.seo_title is not None:
            tenant.seo_title = data.seo_title
        if data.seo_description is not None:
            tenant.seo_description = data.seo_description
        if data.city is not None:
            tenant.city = data.city

        if actor:
            RecordAuditEvent(self.db).execute(
                actor_user_id=actor.id,
                action="tenant.storefront_updated",
                entity_type="tenant",
                entity_id=str(tenant.id),
                description=f"Tienda y marca actualizadas para {tenant.trade_name}.",
                metadata={"brand_color": tenant.brand_color, "city": tenant.city},
            )

        self.db.commit()
        return self.obtener(tenant_id)

    def subir_imagen(
        self, tenant_id: UUID, kind: str, raw_bytes: bytes, actor: UserModel | None = None, public_base: str = ""
    ) -> str:
        tenant = self._get_tenant(tenant_id)
        directory = Path(settings.media_storage_dir).resolve()
        name, width, height = store_image(raw_bytes, directory)

        base_url = public_base.rstrip("/") if public_base else "/api/v1/media/files"
        url = f"{base_url}/{name}"

        if kind == "logo":
            tenant.logo_url = url
        elif kind == "banner":
            tenant.banner_url = url

        if actor:
            RecordAuditEvent(self.db).execute(
                actor_user_id=actor.id,
                action=f"tenant.{kind}_uploaded",
                entity_type="tenant",
                entity_id=str(tenant.id),
                description=f"{kind.capitalize()} de tienda subido para {tenant.trade_name}.",
                metadata={"url": url, "width": width, "height": height},
            )

        self.db.commit()
        return url

    def publicar(self, tenant_id: UUID, actor: UserModel | None = None) -> StorefrontAdminOut:
        tenant = self._get_tenant(tenant_id)
        missing = self._evaluar_requisitos(tenant)
        if missing:
            raise PublishRequirementsError(missing=missing)

        tenant.is_published = True
        tenant.published_at = datetime.now(timezone.utc)

        if actor:
            RecordAuditEvent(self.db).execute(
                actor_user_id=actor.id,
                action="tenant.published",
                entity_type="tenant",
                entity_id=str(tenant.id),
                description=f"Tienda pública publicada: {tenant.trade_name}.",
            )

        self.db.commit()
        return self.obtener(tenant_id)

    def despublicar(
        self, tenant_id: UUID, reason: str | None = None, actor: UserModel | None = None
    ) -> StorefrontAdminOut:
        tenant = self._get_tenant(tenant_id)
        tenant.is_published = False

        if actor:
            RecordAuditEvent(self.db).execute(
                actor_user_id=actor.id,
                action="tenant.unpublished",
                entity_type="tenant",
                entity_id=str(tenant.id),
                description=f"Tienda pública despublicada: {tenant.trade_name}. Motivo: {reason or 'No indicado'}",
                metadata={"reason": reason},
            )

        self.db.commit()
        return self.obtener(tenant_id)

    def publico(self, slug: str, viewer: UserModel | None = None) -> PublicStoreOut:
        tenant = self.db.scalar(select(TenantModel).where(TenantModel.slug == slug))
        if tenant is None:
            raise StoreNotPublishedError()
        if tenant.status != "ACTIVA":
            raise StoreNotPublishedError()

        is_preview = False
        if not tenant.is_published:
            support_tenant, support_session = get_audit_scope()
            puede = viewer is not None and (
                support_tenant == tenant.id if support_session is not None
                else viewer.tenant_id == tenant.id or is_platform_account(viewer)
            )
            if not puede:
                raise StoreNotPublishedError()
            is_preview = True

        # Obtener sucursales activas
        branches = self.db.scalars(
            select(BranchModel).where(
                BranchModel.tenant_id == tenant.id,
                BranchModel.is_active.is_(True),
            )
        ).all()
        branch_outs = [
            PublicStoreBranch(
                id=b.id,
                name=b.name,
                code=b.code,
                address=b.address,
                city=b.city.name if hasattr(b.city, "name") else (str(b.city) if b.city else None),
                phone=b.phone,
                opening_hours=b.opening_hours,
            )
            for b in branches
        ]

        # Obtener métodos de cobro públicos (enmascarados)
        methods = self.db.scalars(
            select(TenantPaymentMethodModel).where(
                TenantPaymentMethodModel.tenant_id == tenant.id,
                TenantPaymentMethodModel.is_active.is_(True),
            ).order_by(TenantPaymentMethodModel.sort_order.asc())
        ).all()
        methods_outs = [
            {
                "id": str(m.id),
                "kind": m.kind,
                "label": m.label,
                "qr_image_url": m.qr_image_url,
                "bank_name": m.bank_name,
                "account_holder": m.account_holder,
                "account_number": enmascarar_cuenta(m.account_number or "") if m.account_number else None,
                "instructions": m.instructions,
            }
            for m in methods
        ]

        brand_color_dark = color_oscuro(tenant.brand_color) if tenant.brand_color else None
        ink = tinta_sobre(tenant.brand_color) if tenant.brand_color else None

        return PublicStoreOut(
            slug=tenant.slug,
            trade_name=tenant.trade_name,
            logo_url=tenant.logo_url,
            banner_url=tenant.banner_url,
            brand_color=tenant.brand_color,
            brand_color_dark=brand_color_dark,
            ink_on_brand=ink,
            slogan=tenant.slogan,
            about=tenant.about,
            whatsapp=tenant.whatsapp,
            social_links=tenant.social_links or {},
            shipping_policy=tenant.shipping_policy,
            seo_title=tenant.seo_title,
            seo_description=tenant.seo_description,
            city=tenant.city,
            branches=branch_outs,
            payment_methods_public=methods_outs,
            preview=is_preview,
        )

    def directorio(
        self, search: str | None = None, city: str | None = None, page: int = 1, page_size: int = 20
    ) -> dict:
        query = select(TenantModel).where(
            TenantModel.is_published.is_(True),
            TenantModel.status == "ACTIVA",
            (TenantModel.is_sandbox.is_(False) | TenantModel.is_sandbox.is_(None)),
        )

        if search:
            s = f"%{search.strip()}%"
            query = query.where(
                TenantModel.trade_name.ilike(s) | TenantModel.slogan.ilike(s)
            )

        if city:
            query = query.where(TenantModel.city.ilike(f"%{city.strip()}%"))

        total = self.db.scalar(select(func.count()).select_from(query.subquery())) or 0
        items = (
            self.db.scalars(
                query.order_by(TenantModel.is_featured.desc(), TenantModel.trade_name.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            .all()
        )

        return {
            "items": [
                PublicStoreCard(
                    slug=t.slug,
                    trade_name=t.trade_name,
                    logo_url=t.logo_url,
                    banner_url=t.banner_url,
                    brand_color=t.brand_color,
                    slogan=t.slogan,
                    city=t.city,
                    is_featured=t.is_featured,
                )
                for t in items
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
