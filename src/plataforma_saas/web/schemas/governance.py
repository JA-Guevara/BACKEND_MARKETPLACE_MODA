from datetime import date, datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ModuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    code: str
    name: str
    description: str | None = None
    category: str | None = None
    icon: str | None = None
    kind: str
    lifecycle: str
    depends_on: list[str] = Field(default_factory=list)
    web_routes: list[str] = Field(default_factory=list)
    sort_order: int = 0
    plans_count: int = 0
    tenants_count: int = 0
    permissions_count: int = 0
    last_preview_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ModulePermissionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")
    id: UUID
    code: str
    name: str
    description: str | None = None


class ModuleDetail(ModuleOut):
    permissions: list[ModulePermissionSummary] = Field(default_factory=list)
    plans: list[dict] = Field(default_factory=list)
    active_tenants: list[dict] = Field(default_factory=list)
    history: list[dict] = Field(default_factory=list)


class ModuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = None
    category: str | None = None
    icon: str | None = Field(default=None, max_length=8)
    lifecycle: Literal["BORRADOR", "BETA", "GA", "RETIRADO"] | None = None
    depends_on: list[str] | None = None
    web_routes: list[str] | None = None
    sort_order: int | None = None


class ModulePermissionsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    permission_codes: list[str]


class ModuleMatrixPlan(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")
    id: UUID
    code: str
    name: str
    modules: dict[str, bool] = Field(default_factory=dict)
    limits: dict[str, int] = Field(default_factory=dict)


class ModuleMatrix(BaseModel):
    model_config = ConfigDict(extra="forbid")
    modules: list[ModuleOut]
    plans: list[ModuleMatrixPlan]


class PlanImpact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: UUID
    affected_tenants: int
    affected_users: int
    modules_added: list[str] = Field(default_factory=list)
    modules_removed: list[str] = Field(default_factory=list)
    permissions_gained: list[str] = Field(default_factory=list)
    permissions_lost: list[str] = Field(default_factory=list)


class TenantModuleOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID | None = None
    module_code: str
    module_name: str
    kind: str
    lifecycle: str
    effective: bool
    origin: str  # BASE, PLAN, EXTRA, TRIAL, SANDBOX, NONE
    mode: str | None = None  # EXTRA, TRIAL, BLOQUEADO
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    reason: str | None = None
    granted_by_name: str | None = None
    is_blocked: bool = False


class TenantModuleGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    module_code: str
    mode: str  # EXTRA, TRIAL, BLOQUEADO
    days: int | None = None
    reason: str


class RevokeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str


class TenantLimitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")
    id: UUID
    tenant_id: UUID
    limit_code: str
    value: int
    expires_at: datetime | None = None
    reason: str
    created_at: datetime


class TenantLimitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit_code: str
    value: int
    days: int | None = None
    reason: str


class EffectiveTenantLimitOut(BaseModel):
    """Un cupo efectivo; el override puede estar vencido y ya no ser efectivo."""
    model_config = ConfigDict(extra="forbid")
    limit_code: str
    plan_value: int | None
    effective_value: int | None
    usage: int
    source: Literal["PLAN", "EMPRESA"]
    subscription_end_date: date | None
    override_active: bool
    override: TenantLimitOut | None = None


class GlobalUserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str  # "tenant" | "platform"
    tenant_id: UUID | None = None
    first_name: str
    last_name: str
    email: EmailStr
    phone: str | None = None
    role_ids: list[UUID]
    branch_ids: list[UUID] | None = None
    access: str = "invite"  # "invite" | "temporary_password"


class GlobalUserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    first_name: str | None = None
    last_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    is_active: bool | None = None


class RoleIdsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role_ids: list[UUID]


class BranchIdsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    branch_ids: list[UUID]
    default_id: UUID | None = None


class EffectivePermissionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    name: str
    module: str | None = None
    granted_by_role: str | None = None
    status: str  # PERMITIDO, TRIAL, BLOQUEADO_MODULO, SIN_ROL


class EffectivePermissions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: UUID
    permissions: list[EffectivePermissionItem] = Field(default_factory=list)


class RoleTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")
    id: UUID
    code: str
    name: str
    description: str | None = None
    is_system: bool
    audience: str
    tenants_count: int = 0
    users_count: int = 0
    permissions: list[str] = Field(default_factory=list)


class TemplateImpact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role_id: UUID
    affected_tenants: int
    affected_users: int
    permissions_added: list[str] = Field(default_factory=list)
    permissions_removed: list[str] = Field(default_factory=list)


class TemplatePermissionsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    permission_codes: list[str]
    reason: str
    confirm: bool = False


class PlatformRoleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    name: str
    description: str | None = None
    permission_codes: list[str] = Field(default_factory=list)


class PermissionCatalogItem(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")
    id: UUID
    code: str
    name: str
    description: str | None = None
    module: str
    scope: str
    is_active: bool


class PermissionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


class SandboxResetIn(BaseModel):
    confirm: bool


class SandboxOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID | None
    slug: str
    trade_name: str
    is_active: bool
    modules: list[dict] = Field(default_factory=list)
    branches_count: int = 0
    products_count: int = 0


class PreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    module_code: str
