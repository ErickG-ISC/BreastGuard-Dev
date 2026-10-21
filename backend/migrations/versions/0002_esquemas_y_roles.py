"""esquemas control y clinical, funciones de contexto y rol de la app

Crea el rol de la app (APP_DB_USER, por defecto app_user) sin superusuario ni BYPASSRLS.
La contraseña (APP_DB_PASSWORD) entra por set_config local y format('%L'): nunca aparece en
el SQL de la migración. El downgrade no borra el rol (es de todo el clúster).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-21

"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

from backend.migrations.rls import app_role, revoke_supabase_api_roles

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTEXT_FUNCTIONS = {
    "current_tenant_id": ("uuid", "NULLIF(current_setting('app.tenant_id', true), '')::uuid"),
    "current_user_id": ("uuid", "NULLIF(current_setting('app.user_id', true), '')::uuid"),
    "current_app_role": ("text", "NULLIF(current_setting('app.role', true), '')"),
}


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError(
            "Esta migración no se genera en modo offline (crea un rol con contraseña)."
        )
    password = os.environ.get("APP_DB_PASSWORD")
    if not password:
        raise RuntimeError("Falta APP_DB_PASSWORD para crear el rol de la aplicación.")
    role = app_role()

    op.execute("CREATE SCHEMA IF NOT EXISTS control")
    op.execute("CREATE SCHEMA IF NOT EXISTS clinical")
    op.execute("REVOKE ALL ON SCHEMA control, clinical FROM PUBLIC")
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")

    # Funciones de contexto: sin contexto devuelven NULL, así las políticas fallan cerrado
    for name, (returns, expr) in CONTEXT_FUNCTIONS.items():
        op.execute(
            f"CREATE OR REPLACE FUNCTION clinical.{name}() RETURNS {returns} "
            f"LANGUAGE sql STABLE PARALLEL SAFE AS $$ SELECT {expr} $$"
        )

    # Rol de la app: LOGIN, sin atributos privilegiados (los defaults son NOSUPERUSER,
    # NOBYPASSRLS, NOCREATEDB, NOCREATEROLE)
    op.execute(
        sa.text("SELECT set_config('breastguard.app_password', :pw, true)").bindparams(pw=password)
    )
    op.execute(
        f"""
        DO $$
        DECLARE pw text := current_setting('breastguard.app_password');
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
            EXECUTE format('CREATE ROLE %I LOGIN NOINHERIT PASSWORD %L', '{role}', pw);
          ELSE
            EXECUTE format('ALTER ROLE %I LOGIN PASSWORD %L', '{role}', pw);
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}'
                     AND (rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole)) THEN
            RAISE EXCEPTION 'El rol de la app tiene atributos privilegiados';
          END IF;
        END $$;
        """
    )
    op.execute("SELECT set_config('breastguard.app_password', '', true)")

    op.execute(f"GRANT USAGE ON SCHEMA control, clinical TO {role}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {role}")
    revoke_supabase_api_roles()


def downgrade() -> None:
    for name in CONTEXT_FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS clinical.{name}()")
    # Sin CASCADE: si queda algo en los esquemas, el downgrade falla en lugar de borrarlo
    op.execute("DROP SCHEMA IF EXISTS clinical")
    op.execute("DROP SCHEMA IF EXISTS control")
    # El rol no se borra: es de todo el clúster y otras bases pueden usarlo.
