"""esquema clinical: patients, medical_images y audit_log con RLS forzado

Cada tabla: tenant_id con default del contexto, PK (tenant_id, id), RLS habilitado y
forzado, política tenant_isolation y políticas restrictivas por rol. Las referencias son
FKs compuestas. audit_log es de solo inserción para la app.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import INET, UUID

from backend.migrations.rls import (
    CLINICAL,
    CONTROL,
    CURRENT_ROLE,
    CURRENT_USER,
    add_role_policy,
    assert_empty,
    create_tenant_table,
    enable_tenant_rls,
    grant_app,
    revoke_supabase_api_roles,
    table_exists,
    tenant_fk,
)

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("audit_log", "medical_images", "patients")  # orden de borrado

# Un rol nulo nunca pasa: las políticas por rol exigen contexto completo
ROLE_PRESENT = f"{CURRENT_ROLE} IS NOT NULL"
OWN_PATIENT_ROW = f"user_id = {CURRENT_USER}"
OWN_PATIENT_IDS = (
    f"patient_id IN (SELECT p.id FROM clinical.patients p WHERE p.user_id = {CURRENT_USER})"
)


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


def upgrade() -> None:
    # --- patients: ficha clínica dentro del tenant (puede no tener cuenta, CU-07) ---
    if create_tenant_table(
        "patients",
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        _created_at(),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_patients_tenant_user"),
    ):
        tenant_fk(
            "fk_patients_user",
            "patients",
            ["tenant_id", "user_id"],
            "users",
            ["tenant_id", "id"],
            ref_schema=CONTROL,
        )
    enable_tenant_rls("patients")
    # Un paciente solo ve (y crea) su propia ficha
    patient_rule = f"{ROLE_PRESENT} AND ({CURRENT_ROLE} <> 'patient' OR {OWN_PATIENT_ROW})"
    add_role_policy("patients", "patients_by_role", patient_rule, with_check_sql=patient_rule)
    grant_app("patients", "SELECT, INSERT, UPDATE, DELETE")

    # --- medical_images ---
    if create_tenant_table(
        "medical_images",
        sa.Column("patient_id", UUID(as_uuid=True), nullable=False),
        sa.Column("uploaded_by", UUID(as_uuid=True), nullable=False),
        sa.Column("object_path", sa.Text(), nullable=False),
        sa.Column("image_type", sa.Text(), nullable=False),
        sa.Column("prediction", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "image_type IN ('BUSI', 'mammography')", name="ck_medical_images_image_type"
        ),
    ):
        tenant_fk(
            "fk_medical_images_patient",
            "medical_images",
            ["tenant_id", "patient_id"],
            "patients",
            ["tenant_id", "id"],
        )
        op.create_index(
            "ix_medical_images_patient",
            "medical_images",
            ["tenant_id", "patient_id", "created_at"],
            schema=CLINICAL,
        )
    enable_tenant_rls("medical_images")
    image_rule = f"{ROLE_PRESENT} AND ({CURRENT_ROLE} <> 'patient' OR {OWN_PATIENT_IDS})"
    add_role_policy("medical_images", "images_by_role", image_rule, with_check_sql=image_rule)
    grant_app("medical_images", "SELECT, INSERT, UPDATE, DELETE")

    # --- audit_log: solo inserción para la app; lectura solo para tenant_admin ---
    if create_tenant_table(
        "audit_log",
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("actor_id", UUID(as_uuid=True), nullable=False),
        sa.Column("actor_role", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=True),
        sa.Column("resource_id", UUID(as_uuid=True), nullable=True),
        sa.Column("ip", INET(), nullable=True),
    ):
        op.create_index(
            "ix_audit_log_occurred", "audit_log", ["tenant_id", "occurred_at"], schema=CLINICAL
        )
        op.create_index(
            "ix_audit_log_actor",
            "audit_log",
            ["tenant_id", "actor_id", "occurred_at"],
            schema=CLINICAL,
        )
    enable_tenant_rls("audit_log")
    add_role_policy(
        "audit_log",
        "audit_read_tenant_admin",
        f"{CURRENT_ROLE} = 'tenant_admin'",
        command="SELECT",
    )
    add_role_policy(
        "audit_log",
        "audit_insert_own_actor",
        None,
        command="INSERT",
        with_check_sql=f"{ROLE_PRESENT} AND actor_id = {CURRENT_USER}",
    )
    grant_app("audit_log", "SELECT, INSERT")

    revoke_supabase_api_roles()


def downgrade() -> None:
    for table in TABLES:
        if table_exists(table, CLINICAL):
            assert_empty(
                f"{CLINICAL}.{table}",
                f"{CLINICAL}.{table} tiene datos; el downgrade de 0004 no los borra.",
            )
    for table in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {CLINICAL}.{table}")
