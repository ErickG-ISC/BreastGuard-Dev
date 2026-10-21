"""CU-01: registro con consentimiento, plan simulado y cuestionario de antecedentes."""

import pytest
from sqlalchemy import text

from backend.app.content.consent import CURRENT_CONSENT_VERSION, current_consent
from backend.app.content.questionnaire import AnswersV1
from backend.app.content.risk_rules import (
    LEVEL_DISCUSS,
    LEVEL_NONE,
    LEVEL_SYMPTOMS,
    evaluate,
)
from tests.helpers import DEFAULT_PASSWORD, auth_headers, registration

API = "/api/v1"
NO_FACTORS = {
    "age": 30,
    "family_history_breast": "none",
    "family_history_ovarian": False,
    "brca_mutation": "no",
    "previous_biopsy": False,
    "hormone_therapy": False,
    "current_symptoms": [],
    "last_checkup": "less_than_1y",
}


def scalar(owner_engine, sql, **params):
    with owner_engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def login(client, email):
    token = client.post(
        f"{API}/auth/token", data={"username": email, "password": DEFAULT_PASSWORD}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestConsentimientoYPlanes:
    def test_texto_vigente_publico(self, client):
        body = client.get(f"{API}/consent/current").json()
        assert body["version"] == CURRENT_CONSENT_VERSION
        assert "No sustituye el criterio ni la consulta médica" in body["text"]
        assert "eliminación" in body["text"]
        assert body["sha256"] == current_consent().sha256

    def test_planes_simulados(self, client):
        plans = client.get(f"{API}/plans").json()
        assert [p["code"] for p in plans] == ["basico", "plus", "premium"]
        assert all(p["simulated"] and "Simulado" in p["price_label"] for p in plans)

    def test_registro_guarda_consentimiento_y_plan(self, client, owner_engine):
        response = client.post(f"{API}/auth/register", json=registration("ana@example.com"))
        assert response.status_code == 201
        user_id = response.json()["id"]
        row = None
        with owner_engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT c.version, c.text_sha256, c.accepted_at, host(c.ip) AS ip, "
                    "s.plan_code, s.status FROM control.consents c "
                    "JOIN control.subscriptions s ON s.user_id = c.user_id WHERE c.user_id = :u"
                ),
                {"u": user_id},
            ).one()
        assert row.version == CURRENT_CONSENT_VERSION
        assert row.text_sha256 == current_consent().sha256
        assert row.accepted_at is not None
        assert row.ip == "198.51.100.7"
        assert (row.plan_code, row.status) == ("basico", "simulada")

    @pytest.mark.parametrize(
        "overrides",
        [
            {"consent_accepted": False},
            {"consent_accepted": None},
            {"consent_version": "2020-01-v0"},
            {"plan_code": "inexistente"},
        ],
    )
    def test_sin_consentimiento_vigente_o_plan_valido_no_se_crea_nada(
        self, client, owner_engine, overrides
    ):
        payload = registration("ana@example.com", **overrides)
        response = client.post(f"{API}/auth/register", json=payload)
        assert response.status_code == 422
        assert scalar(owner_engine, "SELECT count(*) FROM control.users") == 0
        assert scalar(owner_engine, "SELECT count(*) FROM control.consents") == 0

    def test_sin_campo_de_consentimiento_422(self, client):
        payload = registration("ana@example.com")
        del payload["consent_accepted"]
        assert client.post(f"{API}/auth/register", json=payload).status_code == 422

    def test_cambio_de_plan_simulado(self, client):
        client.post(f"{API}/auth/register", json=registration("ana@example.com"))
        headers = login(client, "ana@example.com")
        response = client.put(
            f"{API}/subscription/me", json={"plan_code": "premium"}, headers=headers
        )
        assert response.status_code == 200
        assert response.json()["plan"]["code"] == "premium"
        assert client.get(f"{API}/subscription/me", headers=headers).json()["status"] == "simulada"

    def test_plan_inexistente_422(self, client):
        client.post(f"{API}/auth/register", json=registration("ana@example.com"))
        response = client.put(
            f"{API}/subscription/me",
            json={"plan_code": "oro"},
            headers=login(client, "ana@example.com"),
        )
        assert response.status_code == 422


