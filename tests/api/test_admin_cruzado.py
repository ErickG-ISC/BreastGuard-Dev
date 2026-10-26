"""ADR 0008: acceso cruzado y bordes de la administración (tenants, personal, invitaciones)."""

import uuid

import pytest
from sqlalchemy import text

from backend.app.services.auth import create_access_token
from tests.helpers import DEFAULT_PASSWORD, auth_headers

API = "/api/v1"
BODY = {"is_active": False, "name": "Hack", "email": "q@a.example.com", "full_name": "Q"}


@pytest.fixture
def world(tenant_factory, user_factory):
    a, b = tenant_factory("clinica-a"), tenant_factory("clinica-b")
    return {
        "a": a,
        "b": b,
        "root": user_factory(role="platform_admin", email="root@example.com"),
        "root2": user_factory(role="platform_admin", email="root2@example.com"),
        "a_admin": user_factory(a, role="tenant_admin", email="admin@a.example.com"),
        "a_doctor": user_factory(a, role="doctor", email="doc@a.example.com"),
        "a_patient": user_factory(a, role="patient"),
        "b_admin": user_factory(b, role="tenant_admin", email="admin@b.example.com"),
        "b_doctor": user_factory(b, role="doctor", email="doc@b.example.com"),
        "b_patient": user_factory(b, role="patient", email="pac@b.example.com"),
    }


def rows(owner_engine, sql, **params):
    with owner_engine.connect() as conn:
        return conn.execute(text(sql), params).all()


def invite(client, actor, **body):
    payload = {"email": "nuevo@a.example.com", "full_name": "Nuevo", "role": "doctor", **body}
    return client.post(f"{API}/institution/users", json=payload, headers=auth_headers(actor))


def login(client, email, password=DEFAULT_PASSWORD):
    return client.post(f"{API}/auth/token", data={"username": email, "password": password})


def bearer(response) -> dict[str, str]:
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def snapshot_b(owner_engine, world):
    t = world["b"].id
    return {
        "users": rows(owner_engine, "SELECT * FROM control.users WHERE tenant_id = :t", t=t),
        "tenant": rows(owner_engine, "SELECT * FROM control.tenants WHERE id = :t", t=t),
        "invitations": rows(
            owner_engine, "SELECT * FROM control.invitations WHERE tenant_id = :t", t=t
        ),
        "events": rows(
            owner_engine, "SELECT * FROM control.admin_events WHERE tenant_id = :t", t=t
        ),
    }


