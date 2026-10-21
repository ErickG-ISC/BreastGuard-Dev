"""CU-12: administración de plataforma (solo platform_admin, solo esquema control)."""

import uuid

import pytest
from sqlalchemy import text

from backend.app.services import audit
from tests.helpers import DEFAULT_PASSWORD, auth_headers

NEW_TENANT = {
    "name": "Clínica Norte",
    "slug": "clinica-norte",
    "admin_email": "admin@norte.example.com",
    "admin_full_name": "Admin Norte",
    "admin_password": DEFAULT_PASSWORD,
}


@pytest.fixture
def root(user_factory):
    return user_factory(role="platform_admin", email="root@example.com")


def create(client, root, **overrides):
    return client.post(
        "/api/v1/admin/tenants", json={**NEW_TENANT, **overrides}, headers=auth_headers(root)
    )


def scalar(owner_engine, sql: str, **params):
    with owner_engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


class TestCrearTenant:
    def test_crea_tenant_admin_y_auditoria_en_una_transaccion(self, client, root, owner_engine):
        response = create(client, root)

        assert response.status_code == 201
        body = response.json()
        tenant_id = body["tenant"]["id"]
        assert body["tenant"]["kind"] == "institucion"
        assert (
            scalar(
                owner_engine,
                "SELECT role FROM control.users WHERE id = :id AND tenant_id = :t",
                id=body["admin_user_id"],
                t=tenant_id,
            )
            == "tenant_admin"
        )
        actions = scalar(
            owner_engine,
            "SELECT array_agg(action ORDER BY action) FROM clinical.audit_log "
            "WHERE tenant_id = :t AND actor_id = :actor",
            t=tenant_id,
            actor=root.id,
        )
        assert actions == ["tenant.create", "user.create"]

    def test_el_admin_del_tenant_puede_iniciar_sesion(self, client, root):
        create(client, root)
        response = client.post(
            "/api/v1/auth/token",
            data={"username": NEW_TENANT["admin_email"], "password": DEFAULT_PASSWORD},
        )
        assert response.status_code == 200

    @pytest.mark.parametrize("role", ["patient", "doctor", "tenant_admin"])
    def test_solo_platform_admin(self, client, user_factory, tenant_factory, b2c_tenant, role):
        tenant = b2c_tenant if role == "patient" else tenant_factory("clinica-a")
        user = user_factory(tenant, role=role)
        response = client.post("/api/v1/admin/tenants", json=NEW_TENANT, headers=auth_headers(user))
        assert response.status_code == 403

    def test_sin_token_401(self, client):
        assert client.post("/api/v1/admin/tenants", json=NEW_TENANT).status_code == 401

    def test_slug_duplicado_409(self, client, root):
        create(client, root)
        response = create(client, root, admin_email="otro@norte.example.com")
        assert response.status_code == 409

    def test_email_duplicado_409_sin_dejar_nada_a_medias(self, client, root, owner_engine):
        response = create(client, root, admin_email=root.email)
        assert response.status_code == 409
        assert (
            scalar(
                owner_engine,
                "SELECT count(*) FROM control.tenants WHERE slug = :s",
                s="clinica-norte",
            )
            == 0
        )

    def test_fallo_a_mitad_no_deja_nada(self, client, root, owner_engine, monkeypatch):
        # Falla en la SEGUNDA auditoría: tenant, admin y la primera fila ya se escribieron
        real_record = audit.record
        calls = []

        def fail_on_second(*args, **kwargs):
            calls.append(kwargs["action"])
            if len(calls) == 2:
                raise RuntimeError("fallo simulado en la auditoría")
            real_record(*args, **kwargs)

        monkeypatch.setattr(audit, "record", fail_on_second)
        with pytest.raises(RuntimeError, match="fallo simulado"):
            create(client, root)

        assert (
            scalar(
                owner_engine,
                "SELECT count(*) FROM control.tenants WHERE slug = :s",
                s="clinica-norte",
            )
            == 0
        )
        assert (
            scalar(
                owner_engine,
                "SELECT count(*) FROM control.users WHERE email = :e",
                e=NEW_TENANT["admin_email"],
            )
            == 0
        )
        assert calls == ["tenant.create", "user.create"]
        assert scalar(owner_engine, "SELECT count(*) FROM clinical.audit_log") == 0

    def test_carrera_de_email_409_sin_dejar_nada(self, client, root, owner_engine, monkeypatch):
        # Simula que otro proceso registró el email entre la verificación y el INSERT
        from backend.app.services import tenants as tenants_service

        monkeypatch.setattr(tenants_service, "get_user_by_email", lambda db, email: None)
        response = create(client, root, admin_email=root.email)

        assert response.status_code == 409
        assert (
            scalar(
                owner_engine,
                "SELECT count(*) FROM control.tenants WHERE slug = :s",
                s="clinica-norte",
            )
            == 0
        )

    @pytest.mark.parametrize("slug", ["b2c", "uploads", "admin", "legacy"])
    def test_slug_reservado_422(self, client, root, slug):
        assert create(client, root, slug=slug).status_code == 422

    def test_contrasena_corta_para_personal_422(self, client, root):
        assert create(client, root, admin_password="corta-11ch").status_code == 422

    @pytest.mark.parametrize(
        "overrides",
        [{"slug": "Con Mayusculas"}, {"slug": "-x"}, {"kind": "b2c"}, {"tenant_id": "x"}],
    )
    def test_entrada_invalida_422(self, client, root, overrides):
        assert create(client, root, **overrides).status_code == 422


