from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class MLModelInfo(BaseModel):
    id: Optional[str] = None
    nombre: str
    version: str
    metricas: Dict[str, Any] = Field(default_factory=dict)


class DashboardKPIs(BaseModel):
    demanda_proyectada_proximas_4_semanas: float
    total_clientes_segmentados: int
    anomalias_pendientes: int
    mae: float
    r2: float


class DemandaSeriePunto(BaseModel):
    fecha: str
    predicho: float
    real: Optional[float] = None


class SegmentoResumen(BaseModel):
    segmento: str
    conteo: int
    porcentaje: float
    ticket_promedio: float


class AnomaliaItem(BaseModel):
    id: str
    branch_id: str
    fecha: str
    score: float
    razon: str
    notas: Optional[str] = None


class RecomendacionIAOut(BaseModel):
    tipo: str
    prioridad: str
    titulo: str
    descripcion: str
    accion: str
    impacto_estimado: str


class MLDashboardOut(BaseModel):
    modelo_activo: MLModelInfo
    kpis: DashboardKPIs
    serie_demanda: List[DemandaSeriePunto]
    segmentos: List[SegmentoResumen]
    anomalias_recientes: List[AnomaliaItem]
    recomendaciones_ia: List[RecomendacionIAOut] = Field(default_factory=list)


class CustomerSegmentOut(BaseModel):
    id: str
    customer_id: str
    segment_name: str
    recency_days: int
    frequency_orders: int
    monetary_total: float
    cluster_id: int


class AnomalyOut(BaseModel):
    id: str
    branch_id: str
    sale_date: str
    anomaly_score: float
    reason: str
    resolved: bool
    notes: Optional[str] = None
    created_at: str


class ResolveAnomalyIn(BaseModel):
    notes: Optional[str] = None


class MLTrainingRunOut(BaseModel):
    id: str
    tenant_id: str
    tenant_name: str
    model_type: str
    status: str
    metrics: Optional[Dict[str, Any]] = None
    created_at: str
    finished_at: Optional[str] = None
