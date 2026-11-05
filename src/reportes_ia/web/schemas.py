import uuid
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from src.reportes_ia.domain.especificacion import ReportSpec


class InterpretIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=3, max_length=500)
    channel: Literal["TEXT", "VOICE"] = "TEXT"


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: ReportSpec
    request_id: Optional[uuid.UUID] = None


class ExportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: ReportSpec
    format: Literal["xlsx", "pdf", "csv"] = "xlsx"
    request_id: Optional[uuid.UUID] = None


class ColumnMeta(BaseModel):
    key: str
    label: str
    type: str = "text"


class ReportResponse(BaseModel):
    request_id: Optional[str] = None
    definition_code: str
    title: str
    columns: list[ColumnMeta]
    rows: list[dict[str, Any]]
    totals: dict[str, Any]
    chart: dict[str, Any]
    series: list[dict[str, Any]]
    narrative: str
    truncated: bool = False
    duration_ms: Optional[int] = None
    usage: dict[str, Any]


class DefinitionOut(BaseModel):
    code: str
    title: str
    description: str
    metrics: list[str]
    dimensions: list[str]
    default_chart: str
    examples: list[str]


class HistoryItemOut(BaseModel):
    id: str
    created_at: str
    prompt_length: int
    title: str
    definition_code: Optional[str] = None
    user_name: str
    channel: str
    status: str
    rows: Optional[int] = None
    export_format: Optional[str] = None
    spec: dict[str, Any] = Field(default_factory=dict)


class HistoryResponse(BaseModel):
    items: list[HistoryItemOut]
    total: int
    page: int
    page_size: int