class TestChequeoDeAislamiento:
    def test_el_tenant_nuevo_no_ve_ajenas_y_nadie_ve_las_suyas(
        self, client, root, user_factory, b2c_tenant, owner_engine
    ):
        # Datos de otro tenant para que el chequeo no pase en vacío
        user_factory(b2c_tenant, role="patient")
        assert scalar(owner_engine, "SELECT count(*) FROM clinical.patients") > 0
        tenant_id = create(client, root).json()["tenant"]["id"]

        response = client.post(
            f"/api/v1/admin/tenants/{tenant_id}/isolation-check", headers=auth_headers(root)
        )

        assert response.status_code == 200
        report = response.json()
        assert report["passed"] is True
        assert report["app_role_without_bypass"] is True
        assert report["rows_visible_without_context"] == 0
        assert report["foreign_rows_visible_to_tenant"] == 0
        assert report["tenant_rows_visible_to_others"] == 0
        assert report["tenant_has_witness_rows"] is True
        assert report["conclusive"] is True
        assert report["other_tenants_checked"] >= 1
        assert set(report["tables_checked"]) == {
            "patients",
            "medical_images",
            "audit_log",
            "questionnaires",
        }

    def test_no_deja_rastro(self, client, root, owner_engine):
        tenant_id = create(client, root).json()["tenant"]["id"]
        before = scalar(owner_engine, "SELECT count(*) FROM clinical.audit_log")
        client.post(
            f"/api/v1/admin/tenants/{tenant_id}/isolation-check", headers=auth_headers(root)
        )
        assert scalar(owner_engine, "SELECT count(*) FROM clinical.audit_log") == before

    def test_detecta_una_fuga_si_rls_se_desactiva(
        self, client, root, user_factory, b2c_tenant, owner_engine
    ):
        user_factory(b2c_tenant, role="patient")
        tenant_id = create(client, root).json()["tenant"]["id"]
        with owner_engine.begin() as conn:
            conn.execute(text("ALTER TABLE clinical.patients DISABLE ROW LEVEL SECURITY"))
        try:
            report = client.post(
                f"/api/v1/admin/tenants/{tenant_id}/isolation-check", headers=auth_headers(root)
            ).json()
        finally:
            with owner_engine.begin() as conn:
                conn.execute(text("ALTER TABLE clinical.patients ENABLE ROW LEVEL SECURITY"))
        assert report["passed"] is False
        assert report["foreign_rows_visible_to_tenant"] > 0

    def test_corre_en_transaccion_de_solo_lectura(self, client, root, monkeypatch):
        from backend.app.services import tenants as tenants_service

        tenant_id = create(client, root).json()["tenant"]["id"]

        def write_attempt(db, table, where, **params):
            db.execute(text("UPDATE control.tenants SET plan = plan"))
            return 0

        monkeypatch.setattr(tenants_service, "_count", write_attempt)
        with pytest.raises(Exception, match="read-only"):
            client.post(
                f"/api/v1/admin/tenants/{tenant_id}/isolation-check", headers=auth_headers(root)
            )

    def test_tenant_inexistente_404(self, client, root):
        response = client.post(
            f"/api/v1/admin/tenants/{uuid.uuid4()}/isolation-check", headers=auth_headers(root)
        )
        assert response.status_code == 404

    def test_solo_platform_admin(self, client, user_factory, tenant_factory):
        tenant = tenant_factory("clinica-a")
        admin = user_factory(tenant, role="tenant_admin")
        response = client.post(
            f"/api/v1/admin/tenants/{tenant.id}/isolation-check", headers=auth_headers(admin)
        )
        assert response.status_code == 403


