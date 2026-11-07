from fastapi import APIRouter

from src.auth.infrastructure.http.router import router as auth_router
from src.bitacora.web.router import router as audit_router
from src.inventario_sucursales.web.router import router as organization_router
from src.usuarios_catalogo.web.router import router as users_catalog_router
from src.shared.bulk.router import router as bulk_router
from src.usuarios_catalogo.web.routers.media_router import router as media_router
from src.ventas_pagos.web.router import router as commerce_router, analytics_router
from src.reservas.web.router import router as reservations_router
from src.probador_virtual.web.router import router as vestidor_router
from src.tryon_ai_jobs.web.router import router as tryon_ai_router
from src.notificaciones.web.router import router as notifications_router
from src.ventas_pagos.web.engagement_router import router as engagement_router


api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(users_catalog_router)
api_router.include_router(organization_router)
api_router.include_router(audit_router)
api_router.include_router(bulk_router)
api_router.include_router(media_router)
api_router.include_router(commerce_router)
api_router.include_router(analytics_router)
api_router.include_router(reservations_router)
api_router.include_router(vestidor_router)
api_router.include_router(tryon_ai_router)
api_router.include_router(notifications_router)
api_router.include_router(engagement_router)

from src.plataforma_saas.web.router import plataforma_router
from src.plataforma_saas.web.routers.ops_router import router as ops_router
from src.plataforma_saas.web.routers.tenant_admin_router import router as tenant_admin_router
from src.operacion_offline.web.router import router as offline_router
api_router.include_router(plataforma_router)
api_router.include_router(ops_router)
api_router.include_router(tenant_admin_router)
api_router.include_router(offline_router)

from src.operacion_offline.web.sync_router import router as sync_router
api_router.include_router(sync_router)

from src.dispositivos.web.router import router as devices_router
api_router.include_router(devices_router)

from src.analitica_ml.web.router import router as ml_router, platform_ml_router
api_router.include_router(ml_router)
api_router.include_router(platform_ml_router)

from src.ventas_pagos.web.exchanges_router import router as exchanges_router
api_router.include_router(exchanges_router)

from src.reportes_ia.web.router import router as ai_reports_router
api_router.include_router(ai_reports_router)

from src.integraciones.web.router import router as integrations_router
api_router.include_router(integrations_router)
from src.integraciones.web.api_v1_router import router as integrations_v1_router
from src.plataforma_saas.web.routers.stripe_saas_router import router as stripe_saas_router
api_router.include_router(integrations_v1_router)
api_router.include_router(stripe_saas_router)
from src.plataforma_saas.web.routers.analytics_router import router as platform_analytics_router
api_router.include_router(platform_analytics_router)
from src.plataforma_saas.web.routers.tenant_backups_router import router as tenant_backups_router
api_router.include_router(tenant_backups_router)
