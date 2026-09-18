"""CU19: registrar una devolucion de un pedido entregado.

Cubre las reglas (que se puede devolver y hasta cuando), el circuito completo
solicitud -> aprobacion -> recepcion, y que recien al recibir las prendas
vuelven al stock de la sucursal.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.base import Base
from src.inventario_sucursales.application.services.organization_service import OrganizationService
from src.inventario_sucursales.web.schemas.organization import BranchCreate, CityCreate
from src.shared.exceptions.domain_exception import ConflictError, ValidationError
from src.usuarios_catalogo.application.services.catalog_service import CatalogService
from src.usuarios_catalogo.web.schemas.catalog import CategoryCreate, ColorCreate, ProductCreate, SizeCreate, VariantCreate
from src.ventas_pagos.application.returns_service import ReturnsService
from src.ventas_pagos.domain import returns
from src.ventas_pagos.infrastructure.models import OrderModel, StockModel
from src.ventas_pagos.web.schemas import CounterReturn, ReturnItemInput, ReturnRequest, ReturnResolution


def make_world():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    cliente = UserModel(email="cliente@fashionstore.test", password_hash="x", first_name="Ana",
                        last_name="Lopez", is_active=True, is_verified=True)
    admin = UserModel(email="admin@fashionstore.test", password_hash="x", first_name="Luis",
                      last_name="Admin", is_active=True, is_verified=True)
    db.add_all([cliente, admin])
    db.flush()
    org = OrganizationService(db)
    city = org.create_city(CityCreate(name="Santa Cruz", department="Santa Cruz"), admin)
    branch = org.create_branch(BranchCreate(code="SCZ-01", name="Central", city_id=city.id, address="Av. 1"), admin)
    catalog = CatalogService(db)
    category = catalog.create_category(CategoryCreate(name="Poleras"), admin)
    size = catalog.create_size(SizeCreate(code="M", name="Mediana", sort_order=20), admin)
    color = catalog.create_color(ColorCreate(name="Negro", hex_code="#000000"), admin)
    product = catalog.create_product(ProductCreate(
        name="Polera basica", description="descripcion de QA", brand="FashionStore", gender="unisex",
        base_price=Decimal("100"), category_id=category.id,
        variants=[VariantCreate(size_id=size.id, color_id=color.id, sku="POL-001")]), admin)
    variant = product.variants[0]
    db.add(StockModel(variant_id=variant.id, branch_id=branch.id, quantity=5))
    db.commit()
    return db, {"cliente": cliente, "admin": admin, "branch": branch, "variant": variant}


def make_order(db, world, *, status="delivered", payment_status="paid", entregado_hace_dias=1, cantidad=2):
    entrega = datetime.now(timezone.utc) - timedelta(days=entregado_hace_dias)
    order = OrderModel(
        number="FS-" + uuid.uuid4().hex[:10].upper(), user_id=world["cliente"].id,
        customer_email=world["cliente"].email, branch_id=world["branch"].id,
        status=status, payment_status=payment_status, payment_method="manual",
        total=Decimal(100 * cantidad), currency="BOB", address={"recipient": "Ana"},
        items=[{"variant_id": str(world["variant"].id), "name": "Polera basica", "sku": "POL-001",
                "size": "M", "color": "Negro", "quantity": cantidad, "unit_price": "100.00",
                "line_total": f"{100 * cantidad}.00"}],
        tracking=[{"status": "delivered", "note": "Entregado.", "date": entrega.isoformat()}],
        paid_at=entrega,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def solicitud(variant_id, cantidad=1, motivo="La talla no me quedo bien."):
    return ReturnRequest(reason=motivo, items=[ReturnItemInput(variant_id=variant_id, quantity=cantidad)])


class TestReglas:
    def test_un_pedido_no_entregado_no_se_puede_devolver(self):
        db, world = make_world()
        order = make_order(db, world, status="shipped")
        assert "entregados" in returns.motivo_para_rechazar(order)

    def test_vencido_el_plazo_ya_no_se_admite(self):
        db, world = make_world()
        order = make_order(db, world, entregado_hace_dias=returns.DIAS_PARA_DEVOLVER + 1)
        assert "plazo" in returns.motivo_para_rechazar(order)

    def test_dentro_del_plazo_y_entregado_se_admite(self):
        db, world = make_world()
        assert returns.motivo_para_rechazar(make_order(db, world)) is None

    def test_no_se_puede_devolver_mas_de_lo_comprado(self):
        db, world = make_world()
        order = make_order(db, world, cantidad=2)
        with pytest.raises(ValueError):
            returns.armar_detalle(order, [], [(str(world["variant"].id), 3)])

    def test_una_prenda_ajena_al_pedido_se_rechaza(self):
        db, world = make_world()
        order = make_order(db, world)
        with pytest.raises(ValueError):
            returns.armar_detalle(order, [], [(str(uuid.uuid4()), 1)])


class TestCircuito:
    def test_solicitud_registra_detalle_e_importe(self):
        db, world = make_world()
        order = make_order(db, world, cantidad=2)
        devolucion = ReturnsService(db).solicitar(world["cliente"], order, solicitud(world["variant"].id, 2))
        assert devolucion.status == "requested"
        assert str(devolucion.refund_amount) == "200.00"
        assert devolucion.items[0]["size"] == "M"

    def test_el_stock_vuelve_recien_cuando_se_reciben_las_prendas(self):
        db, world = make_world()
        order = make_order(db, world)
        service = ReturnsService(db)
        devolucion = service.solicitar(world["cliente"], order, solicitud(world["variant"].id, 1))
        stock = db.scalar(select(StockModel).where(StockModel.variant_id == world["variant"].id))
        assert stock.quantity == 5

        service.resolver(world["admin"], devolucion, ReturnResolution(status="approved", note="Aprobada."))
        db.refresh(stock)
        assert stock.quantity == 5, "aprobar no es recibir la prenda"

        service.resolver(world["admin"], devolucion, ReturnResolution(status="completed", note="Prendas recibidas."))
        db.refresh(stock)
        assert stock.quantity == 6

    def test_un_rechazo_no_devuelve_unidades_pero_las_libera_para_pedir_de_nuevo(self):
        db, world = make_world()
        order = make_order(db, world, cantidad=1)
        service = ReturnsService(db)
        devolucion = service.solicitar(world["cliente"], order, solicitud(world["variant"].id, 1))
        service.resolver(world["admin"], devolucion, ReturnResolution(status="rejected", note="Prenda usada."))
        stock = db.scalar(select(StockModel).where(StockModel.variant_id == world["variant"].id))
        assert stock.quantity == 5
        # Rechazada deja de comprometer la unidad: el cliente puede volver a pedirla.
        assert service.devolvible(order)["can_request"] is True

    def test_no_se_puede_pedir_dos_veces_la_misma_unidad(self):
        db, world = make_world()
        order = make_order(db, world, cantidad=1)
        service = ReturnsService(db)
        service.solicitar(world["cliente"], order, solicitud(world["variant"].id, 1))
        with pytest.raises(ValidationError):
            service.solicitar(world["cliente"], order, solicitud(world["variant"].id, 1))

    def test_reenviar_el_formulario_no_duplica_la_devolucion(self):
        db, world = make_world()
        order = make_order(db, world, cantidad=2)
        service = ReturnsService(db)
        data = ReturnRequest(reason="No me quedo bien.", client_request_id=uuid.uuid4(),
                             items=[ReturnItemInput(variant_id=world["variant"].id, quantity=1)])
        primera = service.solicitar(world["cliente"], order, data)
        segunda = service.solicitar(world["cliente"], order, data)
        assert primera.id == segunda.id

    def test_una_transicion_invalida_se_rechaza(self):
        db, world = make_world()
        order = make_order(db, world)
        service = ReturnsService(db)
        devolucion = service.solicitar(world["cliente"], order, solicitud(world["variant"].id, 1))
        with pytest.raises(ConflictError):
            service.resolver(world["admin"], devolucion, ReturnResolution(status="completed"))

    def test_un_pedido_sin_entregar_no_admite_solicitud(self):
        db, world = make_world()
        order = make_order(db, world, status="processing")
        with pytest.raises(ConflictError):
            ReturnsService(db).solicitar(world["cliente"], order, solicitud(world["variant"].id, 1))

    def test_el_rechazo_exige_explicar_el_motivo(self):
        with pytest.raises(ValueError):
            ReturnResolution(status="rejected", note="   ")


class TestDevolucionEnCaja:
    """CU19 en el mostrador: el cliente entrega la prenda y cobra en el momento."""

    def mostrador(self, world, order, cantidad=1, clave=None):
        return CounterReturn(
            order_id=order.id, reason="No le quedo bien.",
            items=[ReturnItemInput(variant_id=world["variant"].id, quantity=cantidad)],
            client_request_id=clave or uuid.uuid4(),
        )

    def test_se_registra_cerrada_y_devuelve_el_stock_de_una_vez(self):
        db, world = make_world()
        order = make_order(db, world, cantidad=2)
        service = ReturnsService(db)
        devolucion = service.registrar_en_caja(world["admin"], order, self.mostrador(world, order, 2))

        assert devolucion.status == "completed"
        assert devolucion.resolved_by == world["admin"].id
        assert str(devolucion.refund_amount) == "200.00"
        stock = db.scalar(select(StockModel).where(StockModel.variant_id == world["variant"].id))
        assert stock.quantity == 7, "las dos unidades vuelven en el acto"

    def test_reintentar_el_formulario_no_reintegra_dos_veces(self):
        db, world = make_world()
        order = make_order(db, world, cantidad=2)
        service = ReturnsService(db)
        datos = self.mostrador(world, order, 1)
        primera = service.registrar_en_caja(world["admin"], order, datos)
        segunda = service.registrar_en_caja(world["admin"], order, datos)

        assert primera.id == segunda.id
        stock = db.scalar(select(StockModel).where(StockModel.variant_id == world["variant"].id))
        assert stock.quantity == 6, "una sola unidad vuelve, no dos"

    def test_no_se_puede_devolver_mas_de_lo_vendido(self):
        db, world = make_world()
        order = make_order(db, world, cantidad=1)
        service = ReturnsService(db)
        with pytest.raises(ValidationError):
            service.registrar_en_caja(world["admin"], order, self.mostrador(world, order, 3))

    def test_una_venta_ya_devuelta_no_admite_otra_devolucion(self):
        db, world = make_world()
        order = make_order(db, world, cantidad=1)
        service = ReturnsService(db)
        service.registrar_en_caja(world["admin"], order, self.mostrador(world, order, 1))
        with pytest.raises(ValidationError):
            service.registrar_en_caja(world["admin"], order, self.mostrador(world, order, 1))

    def test_fuera_de_plazo_se_rechaza_igual_que_en_la_web(self):
        db, world = make_world()
        order = make_order(db, world, entregado_hace_dias=returns.DIAS_PARA_DEVOLVER + 1)
        with pytest.raises(ConflictError):
            ReturnsService(db).registrar_en_caja(world["admin"], order, self.mostrador(world, order))

    def test_deja_una_nota_por_defecto_para_la_bitacora(self):
        db, world = make_world()
        order = make_order(db, world)
        devolucion = ReturnsService(db).registrar_en_caja(
            world["admin"], order, self.mostrador(world, order)
        )
        assert "caja" in (devolucion.resolution_note or "").lower()
