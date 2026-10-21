"""Esquema `clinical`: datos clínicos con RLS forzado por tenant_id (ADR 0002).

`tenant_id` lo rellena la base con el contexto de la transacción; el código no lo asigna.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base


def _tenant_id() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("clinical.current_tenant_id()"),
    )


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_patients_tenant_user"),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["control.users.tenant_id", "control.users.id"],
            name="fk_patients_user",
        ),
        {"schema": "clinical"},
    )

    tenant_id: Mapped[uuid.UUID] = _tenant_id()
    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    display_name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MedicalImage(Base):
    __tablename__ = "medical_images"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["clinical.patients.tenant_id", "clinical.patients.id"],
            name="fk_medical_images_patient",
        ),
        CheckConstraint(
            "image_type IN ('BUSI', 'mammography')", name="ck_medical_images_image_type"
        ),
        Index("ix_medical_images_patient", "tenant_id", "patient_id", "created_at"),
        {"schema": "clinical"},
    )

    tenant_id: Mapped[uuid.UUID] = _tenant_id()
    id: Mapped[uuid.UUID] = _id()
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    # Ruta del objeto en Storage ({tenant_slug}/images/...), nunca una URL
    object_path: Mapped[str] = mapped_column(Text)
    image_type: Mapped[str] = mapped_column(Text)
    prediction: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    """Bitácora de solo inserción para la app (sin datos clínicos ni tokens).

    Se inserta con `insert()` de Core, sin RETURNING: RETURNING exige pasar la política
    SELECT, que solo admite tenant_admin. No uses `session.add(AuditLog(...))`.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_occurred", "tenant_id", "occurred_at"),
        Index("ix_audit_log_actor", "tenant_id", "actor_id", "occurred_at"),
        {"schema": "clinical"},
    )

    tenant_id: Mapped[uuid.UUID] = _tenant_id()
    id: Mapped[uuid.UUID] = _id()
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    actor_role: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    resource_type: Mapped[str | None] = mapped_column(Text)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    ip: Mapped[str | None] = mapped_column(INET)
