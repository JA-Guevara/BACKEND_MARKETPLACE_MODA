from fastapi import APIRouter
from src.plataforma_saas.web.routers.console_router import router as console_router
from src.plataforma_saas.web.routers.platform_users_router import router as platform_users_router
from src.plataforma_saas.web.routers.platform_audit_router import router as platform_audit_router
from src.plataforma_saas.web.routers.tenants_router import router as tenants_router
from src.plataforma_saas.web.routers.plans_router import router as plans_router
from src.plataforma_saas.web.routers.subscriptions_router import platform_router, tenant_router
from src.plataforma_saas.web.routers.support_router import router as support_router

plataforma_router = APIRouter()
for router in (
    console_router,
    platform_users_router,
    platform_audit_router,
    tenants_router,
    plans_router,
    platform_router,
    tenant_router,
    support_router,
):
    plataforma_router.include_router(router)
