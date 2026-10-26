"""control: invitaciones, bitácora de plataforma, último acceso y purga solicitada

Administración de tenants y usuarios (ADR 0008). Todo en control: identidad y operación, nunca
datos clínicos.

- users.hashed_password admite NULL: cuenta invitada que aún no fija contraseña.
- users.last_login_at y users.sessions_valid_after (cierra sesiones al restablecer acceso).
- tenants.purge_requested_at/by: la UI solicita la purga; la ejecuta el script con rol dueño.
- control.invitations: tokens de un solo uso (solo se guarda su sha256).
- control.admin_events: bitácora de solo inserción (sin UPDATE ni DELETE para app_user).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID

from backend.migrations.rls import (
    CONTROL,
    app_role,
    grant_app,
    revoke_supabase_api_roles,
    table_exists,
)

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )


def _has_column(table: str, column: str) -> bool:
    columns = sa.inspect(op.get_bind()).get_columns(table, schema=CONTROL)
    return any(c["name"] == column for c in columns)


def upgrade() -> None:
    op.alter_column("users", "hashed_password", nullable=True, schema=CONTROL)
    for column in ("last_login_at", "sessions_valid_after"):
        if not _has_column("users", column):
            op.add_column(
                "users",
                sa.Column(column, sa.DateTime(timezone=True), nullable=True),
                schema=CONTROL,
            )
    if not _has_column("tenants", "sessions_valid_after"):
        op.add_column(
            "tenants",
            sa.Column("sessions_valid_after", sa.DateTime(timezone=True), nullable=True),
            schema=CONTROL,
        )
    if not _has_column("tenants", "purge_requested_at"):
        op.add_column(
            "tenants",
            sa.Column("purge_requested_at", sa.DateTime(timezone=True), nullable=True),
            schema=CONTROL,
        )
    if not _has_column("tenants", "purge_requested_by"):
        op.add_column(
            "tenants",
            sa.Column("purge_requested_by", UUID(as_uuid=True), nullable=True),
            schema=CONTROL,
        )

    if not table_exists("invitations", CONTROL):
        op.create_table(
            "invitations",
            _uuid_pk(),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", UUID(as_uuid=True), nullable=False),
            sa.Column("purpose", sa.Text(), nullable=False),
            sa.Column("token_hash", sa.Text(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by", UUID(as_uuid=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "user_id"],
                ["control.users.tenant_id", "control.users.id"],
                name="fk_invitations_user",
                ondelete="CASCADE",
            ),
            sa.UniqueConstraint("token_hash", name="uq_invitations_token_hash"),
            sa.CheckConstraint("purpose IN ('invite', 'reset')", name="ck_invitations_purpose"),
            sa.CheckConstraint("char_length(token_hash) = 64", name="ck_invitations_token_hash"),
            schema=CONTROL,
        )
        op.create_index("ix_invitations_user", "invitations", ["user_id"], schema=CONTROL)

    if not table_exists("admin_events", CONTROL):
        op.create_table(
            "admin_events",
            _uuid_pk(),
            sa.Column(
                "occurred_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("actor_id", UUID(as_uuid=True), nullable=True),
            sa.Column("actor_role", sa.Text(), nullable=False),
            sa.Column("action", sa.Text(), nullable=False),
            # Sin FK: la bitácora sobrevive a la purga del tenant
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=True),
            sa.Column("target_type", sa.Text(), nullable=False),
            sa.Column("target_id", UUID(as_uuid=True), nullable=True),
            sa.Column("ip", INET(), nullable=True),
            sa.Column("details", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.CheckConstraint(
                "actor_role IN ('platform_admin', 'tenant_admin', 'system', 'user')",
                name="ck_admin_events_actor_role",
            ),
            sa.CheckConstraint(
                "target_type IN ('tenant', 'user')", name="ck_admin_events_target_type"
            ),
            schema=CONTROL,
        )
        op.create_index(
            "ix_admin_events_tenant",
            "admin_events",
            ["tenant_id", "occurred_at"],
            schema=CONTROL,
        )
        op.create_index("ix_admin_events_occurred", "admin_events", ["occurred_at"], schema=CONTROL)

    # La app puede cambiar el rol SOLO entre doctor y tenant_admin; la base lo garantiza aunque
    # el código tuviera un error (nunca hacia ni desde patient o platform_admin)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION control.enforce_staff_role_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.role IS DISTINCT FROM OLD.role AND NOT (
               OLD.role IN ('doctor', 'tenant_admin')
               AND NEW.role IN ('doctor', 'tenant_admin')) THEN
            RAISE EXCEPTION 'Solo se permite cambiar el rol entre doctor y tenant_admin';
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_users_staff_role_change ON control.users")
    op.execute(
        "CREATE TRIGGER trg_users_staff_role_change BEFORE UPDATE OF role ON control.users "
        "FOR EACH ROW EXECUTE FUNCTION control.enforce_staff_role_change()"
    )
    grant_app("users", "UPDATE (last_login_at, sessions_valid_after, role)", schema=CONTROL)
    grant_app(
        "tenants",
        "UPDATE (purge_requested_at, purge_requested_by, sessions_valid_after)",
        schema=CONTROL,
    )
    grant_app("invitations", "SELECT, INSERT, UPDATE (used_at, revoked_at)", schema=CONTROL)
    # Bitácora inalterable desde la app: solo leer e insertar
    grant_app("admin_events", "SELECT, INSERT", schema=CONTROL)
    revoke_supabase_api_roles()


def downgrade() -> None:
    bind = op.get_bind()
    for table in ("admin_events", "invitations"):
        if table_exists(table, CONTROL):
            if bind.execute(sa.text(f"SELECT 1 FROM control.{table} LIMIT 1")).first():
                raise RuntimeError(f"control.{table} tiene datos; el downgrade de 0012 no borra.")
    if bind.execute(
        sa.text("SELECT 1 FROM control.users WHERE hashed_password IS NULL LIMIT 1")
    ).first():
        raise RuntimeError("Hay cuentas invitadas sin contraseña; el downgrade de 0012 no sigue.")
    op.execute("DROP TABLE IF EXISTS control.admin_events")
    op.execute("DROP TABLE IF EXISTS control.invitations")
    # Las columnas que se borran pierden sus privilegios; role se queda y se le quita el UPDATE
    op.execute(f"REVOKE UPDATE (role) ON control.users FROM {app_role()}")
    op.execute("DROP TRIGGER IF EXISTS trg_users_staff_role_change ON control.users")
    op.execute("DROP FUNCTION IF EXISTS control.enforce_staff_role_change()")
    for table, column in (
        ("users", "last_login_at"),
        ("users", "sessions_valid_after"),
        ("tenants", "sessions_valid_after"),
        ("tenants", "purge_requested_at"),
        ("tenants", "purge_requested_by"),
    ):
        op.execute(f"ALTER TABLE control.{table} DROP COLUMN IF EXISTS {column}")
    op.alter_column("users", "hashed_password", nullable=False, schema=CONTROL)
