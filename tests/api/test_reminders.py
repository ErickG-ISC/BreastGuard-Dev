"""CU-05: configuración de recordatorios, avisos en la app, baja por correo y acceso cruzado.

Los recordatorios viven en `control` (sin RLS): la pertenencia la da el filtro por user_id y
tenant_id del JWT en el servicio. Estas pruebas atacan ese filtro con pacientes de la misma
clínica y de otra.
"""

import threading
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from backend.app.services.auth import create_access_token
from backend.app.services.unsubscribe import make_token
from tests.helpers import auth_headers
from tests.pgtest import TEST_APP_ROLE

API = "/api/v1"
BODY = {
    "frequency": "first_sunday",
    "local_time": "09:00",
    "timezone": "America/Tijuana",
    "channels": ["in_app", "email"],
}


@pytest.fixture
def world(tenant_factory, user_factory):
    tenant_a, tenant_b = tenant_factory("clinica-a"), tenant_factory("clinica-b")
    return {
        "ta": tenant_a,
        "tb": tenant_b,
        "a1": user_factory(tenant_a, role="patient"),
        "a2": user_factory(tenant_a, role="patient"),
        "b1": user_factory(tenant_b, role="patient"),
    }


def save(client, user, kind="self_exam", **overrides):
    return client.put(
        f"{API}/reminders/{kind}", json={**BODY, **overrides}, headers=auth_headers(user)
    )


def reminder_row(owner_engine, user, kind="self_exam"):
    with owner_engine.connect() as conn:
        return conn.execute(
            text("SELECT * FROM control.reminders WHERE user_id = :u AND kind = :k"),
            {"u": user.id, "k": kind},
        ).first()


def insert_notice(owner_engine, user, reminder_id) -> uuid.UUID:
    with owner_engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO control.reminder_notices (tenant_id, user_id, reminder_id, kind, "
                "due_at) VALUES (:t, :u, :r, 'self_exam', now()) RETURNING id"
            ),
            {"t": user.tenant_id, "u": user.id, "r": reminder_id},
        ).scalar_one()


class TestConfiguracion:
    def test_crear_y_listar(self, client, world):
        response = save(client, world["a1"])
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["discreet"] is True and body["active"] is True
        assert datetime.fromisoformat(body["next_run_at"]) > datetime.now(UTC)
        listed = client.get(f"{API}/reminders", headers=auth_headers(world["a1"])).json()
        assert [r["kind"] for r in listed] == ["self_exam"]

    def test_guardar_dos_veces_reemplaza(self, client, world, owner_engine):
        save(client, world["a1"])
        second = save(client, world["a1"], frequency="every_n_days", interval_n=28, discreet=False)
        assert second.status_code == 200
        assert second.json()["interval_n"] == 28 and second.json()["discreet"] is False
        with owner_engine.connect() as conn:
            count = conn.execute(text("SELECT count(*) FROM control.reminders")).scalar_one()
        assert count == 1

    def test_dos_tipos_independientes(self, client, world):
        save(client, world["a1"])
        response = save(
            client, world["a1"], kind="repeat_analysis", frequency="every_n_months", interval_n=6
        )
        assert response.status_code == 200
        kinds = [
            r["kind"]
            for r in client.get(f"{API}/reminders", headers=auth_headers(world["a1"])).json()
        ]
        assert kinds == ["repeat_analysis", "self_exam"]

    def test_la_hora_se_guarda_en_la_zona_de_la_paciente(self, client, world):
        body = save(client, world["a1"], timezone="America/Tijuana", local_time="09:00").json()
        local = datetime.fromisoformat(body["next_run_at"]).astimezone(ZoneInfo("America/Tijuana"))
        assert (local.hour, local.minute) == (9, 0)
        assert local.weekday() == 6 and local.day <= 7

    @pytest.mark.parametrize(
        "overrides",
        [
            {"local_time": "09:10"},
            {"local_time": "09:00:30"},
            {"timezone": "Mars/Base"},
            {"timezone": "../../etc/passwd"},
            {"frequency": "every_n_days"},
            {"frequency": "every_n_days", "interval_n": 0},
            {"frequency": "every_n_days", "interval_n": 91},
            {"frequency": "every_n_months", "interval_n": 25},
            {"frequency": "first_sunday", "interval_n": 3},
            {"frequency": "weekly"},
            {"channels": []},
            {"channels": ["email", "email"]},
            {"channels": ["push"]},
            {"tenant_id": str(uuid.uuid4())},
            {"user_id": str(uuid.uuid4())},
            {"next_run_at": "2020-01-01T00:00:00Z"},
        ],
    )
    def test_entrada_invalida_422(self, client, world, overrides):
        assert save(client, world["a1"], **overrides).status_code == 422

    def test_tipo_desconocido_422(self, client, world):
        assert save(client, world["a1"], kind="mamografia").status_code == 422

    def test_borrar(self, client, world):
        save(client, world["a1"])
        headers = auth_headers(world["a1"])
        assert client.delete(f"{API}/reminders/self_exam", headers=headers).status_code == 204
        assert client.delete(f"{API}/reminders/self_exam", headers=headers).status_code == 404
        assert client.get(f"{API}/reminders", headers=headers).json() == []

    @pytest.mark.parametrize("role", ["doctor", "tenant_admin"])
    def test_el_personal_no_configura_recordatorios(self, client, world, user_factory, role):
        staff = user_factory(world["ta"], role=role)
        assert save(client, staff).status_code == 403


