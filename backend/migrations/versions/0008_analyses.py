"""clinical.analyses: resultado del análisis de una imagen, con RLS forzado (CU-02)

Revision ID: 0008
Revises: 0007
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

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if create_tenant_table(
        "analyses",
        sa.Column("patient_id", UUID(as_uuid=True), nullable=False),
        sa.Column("image_id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("predicted_class", sa.Text(), nullable=False),
        sa.Column("probabilities", JSONB(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column("heatmap_path", sa.Text(), nullable=False),
        sa.Column("quality_flags", JSONB(), nullable=False),
        sa.Column("report", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("status IN ('completed', 'inconclusive')", name="ck_analyses_status"),
        sa.UniqueConstraint("tenant_id", "image_id", name="uq_analyses_image"),
    ):
        tenant_fk(
            "fk_analyses_patient",
            "analyses",
            ["tenant_id", "patient_id"],
            "patients",
            ["tenant_id", "id"],
        )
        tenant_fk(
            "fk_analyses_image",
            "analyses",
            ["tenant_id", "image_id"],
            "medical_images",
            ["tenant_id", "id"],
        )
        op.create_index(
            "ix_analyses_patient",
            "analyses",
            ["tenant_id", "patient_id", "created_at"],
            schema=CLINICAL,
        )
    enable_tenant_rls("analyses")
    add_patient_owner_policy("analyses", "analyses_by_role")
    # Sin UPDATE: un resultado no se edita; se elimina (derecho de eliminación) o se repite
    grant_app("analyses", "SELECT, INSERT, DELETE")
    revoke_supabase_api_roles()


def downgrade() -> None:
    if table_exists("analyses", CLINICAL):
        assert_empty(
            "clinical.analyses", "clinical.analyses tiene datos; el downgrade de 0008 no los borra."
        )
    op.execute("DROP TABLE IF EXISTS clinical.analyses")
