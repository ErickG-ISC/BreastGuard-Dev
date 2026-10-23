"""Esquema `control`: tenants e identidad (sin RLS, sin datos clínicos; ADR 0003)."""

import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    Text,
    Time,
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


class Reminder(Base):
    """Recordatorio de una paciente (CU-05). Configuración, no datos clínicos (ADR 0007)."""

    __tablename__ = "reminders"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["control.users.tenant_id", "control.users.id"],
            name="fk_reminders_user",
            ondelete="CASCADE",
        ),
        UniqueConstraint("user_id", "kind", name="uq_reminders_user_kind"),
        CheckConstraint("kind IN ('self_exam', 'repeat_analysis')", name="ck_reminders_kind"),
        CheckConstraint(
            "(frequency = 'first_sunday' AND interval_n IS NULL) "
            "OR (frequency = 'every_n_days' AND interval_n BETWEEN 1 AND 90) "
            "OR (frequency = 'every_n_months' AND interval_n BETWEEN 1 AND 24)",
            name="ck_reminders_frequency",
        ),
        CheckConstraint(
            "extract(minute FROM local_time)::int % 15 = 0 AND extract(second FROM local_time) = 0",
            name="ck_reminders_local_time",
        ),
        CheckConstraint(
            "cardinality(channels) >= 1 AND channels <@ ARRAY['in_app', 'email']::text[]",
            name="ck_reminders_channels",
        ),
        Index("ix_reminders_due", "next_run_at", postgresql_where=text("active")),
        {"schema": "control"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(Text)
    frequency: Mapped[str] = mapped_column(Text)
    interval_n: Mapped[int | None] = mapped_column(SmallInteger)
    local_time: Mapped[time] = mapped_column(Time)
    timezone: Mapped[str] = mapped_column(Text)
    anchor_date: Mapped[date] = mapped_column(Date)
    channels: Mapped[list[str]] = mapped_column(ARRAY(Text))
    discreet: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReminderNotice(Base):
    """Aviso del despachador: se muestra en la app y, si la paciente lo pidió, va por correo."""

    __tablename__ = "reminder_notices"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["control.users.tenant_id", "control.users.id"],
            name="fk_reminder_notices_user",
            ondelete="CASCADE",
        ),
        UniqueConstraint("reminder_id", "due_at", name="uq_reminder_notices_due"),
        CheckConstraint(
            "email_status IN ('none', 'pending', 'sent', 'failed')",
            name="ck_reminder_notices_email_status",
        ),
        CheckConstraint(
            "kind IN ('self_exam', 'repeat_analysis')", name="ck_reminder_notices_kind"
        ),
        Index("ix_reminder_notices_user", "user_id", "created_at"),
        {"schema": "control"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    reminder_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("control.reminders.id", name="fk_reminder_notices_reminder", ondelete="CASCADE"),
    )
    kind: Mapped[str] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    email_status: Mapped[str] = mapped_column(Text, server_default="none")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