class TestCuestionario:
    @pytest.fixture
    def patient_headers(self, client):
        client.post(f"{API}/auth/register", json=registration("ana@example.com"))
        return login(client, "ana@example.com")

    def test_definicion_vigente(self, client, patient_headers):
        body = client.get(f"{API}/questionnaire/current", headers=patient_headers).json()
        assert body["version"] == "v1"
        assert {q["id"] for q in body["questions"]} == set(AnswersV1.model_fields)

    def test_envio_guarda_y_devuelve_factores_sin_probabilidad(
        self, client, patient_headers, owner_engine, b2c_tenant
    ):
        answers = {**NO_FACTORS, "age": 45, "family_history_breast": "first_degree"}
        response = client.post(
            f"{API}/questionnaires",
            json={"version": "v1", "answers": answers},
            headers=patient_headers,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["level"] == LEVEL_DISCUSS
        assert {f["code"] for f in body["factors"]} == {"age_screening", "family_first_degree"}
        assert "No sustituye" in body["disclaimer"]
        text_out = (body["message"] + str(body["factors"])).lower()
        assert "%" not in text_out and "probabilidad" not in text_out
        tenant = scalar(owner_engine, "SELECT tenant_id FROM clinical.questionnaires")
        assert tenant == b2c_tenant.id
        actions = scalar(owner_engine, "SELECT array_agg(action) FROM clinical.audit_log")
        assert actions == ["questionnaire.create"]

    def test_ultimo_cuestionario(self, client, patient_headers):
        client.post(
            f"{API}/questionnaires",
            json={"version": "v1", "answers": NO_FACTORS},
            headers=patient_headers,
        )
        body = client.get(f"{API}/questionnaires/latest", headers=patient_headers).json()
        assert body["level"] == LEVEL_NONE

    def test_sin_cuestionario_404(self, client, patient_headers):
        response = client.get(f"{API}/questionnaires/latest", headers=patient_headers)
        assert response.status_code == 404

    @pytest.mark.parametrize(
        "body",
        [
            {"version": "v0", "answers": NO_FACTORS},
            {"version": "v1", "answers": {**NO_FACTORS, "age": 5}},
            {"version": "v1", "answers": {**NO_FACTORS, "extra": 1}},
            {"version": "v1", "answers": {**NO_FACTORS, "current_symptoms": ["otro"]}},
        ],
    )
    def test_respuestas_invalidas_422(self, client, patient_headers, body):
        response = client.post(f"{API}/questionnaires", json=body, headers=patient_headers)
        assert response.status_code == 422

    def test_otra_paciente_no_ve_mi_cuestionario(self, client, patient_headers):
        client.post(
            f"{API}/questionnaires",
            json={"version": "v1", "answers": NO_FACTORS},
            headers=patient_headers,
        )
        client.post(f"{API}/auth/register", json=registration("bea@example.com"))
        other = login(client, "bea@example.com")
        assert client.get(f"{API}/questionnaires/latest", headers=other).status_code == 404

    def test_paciente_de_otro_tenant_no_ve_mi_cuestionario(
        self, client, patient_headers, tenant_factory, user_factory
    ):
        client.post(
            f"{API}/questionnaires",
            json={"version": "v1", "answers": NO_FACTORS},
            headers=patient_headers,
        )
        other = user_factory(tenant_factory("clinica-b"), role="patient")
        response = client.get(f"{API}/questionnaires/latest", headers=auth_headers(other))
        assert response.status_code == 404


class TestReglasDeRiesgo:
    def test_sin_factores(self):
        assert evaluate(AnswersV1(**NO_FACTORS)).level == LEVEL_NONE

    def test_sintomas_tienen_prioridad(self):
        answers = AnswersV1(**{**NO_FACTORS, "current_symptoms": ["lump"], "age": 50})
        evaluation = evaluate(answers)
        assert evaluation.level == LEVEL_SYMPTOMS
        assert "consulta" in evaluation.message

    @pytest.mark.parametrize(
        ("change", "code"),
        [
            ({"age": 40}, "age_screening"),
            ({"family_history_breast": "first_degree"}, "family_first_degree"),
            ({"family_history_ovarian": True}, "family_ovarian"),
            ({"brca_mutation": "yes"}, "brca"),
            ({"previous_biopsy": True}, "previous_biopsy"),
            ({"hormone_therapy": True}, "hormone_therapy"),
            ({"last_checkup": "never"}, "no_recent_checkup"),
        ],
    )
    def test_cada_regla(self, change, code):
        evaluation = evaluate(AnswersV1(**{**NO_FACTORS, **change}))
        assert [f["code"] for f in evaluation.factors] == [code]
        assert evaluation.level == LEVEL_DISCUSS

    def test_mensajes_sin_lenguaje_de_diagnostico(self):
        from backend.app.content.risk_rules import LEVEL_MESSAGES

        for message in LEVEL_MESSAGES.values():
            lowered = message.lower()
            assert "tienes cáncer" not in lowered
            assert "estás sana" not in lowered
            assert "probabilidad" not in lowered
