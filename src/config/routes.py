from fastapi import APIRouter

from src.auth.infrastructure.http.router import router as auth_router
from src.bitacora.web.router import router as audit_router
from src.inventario_sucursales.web.router import router as organization_router
from src.usuarios_catalogo.web.router import router as users_catalog_router


api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(users_catalog_router)
api_router.include_router(organization_router)
api_router.include_router(audit_router)
