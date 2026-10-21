import uuid
from datetime import timedelta

import pytest
from jose import jwt
from sqlalchemy import text

from backend.app.services.auth import create_access_token
from tests.helpers import DEFAULT_PASSWORD, TestUser

NEW_USER = {
    "email": "nueva@example.com",
    "password": DEFAULT_PASSWORD,
    "full_name": "Usuaria Nueva",
}


def login(client, email: str, password: str = DEFAULT_PASSWORD):
    return client.post("/api/v1/auth/token", data={"username": email, "password": password})


class TestRegister:
    def test_crea_paciente_en_b2c_con_ficha_clinica(self, client, owner_engine, b2c_tenant):
        response = client.post("/api/v1/auth/register", json=NEW_USER)

        assert response.status_code == 201
        body = response.json()
        assert body["role"] == "patient"
        assert body["tenant_id"] == str(b2c_tenant.id)
        assert "password" not in body and "hashed_password" not in body
        with owner_engine.connect() as conn:
            fichas = conn.execute(
                text("SELECT tenant_id FROM clinical.patients WHERE user_id = :id"),
                {"id": body["id"]},
            ).all()
        assert [f.tenant_id for f in fichas] == [b2c_tenant.id]

    @pytest.mark.parametrize(
        "extra",
        [
            {"role": "platform_admin"},
            {"role": "doctor"},
            {"is_medical": True},
            {"tenant_id": str(uuid.uuid4())},
        ],
    )
    def test_no_acepta_rol_ni_tenant_del_cliente(self, client, extra):
        response = client.post("/api/v1/auth/register", json={**NEW_USER, **extra})
        assert response.status_code == 422

    def test_email_duplicado_400_sin_importar_mayusculas(self, client):
        client.post("/api/v1/auth/register", json=NEW_USER)
        duplicate = {**NEW_USER, "email": NEW_USER["email"].upper()}
        assert client.post("/api/v1/auth/register", json=duplicate).status_code == 400

    def test_no_acepta_credenciales_en_query_string(self, client):
        assert client.post("/api/v1/auth/register", params=NEW_USER).status_code == 422

    def test_contrasena_de_mas_de_72_bytes_422(self, client):
        response = client.post("/api/v1/auth/register", json={**NEW_USER, "password": "ñ" * 40})
        assert response.status_code == 422

    def test_b2c_inactivo_503(self, client, owner_engine):
        with owner_engine.begin() as conn:
            conn.execute(text("UPDATE control.tenants SET is_active = false WHERE slug = 'b2c'"))
        assert client.post("/api/v1/auth/register", json=NEW_USER).status_code == 503


class TestToken:
    def test_login_emite_jwt_con_sub_tenant_y_rol(self, client, user_factory, tenant_factory):
        tenant = tenant_factory("clinica-a")
        user = user_factory(tenant, role="doctor", email="doc@example.com")

        response = login(client, "doc@example.com")

        assert response.status_code == 200
        claims = jwt.get_unverified_claims(response.json()["access_token"])
        assert claims["sub"] == str(user.id)
        assert claims["tenant_id"] == str(tenant.id)
        assert claims["role"] == "doctor"

    def test_platform_admin_sin_tenant_en_el_token(self, client, user_factory):
        user_factory(role="platform_admin", email="root@example.com")
        claims = jwt.get_unverified_claims(login(client, "root@example.com").json()["access_token"])
        assert claims["tenant_id"] is None
        assert claims["role"] == "platform_admin"

    def test_contrasena_incorrecta_e_inexistente_mismo_401(self, client, user_factory, b2c_tenant):
        user_factory(b2c_tenant, email="paciente@example.com")
        wrong = login(client, "paciente@example.com", "otra-contrasena")
        unknown = login(client, "nadie@example.com")
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json()

    def test_usuario_inactivo_403(self, client, user_factory, b2c_tenant):
        user_factory(b2c_tenant, email="inactiva@example.com", active=False)
        assert login(client, "inactiva@example.com").status_code == 403

    def test_tenant_inactivo_403(self, client, user_factory, tenant_factory):
        tenant = tenant_factory("clinica-cerrada", active=False)
        user_factory(tenant, role="doctor", email="doc@cerrada.com")
        assert login(client, "doc@cerrada.com").status_code == 403

    def test_inactiva_con_contrasena_incorrecta_sigue_siendo_401(
        self, client, user_factory, b2c_tenant
    ):
        user_factory(b2c_tenant, email="inactiva@example.com", active=False)
        assert login(client, "inactiva@example.com", "otra-contrasena").status_code == 401


class TestCurrentUser:
    """get_current_user se ejerce por /images/upload (endpoint protegido)."""

    URL = "/api/v1/images/upload"

    def post_with(self, client, token: str):
        return client.post(self.URL, headers={"Authorization": f"Bearer {token}"})

    def test_token_expirado_401(self, client, user_factory, b2c_tenant):
        user = user_factory(b2c_tenant)
        token = create_access_token(user, expires_delta=timedelta(minutes=-1))
        assert self.post_with(client, token).status_code == 401

    def test_usuario_desactivado_despues_del_login_401(
        self, client, user_factory, b2c_tenant, owner_engine
    ):
        user = user_factory(b2c_tenant)
        token = create_access_token(user)
        with owner_engine.begin() as conn:
            conn.execute(
                text("UPDATE control.users SET is_active = false WHERE id = :id"), {"id": user.id}
            )
        assert self.post_with(client, token).status_code == 401

    def test_rol_manipulado_en_el_token_401(self, client, user_factory, b2c_tenant):
        user = user_factory(b2c_tenant)
        forged = TestUser(id=user.id, tenant_id=user.tenant_id, role="tenant_admin", email="x")
        assert self.post_with(client, create_access_token(forged)).status_code == 401

    def test_tenant_manipulado_en_el_token_401(
        self, client, user_factory, b2c_tenant, tenant_factory
    ):
        other = tenant_factory("clinica-b")
        user = user_factory(b2c_tenant)
        forged = TestUser(id=user.id, tenant_id=other.id, role=user.role, email="x")
        assert self.post_with(client, create_access_token(forged)).status_code == 401

    def test_platform_admin_con_tenant_en_el_token_401(self, client, user_factory, b2c_tenant):
        admin = user_factory(role="platform_admin")
        forged = TestUser(id=admin.id, tenant_id=b2c_tenant.id, role="platform_admin", email="x")
        assert self.post_with(client, create_access_token(forged)).status_code == 401
