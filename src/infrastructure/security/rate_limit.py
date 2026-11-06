"""Límite de peticiones.

Sin REDIS_URL: ventanas deslizantes por proceso (una réplica y un worker).
Con REDIS_URL y conexión: ventana fija compartida entre workers y réplicas.
"""
from collections import deque
from dataclasses import dataclass
import hashlib
import json
import math
import os
import re
from threading import Lock
import time

import anyio

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.auth.infrastructure.security.jwt_service import JWTService
from src.infrastructure.cache.redis import RedisCacheWrapper, get_cache
from src.infrastructure.config.settings import settings
from src.shared.exceptions.domain_exception import AuthenticationError


@dataclass(frozen=True)
class Politica:
    nombre: str
    limite: int
    ventana_s: int


class RateLimiter:
    def __init__(self, clock=time.monotonic, max_keys: int = 50_000) -> None:
        self.clock = clock
        self.max_keys = max_keys
        self.buckets: dict[tuple[str, str], tuple[deque, int]] = {}
        self.lock = Lock()
        self.calls = 0

    def permitir(self, clave: str, politica: Politica) -> tuple[bool, int, int]:
        now = self.clock()
        key = (politica.nombre, clave)
        with self.lock:
            self.calls += 1
            if self.calls % 128 == 0 or len(self.buckets) >= self.max_keys:
                stale = [k for k, (q, window) in self.buckets.items() if not q or q[-1] <= now - window]
                for k in stale:
                    del self.buckets[k]
            if key not in self.buckets and len(self.buckets) >= self.max_keys:
                return False, 0, 60
            q, _ = self.buckets.setdefault(key, (deque(), politica.ventana_s))
            while q and q[0] <= now - politica.ventana_s:
                q.popleft()
            if len(q) >= politica.limite:
                return False, 0, max(1, math.ceil(q[0] + politica.ventana_s - now))
            q.append(now)
            return True, politica.limite - len(q), 0


