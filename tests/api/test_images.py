import base64
import os

import pytest
from jose import jwt
from sqlalchemy import text

from tests.helpers import auth_headers, make_image_bytes

UPLOAD_URL = "/api/v1/images/upload"


def png_file(name: str = "eco.png", content: bytes | None = None, mime: str = "image/png"):
    return {"file": (name, content if content is not None else make_image_bytes("PNG"), mime)}


def image_rows(owner_engine):
    with owner_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT id, tenant_id, patient_id, uploaded_by, object_path, image_type "
                "FROM clinical.medical_images"
            )
        ).all()


@pytest.fixture
def patient(user_factory, b2c_tenant):
    return user_factory(b2c_tenant, role="patient")


class TestUploadHappyPath:
    def test_sube_a_la_ficha_del_paciente_del_token(self, client, patient, owner_engine):
        response = client.post(UPLOAD_URL, files=png_file(), headers=auth_headers(patient))

        assert response.status_code == 201
        [row] = image_rows(owner_engine)
        assert str(row.id) == response.json()["image_id"]
        assert row.tenant_id == patient.tenant_id  # lo pone la base desde el contexto
        assert row.patient_id == patient.patient_id
        assert row.uploaded_by == patient.id
        assert row.image_type == "BUSI"

    def test_acepta_jpg_y_tipo_mammography(self, client, patient, owner_engine):
        files = {"file": ("mx.jpg", make_image_bytes("JPEG"), "image/jpeg")}
        response = client.post(
            UPLOAD_URL,
            files=files,
            data={"image_type": "mammography"},
            headers=auth_headers(patient),
        )
        assert response.status_code == 201
        assert image_rows(owner_engine)[0].image_type == "mammography"

    def test_ruta_con_prefijo_del_tenant_y_sin_nombre_del_cliente(
        self, client, patient, storage, owner_engine
    ):
        response = client.post(
            UPLOAD_URL, files=png_file(name="../../secreto.png"), headers=auth_headers(patient)
        )

        assert response.status_code == 201
        [object_name] = storage.objects
        assert object_name.startswith("b2c/images/")
        assert "secreto" not in object_name and ".." not in object_name
        assert image_rows(owner_engine)[0].object_path == object_name

    def test_borra_el_archivo_temporal(self, client, patient, storage):
        client.post(UPLOAD_URL, files=png_file(), headers=auth_headers(patient))
        [temp_path] = storage.uploaded_from
        assert not os.path.exists(temp_path)


class TestUploadAuth:
    def test_sin_token_401(self, client, owner_engine):
        assert client.post(UPLOAD_URL, files=png_file()).status_code == 401
        assert image_rows(owner_engine) == []

    def test_token_invalido_401(self, client):
        response = client.post(
            UPLOAD_URL, files=png_file(), headers={"Authorization": "Bearer no-es-un-jwt"}
        )
        assert response.status_code == 401

    def test_token_firmado_con_otra_clave_401(self, client, patient):
        forged = jwt.encode(
            {
                "sub": str(patient.id),
                "tenant_id": str(patient.tenant_id),
                "role": "patient",
                "exp": 9999999999,
            },
            "otra-clave",
            algorithm="HS256",
        )
        response = client.post(
            UPLOAD_URL, files=png_file(), headers={"Authorization": f"Bearer {forged}"}
        )
        assert response.status_code == 401

    def test_token_alg_none_401(self, client, patient):
        header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=")
        payload = base64.urlsafe_b64encode(
            (
                f'{{"sub":"{patient.id}","tenant_id":"{patient.tenant_id}",'
                f'"role":"patient","exp":9999999999}}'
            ).encode()
        ).rstrip(b"=")
        token = f"{header.decode()}.{payload.decode()}."
        response = client.post(
            UPLOAD_URL, files=png_file(), headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 401

    @pytest.mark.parametrize("role", ["doctor", "tenant_admin"])
    def test_rol_no_paciente_403(self, client, user_factory, tenant_factory, role):
        user = user_factory(tenant_factory("clinica-a"), role=role)
        response = client.post(UPLOAD_URL, files=png_file(), headers=auth_headers(user))
        assert response.status_code == 403

    def test_platform_admin_403(self, client, user_factory):
        admin = user_factory(role="platform_admin")
        response = client.post(UPLOAD_URL, files=png_file(), headers=auth_headers(admin))
        assert response.status_code == 403

    def test_tenant_y_usuario_del_cliente_se_ignoran(
        self, client, patient, user_factory, tenant_factory, owner_engine
    ):
        other_tenant = tenant_factory("clinica-b")
        other = user_factory(other_tenant, role="patient")

        response = client.post(
            UPLOAD_URL,
            params={"tenant_id": str(other_tenant.id), "user_id": str(other.id)},
            data={"tenant_id": str(other_tenant.id), "patient_id": str(other.patient_id)},
            files=png_file(),
            headers={**auth_headers(patient), "X-Tenant-Id": str(other_tenant.id)},
        )

        assert response.status_code == 201
        [row] = image_rows(owner_engine)
        assert row.tenant_id == patient.tenant_id
        assert row.patient_id == patient.patient_id


class TestUploadValidation:
    @pytest.mark.parametrize(
        ("name", "mime"),
        [("eco.gif", "image/gif"), ("eco.exe", "application/octet-stream"), ("eco", "image/png")],
    )
    def test_extension_no_permitida_415(self, client, patient, name, mime):
        response = client.post(
            UPLOAD_URL, files=png_file(name=name, mime=mime), headers=auth_headers(patient)
        )
        assert response.status_code == 415

    def test_mime_no_coincide_415(self, client, patient):
        response = client.post(
            UPLOAD_URL, files=png_file(mime="text/plain"), headers=auth_headers(patient)
        )
        assert response.status_code == 415

    def test_archivo_que_no_abre_como_imagen_400(self, client, patient, storage):
        response = client.post(
            UPLOAD_URL, files=png_file(content=b"no es imagen"), headers=auth_headers(patient)
        )
        assert response.status_code == 400
        assert storage.objects == {}

    def test_archivo_demasiado_grande_413(self, client, patient, monkeypatch):
        monkeypatch.setenv("MAX_UPLOAD_MB", "0")
        response = client.post(UPLOAD_URL, files=png_file(), headers=auth_headers(patient))
        assert response.status_code == 413

    def test_image_type_invalido_422(self, client, patient):
        response = client.post(
            UPLOAD_URL, files=png_file(), data={"image_type": "otro"}, headers=auth_headers(patient)
        )
        assert response.status_code == 422


class TestUploadStorageFailure:
    def test_fallo_de_storage_502_sin_fila_y_sin_temporal(
        self, client, patient, storage, owner_engine
    ):
        storage.fail = True
        response = client.post(UPLOAD_URL, files=png_file(), headers=auth_headers(patient))

        assert response.status_code == 502
        assert image_rows(owner_engine) == []
        [temp_path] = storage.uploaded_from
        assert not os.path.exists(temp_path)


def test_paciente_sin_ficha_404(client, user_factory, b2c_tenant, owner_engine):
    patient = user_factory(b2c_tenant, role="patient")
    with owner_engine.begin() as conn:
        conn.execute(text("DELETE FROM clinical.patients WHERE user_id = :id"), {"id": patient.id})
    response = client.post(UPLOAD_URL, files=png_file(), headers=auth_headers(patient))
    assert response.status_code == 404
