from typing import Literal
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, model_validator


class Quantity(BaseModel):
    quantity: int = Field(ge=1, le=99)


class StockQuantity(BaseModel):
    branch_id: UUID
    quantity: int = Field(ge=0, le=1000000)


class Address(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    recipient: str = Field(min_length=2, max_length=200)
    phone: str = Field(min_length=6, max_length=30)
    line1: str = Field(min_length=5, max_length=300)
    city: str = Field(min_length=2, max_length=100)
    country: str = Field(default="BO", min_length=2, max_length=2)
    postal_code: str | None = Field(default=None, max_length=20)


class CheckoutOrder(BaseModel):
    branch_id: UUID
    address: Address
    payment_method: Literal["stripe", "manual"]


class TrackingUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    status: Literal["processing", "shipped", "delivered"]
    carrier: str | None = Field(default=None, max_length=120)
    tracking_number: str | None = Field(default=None, max_length=150)
    note: str = Field(default="", max_length=1000)


class ManualPayment(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    method: Literal["cash", "transfer"]
    reference: str = Field(min_length=3, max_length=255)


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    first_name: str = Field(min_length=2, max_length=100)
    last_name: str = Field(min_length=2, max_length=100)
    phone: str | None = Field(default=None, max_length=30)


class AssistantMessage(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=1000)
    context: str | None = Field(default=None, max_length=120)


class ReportFilters(BaseModel):
    """Contexto de filtros del dashboard que comparte la vista. El servidor
    siempre recalcula las metricas con estos filtros; nunca confia en cifras
    enviadas por el navegador."""
    date_from: datetime | None = None
    date_to: datetime | None = None
    branch_id: UUID | None = None
    category_id: UUID | None = None
    status: Literal['pending_payment', 'paid', 'processing', 'shipped', 'delivered', 'cancelled', 'expired'] | None = None
    low_stock_lt: int | None = Field(default=None, ge=1, le=10000)

    @model_validator(mode='after')
    def ordered_dates(self):
        from zoneinfo import ZoneInfo
        if self.date_from and self.date_to:
            zone = ZoneInfo('America/La_Paz')
            start = self.date_from if self.date_from.tzinfo else self.date_from.replace(tzinfo=zone)
            end = self.date_to if self.date_to.tzinfo else self.date_to.replace(tzinfo=zone)
            if start > end:
                raise ValueError('La fecha inicial no puede ser posterior a la final.')
        return self


class InterpretRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=300)
    current: ReportFilters | None = None


class ExplainRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=500)
    filters: ReportFilters | None = None


class InsightsRequest(BaseModel):
    """Cuerpo opcional para /analytics/insights (retrocompatible): si llega
    vacio se usa el dashboard completo; si llega, filtra el contexto que vera
    la IA."""
    question: str | None = Field(default=None, max_length=500)
    filters: ReportFilters | None = None


REPORT_TYPES = {"ventas", "pedidos", "pagos", "prendas_vendidas", "existencias", "sucursales"}


class MultiExportRequest(BaseModel):
    """Solicitud de exportacion multiple: varios reportes en una sola operacion.
    Los tipos y filtros se validan en el servidor; el orden pedido se conserva
    (los duplicados se eliminan)."""
    model_config = ConfigDict(str_strip_whitespace=True)

    reports: list[str] = Field(min_length=1, max_length=6)
    format: Literal["xlsx", "pdf", "csv"]
    filters: ReportFilters | None = None


class ExportReportToolParams(BaseModel):
    """Parametros validados de la herramienta export_report del asistente."""
    model_config = ConfigDict(str_strip_whitespace=True)

    reports: list[str] = Field(min_length=1, max_length=6)
    format: Literal["xlsx", "pdf", "csv"]
    filters: ReportFilters | None = None


class AssistantToolRequest(BaseModel):
    """Pedido de ejecutar una herramienta tipada del asistente. Solo existen
    las herramientas del registro autorizado en el servidor; los parametros se
    validan aqui. request_id hace idempotente la operacion (una sola bitacora)."""
    model_config = ConfigDict(str_strip_whitespace=True)

    tool: Literal["export_report"]
    request_id: str | None = Field(
        default=None, max_length=64, pattern=r"^[A-Za-z0-9._-]+$"
    )
    params: ExportReportToolParams | None = None
