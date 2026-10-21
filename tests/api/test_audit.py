"""CU-13: el tenant_admin ve el log de accesos de su tenant y solo de su tenant."""

from datetime import UTC, datetime, timedelta

import pytest

from tests.helpers import auth_headers, make_image_bytes

AUDIT_URL = "/api/v1/audit"


def upload(client, user) -> str:
    response = client.post(
        "/api/v1/images/upload",
        files={"file": ("eco.png", make_image_bytes("PNG"), "image/png")},
        headers=auth_headers(user),
    )
    return response.json()["image_id"]


@pytest.fixture
def clinics(tenant_factory, user_factory):
    data = {}
    for slug in ("clinica-a", "clinica-b"):
        tenant = tenant_factory(slug)
        data[slug] = {
            "admin": user_factory(tenant, role="tenant_admin"),
            "doctor": user_factory(tenant, role="doctor"),
            "patient": user_factory(tenant, role="patient"),
        }
    return data["clinica-a"], data["clinica-b"]


def test_admin_ve_quien_accedio_a_que(client, clinics):
    a, _ = clinics
    image_id = upload(client, a["patient"])
    client.get(f"/api/v1/images/{image_id}", headers=auth_headers(a["doctor"]))

    response = client.get(AUDIT_URL, headers=auth_headers(a["admin"]))

    assert response.status_code == 200
    entries = response.json()
    read = next(e for e in entries if e["action"] == "image.read")
    assert read["actor_id"] == str(a["doctor"].id)
    assert read["actor_role"] == "doctor"
    assert read["resource_id"] == image_id
    assert read["ip"] == "198.51.100.7"
    assert {"image.upload", "image.read"} <= {e["action"] for e in entries}


def test_el_log_de_a_no_muestra_actividad_de_b(client, clinics):
    a, b = clinics
    upload(client, b["patient"])
    b_image = upload(client, b["patient"])
    client.get(f"/api/v1/images/{b_image}", headers=auth_headers(b["doctor"]))

    entries = client.get(AUDIT_URL, headers=auth_headers(a["admin"])).json()

    b_actors = {str(b[k].id) for k in ("admin", "doctor", "patient")}
    assert not any(e["actor_id"] in b_actors for e in entries)
    assert all(e["resource_id"] != b_image for e in entries)


@pytest.mark.parametrize("role", ["doctor", "patient"])
def test_solo_tenant_admin(client, clinics, role):
    a, _ = clinics
    assert client.get(AUDIT_URL, headers=auth_headers(a[role])).status_code == 403


def test_platform_admin_no_lee_logs_clinicos(client, user_factory):
    admin = user_factory(role="platform_admin")
    assert client.get(AUDIT_URL, headers=auth_headers(admin)).status_code == 403


def test_filtros_por_usuario_y_fecha(client, clinics):
    a, _ = clinics
    image_id = upload(client, a["patient"])
    client.get(f"/api/v1/images/{image_id}", headers=auth_headers(a["doctor"]))
    headers = auth_headers(a["admin"])

    by_doctor = client.get(AUDIT_URL, params={"actor_id": str(a["doctor"].id)}, headers=headers)
    assert {e["actor_id"] for e in by_doctor.json()} == {str(a["doctor"].id)}

    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert client.get(AUDIT_URL, params={"from": future}, headers=headers).json() == []
    past = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    assert client.get(AUDIT_URL, params={"from": past}, headers=headers).json() != []


def test_consultar_el_log_queda_auditado(client, clinics):
    a, _ = clinics
    headers = auth_headers(a["admin"])
    client.get(AUDIT_URL, headers=headers)
    entries = client.get(AUDIT_URL, headers=headers).json()
    assert any(e["action"] == "audit.read" and e["actor_id"] == str(a["admin"].id) for e in entries)


def test_limite_invalido_422(client, clinics):
    a, _ = clinics
    response = client.get(AUDIT_URL, params={"limit": 1000}, headers=auth_headers(a["admin"]))
    assert response.status_code == 422