class TestUsuariosYActivacion:
    def test_crea_doctor_en_institucion(self, client, root, tenant_factory, owner_engine):
        tenant = tenant_factory("clinica-a")
        response = client.post(
            f"/api/v1/admin/tenants/{tenant.id}/users",
            json={
                "email": "doc@a.example.com",
                "full_name": "Doc",
                "password": DEFAULT_PASSWORD,
                "role": "doctor",
            },
            headers=auth_headers(root),
        )
        assert response.status_code == 201
        assert response.json()["tenant_id"] == str(tenant.id)
        assert (
            scalar(
                owner_engine,
                "SELECT count(*) FROM clinical.audit_log "
                "WHERE tenant_id = :t AND action = 'user.create'",
                t=tenant.id,
            )
            == 1
        )

    @pytest.mark.parametrize("role", ["platform_admin", "patient"])
    def test_no_crea_roles_no_permitidos(self, client, root, tenant_factory, role):
        tenant = tenant_factory("clinica-a")
        response = client.post(
            f"/api/v1/admin/tenants/{tenant.id}/users",
            json={"email": "x@a.com", "full_name": "X", "password": DEFAULT_PASSWORD, "role": role},
            headers=auth_headers(root),
        )
        assert response.status_code == 422

    def test_b2c_no_admite_personal(self, client, root, b2c_tenant):
        response = client.post(
            f"/api/v1/admin/tenants/{b2c_tenant.id}/users",
            json={
                "email": "doc@b2c.com",
                "full_name": "Doc",
                "password": DEFAULT_PASSWORD,
                "role": "doctor",
            },
            headers=auth_headers(root),
        )
        assert response.status_code == 422

    def test_desactivar_tenant_bloquea_login_y_tokens(
        self, client, root, user_factory, tenant_factory
    ):
        tenant = tenant_factory("clinica-a")
        doctor = user_factory(tenant, role="doctor", email="doc@a.example.com")
        headers = auth_headers(doctor)

        response = client.patch(
            f"/api/v1/admin/tenants/{tenant.id}",
            json={"is_active": False},
            headers=auth_headers(root),
        )

        assert response.status_code == 200
        login = client.post(
            "/api/v1/auth/token",
            data={"username": "doc@a.example.com", "password": DEFAULT_PASSWORD},
        )
        assert login.status_code == 403
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401

    def test_desactivar_usuario(self, client, root, user_factory, tenant_factory):
        doctor = user_factory(tenant_factory("clinica-a"), role="doctor")
        response = client.patch(
            f"/api/v1/admin/users/{doctor.id}",
            json={"is_active": False},
            headers=auth_headers(root),
        )
        assert response.status_code == 200
        assert client.get("/api/v1/auth/me", headers=auth_headers(doctor)).status_code == 401

    def test_platform_admin_no_se_gestiona_por_api(self, client, root, user_factory):
        other = user_factory(role="platform_admin")
        response = client.patch(
            f"/api/v1/admin/users/{other.id}", json={"is_active": False}, headers=auth_headers(root)
        )
        assert response.status_code == 404

    def test_no_desactiva_b2c(self, client, root, b2c_tenant):
        response = client.patch(
            f"/api/v1/admin/tenants/{b2c_tenant.id}",
            json={"is_active": False},
            headers=auth_headers(root),
        )
        assert response.status_code == 422

    def test_desactivacion_queda_auditada_en_el_tenant(
        self, client, root, tenant_factory, owner_engine
    ):
        tenant = tenant_factory("clinica-a")
        client.patch(
            f"/api/v1/admin/tenants/{tenant.id}",
            json={"is_active": False},
            headers=auth_headers(root),
        )
        count = scalar(
            owner_engine,
            "SELECT count(*) FROM clinical.audit_log WHERE tenant_id = :t "
            "AND action = 'tenant.deactivate' AND actor_id = :a",
            t=tenant.id,
            a=root.id,
        )
        assert count == 1

    def test_listar_tenants(self, client, root, tenant_factory):
        tenant_factory("clinica-a")
        response = client.get("/api/v1/admin/tenants", headers=auth_headers(root))
        assert response.status_code == 200
        assert {t["slug"] for t in response.json()} >= {"b2c", "clinica-a"}


