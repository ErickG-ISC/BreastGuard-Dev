"""clinical.questionnaires: cuestionario de antecedentes con RLS forzado (CU-01)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

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

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if create_tenant_table(
        "questionnaires",
        sa.Column("patient_id", UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("answers", JSONB(), nullable=False),
        sa.Column("risk_factors", JSONB(), nullable=False),
        sa.Column("summary_level", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ):
        tenant_fk(
            "fk_questionnaires_patient",
            "questionnaires",
            ["tenant_id", "patient_id"],
            "patients",
            ["tenant_id", "id"],
        )
        op.create_index(
            "ix_questionnaires_patient",
            "questionnaires",
            ["tenant_id", "patient_id", "created_at"],
            schema=CLINICAL,
        )
    enable_tenant_rls("questionnaires")
    add_patient_owner_policy("questionnaires", "questionnaires_by_role")
    # Historial inmutable: una respuesta nueva es una fila nueva
    grant_app("questionnaires", "SELECT, INSERT")
    revoke_supabase_api_roles()


def downgrade() -> None:
    if table_exists("questionnaires", CLINICAL):
        assert_empty(
            "clinical.questionnaires",
            "clinical.questionnaires tiene datos; el downgrade de 0007 no los borra.",
        )
    op.execute("DROP TABLE IF EXISTS clinical.questionnaires")
