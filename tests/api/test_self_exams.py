"""CU-03: autoexploración guiada (guía pública, iniciar, terminar, historial y acceso cruzado)."""

import uuid

import pytest
from sqlalchemy import text

from tests.helpers import auth_headers

API = "/api/v1"
SECRET_NOTE = "nota-secreta-de-la-paciente"


@pytest.fixture
def world(tenant_factory, user_factory):
    """Clínica A con dos pacientes (a1, a2) y clínica B con una (b1)."""
    tenant_a, tenant_b = tenant_factory("clinica-a"), tenant_factory("clinica-b")
    return {
        "ta": tenant_a,
        "tb": tenant_b,
        "a1": user_factory(tenant_a, role="patient"),
        "a2": user_factory(tenant_a, role="patient"),
        "b1": user_factory(tenant_b, role="patient"),
    }


def start(client, user) -> dict:
    response = client.post(f"{API}/self-exams", headers=auth_headers(user))
    assert response.status_code == 201, response.text
    return response.json()


def finish(client, user, exam_id, **body):
    payload = {"noticed_change": "no", **body}
    return client.post(
        f"{API}/self-exams/{exam_id}/finish", json=payload, headers=auth_headers(user)
    )


def audit_actions(owner_engine, tenant_id) -> list[tuple]:
    with owner_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT action, resource_id FROM clinical.audit_log "
                "WHERE tenant_id = :t ORDER BY occurred_at"
            ),
            {"t": tenant_id},
        ).all()


class TestGuia:
    def test_es_publica_versionada_y_borrador(self, client):
        response = client.get(f"{API}/self-exam/guide")
        assert response.status_code == 200
        guide = response.json()
        assert guide["version"] == "v1"
        assert guide["status"] == "borrador"
        assert len(guide["steps"]) == 6
        assert all(step["instructions"] and step["look_for"] for step in guide["steps"])
        assert "No sustituye" in guide["disclaimer"]

    def test_tono_sin_promesas_de_deteccion(self, client):
        text_all = client.get(f"{API}/self-exam/guide").text.lower()
        for phrase in ("detecta el cáncer", "descarta", "diagnostica", "estás sana"):
            assert phrase not in text_all


class TestFlujo:
    def test_iniciar_terminar_y_ultima(self, client, world):
        a1 = world["a1"]
        exam = start(client, a1)
        assert exam["finished_at"] is None and exam["noticed_change"] is None
        assert exam["content_version"] == "v1"

        # Sin terminar no cuenta como "la vez pasada"
        assert client.get(f"{API}/self-exams/latest", headers=auth_headers(a1)).status_code == 404

        done = finish(client, a1, exam["id"], noticed_change="si", note="  Bulto pequeño  ")
        assert done.status_code == 200, done.text
        assert done.json()["noticed_change"] == "si"
        assert done.json()["note"] == "Bulto pequeño"
        assert done.json()["finished_at"] is not None

        latest = client.get(f"{API}/self-exams/latest", headers=auth_headers(a1))
        assert latest.status_code == 200 and latest.json()["id"] == exam["id"]

    def test_terminar_dos_veces_409(self, client, world):
        exam = start(client, world["a1"])
        assert finish(client, world["a1"], exam["id"]).status_code == 200
        assert finish(client, world["a1"], exam["id"], noticed_change="si").status_code == 409

    @pytest.mark.parametrize(
        "body",
        [
            {"noticed_change": "quizas"},
            {"noticed_change": "no", "note": "x" * 1001},
            {"noticed_change": "no", "tenant_id": str(uuid.uuid4())},
            {"noticed_change": "no", "patient_id": str(uuid.uuid4())},
        ],
    )
    def test_entrada_invalida_422(self, client, world, body):
        exam = start(client, world["a1"])
        response = client.post(
            f"{API}/self-exams/{exam['id']}/finish", json=body, headers=auth_headers(world["a1"])
        )
        assert response.status_code == 422

    def test_nota_vacia_se_guarda_como_nula(self, client, world):
        exam = start(client, world["a1"])
        assert finish(client, world["a1"], exam["id"], note="   ").json()["note"] is None

    def test_historial_paginado_solo_propio(self, client, world):
        for _ in range(3):
            start(client, world["a1"])
        start(client, world["a2"])
        page = client.get(f"{API}/self-exams?limit=2", headers=auth_headers(world["a1"])).json()
        assert page["total"] == 3 and len(page["items"]) == 2

    def test_eliminar(self, client, world, owner_engine):
        exam = start(client, world["a1"])
        headers = auth_headers(world["a1"])
        assert client.delete(f"{API}/self-exams/{exam['id']}", headers=headers).status_code == 204
        assert client.get(f"{API}/self-exams/{exam['id']}", headers=headers).status_code == 404
        with owner_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM clinical.self_exams")).scalar_one() == 0

    def test_auditoria_sin_contenido_de_la_nota(self, client, world, owner_engine):
        a1 = world["a1"]
        exam = start(client, a1)
        finish(client, a1, exam["id"], noticed_change="si", note=SECRET_NOTE)
        client.get(f"{API}/self-exams/{exam['id']}", headers=auth_headers(a1))
        client.get(f"{API}/self-exams", headers=auth_headers(a1))
        actions = [a for a, _ in audit_actions(owner_engine, world["ta"].id)]
        assert actions == [
            "self_exam.start",
            "self_exam.finish",
            "self_exam.read",
            "self_exam.list",
        ]
        with owner_engine.connect() as conn:
            dump = conn.execute(
                text("SELECT string_agg(to_jsonb(a)::text, '') FROM clinical.audit_log a")
            ).scalar_one()
        assert SECRET_NOTE not in dump

    def test_la_nota_no_aparece_en_los_logs(self, client, world, caplog):
        exam = start(client, world["a1"])
        with caplog.at_level("DEBUG"):
            finish(client, world["a1"], exam["id"], noticed_change="si", note=SECRET_NOTE)
        assert SECRET_NOTE not in caplog.text


