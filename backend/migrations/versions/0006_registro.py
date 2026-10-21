"""control: consentimientos, planes simulados y suscripciones (CU-01)

Identidad y cuenta, no datos clínicos: van en control, sin RLS. app_user no puede borrar ni
modificar consentimientos (solo SELECT, INSERT) y solo lee los planes.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, INET, UUID

from backend.migrations.rls import CONTROL, grant_app, revoke_supabase_api_roles, table_exists

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PLANS = [
    (
        "basico",
        "Básico",
        "Para empezar a cuidar tu salud mamaria.",
        "Simulado · $0/mes",
        ["Análisis de ecografías", "Cuestionario de factores", "Historial de resultados"],
        1,
    ),
    (
        "plus",
        "Plus",
        "Más seguimiento y recordatorios.",
        "Simulado · $0/mes",
        ["Todo lo del plan Básico", "Recordatorios de autoexploración", "Diario de síntomas"],
        2,
    ),
    (
        "premium",
        "Premium",
        "Comparte tu información con tu médica o médico.",
        "Simulado · $0/mes",
        ["Todo lo del plan Plus", "Compartir paquete con tu médico", "Reporte en PDF"],
        3,
    ),
]


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )


def upgrade() -> None:
    if not table_exists("consents", CONTROL):
        op.create_table(
            "consents",
            _uuid_pk(),
            sa.Column(
                "user_id",
                UUID(as_uuid=True),
                sa.ForeignKey("control.users.id", name="fk_consents_user"),
                nullable=False,
            ),
            sa.Column("version", sa.Text(), nullable=False),
            sa.Column("text_sha256", sa.Text(), nullable=False),
            sa.Column(
                "accepted_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("ip", INET(), nullable=True),
            sa.UniqueConstraint("user_id", "version", name="uq_consents_user_version"),
            schema=CONTROL,
        )
    if not table_exists("plans", CONTROL):
        op.create_table(
            "plans",
            sa.Column("code", sa.Text(), primary_key=True),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("price_label", sa.Text(), nullable=False),
            sa.Column("features", ARRAY(sa.Text()), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
            schema=CONTROL,
        )
    if not table_exists("subscriptions", CONTROL):
        op.create_table(
            "subscriptions",
            _uuid_pk(),
            sa.Column(
                "user_id",
                UUID(as_uuid=True),
                sa.ForeignKey("control.users.id", name="fk_subscriptions_user"),
                nullable=False,
            ),
            sa.Column(
                "plan_code",
                sa.Text(),
                sa.ForeignKey("control.plans.code", name="fk_subscriptions_plan"),
                nullable=False,
            ),
            # Sin pasarela de pago: toda suscripción es una simulación
            sa.Column("status", sa.Text(), nullable=False, server_default="simulada"),
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint("user_id", name="uq_subscriptions_user"),
            sa.CheckConstraint("status = 'simulada'", name="ck_subscriptions_status"),
            schema=CONTROL,
        )

    for code, name, description, price, features, sort in PLANS:
        op.execute(
            sa.text(
                "INSERT INTO control.plans (code, name, description, price_label, features, sort) "
                "VALUES (:code, :name, :description, :price, :features, :sort) "
                "ON CONFLICT (code) DO NOTHING"
            ).bindparams(
                code=code,
                name=name,
                description=description,
                price=price,
                features=features,
                sort=sort,
            )
        )

    grant_app("consents", "SELECT, INSERT", schema=CONTROL)
    grant_app("plans", "SELECT", schema=CONTROL)
    grant_app("subscriptions", "SELECT, INSERT, UPDATE (plan_code, started_at)", schema=CONTROL)
    revoke_supabase_api_roles()


def downgrade() -> None:
    for table in ("subscriptions", "consents"):
        if table_exists(table, CONTROL):
            if op.get_bind().execute(sa.text(f"SELECT 1 FROM control.{table} LIMIT 1")).first():
                raise RuntimeError(f"control.{table} tiene datos; el downgrade de 0006 no borra.")
    op.execute("DROP TABLE IF EXISTS control.subscriptions")
    op.execute("DROP TABLE IF EXISTS control.consents")
    op.execute("DROP TABLE IF EXISTS control.plans")