class TestInstitucionContraOtroTenant:
    """El tenant_admin de A contra usuarios REALES de B, en todas las rutas /institution/*."""

    @pytest.mark.parametrize("target", ["b_admin", "b_doctor", "b_patient"])
    @pytest.mark.parametrize(
        ("method", "suffix", "body"),
        [
            ("PATCH", "", {"is_active": False}),
            ("PATCH", "", {"role": "tenant_admin"}),
            ("POST", "/invitation", None),
            ("POST", "/reset-access", None),
        ],
    )
    def test_rutas_con_usuarios_reales_de_b_dan_404_uniforme(
        self, client, world, owner_engine, outbox, target, method, suffix, body
    ):
        headers = auth_headers(world["a_admin"])
        before = snapshot_b(owner_engine, world)
        theirs = client.request(
            method,
            f"{API}/institution/users/{world[target].id}{suffix}",
            json=body,
            headers=headers,
        )
        missing = client.request(
            method, f"{API}/institution/users/{uuid.uuid4()}{suffix}", json=body, headers=headers
        )
        assert theirs.status_code == missing.status_code == 404
        assert theirs.json() == missing.json()
        assert outbox.messages == []
        assert snapshot_b(owner_engine, world) == before

    def test_b_nunca_aparece_en_el_listado_aunque_mande_tenant_id(self, client, world):
        headers = {**auth_headers(world["a_admin"]), "X-Tenant-Id": str(world["b"].id)}
        response = client.get(
            f"{API}/institution/users", params={"tenant_id": str(world["b"].id)}, headers=headers
        )
        body = response.json()
        assert response.status_code == 200
        assert {u["tenant_id"] for u in body["items"]} == {str(world["a"].id)}
        ids = {u["id"] for u in body["items"]}
        assert not {str(world["b_admin"].id), str(world["b_doctor"].id)} & ids
        assert body["patients"] == 1  # solo la paciente de A

    @pytest.mark.parametrize("who", ["a_admin", "b_admin"])
    def test_eventos_nunca_son_de_otro_tenant_con_filtros_headers_y_query(self, client, world, who):
        invite(client, world["a_admin"], email="x@a.example.com")
        invite(client, world["b_admin"], email="y@b.example.com")
        mine = world["a"] if who == "a_admin" else world["b"]
        other = world["b"] if who == "a_admin" else world["a"]
        for params in (
            {},
            {"tenant_id": str(other.id)},
            {"action": "user.invite", "tenant_id": str(other.id)},
            {"from": "2000-01-01T00:00:00Z", "to": "2100-01-01T00:00:00Z", "limit": 200},
        ):
            response = client.get(
                f"{API}/institution/events",
                params=params,
                headers={**auth_headers(world[who]), "X-Tenant-Id": str(other.id)},
            )
            assert response.status_code == 200
            page = response.json()
            assert page["total"] == 1
            assert {e["tenant_id"] for e in page["items"]} == {str(mine.id)}

    def test_invitar_con_tenant_id_ajeno_en_cuerpo_422_y_nada_se_crea(
        self, client, world, owner_engine, outbox
    ):
        before = rows(owner_engine, "SELECT count(*) FROM control.users")
        response = invite(client, world["a_admin"], tenant_id=str(world["b"].id))
        assert response.status_code == 422
        assert rows(owner_engine, "SELECT count(*) FROM control.users") == before
        assert outbox.messages == []

    def test_conflicto_de_correo_no_revela_al_otro_tenant(self, client, world):
        response = invite(client, world["a_admin"], email="doc@b.example.com")
        assert response.status_code in (409, 422)
        assert "clinica-b" not in response.text and str(world["b"].id) not in response.text


class TestPlatformAdminBordes:
    @pytest.mark.parametrize("target", ["a_patient", "root2", "root"])
    @pytest.mark.parametrize(
        ("method", "suffix", "body"),
        [
            ("PATCH", "", {"is_active": False}),
            ("POST", "/invitation", None),
            ("POST", "/reset-access", None),
        ],
    )
    def test_usuarios_que_no_son_personal_dan_404(
        self, client, world, owner_engine, outbox, target, method, suffix, body
    ):
        headers = auth_headers(world["root"])
        sql = "SELECT * FROM control.users WHERE id = :u"
        before = rows(owner_engine, sql, u=world[target].id)
        response = client.request(
            method, f"{API}/admin/users/{world[target].id}{suffix}", json=body, headers=headers
        )
        missing = client.request(
            method, f"{API}/admin/users/{uuid.uuid4()}{suffix}", json=body, headers=headers
        )
        assert response.status_code == missing.status_code == 404
        assert response.json() == missing.json()
        assert outbox.messages == []
        assert rows(owner_engine, sql, u=world[target].id) == before

    def test_invitar_en_tenant_desactivado_422(self, client, world, tenant_factory, outbox):
        inactive = tenant_factory("clinica-baja", active=False)
        response = client.post(
            f"{API}/admin/tenants/{inactive.id}/users",
            json={"email": "z@baja.example.com", "full_name": "Z", "role": "doctor"},
            headers=auth_headers(world["root"]),
        )
        assert response.status_code == 422
        assert outbox.messages == []

    def test_invitar_en_b2c_422(self, client, world, b2c_tenant, outbox):
        response = client.post(
            f"{API}/admin/tenants/{b2c_tenant.id}/users",
            json={"email": "z@b2c.example.com", "full_name": "Z", "role": "doctor"},
            headers=auth_headers(world["root"]),
        )
        assert response.status_code == 422
        assert outbox.messages == []

    def test_tenant_inexistente_404_en_todas_las_rutas_con_id(self, client, world):
        headers = auth_headers(world["root"])
        missing = uuid.uuid4()
        calls = [
            client.patch(f"{API}/admin/tenants/{missing}", json={"name": "X"}, headers=headers),
            client.get(f"{API}/admin/tenants/{missing}", headers=headers),
            client.get(f"{API}/admin/tenants/{missing}/users", headers=headers),
            client.post(
                f"{API}/admin/tenants/{missing}/purge-request",
                json={"confirm_slug": "x"},
                headers=headers,
            ),
            client.delete(f"{API}/admin/tenants/{missing}/purge-request", headers=headers),
        ]
        assert [c.status_code for c in calls] == [404] * 5

    def test_listar_personal_de_un_tenant_solo_trae_ese_tenant(self, client, world):
        body = client.get(
            f"{API}/admin/tenants/{world['a'].id}/users", headers=auth_headers(world["root"])
        ).json()
        assert {u["tenant_id"] for u in body["items"]} == {str(world["a"].id)}


