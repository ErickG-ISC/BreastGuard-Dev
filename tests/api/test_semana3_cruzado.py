"""Semana 3 (CU-03 a CU-05): acceso cruzado con recursos reales en tres ejes e inyección de ids.

Ejes: la propia paciente (control positivo), otra paciente del mismo tenant (a2) y una paciente
de otro tenant (b1). Complementa a los módulos por endpoint: aquí se compara el CUERPO del 404
en todas las operaciones por id y se comprueba que el dueño conserva sus datos intactos.
"""

import uuid
from datetime import date

import pytest
from sqlalchemy import text

from tests.helpers import auth_headers

API = "/api/v1"
SECRET = "nota-secreta-semana3"
REMINDER = {
    "frequency": "first_sunday",
    "local_time": "09:00",
    "timezone": "America/Tijuana",
    "channels": ["in_app", "email"],
}
VICTIMS = ["a2", "b1"]


@pytest.fixture
def world(tenant_factory, user_factory):
    ta, tb = tenant_factory("clinica-a"), tenant_factory("clinica-b")
    return {
        "ta": ta,
        "tb": tb,
        "a1": user_factory(ta, role="patient"),
        "a2": user_factory(ta, role="patient"),
        "b1": user_factory(tb, role="patient"),
    }


def entry_body(**overrides) -> dict:
    return {
        "entry_date": date.today().isoformat(),
        "side": "izquierdo",
        "zone": "axila",
        "symptoms": ["dolor"],
        "intensity": 3,
        **overrides,
    }


def seed(client, owner_engine, user) -> dict:
    """Crea un recurso real de cada tipo para `user` y devuelve sus ids."""
    headers = auth_headers(user)
    exam = client.post(f"{API}/self-exams", headers=headers).json()
    done = client.post(
        f"{API}/self-exams/{exam['id']}/finish",
        json={"noticed_change": "si", "note": SECRET},
        headers=headers,
    )
    assert done.status_code == 200, done.text
    open_exam = client.post(f"{API}/self-exams", headers=headers).json()
    entry = client.post(f"{API}/symptoms", json=entry_body(note=SECRET), headers=headers)
    assert entry.status_code == 201, entry.text
    saved = client.put(f"{API}/reminders/self_exam", json=REMINDER, headers=headers)
    assert saved.status_code == 200
    with owner_engine.begin() as conn:
        reminder_id = conn.execute(
            text("SELECT id FROM control.reminders WHERE user_id = :u"), {"u": user.id}
        ).scalar_one()
        notice_id = conn.execute(
            text(
                "INSERT INTO control.reminder_notices (tenant_id, user_id, reminder_id, kind, "
                "due_at) VALUES (:t, :u, :r, 'self_exam', now()) RETURNING id"
            ),
            {"t": user.tenant_id, "u": user.id, "r": reminder_id},
        ).scalar_one()
    return {
        "exam": exam["id"],
        "open_exam": open_exam["id"],
        "entry": entry.json()["id"],
        "notice": str(notice_id),
    }


def snapshot(owner_engine) -> dict:
    tables = (
        "clinical.self_exams",
        "clinical.symptom_entries",
        "control.reminders",
        "control.reminder_notices",
    )
    with owner_engine.connect() as conn:
        return {
            table: conn.execute(
                text(f"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY t.id), '[]') FROM {table} t")
            ).scalar_one()
            for table in tables
        }


def calls_for(ids: dict) -> dict:
    """Operaciones por id: nombre -> (método, ruta, kwargs)."""
    return {
        "exam_get": ("GET", f"/self-exams/{ids['exam']}", {}),
        "exam_finish": (
            "POST",
            f"/self-exams/{ids['open_exam']}/finish",
            {"json": {"noticed_change": "no"}},
        ),
        "exam_delete": ("DELETE", f"/self-exams/{ids['exam']}", {}),
        "symptom_get": ("GET", f"/symptoms/{ids['entry']}", {}),
        "symptom_patch": ("PATCH", f"/symptoms/{ids['entry']}", {"json": {"intensity": 0}}),
        "symptom_delete": ("DELETE", f"/symptoms/{ids['entry']}", {}),
        "notice_read": ("POST", f"/notices/{ids['notice']}/read", {}),
    }


