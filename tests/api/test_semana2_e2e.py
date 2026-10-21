"""Semana 2: flujo completo por API (CU-01 + CU-02) y aislamiento con datos en ambos tenants."""

import io

import numpy as np
from PIL import Image
from sqlalchemy import text

from tests.helpers import DEFAULT_PASSWORD, auth_headers, registration

API = "/api/v1"
ANSWERS = {
    "age": 45,
    "family_history_breast": "first_degree",
    "family_history_ovarian": False,
    "brca_mutation": "no",
    "previous_biopsy": False,
    "hormone_therapy": False,
    "current_symptoms": [],
    "last_checkup": "less_than_1y",
}


def ultrasound_png(seed: int = 3) -> bytes:
    rng = np.random.default_rng(seed)
    array = rng.gamma(2.0, 30.0, (240, 320)).clip(0, 255).astype(np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(array, "L").save(buffer, format="PNG")
    return buffer.getvalue()


def login(client, email) -> dict[str, str]:
    response = client.post(
        f"{API}/auth/token", data={"username": email, "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def post_analysis(client, headers) -> dict:
    response = client.post(
        f"{API}/analyses",
        files={"file": ("eco.png", ultrasound_png(), "image/png")},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def rows(owner_engine, sql, **params):
    with owner_engine.connect() as conn:
        return conn.execute(text(sql), params).all()


def audit(owner_engine, tenant_id):
    return rows(
        owner_engine,
        "SELECT action, actor_id, resource_type, resource_id, host(ip) AS ip "
        "FROM clinical.audit_log WHERE tenant_id = :t ORDER BY occurred_at",
        t=tenant_id,
    )


class TestFlujoCompleto:
    def test_registro_cuestionario_analisis_detalle_historial_y_borrado(
        self, client, storage, owner_engine, b2c_tenant, tenant_factory, user_factory
    ):
        # Otro tenant con una paciente y un análisis propio: nunca debe verse afectado
        clinic = tenant_factory("clinica-b")
        other = user_factory(clinic, role="patient")
        other_analysis = post_analysis(client, auth_headers(other))
        other_objects = {k: v for k, v in storage.objects.items() if k.startswith("clinica-b/")}
        other_audit = audit(owner_engine, clinic.id)
        assert len(other_objects) == 2

        # 1) Registro con consentimiento y plan, luego login
        registered = client.post(f"{API}/auth/register", json=registration("ana@example.com"))
        assert registered.status_code == 201
        user_id = registered.json()["id"]
        assert registered.json()["tenant_id"] == str(b2c_tenant.id)
        headers = login(client, "ana@example.com")
        me = client.get(f"{API}/auth/me", headers=headers).json()
        assert me["role"] == "patient" and me["tenant_slug"] == "b2c"
        assert client.get(f"{API}/subscription/me", headers=headers).json()["plan"]["code"] == (
            "basico"
        )

        # 2) Cuestionario
        questionnaire = client.post(
            f"{API}/questionnaires", json={"version": "v1", "answers": ANSWERS}, headers=headers
        )
        assert questionnaire.status_code == 201
        assert "disclaimer" in questionnaire.json()

        # 3) Subida de la ecografía sintética en escala de grises
        created = post_analysis(client, headers)
        analysis_id = created["id"]
        assert created["status"] == "completed"
        b2c_objects = {k for k in storage.objects if k.startswith("b2c/")}
        assert {p.split("/")[1] for p in b2c_objects} == {"images", "heatmaps"}
        image_path = next(p for p in b2c_objects if "/images/" in p)
        heatmap_path = next(p for p in b2c_objects if "/heatmaps/" in p)
        assert storage.objects[image_path] and storage.objects[heatmap_path]
        assert (
            rows(
                owner_engine,
                "SELECT tenant_id FROM clinical.analyses WHERE id = :a",
                a=analysis_id,
            )[0].tenant_id
            == b2c_tenant.id
        )

        # 4) Detalle con URLs firmadas de corta duración, sin rutas internas ni URLs públicas
        storage.signed.clear()
        detail = client.get(f"{API}/analyses/{analysis_id}", headers=headers)
        assert detail.status_code == 200
        body = detail.json()
        assert body["image_url"].startswith(f"https://storage.test/signed/{image_path}")
        assert body["heatmap_url"].startswith(f"https://storage.test/signed/{heatmap_path}")
        assert 0 < body["url_expires_in"] <= 3600
        assert set(storage.signed) == {image_path, heatmap_path}
        assert "object_path" not in body and "heatmap_path" not in body

        # 5) Historial
        history = client.get(f"{API}/analyses", headers=headers).json()
        assert history["total"] == 1 and [i["id"] for i in history["items"]] == [analysis_id]
        assert other_analysis["id"] not in [i["id"] for i in history["items"]]

        # 6) Borrado: archivos y filas desaparecen
        assert client.delete(f"{API}/analyses/{analysis_id}", headers=headers).status_code == 204
        assert image_path not in storage.objects and heatmap_path not in storage.objects
        assert {image_path, heatmap_path} <= set(storage.removed)
        assert (
            rows(owner_engine, "SELECT 1 FROM clinical.analyses WHERE id = :a", a=analysis_id) == []
        )
        assert (
            rows(
                owner_engine,
                "SELECT 1 FROM clinical.medical_images WHERE patient_id IN "
                "(SELECT id FROM clinical.patients WHERE user_id = :u)",
                u=user_id,
            )
            == []
        )
        gone = client.get(f"{API}/analyses/{analysis_id}", headers=headers)
        assert gone.status_code == 404
        assert client.get(f"{API}/analyses", headers=headers).json()["total"] == 0

        # 7) Auditoría de cada paso, a nombre de la paciente y con IP
        entries = audit(owner_engine, b2c_tenant.id)
        assert [e.action for e in entries] == [
            "questionnaire.create",
            "analysis.create",
            "analysis.read",  # lectura interna de la respuesta del POST
            "analysis.read",
            "analysis.list",
            "analysis.delete",
            "analysis.denied",  # GET tras el borrado
            "analysis.list",
        ]
        assert {str(e.actor_id) for e in entries} == {user_id}
        assert all(e.ip == "198.51.100.7" for e in entries)
        assert {e.resource_type for e in entries} <= {"analysis", "questionnaire"}

        # 8) El otro tenant nunca vio ni perdió nada
        assert audit(owner_engine, clinic.id) == other_audit
        assert {k: v for k, v in storage.objects.items() if k.startswith("clinica-b/")} == (
            other_objects
        )
        still = client.get(f"{API}/analyses/{other_analysis['id']}", headers=auth_headers(other))
        assert still.status_code == 200


class TestAislamientoConDatosEnAmbosTenants:
    def test_listado_cuestionario_y_suscripcion_de_a_no_reflejan_nada_de_b(
        self, client, b2c_tenant, tenant_factory, user_factory
    ):
        clinic = tenant_factory("clinica-b")
        in_b = user_factory(clinic, role="patient")
        in_a = user_factory(b2c_tenant, role="patient")

        # Datos en B: tres análisis, un cuestionario (edad 61) y un plan premium
        b_ids = {post_analysis(client, auth_headers(in_b))["id"] for _ in range(3)}
        client.post(
            f"{API}/questionnaires",
            json={"version": "v1", "answers": {**ANSWERS, "age": 61}},
            headers=auth_headers(in_b),
        )
        client.put(
            f"{API}/subscription/me", json={"plan_code": "premium"}, headers=auth_headers(in_b)
        )

        # A sin datos: todo vacío, sin reflejo de B
        empty = client.get(f"{API}/analyses", headers=auth_headers(in_a)).json()
        assert empty["total"] == 0 and empty["items"] == []
        assert (
            client.get(f"{API}/questionnaires/latest", headers=auth_headers(in_a)).status_code
            == 404
        )
        assert client.get(f"{API}/subscription/me", headers=auth_headers(in_a)).status_code == 404

        # A con sus propios datos: solo ve los suyos, aunque B tenga más y más recientes
        a_analysis = post_analysis(client, auth_headers(in_a))
        a_questionnaire = client.post(
            f"{API}/questionnaires",
            json={"version": "v1", "answers": {**ANSWERS, "age": 33}},
            headers=auth_headers(in_a),
        ).json()
        client.put(f"{API}/subscription/me", json={"plan_code": "plus"}, headers=auth_headers(in_a))

        page = client.get(
            f"{API}/analyses", params={"limit": 50}, headers=auth_headers(in_a)
        ).json()
        assert [i["id"] for i in page["items"]] == [a_analysis["id"]] and page["total"] == 1
        assert not b_ids & {i["id"] for i in page["items"]}
        latest = client.get(f"{API}/questionnaires/latest", headers=auth_headers(in_a)).json()
        assert latest["id"] == a_questionnaire["id"]
        assert (
            client.get(f"{API}/subscription/me", headers=auth_headers(in_a)).json()["plan"]["code"]
            == "plus"
        )

        # Y B conserva lo suyo
        b_page = client.get(
            f"{API}/analyses", params={"limit": 50}, headers=auth_headers(in_b)
        ).json()
        assert {i["id"] for i in b_page["items"]} == b_ids
        assert (
            client.get(f"{API}/subscription/me", headers=auth_headers(in_b)).json()["plan"]["code"]
            == "premium"
        )
