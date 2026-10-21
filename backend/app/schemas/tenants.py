import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{1,40}$"


def _bcrypt_limit(value: str) -> str:
    if len(value.encode("utf-8")) > 72:
        raise ValueError("La contraseña no puede superar 72 bytes")
    return value


class TenantCreate(BaseModel):
    """Alta de una institución (CU-12). El tenant B2C ya existe y no se crea por aquí."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=SLUG_PATTERN)
    plan: str = Field(default="basic", min_length=1, max_length=50)
    admin_email: EmailStr
    admin_full_name: str = Field(min_length=1, max_length=200)
    admin_password: str = Field(min_length=8)

    _check_password = field_validator("admin_password")(_bcrypt_limit)


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    kind: str
    plan: str
    is_active: bool
    created_at: datetime


class TenantCreated(BaseModel):
    tenant: TenantOut
    admin_user_id: uuid.UUID


class ActiveUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: bool


class TenantUserCreate(BaseModel):
    """Usuarios de una institución creados por el platform_admin (nunca platform_admin)."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8)
    role: Literal["tenant_admin", "doctor"]

    _check_password = field_validator("password")(_bcrypt_limit)


class AdminUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID | None
    email: EmailStr
    full_name: str
    role: str
    is_active: bool


class IsolationReport(BaseModel):
    """Solo conteos y booleanos: nunca datos de ningún tenant."""

    tenant_slug: str
    app_role_without_bypass: bool
    rows_visible_without_context: int
    foreign_rows_visible_to_tenant: int
    tenant_rows_visible_to_others: int
    tenant_witness_rows: int
    other_tenants_checked: int
    tables_checked: list[str]
    passed: bool