ID_KEYS = ("exam", "open_exam", "entry", "notice")
CALL_NAMES = list(calls_for(dict.fromkeys(ID_KEYS, "x")))


def run(client, call, headers):
    method, path, kwargs = call
    return client.request(method, f"{API}{path}", headers=headers, **kwargs)


class TestControlPositivo:
    def test_la_propia_paciente_ve_y_modifica_lo_suyo(self, client, world, owner_engine):
        ids = seed(client, owner_engine, world["a1"])
        headers = auth_headers(world["a1"])
        calls = calls_for(ids)
        assert run(client, calls["exam_get"], headers).status_code == 200
        assert run(client, calls["symptom_get"], headers).status_code == 200
        patch = run(client, calls["symptom_patch"], headers)
        assert patch.status_code == 200 and patch.json()["intensity"] == 0
        assert run(client, calls["exam_finish"], headers).status_code == 200
        reminders = client.get(f"{API}/reminders", headers=headers).json()
        assert [r["kind"] for r in reminders] == ["self_exam"]
        notices = client.get(f"{API}/notices", headers=headers).json()
        assert [n["id"] for n in notices] == [ids["notice"]]
        assert run(client, calls["notice_read"], headers).status_code == 204
        assert run(client, calls["exam_delete"], headers).status_code == 204
        assert run(client, calls["symptom_delete"], headers).status_code == 204


class TestRecursosAjenos:
    @pytest.mark.parametrize("victim", VICTIMS)
    @pytest.mark.parametrize("name", CALL_NAMES)
    def test_404_con_el_mismo_cuerpo_que_un_id_inexistente(
        self, client, world, owner_engine, victim, name
    ):
        ids = seed(client, owner_engine, world[victim])
        headers = auth_headers(world["a1"])
        missing_ids = {k: str(uuid.uuid4()) for k in ID_KEYS}

        theirs = run(client, calls_for(ids)[name], headers)
        missing = run(client, calls_for(missing_ids)[name], headers)

        assert theirs.status_code == missing.status_code == 404
        assert theirs.json() == missing.json()
        assert SECRET not in theirs.text

    @pytest.mark.parametrize("victim", VICTIMS)
    def test_tras_los_ataques_la_victima_ve_sus_datos_intactos(
        self, client, world, owner_engine, victim
    ):
        ids = seed(client, owner_engine, world[victim])
        before = snapshot(owner_engine)
        headers = auth_headers(world["a1"])
        for call in calls_for(ids).values():
            assert run(client, call, headers).status_code == 404
        # Listados del atacante: vacíos
        for path in ("/self-exams", "/symptoms"):
            assert client.get(f"{API}{path}", headers=headers).json()["total"] == 0
        assert client.get(f"{API}/reminders", headers=headers).json() == []
        assert client.get(f"{API}/notices", headers=headers).json() == []

        assert snapshot(owner_engine) == before
        owner = auth_headers(world[victim])
        assert client.get(f"{API}/self-exams/{ids['exam']}", headers=owner).status_code == 200
        symptom = client.get(f"{API}/symptoms/{ids['entry']}", headers=owner).json()
        assert symptom["intensity"] == 3
        assert client.get(f"{API}/self-exams", headers=owner).json()["total"] == 2
        unread = client.get(f"{API}/notices?unread=true", headers=owner).json()
        assert [n["id"] for n in unread] == [ids["notice"]]
        assert len(client.get(f"{API}/reminders", headers=owner).json()) == 1

    def test_el_atacante_no_deja_rastro_en_el_log_de_la_victima(self, client, world, owner_engine):
        ids = seed(client, owner_engine, world["b1"])
        for call in calls_for(ids).values():
            run(client, call, auth_headers(world["a1"]))
        with owner_engine.connect() as conn:
            actors = {
                r.actor_id
                for r in conn.execute(
                    text("SELECT actor_id FROM clinical.audit_log WHERE tenant_id = :t"),
                    {"t": world["tb"].id},
                )
            }
        assert world["a1"].id not in actors


