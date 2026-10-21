"""Helpers de migración para el modelo de una base con RLS forzado (ADR 0002).

Toda tabla de `clinical` se crea y protege con estas funciones; no uses `op.create_table`
suelto para datos clínicos. Los identificadores vienen del código de la migración, nunca de
entradas externas, y aun así se validan.
"""

import os
import re

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.schema import SchemaItem

CLINICAL = "clinical"
CONTROL = "control"
# Roles de Supabase que exponen datos por la Data API; se les revoca todo si existen
SUPABASE_API_ROLES = ("anon", "authenticated", "service_role")

_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

CURRENT_TENANT = "(SELECT clinical.current_tenant_id())"
CURRENT_USER = "(SELECT clinical.current_user_id())"
CURRENT_ROLE = "(SELECT clinical.current_app_role())"


def ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"Identificador SQL no válido: {name!r}")
    return name


def app_role() -> str:
    """Rol de la aplicación (`APP_DB_USER`, por defecto `app_user`)."""
    return ident(os.environ.get("APP_DB_USER", "app_user"))


def table_exists(name: str, schema: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name, schema=schema)


def create_tenant_table(name: str, *columns: SchemaItem) -> bool:
    """Crea `clinical.<name>` con `tenant_id` (default del contexto) e `id`, PK `(tenant_id, id)`.

    Devuelve False si la tabla ya existía (idempotente).
    """
    if table_exists(name, CLINICAL):
        return False
    op.create_table(
        ident(name),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("clinical.current_tenant_id()"),
        ),
        sa.Column(
            "id", UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")
        ),
        *columns,
        sa.PrimaryKeyConstraint("tenant_id", "id", name=f"{name}_pkey"),
        schema=CLINICAL,
    )
    return True


def enable_tenant_rls(name: str) -> None:
    """RLS habilitado y FORZADO, con la política de aislamiento por tenant (USING + WITH CHECK)."""
    table = f"{CLINICAL}.{ident(name)}"
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} AS PERMISSIVE FOR ALL "
        f"USING (tenant_id = {CURRENT_TENANT}) WITH CHECK (tenant_id = {CURRENT_TENANT})"
    )


def add_role_policy(
    name: str,
    policy: str,
    using_sql: str | None,
    *,
    command: str = "ALL",
    with_check_sql: str | None = None,
    restrictive: bool = True,
) -> None:
    """Política adicional (por defecto RESTRICTIVE: se combina con AND con la de tenant)."""
    if command not in {"ALL", "SELECT", "INSERT", "UPDATE", "DELETE"}:
        raise ValueError(f"Comando de política no válido: {command}")
    table = f"{CLINICAL}.{ident(name)}"
    kind = "RESTRICTIVE" if restrictive else "PERMISSIVE"
    op.execute(f"DROP POLICY IF EXISTS {ident(policy)} ON {table}")
    sql = f"CREATE POLICY {policy} ON {table} AS {kind} FOR {command}"
    if using_sql is not None:
        sql += f" USING ({using_sql})"
    if with_check_sql is not None:
        sql += f" WITH CHECK ({with_check_sql})"
    op.execute(sql)


# Solo los roles clínicos del tenant pasan; un rol nulo o desconocido ve 0 filas
CLINICAL_ROLE_SQL = f"{CURRENT_ROLE} IN ('patient', 'doctor', 'tenant_admin')"


def add_patient_owner_policy(name: str, policy: str) -> None:
    """Política restrictiva para tablas con `patient_id`: una paciente solo ve y crea lo suyo.

    El personal clínico del tenant (doctor, tenant_admin) ve todas las filas de su tenant.
    """
    own = f"patient_id IN (SELECT p.id FROM clinical.patients p WHERE p.user_id = {CURRENT_USER})"
    rule = f"{CLINICAL_ROLE_SQL} AND ({CURRENT_ROLE} <> 'patient' OR {own})"
    add_role_policy(name, policy, rule, with_check_sql=rule)


def tenant_fk(
    name: str,
    table: str,
    columns: list[str],
    ref_table: str,
    ref_columns: list[str],
    *,
    ref_schema: str = CLINICAL,
) -> None:
    """FK compuesta que siempre empieza por `tenant_id`: impide referenciar filas de otro tenant."""
    if columns[0] != "tenant_id" or ref_columns[0] != "tenant_id":
        raise ValueError(
            "Las FKs entre datos de tenants deben ser compuestas y empezar por tenant_id"
        )
    op.create_foreign_key(
        ident(name),
        ident(table),
        ident(ref_table),
        columns,
        ref_columns,
        source_schema=CLINICAL,
        referent_schema=ref_schema,
    )


def grant_app(name: str, privileges: str, *, schema: str = CLINICAL) -> None:
    allowed = {"SELECT", "INSERT", "UPDATE", "DELETE"}
    # Separa por comas que no estén dentro de paréntesis: "UPDATE (is_active, name)"
    parts = [p.strip() for p in re.split(r",(?![^()]*\))", privileges)]
    for part in parts:
        verb, _, cols = part.partition("(")
        if verb.strip().upper() not in allowed:
            raise ValueError(f"Privilegio no permitido para la app: {part}")
        for col in filter(None, (c.strip() for c in cols.rstrip(")").split(","))):
            ident(col)
    op.execute(f"GRANT {', '.join(parts)} ON {ident(schema)}.{ident(name)} TO {app_role()}")


def revoke_supabase_api_roles() -> None:
    """Quita todo acceso a control/clinical (y alembic_version) a los roles de la Data API."""
    roles = ", ".join(f"'{r}'" for r in SUPABASE_API_ROLES)
    op.execute(
        f"""
        DO $$
        DECLARE r text;
        BEGIN
          FOR r IN SELECT rolname FROM pg_roles WHERE rolname IN ({roles}) LOOP
            EXECUTE format('REVOKE ALL ON SCHEMA control, clinical FROM %I', r);
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA control, clinical FROM %I', r);
            EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA control, clinical FROM %I', r);
            EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA control, clinical FROM %I', r);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA control, clinical '
                           'REVOKE ALL ON TABLES FROM %I', r);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA control, clinical '
                           'REVOKE ALL ON FUNCTIONS FROM %I', r);
            IF to_regclass('public.alembic_version') IS NOT NULL THEN
              EXECUTE format('REVOKE ALL ON TABLE public.alembic_version FROM %I', r);
            END IF;
          END LOOP;
        END $$;
        """
    )


def assert_bypass(bind) -> None:
    """Las migraciones que leen o escriben datos clínicos exigen un dueño con BYPASSRLS.

    Con RLS forzado, un dueño sin bypass vería 0 filas sin error: un guard de "tabla vacía"
    pasaría y un DROP borraría datos reales. Mejor fallar fuerte.
    """
    row = bind.execute(
        sa.text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
    ).one()
    if not (row.rolsuper or row.rolbypassrls):
        raise RuntimeError(
            "Esta migración toca datos clínicos y requiere un rol dueño con BYPASSRLS."
        )


def assert_empty(table: str, message: str) -> None:
    """Para downgrades: se niega a borrar tablas con datos (nunca en falso por RLS)."""
    bind = op.get_bind()
    if table.startswith(f"{CLINICAL}."):
        assert_bypass(bind)
    if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
        raise RuntimeError(message)
