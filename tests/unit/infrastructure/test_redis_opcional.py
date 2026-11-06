"""O1.4 · Redis opcional: con REDIS_URL y conexión se comparte estado; sin él, memoria como antes.

No usa red ni la librería redis: un envoltorio falso imita a RedisCacheWrapper.
"""
from src.infrastructure.cache.redis import InMemoryCache
from src.infrastructure.security import rate_limit
from src.infrastructure.security.rate_limit import Politica, RateLimiter, RedisRateLimiter, crear_limitador
from src.reportes_ia.application import cache_interpretaciones as cache_mod
from src.reportes_ia.application.cache_interpretaciones import CacheInterpretaciones


class RedisFalso:
    """Mismo contrato que RedisCacheWrapper; un único almacén compartido simula varias réplicas."""

    def __init__(self, conectado: bool = True) -> None:
        self.is_connected = conectado
        self._mem = InMemoryCache()
        self.claves: list[str] = []

    def get(self, key):
        return self._mem.get(key)

    def set(self, key, value, ex=60):
        self.claves.append(key)
        self._mem.set(key, value, ex=ex)

    def incr(self, key, window_seconds=60):
        self.claves.append(key)
        return self._mem.incr(key, window_seconds=window_seconds)


def test_sin_redis_url_se_usa_el_limitador_en_memoria(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert type(crear_limitador()) is RateLimiter


def test_redis_url_sin_conexion_cae_a_memoria(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://example.invalid:6379/0")
    monkeypatch.setattr(rate_limit, "get_cache", lambda: RedisFalso(conectado=False))
    assert type(crear_limitador()) is RateLimiter


def test_limite_compartido_entre_dos_workers(monkeypatch):
    compartido = RedisFalso()
    monkeypatch.setenv("REDIS_URL", "redis://example.invalid:6379/0")
    monkeypatch.setattr(rate_limit, "get_cache", lambda: compartido)
    worker_a, worker_b = crear_limitador(), crear_limitador()
    assert isinstance(worker_a, RedisRateLimiter)
    worker_a.clock = worker_b.clock = lambda: 1_000.0
    politica = Politica("login_ip", 3, 60)
    resultados = [w.permitir("ip-1", politica)[0] for w in (worker_a, worker_b, worker_a, worker_b)]
    assert resultados == [True, True, True, False]
    ok, restante, espera = worker_b.permitir("ip-1", politica)
    assert (ok, restante) == (False, 0) and 1 <= espera <= 60
    # Otra clave no comparte cupo
    assert worker_a.permitir("ip-2", politica)[0] is True


def test_cache_ia_en_redis_aislada_por_empresa_y_sin_texto(monkeypatch):
    compartido = RedisFalso()
    monkeypatch.setenv("REDIS_URL", "redis://example.invalid:6379/0")
    monkeypatch.setattr(cache_mod, "get_cache", lambda: compartido)
    replica_1, replica_2 = CacheInterpretaciones(), CacheInterpretaciones()
    interpretacion = {"status": "READY", "spec": {"report": "ventas"}, "prompt": "texto original", "rows": [1]}
    replica_1.set("empresa-a", "Ventas del mes", interpretacion)
    leida = replica_2.get("empresa-a", "ventas   DEL mes")
    assert leida is not None and leida["spec"] == {"report": "ventas"}
    assert "prompt" not in leida and "rows" not in leida
    assert replica_2.get("empresa-b", "Ventas del mes") is None
    assert all(k.startswith("fs_ia_interp:empresa-a:") for k in compartido.claves)
    assert replica_1.stats()["tenants_cached"] == 0  # nada quedó en memoria


def test_cache_ia_sin_redis_sigue_en_memoria(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    cache = CacheInterpretaciones()
    cache.set("empresa-a", "Ventas del mes", {"status": "READY", "spec": {"report": "ventas"}})
    assert cache.get("empresa-a", "Ventas del mes")["spec"] == {"report": "ventas"}
    assert cache.stats()["tenants_cached"] == 1
