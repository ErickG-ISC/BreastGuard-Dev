import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{1,40}$"
# Prefijos de Storage o nombres que no pueden ser de un tenant institucional
RESERVED_SLUGS = {"b2c", "uploads", "admin", "api", "legacy", "public", "control", "clinical"}
STAFF_PASSWORD_MIN = 12
# Planes de institución (simulados: no hay facturación)
TenantPlan = Literal["basic", "pro", "enterprise"]
StaffRole = Literal["tenant_admin", "doctor"]


def _bcrypt_limit(value: str) -> str:
    if len(value.encode("utf-8")) > 72:
        raise ValueError("La contraseña no puede superar 72 bytes")
    return value


class TenantCreate(BaseModel):
    """Alta de una institución (CU-12). El primer tenant_admin se INVITA: sin contraseña."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=SLUG_PATTERN)
    plan: TenantPlan = "basic"
    admin_email: EmailStr
    admin_full_name: str = Field(min_length=1, max_length=200)

    @field_validator("slug")
    @classmethod
    def slug_not_reserved(cls, value: str) -> str:
        if value in RESERVED_SLUGS:
            raise ValueError("Ese slug está reservado")
        return value


class TenantUpdate(BaseModel):
    """Nombre, plan y estado. El tipo (b2c/institución) es fijo y no se acepta aquí."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    plan: TenantPlan | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def something_to_change(self):
        if not self.model_fields_set:
            raise ValueError("Nada que cambiar")
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} no puede ser nulo")
        return self


class PurgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_slug: str = Field(min_length=1, max_length=64)


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    kind: str
    plan: str
    is_active: bool
    created_at: datetime
    purge_requested_at: datetime | None


class TenantStats(BaseModel):
    """Solo datos de control: nunca análisis, diario ni nada clínico."""

    staff: int
    staff_active: int
    invitations_pending: int
    patients: int
    last_login_at: datetime | None


class TenantSummary(TenantOut):
    stats: TenantStats


class TenantPage(BaseModel):
    items: list[TenantSummary]
    total: int
    limit: int
    offset: int


class TenantCreated(BaseModel):
    tenant: TenantOut
    admin_user_id: uuid.UUID
    email_sent: bool


class StaffInvite(BaseModel):
    """Alta de personal por invitación: solo doctor o tenant_admin, nunca platform_admin."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    role: StaffRole


class PlatformAdminCreate(BaseModel):
    """Solo para backend/scripts/create_platform_admin.py (nunca por la API)."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=STAFF_PASSWORD_MIN)

    _check_password = field_validator("password")(_bcrypt_limit)


class StaffUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: bool | None = None
    role: StaffRole | None = None

    @model_validator(mode="after")
    def something_to_change(self):
        if not self.model_fields_set:
            raise ValueError("Nada que cambiar")
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} no puede ser nulo")
        return self


class StaffOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    email: EmailStr
    full_name: str
    role: str
    is_active: bool
    # invited: aún no fija contraseña; active/inactive según is_active
    status: Literal["invited", "active", "inactive"]
    last_login_at: datetime | None
    created_at: datetime


class StaffList(BaseModel):
    items: list[StaffOut]
    patients: int


class StaffInvited(BaseModel):
    user: StaffOut
    email_sent: bool


class InvitationSent(BaseModel):
    email_sent: bool


class AdminEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    occurred_at: datetime
    actor_id: uuid.UUID | None
    actor_role: str
    action: str
    tenant_id: uuid.UUID | None
    target_type: str
    target_id: uuid.UUID | None
    ip: str | None
    details: dict

    @field_validator("ip", mode="before")
    @classmethod
    def ip_as_text(cls, value):
        return None if value is None else str(value)


class AdminEventPage(BaseModel):
    items: list[AdminEventOut]
    total: int
    limit: int
    offset: int


class InvitationTokenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=200)


class InvitationAcceptIn(InvitationTokenIn):
    password: str = Field(min_length=STAFF_PASSWORD_MIN)

    _check_password = field_validator("password")(_bcrypt_limit)


class InvitationInfoOut(BaseModel):
    email_masked: str
    full_name: str
    institution: str
    purpose: str


class IsolationReport(BaseModel):
    """Solo conteos y booleanos: nunca datos de ningún tenant."""

    tenant_slug: str
    app_role_without_bypass: bool
    rows_visible_without_context: int
    foreign_rows_visible_to_tenant: int
    tenant_rows_visible_to_others: int
    tenant_has_witness_rows: bool
    other_tenants_checked: int
    tables_checked: list[str]
    # Solo es concluyente si hay filas testigo, tablas y otros tenants contra quienes comparar
    conclusive: bool
    passed: bool
