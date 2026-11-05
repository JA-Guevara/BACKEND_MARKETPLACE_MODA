import math
from typing import Any, Dict, List, Tuple
import numpy as np


class ExtractorCaracteristicasDemanda:
    """Construye matrices de características autorregresivas y exógenas para pronóstico de demanda."""

    def __init__(self) -> None:
        pass

    def preparar_dataset(
        self, registros: List[Dict[str, Any]]
    ) -> Tuple[np.ndarray, np.ndarray, List[str], List[Dict[str, Any]]]:
        """Convierte registros ordenados por serie temporal en matriz de características X e target y.

        Retorna:
            X: np.ndarray de forma (N, num_features)
            y: np.ndarray de forma (N,)
            feature_names: List[str]
            metadata: List[Dict] (variante, sucursal, fecha_semana)
        """
        # Agrupar registros por serie temporal (variante_id, sucursal_id)
        series: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for r in registros:
            clave = (r["variante_id"], r["sucursal_id"])
            if clave not in series:
                series[clave] = []
            series[clave].append(r)

        X_filas: List[List[float]] = []
        y_filas: List[float] = []
        meta_filas: List[Dict[str, Any]] = []

        # Extraer variantes y sucursales únicas para encoding determinista
        variantes_unicas = sorted(list({r["variante_id"] for r in registros}))
        sucursales_unicas = sorted(list({r["sucursal_id"] for r in registros}))

        for (v_id, s_id), serie in series.items():
            serie_ord = sorted(serie, key=lambda x: x["semana"])
            for i in range(4, len(serie_ord)):
                actual = serie_ord[i]
                lag1 = float(serie_ord[i - 1]["unidades_vendidas"])
                lag2 = float(serie_ord[i - 2]["unidades_vendidas"])
                lag3 = float(serie_ord[i - 3]["unidades_vendidas"])
                lag4 = float(serie_ord[i - 4]["unidades_vendidas"])

                media_movil_4 = (lag1 + lag2 + lag3 + lag4) / 4.0
                tendencia = lag1 - lag4

                semana = actual["semana"]
                sin_semana = math.sin(2 * math.pi * semana / 52)
                cos_semana = math.cos(2 * math.pi * semana / 52)

                precio = float(actual["precio"])
                es_festivo = float(actual.get("es_festivo", 0))
                en_promocion = float(actual.get("en_promocion", 0))

                fila = [
                    lag1,
                    lag2,
                    lag3,
                    lag4,
                    media_movil_4,
                    tendencia,
                    precio,
                    es_festivo,
                    en_promocion,
                    sin_semana,
                    cos_semana,
                ]

                # One-hot encoding de variante y sucursal
                for u_v in variantes_unicas:
                    fila.append(1.0 if v_id == u_v else 0.0)
                for u_s in sucursales_unicas:
                    fila.append(1.0 if s_id == u_s else 0.0)

                X_filas.append(fila)
                y_filas.append(float(actual["unidades_vendidas"]))
                meta_filas.append({
                    "variante_id": v_id,
                    "sucursal_id": s_id,
                    "semana": actual["semana"],
                    "fecha_semana": actual.get("fecha_semana"),
                })

        feature_names = [
            "lag_1",
            "lag_2",
            "lag_3",
            "lag_4",
            "media_movil_4",
            "tendencia",
            "precio",
            "es_festivo",
            "en_promocion",
            "sin_semana",
            "cos_semana",
        ]
        feature_names.extend([f"var_{v}" for v in variantes_unicas])
        feature_names.extend([f"suc_{s}" for s in sucursales_unicas])

        return np.array(X_filas), np.array(y_filas), feature_names, meta_filas


class ExtractorCaracteristicasRFM:
    """Normaliza y escala métricas RFM de clientes."""

    def __init__(self) -> None:
        self.mean_: np.ndarray | None = None
        self.std_: np.ndarray | None = None

    def fit_transform(self, clientes: List[Dict[str, Any]]) -> np.ndarray:
        raw = np.array([
            [float(c["recency_dias"]), float(c["frequency_compras"]), float(c["monetary_total"])]
            for c in clientes
        ])
        # Log-transform para estabilizar sesgos de monetary y frequency
        transformed = np.zeros_like(raw)
        transformed[:, 0] = raw[:, 0]  # recency sin log
        transformed[:, 1] = np.log1p(raw[:, 1])  # log(1 + frequency)
        transformed[:, 2] = np.log1p(raw[:, 2])  # log(1 + monetary)

        self.mean_ = np.mean(transformed, axis=0)
        self.std_ = np.std(transformed, axis=0)
        # Evitar división por cero
        self.std_[self.std_ == 0] = 1.0

        return (transformed - self.mean_) / self.std_

    def transform(self, clientes: List[Dict[str, Any]]) -> np.ndarray:
        if self.mean_ is None or self.std_ is None:
            raise RuntimeError("Extractor no ha sido ajustado (fit).")
        raw = np.array([
            [float(c["recency_dias"]), float(c["frequency_compras"]), float(c["monetary_total"])]
            for c in clientes
        ])
        transformed = np.zeros_like(raw)
        transformed[:, 0] = raw[:, 0]
        transformed[:, 1] = np.log1p(raw[:, 1])
        transformed[:, 2] = np.log1p(raw[:, 2])
        return (transformed - self.mean_) / self.std_
