from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import time
from typing import Any, Callable
import unicodedata
import uuid

from src.reportes_ia.domain.especificacion import InterpretResult, ReportSpec


def normalizar_texto_cache(texto: str) -> str:
    """
    Normaliza el texto para la clave de caché:
    - Minúsculas
    - Sin tildes / diacríticos
    - Espacios colapsados y sin signos de puntuación periféricos
    - Conserva términos clave para la resolución posterior
    """
    if not texto:
        return ""
    texto = texto.lower().strip()
    nfkd = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(c for c in nfkd if not unicodedata.combining(c))
    # Limpiar signos repetidos o periféricos
    palabras = sin_tildes.split()
    return " ".join(palabras)


class CacheInterpretaciones:
    """
    Caché en memoria de interpretaciones de reportes con IA por empresa (PX1.7).
    Reglas fundamentales:
    - RN22: Guarda SOLO la interpretación validada (tipo de reporte, filtros, agrupación),
      NUNCA resultados, datos de la empresa ni el texto original del pedido.
    - Clave: sha256(tenant_id | texto normalizado | versión del esquema de reportes).
    - TTL: 24 horas (86400 segundos).
    - Capacidad: máximo 500 entradas por empresa (LRU con OrderedDict).
    - Aislamiento estricto: la empresa B no accede jamás a las claves de A.
    """

    def __init__(self, max_entries_per_tenant: int = 500, ttl_seconds: int = 86400) -> None:
        self.max_entries_per_tenant = max_entries_per_tenant
        self.ttl_seconds = ttl_seconds
        # tenant_id_str -> OrderedDict[key_sha256, {timestamp, interpretation}]
        self._stores: dict[str, OrderedDict[str, dict[str, Any]]] = {}
        self.hits: int = 0
        self.misses: int = 0

    def _get_tenant_store(self, tenant_id_str: str) -> OrderedDict[str, dict[str, Any]]:
        if tenant_id_str not in self._stores:
            self._stores[tenant_id_str] = OrderedDict()
        return self._stores[tenant_id_str]

    def build_key(self, tenant_id: uuid.UUID | str, prompt: str, schema_version: str = "v1") -> str:
        tid = str(tenant_id)
        norm = normalizar_texto_cache(prompt)
        raw = f"{tid}|{norm}|{schema_version}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(
        self,
        tenant_id: uuid.UUID | str,
        prompt: str,
        schema_version: str = "v1",
    ) -> dict[str, Any] | None:
        tid = str(tenant_id)
        key = self.build_key(tenant_id, prompt, schema_version)
        store = self._stores.get(tid)
        if not store or key not in store:
            self.misses += 1
            return None

        entry = store[key]
        now = time.time()
        if (now - entry["timestamp"]) > self.ttl_seconds:
            # Entrada expirada
            store.pop(key, None)
            self.misses += 1
            return None

        # Hit: mover al final (más reciente)
        store.move_to_end(key)
        self.hits += 1
        return deepcopy(entry["interpretation"])

    def set(
        self,
        tenant_id: uuid.UUID | str,
        prompt: str,
        interpretacion: dict[str, Any] | InterpretResult,
        schema_version: str = "v1",
    ) -> None:
        tid = str(tenant_id)
        key = self.build_key(tenant_id, prompt, schema_version)
        store = self._get_tenant_store(tid)

        # Sanitizar estrictamente: RN22 prohíbe guardar texto original o resultados de consulta
        if isinstance(interpretacion, InterpretResult):
            raw_dict = interpretacion.model_dump(mode="json")
        elif isinstance(interpretacion, dict):
            raw_dict = deepcopy(interpretacion)
        else:
            return

        sanitized: dict[str, Any] = {
            "status": raw_dict.get("status", "READY"),
            "spec": raw_dict.get("spec"),
            "questions": raw_dict.get("questions", []),
            "assumptions": raw_dict.get("assumptions", []),
            "suggestions": raw_dict.get("suggestions", []),
            "interpreter": raw_dict.get("interpreter", "CACHE"),
        }

        # Asegurar que no contenga claves prohibidas
        for prohibited in ("text", "prompt", "results", "rows", "execution_result", "data", "request_id", "raw_text"):
            sanitized.pop(prohibited, None)
            if isinstance(sanitized.get("spec"), dict):
                sanitized["spec"].pop(prohibited, None)

        if key in store:
            store.move_to_end(key)
        store[key] = {
            "timestamp": time.time(),
            "interpretation": sanitized,
        }

        # Enforzar LRU por empresa
        while len(store) > self.max_entries_per_tenant:
            store.popitem(last=False)

    def stats(self) -> dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_ratio": (self.hits / (self.hits + self.misses)) if (self.hits + self.misses) > 0 else 0.0,
            "tenants_cached": len(self._stores),
            "total_entries": sum(len(s) for s in self._stores.values()),
        }

    def clear(self) -> None:
        self._stores.clear()
        self.hits = 0
        self.misses = 0


# Instancia única en memoria para el proceso
cache_interpretaciones = CacheInterpretaciones()
