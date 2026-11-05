"""Bloquea cambios durante una ventana de mantenimiento."""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from src.infrastructure.config.settings import settings
from src.shared.exceptions.domain_exception import MaintenanceError


def maintenance_response() -> JSONResponse:
    error = MaintenanceError()
    return JSONResponse(
        status_code=error.status_code,
        headers={"Retry-After": "300"},
        content={
            "success": False,
            "error": {"code": error.code, "message": error.message, "details": None},
        },
    )


class MaintenanceMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and settings.maintenance_mode:
            method = scope["method"]
            path = scope["path"].rstrip("/")
            api_prefix = settings.api_v1_prefix
            ops_path = f"{api_prefix}/platform/ops"
            if method == "POST" and path == f"{api_prefix}/auth/login":
                # La cuenta real se comprueba antes de que el servicio de
                # autenticación emita tokens o escriba intentos de la empresa.
                scope.setdefault("state", {})["maintenance_platform_only"] = True
            elif (
                method not in {"GET", "HEAD", "OPTIONS"}
                and path not in {"/health", ops_path}
                and not path.startswith(("/health/", f"{ops_path}/"))
            ):
                await maintenance_response()(scope, receive, send)
                return

        await self.app(scope, receive, send)