class TestAvisos:
    def test_listar_no_leidos_y_marcar_leido(self, client, world, owner_engine):
        save(client, world["a1"])
        reminder = reminder_row(owner_engine, world["a1"])
        notice_id = insert_notice(owner_engine, world["a1"], reminder.id)
        headers = auth_headers(world["a1"])
        unread = client.get(f"{API}/notices?unread=true", headers=headers).json()
        assert [n["id"] for n in unread] == [str(notice_id)]
        assert client.post(f"{API}/notices/{notice_id}/read", headers=headers).status_code == 204
        assert client.get(f"{API}/notices?unread=true", headers=headers).json() == []
        assert len(client.get(f"{API}/notices", headers=headers).json()) == 1


VICTIMS = ["a2", "b1"]


class TestAccesoCruzado:
    @pytest.mark.parametrize("victim", VICTIMS)
    def test_no_ve_recordatorios_ni_avisos_ajenos(self, client, world, owner_engine, victim):
        save(client, world[victim])
        reminder = reminder_row(owner_engine, world[victim])
        insert_notice(owner_engine, world[victim], reminder.id)
        headers = auth_headers(world["a1"])
        assert client.get(f"{API}/reminders", headers=headers).json() == []
        assert client.get(f"{API}/notices", headers=headers).json() == []

    @pytest.mark.parametrize("victim", VICTIMS)
    def test_guardar_y_borrar_no_tocan_lo_ajeno(self, client, world, owner_engine, victim):
        save(client, world[victim], discreet=True)
        before = reminder_row(owner_engine, world[victim])
        assert save(client, world["a1"], discreet=False).status_code == 200
        headers = auth_headers(world["a1"])
        client.delete(f"{API}/reminders/self_exam", headers=headers)
        assert client.delete(f"{API}/reminders/self_exam", headers=headers).status_code == 404
        assert reminder_row(owner_engine, world[victim]) == before

    @pytest.mark.parametrize("victim", VICTIMS)
    def test_no_marca_avisos_ajenos(self, client, world, owner_engine, victim):
        save(client, world[victim])
        reminder = reminder_row(owner_engine, world[victim])
        notice_id = insert_notice(owner_engine, world[victim], reminder.id)
        response = client.post(f"{API}/notices/{notice_id}/read", headers=auth_headers(world["a1"]))
        missing = client.post(
            f"{API}/notices/{uuid.uuid4()}/read", headers=auth_headers(world["a1"])
        )
        assert response.status_code == missing.status_code == 404
        assert response.json() == missing.json()
        with owner_engine.connect() as conn:
            read_at = conn.execute(
                text("SELECT read_at FROM control.reminder_notices WHERE id = :id"),
                {"id": notice_id},
            ).scalar_one()
        assert read_at is None


