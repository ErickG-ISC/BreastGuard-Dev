"""Las tablas de la semana 3 no son accesibles por la Data API de Supabase.

La prueba genérica de test_catalog.py mira `role_table_grants` (solo permisos de tabla). Aquí se
exige además que ningún permiso, ni siquiera de columna, llegue a anon/authenticated/service_role.
"""

import pytest
from sqlalchemy import text

from tests.pgtest import ensure_supabase_api_roles

pytestmark = pytest.mark.usefixtures("database")

TABLES = [
    "control.reminders",
    "control.reminder_notices",
    "clinical.self_exams",
    "clinical.symptom_entries",
]
API_ROLES = ["anon", "authenticated", "service_role"]
PRIVILEGES = ["SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"]


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize("role", API_ROLES)
def test_roles_de_la_data_api_sin_privilegios(owner_engine, role, table):
    ensure_supabase_api_roles()
    with owner_engine.connect() as conn:
        assert conn.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar_one()
        for privilege in PRIVILEGES:
            assert not conn.execute(
                text("SELECT has_table_privilege(:r, :t, :p)"),
                {"r": role, "t": table, "p": privilege},
            ).scalar_one(), f"{role} tiene {privilege} sobre {table}"
        for privilege in ("SELECT", "INSERT", "UPDATE", "REFERENCES"):
            assert not conn.execute(
                text("SELECT has_any_column_privilege(:r, :t, :p)"),
                {"r": role, "t": table, "p": privilege},
            ).scalar_one(), f"{role} tiene {privilege} en alguna columna de {table}"


@pytest.mark.parametrize("table", TABLES)
def test_public_sin_privilegios(owner_engine, table):
    with owner_engine.connect() as conn:
        grants = conn.execute(
            text(
                "SELECT count(*) FROM information_schema.role_table_grants "
                "WHERE grantee = 'PUBLIC' AND table_schema || '.' || table_name = :t"
            ),
            {"t": table},
        ).scalar_one()
    assert grants == 0
