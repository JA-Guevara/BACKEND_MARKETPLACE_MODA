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
