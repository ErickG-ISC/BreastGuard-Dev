"""Lectura de imágenes con URL firmada y acceso cruzado (entre tenants y entre pacientes)."""

import uuid

import pytest
from sqlalchemy import text

from tests.helpers import auth_headers, make_image_bytes


def upload(client, user) -> str:
    response = client.post(
        "/api/v1/images/upload",
        files={"file": ("eco.png", make_image_bytes("PNG"), "image/png")},
        headers=auth_headers(user),
    )
    assert response.status_code == 201
    return response.json()["image_id"]


def actions(owner_engine, tenant_id) -> list[str]:
    with owner_engine.connect() as conn:
        return list(
            conn.scalars(
                text("SELECT action FROM clinical.audit_log WHERE tenant_id = :t ORDER BY 1"),
                {"t": tenant_id},
            )
        )


@pytest.fixture
def scenario(tenant_factory, user_factory, b2c_tenant):
    """Paciente B2C con imagen, otra paciente B2C, y una clínica con médico y paciente."""
    clinic = tenant_factory("clinica-a")
    return {
        "maria": user_factory(b2c_tenant, role="patient"),
        "ana": user_factory(b2c_tenant, role="patient"),
        "clinic_doctor": user_factory(clinic, role="doctor"),
        "clinic_patient": user_factory(clinic, role="patient"),
    }


class TestDetalle:
    def test_paciente_obtiene_su_imagen_con_url_firmada(self, client, scenario, storage):
        image_id = upload(client, scenario["maria"])

        response = client.get(f"/api/v1/images/{image_id}", headers=auth_headers(scenario["maria"]))

        assert response.status_code == 200
        body = response.json()
        assert body["url"].startswith("https://storage.test/signed/b2c/images/")
        assert body["url_expires_in"] == 300
        assert "object_path" not in body
        assert storage.signed == [next(iter(storage.objects))]

    def test_otro_tenant_recibe_404_igual_que_inexistente(self, client, scenario):
        image_id = upload(client, scenario["clinic_patient"])
        other_tenant_view = client.get(
            f"/api/v1/images/{image_id}", headers=auth_headers(scenario["maria"])
        )
        missing = client.get(
            f"/api/v1/images/{uuid.uuid4()}", headers=auth_headers(scenario["maria"])
        )
        assert other_tenant_view.status_code == missing.status_code == 404
        assert other_tenant_view.json() == missing.json()

    def test_otra_paciente_del_mismo_tenant_recibe_404(self, client, scenario, storage):
        image_id = upload(client, scenario["maria"])
        response = client.get(f"/api/v1/images/{image_id}", headers=auth_headers(scenario["ana"]))
        assert response.status_code == 404
        assert storage.signed == []

    def test_medico_de_la_clinica_ve_imagenes_de_su_tenant(self, client, scenario):
        image_id = upload(client, scenario["clinic_patient"])
        response = client.get(
            f"/api/v1/images/{image_id}", headers=auth_headers(scenario["clinic_doctor"])
        )
        assert response.status_code == 200

    def test_medico_de_otro_tenant_recibe_404(self, client, scenario):
        image_id = upload(client, scenario["maria"])
        response = client.get(
            f"/api/v1/images/{image_id}", headers=auth_headers(scenario["clinic_doctor"])
        )
        assert response.status_code == 404

    def test_no_firma_rutas_fuera_del_prefijo_del_tenant(
        self, client, scenario, owner_engine, storage
    ):
        image_id = upload(client, scenario["maria"])
        with owner_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE clinical.medical_images SET object_path = 'clinica-a/x.png' "
                    "WHERE id = :i"
                ),
                {"i": image_id},
            )
        response = client.get(f"/api/v1/images/{image_id}", headers=auth_headers(scenario["maria"]))
        assert response.status_code == 404
        assert storage.signed == []

    def test_platform_admin_no_lee_imagenes(self, client, scenario, user_factory):
        image_id = upload(client, scenario["maria"])
        admin = user_factory(role="platform_admin")
        response = client.get(f"/api/v1/images/{image_id}", headers=auth_headers(admin))
        assert response.status_code == 403

    def test_lectura_queda_auditada(self, client, scenario, owner_engine):
        maria = scenario["maria"]
        image_id = upload(client, maria)
        client.get(f"/api/v1/images/{image_id}", headers=auth_headers(maria))
        assert actions(owner_engine, maria.tenant_id) == ["image.read", "image.upload"]


class TestListado:
    def test_paciente_solo_lista_las_suyas(self, client, scenario):
        mine = upload(client, scenario["maria"])
        upload(client, scenario["ana"])
        upload(client, scenario["clinic_patient"])

        response = client.get("/api/v1/images", headers=auth_headers(scenario["maria"]))

        assert [img["id"] for img in response.json()] == [mine]

    def test_medico_lista_solo_su_tenant(self, client, scenario):
        upload(client, scenario["maria"])
        clinic_image = upload(client, scenario["clinic_patient"])
        response = client.get("/api/v1/images", headers=auth_headers(scenario["clinic_doctor"]))
        assert [img["id"] for img in response.json()] == [clinic_image]

    def test_tenant_id_del_cliente_se_ignora(self, client, scenario, b2c_tenant):
        upload(client, scenario["maria"])
        response = client.get(
            "/api/v1/images",
            params={"tenant_id": str(b2c_tenant.id)},
            headers={
                **auth_headers(scenario["clinic_doctor"]),
                "X-Tenant-Id": str(b2c_tenant.id),
            },
        )
        assert response.json() == []
