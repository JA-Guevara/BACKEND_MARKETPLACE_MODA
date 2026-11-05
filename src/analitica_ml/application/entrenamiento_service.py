from datetime import datetime, timezone
import uuid
from typing import Any, Dict
import numpy as np
from sqlalchemy.orm import Session

from src.analitica_ml.domain.caracteristicas import (
    ExtractorCaracteristicasDemanda,
    ExtractorCaracteristicasRFM,
)
from src.analitica_ml.domain.evaluacion import EvaluadorModelos
from src.analitica_ml.domain.modelos import (
    ModeloDemanda,
    ModeloDetectorAnomalias,
    ModeloSectorizacionRFM,
)
from src.analitica_ml.domain.sinteticos import GeneradorSintetico
from src.analitica_ml.infrastructure.artefactos import GestorArtefactosML
from src.analitica_ml.infrastructure.models import (
    MLAnomalyModel,
    MLCustomerSegmentModel,
    MLModelModel,
    MLPredictionModel,
    MLTrainingRunModel,
)
from src.shared.exceptions.domain_exception import NotFoundError


class EntrenamientoService:
    def __init__(self, db: Session, artefactos: GestorArtefactosML | None = None) -> None:
        self.db = db
        self.artefactos = artefactos or GestorArtefactosML()

    def inicializar_datos_y_modelos(self, tenant_id: str | Any, seed: int = 42) -> Dict[str, Any]:
        """Arranque en frío determinista: genera datos sintéticos y entrena los 3 modelos."""
        tenant_id = str(tenant_id)
        gen = GeneradorSintetico(seed=seed)

        # 1. ENTRENAR MODELO DE DEMANDA
        run_demanda = MLTrainingRunModel(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            model_type="DEMAND",
            status="RUNNING",
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(run_demanda)
        self.db.flush()

        series = gen.generar_series_demanda(num_variantes=8, num_semanas=52, num_sucursales=3)
        extractor_demanda = ExtractorCaracteristicasDemanda()
        X, y, feature_names, meta = extractor_demanda.preparar_dataset(series)

        # 80/20 train/test
        split_idx = int(len(X) * 0.8)
        X_train, y_train = X[:split_idx], y[:split_idx]
        X_test, y_test = X[split_idx:], y[split_idx:]

        modelo_demanda = ModeloDemanda(n_estimators=60, max_depth=4, random_state=seed)
        modelo_demanda.entrenar(X_train, y_train, feature_names)

        preds_test = modelo_demanda.predecir(X_test)
        metricas_demanda = EvaluadorModelos.metricas_regresion(y_test, preds_test)

        # Desactivar modelos anteriores
        self.db.query(MLModelModel).filter(
            MLModelModel.tenant_id == tenant_id,
            MLModelModel.model_type == "DEMAND",
            MLModelModel.is_active == True,
        ).update({"is_active": False})

        model_id = str(uuid.uuid4())
        artifact = self.artefactos.serializar(modelo_demanda)

        ml_model = MLModelModel(
            id=model_id,
            tenant_id=tenant_id,
            name="GradientBoosting Demand Regressor",
            model_type="DEMAND",
            version="1.0.0-synthetic",
            artifact=artifact,
            artifact_bytes=len(artifact),
            artifact_sha256=self.artefactos.sha256(artifact),
            metrics=metricas_demanda,
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(ml_model)

        run_demanda.status = "COMPLETED"
        run_demanda.metrics = metricas_demanda
        run_demanda.finished_at = datetime.now(timezone.utc)

        # Generar predicciones para las últimas semanas
        self.db.query(MLPredictionModel).filter(MLPredictionModel.tenant_id == tenant_id).delete()
        for i in range(min(40, len(X_test))):
            idx_global = split_idx + i
            m_info = meta[idx_global]
            pred_val = float(preds_test[i])
            act_val = float(y_test[i])
            pred_row = MLPredictionModel(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                model_id=model_id,
                target_date=m_info.get("fecha_semana", f"2026-W{m_info['semana']:02d}"),
                variant_id=m_info["variante_id"],
                branch_id=m_info["sucursal_id"],
                predicted_units=round(pred_val, 1),
                actual_units=round(act_val, 1),
                created_at=datetime.now(timezone.utc),
            )
            self.db.add(pred_row)

        # 2. ENTRENAR SEGMENTACIÓN RFM
        clientes = gen.generar_clientes_rfm(num_clientes=120)
        extractor_rfm = ExtractorCaracteristicasRFM()
        X_rfm = extractor_rfm.fit_transform(clientes)

        modelo_rfm = ModeloSectorizacionRFM(k_fijo=4, random_state=seed)
        modelo_rfm.entrenar(X_rfm, clientes)
        clusters, nombres_segmentos = modelo_rfm.predecir(X_rfm)

        self.db.query(MLCustomerSegmentModel).filter(MLCustomerSegmentModel.tenant_id == tenant_id).delete()
        for c, cluster_id, seg_name in zip(clientes, clusters, nombres_segmentos):
            seg_row = MLCustomerSegmentModel(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                customer_id=c["cliente_id"],
                segment_name=seg_name,
                recency_days=c["recency_dias"],
                frequency_orders=c["frequency_compras"],
                monetary_total=c["monetary_total"],
                cluster_id=int(cluster_id),
                updated_at=datetime.now(timezone.utc),
            )
            self.db.add(seg_row)

        # 3. ENTRENAR DETECCIÓN DE ANOMALÍAS
        ventas_diarias = gen.generar_ventas_diarias_anomalias(num_dias=90, num_sucursales=3, tasa_anomalias=0.06)
        X_anomalias = np.array([
            [v["ventas_totales"], v["num_transacciones"], v["ticket_promedio"]]
            for v in ventas_diarias
        ])

        detector = ModeloDetectorAnomalias(contaminacion=0.06, random_state=seed)
        detector.entrenar(X_anomalias)
        es_anomalia, scores = detector.predecir(X_anomalias)

        self.db.query(MLAnomalyModel).filter(MLAnomalyModel.tenant_id == tenant_id).delete()
        anomalias_detectadas = 0
        for v, anom, score in zip(ventas_diarias, es_anomalia, scores):
            if anom:
                anomalias_detectadas += 1
                razon = v.get("tipo_anomalia") or ("Caída de ventas" if v["ventas_totales"] < 500 else "Pico atípico")
                anom_row = MLAnomalyModel(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    branch_id=v["sucursal_id"],
                    sale_date=v["fecha"],
                    anomaly_score=round(float(score), 4),
                    reason=razon,
                    resolved=False,
                    notes=f"Ventas: {v['ventas_totales']}, Tx: {v['num_transacciones']}",
                    created_at=datetime.now(timezone.utc),
                )
                self.db.add(anom_row)

        self.db.commit()

        return {
            "demand_model_id": model_id,
            "demand_metrics": metricas_demanda,
            "segmented_customers": len(clientes),
            "detected_anomalies": anomalias_detectadas,
            "status": "COMPLETED",
        }

    def cargar_modelo_activo(self, tenant_id: str | Any, model_type: str = "DEMAND") -> Any:
        """Reconstruye el modelo activo desde el artefacto guardado en la base.

        No toca el sistema de archivos: después de un despliegue en Railway el
        binario sigue disponible en la fila de ``ml_models``.
        """
        tenant_id = str(tenant_id)
        row = (
            self.db.query(MLModelModel)
            .filter(
                MLModelModel.tenant_id == tenant_id,
                MLModelModel.model_type == model_type,
                MLModelModel.is_active == True,
            )
            .order_by(MLModelModel.created_at.desc())
            .first()
        )
        if row is None:
            raise NotFoundError(f"No hay un modelo activo de tipo {model_type} para esta empresa.")
        return self.artefactos.deserializar(row.artifact)

    def predecir_demanda(self, tenant_id: str | Any, caracteristicas: Any) -> Any:
        """Inferencia de demanda leyendo el artefacto de la base."""
        modelo = self.cargar_modelo_activo(tenant_id, model_type="DEMAND")
        return modelo.predecir(caracteristicas)
