"""CU-02: subir y analizar, historial, detalle con URLs firmadas y eliminación."""

import io
import uuid

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import text

from backend.app.ml.service import InferenceService
from backend.app.ml.settings import MLSettings
from tests.helpers import auth_headers

URL = "/api/v1/analyses"


def ultrasound_png(size=(320, 240)) -> bytes:
    rng = np.random.default_rng(5)
    image = Image.fromarray(rng.gamma(2.0, 30.0, size[::-1]).clip(0, 255).astype(np.uint8), "L")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def upload(client, user, content: bytes | None = None, name="eco.png", mime="image/png"):
    return client.post(
        URL,
        files={"file": (name, content or ultrasound_png(), mime)},
        headers=auth_headers(user),
    )


def rows(owner_engine, sql, **params):
    with owner_engine.connect() as conn:
        return conn.execute(text(sql), params).all()


@pytest.fixture
def ana(user_factory, b2c_tenant):
    return user_factory(b2c_tenant, role="patient")


class TestCrear:
    def test_analiza_guarda_y_devuelve_urls_firmadas(self, client, ana, storage, owner_engine):
        response = upload(client, ana)

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "completed"
        assert body["predicted_class"] == "normal"
        assert body["model_version"] == "fake-3c-1"
        assert body["report"]["disclaimer"].startswith("Herramienta de apoyo")
        assert "demo_notice" in body["report"]
        assert body["image_url"].startswith("https://storage.test/signed/b2c/images/")
        assert body["heatmap_url"].startswith("https://storage.test/signed/b2c/heatmaps/")
        assert "heatmap_path" not in body and "object_path" not in body
        assert sorted(p.split("/")[1] for p in storage.objects) == ["heatmaps", "images"]
        [analysis] = rows(owner_engine, "SELECT tenant_id, patient_id FROM clinical.analyses")
        assert analysis.tenant_id == ana.tenant_id and analysis.patient_id == ana.patient_id
        actions = [r.action for r in rows(owner_engine, "SELECT action FROM clinical.audit_log")]
        assert sorted(actions) == ["analysis.create", "analysis.read"]

    def test_imagen_guardada_sin_exif(self, client, ana, storage):
        rgb = Image.open(io.BytesIO(ultrasound_png())).convert("RGB")
        exif = Image.Exif()
        exif[0x010F] = "MarcaDelTelefono"
        buffer = io.BytesIO()
        rgb.save(buffer, format="JPEG", exif=exif)
        response = upload(client, ana, buffer.getvalue(), name="eco.jpg", mime="image/jpeg")
        assert response.status_code == 201
        stored = next(v for k, v in storage.objects.items() if "/images/" in k)
        assert b"MarcaDelTelefono" not in stored

    def test_foto_a_color_422_sin_guardar_nada(self, client, ana, storage, owner_engine):
        buffer = io.BytesIO()
        Image.new("RGB", (300, 300), (200, 40, 40)).save(buffer, format="PNG")
        response = upload(client, ana, buffer.getvalue())
        assert response.status_code == 422
        assert "color" in response.json()["detail"]
        assert storage.objects == {}
        assert rows(owner_engine, "SELECT 1 FROM clinical.analyses") == []

    def test_baja_confianza_es_no_concluyente(self, client, ana, predictor):
        predictor.probabilities = {"normal": 0.4, "benigno": 0.35, "maligno": 0.25}
        body = upload(client, ana).json()
        assert body["status"] == "inconclusive"
        assert "consulta" in body["report"]["recommendation"].lower()

    def test_sin_modelo_503(self, client, ana):
        from backend.app.main import app
        from backend.app.ml.deps import get_inference

        app.dependency_overrides[get_inference] = lambda: InferenceService(None, MLSettings())
        assert upload(client, ana).status_code == 503

    def test_fallo_de_storage_502_sin_filas_ni_objetos(self, client, ana, storage, owner_engine):
        storage.fail = True
        assert upload(client, ana).status_code == 502
        assert rows(owner_engine, "SELECT 1 FROM clinical.analyses") == []

    @pytest.mark.parametrize("role", ["doctor", "tenant_admin"])
    def test_solo_pacientes(self, client, tenant_factory, user_factory, role):
        staff = user_factory(tenant_factory("clinica-a"), role=role)
        assert upload(client, staff).status_code == 403


