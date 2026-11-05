"""Módulo de caché Redis opcional para FashionStore SaaS.

Solo si REDIS_URL existe y la librería redis está disponible, utiliza Redis
para:
- Caché del catálogo público (TTL 60 s).
- Límite de peticiones distribuido (PS1.1).
- Caché de IA (PX1.7).

Sin REDIS_URL o sin conexión, todo continúa funcionando en memoria de forma transparente.
"""
from collections.abc import Callable
import os
import threading
import time
from typing import Any

try:
    import redis
except ImportError:
    redis = None


class InMemoryCache:
    """Caché LRU/TTL en memoria para fallback sin Redis."""

    def __init__(self, max_entries: int = 1000):
        self._store: dict[str, tuple[str, float]] = {}
        self._counters: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()
        self._max_entries = max_entries

    def get(self, key: str) -> str | None:
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            val, expires_at = entry
            if time.time() > expires_at:
                del self._store[key]
                return None
            return val

    def set(self, key: str, value: str, ex: int = 60) -> None:
        with self._lock:
            if len(self._store) >= self._max_entries:
                # Expulsar elementos vencidos o el más antiguo
                ahora = time.time()
                vencidos = [k for k, (_, exp) in self._store.items() if ahora > exp]
                for k in vencidos:
                    del self._store[k]
                if len(self._store) >= self._max_entries and self._store:
                    del self._store[next(iter(self._store))]

            self._store[key] = (str(value), time.time() + ex)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)
            self._counters.pop(key, None)

    def incr(self, key: str, window_seconds: int = 60) -> int:
        with self._lock:
            ahora = time.time()
            count, expires_at = self._counters.get(key, (0, ahora + window_seconds))
            if ahora > expires_at:
                count = 0
                expires_at = ahora + window_seconds
            new_count = count + 1
            self._counters[key] = (new_count, expires_at)
            return new_count


class RedisCacheWrapper:
    """Envoltorio que abstrae llamadas a Redis real o memoria."""

    def __init__(self, redis_url: str | None = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL")
        self._memory = InMemoryCache()
        self._client: Any = None
        self._init_client()

    def _init_client(self) -> None:
        if self.redis_url and redis is not None:
            try:
                self._client = redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                )
                self._client.ping()
            except Exception:
                self._client = None
        else:
            self._client = None

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    def get(self, key: str) -> str | None:
        if self._client:
            try:
                return self._client.get(key)
            except Exception:
                pass
        return self._memory.get(key)

    def set(self, key: str, value: str, ex: int = 60) -> None:
        if self._client:
            try:
                self._client.set(key, value, ex=ex)
                return
            except Exception:
                pass
        self._memory.set(key, value, ex=ex)

    def delete(self, key: str) -> None:
        if self._client:
            try:
                self._client.delete(key)
                return
            except Exception:
                pass
        self._memory.delete(key)

    def incr(self, key: str, window_seconds: int = 60) -> int:
        """Incrementa un contador para limitación de tasa distribuida."""
        if self._client:
            try:
                pipe = self._client.pipeline()
                pipe.incr(key)
                pipe.expire(key, window_seconds)
                results = pipe.execute()
                return int(results[0])
            except Exception:
                pass
        return self._memory.incr(key, window_seconds=window_seconds)


_global_cache: RedisCacheWrapper | None = None


def get_cache() -> RedisCacheWrapper:
    """Devuelve la instancia global de caché (Redis o memoria)."""
    global _global_cache
    if _global_cache is None:
        _global_cache = RedisCacheWrapper()
    return _global_cache


def cache_catalogo_publico(key: str, getter_fn: Callable[[], str], ttl: int = 60) -> str:
    """Caché para el catálogo público con TTL de 60 segundos."""
    cache = get_cache()
    full_key = f"fs_cat_pub_{key}"
    cached = cache.get(full_key)
    if cached is not None:
        return cached
    computed = getter_fn()
    cache.set(full_key, computed, ex=ttl)
    return computed
