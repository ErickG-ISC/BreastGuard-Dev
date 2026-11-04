"""control: paquetes compartidos, su bitácora y avisos internos (CU-07, ADR 0010)

Solo METADATOS en control, nunca datos clínicos:
- `share_packages`: hash del código (HMAC), estado, caducidad, secciones elegidas (booleanos),
  consentimiento, prefijo de transferencia en Storage y quién lo importó;
- `share_events`: lo que la paciente puede ver de su paquete (creado, revocado, importado...);
- `inbox_notices`: avisos internos ("tienes un paquete"), solo tipo e id de referencia.

El contenido viaja cifrado en Storage bajo `transfer/{uuid}/`; la llave solo existe en el código.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.migrations.rls import (
    CONTROL,
    assert_empty,
    grant_app,
    revoke_supabase_api_roles,
    table_exists,
)

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = ("activo", "importando", "importado", "revocado", "caducado")
EVENT_KINDS = ("creado", "revocado", "caducado", "importado", "intento_fallido", "reasignado")
NOTICE_KINDS = ("share_received", "share_update")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )


def _created_at(name: str = "created_at") -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    if not table_exists("share_packages", CONTROL):
        op.create_table(
            "share_packages",
            _uuid_pk(),
            sa.Column("source_tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("source_user_id", UUID(as_uuid=True), nullable=False),
            sa.Column("key_hash", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'activo'")),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("recipient_email", sa.Text(), nullable=True),
            sa.Column("recipient_user_id", UUID(as_uuid=True), nullable=True),
            # Solo booleanos: qué secciones se eligieron, nunca su contenido
            sa.Column("sections", JSONB(), nullable=False),
            sa.Column("analyses_count", sa.SmallInteger(), nullable=False),
            sa.Column("size_bytes", sa.BigInteger(), nullable=False),
            sa.Column("consent_version", sa.Text(), nullable=False),
            sa.Column("consent_sha256", sa.Text(), nullable=False),
            sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("object_prefix", sa.Text(), nullable=False),
            sa.Column("objects_deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "failed_attempts", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
            ),
            sa.Column("claimed_by", UUID(as_uuid=True), nullable=True),
            sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("imported_tenant_id", UUID(as_uuid=True), nullable=True),
            _created_at(),
            sa.ForeignKeyConstraint(
                ["source_tenant_id", "source_user_id"],
                ["control.users.tenant_id", "control.users.id"],
                name="fk_share_packages_source",
            ),
            sa.ForeignKeyConstraint(
                ["recipient_user_id"], ["control.users.id"], name="fk_share_packages_recipient"
            ),
            sa.UniqueConstraint("key_hash", name="uq_share_packages_key_hash"),
            sa.CheckConstraint(f"status IN ({_in(STATUSES)})", name="ck_share_packages_status"),
            sa.CheckConstraint("char_length(key_hash) = 64", name="ck_share_packages_key_hash"),
            sa.CheckConstraint(
                "object_prefix ~ '^transfer/[0-9a-f]{32}/$'", name="ck_share_packages_prefix"
            ),
            sa.CheckConstraint(
                "analyses_count BETWEEN 0 AND 10", name="ck_share_packages_analyses_count"
            ),
            sa.CheckConstraint(
                "expires_at <= created_at + interval '7 days'", name="ck_share_packages_expiry"
            ),
            sa.CheckConstraint(
                "recipient_email IS NULL OR recipient_email = lower(recipient_email)",
                name="ck_share_packages_recipient_lower",
            ),
            schema=CONTROL,
        )
        op.create_index(
            "ix_share_packages_source",
            "share_packages",
            ["source_tenant_id", "source_user_id", "created_at"],
            schema=CONTROL,
        )
        op.create_index(
            "ix_share_packages_status_expiry",
            "share_packages",
            ["status", "expires_at"],
            schema=CONTROL,
        )

    if not table_exists("share_events", CONTROL):
        op.create_table(
            "share_events",
            _uuid_pk(),
            sa.Column("package_id", UUID(as_uuid=True), nullable=False),
            _created_at("occurred_at"),
            sa.Column("kind", sa.Text(), nullable=False),
            # Para que la paciente sepa quién tiene su copia (CU-07): nombres, nunca datos clínicos
            sa.Column("institution_name", sa.Text(), nullable=True),
            sa.Column("doctor_name", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(
                ["package_id"],
                ["control.share_packages.id"],
                name="fk_share_events_package",
                ondelete="CASCADE",
            ),
            sa.CheckConstraint(f"kind IN ({_in(EVENT_KINDS)})", name="ck_share_events_kind"),
            schema=CONTROL,
        )
        op.create_index(
            "ix_share_events_package", "share_events", ["package_id", "occurred_at"], schema=CONTROL
        )

    if not table_exists("inbox_notices", CONTROL):
        op.create_table(
            "inbox_notices",
            _uuid_pk(),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", UUID(as_uuid=True), nullable=False),
            sa.Column("kind", sa.Text(), nullable=False),
            sa.Column("ref_id", UUID(as_uuid=True), nullable=True),
            _created_at(),
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["tenant_id", "user_id"],
                ["control.users.tenant_id", "control.users.id"],
                name="fk_inbox_notices_user",
                ondelete="CASCADE",
            ),
            sa.CheckConstraint(f"kind IN ({_in(NOTICE_KINDS)})", name="ck_inbox_notices_kind"),
            schema=CONTROL,
        )
        op.create_index(
            "ix_inbox_notices_user", "inbox_notices", ["user_id", "created_at"], schema=CONTROL
        )

    # control no tiene RLS y app_user es también el rol de las sesiones clínicas. La base asegura:
    # - solo la paciente, con SU contexto, crea paquetes a su nombre;
    # - en su contexto solo puede revocar los suyos (activo → revocado), nada más;
    # - ninguna sesión con contexto de doctora o administración toca paquetes: la importación y
    #   la limpieza usan sesiones de control sin contexto.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION control.enforce_share_writes() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
          ctx_role text := NULLIF(current_setting('app.role', true), '');
        BEGIN
          IF ctx_role IS NULL THEN
            RETURN NEW;
          END IF;
          IF ctx_role <> 'patient' THEN
            RAISE EXCEPTION 'Solo la paciente o el servidor modifican paquetes compartidos';
          END IF;
          IF TG_OP = 'INSERT' THEN
            IF NEW.source_user_id IS DISTINCT FROM clinical.current_user_id()
               OR NEW.source_tenant_id IS DISTINCT FROM clinical.current_tenant_id()
               OR NEW.status <> 'activo' OR NEW.claimed_by IS NOT NULL
               OR NEW.imported_at IS NOT NULL OR NEW.failed_attempts <> 0 THEN
              RAISE EXCEPTION 'Un paquete nuevo es de quien lo crea y empieza activo';
            END IF;
            RETURN NEW;
          END IF;
          IF OLD.source_user_id IS DISTINCT FROM clinical.current_user_id()
             OR NOT (NEW.status = OLD.status OR (OLD.status = 'activo' AND NEW.status = 'revocado'))
             OR NEW.failed_attempts IS DISTINCT FROM OLD.failed_attempts
             OR NEW.claimed_by IS DISTINCT FROM OLD.claimed_by
             OR NEW.claimed_at IS DISTINCT FROM OLD.claimed_at
             OR NEW.imported_at IS DISTINCT FROM OLD.imported_at
             OR NEW.imported_tenant_id IS DISTINCT FROM OLD.imported_tenant_id THEN
            RAISE EXCEPTION 'La paciente solo puede revocar sus paquetes activos';
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_share_packages_writes ON control.share_packages")
    op.execute(
        "CREATE TRIGGER trg_share_packages_writes BEFORE INSERT OR UPDATE "
        "ON control.share_packages FOR EACH ROW EXECUTE FUNCTION control.enforce_share_writes()"
    )
    grant_app(
        "share_packages",
        "SELECT, INSERT, UPDATE (status, objects_deleted_at, failed_attempts, claimed_by, "
        "claimed_at, imported_at, imported_tenant_id)",
        schema=CONTROL,
    )
    # Bitácora del paquete: solo inserción
    grant_app("share_events", "SELECT, INSERT", schema=CONTROL)
    grant_app("inbox_notices", "SELECT, INSERT, UPDATE (read_at)", schema=CONTROL)
    revoke_supabase_api_roles()


def downgrade() -> None:
    for table in ("inbox_notices", "share_events", "share_packages"):
        if table_exists(table, CONTROL):
            assert_empty(f"control.{table}", f"control.{table} tiene datos; 0015 no los borra.")
    op.execute("DROP TABLE IF EXISTS control.inbox_notices")
    op.execute("DROP TABLE IF EXISTS control.share_events")
    op.execute("DROP TABLE IF EXISTS control.share_packages")
    op.execute("DROP FUNCTION IF EXISTS control.enforce_share_writes()")