class TestInyeccionDeIdentificadores:
    def spoof(self, world, victim="b1"):
        target = world[victim]
        params = {
            "tenant_id": str(target.tenant_id),
            "user_id": str(target.id),
            "patient_id": str(target.patient_id),
        }
        headers = {
            "X-Tenant-Id": params["tenant_id"],
            "X-User-Id": params["user_id"],
            "X-Patient-Id": params["patient_id"],
            "X-Role": "platform_admin",
        }
        return params, headers

    @pytest.mark.parametrize("victim", VICTIMS)
    def test_lecturas_ignoran_query_y_headers(self, client, world, owner_engine, victim):
        ids = seed(client, owner_engine, world[victim])
        params, extra = self.spoof(world, victim)
        headers = {**auth_headers(world["a1"]), **extra}
        for path in ("/self-exams", "/symptoms", "/reminders", "/notices"):
            response = client.get(f"{API}{path}", params=params, headers=headers)
            assert response.status_code == 200
            body = response.json()
            assert (body["items"] if isinstance(body, dict) else body) == []
        latest = client.get(f"{API}/self-exams/latest", params=params, headers=headers)
        assert latest.status_code == 404
        for path in (f"/self-exams/{ids['exam']}", f"/symptoms/{ids['entry']}"):
            assert client.get(f"{API}{path}", params=params, headers=headers).status_code == 404

    def test_creaciones_quedan_en_el_tenant_y_ficha_del_jwt(self, client, world, owner_engine):
        params, extra = self.spoof(world)
        headers = {**auth_headers(world["a1"]), **extra}
        exam = client.post(f"{API}/self-exams", params=params, headers=headers)
        entry = client.post(f"{API}/symptoms", params=params, headers=headers, json=entry_body())
        reminder = client.put(
            f"{API}/reminders/self_exam", params=params, headers=headers, json=REMINDER
        )
        assert (exam.status_code, entry.status_code, reminder.status_code) == (201, 201, 200)
        a1 = world["a1"]
        with owner_engine.connect() as conn:
            for table in ("clinical.self_exams", "clinical.symptom_entries"):
                rows = conn.execute(text(f"SELECT tenant_id, patient_id FROM {table}")).all()
                assert [(r.tenant_id, r.patient_id) for r in rows] == [
                    (a1.tenant_id, a1.patient_id)
                ]
            row = conn.execute(text("SELECT tenant_id, user_id FROM control.reminders")).one()
            assert (row.tenant_id, row.user_id) == (a1.tenant_id, a1.id)

    @pytest.mark.parametrize("key", ["tenant_id", "user_id", "patient_id"])
    def test_cuerpo_con_identificadores_no_cambia_el_dueno(self, client, world, owner_engine, key):
        """Se rechaza (422) o se ignora; en ningún caso se crea nada a nombre de otro."""
        params, _ = self.spoof(world)
        headers = auth_headers(world["a1"])
        response = client.post(
            f"{API}/symptoms", json=entry_body(**{key: params[key]}), headers=headers
        )
        assert response.status_code in (201, 422)
        reminder = client.put(
            f"{API}/reminders/self_exam", json={**REMINDER, key: params[key]}, headers=headers
        )
        assert reminder.status_code in (200, 422)
        with owner_engine.connect() as conn:
            patients = conn.execute(text("SELECT patient_id FROM clinical.symptom_entries")).all()
            users = conn.execute(text("SELECT user_id FROM control.reminders")).all()
        assert all(r.patient_id == world["a1"].patient_id for r in patients)
        assert all(r.user_id == world["a1"].id for r in users)

    def test_header_de_rol_no_eleva_privilegios(self, client, world):
        headers = {**auth_headers(world["a1"]), "X-Role": "platform_admin", "X-Tenant-Id": "x"}
        assert client.get(f"{API}/auth/me", headers=headers).json()["role"] == "patient"
