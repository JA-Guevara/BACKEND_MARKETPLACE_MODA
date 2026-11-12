from datetime import date
from enum import StrEnum
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Metric(StrEnum):
    REVENUE = "REVENUE"
    UNITS = "UNITS"
    ORDERS = "ORDERS"
    AVG_TICKET = "AVG_TICKET"
    STOCK = "STOCK"
    RESERVATIONS = "RESERVATIONS"


class Dimension(StrEnum):
    BRANCH = "BRANCH"
    CATEGORY = "CATEGORY"
    PRODUCT = "PRODUCT"
    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"
    PAYMENT_METHOD = "PAYMENT_METHOD"
    STATUS = "STATUS"


class ChartKind(StrEnum):
    BAR = "BAR"
    GROUPED_BAR = "GROUPED_BAR"
    LINE = "LINE"
    PIE = "PIE"
    TABLE = "TABLE"


class Period(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date_from: date
    date_to: date
    label: str = ""

    @model_validator(mode="after")
    def validate_range(self) -> "Period":
        if self.date_to < self.date_from:
            raise ValueError("date_to no puede ser anterior a date_from.")
        # Máximo 24 meses (~730 días)
        if (self.date_to - self.date_from).days > 730:
            raise ValueError("El período no puede exceder 24 meses.")
        return self


class Filters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: Optional[Period] = None
    branch_names: list[str] = Field(default_factory=list)
    category_names: list[str] = Field(default_factory=list)
    product_names: list[str] = Field(default_factory=list)
    status: Optional[str] = None
    low_stock_lt: Optional[int] = Field(None, ge=1, le=10000)


class ReportSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition_code: str
    metrics: list[Metric] = Field(min_length=1, max_length=3)
    dimensions: list[Dimension] = Field(default_factory=list, max_length=2)
    filters: Filters = Field(default_factory=Filters)
    top_n: Optional[int] = Field(None, ge=1, le=50)
    order: Literal["asc", "desc"] = "desc"
    compare_previous: bool = False
    chart: Optional[ChartKind] = None


class InterpretResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["READY", "NEEDS_CLARIFICATION", "UNSUPPORTED"]
    request_id: Optional[str] = None
    spec: Optional[ReportSpec] = None
    questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    interpreter: Literal["LLM", "FALLBACK", "CACHE"] = "FALLBACK"
