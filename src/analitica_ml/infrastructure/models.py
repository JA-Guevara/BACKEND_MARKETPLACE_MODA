from datetime import datetime, timezone
from sqlalchemy import CHAR, Boolean, Column, DateTime, Float, ForeignKey, Integer, Index, JSON, LargeBinary, Numeric, String, Text, Uuid
from sqlalchemy.orm import relationship
from src.infrastructure.database.base import Base


class MLTrainingRunModel(Base):
    __tablename__ = "ml_training_runs"
    __table_args__ = (Index("ix_ml_training_runs_tenant", "tenant_id"),)

    id = Column(String(36), primary_key=True)
    tenant_id = Column(Uuid(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    model_type = Column(String(50), nullable=False)  # DEMAND, RFM, ANOMALY
    status = Column(String(30), nullable=False, default="RUNNING")  # RUNNING, COMPLETED, REJECTED (CU-30: candidato no promovido), FAILED
    metrics = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class MLModelModel(Base):
    __tablename__ = "ml_models"
    __table_args__ = (Index("ix_ml_models_tenant_active", "tenant_id", "is_active"),)

    id = Column(String(36), primary_key=True)
    tenant_id = Column(Uuid(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    model_type = Column(String(50), nullable=False)
    version = Column(String(50), nullable=False)
    artifact = Column(LargeBinary, nullable=False)
    artifact_bytes = Column(Integer, nullable=False)
    artifact_sha256 = Column(CHAR(64), nullable=False)
    metrics = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    predictions = relationship("MLPredictionModel", back_populates="model", cascade="all, delete-orphan")


class MLPredictionModel(Base):
    __tablename__ = "ml_predictions"
    __table_args__ = (Index("ix_ml_predictions_tenant_date", "tenant_id", "target_date"),)

    id = Column(String(36), primary_key=True)
    tenant_id = Column(Uuid(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    model_id = Column(String(36), ForeignKey("ml_models.id", ondelete="CASCADE"), nullable=False)
    target_date = Column(String(20), nullable=False)
    variant_id = Column(String(36), nullable=False)
    branch_id = Column(String(36), nullable=False)
    predicted_units = Column(Float, nullable=False)
    actual_units = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    model = relationship("MLModelModel", back_populates="predictions")


class MLCustomerSegmentModel(Base):
    __tablename__ = "ml_customer_segments"
    __table_args__ = (Index("ix_ml_customer_segments_tenant", "tenant_id"),)

    id = Column(String(36), primary_key=True)
    tenant_id = Column(Uuid(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    customer_id = Column(String(36), nullable=False)
    segment_name = Column(String(100), nullable=False)
    recency_days = Column(Integer, nullable=False)
    frequency_orders = Column(Integer, nullable=False)
    monetary_total = Column(Numeric(12, 2), nullable=False)
    cluster_id = Column(Integer, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class MLAnomalyModel(Base):
    __tablename__ = "ml_anomalies"
    __table_args__ = (Index("ix_ml_anomalies_tenant_date", "tenant_id", "sale_date"),)

    id = Column(String(36), primary_key=True)
    tenant_id = Column(Uuid(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(String(36), nullable=False)
    sale_date = Column(String(20), nullable=False)
    anomaly_score = Column(Float, nullable=False)
    reason = Column(String(100), nullable=False)
    resolved = Column(Boolean, default=False, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
