"""Router de tienda pública, marca, cobros y solicitudes (RS-3)."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.web.dependencies import get_current_user, get_optional_user
from src.infrastructure.config.settings import settings
from src.infrastructure.database.session import get_db
from src.infrastructure.security.access_context import AccessContext, get_access_context
from src.infrastructure.security.authorization import require_permissions
from src.infrastructure.security.tenancy import TenantScope
from src.plataforma_saas.application.catalog_template_service import CatalogTemplateService
from src.plataforma_saas.application.payment_methods_service import PaymentMethodsService
from src.plataforma_saas.application.storefront_service import StorefrontService
from src.plataforma_saas.application.upgrade_request_service import UpgradeRequestService
from src.plataforma_saas.application.usage_service import UsageService
from src.plataforma_saas.web.schemas.storefront import (
    CatalogTemplateIn,
    HandleUpgradeRequestIn,
    PaymentMethodIn,
    PlatformStorefrontUpdate,
    StorefrontUpdate,
    UpgradeRequestIn,
)
from src.shared.exceptions.domain_exception import ValidationError
from src.shared.responses.api_response import ApiResponse

router = APIRouter(tags=["RS-3 · Tienda pública y marca"])


# =========================================================================
# 1. PÚBLICO: DIRECTORIO Y TIENDA
# =========================================================================

@router.get("/public/stores")
def get_public_stores(
    search: str | None = Query(None, max_length=100),
    city: str | None = Query(None, max_length=80),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Directorio público de tiendas activas y publicadas."""
    data = StorefrontService(db).directorio(search=search, city=city, page=page, page_size=page_size)
    return ApiResponse(data=data)


