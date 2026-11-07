import uuid
from decimal import Decimal
import pytest
from sqlalchemy import select

import src.integraciones.infrastructure.models  # registers webhook tables with Base.metadata

from src.inventario_sucursales.application.services.organization_service import OrganizationService
from src.inventario_sucursales.web.schemas.organization import BranchCreate
from src.shared.exceptions.domain_exception import NotFoundError, ValidationError
from src.usuarios_catalogo.infrastructure.models.catalog import ProductVariantModel, SizeModel
from src.ventas_pagos.application.exchange_service import ExchangeService
from src.ventas_pagos.infrastructure.models import StockModel
from tests.unit.ventas_pagos.test_devoluciones import make_order, make_world


def setup_multibranch():
    db, world = make_world()
    org = OrganizationService(db)
    city_id = world["branch"].city_id
    branch2 = org.create_branch(BranchCreate(code="SCZ-02", name="Sucursal Equipetrol", city_id=city_id, address="Av. San Martin"), world["admin"])

    order = make_order(db, world, cantidad=2)
    size_l = SizeModel(code="L", name="Grande")
    db.add(size_l)
    db.flush()

    replacement = ProductVariantModel(
        product_id=world["variant"].product_id, size_id=size_l.id,
        color_id=world["variant"].color_id, sku="POL-L-003",
    )
    db.add(replacement)
    db.flush()

    # Stock en sucursal 1 (Central) = 0 unidades
    # Stock en sucursal 2 (Equipetrol) = 5 unidades
    stock2 = StockModel(variant_id=replacement.id, branch_id=branch2.id, quantity=5)
    db.add(stock2)
    db.commit()

    return db, world, order, branch2, replacement, stock2


def test_consultar_disponibilidad_multisucursal():
    db, world, order, branch2, replacement, _ = setup_multibranch()
    svc = ExchangeService(db)
    tenant_id = world["tenant_id"] if "tenant_id" in world else None
    if not tenant_id:
        from src.plataforma_saas.infrastructure.models.tenant import TenantModel
        t = db.scalar(select(TenantModel))
        tenant_id = t.id if t else uuid.uuid4()

    # Consultar disponibilidad
    disponibilidad = svc.consultar_disponibilidad_multisucursal(tenant_id, replacement.id)
    assert len(disponibilidad) >= 2
    eq_branch = next(b for b in disponibilidad if b["branch_id"] == str(branch2.id))
    assert eq_branch["available_quantity"] == 5
    assert eq_branch["can_transfer"] is True


def test_traslado_intersucursal():
    db, world, order, branch2, replacement, stock2 = setup_multibranch()
    svc = ExchangeService(db)
    from src.plataforma_saas.infrastructure.models.tenant import TenantModel
    t = db.scalar(select(TenantModel))
    tenant_id = t.id if t else uuid.uuid4()

    # Trasladar 2 unidades de Sucursal 2 (Equipetrol) a Sucursal 1 (Central)
    res = svc.transferir_prenda_intersucursal(
        tenant_id=tenant_id,
        variant_id=replacement.id,
        from_branch_id=branch2.id,
        to_branch_id=world["branch"].id,
        quantity=2,
        actor_id=world["admin"].id,
        notes="Traslado para atender cambio de cliente",
    )

    assert res["transferred_quantity"] == 2
    assert res["destination_available_stock"] == 2

    # Verificar stock en destino (Sucursal 1)
    dest_stock = db.scalar(select(StockModel.quantity).where(
        StockModel.variant_id == replacement.id, StockModel.branch_id == world["branch"].id
    ))
    assert dest_stock == 2

    # Verificar stock en origen (Sucursal 2)
    db.refresh(stock2)
    assert stock2.quantity == 3


def test_traslado_mismo_origen_falla():
    db, world, order, branch2, replacement, _ = setup_multibranch()
    svc = ExchangeService(db)
    from src.plataforma_saas.infrastructure.models.tenant import TenantModel
    t = db.scalar(select(TenantModel))
    tenant_id = t.id if t else uuid.uuid4()

    with pytest.raises(ValidationError, match="distintas"):
        svc.transferir_prenda_intersucursal(
            tenant_id=tenant_id,
            variant_id=replacement.id,
            from_branch_id=branch2.id,
            to_branch_id=branch2.id,
            quantity=1,
            actor_id=world["admin"].id,
        )
