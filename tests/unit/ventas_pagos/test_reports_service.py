import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.base import Base
from src.inventario_sucursales.application.services.organization_service import OrganizationService
from src.inventario_sucursales.web.schemas.organization import BranchCreate, CityCreate
from src.usuarios_catalogo.application.services.catalog_service import CatalogService
from src.usuarios_catalogo.web.schemas.catalog import CategoryCreate, ColorCreate, ProductCreate, SizeCreate, VariantCreate
from src.ventas_pagos.application.reports_ai import ReportsAI
from src.ventas_pagos.application.reports_service import ReportsService
from src.ventas_pagos.infrastructure.models import OrderModel, StockModel


def make_world() -> tuple[Session, dict]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    actor = UserModel(email="admin@fashionstore.test", password_hash="x", first_name="Admin", last_name="FashionStore",
                      is_active=True, is_verified=True)
    db.add(actor)
    db.flush()

    organization = OrganizationService(db)
    city = organization.create_city(CityCreate(name="Santa Cruz", department="Santa Cruz"), actor)
    branch = organization.create_branch(BranchCreate(code="SCZ-01", name="Sucursal Central", city_id=city.id, address="Av. 1"), actor)

    catalog = CatalogService(db)
    category = catalog.create_category(CategoryCreate(name="Vestidos"), actor)
    size = catalog.create_size(SizeCreate(code="M", name="Mediana", sort_order=20), actor)
    color = catalog.create_color(ColorCreate(name="Rojo", hex_code="#FF0000"), actor)
    color_b = catalog.create_color(ColorCreate(name="Azul", hex_code="#0000FF"), actor)
    product = catalog.create_product(ProductCreate(
        name="Vestido primavera", description="descripcion de prueba", brand="FashionStore", gender="mujer",
        base_price=Decimal("50"), category_id=category.id,
        variants=[VariantCreate(size_id=size.id, color_id=color.id, sku="VES-001"),
                  VariantCreate(size_id=size.id, color_id=color_b.id, sku="VES-002")]), actor)
    variant_a, variant_b = product.variants
    db.add(StockModel(variant_id=variant_a.id, branch_id=branch.id, quantity=2))
    db.add(StockModel(variant_id=variant_b.id, branch_id=branch.id, quantity=50))
    db.commit()
    return db, {"actor": actor, "branch": branch, "category": category, "v1": variant_a, "v2": variant_b,
                "product": product, "db": db}


def add_order(db, branch, user, variant_id, quantity, total, status="paid", payment_status="paid", days_ago=1):
    order = OrderModel(
        number=str(uuid.uuid4())[:20].upper(), user_id=user.id, customer_email="c@mail.test",
        branch_id=branch.id, status=status, payment_status=payment_status, payment_method="stripe",
        total=total, currency="bob", address={},
        items=[{"variant_id": str(variant_id), "product_id": str(variant_id), "name": "Vestido primavera",
                "quantity": quantity, "unit_price": "50"}],
        tracking=[], created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        updated_at=datetime.now(timezone.utc) - timedelta(days=days_ago))
    db.add(order)
    db.commit()
    return order


def test_period_metrics_comparison_and_unbounded_history():
    db, world = make_world()
    user = world["actor"]
    add_order(db, world["branch"], user, world["v1"].id, 2, Decimal("100"), days_ago=1)
    add_order(db, world["branch"], user, world["v2"].id, 1, Decimal("50"), days_ago=2)
    add_order(db, world["branch"], user, world["v1"].id, 1, Decimal("30"), status="pending_payment", payment_status="pending", days_ago=1)
    add_order(db, world["branch"], user, world["v1"].id, 5, Decimal("400"), days_ago=40)

    start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    end = datetime.now(timezone.utc).isoformat()
    data = ReportsService(db).dashboard(datetime.fromisoformat(start), datetime.fromisoformat(end))

    assert data["period"]["orders"] == 3
    assert data["period"]["paid_orders"] == 2
    assert data["period"]["revenue"] == "150.00"
    assert data["period"]["units_sold"] == 3
    assert data["period"]["pending_orders"] == 1
    assert data["period"]["ticket_avg"] == "75.00"
    assert data["meta"]["timezone"] == "America/La_Paz"
    assert data["comparison"]["available"] is True
    assert data["comparison"]["previous"]["base_note"] == "Sin base comparable"
    assert data["comparison"]["previous"]["revenue_delta_pct"] is None

    all_history = ReportsService(db).dashboard()
    assert all_history["period"]["orders"] == 4
    assert all_history["meta"]["coverage"] == "todo el historial"
    assert all_history["comparison"]["available"] is False


def test_period_comparison_with_previous_revenue():
    db, world = make_world()
    user = world["actor"]
    add_order(db, world["branch"], user, world["v1"].id, 1, Decimal("100"), days_ago=1)
    add_order(db, world["branch"], user, world["v1"].id, 1, Decimal("50"), days_ago=9)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=5)
    data = ReportsService(db).dashboard(start, end)
    prev = data["comparison"]["previous"]
    assert prev["revenue"] == "50.00"
    assert prev["revenue_delta_pct"] == 1.0


def test_low_stock_variants_detailed():
    db, world = make_world()
    data = ReportsService(db).dashboard()
    assert data["low_stock"] == 1
    assert len(data["low_stock_variants"]) == 1
    assert data["low_stock_variants"][0]["sku"] == "VES-001"
    assert data["low_stock_variants"][0]["quantity"] == 2


def test_interpret_resolves_branch_and_period():
    db, world = make_world()
    ai = ReportsAI(db)
    result = ai.interpret(
        "mostrar ingresos de la sucursal central ultimos 7 dias",
        None,
        {"branches": [{"id": str(world["branch"].id), "name": "Sucursal Central"}],
         "categories": [{"id": str(world["category"].id), "name": "Vestidos"}]},
    )
    assert result["ok"] is True
    assert result["metrica"] == "revenue"
    assert result["filtros"]["branch_id"] == str(world["branch"].id)
    assert result["filtros"]["date_from"] is not None
    assert result["comparacion"] == "none"


def test_export_report_rows_matches_period():
    db, world = make_world()
    add_order(db, world["branch"], world["actor"], world["v1"].id, 2, Decimal("100"), days_ago=1)
    title, headers, rows = ReportsService(db).export_report("pedidos")
    assert title == "Pedidos"
    assert len(rows) == 1
    assert rows[0]["total"] == 100.0