"""clinical.self_exams: autoexploraciones guiadas con RLS forzado (CU-03)

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from backend.migrations.rls import (
    CLINICAL,
    add_patient_owner_policy,
    assert_empty,
    create_tenant_table,
    enable_tenant_rls,
    grant_app,
    revoke_supabase_api_roles,
    table_exists,
    tenant_fk,
)

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if create_tenant_table(
        "self_exams",
        sa.Column("patient_id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("content_version", sa.Text(), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("noticed_change", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "noticed_change IN ('si', 'no', 'no_segura')", name="ck_self_exams_noticed_change"
        ),
        sa.CheckConstraint("char_length(note) <= 1000", name="ck_self_exams_note_length"),
        # Terminada <=> tiene respuesta; en curso no tiene respuesta ni nota
        sa.CheckConstraint(
            "(finished_at IS NULL) = (noticed_change IS NULL) "
            "AND (finished_at IS NOT NULL OR note IS NULL)",
            name="ck_self_exams_finished",
        ),
        # Destino de la FK del diario: garantiza que una entrada solo enlace autoexploraciones
        # de la MISMA paciente (las FKs no pasan por RLS)
        sa.UniqueConstraint("tenant_id", "patient_id", "id", name="uq_self_exams_patient_id"),
    ):
        tenant_fk(
            "fk_self_exams_patient",
            "self_exams",
            ["tenant_id", "patient_id"],
            "patients",
            ["tenant_id", "id"],
        )
        op.create_index(
            "ix_self_exams_patient",
            "self_exams",
            ["tenant_id", "patient_id", "started_at"],
            schema=CLINICAL,
        )
    enable_tenant_rls("self_exams")
    add_patient_owner_policy("self_exams", "self_exams_by_role")
    # Solo se edita al terminarla; la paciente puede borrar su registro
    grant_app("self_exams", "SELECT, INSERT, UPDATE (finished_at, noticed_change, note), DELETE")
    revoke_supabase_api_roles()


def downgrade() -> None:
    if table_exists("self_exams", CLINICAL):
        assert_empty(
            "clinical.self_exams",
            "clinical.self_exams tiene datos; el downgrade de 0009 no los borra.",
        )
    op.execute("DROP TABLE IF EXISTS clinical.self_exams")
