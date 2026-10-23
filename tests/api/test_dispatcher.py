"""CU-05: despachador de recordatorios (secreto, idempotencia, fallos de correo, aislamiento)."""

import re
import threading
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, text

from backend.app.api.v1.internal import get_email_sender
from backend.app.db import get_engine, new_session
from backend.app.main import app
from backend.app.services import reminders
from backend.app.services.email import ConsoleEmailSender, EmailError
from backend.app.services.unsubscribe import read_token
from tests.helpers import auth_headers

API = "/api/v1"
DISPATCH = f"{API}/internal/reminders/dispatch"
SECRET = "secreto-de-cron-solo-para-pruebas-0123456789"
HEADERS = {"X-Cron-Secret": SECRET}
FORBIDDEN_IN_DISCREET = re.compile(
    r"mama|c[aá]ncer|cancer|breast|autoexplor|an[aá]lisis|ecograf|seno|tumor|bulto", re.I
)


class FakeSender:
    def __init__(self, fail_for: set[str] | None = None):
        self.sent = []
        self.fail_for = fail_for or set()
        self.lock = threading.Lock()

    def send(self, message):
        if message.to in self.fail_for:
            raise EmailError("proveedor caído")
        with self.lock:
            self.sent.append(message)


@pytest.fixture
def sender():
    fake = FakeSender()
    app.dependency_overrides[get_email_sender] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_email_sender, None)


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


def configure(client, user, kind="self_exam", **overrides):
    body = {
        "frequency": "first_sunday",
        "local_time": "09:00",
        "timezone": "America/Mexico_City",
        "channels": ["in_app", "email"],
        **overrides,
    }
    response = client.put(f"{API}/reminders/{kind}", json=body, headers=auth_headers(user))
    assert response.status_code == 200, response.text


def make_due(owner_engine, user=None, ago=timedelta(minutes=5)):
    """Vence recordatorios como dueño (preparación de datos; no cambia el reloj)."""
    where = "WHERE user_id = :u" if user else ""
    with owner_engine.begin() as conn:
        conn.execute(
            text(f"UPDATE control.reminders SET next_run_at = now() - :ago {where}"),
            {"ago": ago, "u": getattr(user, "id", None)},
        )


def notices(owner_engine):
    with owner_engine.connect() as conn:
        return conn.execute(
            text("SELECT user_id, kind, email_status FROM control.reminder_notices")
        ).all()


class TestSecreto:
    def test_sin_header_401(self, client, sender):
        assert client.post(DISPATCH).status_code == 401

    def test_secreto_incorrecto_401(self, client, sender):
        response = client.post(DISPATCH, headers={"X-Cron-Secret": SECRET + "x"})
        assert response.status_code == 401
        assert SECRET not in response.text

    def test_un_jwt_valido_no_sustituye_al_secreto(self, client, sender, world):
        assert client.post(DISPATCH, headers=auth_headers(world["a1"])).status_code == 401

    @pytest.mark.parametrize("value", [None, "", "corto"])
    def test_sin_secreto_configurado_503(self, client, sender, monkeypatch, value):
        if value is None:
            monkeypatch.delenv("REMINDER_CRON_SECRET", raising=False)
        else:
            monkeypatch.setenv("REMINDER_CRON_SECRET", value)
        response = client.post(DISPATCH, headers={"X-Cron-Secret": value or "x"})
        assert response.status_code == 503