ROUTES = [
    ("GET", "/admin/tenants/{t}"),
    ("GET", "/admin/tenants/{t}/users"),
    ("PATCH", "/admin/tenants/{t}"),
    ("PATCH", "/admin/users/{u}"),
    ("POST", "/admin/users/{u}/invitation"),
    ("POST", "/admin/users/{u}/reset-access"),
    ("POST", "/admin/tenants/{t}/isolation-check"),
    ("GET", "/admin/events"),
    ("GET", "/institution/users"),
    ("POST", "/institution/users"),
    ("PATCH", "/institution/users/{u}"),
    ("POST", "/institution/users/{u}/invitation"),
    ("POST", "/institution/users/{u}/reset-access"),
    ("GET", "/institution/events"),
]


class TestRolesSinPermisoEnRutasConId:
    """Rutas con ids reales de B, llamadas por roles que no corresponden."""

    @pytest.mark.parametrize("actor", ["a_doctor", "a_patient"])
    @pytest.mark.parametrize(("method", "path"), ROUTES)
    def test_doctor_y_paciente_403(self, client, world, owner_engine, actor, method, path):
        before = snapshot_b(owner_engine, world)
        url = path.format(t=world["b"].id, u=world["b_doctor"].id)
        response = client.request(
            method,
            f"{API}{url}",
            json={**BODY, "role": "doctor"},
            headers=auth_headers(world[actor]),
        )
        assert response.status_code == 403
        assert snapshot_b(owner_engine, world) == before

    @pytest.mark.parametrize(("method", "path"), [r for r in ROUTES if "/institution" in r[1]])
    def test_platform_admin_403_en_institucion(self, client, world, method, path):
        url = path.format(t=world["a"].id, u=world["a_doctor"].id)
        response = client.request(
            method,
            f"{API}{url}",
            json={**BODY, "role": "doctor"},
            headers=auth_headers(world["root"]),
        )
        assert response.status_code == 403

    @pytest.mark.parametrize(("method", "path"), [r for r in ROUTES if "/admin" in r[1]])
    def test_tenant_admin_403_en_plataforma_y_b_no_cambia(
        self, client, world, owner_engine, method, path
    ):
        before = snapshot_b(owner_engine, world)
        url = path.format(t=world["b"].id, u=world["b_doctor"].id)
        response = client.request(
            method, f"{API}{url}", json=BODY, headers=auth_headers(world["a_admin"])
        )
        assert response.status_code == 403
        assert snapshot_b(owner_engine, world) == before


