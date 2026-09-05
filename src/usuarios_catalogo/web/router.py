from fastapi import APIRouter

from src.roles.web.router import router as roles_router
from src.usuarios.web.router import router as users_router
from src.usuarios_catalogo.web.routers.catalog_router import router as catalog_router


router = APIRouter()
router.include_router(users_router)
router.include_router(roles_router)
router.include_router(catalog_router)