class TestDespacho:
    def test_solo_los_vencidos_y_luego_se_reprograman(self, client, sender, world, owner_engine):
        configure(client, world["a1"])
        configure(client, world["a2"])
        configure(client, world["b1"])
        make_due(owner_engine, world["a1"])
        make_due(owner_engine, world["b1"])

        response = client.post(DISPATCH, headers=HEADERS)
        assert response.status_code == 200
        assert response.json() == {"claimed": 2, "emailed": 2, "failed": 0}
        assert {n.user_id for n in notices(owner_engine)} == {world["a1"].id, world["b1"].id}
        with owner_engine.connect() as conn:
            pending = conn.execute(
                text("SELECT count(*) FROM control.reminders WHERE next_run_at <= now()")
            ).scalar_one()
        assert pending == 0

    def test_es_idempotente(self, client, sender, world, owner_engine):
        configure(client, world["a1"])
        make_due(owner_engine, world["a1"])
        first = client.post(DISPATCH, headers=HEADERS).json()
        second = client.post(DISPATCH, headers=HEADERS).json()
        assert first["claimed"] == 1 and second == {"claimed": 0, "emailed": 0, "failed": 0}
        assert len(notices(owner_engine)) == 1
        assert len(sender.sent) == 1

    def test_despachos_concurrentes_no_duplican(self, client, world, owner_engine):
        for key in ("a1", "a2", "b1"):
            configure(client, world[key])
        make_due(owner_engine)
        fake = FakeSender()
        results = []

        def run():
            with new_session() as db:
                results.append(reminders.dispatch(db, fake))

        threads = [threading.Thread(target=run) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sum(r.claimed for r in results) == 3
        assert len(notices(owner_engine)) == 3
        assert len(fake.sent) == 3

    def test_atrasado_da_un_solo_aviso(self, client, sender, world, owner_engine):
        configure(client, world["a1"], frequency="every_n_days", interval_n=1)
        make_due(owner_engine, world["a1"], ago=timedelta(days=30))
        assert client.post(DISPATCH, headers=HEADERS).json()["claimed"] == 1
        assert len(notices(owner_engine)) == 1
        with owner_engine.connect() as conn:
            next_run = conn.execute(text("SELECT next_run_at FROM control.reminders")).scalar_one()
        assert datetime.now(UTC) < next_run <= datetime.now(UTC) + timedelta(days=1, minutes=1)

    def test_un_correo_fallido_no_detiene_a_los_demas(self, client, world, owner_engine):
        for key in ("a1", "a2", "b1"):
            configure(client, world[key])
        make_due(owner_engine)
        fake = FakeSender(fail_for={world["a2"].email})
        app.dependency_overrides[get_email_sender] = lambda: fake
        try:
            body = client.post(DISPATCH, headers=HEADERS).json()
        finally:
            app.dependency_overrides.pop(get_email_sender, None)
        assert body == {"claimed": 3, "emailed": 2, "failed": 1}
        statuses = {n.user_id: n.email_status for n in notices(owner_engine)}
        assert statuses[world["a2"].id] == "failed"
        assert statuses[world["a1"].id] == statuses[world["b1"].id] == "sent"

    def test_solo_en_la_app_no_envia_correo(self, client, sender, world, owner_engine):
        configure(client, world["a1"], channels=["in_app"])
        make_due(owner_engine, world["a1"])
        assert client.post(DISPATCH, headers=HEADERS).json() == {
            "claimed": 1,
            "emailed": 0,
            "failed": 0,
        }
        assert notices(owner_engine)[0].email_status == "none"
        assert sender.sent == []

    @pytest.mark.parametrize("what", ["usuario", "tenant", "recordatorio"])
    def test_inactivos_no_se_despachan(self, client, sender, world, owner_engine, what):
        configure(client, world["a1"])
        make_due(owner_engine, world["a1"])
        sql = {
            "usuario": "UPDATE control.users SET is_active = false WHERE id = :u",
            "tenant": "UPDATE control.tenants SET is_active = false WHERE id = :t",
            "recordatorio": "UPDATE control.reminders SET active = false WHERE user_id = :u",
        }[what]
        with owner_engine.begin() as conn:
            conn.execute(text(sql), {"u": world["a1"].id, "t": world["ta"].id})
        assert client.post(DISPATCH, headers=HEADERS).json()["claimed"] == 0
        assert notices(owner_engine) == []

    def test_aviso_visible_en_la_app_de_la_paciente(self, client, sender, world, owner_engine):
        configure(client, world["a1"])
        make_due(owner_engine, world["a1"])
        client.post(DISPATCH, headers=HEADERS)
        unread = client.get(f"{API}/notices?unread=true", headers=auth_headers(world["a1"]))
        assert [n["kind"] for n in unread.json()] == ["self_exam"]
        other = client.get(f"{API}/notices", headers=auth_headers(world["a2"])).json()
        assert other == []


class TestCorreo:
    def test_modo_discreto_no_revela_el_tema(self, client, sender, world, owner_engine):
        configure(client, world["a1"])
        configure(
            client, world["a1"], kind="repeat_analysis", frequency="every_n_months", interval_n=6
        )
        make_due(owner_engine, world["a1"])
        client.post(DISPATCH, headers=HEADERS)
        assert len(sender.sent) == 2
        for message in sender.sent:
            visible = f"{message.subject}\n{message.body.split('http')[0]}\n{message.from_name}"
            assert not FORBIDDEN_IN_DISCREET.search(visible), visible
            assert "/baja?token=" in message.body

    def test_sin_modo_discreto_lleva_marca_y_aviso(self, client, sender, world, owner_engine):
        configure(client, world["a1"], discreet=False)
        make_due(owner_engine, world["a1"])
        client.post(DISPATCH, headers=HEADERS)
        (message,) = sender.sent
        assert "BreastGuard" in message.subject
        assert "No sustituye" in message.body

    def test_el_enlace_de_baja_es_del_recordatorio_correcto(
        self, client, sender, world, owner_engine
    ):
        configure(client, world["a1"])
        make_due(owner_engine, world["a1"])
        client.post(DISPATCH, headers=HEADERS)
        token = sender.sent[0].body.split("token=")[1].strip()
        reminder_id, user_id = read_token(token)
        assert user_id == world["a1"].id
        response = client.post(f"{API}/reminders/unsubscribe", json={"token": token})
        assert response.status_code == 204
        with owner_engine.connect() as conn:
            channels = conn.execute(
                text("SELECT channels FROM control.reminders WHERE id = :id"), {"id": reminder_id}
            ).scalar_one()
        assert channels == ["in_app"]

    def test_los_logs_no_llevan_el_correo_completo(self, client, world, owner_engine, caplog):
        configure(client, world["a1"])
        make_due(owner_engine, world["a1"])
        app.dependency_overrides[get_email_sender] = ConsoleEmailSender
        try:
            with caplog.at_level("DEBUG"):
                client.post(DISPATCH, headers=HEADERS)
        finally:
            app.dependency_overrides.pop(get_email_sender, None)
        assert "Correo (consola)" in caplog.text
        assert world["a1"].email not in caplog.text
        assert "token=" not in caplog.text


class TestAislamiento:
    def test_el_despacho_nunca_toca_clinical_ni_usa_contexto(self, client, world, owner_engine):
        configure(client, world["a1"])
        configure(client, world["b1"])
        make_due(owner_engine)
        statements = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        engine = get_engine()
        event.listen(engine, "before_cursor_execute", capture)
        try:
            with new_session() as db:
                result = reminders.dispatch(db, FakeSender())
                tenant_setting = db.execute(
                    text("SELECT current_setting('app.tenant_id', true)")
                ).scalar_one()
                role = db.execute(text("SELECT current_user")).scalar_one()
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert result.claimed == 2
        assert statements, "no se capturó SQL: la prueba sería vacía"
        assert not [s for s in statements if "clinical." in s.lower()]
        assert tenant_setting in (None, "")
        with owner_engine.connect() as conn:
            assert not conn.execute(
                text("SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname = :r"),
                {"r": role},
            ).scalar_one()

    def test_la_sesion_del_despachador_no_ve_datos_clinicos(self, client, world):
        """Aunque alguien agregara una consulta a clinical, sin contexto vería 0 filas."""
        configure(client, world["a1"])
        with new_session() as db:
            count = db.execute(text("SELECT count(*) FROM clinical.patients")).scalar_one()
        assert count == 0


class TestHuerfanos:
    def _orphan(self, owner_engine, user, age):
        with owner_engine.begin() as conn:
            reminder_id = conn.execute(
                text("SELECT id FROM control.reminders WHERE user_id = :u"), {"u": user.id}
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO control.reminder_notices (tenant_id, user_id, reminder_id, kind, "
                    "due_at, email_status, created_at) VALUES (:t, :u, :r, 'self_exam', "
                    "now() - :age, 'pending', now() - :age)"
                ),
                {"t": user.tenant_id, "u": user.id, "r": reminder_id, "age": age},
            )

    def test_pending_viejo_se_reintenta_una_vez(self, client, sender, world, owner_engine):
        configure(client, world["a1"])
        self._orphan(owner_engine, world["a1"], timedelta(minutes=30))
        first = client.post(DISPATCH, headers=HEADERS).json()
        assert first == {"claimed": 0, "emailed": 1, "failed": 0}
        assert [n.email_status for n in notices(owner_engine)] == ["sent"]
        assert client.post(DISPATCH, headers=HEADERS).json()["emailed"] == 0

    def test_pending_reciente_no_se_toca(self, client, sender, world, owner_engine):
        configure(client, world["a1"])
        self._orphan(owner_engine, world["a1"], timedelta(minutes=1))
        assert client.post(DISPATCH, headers=HEADERS).json()["emailed"] == 0
        assert [n.email_status for n in notices(owner_engine)] == ["pending"]

    def test_tras_la_baja_no_se_reintenta(self, client, sender, world, owner_engine):
        configure(client, world["a1"], channels=["in_app"])
        self._orphan(owner_engine, world["a1"], timedelta(minutes=30))
        assert client.post(DISPATCH, headers=HEADERS).json()["emailed"] == 0
        assert sender.sent == []
