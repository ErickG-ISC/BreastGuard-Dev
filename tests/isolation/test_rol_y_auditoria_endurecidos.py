"""(a) y (e) que faltaban: el rol de la app no puede evadir RLS y audit_log es de solo inserción.

Complementa test_db_role.py y TestAuditoria de test_rls.py: aquí se comprueba, con el dueño, que
los intentos de alterar o borrar el log no cambian ni una fila, y que el rol no puede apagar RLS.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from backend.app.db import get_engine, new_session
from tests.helpers import tenant_session
from tests.pgtest import TEST_APP_ROLE

pytestmark = pytest.mark.usefixtures("database")


class TestRolDeLaApp:
    def test_sin_atributos_de_privilegio(self):
        with get_engine().connect() as conn:
            row = conn.execute(
                text(
                    "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolreplication, "
                    "rolinherit FROM pg_roles WHERE rolname = current_user"
                )
            ).one()
        assert not (
            row.rolsuper
            or row.rolbypassrls
            or row.rolcreaterole
            or row.rolcreatedb
            or row.rolreplication
        )

    def test_no_es_miembro_del_dueno_ni_de_roles_con_bypass(self, owner_engine):
        with owner_engine.connect() as conn:
            members = conn.scalars(
                text(
                    "SELECT r.rolname FROM pg_auth_members m "
                    "JOIN pg_roles r ON r.oid = m.roleid "
                    "JOIN pg_roles u ON u.oid = m.member WHERE u.rolname = :app "
                    "AND (r.rolsuper OR r.rolbypassrls OR r.rolname = current_user "
                    "OR r.rolname = (SELECT pg_get_userbyid(relowner) FROM pg_class "
                    "WHERE oid = 'clinical.patients'::regclass))"
                ),
                {"app": TEST_APP_ROLE},
            ).all()
        assert members == []

    def test_no_puede_apagar_row_security(self):
        """`SET row_security = off` no salta RLS: la consulta falla en lugar de ver todo."""
        with new_session() as session:
            session.execute(text("SET LOCAL row_security = off"))
            with pytest.raises(DBAPIError, match="row-level security"):
                session.execute(text("SELECT count(*) FROM clinical.patients"))

    @pytest.mark.parametrize(
        "sql",
        [
            "ALTER TABLE clinical.patients NO FORCE ROW LEVEL SECURITY",
            "ALTER TABLE clinical.patients DISABLE ROW LEVEL SECURITY",
            "DROP POLICY tenant_isolation ON clinical.patients",
            "SET ROLE postgres",
            "CREATE TABLE clinical.intruso (id int)",
        ],
    )
    def test_no_puede_cambiar_politicas_ni_asumir_otro_rol(self, sql):
        with new_session() as session, pytest.raises(DBAPIError, match="must be owner|permission"):
            session.execute(text(sql))


class TestAuditLogSoloInsercion:
    @pytest.fixture
    def with_entry(self, tenant_factory, user_factory, owner_engine):
        tenant = tenant_factory("clinica-a")
        admin = user_factory(tenant, role="tenant_admin")
        entry_id = uuid.uuid4()
        with tenant_session(admin) as session:
            session.execute(
                text(
                    "INSERT INTO clinical.audit_log (id, actor_id, actor_role, action) "
                    "VALUES (:id, :actor, 'tenant_admin', 'prueba')"
                ),
                {"id": entry_id, "actor": admin.id},
            )
            session.commit()
        return admin, entry_id

    @pytest.mark.parametrize(
        "sql",
        [
            "UPDATE clinical.audit_log SET action = 'borrado'",
            "UPDATE clinical.audit_log SET actor_id = gen_random_uuid() WHERE id = :id",
            "DELETE FROM clinical.audit_log",
            "DELETE FROM clinical.audit_log WHERE id = :id",
            "TRUNCATE clinical.audit_log",
            "ALTER TABLE clinical.audit_log DISABLE ROW LEVEL SECURITY",
        ],
    )
    def test_ni_el_tenant_admin_modifica_ni_borra_el_log(self, with_entry, owner_engine, sql):
        admin, entry_id = with_entry
        with owner_engine.connect() as conn:
            before = conn.execute(text("SELECT to_jsonb(a) FROM clinical.audit_log a")).all()

        with tenant_session(admin) as session:
            with pytest.raises(DBAPIError, match="permission denied|must be owner"):
                session.execute(text(sql), {"id": entry_id})

        with owner_engine.connect() as conn:
            after = conn.execute(text("SELECT to_jsonb(a) FROM clinical.audit_log a")).all()
        assert len(before) == 1
        assert after == before

    def test_el_tenant_admin_si_puede_insertar_y_leer_su_log(self, with_entry):
        admin, entry_id = with_entry
        with tenant_session(admin) as session:
            ids = set(session.scalars(text("SELECT id FROM clinical.audit_log")))
        assert entry_id in ids

    def test_el_admin_de_otro_tenant_no_ve_ni_toca_el_log(
        self, with_entry, tenant_factory, user_factory, owner_engine
    ):
        _, entry_id = with_entry
        other_admin = user_factory(tenant_factory("clinica-b"), role="tenant_admin")
        with tenant_session(other_admin) as session:
            assert session.execute(text("SELECT count(*) FROM clinical.audit_log")).scalar() == 0
        with owner_engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT count(*) FROM clinical.audit_log WHERE id = :id"), {"id": entry_id}
                ).scalar_one()
                == 1
            )
