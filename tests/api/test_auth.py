from datetime import timedelta

from backend.app.services.auth import create_access_token
from tests.helpers import DEFAULT_PASSWORD

NEW_USER = {
    "email": "nueva@example.com",
    "password": DEFAULT_PASSWORD,
    "full_name": "Usuaria Nueva",
}


class TestRegister:
    def test_registra_usuario_sin_devolver_contrasena(self, client):
        response = client.post("/api/v1/auth/register", json=NEW_USER)

        assert response.status_code == 201
        body = response.json()
        assert body["email"] == NEW_USER["email"]
        assert body["is_medical"] is False
        assert "password" not in body
        assert "hashed_password" not in body

    def test_email_duplicado_400(self, client):
        client.post("/api/v1/auth/register", json=NEW_USER)
        response = client.post("/api/v1/auth/register", json=NEW_USER)
        assert response.status_code == 400

    def test_no_acepta_credenciales_en_query_string(self, client):
        response = client.post("/api/v1/auth/register", params=NEW_USER)
        assert response.status_code == 422

    def test_email_invalido_422(self, client):
        response = client.post("/api/v1/auth/register", json={**NEW_USER, "email": "no-es-email"})
        assert response.status_code == 422

    def test_contrasena_corta_422(self, client):
        response = client.post("/api/v1/auth/register", json={**NEW_USER, "password": "corta"})
        assert response.status_code == 422

    def test_contrasena_de_mas_de_72_bytes_422(self, client):
        response = client.post("/api/v1/auth/register", json={**NEW_USER, "password": "ñ" * 40})
        assert response.status_code == 422


class TestToken:
    def test_login_devuelve_token_utilizable(self, client, user_factory):
        user_factory(email="paciente@example.com")

        response = client.post(
            "/api/v1/auth/token",
            data={"username": "paciente@example.com", "password": DEFAULT_PASSWORD},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]

    def test_contrasena_incorrecta_401(self, client, user_factory):
        user_factory(email="paciente@example.com")
        response = client.post(
            "/api/v1/auth/token",
            data={"username": "paciente@example.com", "password": "otra-contrasena"},
        )
        assert response.status_code == 401

    def test_usuario_inexistente_401_mismo_mensaje(self, client, user_factory):
        user_factory(email="paciente@example.com")
        wrong_password = client.post(
            "/api/v1/auth/token",
            data={"username": "paciente@example.com", "password": "otra-contrasena"},
        )
        unknown_user = client.post(
            "/api/v1/auth/token",
            data={"username": "nadie@example.com", "password": DEFAULT_PASSWORD},
        )
        assert unknown_user.status_code == 401
        # No revela si el email existe
        assert unknown_user.json() == wrong_password.json()


class TestCurrentUser:
    """get_current_user se ejerce a través de /images/upload, el único endpoint protegido."""

    def test_token_de_usuario_borrado_401(self, client, user_factory, db_session):
        user = user_factory()
        token = create_access_token(user.id)
        db_session.delete(user)
        db_session.commit()

        response = client.post(
            "/api/v1/images/upload", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 401

    def test_token_expirado_401(self, client, user_factory):
        user = user_factory()
        token = create_access_token(user.id, expires_delta=timedelta(minutes=-1))

        response = client.post(
            "/api/v1/images/upload", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 401
