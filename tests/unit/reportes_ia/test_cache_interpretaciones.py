from copy import deepcopy
import time
from unittest.mock import MagicMock
import uuid
import pytest

from src.reportes_ia.application.cache_interpretaciones import (
    CacheInterpretaciones,
    normalizar_texto_cache,
)
from src.reportes_ia.domain.especificacion import ChartKind, Dimension, Metric, ReportSpec


def test_normalizacion_de_texto() -> None:
    t1 = "  ¿Cuáles fueron las Ventas por Categoría este mes?  "
    t2 = "¿cuáles fueron las ventas por categoria este mes?"
    assert normalizar_texto_cache(t1) == normalizar_texto_cache(t2)


def test_misma_pregunta_en_a_y_b_no_comparte_entrada() -> None:
    cache = CacheInterpretaciones()
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    prompt = "Ventas por sucursal de este mes"

    spec_a = {
        "status": "READY",
        "spec": {
            "definition_code": "sales_by_branch",
            "metrics": ["total_amount"],
            "dimensions": ["branch"],
            "chart_type": "BAR",
            "filters": {},
        },
        "interpreter": "DETERMINISTIC",
    }

    cache.set(tenant_a, prompt, spec_a)

    # Tenant B con la misma pregunta exacta debe tener miss
    assert cache.get(tenant_b, prompt) is None

    # Tenant A debe tener hit
    res_a = cache.get(tenant_a, prompt)
    assert res_a is not None
    assert res_a["spec"]["definition_code"] == "sales_by_branch"


def test_no_guarda_texto_ni_resultados() -> None:
    cache = CacheInterpretaciones()
    tenant = uuid.uuid4()
    prompt = "Dame los clientes con más compras y sus teléfonos secretos"

    # Simular una estructura que intentase colar datos o texto del pedido
    payload_con_datos = {
        "status": "READY",
        "text": prompt,
        "prompt": prompt,
        "results": [{"cliente": "Juan Perez", "telefono": "77112233"}],
        "rows": [{"monto": 500}],
        "data": "datos sensibles",
        "spec": {
            "definition_code": "top_customers",
            "metrics": ["order_count"],
            "dimensions": ["customer"],
            "chart_type": "TABLE",
            "filters": {},
            "raw_text": prompt,
        },
    }

    cache.set(tenant, prompt, payload_con_datos)

    # Inspeccionar el almacén interno de la caché
    key = cache.build_key(tenant, prompt)
    stored_entry = cache._stores[str(tenant)][key]
    stored_interp = stored_entry["interpretation"]

    # Verificar que NO existe texto original ni resultados almacenados (RN22)
    assert "text" not in stored_interp
    assert "prompt" not in stored_interp
    assert "results" not in stored_interp
    assert "rows" not in stored_interp
    assert "data" not in stored_interp

    # Tampoco dentro del spec
    assert "raw_text" not in stored_interp["spec"]
    assert stored_interp["spec"]["definition_code"] == "top_customers"


def test_acierto_no_llama_al_proveedor() -> None:
    cache = CacheInterpretaciones()
    tenant = uuid.uuid4()
    prompt = "Ventas por sucursal"

    mock_provider = MagicMock()
    mock_provider.return_value = {
        "status": "READY",
        "spec": {
            "definition_code": "sales_by_branch",
            "metrics": ["total_amount"],
            "dimensions": ["branch"],
            "chart_type": "BAR",
            "filters": {},
        },
    }

    # Primera consulta: Miss -> llama al proveedor
    cached = cache.get(tenant, prompt)
    if cached is None:
        result = mock_provider(prompt)
        cache.set(tenant, prompt, result)

    assert mock_provider.call_count == 1

    # Segunda consulta idéntica (con distinta capitalización y tildes): Hit -> NO llama al proveedor
    prompt_variante = "ventas por SUCURSAL"
    cached_2 = cache.get(tenant, prompt_variante)
    assert cached_2 is not None

    if cached_2 is None:
        mock_provider(prompt_variante)

    # El proveedor NO debió ser llamado por segunda vez
    assert mock_provider.call_count == 1
    assert cache.hits == 1
    assert cache.misses == 1


def test_lru_capacidad_maxima_por_empresa() -> None:
    cache = CacheInterpretaciones(max_entries_per_tenant=3)
    tenant = uuid.uuid4()

    for i in range(4):
        cache.set(
            tenant,
            f"Consulta reporte {i}",
            {"status": "READY", "spec": {"definition_code": f"report_{i}"}},
        )

    # La primera consulta (0) debió ser expulsada por LRU
    assert cache.get(tenant, "Consulta reporte 0") is None
    # Las consultas 1, 2 y 3 se conservan
    assert cache.get(tenant, "Consulta reporte 1") is not None
    assert cache.get(tenant, "Consulta reporte 2") is not None
    assert cache.get(tenant, "Consulta reporte 3") is not None


def test_ttl_expiracion_de_entrada() -> None:
    cache = CacheInterpretaciones(ttl_seconds=1)
    tenant = uuid.uuid4()
    prompt = "Reporte de stock"

    cache.set(tenant, prompt, {"status": "READY", "spec": {"definition_code": "stock"}})

    # Simular paso del tiempo manipulando la marca de tiempo de la entrada
    key = cache.build_key(tenant, prompt)
    cache._stores[str(tenant)][key]["timestamp"] = time.time() - 10

    # Debe expirar y retornar None
    assert cache.get(tenant, prompt) is None