# a1 ataca recursos de b1 (otro tenant) y de a2 (misma clínica, otra paciente)
VICTIMS = ["b1", "a2"]


class TestAccesoCruzado:
    @pytest.fixture
    def victim_exam(self, client, world, request):
        victim = world[request.param]
        exam = start(client, victim)
        assert finish(client, victim, exam["id"], noticed_change="si", note=SECRET_NOTE)
        return victim, exam

    @pytest.mark.parametrize("victim_exam", VICTIMS, indirect=True)
    def test_detalle_ajeno_404_igual_que_inexistente(self, client, world, victim_exam):
        _, exam = victim_exam
        headers = auth_headers(world["a1"])
        theirs = client.get(f"{API}/self-exams/{exam['id']}", headers=headers)
        missing = client.get(f"{API}/self-exams/{uuid.uuid4()}", headers=headers)
        assert theirs.status_code == missing.status_code == 404
        assert theirs.json() == missing.json()
        assert SECRET_NOTE not in theirs.text

    @pytest.mark.parametrize("victim_exam", VICTIMS, indirect=True)
    def test_no_puede_terminar_ni_borrar_lo_ajeno(self, client, world, victim_exam, owner_engine):
        victim, exam = victim_exam
        headers = auth_headers(world["a1"])
        with owner_engine.connect() as conn:
            before = conn.execute(
                text("SELECT to_jsonb(s) FROM clinical.self_exams s WHERE id = :id"),
                {"id": exam["id"]},
            ).scalar_one()
        assert finish(client, world["a1"], exam["id"]).status_code == 404
        assert client.delete(f"{API}/self-exams/{exam['id']}", headers=headers).status_code == 404
        with owner_engine.connect() as conn:
            after = conn.execute(
                text("SELECT to_jsonb(s) FROM clinical.self_exams s WHERE id = :id"),
                {"id": exam["id"]},
            ).scalar_one()
        assert after == before

    @pytest.mark.parametrize("victim_exam", VICTIMS, indirect=True)
    def test_listas_y_ultima_no_incluyen_lo_ajeno(self, client, world, victim_exam):
        headers = auth_headers(world["a1"])
        assert client.get(f"{API}/self-exams", headers=headers).json()["total"] == 0
        assert client.get(f"{API}/self-exams/latest", headers=headers).status_code == 404

    @pytest.mark.parametrize("victim_exam", VICTIMS, indirect=True)
    def test_el_intento_se_audita_en_el_tenant_del_atacante(
        self, client, world, victim_exam, owner_engine
    ):
        victim, exam = victim_exam
        client.get(f"{API}/self-exams/{exam['id']}", headers=auth_headers(world["a1"]))
        rows = audit_actions(owner_engine, world["ta"].id)
        assert ("self_exam.denied", uuid.UUID(exam["id"])) in rows
        if victim.tenant_id != world["a1"].tenant_id:
            victim_rows = audit_actions(owner_engine, victim.tenant_id)
            assert all(action != "self_exam.denied" for action, _ in victim_rows)

    @pytest.mark.parametrize("role", ["doctor", "tenant_admin"])
    def test_el_personal_no_usa_endpoints_de_paciente(self, client, world, user_factory, role):
        staff = user_factory(world["ta"], role=role)
        assert client.post(f"{API}/self-exams", headers=auth_headers(staff)).status_code == 403
