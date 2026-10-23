from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator
from src.plataforma_saas.domain.estados import FUNCIONES, LIMITES


class PlanFeatureInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feature_code: str
    enabled: bool = True
    limit_value: int | None = None

    @field_validator("feature_code")
    @classmethod
    def known_code(cls, code):
        if code not in (*FUNCIONES, *LIMITES):
            raise ValueError("Funcionalidad desconocida.")
        return code


class PlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,29}$")
    name: str = Field(min_length=2, max_length=80)
    reference_price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    duration_days: int = Field(ge=1, le=366)
    features: list[PlanFeatureInput]


class PlanUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=2, max_length=80)
    reference_price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    duration_days: int | None = Field(default=None, ge=1, le=366)
    features: list[PlanFeatureInput] | None = None


class PlanResponse(BaseModel):
    id: UUID
    code: str
    name: str
    reference_price: Decimal
    duration_days: int
    is_active: bool
    features: dict[str, bool]
    limits: dict[str, int]
    tenants_count: int


class PlanSaveResult(BaseModel):
    plan: PlanResponse
    exceeded_tenants: list[str]


class FeatureCatalogItem(BaseModel):
    code: str
    label: str
    kind: Literal["feature", "limit"]