class TestHistorialYDetalle:
    def test_historial_propio_paginado(self, client, ana, user_factory, b2c_tenant):
        bea = user_factory(b2c_tenant, role="patient")
        mine = [upload(client, ana).json()["id"] for _ in range(3)]
        upload(client, bea)

        page = client.get(URL, params={"limit": 2}, headers=auth_headers(ana)).json()
        assert page["total"] == 3 and len(page["items"]) == 2
        second = client.get(URL, params={"limit": 2, "offset": 2}, headers=auth_headers(ana)).json()
        ids = {i["id"] for i in page["items"]} | {i["id"] for i in second["items"]}
        assert ids == set(mine)

    def test_detalle_con_urls(self, client, ana, storage):
        analysis_id = upload(client, ana).json()["id"]
        storage.signed.clear()
        body = client.get(f"{URL}/{analysis_id}", headers=auth_headers(ana)).json()
        assert body["id"] == analysis_id
        assert body["url_expires_in"] == 300
        assert len(storage.signed) == 2

    def test_otra_paciente_404_igual_que_inexistente(
        self, client, ana, user_factory, b2c_tenant, owner_engine
    ):
        bea = user_factory(b2c_tenant, role="patient")
        analysis_id = upload(client, ana).json()["id"]
        foreign = client.get(f"{URL}/{analysis_id}", headers=auth_headers(bea))
        missing = client.get(f"{URL}/{uuid.uuid4()}", headers=auth_headers(bea))
        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json()
        denied = rows(
            owner_engine,
            "SELECT 1 FROM clinical.audit_log WHERE action = 'analysis.denied' AND actor_id = :a",
            a=bea.id,
        )
        assert len(denied) == 2

    def test_otro_tenant_404(self, client, ana, tenant_factory, user_factory):
        analysis_id = upload(client, ana).json()["id"]
        other = user_factory(tenant_factory("clinica-b"), role="patient")
        assert client.get(f"{URL}/{analysis_id}", headers=auth_headers(other)).status_code == 404
        listing = client.get(URL, headers=auth_headers(other)).json()
        assert listing["total"] == 0


class TestEliminar:
    def test_borra_filas_archivos_y_audita(self, client, ana, storage, owner_engine):
        analysis_id = upload(client, ana).json()["id"]
        stored = set(storage.objects)

        response = client.delete(f"{URL}/{analysis_id}", headers=auth_headers(ana))

        assert response.status_code == 204
        assert storage.objects == {}
        assert set(storage.removed) == stored
        assert rows(owner_engine, "SELECT 1 FROM clinical.analyses") == []
        assert rows(owner_engine, "SELECT 1 FROM clinical.medical_images") == []
        audit = rows(
            owner_engine,
            "SELECT 1 FROM clinical.audit_log "
            "WHERE action = 'analysis.delete' AND resource_id = :r",
            r=analysis_id,
        )
        assert len(audit) == 1
        assert client.get(f"{URL}/{analysis_id}", headers=auth_headers(ana)).status_code == 404

    def test_si_storage_falla_no_se_borra_nada(self, client, ana, storage, owner_engine):
        analysis_id = upload(client, ana).json()["id"]
        storage.fail_remove = True
        assert client.delete(f"{URL}/{analysis_id}", headers=auth_headers(ana)).status_code == 502
        assert len(rows(owner_engine, "SELECT 1 FROM clinical.analyses")) == 1
        storage.fail_remove = False
        assert client.delete(f"{URL}/{analysis_id}", headers=auth_headers(ana)).status_code == 204

    def test_otra_paciente_no_puede_borrar(
        self, client, ana, user_factory, b2c_tenant, storage, owner_engine
    ):
        bea = user_factory(b2c_tenant, role="patient")
        analysis_id = upload(client, ana).json()["id"]
        assert client.delete(f"{URL}/{analysis_id}", headers=auth_headers(bea)).status_code == 404
        assert len(storage.objects) == 2
        assert len(rows(owner_engine, "SELECT 1 FROM clinical.analyses")) == 1
