"""clinical.symptom_entries: diario de síntomas con mapa corporal y RLS forzado (CU-04)

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, UUID

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

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Códigos fijos (los textos para la paciente viven en el frontend)
SIDES = ("izquierdo", "derecho", "ambos")
ZONES = (
    "superior_externo",
    "superior_interno",
    "inferior_externo",
    "inferior_interno",
    "areola_pezon",
    "axila",
    "otra",
)
SYMPTOMS = (
    "bulto",
    "dolor",
    "sensibilidad",
    "secrecion",
    "cambio_piel",
    "cambio_pezon",
    "enrojecimiento",
    "otro",
)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    if create_tenant_table(
        "symptom_entries",
        sa.Column("patient_id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("zone", sa.Text(), nullable=False),
        sa.Column("symptoms", ARRAY(sa.Text()), nullable=False),
        sa.Column("intensity", sa.SmallInteger(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("self_exam_id", UUID(as_uuid=True), nullable=True),
        sa.Column("cycle_day", sa.SmallInteger(), nullable=True),
        sa.Column("in_period", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"side IN ({_in(SIDES)})", name="ck_symptom_entries_side"),
        sa.CheckConstraint(f"zone IN ({_in(ZONES)})", name="ck_symptom_entries_zone"),
        sa.CheckConstraint(
            f"cardinality(symptoms) >= 1 AND symptoms <@ ARRAY[{_in(SYMPTOMS)}]::text[]",
            name="ck_symptom_entries_symptoms",
        ),
        sa.CheckConstraint("intensity BETWEEN 0 AND 10", name="ck_symptom_entries_intensity"),
        sa.CheckConstraint("char_length(note) <= 2000", name="ck_symptom_entries_note_length"),
        sa.CheckConstraint("cycle_day BETWEEN 1 AND 60", name="ck_symptom_entries_cycle_day"),
    ):
        tenant_fk(
            "fk_symptom_entries_patient",
            "symptom_entries",
            ["tenant_id", "patient_id"],
            "patients",
            ["tenant_id", "id"],
        )
        # Incluye patient_id: una entrada solo puede enlazar autoexploraciones de la MISMA
        # paciente (las FKs no pasan por RLS). Al borrar la autoexploración solo se anula el enlace.
        tenant_fk(
            "fk_symptom_entries_self_exam",
            "symptom_entries",
            ["tenant_id", "patient_id", "self_exam_id"],
            "self_exams",
            ["tenant_id", "patient_id", "id"],
            ondelete="SET NULL (self_exam_id)",
        )
        op.create_index(
            "ix_symptom_entries_patient",
            "symptom_entries",
            ["tenant_id", "patient_id", "entry_date"],
            schema=CLINICAL,
        )
    enable_tenant_rls("symptom_entries")
    add_patient_owner_policy("symptom_entries", "symptom_entries_by_role")
    grant_app(
        "symptom_entries",
        "SELECT, INSERT, DELETE, UPDATE (entry_date, side, zone, symptoms, intensity, note, "
        "self_exam_id, cycle_day, in_period, updated_at)",
    )
    revoke_supabase_api_roles()


def downgrade() -> None:
    if table_exists("symptom_entries", CLINICAL):
        assert_empty(
            "clinical.symptom_entries",
            "clinical.symptom_entries tiene datos; el downgrade de 0010 no los borra.",
        )
    op.execute("DROP TABLE IF EXISTS clinical.symptom_entries")
