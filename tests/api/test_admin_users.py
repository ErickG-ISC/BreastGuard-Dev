"""ADR 0008: administración de tenants y personal, invitaciones, sesiones, purga y bitácora."""

import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from backend.app.services.auth import create_access_token
from backend.scripts.purge_tenant import pending_slugs, purge_tenant
from tests.helpers import DEFAULT_PASSWORD, auth_headers

API = "/api/v1"


@pytest.fixture
def world(tenant_factory, user_factory):
    a, b = tenant_factory("clinica-a"), tenant_factory("clinica-b")
    return {
        "a": a,
        "b": b,
        "root": user_factory(role="platform_admin", email="root@example.com"),
        "a_admin": user_factory(a, role="tenant_admin", email="admin@a.example.com"),
        "a_doctor": user_factory(a, role="doctor", email="doc@a.example.com"),
        "a_patient": user_factory(a, role="patient"),
        "b_admin": user_factory(b, role="tenant_admin", email="admin@b.example.com"),
        "b_doctor": user_factory(b, role="doctor", email="doc@b.example.com"),
    }


def q(owner_engine, sql, **params):
    with owner_engine.connect() as conn:
        return conn.execute(text(sql), params).all()


def scalar(owner_engine, sql, **params):
    with owner_engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def invite(client, actor, **body):
    payload = {"email": "nuevo@a.example.com", "full_name": "Nuevo", "role": "doctor", **body}
    return client.post(f"{API}/institution/users", json=payload, headers=auth_headers(actor))


def login(client, email, password=DEFAULT_PASSWORD):
    return client.post(f"{API}/auth/token", data={"username": email, "password": password})


def events(owner_engine, action=None):
    sql = "SELECT action, actor_id, tenant_id, target_id, host(ip) AS ip, details FROM "
    sql += "control.admin_events"
    if action:
        sql += " WHERE action = :a"
    return q(owner_engine, sql + " ORDER BY occurred_at", a=action)


class TestTenantsDePlataforma:
    def test_listado_con_estadisticas_de_control_y_filtros(self, client, world):
        headers = auth_headers(world["root"])
        page = client.get(f"{API}/admin/tenants", params={"q": "clinica-a"}, headers=headers)
        assert page.status_code == 200
        (item,) = page.json()["items"]
        assert item["slug"] == "clinica-a"
        assert item["stats"] == {
            "staff": 2,
            "staff_active": 2,
            "invitations_pending": 0,
            "patients": 1,
            "last_login_at": None,
        }
        # Nada clínico en la respuesta
        assert not {"analyses", "symptoms", "self_exams"} & set(item["stats"])
        inactive = client.get(f"{API}/admin/tenants", params={"active": False}, headers=headers)
        assert inactive.json()["total"] == 0

    def test_editar_nombre_y_plan_queda_en_bitacora(self, client, world, owner_engine):
        response = client.patch(
            f"{API}/admin/tenants/{world['a'].id}",
            json={"name": "Clínica A Renovada", "plan": "pro"},
            headers=auth_headers(world["root"]),
        )
        assert response.status_code == 200
        assert response.json()["plan"] == "pro"
        (event,) = events(owner_engine, "tenant.update")
        assert event.details == {"fields": ["name", "plan"], "plan": "pro"}
        assert event.ip == "198.51.100.7"

    @pytest.mark.parametrize(
        "body", [{"kind": "b2c"}, {"plan": "gratis"}, {"slug": "otro"}, {}, {"name": None}]
    )
    def test_edicion_invalida_422(self, client, world, body):
        response = client.patch(
            f"{API}/admin/tenants/{world['a'].id}", json=body, headers=auth_headers(world["root"])
        )
        assert response.status_code == 422

    def test_b2c_no_se_desactiva_ni_se_purga(self, client, world, b2c_tenant):
        headers = auth_headers(world["root"])
        deactivate = client.patch(
            f"{API}/admin/tenants/{b2c_tenant.id}", json={"is_active": False}, headers=headers
        )
        purge = client.post(
            f"{API}/admin/tenants/{b2c_tenant.id}/purge-request",
            json={"confirm_slug": "b2c"},
            headers=headers,
        )
        assert deactivate.status_code == purge.status_code == 422


