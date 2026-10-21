"""Huecos señalados por la revisión de la batería de aislamiento."""

import threading
import uuid

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import text

from backend.app.api.deps import get_control_db, get_tenant_db
from backend.app.main import app
from backend.app.services.auth import AuthContext
from tests.api.test_acceso_cruzado_endpoints import PROTECTED
from tests.helpers import tenant_session
from tests.isolation.catalogo import CLINICAL_TABLES_SQL, rls_problems
from tests.isolation.test_rls_por_tabla import MODEL_TABLES, seed
from tests.pgtest import TEST_APP_ROLE

PUBLIC_ROUTES = {
    ("GET", "/"),
    ("GET", "/api/v1/health"),
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/token"),
}


def test_todo_endpoint_es_publico_declarado_o_esta_en_la_matriz_cruzada():
    """Un endpoint nuevo sin pruebas de 401/403/acceso cruzado hace fallar esta prueba."""
    uncovered = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods - {"HEAD", "OPTIONS"}:
            if (method, route.path) in PUBLIC_ROUTES:
                continue
            covered = any(
                m == method and route.path_regex.match(path) for m, path, _ in PROTECTED.values()
            )
            if not covered:
                uncovered.append(f"{method} {route.path}")
    assert uncovered == []


class TestSesionesDeLaApp:
    def test_get_tenant_db_entrega_app_user_con_el_contexto_del_jwt(self, database, tenant_factory):
        tenant = tenant_factory("clinica-a")
        auth = AuthContext(
            user_id=uuid.uuid4(), tenant_id=tenant.id, tenant_slug=tenant.slug, role="doctor"
        )
        generator = get_tenant_db(auth)
        session = next(generator)
        try:
            row = session.execute(
                text(
                    "SELECT current_user AS who, "
                    "current_setting('app.tenant_id', true) AS tenant_ctx, "
                    "current_setting('app.role', true) AS role_ctx"
                )
            ).one()
        finally:
            generator.close()
        assert row.who == TEST_APP_ROLE
        assert row.tenant_ctx == str(tenant.id)
        assert row.role_ctx == "doctor"

    def test_get_control_db_entrega_app_user_sin_contexto(self, database):
        generator = get_control_db()
        session = next(generator)
        try:
            row = session.execute(
                text(
                    "SELECT current_user AS who, "
                    "current_setting('app.tenant_id', true) AS tenant_ctx"
                )
            ).one()
        finally:
            generator.close()
        assert row.who == TEST_APP_ROLE
        assert row.tenant_ctx in (None, "")


def test_rol_de_la_app_noinherit_y_sin_membresias(owner_engine):
    with owner_engine.connect() as conn:
        role = conn.execute(
            text("SELECT rolinherit FROM pg_roles WHERE rolname = :r"), {"r": TEST_APP_ROLE}
        ).one()
        memberships = conn.execute(
            text(
                "SELECT r.rolname FROM pg_auth_members m "
                "JOIN pg_roles r ON r.oid = m.roleid "
                "JOIN pg_roles u ON u.oid = m.member WHERE u.rolname = :r"
            ),
            {"r": TEST_APP_ROLE},
        ).all()
    assert role.rolinherit is False
    assert memberships == []


@pytest.mark.parametrize("actor_role", ["doctor", "patient"])
@pytest.mark.parametrize("table", MODEL_TABLES)
def test_doctor_y_paciente_de_a_no_ven_filas_de_b(
    owner_engine, tenant_factory, user_factory, table, actor_role
):
    a, b = tenant_factory("clinica-a"), tenant_factory("clinica-b")
    admin_b = user_factory(b, role="tenant_admin")
    actor = user_factory(a, role=actor_role)
    seed(owner_engine, table, b, admin_b)
    with owner_engine.connect() as conn:
        seeded = conn.execute(
            text(f"SELECT count(*) FROM clinical.{table} WHERE tenant_id = :b"), {"b": b.id}
        ).scalar_one()
    assert seeded >= 1  # el 0 de abajo no es trivial

    with tenant_session(actor) as session:
        visible = session.execute(
            text(f"SELECT count(*) FROM clinical.{table} WHERE tenant_id = :b"), {"b": b.id}
        ).scalar_one()
    assert visible == 0


def test_el_catalogo_rechaza_una_politica_con_or_true(owner_engine):
    with owner_engine.connect() as conn:
        transaction = conn.begin()
        try:
            conn.execute(
                text(
                    "CREATE TABLE clinical.tmp_or_true (tenant_id uuid NOT NULL, id uuid, "
                    "PRIMARY KEY (tenant_id, id))"
                )
            )
            conn.execute(text("ALTER TABLE clinical.tmp_or_true ENABLE ROW LEVEL SECURITY"))
            conn.execute(text("ALTER TABLE clinical.tmp_or_true FORCE ROW LEVEL SECURITY"))
            conn.execute(
                text(
                    "CREATE POLICY tenant_isolation ON clinical.tmp_or_true FOR ALL "
                    "USING (tenant_id = (SELECT clinical.current_tenant_id()) OR true) "
                    "WITH CHECK (tenant_id = (SELECT clinical.current_tenant_id()) OR true)"
                )
            )
            problems = rls_problems(conn.execute(text(CLINICAL_TABLES_SQL)).all())
        finally:
            transaction.rollback()
    assert any("tmp_or_true" in p for p in problems)


def test_contexto_no_se_cruza_entre_peticiones_concurrentes(tenant_factory, user_factory):
    """Dos hilos alternan sesiones de A y B sobre el mismo pool: nadie ve filas del otro."""
    users = {}
    for slug in ("clinica-a", "clinica-b"):
        tenant = tenant_factory(slug)
        users[slug] = (tenant, user_factory(tenant, role="doctor"))
        user_factory(tenant, role="patient")  # una ficha por tenant
    errors: list[str] = []

    def worker(own: str, other: str) -> None:
        own_tenant, actor = users[own]
        other_tenant, _ = users[other]
        try:
            for _ in range(40):
                with tenant_session(actor) as session:
                    mine = session.execute(
                        text("SELECT count(*) FROM clinical.patients WHERE tenant_id = :t"),
                        {"t": own_tenant.id},
                    ).scalar_one()
                    theirs = session.execute(
                        text("SELECT count(*) FROM clinical.patients WHERE tenant_id = :t"),
                        {"t": other_tenant.id},
                    ).scalar_one()
                if mine != 1 or theirs != 0:
                    errors.append(f"{own}: propias={mine} ajenas={theirs}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{own}: {type(exc).__name__}")

    threads = [
        threading.Thread(target=worker, args=("clinica-a", "clinica-b")),
        threading.Thread(target=worker, args=("clinica-b", "clinica-a")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
