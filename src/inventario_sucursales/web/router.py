from fastapi import APIRouter

from src.inventario_sucursales.web.routers.organization_router import router as organization_router


router = APIRouter()
router.include_router(organization_router)