class TestBaja:
    def test_token_valido_quita_el_correo_y_conserva_el_aviso_en_la_app(
        self, client, world, owner_engine
    ):
        save(client, world["a1"])
        reminder = reminder_row(owner_engine, world["a1"])
        token = make_token(reminder.id, world["a1"].id)
        response = client.post(f"{API}/reminders/unsubscribe", json={"token": token})
        assert response.status_code == 204
        after = reminder_row(owner_engine, world["a1"])
        assert after.channels == ["in_app"] and after.active is True
        # Repetir no falla (el enlace puede abrirse dos veces)
        assert client.post(f"{API}/reminders/unsubscribe", json={"token": token}).status_code == 204

    def test_solo_correo_queda_en_la_app(self, client, world, owner_engine):
        save(client, world["a1"], channels=["email"])
        reminder = reminder_row(owner_engine, world["a1"])
        client.post(
            f"{API}/reminders/unsubscribe", json={"token": make_token(reminder.id, world["a1"].id)}
        )
        assert reminder_row(owner_engine, world["a1"]).channels == ["in_app"]

    def test_token_alterado_400(self, client, world, owner_engine):
        save(client, world["a1"])
        reminder = reminder_row(owner_engine, world["a1"])
        token = make_token(reminder.id, world["a1"].id)
        tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
        response = client.post(f"{API}/reminders/unsubscribe", json={"token": tampered})
        assert response.status_code == 400
        assert "email" in reminder_row(owner_engine, world["a1"]).channels

    def test_token_vencido_400(self, client, world, owner_engine):
        save(client, world["a1"])
        reminder = reminder_row(owner_engine, world["a1"])
        old = make_token(reminder.id, world["a1"].id, now=datetime.now(UTC) - timedelta(days=91))
        assert client.post(f"{API}/reminders/unsubscribe", json={"token": old}).status_code == 400

    def test_token_de_sesion_no_sirve_para_la_baja(self, client, world):
        session_token = create_access_token(world["a1"])
        response = client.post(f"{API}/reminders/unsubscribe", json={"token": session_token})
        assert response.status_code == 400

    def test_token_de_baja_no_sirve_como_sesion(self, client, world, owner_engine):
        save(client, world["a1"])
        reminder = reminder_row(owner_engine, world["a1"])
        token = make_token(reminder.id, world["a1"].id)
        response = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

    def test_token_de_otra_paciente_no_toca_recordatorios_ajenos(self, client, world, owner_engine):
        """El token lleva recordatorio Y usuario: combinar ids de dos personas no da de baja."""
        save(client, world["a1"])
        save(client, world["a2"])
        reminder_a2 = reminder_row(owner_engine, world["a2"])
        token = make_token(reminder_a2.id, world["a1"].id)
        assert client.post(f"{API}/reminders/unsubscribe", json={"token": token}).status_code == 204
        assert "email" in reminder_row(owner_engine, world["a2"]).channels


class TestEndurecimiento:
    def test_guardados_simultaneos_no_fallan(self, client, world, owner_engine):
        results = []

        def go(discreet):
            results.append(save(client, world["a1"], discreet=discreet).status_code)

        threads = [threading.Thread(target=go, args=(d,)) for d in (True, False, True, False)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert results == [200] * 4
        with owner_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM control.reminders")).scalar_one() == 1

    @pytest.mark.parametrize("column", ["user_id", "tenant_id", "kind", "id", "created_at"])
    def test_app_user_no_actualiza_columnas_de_identidad(self, owner_engine, column):
        with owner_engine.connect() as conn:
            allowed = conn.execute(
                text("SELECT has_column_privilege(:r, 'control.reminders', :c, 'UPDATE')"),
                {"r": TEST_APP_ROLE, "c": column},
            ).scalar_one()
        assert allowed is False

    @pytest.mark.parametrize(
        "column", ["user_id", "tenant_id", "reminder_id", "kind", "due_at", "created_at"]
    )
    def test_app_user_no_actualiza_avisos_salvo_lectura_y_estado(self, owner_engine, column):
        with owner_engine.connect() as conn:
            allowed = conn.execute(
                text("SELECT has_column_privilege(:r, 'control.reminder_notices', :c, 'UPDATE')"),
                {"r": TEST_APP_ROLE, "c": column},
            ).scalar_one()
            can_delete = conn.execute(
                text("SELECT has_table_privilege(:r, 'control.reminder_notices', 'DELETE')"),
                {"r": TEST_APP_ROLE},
            ).scalar_one()
        assert allowed is False and can_delete is False
