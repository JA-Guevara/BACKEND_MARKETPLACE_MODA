from uuid import uuid4
import logging
from sqlalchemy.exc import SQLAlchemyError
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.config.routes import api_router
from src.infrastructure.config.settings import settings
from src.infrastructure.cors.config import configure_cors
from src.shared.context.audit_context import reset_audit_context, set_audit_context
from src.shared.exceptions.base_exception import AppException


class AuditContextMiddleware:
    """Captura IP y user-agent de cada request HTTP para que la bitacora
    pueda registrarlos automaticamente, sin que cada servicio tenga que
    pasarlos explicitamente."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        token = None
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            user_agent = headers.get(b"user-agent")
            client = scope.get("client")
            token = set_audit_context(
                client[0] if client else None,
                user_agent.decode("latin-1")[:500] if user_agent else None,
                str(uuid4()),
            )
        try:
            await self.app(scope, receive, send)
        finally:
            if token is not None:
                reset_audit_context(token)


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, debug=settings.debug, version="1.0.0")
    configure_cors(app)
    app.add_middleware(AuditContextMiddleware)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.exception_handler(AppException)
    async def handle_app_exception(_: Request, exc: AppException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": {"code": exc.code, "message": exc.message, "details": exc.details},
            },
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(part) for part in error["loc"] if part != "body"),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error": {
                    "code": "validation_error",
                    "message": "Los datos enviados no son validos.",
                    "details": details,
                },
            },
        )

    @app.exception_handler(SQLAlchemyError)
    async def handle_database_error(_: Request, exc: SQLAlchemyError) -> JSONResponse:
        reference = uuid4().hex[:12]
        original = getattr(exc, "orig", None)
        diagnostic = getattr(original, "diag", None)
        logging.getLogger(__name__).error(
            "Database failure reference=%s type=%s sqlstate=%s table=%s",
            reference, type(exc).__name__,
            getattr(original, "sqlstate", None) or getattr(original, "pgcode", None),
            getattr(diagnostic, "table_name", None),
        )
        return JSONResponse(status_code=503, content={
            "success": False,
            "error": {"code": "database_unavailable", "message": "El servicio de datos no está disponible. Reintentá en unos momentos. Referencia: " + reference}
        })

    return app


app = create_app()