class TestPerdidaDeAcceso:
    def test_tenant_desactivado_no_inicia_sesion_ni_usa_su_token(self, client, world):
        token_headers = auth_headers(world["a_doctor"])
        assert client.get(f"{API}/auth/me", headers=token_headers).status_code == 200
        client.patch(
            f"{API}/admin/tenants/{world['a'].id}",
            json={"is_active": False},
            headers=auth_headers(world["root"]),
        )
        assert login(client, "doc@a.example.com").status_code == 403
        assert client.get(f"{API}/auth/me", headers=token_headers).status_code == 401
        # El otro tenant sigue funcionando
        assert (
            client.get(f"{API}/auth/me", headers=auth_headers(world["b_doctor"])).status_code == 200
        )

    def test_usuario_desactivado_pierde_su_token(self, client, world):
        token_headers = auth_headers(world["a_doctor"])
        client.patch(
            f"{API}/institution/users/{world['a_doctor'].id}",
            json={"is_active": False},
            headers=auth_headers(world["a_admin"]),
        )
        assert client.get(f"{API}/auth/me", headers=token_headers).status_code == 401
        assert login(client, "doc@a.example.com").status_code == 403

    def test_restablecer_acceso_cierra_sesiones_y_exige_nueva_contrasena(
        self, client, world, outbox
    ):
        old = {"Authorization": f"Bearer {create_access_token(world['a_doctor'])}"}
        response = client.post(
            f"{API}/institution/users/{world['a_doctor'].id}/reset-access",
            headers=auth_headers(world["a_admin"]),
        )
        assert response.status_code == 200 and response.json() == {"email_sent": True}
        assert client.get(f"{API}/auth/me", headers=old).status_code == 401
        assert login(client, "doc@a.example.com").status_code == 401
        accepted = client.post(
            f"{API}/auth/invitations/accept",
            json={"token": outbox.last_token(), "password": "otra-contrasena-larga"},
        )
        assert accepted.status_code == 204
        assert login(client, "doc@a.example.com", "otra-contrasena-larga").status_code == 200

    def test_cambio_de_rol_invalida_el_token_anterior(self, client, world):
        token_headers = auth_headers(world["a_doctor"])
        client.patch(
            f"{API}/institution/users/{world['a_doctor'].id}",
            json={"role": "tenant_admin"},
            headers=auth_headers(world["a_admin"]),
        )
        assert client.get(f"{API}/auth/me", headers=token_headers).status_code == 401


