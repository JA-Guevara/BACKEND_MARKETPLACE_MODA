import math
from typing import Any, Dict
import numpy as np


class EvaluadorModelos:
    """Calcula métricas de precisión y valida reglas de negocio para publicación."""

    @staticmethod
    def metricas_regresion(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
        y_true = np.asarray(y_true, dtype=float)
        y_pred = np.asarray(y_pred, dtype=float)

        errores = y_true - y_pred
        mae = float(np.mean(np.abs(errores)))
        mse = float(np.mean(errores**2))
        rmse = float(math.sqrt(mse))

        # MAPE protegiendo división por cero
        denom = np.where(y_true == 0, 1.0, y_true)
        mape = float(np.mean(np.abs(errores) / denom) * 100.0)

        # R² score
        ss_res = np.sum(errores**2)
        ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
        r2 = float(1.0 - (ss_res / ss_tot)) if ss_tot > 0 else 0.0

        return {
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
            "mape": round(mape, 2),
            "r2": round(r2, 4),
        }

    @staticmethod
    def validar_candidato_vs_baseline(
        metricas_candidato: Dict[str, float],
        metricas_baseline: Dict[str, float],
        umbral_mejora: float = 0.05,
    ) -> Dict[str, Any]:
        """Regla de publicación:

        El nuevo modelo debe superar o no empeorar más de umbral respecto a la línea base.
        """
        mae_candidato = metricas_candidato.get("mae", 9999.0)
        mae_baseline = metricas_baseline.get("mae", 9999.0)

        # Si el modelo tiene MAE <= baseline * (1 + margen), se aprueba
        mejora_pct = ((mae_baseline - mae_candidato) / max(mae_baseline, 0.001)) * 100.0
        aprobado = mae_candidato <= (mae_baseline * 1.05)

        return {
            "aprobado": aprobado,
            "mae_candidato": mae_candidato,
            "mae_baseline": mae_baseline,
            "mejora_porcentual": round(mejora_pct, 2),
            "razon": (
                "Modelo supera umbral de precisión requerido."
                if aprobado
                else f"MAE ({mae_candidato}) no supera al baseline ({mae_baseline})."
            ),
        }