class TestAccesoCruzadoDeAdministracion:
    """Un tenant_admin (o doctor) de A no usa la administración de plataforma contra B."""

    @pytest.fixture
    def setup(self, tenant_factory, user_factory):
        a, b = tenant_factory("clinica-a"), tenant_factory("clinica-b")
        return {
            "a_admin": user_factory(a, role="tenant_admin"),
            "a_doctor": user_factory(a, role="doctor"),
            "b": b,
            "b_doctor": user_factory(b, role="doctor"),
        }

    @pytest.mark.parametrize("actor", ["a_admin", "a_doctor"])
    def test_403_en_todos_los_endpoints(self, client, setup, actor, owner_engine):
        headers = auth_headers(setup[actor])
        b, b_doctor = setup["b"], setup["b_doctor"]
        new_user = {
            "email": "intruso@x.com",
            "full_name": "X",
            "password": DEFAULT_PASSWORD,
            "role": "tenant_admin",
        }
        calls = [
            client.get("/api/v1/admin/tenants", headers=headers),
            client.patch(
                f"/api/v1/admin/tenants/{b.id}", json={"is_active": False}, headers=headers
            ),
            client.post(f"/api/v1/admin/tenants/{b.id}/users", json=new_user, headers=headers),
            client.patch(
                f"/api/v1/admin/users/{b_doctor.id}", json={"is_active": False}, headers=headers
            ),
        ]
        assert [c.status_code for c in calls] == [403, 403, 403, 403]
        active = scalar(owner_engine, "SELECT is_active FROM control.tenants WHERE id = :t", t=b.id)
        assert active is True
        intruders = scalar(
            owner_engine, "SELECT count(*) FROM control.users WHERE email = 'intruso@x.com'"
        )
        assert intruders == 0


def test_me_devuelve_el_contexto(client, user_factory, tenant_factory):
    tenant = tenant_factory("clinica-a")
    doctor = user_factory(tenant, role="doctor")
    response = client.get("/api/v1/auth/me", headers=auth_headers(doctor))
    assert response.json() == {
        "user_id": str(doctor.id),
        "tenant_id": str(tenant.id),
        "tenant_slug": "clinica-a",
        "role": "doctor",
    }
