from src.analitica_ml.application.dashboard_service import DashboardMLService
from src.analitica_ml.application.entrenamiento_service import EntrenamientoService
from src.analitica_ml.infrastructure.models import (
    MLAnomalyModel,
    MLCustomerSegmentModel,
    MLModelModel,
    MLPredictionModel,
)


def test_entrenamiento_service_inicializacion_completa(saas_world):
    w = saas_world
    tenant_id = str(w.tenants[1].id)

    svc = EntrenamientoService(w.db)
    res = svc.inicializar_datos_y_modelos(tenant_id, seed=42)

    assert res["status"] == "COMPLETED"
    assert "demand_model_id" in res
    assert res["segmented_customers"] == 120
    assert res["detected_anomalies"] > 0

    # Verificar filas en la base de datos
    modelos = w.db.query(MLModelModel).filter(MLModelModel.tenant_id == tenant_id).all()
    assert len(modelos) >= 1
    assert modelos[0].is_active is True

    preds = w.db.query(MLPredictionModel).filter(MLPredictionModel.tenant_id == tenant_id).all()
    assert len(preds) > 0

    segs = w.db.query(MLCustomerSegmentModel).filter(MLCustomerSegmentModel.tenant_id == tenant_id).all()
    assert len(segs) == 120

    anoms = w.db.query(MLAnomalyModel).filter(MLAnomalyModel.tenant_id == tenant_id).all()
    assert len(anoms) > 0


def test_dashboard_ml_endpoints_http(saas_world):
    w = saas_world
    admin = w.admins[1]
    tenant_id = str(w.tenants[1].id)
    headers = w.headers(admin)

    # Inicializar datos para el tenant pro
    EntrenamientoService(w.db).inicializar_datos_y_modelos(tenant_id, seed=42)

    # 1. Obtener tablero ML
    resp = w.client.get("/api/v1/analytics/ml/dashboard", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    assert "modelo_activo" in data
    assert "kpis" in data
    assert "serie_demanda" in data
    assert "segmentos" in data
    assert "anomalias_recientes" in data

    assert data["kpis"]["total_clientes_segmentados"] > 0
    assert len(data["segmentos"]) > 0

    # 2. Obtener lista de clientes segmentados
    resp_segs = w.client.get("/api/v1/analytics/ml/segments", headers=headers)
    assert resp_segs.status_code == 200
    segmentos_lista = resp_segs.json()["data"]
    assert len(segmentos_lista) > 0
    assert "segment_name" in segmentos_lista[0]

    # 3. Obtener y resolver anomalías
    resp_anoms = w.client.get("/api/v1/analytics/ml/anomalies", headers=headers)
    assert resp_anoms.status_code == 200
    anomalias_lista = resp_anoms.json()["data"]
    assert len(anomalias_lista) > 0

    primer_anomalia_id = anomalias_lista[0]["id"]
    resp_res = w.client.post(
        f"/api/v1/analytics/ml/anomalies/{primer_anomalia_id}/resolve",
        json={"notes": "Verificado con gerente de sucursal, corte de luz local."},
        headers=headers,
    )
    assert resp_res.status_code == 200
    res_data = resp_res.json()["data"]
    assert res_data["resolved"] is True
    assert "corte de luz" in res_data["notes"]


def test_platform_ml_endpoints_http(saas_world):
    w = saas_world
    admin = w.admins[1]
    headers = w.headers(admin)

    # Inicializar entrenamiento
    resp_init = w.client.post("/api/v1/analytics/ml/initialize?seed=42", headers=headers)
    assert resp_init.status_code == 200
    assert resp_init.json()["data"]["status"] == "COMPLETED"

    # Consultar runs y models
    resp_runs = w.client.get("/api/v1/platform/ml/runs", headers=headers)
    assert resp_runs.status_code == 200
    runs = resp_runs.json()["data"]
    assert len(runs) >= 1
    assert runs[0]["model_type"] == "DEMAND"

    resp_models = w.client.get("/api/v1/platform/ml/models", headers=headers)
    assert resp_models.status_code == 200
    models = resp_models.json()["data"]
    assert len(models) >= 1
