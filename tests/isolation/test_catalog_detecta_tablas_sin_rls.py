"""(d) La prueba de catálogo no pasa en falso: la misma consulta detecta tablas mal protegidas.

Se crea como dueño una tabla temporal en `clinical` dentro de una transacción que siempre
termina en rollback (DDL transaccional de Postgres), así que no queda rastro.
"""

import pytest
from sqlalchemy import text

from tests.isolation.catalogo import CLINICAL_TABLES_SQL, rls_problems

pytestmark = pytest.mark.usefixtures("database")

TENANT = "(SELECT clinical.current_tenant_id())"
BASE = (
    "CREATE TABLE clinical.tmp_sin_proteger (tenant_id uuid NOT NULL "
    "DEFAULT clinical.current_tenant_id(), id uuid NOT NULL, PRIMARY KEY (tenant_id, id))"
)
POLICY = (
    f"CREATE POLICY tenant_isolation ON clinical.tmp_sin_proteger AS PERMISSIVE FOR ALL "
    f"USING (tenant_id = {TENANT}) WITH CHECK (tenant_id = {TENANT})"
)
ROLE_POLICY = (
    "CREATE POLICY tmp_by_role ON clinical.tmp_sin_proteger AS RESTRICTIVE FOR ALL "
    "USING (clinical.current_app_role() = 'patient') "
    "WITH CHECK (clinical.current_app_role() = 'patient')"
)
ENABLE = "ALTER TABLE clinical.tmp_sin_proteger ENABLE ROW LEVEL SECURITY"
FORCE = "ALTER TABLE clinical.tmp_sin_proteger FORCE ROW LEVEL SECURITY"

CASES = {
    "sin_rls": ([BASE], "sin RLS habilitado"),
    "rls_sin_forzar": ([BASE, ENABLE, POLICY], "sin RLS forzado"),
    "rls_forzado_sin_politica": ([BASE, ENABLE, FORCE], "sin políticas"),
    "politica_sin_with_check": (
        [
            BASE,
            ENABLE,
            FORCE,
            f"CREATE POLICY tenant_isolation ON clinical.tmp_sin_proteger "
            f"USING (tenant_id = {TENANT})",
        ],
        "sin tenant_isolation con USING y WITH CHECK",
    ),
    # Solo tenant_isolation: todo el personal del tenant vería la tabla
    "solo_tenant_isolation": ([BASE, ENABLE, FORCE, POLICY], "sin política RESTRICTIVE por rol"),
    "restrictiva_sin_with_check": (
        [BASE, ENABLE, FORCE, POLICY, ROLE_POLICY.split(" WITH CHECK")[0]],
        "sin política RESTRICTIVE por rol",
    ),
    "sin_tenant_id": (
        [
            "CREATE TABLE clinical.tmp_sin_proteger (id uuid PRIMARY KEY)",
            ENABLE,
            FORCE,
            POLICY.replace("tenant_id = " + TENANT, "true"),
        ],
        "sin tenant_id NOT NULL",
    ),
}


def problems_with(owner_engine, statements: list[str]) -> list[str]:
    """Ejecuta el DDL como dueño, corre la consulta del catálogo y revierte todo."""
    with owner_engine.connect() as conn:
        transaction = conn.begin()
        try:
            for sql in statements:
                conn.execute(text(sql))
            return rls_problems(conn.execute(text(CLINICAL_TABLES_SQL)).all())
        finally:
            transaction.rollback()


@pytest.mark.parametrize("case", CASES)
def test_el_catalogo_detecta_una_tabla_clinica_mal_protegida(owner_engine, case):
    statements, expected = CASES[case]
    problems = problems_with(owner_engine, statements)
    assert any("tmp_sin_proteger" in p and expected in p for p in problems), problems


def test_una_tabla_bien_protegida_no_genera_problemas(owner_engine):
    """Control positivo: el detector no es un 'siempre falla'."""
    assert problems_with(owner_engine, [BASE, ENABLE, FORCE, POLICY, ROLE_POLICY]) == []


def test_la_tabla_temporal_no_sobrevive_al_rollback(owner_engine):
    problems_with(owner_engine, [BASE])
    with owner_engine.connect() as conn:
        names = set(
            conn.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname = 'clinical'"))
        )
    assert "tmp_sin_proteger" not in names
