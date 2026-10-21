"""Esquema `control`: tenants e identidad (sin RLS, sin datos clínicos; ADR 0003)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET, UUID
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


class Consent(Base):
    """Consentimiento informado aceptado por un usuario (versión del texto y su hash)."""

    __tablename__ = "consents"
    __table_args__ = (
        UniqueConstraint("user_id", "version", name="uq_consents_user_version"),
        {"schema": "control"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("control.users.id", name="fk_consents_user")
    )
    version: Mapped[str] = mapped_column(Text)
    text_sha256: Mapped[str] = mapped_column(Text)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ip: Mapped[str | None] = mapped_column(INET)


class Plan(Base):
    """Plan de suscripción SIMULADO: no hay pasarela de pago ni datos de tarjeta."""

    __tablename__ = "plans"
    __table_args__ = {"schema": "control"}

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    price_label: Mapped[str] = mapped_column(Text)
    features: Mapped[list[str]] = mapped_column(ARRAY(Text))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    sort: Mapped[int] = mapped_column(Integer, server_default="0")


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_subscriptions_user"),
        CheckConstraint("status = 'simulada'", name="ck_subscriptions_status"),
        {"schema": "control"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("control.users.id", name="fk_subscriptions_user")
    )
    plan_code: Mapped[str] = mapped_column(
        Text, ForeignKey("control.plans.code", name="fk_subscriptions_plan")
    )
    status: Mapped[str] = mapped_column(Text, server_default="simulada")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
