from datetime import date
from uuid import uuid4
import pytest

from src.reportes_ia.application.interprete import Interprete
from src.reportes_ia.application.validador import Validador
from src.shared.exceptions.domain_exception import ValidationError


def test_interprete_los_seis_ejemplos_del_enunciado():
    catalogo = {
        "branches": [{"id": str(uuid4()), "name": "Central"}, {"id": str(uuid4()), "name": "Norte"}],
        "categories": [{"id": str(uuid4()), "name": "Vestidos"}, {"id": str(uuid4()), "name": "Pantalones"}],
        "products": [{"id": str(uuid4()), "name": "Vestido Lino"}],
    }
    inter = Interprete(catalogo)
    hoy = date(2026, 11, 4)

    # 1. Ventas por sucursal
    r1 = inter.interpretar("Mostrame las ventas de septiembre agrupadas por sucursal", hoy=hoy)
    assert r1.status == "READY"
    assert r1.spec is not None
    assert r1.spec.definition_code == "ventas_por_sucursal"
    assert r1.spec.filters.period is not None
    assert r1.spec.filters.period.date_from.month == 9

    # 2. Top productos
    r2 = inter.interpretar("¿Cuáles fueron los diez productos más vendidos este mes?", hoy=hoy)
    assert r2.status == "READY"
    assert r2.spec is not None
    assert r2.spec.definition_code == "top_productos"
    assert r2.spec.top_n == 10

    # 3. Ventas por semana
    r3 = inter.interpretar("Generá un gráfico de ventas por semana", hoy=hoy)
    assert r3.status == "READY"
    assert r3.spec is not None
    assert r3.spec.definition_code == "ventas_por_semana"

    # 4. Comparativa de sucursales
    r4 = inter.interpretar("Compará las ventas de las sucursales durante los últimos tres meses", hoy=hoy)
    assert r4.status == "READY"
    assert r4.spec is not None
    assert r4.spec.definition_code == "comparativa_sucursales"

    # 5. Menor existencia
    r5 = inter.interpretar("Mostrame los productos con menor existencia", hoy=hoy)
    assert r5.status == "READY"
    assert r5.spec is not None
    assert r5.spec.definition_code == "menor_existencia"

    # 6. Ingresos por categoría
    r6 = inter.interpretar("¿Qué categorías generaron mayores ingresos durante este período?", hoy=hoy)
    assert r6.status == "READY"
    assert r6.spec is not None
    assert r6.spec.definition_code == "ingresos_por_categoria"


def test_interprete_seguridad_escritura_y_cross_tenant():
    inter = Interprete({})

    # Intento de borrado
    r_del = inter.interpretar("eliminar todas las ventas de ayer")
    assert r_del.status == "UNSUPPORTED"
    assert r_del.spec is None
    assert len(r_del.suggestions) > 0

    # Intento de SQL
    r_sql = inter.interpretar("SELECT * FROM users WHERE 1=1")
    assert r_sql.status == "UNSUPPORTED"

    # Intento de cross-tenant
    r_cross = inter.interpretar("dame las ventas de otra empresa")
    assert r_cross.status == "UNSUPPORTED"


def test_validador_resolucion_catalogo(saas_world):
    w = saas_world
    tenant_id = w.tenants[0].id
    inter = Interprete({"branches": [{"id": str(w.branches[0].id), "name": w.branches[0].name}]})

    r = inter.interpretar(f"Ventas por sucursal en {w.branches[0].name}")
    assert r.status == "READY"
    assert r.spec is not None

    validador = Validador(w.db)
    sv = validador.validar(r.spec, tenant_id)
    assert sv.tenant_id == tenant_id
    assert w.branches[0].id in sv.branch_ids
