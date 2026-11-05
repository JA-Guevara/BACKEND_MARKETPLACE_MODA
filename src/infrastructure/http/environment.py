"""Comunica al cliente el ambiente efectivo de esta API."""
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class EnvironmentHeaderMiddleware:
    def __init__(self, app: ASGIApp, env: str) -> None:
        self.app = app
        self.env = env

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_environment(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-App-Env"] = self.env
            await send(message)

        await self.app(scope, receive, send_with_environment)
