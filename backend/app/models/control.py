"""Esquema `control`: tenants e identidad (sin RLS, sin datos clínicos; ADR 0003)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base

ROLES = ("patient", "doctor", "tenant_admin", "platform_admin")


class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_tenants_slug"),
        CheckConstraint("kind IN ('b2c', 'institucion')", name="ck_tenants_kind"),
        CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]{1,40}$'", name="ck_tenants_slug"),
        {"schema": "control"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    slug: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    plan: Mapped[str] = mapped_column(Text, server_default="basic")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('patient', 'doctor', 'tenant_admin', 'platform_admin')", name="ck_users_role"
        ),
        CheckConstraint(
            "(role = 'platform_admin') = (tenant_id IS NULL)",
            name="ck_users_platform_admin_sin_tenant",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_users_tenant_id_id"),
        Index("ix_users_tenant_id", "tenant_id"),
        # Identidad global: email único sin distinguir mayúsculas
        Index("ux_users_email", text("lower(email)"), unique=True),
        {"schema": "control"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("control.tenants.id", name="fk_users_tenant")
    )
    email: Mapped[str] = mapped_column(Text)
    hashed_password: Mapped[str] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
