"""esquema control: tenants y users, más el tenant B2C compartido

Sin RLS (ADR 0003): identidad y administración, nunca datos clínicos. app_user no tiene
DELETE ni DDL, y su UPDATE se limita a columnas concretas.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from backend.migrations.rls import (
    CONTROL,
    assert_empty,
    grant_app,
    revoke_supabase_api_roles,
    table_exists,
)

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLES = ("patient", "doctor", "tenant_admin", "platform_admin")


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


def upgrade() -> None:
    if not table_exists("tenants", CONTROL):
        op.create_table(
            "tenants",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("slug", sa.Text(), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("kind", sa.Text(), nullable=False),
            sa.Column("plan", sa.Text(), nullable=False, server_default="basic"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            _created_at(),
            sa.UniqueConstraint("slug", name="uq_tenants_slug"),
            sa.CheckConstraint("kind IN ('b2c', 'institucion')", name="ck_tenants_kind"),
            sa.CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]{1,40}$'", name="ck_tenants_slug"),
            schema=CONTROL,
        )

    if not table_exists("users", CONTROL):
        roles = ", ".join(f"'{r}'" for r in ROLES)
        op.create_table(
            "users",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("control.tenants.id", name="fk_users_tenant"),
                nullable=True,
            ),
            sa.Column("email", sa.Text(), nullable=False),
            sa.Column("hashed_password", sa.Text(), nullable=False),
            sa.Column("full_name", sa.Text(), nullable=False),
            sa.Column("role", sa.Text(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            _created_at(),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(f"role IN ({roles})", name="ck_users_role"),
            # El platform_admin no pertenece a ningún tenant; los demás roles siempre a uno
            sa.CheckConstraint(
                "(role = 'platform_admin') = (tenant_id IS NULL)",
                name="ck_users_platform_admin_sin_tenant",
            ),
            # Destino de la FK compuesta desde clinical.patients
            sa.UniqueConstraint("tenant_id", "id", name="uq_users_tenant_id_id"),
            schema=CONTROL,
        )
        op.create_index("ix_users_tenant_id", "users", ["tenant_id"], schema=CONTROL)
        # Identidad global: el login es solo con email
        op.execute("CREATE UNIQUE INDEX ux_users_email ON control.users (lower(email))")

    grant_app("tenants", "SELECT, INSERT, UPDATE (is_active, name, plan)", schema=CONTROL)
    grant_app(
        "users",
        "SELECT, INSERT, UPDATE (is_active, full_name, hashed_password, updated_at)",
        schema=CONTROL,
    )

    op.execute(
        "INSERT INTO control.tenants (slug, name, kind, plan) "
        "VALUES ('b2c', 'Pacientes B2C', 'b2c', 'b2c') ON CONFLICT (slug) DO NOTHING"
    )
    revoke_supabase_api_roles()


def downgrade() -> None:
    if table_exists("users", CONTROL):
        assert_empty(
            "control.users", "control.users tiene datos; el downgrade de 0003 no los borra."
        )
    if table_exists("tenants", CONTROL):
        assert_empty(
            "control.tenants WHERE slug <> 'b2c'",
            "Hay tenants además de b2c; el downgrade de 0003 no los borra.",
        )
    op.execute("DROP TABLE IF EXISTS control.users")
    op.execute("DROP TABLE IF EXISTS control.tenants")
