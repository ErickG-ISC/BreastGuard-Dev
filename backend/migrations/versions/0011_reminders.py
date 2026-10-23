"""control: recordatorios y avisos en la app (CU-05)

Configuración de notificaciones, no datos clínicos: va en control, sin RLS (ADR 0007). Así el
despachador trabaja solo con la conexión de control, sin contexto de tenant, y nunca puede ver
filas de clinical. Toda consulta de la app filtra por el user_id del JWT.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, UUID

from backend.migrations.rls import CONTROL, grant_app, revoke_supabase_api_roles, table_exists

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )


def upgrade() -> None:
    if not table_exists("reminders", CONTROL):
        op.create_table(
            "reminders",
            _uuid_pk(),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", UUID(as_uuid=True), nullable=False),
            sa.Column("kind", sa.Text(), nullable=False),
            sa.Column("frequency", sa.Text(), nullable=False),
            sa.Column("interval_n", sa.SmallInteger(), nullable=True),
            sa.Column("local_time", sa.Time(), nullable=False),
            sa.Column("timezone", sa.Text(), nullable=False),
            # Día desde el que se cuentan "cada N días/meses" (fecha local de la paciente)
            sa.Column("anchor_date", sa.Date(), nullable=False),
            sa.Column("channels", ARRAY(sa.Text()), nullable=False),
            sa.Column("discreet", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            # El usuario pertenece a ese tenant (users tiene UNIQUE (tenant_id, id))
            sa.ForeignKeyConstraint(
                ["tenant_id", "user_id"],
                ["control.users.tenant_id", "control.users.id"],
                name="fk_reminders_user",
                ondelete="CASCADE",
            ),
            sa.UniqueConstraint("user_id", "kind", name="uq_reminders_user_kind"),
            sa.CheckConstraint(
                "kind IN ('self_exam', 'repeat_analysis')", name="ck_reminders_kind"
            ),
            sa.CheckConstraint(
                "(frequency = 'first_sunday' AND interval_n IS NULL) "
                "OR (frequency = 'every_n_days' AND interval_n BETWEEN 1 AND 90) "
                "OR (frequency = 'every_n_months' AND interval_n BETWEEN 1 AND 24)",
                name="ck_reminders_frequency",
            ),
            sa.CheckConstraint(
                "extract(minute FROM local_time)::int % 15 = 0 "
                "AND extract(second FROM local_time) = 0",
                name="ck_reminders_local_time",
            ),
            sa.CheckConstraint(
                "cardinality(channels) >= 1 AND channels <@ ARRAY['in_app', 'email']::text[]",
                name="ck_reminders_channels",
            ),
            schema=CONTROL,
        )
        op.create_index(
            "ix_reminders_due",
            "reminders",
            ["next_run_at"],
            schema=CONTROL,
            postgresql_where=sa.text("active"),
        )
    if not table_exists("reminder_notices", CONTROL):
        op.create_table(
            "reminder_notices",
            _uuid_pk(),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "reminder_id",
                UUID(as_uuid=True),
                sa.ForeignKey(
                    "control.reminders.id", name="fk_reminder_notices_reminder", ondelete="CASCADE"
                ),
                nullable=False,
            ),
            sa.Column("kind", sa.Text(), nullable=False),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("email_status", sa.Text(), nullable=False, server_default="none"),
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "user_id"],
                ["control.users.tenant_id", "control.users.id"],
                name="fk_reminder_notices_user",
                ondelete="CASCADE",
            ),
            # Idempotencia del despachador: un aviso por recordatorio y vencimiento
            sa.UniqueConstraint("reminder_id", "due_at", name="uq_reminder_notices_due"),
            sa.CheckConstraint(
                "email_status IN ('none', 'pending', 'sent', 'failed')",
                name="ck_reminder_notices_email_status",
            ),
            sa.CheckConstraint(
                "kind IN ('self_exam', 'repeat_analysis')", name="ck_reminder_notices_kind"
            ),
            schema=CONTROL,
        )
        op.create_index(
            "ix_reminder_notices_user",
            "reminder_notices",
            ["user_id", "created_at"],
            schema=CONTROL,
        )

    grant_app(
        "reminders",
        "SELECT, INSERT, DELETE, UPDATE (frequency, interval_n, local_time, timezone, "
        "anchor_date, channels, discreet, active, next_run_at, last_run_at, updated_at)",
        schema=CONTROL,
    )
    grant_app("reminder_notices", "SELECT, INSERT, UPDATE (read_at, email_status)", schema=CONTROL)
    revoke_supabase_api_roles()


def downgrade() -> None:
    for table in ("reminder_notices", "reminders"):
        if table_exists(table, CONTROL):
            if op.get_bind().execute(sa.text(f"SELECT 1 FROM control.{table} LIMIT 1")).first():
                raise RuntimeError(f"control.{table} tiene datos; el downgrade de 0011 no borra.")
    op.execute("DROP TABLE IF EXISTS control.reminder_notices")
    op.execute("DROP TABLE IF EXISTS control.reminders")
