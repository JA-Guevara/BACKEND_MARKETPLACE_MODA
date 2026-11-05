"""Registros de operación sin cuerpos, credenciales ni datos personales."""
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import logging
import re
import time
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
_SENSITIVE = re.compile(r'''(?ix)
    (?:authorization|proxy-authorization|password(?:_hash)?|passwd|(?:access_|refresh_)?token|secret|cookie|set-cookie|api[_-]?key)
    ["']?\s*[:=]\s*(?:"[^"]*"|'[^']*'|[^\s,;\r\n]+(?:\s+[^\s,;\r\n]+)?)
''')
_EMAIL = re.compile(r"([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_URL = re.compile(r"\b(?:postgres(?:ql)?(?:\+\w+)?|https?)://[^\s\"'<>]+", re.I)


def redact(value: str) -> str:
    value = _URL.sub("[url omitida]", value)
    value = _SENSITIVE.sub("[dato protegido]", value)
    return _EMAIL.sub(lambda m: m[1][:2] + "***@" + m[2], value)


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "nivel": record.levelname, "logger": record.name,
            "mensaje": redact(record.getMessage()),
            "request_id": getattr(record, "request_id", None) or request_id_context.get(),
            "tenant_id": getattr(record, "tenant_id", None),
            "user_ref": getattr(record, "user_ref", None),
            "ruta": getattr(record, "ruta", None), "estado": getattr(record, "estado", None),
            "ms": getattr(record, "ms", None),
        }
        if record.exc_info:
            # Excepciones SQL/HTTP pueden incluir filas, DSN o cabeceras.
            data["exception_type"] = record.exc_info[0].__name__
        return json.dumps(data, ensure_ascii=False)


class LocalFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        suffix = f" [{record.exc_info[0].__name__}]" if record.exc_info else ""
        return f"{record.levelname} {record.name} {redact(record.getMessage())}{suffix}"


def configurar_logging(settings) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RedactFilter())
    handler.setFormatter(JsonFormatter() if settings.app_env in {"staging", "production"}
                         else LocalFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
    # Nuestro middleware registra la plantilla de ruta; uvicorn registra la URL
    # literal, incluyendo valores y query strings. No duplicar ese acceso.
    logging.getLogger("uvicorn.access").disabled = True


def iniciar_sentry(settings) -> None:
    if not settings.sentry_dsn or not settings.sentry_dsn.get_secret_value():
        return
    import sentry_sdk

    def before_send(event, hint):
        event.pop("user", None)
        event.pop("request", None)
        event.pop("breadcrumbs", None)
        event.pop("extra", None)
        for entry in event.get("exception", {}).get("values", []):
            entry["value"] = "Error capturado; consultar request_id en registros protegidos."
            for frame in entry.get("stacktrace", {}).get("frames", []):
                frame.pop("vars", None)
        if "message" in event:
            event["message"] = redact(str(event["message"]))
        return event

    sentry_sdk.init(dsn=settings.sentry_dsn.get_secret_value(), send_default_pii=False,
                    environment=settings.app_env, traces_sample_rate=0.1,
                    include_local_variables=False, before_send=before_send)


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        supplied = dict(scope.get("headers", [])).get(b"x-request-id", b"").decode("latin-1")
        # IDs de correlación son UUID/hex, no texto arbitrario o direcciones.
        rid = supplied if re.fullmatch(r"[A-Fa-f0-9]{32}|[A-Fa-f0-9]{8}(?:-[A-Fa-f0-9]{4}){3}-[A-Fa-f0-9]{12}", supplied) else uuid4().hex
        scope.setdefault("state", {})["request_id"] = rid
        token = request_id_context.set(rid)
        start = time.monotonic()
        status = 500

        async def traced(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = rid
            await send(message)

        try:
            await self.app(scope, receive, traced)
        finally:
            if status >= 500:
                app_state = scope["app"].state
                app_state.server_error_count = getattr(app_state, "server_error_count", 0) + 1
            if scope["path"] not in {"/health", "/health/ready"}:
                route = scope.get("route")
                logging.getLogger("fashionstore.access").info("request_completed", extra={
                    "request_id": rid, "ruta": getattr(route, "path", "<unmatched>"),
                    "estado": status, "ms": round((time.monotonic() - start) * 1000, 2),
                    "tenant_id": scope["state"].get("tenant_id"),
                    "user_ref": hashlib.sha256(str(scope["state"]["actor_id"]).encode()).hexdigest()[:12]
                    if scope["state"].get("actor_id") else None,
                })
            request_id_context.reset(token)
