"""(f) Matriz de acceso cruzado y autorización para CADA endpoint de api/v1.

Completa lo que no cubrían los módulos por endpoint: 401 y 403 en todos los protegidos,
`tenant_id` del cliente ignorado en query, header, formulario y cuerpo, 404 uniforme para
recursos de otro tenant con todos los roles, validación de entrada y 404 en administración.
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text

from backend.app.services.auth import create_access_token
from tests.helpers import DEFAULT_PASSWORD, auth_headers, make_image_bytes

API = "/api/v1"
NEW_TENANT = {
    "name": "Clínica Sur",
    "slug": "clinica-sur",
    "admin_email": "admin@sur.example.com",
    "admin_full_name": "Admin Sur",
    "admin_password": DEFAULT_PASSWORD,
}
NEW_STAFF = {
    "email": "nuevo@example.com",
    "full_name": "Nuevo",
    "password": DEFAULT_PASSWORD,
    "role": "doctor",
}
SOME_ID = uuid.uuid4()

# nombre -> (método, ruta, argumentos de request.). Cubre TODOS los endpoints autenticados.
PROTECTED = {
    "me": ("GET", f"{API}/auth/me", {}),
    "images_list": ("GET", f"{API}/images", {}),
    "images_detail": ("GET", f"{API}/images/{SOME_ID}", {}),
    "images_upload": (
        "POST",
        f"{API}/images/upload",
        {"files": {"file": ("eco.png", make_image_bytes("PNG"), "image/png")}},
    ),
    "audit_list": ("GET", f"{API}/audit", {}),
    "admin_list_tenants": ("GET", f"{API}/admin/tenants", {}),
    "admin_create_tenant": ("POST", f"{API}/admin/tenants", {"json": NEW_TENANT}),
    "admin_update_tenant": (
        "PATCH",
        f"{API}/admin/tenants/{SOME_ID}",
        {"json": {"is_active": False}},
    ),
    "admin_create_user": ("POST", f"{API}/admin/tenants/{SOME_ID}/users", {"json": NEW_STAFF}),
    "admin_update_user": ("PATCH", f"{API}/admin/users/{SOME_ID}", {"json": {"is_active": False}}),
    "admin_isolation_check": ("POST", f"{API}/admin/tenants/{SOME_ID}/isolation-check", {}),
}
ADMIN_ENDPOINTS = [name for name in PROTECTED if name.startswith("admin_")]


def call(client, name: str, headers=None, **extra):
    method, path, kwargs = PROTECTED[name]
    return client.request(method, path, headers=headers, **{**kwargs, **extra})


def upload(client, user) -> str:
    response = client.post(
        f"{API}/images/upload",
        files={"file": ("eco.png", make_image_bytes("PNG"), "image/png")},
        headers=auth_headers(user),
    )
    assert response.status_code == 201
    return response.json()["image_id"]


def audit_actions(owner_engine, tenant_id) -> list[tuple[str, uuid.UUID]]:
    with owner_engine.connect() as conn:
        return [
            (r.action, r.actor_id)
            for r in conn.execute(
                text("SELECT action, actor_id FROM clinical.audit_log WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ]


@pytest.fixture
def two_clinics(tenant_factory, user_factory):
    data = {}
    for slug in ("clinica-a", "clinica-b"):
        tenant = tenant_factory(slug)
        data[slug] = {
            "tenant": tenant,
            "admin": user_factory(tenant, role="tenant_admin"),
            "doctor": user_factory(tenant, role="doctor"),
            "patient": user_factory(tenant, role="patient"),
        }
    return data["clinica-a"], data["clinica-b"]


class TestAutenticacionEnTodosLosEndpoints:
    @pytest.mark.parametrize("name", PROTECTED)
    def test_sin_token_401(self, client, name):
        response = call(client, name)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"

    @pytest.mark.parametrize("name", PROTECTED)
    @pytest.mark.parametrize("token", ["basura", "a.b.c", ""])
    def test_token_invalido_401(self, client, name, token):
        assert call(client, name, headers={"Authorization": f"Bearer {token}"}).status_code == 401

    @pytest.mark.parametrize("name", PROTECTED)
    def test_token_expirado_401(self, client, name, user_factory):
        admin = user_factory(role="platform_admin")
        token = create_access_token(admin, expires_delta=timedelta(minutes=-1))
        assert call(client, name, headers={"Authorization": f"Bearer {token}"}).status_code == 401

    @pytest.mark.parametrize("name", PROTECTED)
    def test_esquema_distinto_de_bearer_401(self, client, name, user_factory):
        admin = user_factory(role="platform_admin")
        token = create_access_token(admin)
        assert call(client, name, headers={"Authorization": f"Basic {token}"}).status_code == 401


class TestRolesEnTodosLosEndpoints:
    @pytest.mark.parametrize("name", ADMIN_ENDPOINTS)
    @pytest.mark.parametrize("role", ["patient", "doctor", "admin"])  # admin = tenant_admin
    def test_administracion_solo_para_platform_admin(self, client, two_clinics, name, role):
        a, _ = two_clinics
        assert call(client, name, headers=auth_headers(a[role])).status_code == 403

    @pytest.mark.parametrize(
        "name", ["images_list", "images_detail", "images_upload", "audit_list"]
    )
    def test_platform_admin_no_toca_datos_clinicos(self, client, user_factory, name):
        admin = user_factory(role="platform_admin")
        assert call(client, name, headers=auth_headers(admin)).status_code == 403

    @pytest.mark.parametrize("role", ["doctor", "patient"])
    def test_auditoria_no_es_para_doctor_ni_paciente_aunque_pidan_otro_tenant(
        self, client, two_clinics, role
    ):
        a, b = two_clinics
        response = client.get(
            f"{API}/audit",
            params={"tenant_id": str(b["tenant"].id)},
            headers={**auth_headers(a[role]), "X-Tenant-Id": str(b["tenant"].id)},
        )
        assert response.status_code == 403


class TestTenantIdDelClienteSeIgnora:
    def test_me_ignora_query_y_header(self, client, two_clinics):
        a, b = two_clinics
        response = client.get(
            f"{API}/auth/me",
            params={"tenant_id": str(b["tenant"].id), "role": "platform_admin"},
            headers={**auth_headers(a["doctor"]), "X-Tenant-Id": str(b["tenant"].id)},
        )
        assert response.status_code == 200
        assert response.json()["tenant_id"] == str(a["tenant"].id)
        assert response.json()["tenant_slug"] == "clinica-a"
        assert response.json()["role"] == "doctor"

    def test_login_ignora_tenant_del_formulario_query_y_header(self, client, two_clinics):
        a, b = two_clinics
        response = client.post(
            f"{API}/auth/token",
            params={"tenant_id": str(b["tenant"].id)},
            data={
                "username": a["doctor"].email,
                "password": DEFAULT_PASSWORD,
                "tenant_id": str(b["tenant"].id),
                "scope": "platform_admin",
            },
            headers={"X-Tenant-Id": str(b["tenant"].id)},
        )
        assert response.status_code == 200
        me = client.get(
            f"{API}/auth/me",
            headers={"Authorization": f"Bearer {response.json()['access_token']}"},
        ).json()
        assert me["tenant_id"] == str(a["tenant"].id)
        assert me["role"] == "doctor"

    def test_registro_con_tenant_en_query_o_header_sigue_en_b2c(
        self, client, two_clinics, b2c_tenant
    ):
        _, b = two_clinics
        response = client.post(
            f"{API}/auth/register",
            params={"tenant_id": str(b["tenant"].id)},
            json={"email": "nueva@example.com", "password": DEFAULT_PASSWORD, "full_name": "Ana"},
            headers={"X-Tenant-Id": str(b["tenant"].id)},
        )
        assert response.status_code == 201
        assert response.json()["tenant_id"] == str(b2c_tenant.id)

    def test_detalle_de_imagen_ignora_tenant_del_cliente(self, client, two_clinics, storage):
        a, b = two_clinics
        mine = upload(client, a["patient"])
        theirs = upload(client, b["patient"])
        spoof = {"tenant_id": str(b["tenant"].id)}
        headers = {**auth_headers(a["admin"]), "X-Tenant-Id": str(b["tenant"].id)}

        own = client.get(f"{API}/images/{mine}", params=spoof, headers=headers)
        foreign = client.get(f"{API}/images/{theirs}", params=spoof, headers=headers)

        assert own.status_code == 200
        assert own.json()["url"].startswith("https://storage.test/signed/clinica-a/")
        assert foreign.status_code == 404
        assert all(path.startswith("clinica-a/") for path in storage.signed)

    def test_log_de_auditoria_ignora_tenant_del_cliente(self, client, two_clinics):
        a, b = two_clinics
        upload(client, b["patient"])
        upload(client, a["patient"])

        entries = client.get(
            f"{API}/audit",
            params={"tenant_id": str(b["tenant"].id)},
            headers={**auth_headers(a["admin"]), "X-Tenant-Id": str(b["tenant"].id)},
        ).json()

        actors = {e["actor_id"] for e in entries}
        assert str(a["patient"].id) in actors
        assert str(b["patient"].id) not in actors

    @pytest.mark.parametrize("name", ["admin_create_tenant", "admin_create_user"])
    def test_administracion_rechaza_tenant_id_en_el_cuerpo(self, client, user_factory, name):
        root = user_factory(role="platform_admin")
        body = {**PROTECTED[name][2]["json"], "tenant_id": str(uuid.uuid4())}
        response = call(client, name, headers=auth_headers(root), json=body)
        assert response.status_code == 422


class TestRecursosDeOtroTenant:
    @pytest.mark.parametrize("role", ["patient", "doctor", "admin"])
    def test_imagen_de_b_da_404_identico_al_de_inexistente(
        self, client, two_clinics, storage, owner_engine, role
    ):
        a, b = two_clinics
        b_image = upload(client, b["patient"])
        with owner_engine.connect() as conn:
            before = conn.execute(
                text("SELECT to_jsonb(m) FROM clinical.medical_images m WHERE id = :i"),
                {"i": b_image},
            ).scalar_one()
        storage.signed.clear()

        foreign = client.get(f"{API}/images/{b_image}", headers=auth_headers(a[role]))
        missing = client.get(f"{API}/images/{uuid.uuid4()}", headers=auth_headers(a[role]))

        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json()
        assert storage.signed == []
        # En B nada cambió ni quedó rastro de A
        with owner_engine.connect() as conn:
            after = conn.execute(
                text("SELECT to_jsonb(m) FROM clinical.medical_images m WHERE id = :i"),
                {"i": b_image},
            ).scalar_one()
        assert after == before
        a_actors = {a[k].id for k in ("admin", "doctor", "patient")}
        assert not {actor for _, actor in audit_actions(owner_engine, b["tenant"].id)} & a_actors

    @pytest.mark.parametrize("role", ["patient", "doctor", "admin"])
    def test_listado_nunca_incluye_imagenes_de_b(self, client, two_clinics, role):
        a, b = two_clinics
        b_image = upload(client, b["patient"])
        response = client.get(f"{API}/images", headers=auth_headers(a[role]))
        assert response.status_code == 200
        assert b_image not in [img["id"] for img in response.json()]

    def test_listar_imagenes_queda_auditado_solo_en_el_tenant_del_actor(
        self, client, two_clinics, owner_engine
    ):
        a, b = two_clinics
        client.get(f"{API}/images", headers=auth_headers(a["doctor"]))
        assert ("image.list", a["doctor"].id) in audit_actions(owner_engine, a["tenant"].id)
        assert audit_actions(owner_engine, b["tenant"].id) == []

    def test_el_log_de_a_no_muestra_actividad_de_b_ni_viceversa(self, client, two_clinics):
        a, b = two_clinics
        upload(client, a["patient"])
        upload(client, b["patient"])
        client.get(f"{API}/images", headers=auth_headers(b["doctor"]))

        in_a = client.get(f"{API}/audit", headers=auth_headers(a["admin"])).json()
        in_b = client.get(f"{API}/audit", headers=auth_headers(b["admin"])).json()

        b_actors = {str(b[k].id) for k in ("admin", "doctor", "patient")}
        a_actors = {str(a[k].id) for k in ("admin", "doctor", "patient")}
        assert {e["actor_id"] for e in in_a} <= a_actors
        assert {e["actor_id"] for e in in_b} <= b_actors
        assert str(b["doctor"].id) in {e["actor_id"] for e in in_b}

    def test_administracion_con_recursos_de_b_da_403_y_b_no_cambia(
        self, client, two_clinics, owner_engine
    ):
        a, b = two_clinics
        headers = auth_headers(a["admin"])
        calls = [
            client.patch(
                f"{API}/admin/tenants/{b['tenant'].id}", json={"is_active": False}, headers=headers
            ),
            client.patch(
                f"{API}/admin/users/{b['doctor'].id}", json={"is_active": False}, headers=headers
            ),
            client.post(f"{API}/admin/tenants/{b['tenant'].id}/isolation-check", headers=headers),
        ]
        assert [c.status_code for c in calls] == [403, 403, 403]
        with owner_engine.connect() as conn:
            assert conn.execute(
                text("SELECT is_active FROM control.tenants WHERE id = :t"), {"t": b["tenant"].id}
            ).scalar_one()
            assert conn.execute(
                text("SELECT is_active FROM control.users WHERE id = :u"), {"u": b["doctor"].id}
            ).scalar_one()


class TestValidacionDeEntrada:
    @pytest.mark.parametrize("path", ["/admin/tenants/no-es-uuid", "/admin/users/no-es-uuid"])
    def test_ids_mal_formados_en_administracion_422(self, client, user_factory, path):
        root = user_factory(role="platform_admin")
        response = client.patch(
            f"{API}{path}", json={"is_active": True}, headers=auth_headers(root)
        )
        assert response.status_code == 422

    def test_id_de_imagen_mal_formado_422(self, client, user_factory, b2c_tenant):
        patient = user_factory(b2c_tenant, role="patient")
        response = client.get(f"{API}/images/no-es-uuid", headers=auth_headers(patient))
        assert response.status_code == 422

    @pytest.mark.parametrize(
        "params",
        [{"from": "ayer"}, {"to": "nunca"}, {"actor_id": "x"}, {"offset": -1}, {"limit": 0}],
    )
    def test_filtros_de_auditoria_invalidos_422(self, client, two_clinics, params):
        a, _ = two_clinics
        response = client.get(f"{API}/audit", params=params, headers=auth_headers(a["admin"]))
        assert response.status_code == 422

    @pytest.mark.parametrize("body", [{}, {"is_active": "quizas"}, {"is_active": True, "x": 1}])
    def test_activacion_con_cuerpo_invalido_422(self, client, user_factory, body):
        root = user_factory(role="platform_admin")
        for path in (f"/admin/tenants/{SOME_ID}", f"/admin/users/{SOME_ID}"):
            response = client.patch(f"{API}{path}", json=body, headers=auth_headers(root))
            assert response.status_code == 422

    @pytest.mark.parametrize(
        "overrides",
        [{"email": "no-es-email"}, {"role": "platform_admin"}, {"password": "corta"}, {"x": 1}],
    )
    def test_alta_de_personal_invalida_422(self, client, user_factory, tenant_factory, overrides):
        root = user_factory(role="platform_admin")
        tenant = tenant_factory("clinica-a")
        response = client.post(
            f"{API}/admin/tenants/{tenant.id}/users",
            json={**NEW_STAFF, **overrides},
            headers=auth_headers(root),
        )
        assert response.status_code == 422

    def test_login_sin_campos_422(self, client):
        assert client.post(f"{API}/auth/token", data={"username": "a@b.com"}).status_code == 422

    def test_subida_sin_archivo_422(self, client, user_factory, b2c_tenant):
        patient = user_factory(b2c_tenant, role="patient")
        response = client.post(f"{API}/images/upload", headers=auth_headers(patient))
        assert response.status_code == 422


class TestAdministracionRecursosInexistentes:
    @pytest.fixture
    def root(self, user_factory):
        return user_factory(role="platform_admin")

    def test_activar_tenant_inexistente_404(self, client, root):
        response = client.patch(
            f"{API}/admin/tenants/{uuid.uuid4()}",
            json={"is_active": False},
            headers=auth_headers(root),
        )
        assert response.status_code == 404

    def test_crear_personal_en_tenant_inexistente_404(self, client, root):
        response = client.post(
            f"{API}/admin/tenants/{uuid.uuid4()}/users", json=NEW_STAFF, headers=auth_headers(root)
        )
        assert response.status_code == 404

    def test_activar_usuario_inexistente_404(self, client, root):
        response = client.patch(
            f"{API}/admin/users/{uuid.uuid4()}",
            json={"is_active": False},
            headers=auth_headers(root),
        )
        assert response.status_code == 404