@router.get("/public/stores/{slug}")
def get_public_store_detail(
    slug: str,
    viewer: UserModel | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Detalle público de una tienda con datos de marca, sucursales y métodos de cobro."""
    data = StorefrontService(db).publico(slug=slug, viewer=viewer)
    return ApiResponse(data=data)


# =========================================================================
# 2. PANEL DE EMPRESA: MI TIENDA, MARCA Y COBROS
# =========================================================================

@router.get("/tenant/storefront")
def get_tenant_storefront(
    ctx: TenantScope,
    user: Annotated[UserModel, Depends(require_permissions("storefront.write"))],
    db: Session = Depends(get_db),
):
    """Configuración de tienda y marca de la empresa."""
    data = StorefrontService(db).obtener(ctx.tenant_id)
    return ApiResponse(data=data)


@router.patch("/tenant/storefront")
def update_tenant_storefront(
    data: StorefrontUpdate,
    ctx: TenantScope,
    user: Annotated[UserModel, Depends(require_permissions("storefront.write"))],
    db: Session = Depends(get_db),
):
    """Actualizar datos de marca, políticas y SEO de la empresa."""
    res = StorefrontService(db).actualizar(ctx.tenant_id, data, ctx.user)
    return ApiResponse(message="Tienda actualizada.", data=res)


@router.post("/tenant/storefront/images/{kind}")
def upload_storefront_image(
    kind: str,
    request: Request,
    ctx: TenantScope,
    user: Annotated[UserModel, Depends(require_permissions("storefront.write"))],
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Subir logo o banner de la tienda procesado a WEBP."""
    if kind not in ("logo", "banner"):
        raise ValidationError("El tipo de imagen debe ser 'logo' o 'banner'.")

    limit = settings.media_max_upload_mb * 1024 * 1024
    try:
        raw = file.file.read(limit + 1)
    finally:
        file.file.close()

    if not raw or len(raw) > limit:
        raise ValidationError(f"La imagen debe pesar entre 1 byte y {settings.media_max_upload_mb} MB.")

    public_base = settings.media_public_base_url.rstrip("/")
    url = StorefrontService(db).subir_imagen(ctx.tenant_id, kind, raw, ctx.user, public_base=public_base)
    return ApiResponse(message=f"{kind.capitalize()} actualizado.", data={"url": url})


@router.post("/tenant/storefront/publish")
def publish_storefront(
    ctx: TenantScope,
    user: Annotated[UserModel, Depends(require_permissions("storefront.write"))],
    db: Session = Depends(get_db),
):
    """Publicar la tienda en el directorio (exige cumplir los 5 requisitos)."""
    res = StorefrontService(db).publicar(ctx.tenant_id, ctx.user)
    return ApiResponse(message="Tienda publicada en el directorio.", data=res)


@router.post("/tenant/storefront/unpublish")
def unpublish_storefront(
    ctx: TenantScope,
    user: Annotated[UserModel, Depends(require_permissions("storefront.write"))],
    data: dict | None = None,
    db: Session = Depends(get_db),
):
    """Despublicar la tienda temporalmente."""
    reason = data.get("reason") if data else None
    res = StorefrontService(db).despublicar(ctx.tenant_id, reason, ctx.user)
    return ApiResponse(message="Tienda despublicada.", data=res)


@router.get("/tenant/payment-methods")
def list_tenant_payment_methods(
    ctx: TenantScope,
    db: Session = Depends(get_db),
):
    """Listar métodos de cobro configurados por la empresa."""
    data = PaymentMethodsService(db).listar(ctx.tenant_id, publico=False)
    return ApiResponse(data=data)


@router.post("/tenant/payment-methods")
def create_tenant_payment_method(
    data: PaymentMethodIn,
    ctx: TenantScope,
    user: Annotated[UserModel, Depends(require_permissions("payment_methods.write"))],
    db: Session = Depends(get_db),
):
    """Crear un método de cobro propio (QR, transferencia o pago en tienda)."""
    res = PaymentMethodsService(db).crear(ctx.tenant_id, data, ctx.user)
    return ApiResponse(message="Método de cobro creado.", data=res)


@router.patch("/tenant/payment-methods/{method_id}")
def update_tenant_payment_method(
    method_id: UUID,
    data: PaymentMethodIn,
    ctx: TenantScope,
    user: Annotated[UserModel, Depends(require_permissions("payment_methods.write"))],
    db: Session = Depends(get_db),
):
    """Actualizar un método de cobro existente."""
    res = PaymentMethodsService(db).actualizar(method_id, ctx.tenant_id, data, ctx.user)
    return ApiResponse(message="Método de cobro actualizado.", data=res)


@router.post("/tenant/payment-methods/{method_id}/deactivate")
def deactivate_tenant_payment_method(
    method_id: UUID,
    ctx: TenantScope,
    user: Annotated[UserModel, Depends(require_permissions("payment_methods.write"))],
    db: Session = Depends(get_db),
):
    """Desactivar un método de cobro."""
    PaymentMethodsService(db).desactivar(method_id, ctx.tenant_id, ctx.user)
    return ApiResponse(message="Método de cobro desactivado.")


# =========================================================================
# 3. ONBOARDING, USO DEL PLAN Y SOLICITUDES DE AMPLIACIÓN
# =========================================================================

@router.get("/tenant/onboarding")
def get_tenant_onboarding(
    ctx: TenantScope,
    db: Session = Depends(get_db),
):
    """Pasos calculados de puesta en marcha para el panel."""
    data = UsageService(db).onboarding(ctx.tenant_id)
    return ApiResponse(data=data)


@router.get("/tenant/usage")
def get_tenant_usage(
    ctx: TenantScope,
    db: Session = Depends(get_db),
):
    """Consumo de cuotas y límites efectivos del plan."""
    data = UsageService(db).uso(ctx.tenant_id)
    return ApiResponse(data=data)


@router.get("/tenant/upgrade-requests")
def list_tenant_upgrade_requests(
    ctx: TenantScope,
    db: Session = Depends(get_db),
):
    """Historial de solicitudes de ampliación de la empresa."""
    data = UpgradeRequestService(db).listar_tenant(ctx.tenant_id)
    return ApiResponse(data=data)


@router.post("/tenant/upgrade-requests")
def create_tenant_upgrade_request(
    data: UpgradeRequestIn,
    ctx: TenantScope,
    db: Session = Depends(get_db),
):
    """Enviar una solicitud de cambio de plan, ampliación de límite o módulo."""
    res = UpgradeRequestService(db).crear(ctx.tenant_id, ctx.user, data)
    return ApiResponse(message="Solicitud de ampliación enviada.", data=res)


@router.get("/tenant/catalog-templates")
def list_tenant_catalog_templates(
    ctx: TenantScope,
    user: Annotated[UserModel, Depends(require_permissions("catalog.write"))],
    db: Session = Depends(get_db),
):
    """Listar plantillas de catálogo globales disponibles para importar."""
    data = CatalogTemplateService(db).listar()
    return ApiResponse(data=data)


@router.post("/tenant/catalog-templates/{code}/import")
def import_tenant_catalog_template(
    code: str,
    ctx: TenantScope,
    user: Annotated[UserModel, Depends(require_permissions("catalog.write"))],
    db: Session = Depends(get_db),
):
    """Importar categorías, tallas y colores de una plantilla al catálogo propio."""
    res = CatalogTemplateService(db).importar(ctx.tenant_id, code, ctx.user)
    return ApiResponse(message=res.message, data=res)


# =========================================================================
# 4. CONSOLA DE PLATAFORMA: PLANTILLAS Y SOLICITUDES GLOBALES
# =========================================================================

@router.get("/platform/catalog-templates")
def list_platform_catalog_templates(
    ctx: AccessContext = Depends(get_access_context),
    user: Annotated[UserModel, Depends(require_permissions("catalog_templates.write"))] = None,
    db: Session = Depends(get_db),
):
    """Listado global de plantillas de catálogo y su uso."""
    data = CatalogTemplateService(db).listar()
    return ApiResponse(data=data)


@router.post("/platform/catalog-templates")
def create_platform_catalog_template(
    data: CatalogTemplateIn,
    ctx: AccessContext = Depends(get_access_context),
    user: Annotated[UserModel, Depends(require_permissions("catalog_templates.write"))] = None,
    db: Session = Depends(get_db),
):
    """Crear una nueva plantilla global de catálogo."""
    res = CatalogTemplateService(db).crear(data, ctx.user)
    return ApiResponse(message="Plantilla creada.", data=res)


@router.patch("/platform/catalog-templates/{template_id}")
def update_platform_catalog_template(
    template_id: UUID,
    data: CatalogTemplateIn,
    ctx: AccessContext = Depends(get_access_context),
    user: Annotated[UserModel, Depends(require_permissions("catalog_templates.write"))] = None,
    db: Session = Depends(get_db),
):
    """Actualizar una plantilla de catálogo existente."""
    res = CatalogTemplateService(db).actualizar(template_id, data, ctx.user)
    return ApiResponse(message="Plantilla actualizada.", data=res)


@router.get("/platform/upgrade-requests")
def list_platform_upgrade_requests(
    status: str | None = Query(None, max_length=15),
    ctx: AccessContext = Depends(get_access_context),
    user: Annotated[UserModel, Depends(require_permissions("upgrade_requests.manage"))] = None,
    db: Session = Depends(get_db),
):
    """Bandeja de solicitudes de ampliación para la plataforma."""
    data = UpgradeRequestService(db).listar_plataforma(status)
    return ApiResponse(data=data)


@router.post("/platform/upgrade-requests/{request_id}/handle")
def handle_platform_upgrade_request(
    request_id: UUID,
    data: HandleUpgradeRequestIn,
    ctx: AccessContext = Depends(get_access_context),
    user: Annotated[UserModel, Depends(require_permissions("upgrade_requests.manage"))] = None,
    db: Session = Depends(get_db),
):
    """Atender y marcar como completada una solicitud de ampliación."""
    res = UpgradeRequestService(db).atender(request_id, ctx.user, data.response)
    return ApiResponse(message="Solicitud atendida.", data=res)


@router.post("/platform/upgrade-requests/{request_id}/reject")
def reject_platform_upgrade_request(
    request_id: UUID,
    data: HandleUpgradeRequestIn,
    ctx: AccessContext = Depends(get_access_context),
    user: Annotated[UserModel, Depends(require_permissions("upgrade_requests.manage"))] = None,
    db: Session = Depends(get_db),
):
    """Rechazar una solicitud de ampliación con motivo."""
    res = UpgradeRequestService(db).rechazar(request_id, ctx.user, data.response)
    return ApiResponse(message="Solicitud rechazada.", data=res)


@router.patch("/platform/tenants/{tenant_id}/storefront")
def moderate_platform_tenant_storefront(
    tenant_id: UUID,
    data: PlatformStorefrontUpdate,
    ctx: AccessContext = Depends(get_access_context),
    user: Annotated[UserModel, Depends(require_permissions("tenants.write"))] = None,
    db: Session = Depends(get_db),
):
    """Moderación de tienda desde la consola (destacar o despublicar por infracción)."""
    srv = StorefrontService(db)
    if data.is_featured is not None:
        tenant = srv._get_tenant(tenant_id)
        tenant.is_featured = data.is_featured
        db.commit()

    if data.unpublish_reason:
        srv.despublicar(tenant_id, reason=data.unpublish_reason, actor=ctx.user)

    res = srv.obtener(tenant_id)
    return ApiResponse(message="Tienda actualizada por plataforma.", data=res)