class TestAlcanceDelTenantAdmin:
    def test_lista_solo_personal_de_su_tenant_y_conteo_de_pacientes(self, client, world):
        body = client.get(f"{API}/institution/users", headers=auth_headers(world["a_admin"])).json()
        emails = {u["email"] for u in body["items"]}
        assert emails == {"admin@a.example.com", "doc@a.example.com"}
        assert body["patients"] == 1

    @pytest.mark.parametrize(
        ("method", "suffix", "body"),
        [
            ("PATCH", "", {"is_active": False}),
            ("PATCH", "", {"role": "tenant_admin"}),
            ("POST", "/invitation", None),
            ("POST", "/reset-access", None),
        ],
    )
    def test_usuarios_de_otro_tenant_404_igual_que_inexistentes(
        self, client, world, owner_engine, method, suffix, body
    ):
        headers = auth_headers(world["a_admin"])
        before = q(
            owner_engine, "SELECT * FROM control.users WHERE tenant_id = :t", t=world["b"].id
        )
        theirs = client.request(
            method,
            f"{API}/institution/users/{world['b_doctor'].id}{suffix}",
            json=body,
            headers=headers,
        )
        missing = client.request(
            method, f"{API}/institution/users/{uuid.uuid4()}{suffix}", json=body, headers=headers
        )
        assert theirs.status_code == missing.status_code == 404
        assert theirs.json() == missing.json()
        after = q(owner_engine, "SELECT * FROM control.users WHERE tenant_id = :t", t=world["b"].id)
        assert after == before

    def test_pacientes_no_se_gestionan_aqui(self, client, world):
        response = client.patch(
            f"{API}/institution/users/{world['a_patient'].id}",
            json={"is_active": False},
            headers=auth_headers(world["a_admin"]),
        )
        assert response.status_code == 404

    def test_invita_en_su_tenant_aunque_mande_otro_tenant_id(self, client, world, owner_engine):
        response = client.post(
            f"{API}/institution/users",
            params={"tenant_id": str(world["b"].id)},
            headers={**auth_headers(world["a_admin"]), "X-Tenant-Id": str(world["b"].id)},
            json={"email": "x@a.example.com", "full_name": "X", "role": "doctor"},
        )
        assert response.status_code == 201
        assert response.json()["user"]["tenant_id"] == str(world["a"].id)
        body_tenant = invite(client, world["a_admin"], tenant_id=str(world["b"].id))
        assert body_tenant.status_code == 422

    def test_bitacora_solo_de_su_tenant(self, client, world):
        invite(client, world["a_admin"])
        invite(client, world["b_admin"], email="otro@b.example.com")
        page = client.get(
            f"{API}/institution/events", headers=auth_headers(world["a_admin"])
        ).json()
        assert page["total"] == 1
        assert {e["tenant_id"] for e in page["items"]} == {str(world["a"].id)}
        filtered = client.get(
            f"{API}/institution/events",
            params={"tenant_id": str(world["b"].id)},
            headers=auth_headers(world["a_admin"]),
        ).json()
        assert {e["tenant_id"] for e in filtered["items"]} == {str(world["a"].id)}


class TestEscalada:
    @pytest.mark.parametrize("role", ["platform_admin", "patient"])
    def test_no_invita_roles_no_permitidos(self, client, world, role):
        assert invite(client, world["a_admin"], role=role).status_code == 422

    @pytest.mark.parametrize("role", ["platform_admin", "patient"])
    def test_no_eleva_a_roles_no_permitidos(self, client, world, role):
        response = client.patch(
            f"{API}/institution/users/{world['a_doctor'].id}",
            json={"role": role},
            headers=auth_headers(world["a_admin"]),
        )
        assert response.status_code == 422

    @pytest.mark.parametrize("body", [{"role": "doctor"}, {"is_active": False}])
    def test_no_se_cambia_el_rol_ni_se_desactiva_a_si_mismo(self, client, world, body):
        response = client.patch(
            f"{API}/institution/users/{world['a_admin'].id}",
            json=body,
            headers=auth_headers(world["a_admin"]),
        )
        assert response.status_code == 422

    def test_el_tenant_conserva_al_menos_un_admin(self, client, world):
        # El platform_admin intenta dejar a la clínica A sin administradores
        response = client.patch(
            f"{API}/admin/users/{world['a_admin'].id}",
            json={"is_active": False},
            headers=auth_headers(world["root"]),
        )
        assert response.status_code == 422

    @pytest.mark.parametrize(
        ("old_role_user", "new_role"),
        [("a_doctor", "platform_admin"), ("a_doctor", "patient"), ("a_patient", "doctor")],
    )
    def test_la_base_impide_escalar_por_sql(self, world, old_role_user, new_role):
        from tests.helpers import tenant_session

        with tenant_session(world["a_admin"]) as session, pytest.raises(DBAPIError):
            session.execute(
                text("UPDATE control.users SET role = :r WHERE id = :id"),
                {"r": new_role, "id": world[old_role_user].id},
            )

    def test_platform_admin_nunca_aparece_ni_se_gestiona(self, client, world):
        other = world["root"]
        response = client.patch(
            f"{API}/admin/users/{other.id}",
            json={"is_active": False},
            headers=auth_headers(world["root"]),
        )
        assert response.status_code == 404


