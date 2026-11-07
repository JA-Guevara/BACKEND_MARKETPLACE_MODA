from typing import Any, Dict, List, Optional
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.analitica_ml.application.entrenamiento_service import EntrenamientoService
from src.analitica_ml.infrastructure.models import (
    MLAnomalyModel,
    MLCustomerSegmentModel,
    MLModelModel,
    MLPredictionModel,
)


class DashboardMLService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def asegurar_datos_iniciales(self, tenant_id: str | Any) -> None:
        """Garantiza que exista al menos un modelo y datos iniciales para el tenant."""
        tenant_id = str(tenant_id)
        hay_modelo = self.db.query(MLModelModel).filter(MLModelModel.tenant_id == tenant_id).first()
        if not hay_modelo:
            entrenamiento = EntrenamientoService(self.db)
            entrenamiento.inicializar_datos_y_modelos(tenant_id)

    def obtener_tablero(self, tenant_id: str | Any) -> Dict[str, Any]:
        tenant_id = str(tenant_id)
        self.asegurar_datos_iniciales(tenant_id)

        # 1. Modelo activo de demanda y métricas
        modelo_activo = (
            self.db.query(MLModelModel)
            .filter(MLModelModel.tenant_id == tenant_id, MLModelModel.is_active == True)
            .order_by(MLModelModel.created_at.desc())
            .first()
        )
        metricas = modelo_activo.metrics if modelo_activo else {"mae": 0.0, "rmse": 0.0, "r2": 0.0}

        # 2. Predicciones recientes agrupadas por fecha
        predicciones_raw = (
            self.db.query(
                MLPredictionModel.target_date,
                func.sum(MLPredictionModel.predicted_units).label("total_predicho"),
                func.sum(MLPredictionModel.actual_units).label("total_real"),
            )
            .filter(MLPredictionModel.tenant_id == tenant_id)
            .group_by(MLPredictionModel.target_date)
            .order_by(MLPredictionModel.target_date.asc())
            .all()
        )

        serie_demanda = [
            {
                "fecha": p.target_date,
                "predicho": round(float(p.total_predicho or 0.0), 1),
                "real": round(float(p.total_real or 0.0), 1) if p.total_real is not None else None,
            }
            for p in predicciones_raw
        ]

        # 3. Distribución de segmentos RFM
        segmentos_dist = (
            self.db.query(
                MLCustomerSegmentModel.segment_name,
                func.count(MLCustomerSegmentModel.id).label("conteo"),
                func.avg(MLCustomerSegmentModel.monetary_total).label("promedio_monetary"),
            )
            .filter(MLCustomerSegmentModel.tenant_id == tenant_id)
            .group_by(MLCustomerSegmentModel.segment_name)
            .all()
        )

        total_clientes = sum(s.conteo for s in segmentos_dist) or 1
        segmentos_resumen = [
            {
                "segmento": s.segment_name,
                "conteo": s.conteo,
                "porcentaje": round((s.conteo / total_clientes) * 100.0, 1),
                "ticket_promedio": round(float(s.promedio_monetary or 0.0), 2),
            }
            for s in segmentos_dist
        ]

        # 4. Anomalías activas y conteos
        anomalias_activas = (
            self.db.query(MLAnomalyModel)
            .filter(MLAnomalyModel.tenant_id == tenant_id, MLAnomalyModel.resolved == False)
            .order_by(MLAnomalyModel.sale_date.desc())
            .limit(10)
            .all()
        )

        anomalias_resumen = [
            {
                "id": a.id,
                "branch_id": a.branch_id,
                "fecha": a.sale_date,
                "score": a.anomaly_score,
                "razon": a.reason,
                "notas": a.notes,
            }
            for a in anomalias_activas
        ]

        total_anomalias_pendientes = (
            self.db.query(func.count(MLAnomalyModel.id))
            .filter(MLAnomalyModel.tenant_id == tenant_id, MLAnomalyModel.resolved == False)
            .scalar()
            or 0
        )

        unidades_proyectadas = sum(s["predicho"] for s in serie_demanda[-4:]) if len(serie_demanda) >= 4 else 0.0

        kpis = {
            "demanda_proyectada_proximas_4_semanas": round(unidades_proyectadas, 1),
            "total_clientes_segmentados": total_clientes,
            "anomalias_pendientes": total_anomalias_pendientes,
            "mae": metricas.get("mae", 0.0),
            "r2": metricas.get("r2", 0.0),
        }

        recomendaciones = self.generar_recomendaciones_estrategicas(
            tenant_id, kpis, serie_demanda, segmentos_resumen, anomalias_resumen
        )

        return {
            "modelo_activo": {
                "id": modelo_activo.id if modelo_activo else None,
                "nombre": modelo_activo.name if modelo_activo else "Sin modelo",
                "version": modelo_activo.version if modelo_activo else "N/A",
                "metricas": metricas,
            },
            "kpis": kpis,
            "serie_demanda": serie_demanda,
            "segmentos": segmentos_resumen,
            "anomalias_recientes": anomalias_resumen,
            "recomendaciones_ia": recomendaciones,
        }

    def generar_recomendaciones_estrategicas(
        self,
        tenant_id: str,
        kpis: Dict[str, Any],
        serie_demanda: List[Dict[str, Any]],
        segmentos: List[Dict[str, Any]],
        anomalias: List[Dict[str, Any]],
    ) -> List[Dict[str, str]]:
        recomendaciones: List[Dict[str, str]] = []
        demanda_4sem = kpis.get("demanda_proyectada_proximas_4_semanas", 0.0)

        # 1. Abastecimiento y previsión de demanda
        if demanda_4sem > 100:
            recomendaciones.append({
                "tipo": "INVENTARIO",
                "prioridad": "ALTA",
                "titulo": "Reposición prioritaria por aceleración de demanda proyectada",
                "descripcion": f"La proyección para las próximas 4 semanas prevé un volumen de {demanda_4sem:.0f} prendas. Se recomienda coordinar órdenes de compra con proveedores antes de agotar margen de seguridad.",
                "accion": "Ver existencias críticas",
                "impacto_estimado": "+18% de disponibilidad y reducción de quiebres de inventario",
            })
        else:
            recomendaciones.append({
                "tipo": "INVENTARIO",
                "prioridad": "MEDIA",
                "titulo": "Monitoreo continuo de existencias mínimas",
                "descripcion": "El flujo proyectado es estable. Mantener niveles de rotación estándar y verificar alertas de prendas por agotarse.",
                "accion": "Ver catálogo y stock",
                "impacto_estimado": "Optimización del costo de almacenamiento",
            })

        # 2. Clientes y Segmentación RFM
        segmento_riesgo = next((s for s in segmentos if "riesgo" in s["segmento"].lower() or "hibern" in s["segmento"].lower()), None)
        if segmento_riesgo:
            recomendaciones.append({
                "tipo": "CLIENTES",
                "prioridad": "ALTA",
                "titulo": "Campaña de reactivación para clientes en riesgo",
                "descripcion": f"El {segmento_riesgo['porcentaje']}% de tus compradores se encuentra en el segmento '{segmento_riesgo['segmento']}'. Sugerimos automatizar un cupón del 10% de descuento vía email o WhatsApp para compras este mes.",
                "accion": "Exportar segmento RFM",
                "impacto_estimado": "Recuperación estimada de 10 a 15 clientes por mes",
            })
        else:
            recomendaciones.append({
                "tipo": "CLIENTES",
                "prioridad": "MEDIA",
                "titulo": "Beneficios exclusivos para clientes de alto valor (VIP)",
                "descripcion": "Incentivar a los clientes frecuentes con acceso anticipado a nuevas colecciones o promociones 2x1 en temporadas de cambio.",
                "accion": "Revisar cartera VIP",
                "impacto_estimado": "+15% en recurrencia de compra y ticket promedio",
            })

        # 3. Precios y Rotación Comercial
        recomendaciones.append({
            "tipo": "PRECIOS",
            "prioridad": "MEDIA",
            "titulo": "Promociones en prendas de baja rotación",
            "descripcion": "Identificar artículos con stock inmovilizado por más de 30 días para aplicar descuentos por paquete o 20% en segunda prenda.",
            "accion": "Configurar promociones",
            "impacto_estimado": "Liberación de capital de trabajo y rotación de almacén",
        })

        # 4. Auditoría Operativa y Anomalías
        if kpis.get("anomalias_pendientes", 0) > 0:
            recomendaciones.append({
                "tipo": "OPERATIVO",
                "prioridad": "ALTA",
                "titulo": f"Auditoría inmediata: {kpis['anomalias_pendientes']} anomalías operativas abiertas",
                "descripcion": "Se detectaron desviaciones atípicas en ventas o transacciones diarias. Verificar con los administradores de sucursal la causa (cortes, fallas de terminal, eventos locales).",
                "accion": "Resolver anomalías",
                "impacto_estimado": "Control estricto de discrepancias de caja y calidad de servicio",
            })
        else:
            recomendaciones.append({
                "tipo": "OPERATIVO",
                "prioridad": "BAJA",
                "titulo": "Operación en sucursales en parámetros normales",
                "descripcion": "El detector Isolation Forest no reporta desvíos críticos pendientes en las transacciones de las sucursales.",
                "accion": "Monitorear en tiempo real",
                "impacto_estimado": "Estabilidad operativa garantizada",
            })

        return recomendaciones

    def listar_segmentos(self, tenant_id: str | Any) -> List[Dict[str, Any]]:
        tenant_id = str(tenant_id)
        self.asegurar_datos_iniciales(tenant_id)
        clientes = (
            self.db.query(MLCustomerSegmentModel)
            .filter(MLCustomerSegmentModel.tenant_id == tenant_id)
            .order_by(MLCustomerSegmentModel.monetary_total.desc())
            .all()
        )
        return [
            {
                "id": c.id,
                "customer_id": c.customer_id,
                "segment_name": c.segment_name,
                "recency_days": c.recency_days,
                "frequency_orders": c.frequency_orders,
                "monetary_total": float(c.monetary_total),
                "cluster_id": c.cluster_id,
            }
            for c in clientes
        ]

    def listar_anomalias(self, tenant_id: str | Any, resueltas: Optional[bool] = None) -> List[Dict[str, Any]]:
        tenant_id = str(tenant_id)
        self.asegurar_datos_iniciales(tenant_id)
        query = self.db.query(MLAnomalyModel).filter(MLAnomalyModel.tenant_id == tenant_id)
        if resueltas is not None:
            query = query.filter(MLAnomalyModel.resolved == resueltas)
        anomalias = query.order_by(MLAnomalyModel.sale_date.desc()).all()
        return [
            {
                "id": a.id,
                "branch_id": a.branch_id,
                "sale_date": a.sale_date,
                "anomaly_score": a.anomaly_score,
                "reason": a.reason,
                "resolved": a.resolved,
                "notes": a.notes,
                "created_at": a.created_at.isoformat(),
            }
            for a in anomalias
        ]

    def resolver_anomalia(self, tenant_id: str | Any, anomalia_id: str, notes: Optional[str] = None) -> Dict[str, Any]:
        tenant_id = str(tenant_id)
        anom = (
            self.db.query(MLAnomalyModel)
            .filter(MLAnomalyModel.tenant_id == tenant_id, MLAnomalyModel.id == anomalia_id)
            .first()
        )
        if not anom:
            raise ValueError(f"Anomalía con ID {anomalia_id} no encontrada.")
        anom.resolved = True
        if notes:
            anom.notes = (anom.notes or "") + f" | Resolución: {notes}"
        self.db.commit()
        return {"id": anom.id, "resolved": True, "notes": anom.notes}