class TestInvitacionesCruzadas:
    def test_token_de_a_no_sirve_en_b(self, client, world, outbox, owner_engine):
        invite(client, world["a_admin"])
        token = outbox.last_token()
        before = snapshot_b(owner_engine, world)
        as_bearer = {"Authorization": f"Bearer {token}"}
        for path in ("/institution/users", "/institution/events", "/auth/me"):
            assert client.get(f"{API}{path}", headers=as_bearer).status_code == 401
        accepted = client.post(
            f"{API}/auth/invitations/accept", json={"token": token, "password": DEFAULT_PASSWORD}
        )
        assert accepted.status_code == 204
        session = login(client, "nuevo@a.example.com")
        me = client.get(f"{API}/auth/me", headers=bearer(session)).json()
        assert me["tenant_id"] == str(world["a"].id)
        assert snapshot_b(owner_engine, world) == before
        assert client.get(f"{API}/institution/users", headers=bearer(session)).status_code == 403

    def test_aceptar_con_tenant_desactivado_400(self, client, world, outbox, owner_engine):
        invite(client, world["a_admin"])
        token = outbox.last_token()
        client.patch(
            f"{API}/admin/tenants/{world['a'].id}",
            json={"is_active": False},
            headers=auth_headers(world["root"]),
        )
        inspect = client.post(f"{API}/auth/invitations/inspect", json={"token": token})
        accept = client.post(
            f"{API}/auth/invitations/accept", json={"token": token, "password": DEFAULT_PASSWORD}
        )
        assert inspect.status_code == accept.status_code == 400
        (row,) = rows(
            owner_engine,
            "SELECT u.hashed_password, i.used_at FROM control.users u "
            "JOIN control.invitations i ON i.user_id = u.id WHERE u.email = :e",
            e="nuevo@a.example.com",
        )
        assert row.hashed_password is None and row.used_at is None

    def test_inspect_no_revela_si_el_token_existio(self, client, world, outbox, owner_engine):
        invite(client, world["a_admin"], email="usado@a.example.com")
        used = outbox.last_token()
        client.post(
            f"{API}/auth/invitations/accept", json={"token": used, "password": DEFAULT_PASSWORD}
        )
        invite(client, world["a_admin"], email="vencido@a.example.com")
        expired = outbox.last_token()
        with owner_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE control.invitations SET expires_at = now() - interval '1 minute' "
                    "WHERE used_at IS NULL"
                )
            )
        created = invite(client, world["a_admin"], email="revocado@a.example.com")
        revoked = outbox.last_token()
        client.post(
            f"{API}/institution/users/{created.json()['user']['id']}/invitation",
            headers=auth_headers(world["a_admin"]),
        )
        responses = [
            client.post(f"{API}/auth/invitations/inspect", json={"token": t})
            for t in (used, expired, revoked, "z" * 43)
        ]
        assert {r.status_code for r in responses} == {400}
        assert len({r.text for r in responses}) == 1

    def test_el_token_de_sesion_no_es_token_de_invitacion(self, client, world):
        session_token = create_access_token(world["a_doctor"])
        for path in ("inspect", "accept"):
            response = client.post(
                f"{API}/auth/invitations/{path}",
                json={"token": session_token, "password": "otra-contrasena-larga"},
            )
            # 422 si el JWT excede el largo máximo del esquema; nunca un 2xx
            assert response.status_code in (400, 422)
        assert login(client, "doc@a.example.com").status_code == 200  # contraseña intacta

    def test_el_hash_guardado_no_sirve_como_token(self, client, world, outbox, owner_engine):
        invite(client, world["a_admin"])
        (stored,) = rows(owner_engine, "SELECT token_hash FROM control.invitations")
        response = client.post(
            f"{API}/auth/invitations/accept",
            json={"token": stored.token_hash, "password": DEFAULT_PASSWORD},
        )
        assert response.status_code == 400


