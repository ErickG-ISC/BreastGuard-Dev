"""migrar usuarios del prototipo (public.users) al tenant B2C y archivar las tablas viejas

- Cada usuario con email y contraseña pasa a control.users con uuid nuevo, tenant b2c y rol
  patient (is_medical era autodeclarado, así que no se conserva). El hash bcrypt se mantiene.
- Cada usuario migrado recibe su ficha en clinical.patients.
- Las imágenes de prueba no se migran (no hay objetos en Storage); quedan archivadas.
- public.users y public.medical_images se MUEVEN al esquema legacy (no expuesto); no se borran.

Solo se registran conteos, nunca emails ni datos.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-21

"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.migrations.rls import assert_bypass, revoke_supabase_api_roles, table_exists

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

LEGACY_TABLES = ("medical_images", "users")


def _b2c_tenant_id(bind) -> str:
    return str(
        bind.execute(sa.text("SELECT id FROM control.tenants WHERE slug = 'b2c'")).scalar_one()
    )


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE SCHEMA IF NOT EXISTS legacy")
    op.execute("REVOKE ALL ON SCHEMA legacy FROM PUBLIC")

    if table_exists("users", "public"):
        assert_bypass(bind)
        b2c = _b2c_tenant_id(bind)
        counts = bind.execute(
            sa.text(
                "SELECT count(*) AS total, "
                "count(*) FILTER (WHERE email IS NULL OR hashed_password IS NULL) AS sin_datos, "
                "count(*) FILTER (WHERE is_medical) AS medicos "
                "FROM public.users"
            )
        ).one()
        bind.execute(
            sa.text(
                """
                INSERT INTO control.users
                  (tenant_id, email, hashed_password, full_name, role, is_active, created_at)
                SELECT CAST(:b2c AS uuid), u.email, u.hashed_password,
                       COALESCE(NULLIF(u.full_name, ''), split_part(u.email, '@', 1)),
                       'patient', true, COALESCE(u.created_at, now())
                FROM public.users u
                WHERE u.email IS NOT NULL AND u.hashed_password IS NOT NULL
                ON CONFLICT ((lower(email))) DO NOTHING
                """
            ),
            {"b2c": b2c},
        )
        # Fichas clínicas con el contexto del tenant b2c (además de BYPASSRLS, por coherencia)
        bind.execute(sa.text("SELECT set_config('app.tenant_id', :b2c, true)"), {"b2c": b2c})
        bind.execute(
            sa.text(
                """
                INSERT INTO clinical.patients (tenant_id, user_id, display_name)
                SELECT u.tenant_id, u.id, u.full_name
                FROM control.users u
                WHERE u.tenant_id = CAST(:b2c AS uuid) AND u.role = 'patient'
                  AND lower(u.email) IN (SELECT lower(email) FROM public.users)
                ON CONFLICT (tenant_id, user_id) DO NOTHING
                """
            ),
            {"b2c": b2c},
        )
        bind.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
        logger.info(
            "Legado: %s usuarios, %s omitidos (sin email/contraseña), %s con is_medical",
            counts.total,
            counts.sin_datos,
            counts.medicos,
        )

    for table in LEGACY_TABLES:
        if table_exists(table, "public"):
            if table == "medical_images":
                n = bind.execute(sa.text("SELECT count(*) FROM public.medical_images")).scalar_one()
                logger.info("Legado: %s imágenes de prueba archivadas sin migrar", n)
            op.execute(f"ALTER TABLE public.{table} SET SCHEMA legacy")

    op.execute(
        """
        DO $$
        DECLARE r text;
        BEGIN
          FOR r IN SELECT rolname FROM pg_roles
                   WHERE rolname IN ('anon', 'authenticated', 'service_role') LOOP
            EXECUTE format('REVOKE ALL ON SCHEMA legacy FROM %I', r);
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA legacy FROM %I', r);
          END LOOP;
        END $$;
        """
    )
    revoke_supabase_api_roles()


def downgrade() -> None:
    bind = op.get_bind()
    if table_exists("users", "legacy"):
        assert_bypass(bind)
        nuevos = bind.execute(
            sa.text(
                "SELECT count(*) FROM control.users u "
                "WHERE u.tenant_id IS NULL OR lower(u.email) NOT IN "
                "(SELECT lower(email) FROM legacy.users WHERE email IS NOT NULL)"
            )
        ).scalar_one()
        if nuevos:
            raise RuntimeError(
                "Hay usuarios creados después de migrar; el downgrade de 0005 no los borra."
            )
        for table in ("clinical.medical_images", "clinical.audit_log"):
            if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
                raise RuntimeError(f"{table} tiene datos; el downgrade de 0005 no los borra.")
        b2c = _b2c_tenant_id(bind)
        bind.execute(sa.text("SELECT set_config('app.tenant_id', :b2c, true)"), {"b2c": b2c})
        bind.execute(sa.text("DELETE FROM clinical.patients"))
        bind.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
        bind.execute(sa.text("DELETE FROM control.users"))

    for table in reversed(LEGACY_TABLES):
        if table_exists(table, "legacy"):
            op.execute(f"ALTER TABLE legacy.{table} SET SCHEMA public")
    op.execute("DROP SCHEMA IF EXISTS legacy")