class TestInvitaciones:
    def test_invitacion_de_un_solo_uso(self, client, world, outbox, owner_engine):
        assert invite(client, world["a_admin"]).status_code == 201
        token = outbox.last_token()
        info = client.post(f"{API}/auth/invitations/inspect", json={"token": token})
        assert info.status_code == 200
        assert info.json()["email_masked"] == "n***@a***.com"
        first = client.post(
            f"{API}/auth/invitations/accept", json={"token": token, "password": DEFAULT_PASSWORD}
        )
        second = client.post(
            f"{API}/auth/invitations/accept", json={"token": token, "password": DEFAULT_PASSWORD}
        )
        assert first.status_code == 204 and second.status_code == 400
        # En la base solo está el hash
        assert (
            scalar(
                owner_engine,
                "SELECT count(*) FROM control.invitations WHERE token_hash = :t",
                t=token,
            )
            == 0
        )

    def test_vencida_400(self, client, world, outbox, owner_engine):
        invite(client, world["a_admin"])
        with owner_engine.begin() as conn:
            conn.execute(
                text("UPDATE control.invitations SET expires_at = now() - interval '1 minute'")
            )
        response = client.post(
            f"{API}/auth/invitations/accept",
            json={"token": outbox.last_token(), "password": DEFAULT_PASSWORD},
        )
        assert response.status_code == 400

    def test_reenviar_revoca_la_anterior(self, client, world, outbox):
        response = invite(client, world["a_admin"])
        old = outbox.last_token()
        user_id = response.json()["user"]["id"]
        resent = client.post(
            f"{API}/institution/users/{user_id}/invitation", headers=auth_headers(world["a_admin"])
        )
        assert resent.status_code == 200
        new = outbox.last_token()
        assert old != new
        stale = client.post(
            f"{API}/auth/invitations/accept", json={"token": old, "password": DEFAULT_PASSWORD}
        )
        fresh = client.post(
            f"{API}/auth/invitations/accept", json={"token": new, "password": DEFAULT_PASSWORD}
        )
        assert stale.status_code == 400 and fresh.status_code == 204

    def test_aceptar_simultaneo_solo_uno_gana(self, client, world, outbox):
        invite(client, world["a_admin"])
        token = outbox.last_token()
        results = []

        def go(password):
            results.append(
                client.post(
                    f"{API}/auth/invitations/accept", json={"token": token, "password": password}
                ).status_code
            )

        threads = [threading.Thread(target=go, args=(f"contrasena-{i}-larga",)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(results) == [204, 400, 400]

    def test_cuenta_desactivada_no_acepta(self, client, world, outbox):
        user_id = invite(client, world["a_admin"]).json()["user"]["id"]
        updated = client.patch(
            f"{API}/institution/users/{user_id}",
            json={"is_active": False},
            headers=auth_headers(world["a_admin"]),
        )
        # Desactivada manda sobre invitada pendiente
        assert updated.json()["status"] == "inactive"
        response = client.post(
            f"{API}/auth/invitations/accept",
            json={"token": outbox.last_token(), "password": DEFAULT_PASSWORD},
        )
        assert response.status_code == 400

    def test_fallo_de_correo_no_deshace_la_invitacion(self, client, world, outbox, owner_engine):
        outbox.fail = True
        response = invite(client, world["a_admin"])
        assert response.status_code == 201
        assert response.json()["email_sent"] is False
        assert scalar(owner_engine, "SELECT count(*) FROM control.invitations") == 1

    def test_ni_token_ni_correo_en_logs_ni_bitacora(
        self, client, world, outbox, owner_engine, caplog
    ):
        with caplog.at_level("DEBUG"):
            invite(client, world["a_admin"])
            token = outbox.last_token()
            client.post(
                f"{API}/auth/invitations/accept",
                json={"token": token, "password": DEFAULT_PASSWORD},
            )
        assert token not in caplog.text
        assert "nuevo@a.example.com" not in caplog.text
        dump = scalar(
            owner_engine, "SELECT string_agg(to_jsonb(e)::text, '') FROM control.admin_events e"
        )
        assert token not in dump and "nuevo@a.example.com" not in dump

    @pytest.mark.parametrize("token", ["x" * 30, "y" * 43])
    def test_token_desconocido_400(self, client, token):
        assert (
            client.post(f"{API}/auth/invitations/inspect", json={"token": token}).status_code == 400
        )


class TestPurga:
    def test_slug_equivocado_no_hace_nada(self, client, world, owner_engine):
        response = client.post(
            f"{API}/admin/tenants/{world['a'].id}/purge-request",
            json={"confirm_slug": "clinica-b"},
            headers=auth_headers(world["root"]),
        )
        assert response.status_code == 422
        assert scalar(
            owner_engine, "SELECT is_active FROM control.tenants WHERE id = :t", t=world["a"].id
        )

    def test_solicitar_desactiva_y_el_script_solo_purga_ese_tenant(
        self, client, world, owner_engine, storage
    ):
        headers = auth_headers(world["root"])
        response = client.post(
            f"{API}/admin/tenants/{world['a'].id}/purge-request",
            json={"confirm_slug": "clinica-a"},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["is_active"] is False
        assert response.json()["purge_requested_at"] is not None
        assert (
            client.get(f"{API}/auth/me", headers=auth_headers(world["a_admin"])).status_code == 401
        )

        b_users_before = scalar(
            owner_engine, "SELECT count(*) FROM control.users WHERE tenant_id = :t", t=world["b"].id
        )
        assert pending_slugs(owner_engine) == ["clinica-a"]
        purge_tenant(owner_engine, "clinica-a", require_request=True)
        assert (
            scalar(owner_engine, "SELECT count(*) FROM control.tenants WHERE slug = 'clinica-a'")
            == 0
        )
        assert (
            scalar(
                owner_engine,
                "SELECT count(*) FROM control.users WHERE tenant_id = :t",
                t=world["b"].id,
            )
            == b_users_before
        )
        # La bitácora sobrevive y registra la purga
        actions = [e.action for e in events(owner_engine) if e.tenant_id == world["a"].id]
        assert actions == ["tenant.purge_request", "tenant.purge"]

    def test_cancelar_evita_la_purga(self, client, world, owner_engine):
        headers = auth_headers(world["root"])
        client.post(
            f"{API}/admin/tenants/{world['a'].id}/purge-request",
            json={"confirm_slug": "clinica-a"},
            headers=headers,
        )
        assert (
            client.delete(
                f"{API}/admin/tenants/{world['a'].id}/purge-request", headers=headers
            ).status_code
            == 200
        )
        assert pending_slugs(owner_engine) == []
        from backend.scripts.purge_tenant import PurgeError

        with pytest.raises(PurgeError):
            purge_tenant(owner_engine, "clinica-a", require_request=True)


class TestBitacora:
    def test_cada_accion_deja_un_evento_sin_datos_sensibles(
        self, client, world, outbox, owner_engine
    ):
        a_admin = auth_headers(world["a_admin"])
        user_id = invite(client, world["a_admin"]).json()["user"]["id"]
        client.post(f"{API}/institution/users/{user_id}/invitation", headers=a_admin)
        client.patch(
            f"{API}/institution/users/{world['a_doctor'].id}",
            json={"role": "tenant_admin"},
            headers=a_admin,
        )
        client.patch(
            f"{API}/institution/users/{world['a_doctor'].id}",
            json={"is_active": False},
            headers=a_admin,
        )
        rows = events(owner_engine)
        assert [r.action for r in rows] == [
            "user.invite",
            "user.invite_resend",
            "user.role_change",
            "user.deactivate",
        ]
        for row in rows:
            assert row.actor_id == world["a_admin"].id
            assert row.tenant_id == world["a"].id
            assert row.ip == "198.51.100.7"
            assert "@" not in str(row.details)

    def test_la_app_no_puede_alterar_la_bitacora(self, client, world, owner_engine):
        from tests.helpers import tenant_session

        invite(client, world["a_admin"])
        for sql in (
            "UPDATE control.admin_events SET action = 'x'",
            "DELETE FROM control.admin_events",
        ):
            with (
                tenant_session(world["a_admin"]) as session,
                pytest.raises(DBAPIError, match="permission"),
            ):
                session.execute(text(sql))


class TestRolesSinPermiso:
    @pytest.mark.parametrize("actor", ["a_doctor", "a_patient"])
    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", "/institution/users"),
            ("POST", "/institution/users"),
            ("GET", "/institution/events"),
            ("GET", "/admin/tenants"),
            ("GET", "/admin/events"),
        ],
    )
    def test_403(self, client, world, actor, method, path):
        response = client.request(
            method,
            f"{API}{path}",
            json={"email": "z@a.example.com", "full_name": "Z", "role": "doctor"},
            headers=auth_headers(world[actor]),
        )
        assert response.status_code == 403

    def test_platform_admin_no_usa_rutas_de_institucion(self, client, world):
        response = client.get(f"{API}/institution/users", headers=auth_headers(world["root"]))
        assert response.status_code == 403

    def test_ultimo_acceso_se_registra(self, client, world, owner_engine):
        login(client, "doc@a.example.com")
        last = scalar(
            owner_engine,
            "SELECT last_login_at FROM control.users WHERE id = :u",
            u=world["a_doctor"].id,
        )
        assert last is not None and last > datetime.now(UTC) - timedelta(minutes=1)


class TestRevisionDeAislamiento:
    def test_reactivar_usuario_no_revive_tokens_viejos(self, client, world):
        old = auth_headers(world["a_doctor"])
        a_admin = auth_headers(world["a_admin"])
        url = f"{API}/institution/users/{world['a_doctor'].id}"
        client.patch(url, json={"is_active": False}, headers=a_admin)
        client.patch(url, json={"is_active": True}, headers=a_admin)
        assert client.get(f"{API}/auth/me", headers=old).status_code == 401
        assert login(client, "doc@a.example.com").status_code == 200

    def test_reactivar_tenant_no_revive_tokens_viejos(self, client, world):
        old = auth_headers(world["a_doctor"])
        root = auth_headers(world["root"])
        url = f"{API}/admin/tenants/{world['a'].id}"
        client.patch(url, json={"is_active": False}, headers=root)
        client.patch(url, json={"is_active": True}, headers=root)
        assert client.get(f"{API}/auth/me", headers=old).status_code == 401
        assert login(client, "doc@a.example.com").status_code == 200
        assert (
            client.get(f"{API}/auth/me", headers=auth_headers(world["b_doctor"])).status_code == 200
        )

    def test_la_institucion_no_ve_ip_ni_id_de_la_plataforma(self, client, world):
        client.patch(
            f"{API}/admin/tenants/{world['a'].id}",
            json={"plan": "pro"},
            headers=auth_headers(world["root"]),
        )
        invite(client, world["a_admin"])
        items = client.get(
            f"{API}/institution/events", headers=auth_headers(world["a_admin"])
        ).json()["items"]
        by_role = {e["actor_role"]: e for e in items}
        assert by_role["platform_admin"]["ip"] is None
        assert by_role["platform_admin"]["actor_id"] is None
        # Lo propio de la institución sí se ve completo
        assert by_role["tenant_admin"]["actor_id"] == str(world["a_admin"].id)
        # La plataforma conserva el detalle completo
        full = client.get(f"{API}/admin/events", headers=auth_headers(world["root"])).json()
        assert any(e["actor_id"] == str(world["root"].id) and e["ip"] for e in full["items"])

    def test_degradaciones_cruzadas_simultaneas_sin_error(self, client, world, user_factory):
        second = user_factory(world["a"], role="tenant_admin", email="admin2@a.example.com")
        results = []

        def demote(actor, target):
            results.append(
                client.patch(
                    f"{API}/institution/users/{target.id}",
                    json={"role": "doctor"},
                    headers=auth_headers(actor),
                ).status_code
            )

        threads = [
            threading.Thread(target=demote, args=(world["a_admin"], second)),
            threading.Thread(target=demote, args=(second, world["a_admin"])),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Uno gana; el otro ya no es admin (401 por rol cambiado) o choca con la regla (422)
        assert 200 in results
        assert all(code in (200, 401, 422) for code in results)

    def test_chequeo_de_aislamiento_con_limite(self, client, world):
        headers = auth_headers(world["root"])
        codes = [
            client.post(
                f"{API}/admin/tenants/{world['a'].id}/isolation-check", headers=headers
            ).status_code
            for _ in range(11)
        ]
        assert codes[:10] == [200] * 10 and codes[10] == 429
