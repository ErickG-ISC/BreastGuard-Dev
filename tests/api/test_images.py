import os

import pytest
from jose import jwt
from sqlalchemy import select

from backend.app.models.image import MedicalImage
from tests.helpers import auth_headers, make_image_bytes

UPLOAD_URL = "/api/v1/images/upload"


def png_file(name: str = "eco.png", content: bytes | None = None, mime: str = "image/png"):
    return {"file": (name, content if content is not None else make_image_bytes("PNG"), mime)}


class TestUploadHappyPath:
    def test_sube_imagen_a_nombre_del_usuario_del_token(self, client, user_factory, db_session):
        user = user_factory()

        response = client.post(UPLOAD_URL, files=png_file(), headers=auth_headers(user))

        assert response.status_code == 201
        image = db_session.get(MedicalImage, response.json()["image_id"])
        assert image.user_id == user.id
        assert image.image_type == "BUSI"

    def test_acepta_jpg_y_tipo_mammography(self, client, user_factory, db_session):
        user = user_factory()
        files = {"file": ("mx.jpg", make_image_bytes("JPEG"), "image/jpeg")}

        response = client.post(
            UPLOAD_URL, files=files, data={"image_type": "mammography"}, headers=auth_headers(user)
        )

        assert response.status_code == 201
        image = db_session.get(MedicalImage, response.json()["image_id"])
        assert image.image_type == "mammography"

    def test_nombre_en_storage_no_usa_el_nombre_del_cliente(self, client, user_factory, storage):
        user = user_factory()

        response = client.post(
            UPLOAD_URL, files=png_file(name="../../secreto.png"), headers=auth_headers(user)
        )

        assert response.status_code == 201
        [object_name] = storage.objects
        assert object_name.startswith(f"uploads/{user.id}/")
        assert "secreto" not in object_name
        assert ".." not in object_name

    def test_borra_el_archivo_temporal(self, client, user_factory, storage):
        user = user_factory()

        client.post(UPLOAD_URL, files=png_file(), headers=auth_headers(user))

        [temp_path] = storage.uploaded_from
        assert not os.path.exists(temp_path)


class TestUploadAuth:
    def test_sin_token_401(self, client, db_session):
        response = client.post(UPLOAD_URL, files=png_file())

        assert response.status_code == 401
        assert db_session.scalars(select(MedicalImage)).first() is None

    def test_token_invalido_401(self, client):
        response = client.post(
            UPLOAD_URL, files=png_file(), headers={"Authorization": "Bearer no-es-un-jwt"}
        )
        assert response.status_code == 401

    def test_token_firmado_con_otra_clave_401(self, client, user_factory):
        user = user_factory()
        forged = jwt.encode({"sub": str(user.id)}, "otra-clave", algorithm="HS256")

        response = client.post(
            UPLOAD_URL, files=png_file(), headers={"Authorization": f"Bearer {forged}"}
        )
        assert response.status_code == 401

    def test_user_id_del_cliente_se_ignora(self, client, user_factory, db_session, storage):
        # Equivalente actual del acceso cruzado: A no puede subir a nombre de B.
        user_a = user_factory(email="a@example.com")
        user_b = user_factory(email="b@example.com")

        response = client.post(
            UPLOAD_URL,
            params={"user_id": user_b.id},
            data={"user_id": str(user_b.id)},
            files=png_file(),
            headers=auth_headers(user_a),
        )

        assert response.status_code == 201
        image = db_session.get(MedicalImage, response.json()["image_id"])
        assert image.user_id == user_a.id
        assert all(name.startswith(f"uploads/{user_a.id}/") for name in storage.objects)


class TestUploadValidation:
    @pytest.mark.parametrize(
        ("name", "mime"),
        [("eco.gif", "image/gif"), ("eco.exe", "application/octet-stream"), ("eco", "image/png")],
    )
    def test_extension_no_permitida_415(self, client, user_factory, name, mime):
        user = user_factory()
        response = client.post(
            UPLOAD_URL, files=png_file(name=name, mime=mime), headers=auth_headers(user)
        )
        assert response.status_code == 415

    def test_mime_no_coincide_415(self, client, user_factory):
        user = user_factory()
        response = client.post(
            UPLOAD_URL, files=png_file(mime="text/plain"), headers=auth_headers(user)
        )
        assert response.status_code == 415

    def test_archivo_que_no_abre_como_imagen_400(self, client, user_factory, storage):
        user = user_factory()
        response = client.post(
            UPLOAD_URL, files=png_file(content=b"esto no es una imagen"), headers=auth_headers(user)
        )
        assert response.status_code == 400
        assert storage.objects == {}

    def test_archivo_demasiado_grande_413(self, client, user_factory, monkeypatch):
        monkeypatch.setenv("MAX_UPLOAD_MB", "0")
        user = user_factory()
        response = client.post(UPLOAD_URL, files=png_file(), headers=auth_headers(user))
        assert response.status_code == 413

    def test_image_type_invalido_422(self, client, user_factory):
        user = user_factory()
        response = client.post(
            UPLOAD_URL, files=png_file(), data={"image_type": "otro"}, headers=auth_headers(user)
        )
        assert response.status_code == 422


class TestUploadStorageFailure:
    def test_fallo_de_storage_502_sin_fila_y_sin_temporal(
        self, client, user_factory, storage, db_session
    ):
        storage.fail = True
        user = user_factory()

        response = client.post(UPLOAD_URL, files=png_file(), headers=auth_headers(user))

        assert response.status_code == 502
        assert db_session.scalars(select(MedicalImage)).first() is None
        [temp_path] = storage.uploaded_from
        assert not os.path.exists(temp_path)
