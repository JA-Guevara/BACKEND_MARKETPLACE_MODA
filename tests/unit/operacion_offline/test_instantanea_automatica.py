import json
from pathlib import Path
from sqlalchemy import select

from src.auth.infrastructure.persistence.models.user import UserModel
from src.inventario_sucursales.infrastructure.models.organization import (
    BranchModel,
    CashPointModel,
    UserBranchModel,
)
from src.operacion_offline.web.schemas import OfflineSnapshot
from src.operacion_offline.web.sync_schemas import SyncBatchIn, SyncBatchOut
from src.plataforma_saas.infrastructure.models.plan import PlanFeatureModel
from src.ventas_pagos.infrastructure.models import StockModel


def test_cliente_empresa_a_recibe_todas_sucursales_a_y_ninguna_b(saas_world):
    w = saas_world
    r = w.client.get("/api/v1/offline/snapshot", headers=w.headers(w.customer_a))
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    branch_ids = [b["id"] for b in data["branches"]]
    assert str(w.branch_a.id) in branch_ids
    assert str(w.branch_b.id) not in branch_ids


def test_cajero_sin_sucursales_asignadas_falla_409_no_authorized_branches(saas_world):
    w = saas_world
    cajero = UserModel(
        tenant_id=w.tenant_a.id,
        email="cajero.sin.sucursal@example.com",
        first_name="Cajero",
        last_name="SinSucursal",
        password_hash=w.platform_user.password_hash,
        is_verified=True,
        roles=[w.cashier_role],
    )
    w.db.add(cajero)
    w.db.commit()
    r = w.client.get("/api/v1/offline/snapshot", headers=w.headers(cajero))
    assert r.status_code == 409, r.text
    body = r.json()
    error = body.get("error") or body
    assert error.get("code") == "no_authorized_branches"


def test_cajero_con_una_sucursal_recibe_solo_esa_sucursal_sus_cajas_y_existencia(saas_world):
    w = saas_world
    branch_a2 = BranchModel(
        tenant_id=w.tenant_a.id,
        name="Sucursal Norte A",
        code="SUC-NORTE-A",
        address="Av. Norte 123",
        city_id=w.branch_a.city_id,
        is_active=True,
    )
    w.db.add(branch_a2)
    w.db.flush()
    caja_a2 = CashPointModel(
        tenant_id=w.tenant_a.id,
        branch_id=branch_a2.id,
        code="CAJA-A2",
        name="Caja Norte",
        is_active=True,
    )
    stock_a2 = StockModel(
        branch_id=branch_a2.id,
        variant_id=w.variant_a.id,
        quantity=5,
    )
    w.db.add_all([caja_a2, stock_a2])
    w.db.flush()

    cajero = UserModel(
        tenant_id=w.tenant_a.id,
        email="cajero.asignado@example.com",
        first_name="Cajero",
        last_name="Asignado",
        password_hash=w.platform_user.password_hash,
        is_verified=True,
        roles=[w.cashier_role],
    )
    w.db.add(cajero)
    w.db.flush()
    w.db.add(UserBranchModel(tenant_id=w.tenant_a.id, user_id=cajero.id, branch_id=w.branch_a.id))
    w.db.commit()

    r = w.client.get("/api/v1/offline/snapshot", headers=w.headers(cajero))
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    branch_ids = [b["id"] for b in data["branches"]]
    assert branch_ids == [str(w.branch_a.id)]
    assert str(branch_a2.id) not in branch_ids

    cash_point_ids = [c["id"] for c in data["cash_points"]]
    assert str(w.cash_point_a.id) in cash_point_ids
    assert str(caja_a2.id) not in cash_point_ids

    stock_branch_ids = {s["branch_id"] for s in data["stock"]}
    assert stock_branch_ids == {str(w.branch_a.id)}


def test_since_sin_cambios_devuelve_incremental_vacio_con_stock_actual(saas_world):
    w = saas_world
    first_resp = w.client.get("/api/v1/offline/snapshot", headers=w.headers(w.admin_a))
    assert first_resp.status_code == 200
    first_data = first_resp.json()["data"]
    version = first_data["version"]

    inc_resp = w.client.get("/api/v1/offline/snapshot", params={"since": version}, headers=w.headers(w.admin_a))
    assert inc_resp.status_code == 200, inc_resp.text
    inc_data = inc_resp.json()["data"]
    assert inc_data["full"] is False
    assert inc_data["products"] == []
    assert len(inc_data["stock"]) > 0


def test_empresa_sin_modulo_offline_falla_403_feature_not_in_plan(saas_world):
    w = saas_world
    feat = w.db.scalar(
        select(PlanFeatureModel).where(
            PlanFeatureModel.plan_id == w.plan_basico.id,
            PlanFeatureModel.feature_code == "offline",
        )
    )
    if feat:
        feat.enabled = False
        w.db.commit()

    r = w.client.get("/api/v1/offline/snapshot", headers=w.headers(w.admin_a))
    assert r.status_code == 403, r.text
    body = r.json()
    error = body.get("error") or body
    assert error.get("code") == "feature_not_in_plan"


def test_ping_sin_token_devuelve_200_status_ok(saas_world):
    w = saas_world
    r = w.client.get("/api/v1/offline/ping")
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "ok"}


def test_fixtures_contrato_validan_contra_schemas():
    fixtures_dir = Path(__file__).resolve().parents[4] / "docs/MJ-02-offline-automatico/contrato/fixtures"
    s1 = OfflineSnapshot.model_validate(json.loads((fixtures_dir / "instantanea_completa.json").read_text("utf-8")))
    assert s1.full is True
    s2 = OfflineSnapshot.model_validate(json.loads((fixtures_dir / "instantanea_incremental.json").read_text("utf-8")))
    assert s2.full is False
    b_in = SyncBatchIn.model_validate(json.loads((fixtures_dir / "lote_peticion.json").read_text("utf-8")))
    assert len(b_in.operations) == 1
    b_out1 = SyncBatchOut.model_validate(json.loads((fixtures_dir / "lote_confirmada.json").read_text("utf-8")))
    assert b_out1.results[0].status == "CONFIRMED"
    b_out2 = SyncBatchOut.model_validate(json.loads((fixtures_dir / "lote_conflicto.json").read_text("utf-8")))
    assert b_out2.results[0].status == "CONFLICT"
    b_out3 = SyncBatchOut.model_validate(json.loads((fixtures_dir / "lote_reintentar.json").read_text("utf-8")))
    assert b_out3.results[0].status in ("RETRY", "CONFLICT")
