"""Regresiones QA: semantica de categoria por lineas (dashboard=export),
fechas/períodos, ingresos por fecha de pago, reservas dentro del periodo."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.base import Base
from src.inventario_sucursales.application.services.organization_service import OrganizationService
from src.inventario_sucursales.web.schemas.organization import BranchCreate, CityCreate
from src.reservas.infrastructure.persistence.models.reserva import ReservationModel
from src.usuarios_catalogo.application.services.catalog_service import CatalogService
from src.usuarios_catalogo.web.schemas.catalog import CategoryCreate, ColorCreate, ProductCreate, SizeCreate, VariantCreate
from src.ventas_pagos.application.reports_ai import ReportsAI
from src.ventas_pagos.application.reports_service import ReportsService
from src.ventas_pagos.infrastructure.models import OrderModel, StockModel

UTC = timezone.utc


def make_two_category_world() -> tuple[Session, dict]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    actor = UserModel(email="qa@fashionstore.test", password_hash="x", first_name="QA", last_name="Tienda",
                      is_active=True, is_verified=True)
    db.add(actor)
    db.flush()
    org = OrganizationService(db)
    city = org.create_city(CityCreate(name="Santa Cruz", department="Santa Cruz"), actor)
    branch = org.create_branch(BranchCreate(code="SCZ-01", name="Sucursal Central", city_id=city.id, address="Av. 1"), actor)
    catalog = CatalogService(db)
    cat_a = catalog.create_category(CategoryCreate(name="Camisas"), actor)
    cat_b = catalog.create_category(CategoryCreate(name="Pantalones"), actor)
    size = catalog.create_size(SizeCreate(code="M", name="Mediana", sort_order=20), actor)
    color = catalog.create_color(ColorCreate(name="Rojo", hex_code="#FF0000"), actor)
    product_a = catalog.create_product(ProductCreate(
        name="Camisa, lino", description="descripcion de QA", brand="FashionStore", gender="mujer", base_price=Decimal("50"),
        category_id=cat_a.id, variants=[VariantCreate(size_id=size.id, color_id=color.id, sku="CAM-001")]), actor)
    product_b = catalog.create_product(ProductCreate(
        name="Pantalón jean", description="descripcion de QA", brand="FashionStore", gender="mujer", base_price=Decimal("150"),
        category_id=cat_b.id, variants=[VariantCreate(size_id=size.id, color_id=color.id, sku="PAN-001")]), actor)
    va, vb = product_a.variants[0], product_b.variants[0]
    db.add(StockModel(variant_id=va.id, branch_id=branch.id, quantity=20))
    db.add(StockModel(variant_id=vb.id, branch_id=branch.id, quantity=30))
    db.commit()
    return db, {"actor": actor, "branch": branch, "cat_a": cat_a, "cat_b": cat_b,
                "va": va, "vb": vb, "product_a": product_a, "product_b": product_b}


def line(variant, product, name, unit_price, quantity):
    return {"variant_id": str(variant.id), "product_id": str(product.id), "name": name,
            "quantity": quantity, "unit_price": str(unit_price), "line_total": str(unit_price * quantity)}


def add_order(db, branch, user, items, created_at, total=None, paid_at=None, status="paid", payment_status="paid"):
    total = total if total is not None else sum(Decimal(i["line_total"]) for i in items)
    order = OrderModel(number=uuid.uuid4().hex[:24].upper()[:24], user_id=user.id, customer_email="c@mail.test",
                       branch_id=branch.id, status=status, payment_status=payment_status, payment_method="stripe",
                       total=total, currency="bob", address={}, items=items, tracking=[], paid_at=paid_at,
                       created_at=created_at, updated_at=created_at)
    db.add(order)
    db.commit()
    return order


def test_categoria_filtra_solo_las_lineas_dashboard():
    db, world = make_two_category_world()
    u, b = world["actor"], world["branch"]
    va, vb = world["va"], world["vb"]
    pa, pb = world["product_a"], world["product_b"]
    now = datetime.now(UTC)
    add_order(db, b, u, [line(va, pa, "Camisa, lino", 50, 1), line(vb, pb, "Pantalón jean", 150, 1)],
              now - timedelta(days=1), paid_at=now - timedelta(days=1))          # Pedido 1: A 50 + B 150
    add_order(db, b, u, [line(vb, pb, "Pantalón jean", 150, 1)],
              now - timedelta(days=2), paid_at=now - timedelta(days=2))          # Pedido 2: B 150

    data = ReportsService(db).dashboard(category_id=world["cat_a"].id)
    assert data["period"]["revenue"] == "50.00"
    assert data["period"]["paid_orders"] == 1
    assert data["period"]["units_sold"] == 1
    assert data["period"]["ticket_avg"] == "50.00"
    breakdown = {c["category"]: c["total"] for c in data["category_breakdown"]}
    assert breakdown == {"Camisas": "50.00"}
    assert data["top_products"] == [{"name": "Camisa, lino", "quantity": 1}]

    data_b = ReportsService(db).dashboard(category_id=world["cat_b"].id)
    assert data_b["period"]["revenue"] == "300.00"
    assert data_b["period"]["paid_orders"] == 2
    assert data_b["by_status"] == {"paid": 2}
    assert data_b["comparison"]["available"] is False  # historial completo, sin base


def test_export_concuerda_con_dashboard_segun_categoria():
    db, world = make_two_category_world()
    u, b = world["actor"], world["branch"]
    va, vb = world["va"], world["vb"]
    pa, pb = world["product_a"], world["product_b"]
    now = datetime.now(UTC)
    add_order(db, b, u, [line(va, pa, "Camisa, lino", 50, 1), line(vb, pb, "Pantalón jean", 150, 1)],
              now - timedelta(days=1), paid_at=now - timedelta(days=1))
    add_order(db, b, u, [line(vb, pb, "Pantalón jean", 150, 1)],
              now - timedelta(days=2), paid_at=now - timedelta(days=2))

    title, headers, rows = ReportsService(db).export_report("ventas", category_id=world["cat_a"].id)
    assert rows[0]["total"] == 50.0

    title, headers, rows = ReportsService(db).export_report("pedidos", category_id=world["cat_a"].id)
    assert len(rows) == 1
    assert headers[-1] == "total_categoria"
    assert rows[0]["total"] == 200.0
    assert rows[0]["total_categoria"] == 50.0

    title, headers, rows = ReportsService(db).export_report("pagos", category_id=world["cat_a"].id)
    assert len(rows) == 1
    assert rows[0]["total"] == 50.0

    title, headers, rows = ReportsService(db).export_report("prendas_vendidas", category_id=world["cat_a"].id)
    assert len(rows) == 1
    assert rows[0]["nombre"] == "Camisa, lino"
    assert rows[0]["total"] == 50.0

    title, headers, rows = ReportsService(db).export_report("pedidos")
    assert len(rows) == 2
    assert headers[-1] == "moneda"


def test_ingresos_usando_fecha_de_pago_con_respaldo_creacion():
    db, world = make_two_category_world()
    u, b = world["actor"], world["branch"]
    va = world["va"]
    pa = world["product_a"]
    now = datetime.now(UTC)
    # Pagado hace tiempo, PERO cobrado hace 1 dia: cuenta por paid_at.
    add_order(db, b, u, [line(va, pa, "Camisa, lino", 50, 1)], now - timedelta(days=60), paid_at=now - timedelta(days=1))
    # Pagado hace 1 dia, sin paid_at (historico): respaldo = creacion.
    add_order(db, b, u, [line(va, pa, "Camisa, lino", 50, 1)], now - timedelta(days=1))
    # Pagado sin paid_at hace 60 dias: queda fuera de la ventana de cobro.
    add_order(db, b, u, [line(va, pa, "Camisa, lino", 50, 1)], now - timedelta(days=60))

    start = now - timedelta(days=7)
    end = now
    data = ReportsService(db).dashboard(start, end)
    assert data["period"]["paid_orders"] == 2
    assert data["period"]["revenue"] == "100.00"


def test_by_status_y_reservas_respetan_la_ventana_por_fecha():
    db, world = make_two_category_world()
    u, b = world["actor"], world["branch"]
    va = world["va"]
    pa = world["product_a"]
    now = datetime.now(UTC)
    add_order(db, b, u, [line(va, pa, "Camisa, lino", 50, 1)], now - timedelta(days=1), paid_at=now - timedelta(days=1))
    add_order(db, b, u, [line(va, pa, "Camisa, lino", 50, 1)], now - timedelta(days=300),
              status="cancelled", payment_status="cancelled")
    # scheduled_at naive = instante "ahora" en hora de La Paz (UTC-4): se pasa
    # en horario de pared desde 4 horas antes para que el instante coincida
    # con el "now" UTC de la ventana del dashboard.
    inside = (now - timedelta(hours=4)).replace(tzinfo=None)
    db.add(ReservationModel(user_id=u.id, branch_id=b.id, status="pending", scheduled_at=inside,
                            items=[], notes=None))
    db.add(ReservationModel(user_id=u.id, branch_id=b.id, status="cancelled",
                            scheduled_at=(inside - timedelta(days=300)), items=[], notes=None))
    db.commit()

    data = ReportsService(db).dashboard(now - timedelta(days=7), now)
    assert data["by_status"] == {"paid": 1}
    assert data["reservations_by_status"] == [{"status": "pending", "count": 1}]
    assert data["meta"]["coverage"] == "ventana definida"


def test_comparativa_anio_pasado_calendario_con_bisiesto():
    db, world = make_two_category_world()
    u, b = world["actor"], world["branch"]
    va = world["va"]
    pa = world["product_a"]
    # 2024 es bisiesto: el mismo lapso calendario de 2023 va 28-feb..4-mar,
    # NO 29-feb (dia inexistente en 2023).
    add_order(db, b, u, [line(va, pa, "Camisa, lino", 50, 1)],
              datetime(2023, 3, 2, 12, tzinfo=UTC), paid_at=datetime(2023, 3, 2, 12, tzinfo=UTC))
    add_order(db, b, u, [line(va, pa, "Camisa, lino", 50, 1)],
              datetime(2024, 2, 29, 12, tzinfo=UTC), paid_at=datetime(2024, 2, 29, 12, tzinfo=UTC))
    add_order(db, b, u, [line(va, pa, "Camisa, lino", 50, 1)],
              datetime(2024, 3, 1, 12, tzinfo=UTC), paid_at=datetime(2024, 3, 1, 12, tzinfo=UTC))

    data = ReportsService(db).dashboard(datetime(2024, 3, 1, 12, tzinfo=UTC), datetime(2024, 3, 5, 12, tzinfo=UTC))
    year_ago = data["comparison"]["year_ago"]
    # El 29-feb-2024 equivale al 28-feb-2023 y queda FUERA del lapso anio-pasado
    # [2023-03-01 .. 2023-03-05): el unico pedido del lapso es el del 2-mar-2023.
    assert year_ago["revenue"] == "50.00"
    assert year_ago["paid_orders"] == 1
    assert year_ago["revenue_delta_pct"] == 0.0


def test_mensual_anclado_a_la_ventana_seleccionada():
    db, world = make_two_category_world()
    u, b = world["actor"], world["branch"]
    va = world["va"]
    pa = world["product_a"]
    add_order(db, b, u, [line(va, pa, "Camisa, lino", 50, 1)],
              datetime(2025, 1, 15, 12, tzinfo=UTC), paid_at=datetime(2025, 1, 15, 12, tzinfo=UTC))
    add_order(db, b, u, [line(va, pa, "Camisa, lino", 50, 1)],
              datetime(2025, 2, 10, 12, tzinfo=UTC), paid_at=datetime(2025, 2, 10, 12, tzinfo=UTC))

    data = ReportsService(db).dashboard(datetime(2025, 1, 1, 12, tzinfo=UTC), datetime(2025, 2, 28, 12, tzinfo=UTC))
    months = [m["month"] for m in data["monthly_sales"]]
    assert months == ["2025-01", "2025-02"]
    totals = {m["month"]: m["total"] for m in data["monthly_sales"]}
    assert totals == {"2025-01": "50.00", "2025-02": "50.00"}


def test_ia_no_confunde_anio_pasado_con_anio_actual():
    db, world = make_two_category_world()
    ai = ReportsAI(db)
    past = ai.interpret(
        "ventas hace un año por sucursal",
        None,
        {"branches": [{"id": str(world["branch"].id), "name": "Sucursal Central"}],
         "categories": []},
    )
    # La normalizacion quita acentos ("año" -> "ano"); el comparador debe
    # resolver "hace un anio" como comparacion de anio pasado, sin abrir el
    # periodo "este anio" para el cuadro.
    assert past["filtros"]["date_from"] is None
    assert past["comparacion"] == "year_ago"

    this_year = ai.interpret(
        "ventas de este ano",
        None,
        {"branches": [], "categories": [{"id": str(world["cat_a"].id), "name": "Camisas"}]},
    )
    assert this_year["filtros"]["date_from"] is not None
    assert this_year["comparacion"] == "none"