class RedisRateLimiter:
    """Ventana fija compartida en Redis (INCR + EXPIRE). Si Redis falla, el
    envoltorio cae a memoria: degrada a límite por proceso, nunca abre la puerta."""

    distribuido = True

    def __init__(self, cache: RedisCacheWrapper, clock=time.time) -> None:
        self.cache = cache
        self.clock = clock

    def permitir(self, clave: str, politica: Politica) -> tuple[bool, int, int]:
        now = self.clock()
        window = int(now // politica.ventana_s)
        count = self.cache.incr(f"fs_rl:{politica.nombre}:{window}:{clave}", window_seconds=politica.ventana_s)
        if count > politica.limite:
            return False, 0, max(1, math.ceil((window + 1) * politica.ventana_s - now))
        return True, politica.limite - count, 0


def crear_limitador() -> "RateLimiter | RedisRateLimiter":
    if os.getenv("REDIS_URL", "").strip():
        cache = get_cache()
        if cache.is_connected:
            return RedisRateLimiter(cache)
    return RateLimiter()


def _key(*values: str) -> str:
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.limiter = crear_limitador()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not settings.rate_limit_enabled:
            await self.app(scope, receive, send)
            return
        path = scope["path"].rstrip("/")
        prefix = settings.api_v1_prefix
        method = scope["method"]
        if path in {"/health", "/health/ready"} or (method == "POST" and path == prefix + "/platform/ops/backups"):
            await self.app(scope, receive, send)
            return
        ip = (scope.get("client") or ("unknown",))[0]
        headers = dict(scope.get("headers", []))
        state = scope["app"].state

        async def check(policy: Politica, key: str) -> tuple[int, int] | None:
            if getattr(self.limiter, "distribuido", False):
                # Redis es E/S de red: fuera del bucle de eventos.
                ok, remaining, wait = await anyio.to_thread.run_sync(self.limiter.permitir, key, policy)
            else:
                ok, remaining, wait = self.limiter.permitir(key, policy)
            if ok:
                return policy.limite, remaining
            state.rate_limited_count = getattr(state, "rate_limited_count", 0) + 1
            counts = getattr(state, "rate_limited_by_policy", {})
            counts[policy.nombre] = counts.get(policy.nombre, 0) + 1
            state.rate_limited_by_policy = counts
            response = JSONResponse(status_code=429,
                content={"success": False, "error": {"code": "rate_limited", "message": f"Demasiadas solicitudes. Reintenta en {wait} segundos."}},
                headers={"Retry-After": str(wait), "X-RateLimit-Limit": str(policy.limite), "X-RateLimit-Remaining": "0"})
            await response(scope, receive, send)
            return None

        result = await check(Politica("api_ip", 300, 60), _key(ip))
        if result is None:
            return
        payload = {}
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        if authorization.lower().startswith("bearer "):
            try:
                payload = JWTService().decode(authorization[7:], "access")
            except AuthenticationError:
                pass
        user = str(payload.get("sub") or ip)
        tenant = str(payload.get("tid") or user)
        policies: list[tuple[Politica, str]] = []
        if method == "POST" and path == prefix + "/auth/login":
            policies.append((Politica("login_ip", 20, 60), _key(ip)))
        body_paths = {prefix + p for p in ("/auth/login", "/auth/forgot-password", "/auth/password-reset/request", "/sync/batch")}
        replay: list[Message] = []
        body = {}
        if method == "POST" and path in body_paths:
            chunks = bytearray()
            while True:
                message = await receive()
                replay.append(message)
                chunks.extend(message.get("body", b"")[:16385-len(chunks)])
                if len(chunks) > 16384 or message["type"] != "http.request" or not message.get("more_body"):
                    break
            if len(chunks) <= 16384:
                try:
                    candidate = json.loads(chunks)
                    body = candidate if isinstance(candidate, dict) else {}
                except (ValueError, UnicodeError):
                    pass
        if method == "POST" and path == prefix + "/auth/login":
            policies.append((Politica("login_email_ip", 5, 60), _key(ip, str(body.get("email", ""))[:320].strip().casefold())))
        elif method == "POST" and path == prefix + "/auth/register":
            policies.append((Politica("register_ip", 5, 3600), _key(ip)))
        elif method == "POST" and path in {prefix + "/auth/forgot-password", prefix + "/auth/password-reset/request"}:
            policies.append((Politica("password_email", 3, 900), _key(str(body.get("email", ""))[:320].strip().casefold())))
        elif method == "POST" and path == prefix + "/auth/mfa/verify":
            policies.append((Politica("mfa_user", 5, 900), _key(user)))
        elif method == "POST" and path == prefix + "/commerce/assistant/transcribe":
            # Primero la cuota individual: un usuario que ya la agotó no debe
            # consumir el cupo de voz compartido con sus compañeros.
            policies.extend((
                (Politica("ai_voice", 5, 60), _key("voice_user", user)),
                (Politica("ai_voice", 10, 60), _key("voice_tenant", tenant)),
            ))
        elif method == "POST" and (
            re.fullmatch(re.escape(prefix) + r"/analytics/(?:ai-reports|assistant)(?:/.*)?", path)
            or path == prefix + "/commerce/assistant"
        ):
            # definitions/history son GET y no consumen el cupo costoso.
            policies.append((Politica("ai_tenant", 20, 60), _key(tenant)))
        elif method == "POST" and path == prefix + "/sync/batch":
            # El dispositivo sin autenticación no puede abrir nuevas cuotas.
            device = str(body.get("device_id", ""))[:200] if payload else ""
            policies.append((Politica("sync_device", 30, 60), _key(user, device)))
        if method != "OPTIONS" and re.search(
            r"/(?:export|export-multiple|multi-export|data-exports)$|\.(?:csv|xlsx|pdf)$",
            path, re.IGNORECASE,
        ):
            policies.append((Politica("export_tenant", 10, 600), _key(tenant)))
        for policy, key in policies:
            checked = await check(policy, key)
            if checked is None:
                return
            if checked[1] < result[1]:
                result = checked

        async def replay_receive() -> Message:
            return replay.pop(0) if replay else await receive()

        async def limited_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                outgoing = MutableHeaders(scope=message)
                outgoing["X-RateLimit-Limit"] = str(result[0])
                outgoing["X-RateLimit-Remaining"] = str(result[1])
            await send(message)

        await self.app(scope, replay_receive, limited_send)
