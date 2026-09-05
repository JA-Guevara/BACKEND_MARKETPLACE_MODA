from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.config.routes import api_router
from src.infrastructure.config.settings import settings
from src.infrastructure.cors.config import configure_cors
from src.shared.exceptions.base_exception import AppException


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, debug=settings.debug, version="1.0.0")
    configure_cors(app)
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

    return app


app = create_app()
