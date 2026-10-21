"""CU-01 a nivel de base: política de paciente en cuestionarios y permisos sobre control."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from backend.app.db import TenantContext, new_session
from backend.app.services import auth as auth_service
from tests.helpers import DEFAULT_PASSWORD, registration, tenant_session
from tests.pgtest import TEST_APP_ROLE


def insert_questionnaire(session, patient_id):
    session.execute(
        text(
            "INSERT INTO clinical.questionnaires (id, patient_id, version, answers, risk_factors, "
            "summary_level) VALUES (:id, :p, 'v1', '{}'::jsonb, '[]'::jsonb, 'sin_factores')"
        ),
        {"id": uuid.uuid4(), "p": patient_id},
    )


class TestPoliticaDePacienteEnCuestionarios:
    def test_no_inserta_en_la_ficha_de_otra_paciente(self, b2c_tenant, user_factory):
        ana = user_factory(b2c_tenant, role="patient")
        bea = user_factory(b2c_tenant, role="patient")
        with tenant_session(ana) as session:
            insert_questionnaire(session, ana.patient_id)  # control positivo: la suya sí
            session.flush()
            with pytest.raises(DBAPIError, match="row-level"):
                insert_questionnaire(session, bea.patient_id)

    def test_no_ve_cuestionarios_de_otra_paciente(self, b2c_tenant, user_factory, owner_engine):
        ana = user_factory(b2c_tenant, role="patient")
        bea = user_factory(b2c_tenant, role="patient")
        with tenant_session(bea) as session:
            insert_questionnaire(session, bea.patient_id)
            session.commit()
        with tenant_session(ana) as session:
            seen = session.execute(text("SELECT count(*) FROM clinical.questionnaires")).scalar()
        assert seen == 0

    @pytest.mark.parametrize("role", ["", "platform_admin", "otro"])
    def test_rol_nulo_o_desconocido_no_ve_ni_inserta(self, b2c_tenant, user_factory, role):
        ana = user_factory(b2c_tenant, role="patient")
        with tenant_session(ana) as session:
            insert_questionnaire(session, ana.patient_id)
            session.commit()
        ctx = TenantContext(b2c_tenant.id, ana.id, role)
        with new_session(ctx) as session:
            assert (
                session.execute(text("SELECT count(*) FROM clinical.questionnaires")).scalar() == 0
            )
            with pytest.raises(DBAPIError, match="row-level"):
                insert_questionnaire(session, ana.patient_id)

    @pytest.mark.parametrize(
        "sql",
        [
            "UPDATE clinical.questionnaires SET summary_level = 'x'",
            "DELETE FROM clinical.questionnaires",
        ],
    )
    def test_historial_inmutable(self, b2c_tenant, user_factory, sql):
        ana = user_factory(b2c_tenant, role="patient")
        with tenant_session(ana) as session, pytest.raises(DBAPIError, match="permission denied"):
            session.execute(text(sql))


@pytest.mark.parametrize(
    ("table", "privilege", "column", "expected"),
    [
        ("control.consents", "UPDATE", None, False),
        ("control.consents", "DELETE", None, False),
        ("control.consents", "INSERT", None, True),
        ("control.subscriptions", "DELETE", None, False),
        ("control.subscriptions", "UPDATE", "user_id", False),
        ("control.subscriptions", "UPDATE", "status", False),
        ("control.subscriptions", "UPDATE", "plan_code", True),
        ("control.plans", "INSERT", None, False),
        ("control.plans", "UPDATE", None, False),
    ],
)
def test_permisos_de_la_app_en_control(owner_engine, table, privilege, column, expected):
    with owner_engine.connect() as conn:
        if column:
            allowed = conn.execute(
                text("SELECT has_column_privilege(:r, :t, :c, :p)"),
                {"r": TEST_APP_ROLE, "t": table, "c": column, "p": privilege},
            ).scalar()
        else:
            allowed = conn.execute(
                text("SELECT has_table_privilege(:r, :t, :p)"),
                {"r": TEST_APP_ROLE, "t": table, "p": privilege},
            ).scalar()
    assert allowed is expected


def test_registro_atomico_si_falla_la_ficha(client, owner_engine, monkeypatch):
    """Un fallo DESPUÉS de insertar cuenta, consentimiento y suscripción no deja nada."""

    def broken_context(*args, **kwargs):
        raise RuntimeError("fallo simulado al crear la ficha")

    monkeypatch.setattr(auth_service, "set_transaction_context", broken_context)
    with pytest.raises(RuntimeError, match="fallo simulado"):
        client.post("/api/v1/auth/register", json=registration("ana@example.com"))
    with owner_engine.connect() as conn:
        for table in ("control.users", "control.consents", "control.subscriptions"):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0


def test_cambio_de_plan_de_a_no_toca_a_b(client):
    for email in ("ana@example.com", "bea@example.com"):
        client.post("/api/v1/auth/register", json=registration(email))

    def headers(email):
        token = client.post(
            "/api/v1/auth/token", data={"username": email, "password": DEFAULT_PASSWORD}
        ).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    client.put(
        "/api/v1/subscription/me",
        json={"plan_code": "premium"},
        headers=headers("ana@example.com"),
    )
    bea = client.get("/api/v1/subscription/me", headers=headers("bea@example.com")).json()
    assert bea["plan"]["code"] == "basico"


def test_hash_de_consentimiento_distinto_422(client, owner_engine):
    payload = registration("ana@example.com", consent_sha256="0" * 64)
    assert client.post("/api/v1/auth/register", json=payload).status_code == 422
    with owner_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM control.users")).scalar() == 0
