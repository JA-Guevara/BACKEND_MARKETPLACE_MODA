import numpy as np
import pytest
from src.analitica_ml.domain.sinteticos import GeneradorSintetico
from src.analitica_ml.domain.caracteristicas import (
    ExtractorCaracteristicasDemanda,
    ExtractorCaracteristicasRFM,
)
from src.analitica_ml.domain.modelos import (
    ModeloDemanda,
    ModeloSectorizacionRFM,
    ModeloDetectorAnomalias,
)
from src.analitica_ml.domain.evaluacion import EvaluadorModelos


def test_entrenamiento_y_prediccion_demanda():
    gen = GeneradorSintetico(seed=42)
    series = gen.generar_series_demanda(num_variantes=3, num_semanas=20, num_sucursales=2)
    extractor = ExtractorCaracteristicasDemanda()
    X, y, names, _ = extractor.preparar_dataset(series)

    # Split train/test
    n_train = int(len(X) * 0.8)
    X_train, y_train = X[:n_train], y[:n_train]
    X_test, y_test = X[n_train:], y[n_train:]

    modelo = ModeloDemanda(n_estimators=30, max_depth=3, random_state=42)
    modelo.entrenar(X_train, y_train, names)

    preds = modelo.predecir(X_test)
    assert len(preds) == len(y_test)
    assert np.all(preds >= 0.0)

    metricas = EvaluadorModelos.metricas_regresion(y_test, preds)
    assert "mae" in metricas
    assert "rmse" in metricas
    assert metricas["mae"] < 25.0


def test_clustering_rfm_semantico():
    gen = GeneradorSintetico(seed=42)
    clientes = gen.generar_clientes_rfm(num_clientes=60)
    extractor = ExtractorCaracteristicasRFM()
    X = extractor.fit_transform(clientes)

    modelo_rfm = ModeloSectorizacionRFM(k_fijo=3, random_state=42)
    modelo_rfm.entrenar(X, clientes)

    clusters, nombres = modelo_rfm.predecir(X)
    assert len(clusters) == 60
    assert len(nombres) == 60
    assert any("VIP" in n or "Estrella" in n for n in nombres)
    assert modelo_rfm.silhouette_score_ > 0.0


def test_detector_anomalias_isolation_forest():
    gen = GeneradorSintetico(seed=42)
    datos = gen.generar_ventas_diarias_anomalias(num_dias=60, num_sucursales=2, tasa_anomalias=0.1)

    X = np.array([
        [d["ventas_totales"], d["num_transacciones"], d["ticket_promedio"]]
        for d in datos
    ])

    detector = ModeloDetectorAnomalias(contaminacion=0.1, random_state=42)
    detector.entrenar(X)

    es_anomalia, scores = detector.predecir(X)
    assert len(es_anomalia) == len(datos)
    # Debe detectar al menos una anomalía
    assert np.sum(es_anomalia) > 0
