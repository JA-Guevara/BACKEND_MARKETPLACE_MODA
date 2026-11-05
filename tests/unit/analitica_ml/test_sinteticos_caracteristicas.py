import numpy as np
import pytest
from src.analitica_ml.domain.sinteticos import GeneradorSintetico
from src.analitica_ml.domain.caracteristicas import (
    ExtractorCaracteristicasDemanda,
    ExtractorCaracteristicasRFM,
)


def test_generador_sintetico_reproducibilidad():
    gen1 = GeneradorSintetico(seed=42)
    series1 = gen1.generar_series_demanda(num_variantes=3, num_semanas=10, num_sucursales=2)

    gen2 = GeneradorSintetico(seed=42)
    series2 = gen2.generar_series_demanda(num_variantes=3, num_semanas=10, num_sucursales=2)

    assert len(series1) == len(series2) == 3 * 10 * 2
    assert series1[0] == series2[0]
    assert series1[10]["unidades_vendidas"] == series2[10]["unidades_vendidas"]


def test_extractor_caracteristicas_demanda():
    gen = GeneradorSintetico(seed=42)
    series = gen.generar_series_demanda(num_variantes=2, num_semanas=12, num_sucursales=1)

    extractor = ExtractorCaracteristicasDemanda()
    X, y, feature_names, meta = extractor.preparar_dataset(series)

    # Cada serie tiene 12 semanas. Como requiere lag 4, genera 12 - 4 = 8 observaciones por serie.
    # 2 variantes * 1 sucursal = 2 series -> 16 filas en total
    assert X.shape[0] == 16
    assert len(y) == 16
    assert "lag_1" in feature_names
    assert "media_movil_4" in feature_names
    assert "var_var-001" in feature_names
    assert len(meta) == 16


def test_extractor_caracteristicas_rfm():
    gen = GeneradorSintetico(seed=42)
    clientes = gen.generar_clientes_rfm(num_clientes=50)

    extractor = ExtractorCaracteristicasRFM()
    X_scaled = extractor.fit_transform(clientes)

    assert X_scaled.shape == (50, 3)
    # Media normalizada debe estar cercana a 0 y desvío cercano a 1
    assert abs(np.mean(X_scaled[:, 0])) < 1e-6
    assert abs(np.std(X_scaled[:, 0]) - 1.0) < 1e-5
