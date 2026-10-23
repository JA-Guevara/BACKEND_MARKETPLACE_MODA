from fastapi import APIRouter
from src.plataforma_saas.web.routers.tenants_router import router as tenants_router
from src.plataforma_saas.web.routers.plans_router import router as plans_router
from src.plataforma_saas.web.routers.subscriptions_router import platform_router, tenant_router

plataforma_router = APIRouter()
for router in (tenants_router, plans_router, platform_router, tenant_router):
    plataforma_router.include_router(router)