class TestSesiones:
    def test_token_emitido_justo_antes_del_reset_da_401(self, client, world, outbox):
        headers = auth_headers(world["a_doctor"])
        assert client.get(f"{API}/auth/me", headers=headers).status_code == 200
        client.post(
            f"{API}/institution/users/{world['a_doctor'].id}/reset-access",
            headers=auth_headers(world["a_admin"]),
        )
        assert client.get(f"{API}/auth/me", headers=headers).status_code == 401

    def test_despues_de_aceptar_el_login_funciona_y_el_token_previo_no(self, client, world, outbox):
        old = auth_headers(world["a_doctor"])
        client.post(
            f"{API}/institution/users/{world['a_doctor'].id}/reset-access",
            headers=auth_headers(world["a_admin"]),
        )
        client.post(
            f"{API}/auth/invitations/accept",
            json={"token": outbox.last_token(), "password": "otra-contrasena-larga"},
        )
        fresh = login(client, "doc@a.example.com", "otra-contrasena-larga")
        assert fresh.status_code == 200
        assert client.get(f"{API}/auth/me", headers=bearer(fresh)).status_code == 200
        assert client.get(f"{API}/auth/me", headers=old).status_code == 401

    def test_reset_en_a_no_afecta_las_sesiones_de_b(self, client, world, outbox):
        b_headers = auth_headers(world["b_doctor"])
        client.post(
            f"{API}/institution/users/{world['a_doctor'].id}/reset-access",
            headers=auth_headers(world["a_admin"]),
        )
        assert client.get(f"{API}/auth/me", headers=b_headers).status_code == 200


class TestBitacoraCruzada:
    def test_tenant_admin_no_ve_eventos_de_plataforma_de_otros_tenants(self, client, world):
        root = auth_headers(world["root"])
        client.patch(f"{API}/admin/tenants/{world['b'].id}", json={"name": "B Nueva"}, headers=root)
        client.patch(
            f"{API}/admin/users/{world['b_doctor'].id}", json={"is_active": False}, headers=root
        )
        client.patch(f"{API}/admin/tenants/{world['a'].id}", json={"name": "A Nueva"}, headers=root)
        page = client.get(
            f"{API}/institution/events",
            params={"limit": 200},
            headers=auth_headers(world["a_admin"]),
        ).json()
        assert page["total"] == 1
        assert {e["tenant_id"] for e in page["items"]} == {str(world["a"].id)}
        assert str(world["b_doctor"].id) not in str(page)
        page_b = client.get(
            f"{API}/institution/events",
            params={"limit": 200},
            headers=auth_headers(world["b_admin"]),
        ).json()
        assert page_b["total"] == 2
        assert {e["tenant_id"] for e in page_b["items"]} == {str(world["b"].id)}

    def test_details_no_llevan_correos_ni_tokens(self, client, world, outbox, owner_engine):
        a_admin, root = auth_headers(world["a_admin"]), auth_headers(world["root"])
        email = "sensible@a.example.com"
        user_id = invite(client, world["a_admin"], email=email).json()["user"]["id"]
        tokens = [outbox.last_token()]
        client.post(f"{API}/institution/users/{user_id}/invitation", headers=a_admin)
        tokens.append(outbox.last_token())
        client.post(f"{API}/institution/users/{world['a_doctor'].id}/reset-access", headers=a_admin)
        tokens.append(outbox.last_token())
        client.post(
            f"{API}/auth/invitations/accept",
            json={"token": tokens[-1], "password": "otra-contrasena-larga"},
        )
        client.patch(f"{API}/admin/users/{user_id}", json={"is_active": False}, headers=root)
        client.patch(f"{API}/admin/tenants/{world['a'].id}", json={"plan": "pro"}, headers=root)

        dumps = [
            client.get(f"{API}/institution/events", params={"limit": 200}, headers=a_admin).text,
            client.get(f"{API}/admin/events", params={"limit": 200}, headers=root).text,
            str(rows(owner_engine, "SELECT to_jsonb(e) FROM control.admin_events e")),
        ]
        forbidden = [email, "doc@a.example.com", "otra-contrasena-larga", DEFAULT_PASSWORD, *tokens]
        for dump in dumps:
            assert "user.invite" in dump
            for secret in forbidden:
                assert secret not in dump
