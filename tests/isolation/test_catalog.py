"""Prueba de catálogo: falla si alguien agrega una tabla clínica sin RLS forzado o abre un hueco.

Se consulta el catálogo de Postgres como dueño (solo lectura de metadatos).
"""

import pytest
from sqlalchemy import text

from tests.isolation.catalogo import CLINICAL_TABLES_SQL, rls_problems
from tests.pgtest import TEST_APP_ROLE

pytestmark = pytest.mark.usefixtures("database")


def rows(owner_engine, sql: str, **params):
    with owner_engine.connect() as conn:
        return conn.execute(text(sql), params).all()


def test_toda_tabla_clinica_tiene_tenant_id_rls_forzado_y_politica(owner_engine):
    tables = rows(owner_engine, CLINICAL_TABLES_SQL)
    assert {t.relname for t in tables} >= {"patients", "medical_images", "audit_log"}
    assert rls_problems(tables) == []


def test_pk_de_tablas_clinicas_empieza_por_tenant_id(owner_engine):
    bad = rows(
        owner_engine,
        """
        SELECT c.relname FROM pg_constraint k
        JOIN pg_class c ON c.oid = k.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.conkey[1]
        WHERE n.nspname = 'clinical' AND k.contype = 'p' AND a.attname <> 'tenant_id'
        """,
    )
    assert bad == []


def test_fks_entre_tablas_de_tenant_son_compuestas(owner_engine):
    fks = rows(
        owner_engine,
        """
        SELECT k.conname, a.attname AS first_col
        FROM pg_constraint k
        JOIN pg_class c ON c.oid = k.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.conkey[1]
        WHERE n.nspname = 'clinical' AND k.contype = 'f'
        """,
    )
    assert fks, "se esperaban FKs compuestas en clinical"
    assert all(fk.first_col == "tenant_id" for fk in fks), fks


def test_sin_vistas_inseguras_ni_security_definer(owner_engine):
    views = rows(
        owner_engine,
        """
        SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname IN ('clinical', 'control') AND c.relkind IN ('v', 'm')
          AND NOT coalesce('security_invoker=true' = ANY (c.reloptions), false)
        """,
    )
    definers = rows(
        owner_engine,
        """
        SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname IN ('clinical', 'control') AND p.prosecdef
        """,
    )
    assert views == []
    assert definers == []


def test_rol_de_la_app_no_es_dueno_ni_tiene_ddl(owner_engine):
    owned = rows(
        owner_engine,
        """
        SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname IN ('clinical', 'control', 'public')
          AND pg_get_userbyid(c.relowner) = :role
        """,
        role=TEST_APP_ROLE,
    )
    assert owned == []
    for schema in ("clinical", "control", "public"):
        [row] = rows(
            owner_engine,
            "SELECT has_schema_privilege(:role, :schema, 'CREATE') AS can_create",
            role=TEST_APP_ROLE,
            schema=schema,
        )
        assert not row.can_create, f"el rol de la app puede crear objetos en {schema}"


@pytest.mark.parametrize(
    ("table", "privilege", "expected"),
    [
        ("clinical.audit_log", "INSERT", True),
        ("clinical.audit_log", "SELECT", True),
        ("clinical.audit_log", "UPDATE", False),
        ("clinical.audit_log", "DELETE", False),
        ("clinical.audit_log", "TRUNCATE", False),
        ("control.users", "DELETE", False),
        ("control.tenants", "DELETE", False),
        ("clinical.patients", "TRUNCATE", False),
        ("clinical.medical_images", "TRUNCATE", False),
    ],
)
def test_permisos_minimos_de_la_app(owner_engine, table, privilege, expected):
    [row] = rows(
        owner_engine,
        "SELECT has_table_privilege(:role, :table, :privilege) AS allowed",
        role=TEST_APP_ROLE,
        table=table,
        privilege=privilege,
    )
    assert row.allowed is expected


def test_update_de_control_solo_en_columnas_permitidas(owner_engine):
    [row] = rows(
        owner_engine,
        "SELECT has_column_privilege(:role, 'control.users', 'role', 'UPDATE') AS role_upd, "
        "has_column_privilege(:role, 'control.users', 'tenant_id', 'UPDATE') AS tenant_upd, "
        "has_column_privilege(:role, 'control.tenants', 'slug', 'UPDATE') AS slug_upd, "
        "has_column_privilege(:role, 'clinical.medical_images', 'object_path', 'UPDATE') "
        "AS path_upd, "
        "has_column_privilege(:role, 'clinical.patients', 'user_id', 'UPDATE') AS patient_upd",
        role=TEST_APP_ROLE,
    )
    assert not (row.role_upd or row.tenant_upd or row.slug_upd or row.path_upd or row.patient_upd)


def test_roles_de_la_data_api_sin_acceso(owner_engine):
    """En Supabase existen anon/authenticated/service_role; localmente se omite si no existen."""
    present = rows(
        owner_engine,
        "SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated', 'service_role')",
    )
    if not present:
        pytest.skip("Los roles de Supabase no existen en este Postgres")
    for (role,) in present:
        grants = rows(
            owner_engine,
            "SELECT table_schema, table_name FROM information_schema.role_table_grants "
            "WHERE grantee = :role AND table_schema IN ('control', 'clinical', 'legacy')",
            role=role,
        )
        assert grants == [], f"{role} tiene permisos: {grants}"
