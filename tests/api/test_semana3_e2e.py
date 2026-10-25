"""Semana 3: flujo completo por API (CU-03 → CU-04 → CU-05) y aislamiento con datos reales.

Registro → autoexploración con "sí noté algo" → entrada del diario enlazada → recordatorio
vencido → despacho → aviso en la app → marcar leído. Sin cambiar el reloj: el vencimiento se
prepara como dueño. Otra paciente (otro tenant y la misma b2c) no ve nada de esto.
"""

from datetime import date

from sqlalchemy import text

from backend.app.api.v1.internal import get_email_sender
from backend.app.main import app
from tests.helpers import DEFAULT_PASSWORD, auth_headers, registration

API = "/api/v1"
CRON = {"X-Cron-Secret": "secreto-de-cron-solo-para-pruebas-0123456789"}


class Sender:
    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message)


def register_and_login(client, email) -> dict[str, str]:
    response = client.post(f"{API}/auth/register", json=registration(email))
    assert response.status_code == 201, response.text
    token = client.post(
        f"{API}/auth/token", data={"username": email, "password": DEFAULT_PASSWORD}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def audit_actions(owner_engine, actor_email):
    with owner_engine.connect() as conn:
        return [
            r.action
            for r in conn.execute(
                text(
                    "SELECT a.action FROM clinical.audit_log a JOIN control.users u "
                    "ON u.id = a.actor_id WHERE u.email = :e ORDER BY a.occurred_at"
                ),
                {"e": actor_email},
            )
        ]


def test_autoexploracion_diario_recordatorio_y_aviso(
    client, owner_engine, tenant_factory, user_factory
):
    sender = Sender()
    app.dependency_overrides[get_email_sender] = lambda: sender
    try:
        me = register_and_login(client, "flujo3@example.com")
        other_b2c = register_and_login(client, "otra3@example.com")
        clinic = tenant_factory("clinica-tres")
        other_tenant = auth_headers(user_factory(clinic, role="patient"))

        # 1. Autoexploración guiada: notó algo distinto
        guide = client.get(f"{API}/self-exam/guide").json()
        exam = client.post(f"{API}/self-exams", headers=me).json()
        finished = client.post(
            f"{API}/self-exams/{exam['id']}/finish",
            json={"noticed_change": "si", "note": "Zona dura arriba a la izquierda"},
            headers=me,
        )
        assert finished.status_code == 200 and guide["version"] == exam["content_version"]

        # 2. Entrada del diario prellenada y enlazada a esa autoexploración
        entry = client.post(
            f"{API}/symptoms",
            json={
                "entry_date": date.today().isoformat(),
                "side": "izquierdo",
                "zone": "superior_externo",
                "symptoms": ["bulto"],
                "intensity": 3,
                "self_exam_id": exam["id"],
                "in_period": False,
            },
            headers=me,
        )
        assert entry.status_code == 201, entry.text
        timeline = client.get(
            f"{API}/symptoms", params={"zone": "superior_externo"}, headers=me
        ).json()
        assert [e["self_exam_id"] for e in timeline["items"]] == [exam["id"]]

        # 3. Recordatorio de autoexploración (discreto, app + correo) que ya venció
        saved = client.put(
            f"{API}/reminders/self_exam",
            json={
                "frequency": "first_sunday",
                "local_time": "09:00",
                "timezone": "America/Tijuana",
                "channels": ["in_app", "email"],
            },
            headers=me,
        )
        assert saved.status_code == 200
        with owner_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE control.reminders SET next_run_at = now() - interval '1 minute' "
                    "WHERE user_id = (SELECT id FROM control.users WHERE email = :e)"
                ),
                {"e": "flujo3@example.com"},
            )

        # 4. El despachador (con el secreto) crea el aviso y "envía" el correo discreto
        dispatched = client.post(f"{API}/internal/reminders/dispatch", headers=CRON).json()
        assert dispatched == {"claimed": 1, "emailed": 1, "failed": 0}
        (mail,) = sender.sent
        assert mail.to == "flujo3@example.com" and "BreastGuard" not in mail.subject

        # 5. Aviso en la app y marcar leído
        unread = client.get(f"{API}/notices", params={"unread": True}, headers=me).json()
        assert [n["kind"] for n in unread] == ["self_exam"]
        read = client.post(f"{API}/notices/{unread[0]['id']}/read", headers=me)
        assert read.status_code == 204
        assert client.get(f"{API}/notices", params={"unread": True}, headers=me).json() == []

        # 6. Nadie más ve nada: otra paciente del mismo tenant b2c y una de otro tenant
        for headers in (other_b2c, other_tenant):
            assert client.get(f"{API}/self-exams", headers=headers).json()["total"] == 0
            assert client.get(f"{API}/symptoms", headers=headers).json()["total"] == 0
            assert client.get(f"{API}/reminders", headers=headers).json() == []
            assert client.get(f"{API}/notices", headers=headers).json() == []
            assert client.get(f"{API}/self-exams/{exam['id']}", headers=headers).status_code == 404
            missing = client.get(f"{API}/symptoms/{entry.json()['id']}", headers=headers)
            assert missing.status_code == 404

        # 7. Auditoría clínica completa y sin el texto de las notas
        actions = audit_actions(owner_engine, "flujo3@example.com")
        for action in ("self_exam.start", "self_exam.finish", "symptom.create", "symptom.list"):
            assert action in actions
        with owner_engine.connect() as conn:
            dump = conn.execute(
                text("SELECT string_agg(to_jsonb(a)::text, '') FROM clinical.audit_log a")
            ).scalar_one()
        assert "Zona dura" not in dump
    finally:
        app.dependency_overrides.pop(get_email_sender, None)
