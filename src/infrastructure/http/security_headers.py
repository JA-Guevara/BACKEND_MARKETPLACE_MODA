from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.infrastructure.config.settings import settings


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def secured(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
                headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
                if settings.app_env == "production":
                    headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
                path = scope.get("path", "")
                if any(path == settings.api_v1_prefix + prefix or path.startswith(settings.api_v1_prefix + prefix + "/")
                       for prefix in ("/auth", "/platform")):
                    headers["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, secured if scope["type"] == "http" else send)
