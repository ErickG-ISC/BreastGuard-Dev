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
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
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


class Questionnaire(Base):
    """Cuestionario de antecedentes (CU-01). Cada envío es una fila nueva (historial)."""

    __tablename__ = "questionnaires"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["clinical.patients.tenant_id", "clinical.patients.id"],
            name="fk_questionnaires_patient",
        ),
        Index("ix_questionnaires_patient", "tenant_id", "patient_id", "created_at"),
        {"schema": "clinical"},
    )

    tenant_id: Mapped[uuid.UUID] = _tenant_id()
    id: Mapped[uuid.UUID] = _id()
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    version: Mapped[str] = mapped_column(Text)
    answers: Mapped[dict] = mapped_column(JSONB)
    risk_factors: Mapped[list] = mapped_column(JSONB)
    summary_level: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Analysis(Base):
    """Resultado del análisis de una imagen (CU-02). No se edita: se elimina o se repite."""

    __tablename__ = "analyses"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["clinical.patients.tenant_id", "clinical.patients.id"],
            name="fk_analyses_patient",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "image_id"],
            ["clinical.medical_images.tenant_id", "clinical.medical_images.id"],
            name="fk_analyses_image",
        ),
        CheckConstraint("status IN ('completed', 'inconclusive')", name="ck_analyses_status"),
        UniqueConstraint("tenant_id", "image_id", name="uq_analyses_image"),
        Index("ix_analyses_patient", "tenant_id", "patient_id", "created_at"),
        {"schema": "clinical"},
    )

    tenant_id: Mapped[uuid.UUID] = _tenant_id()
    id: Mapped[uuid.UUID] = _id()
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    image_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(Text)
    predicted_class: Mapped[str] = mapped_column(Text)
    probabilities: Mapped[dict] = mapped_column(JSONB)
    confidence: Mapped[float] = mapped_column(Float)
    model_version: Mapped[str] = mapped_column(Text)
    heatmap_path: Mapped[str] = mapped_column(Text)  # ruta en Storage, nunca una URL
    quality_flags: Mapped[list] = mapped_column(JSONB)
    report: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SelfExam(Base):
    """Autoexploración guiada (CU-03). Se crea al iniciar y se completa al terminar."""

    __tablename__ = "self_exams"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["clinical.patients.tenant_id", "clinical.patients.id"],
            name="fk_self_exams_patient",
        ),
        CheckConstraint(
            "noticed_change IN ('si', 'no', 'no_segura')", name="ck_self_exams_noticed_change"
        ),
        CheckConstraint("char_length(note) <= 1000", name="ck_self_exams_note_length"),
        CheckConstraint(
            "(finished_at IS NULL) = (noticed_change IS NULL) "
            "AND (finished_at IS NOT NULL OR note IS NULL)",
            name="ck_self_exams_finished",
        ),
        UniqueConstraint("tenant_id", "patient_id", "id", name="uq_self_exams_patient_id"),
        Index("ix_self_exams_patient", "tenant_id", "patient_id", "started_at"),
        {"schema": "clinical"},
    )

    tenant_id: Mapped[uuid.UUID] = _tenant_id()
    id: Mapped[uuid.UUID] = _id()
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    content_version: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    noticed_change: Mapped[str | None] = mapped_column(Text)
    # Texto libre sensible: nunca en logs ni en la auditoría
    note: Mapped[str | None] = mapped_column(Text)
