"""CU-30 · Conservar el modelo anterior si el nuevo empeora.

El entrenamiento real (EntrenamientoService / POST /analytics/ml/initialize)
compara el candidato contra el modelo DEMAND activo con
EvaluadorModelos.validar_candidato_vs_baseline antes de activarlo.
"""
from sqlalchemy.orm.attributes import flag_modified

from src.analitica_ml.application.entrenamiento_service import EntrenamientoService
from src.analitica_ml.infrastructure.models import MLModelModel, MLPredictionModel, MLTrainingRunModel


def _activos(db, tenant_id):
    return db.query(MLModelModel).filter(
        MLModelModel.tenant_id == tenant_id,
        MLModelModel.model_type == "DEMAND",
        MLModelModel.is_active == True,  # noqa: E712
    ).all()


def _fijar_mae(db, modelo, mae):
    modelo.metrics = {**(modelo.metrics or {}), "mae": mae}
    flag_modified(modelo, "metrics")
    db.commit()


def _ultimo_run(db, tenant_id):
    return (
        db.query(MLTrainingRunModel)
        .filter(MLTrainingRunModel.tenant_id == tenant_id, MLTrainingRunModel.model_type == "DEMAND")
        .order_by(MLTrainingRunModel.created_at.desc())
        .first()
    )


def test_sin_modelo_previo_el_candidato_se_activa(saas_world):
    w = saas_world
    tenant_id = str(w.tenants[1].id)
    res = EntrenamientoService(w.db).inicializar_datos_y_modelos(tenant_id, seed=42)
    assert res["demand_promoted"] is True
    assert res["demand_promotion"] is None
    activos = _activos(w.db, tenant_id)
    assert [m.id for m in activos] == [res["demand_model_id"]]
    assert _ultimo_run(w.db, tenant_id).status == "COMPLETED"


def test_candidato_peor_conserva_el_modelo_anterior(saas_world):
    w = saas_world
    tenant_id = str(w.tenants[1].id)
    primero = EntrenamientoService(w.db).inicializar_datos_y_modelos(tenant_id, seed=42)
    anterior = w.db.get(MLModelModel, primero["demand_model_id"])
    # El modelo activo pasa a ser "casi perfecto": cualquier candidato real es peor.
    _fijar_mae(w.db, anterior, 0.0001)
    preds_antes = {p.model_id for p in w.db.query(MLPredictionModel).filter(MLPredictionModel.tenant_id == tenant_id)}

    # Flujo real por HTTP.
    resp = w.client.post("/api/v1/analytics/ml/initialize?seed=42", headers=w.headers(w.admins[1]))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["demand_promoted"] is False
    assert data["demand_run_status"] == "REJECTED"
    assert data["demand_promotion"]["aprobado"] is False
    assert data["demand_model_id"] == anterior.id

    w.db.expire_all()
    activos = _activos(w.db, tenant_id)
    assert [m.id for m in activos] == [anterior.id]
    total = w.db.query(MLModelModel).filter(MLModelModel.tenant_id == tenant_id).count()
    assert total == 1  # el candidato rechazado no se publica
    run = _ultimo_run(w.db, tenant_id)
    assert run.status == "REJECTED"
    assert run.metrics["promocion"]["modelo_baseline_id"] == anterior.id
    assert "no promovido" in (run.error_message or "")
    preds_despues = {p.model_id for p in w.db.query(MLPredictionModel).filter(MLPredictionModel.tenant_id == tenant_id)}
    assert preds_despues == preds_antes == {anterior.id}


def test_candidato_mejor_reemplaza_al_anterior(saas_world):
    w = saas_world
    tenant_id = str(w.tenants[1].id)
    svc = EntrenamientoService(w.db)
    primero = svc.inicializar_datos_y_modelos(tenant_id, seed=42)
    anterior = w.db.get(MLModelModel, primero["demand_model_id"])
    # El modelo activo es muy malo: el candidato lo mejora.
    _fijar_mae(w.db, anterior, 1_000_000.0)

    res = svc.inicializar_datos_y_modelos(tenant_id, seed=42)
    assert res["demand_promoted"] is True
    assert res["demand_promotion"]["aprobado"] is True
    assert res["demand_model_id"] != anterior.id

    w.db.expire_all()
    activos = _activos(w.db, tenant_id)
    assert [m.id for m in activos] == [res["demand_model_id"]]
    assert w.db.get(MLModelModel, anterior.id).is_active is False
    assert _ultimo_run(w.db, tenant_id).status == "COMPLETED"
