"""CU-04: diario de síntomas (CRUD, filtros, enlace con autoexploración y acceso cruzado)."""

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from backend.app.services import symptoms as symptoms_service
from backend.app.services.auth import AuthContext
from tests.helpers import auth_headers, tenant_session

API = "/api/v1"
SECRET_NOTE = "nota-secreta-del-diario"


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


def entry_body(**overrides) -> dict:
    return {
        "entry_date": date.today().isoformat(),
        "side": "izquierdo",
        "zone": "superior_externo",
        "symptoms": ["bulto"],
        "intensity": 4,
        **overrides,
    }


def create_entry(client, user, **overrides) -> dict:
    response = client.post(
        f"{API}/symptoms", json=entry_body(**overrides), headers=auth_headers(user)
    )
    assert response.status_code == 201, response.text
    return response.json()


def finished_self_exam(client, user) -> dict:
    exam = client.post(f"{API}/self-exams", headers=auth_headers(user)).json()
    response = client.post(
        f"{API}/self-exams/{exam['id']}/finish",
        json={"noticed_change": "si"},
        headers=auth_headers(user),
    )
    assert response.status_code == 200
    return response.json()


def audit_actions(owner_engine, tenant_id) -> list[tuple]:
    with owner_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT action, resource_id FROM clinical.audit_log "
                "WHERE tenant_id = :t ORDER BY occurred_at"
            ),
            {"t": tenant_id},
        ).all()


def auth_context(user, tenant) -> AuthContext:
    return AuthContext(
        user_id=user.id, tenant_id=user.tenant_id, tenant_slug=tenant.slug, role=user.role
    )


class TestCrud:
    def test_crear_leer_editar_y_borrar(self, client, world, owner_engine):
        a1 = world["a1"]
        headers = auth_headers(a1)
        created = create_entry(
            client, a1, symptoms=["dolor", "sensibilidad"], note=" Me duele ", in_period=True
        )
        assert created["note"] == "Me duele"
        assert created["in_period"] is True and created["updated_at"] is None

        got = client.get(f"{API}/symptoms/{created['id']}", headers=headers)
        assert got.status_code == 200 and got.json()["symptoms"] == ["dolor", "sensibilidad"]

        patched = client.patch(
            f"{API}/symptoms/{created['id']}",
            json={"intensity": 8, "note": None, "cycle_day": 14},
            headers=headers,
        )
        assert patched.status_code == 200, patched.text
        body = patched.json()
        assert body["intensity"] == 8 and body["note"] is None and body["cycle_day"] == 14
        assert body["zone"] == "superior_externo"  # lo no enviado no cambia
        assert body["updated_at"] is not None

        assert client.delete(f"{API}/symptoms/{created['id']}", headers=headers).status_code == 204
        assert client.get(f"{API}/symptoms/{created['id']}", headers=headers).status_code == 404
        with owner_engine.connect() as conn:
            remaining = conn.execute(text("SELECT count(*) FROM clinical.symptom_entries"))
            assert remaining.scalar_one() == 0

    @pytest.mark.parametrize(
        "overrides",
        [
            {"side": "centro"},
            {"zone": "espalda"},
            {"symptoms": []},
            {"symptoms": ["bulto", "bulto"]},
            {"symptoms": ["picazon"]},
            {"intensity": 11},
            {"intensity": -1},
            {"note": "x" * 2001},
            {"note": "a\x00b"},
            {"cycle_day": 0},
            {"cycle_day": 61},
            {"entry_date": (date.today() + timedelta(days=5)).isoformat()},
            {"tenant_id": str(uuid.uuid4())},
            {"patient_id": str(uuid.uuid4())},
        ],
    )
    def test_entrada_invalida_422(self, client, world, overrides):
        response = client.post(
            f"{API}/symptoms", json=entry_body(**overrides), headers=auth_headers(world["a1"])
        )
        assert response.status_code == 422

    @pytest.mark.parametrize("field", ["side", "zone", "symptoms", "intensity", "entry_date"])
    def test_patch_no_acepta_nulos_en_obligatorios(self, client, world, field):
        entry = create_entry(client, world["a1"])
        response = client.patch(
            f"{API}/symptoms/{entry['id']}", json={field: None}, headers=auth_headers(world["a1"])
        )
        assert response.status_code == 422

    def test_auditoria_sin_contenido_de_la_nota(self, client, world, owner_engine, caplog):
        a1 = world["a1"]
        with caplog.at_level("DEBUG"):
            entry = create_entry(client, a1, note=SECRET_NOTE)
            client.get(f"{API}/symptoms", headers=auth_headers(a1))
            client.get(f"{API}/symptoms/{entry['id']}", headers=auth_headers(a1))
            client.patch(
                f"{API}/symptoms/{entry['id']}", json={"intensity": 1}, headers=auth_headers(a1)
            )
            client.delete(f"{API}/symptoms/{entry['id']}", headers=auth_headers(a1))
        actions = [a for a, _ in audit_actions(owner_engine, world["ta"].id)]
        assert actions == [
            "symptom.create",
            "symptom.list",
            "symptom.read",
            "symptom.update",
            "symptom.delete",
        ]
        with owner_engine.connect() as conn:
            dump = conn.execute(
                text("SELECT string_agg(to_jsonb(a)::text, '') FROM clinical.audit_log a")
            ).scalar_one()
        assert SECRET_NOTE not in dump
        assert SECRET_NOTE not in caplog.text


class TestLineaDeTiempo:
    def test_filtros(self, client, world):
        a1 = world["a1"]
        old = (date.today() - timedelta(days=40)).isoformat()
        create_entry(client, a1, entry_date=old, symptoms=["dolor"], zone="axila")
        create_entry(client, a1, symptoms=["bulto", "dolor"], side="derecho")
        create_entry(client, a1, symptoms=["secrecion"], zone="areola_pezon", side="ambos")
        headers = auth_headers(a1)

        def ids(**params):
            response = client.get(f"{API}/symptoms", params=params, headers=headers)
            assert response.status_code == 200, response.text
            return response.json()

        assert ids()["total"] == 3
        assert ids(symptom="dolor")["total"] == 2
        assert ids(zone="axila")["total"] == 1
        # "ambos" también aparece al filtrar por un lado
        assert ids(side="izquierdo")["total"] == 2
        recent = (date.today() - timedelta(days=7)).isoformat()
        assert ids(**{"from": recent})["total"] == 2
        assert ids(**{"to": recent})["total"] == 1
        assert ids(symptom="dolor", zone="axila", **{"from": recent})["total"] == 0
        # Orden: la más reciente primero
        items = ids()["items"]
        assert items[-1]["entry_date"] == old

    @pytest.mark.parametrize("params", [{"symptom": "x"}, {"zone": "x"}, {"from": "ayer"}])
    def test_filtros_invalidos_422(self, client, world, params):
        response = client.get(f"{API}/symptoms", params=params, headers=auth_headers(world["a1"]))
        assert response.status_code == 422

    def test_get_entries_desde_una_fecha_solo_propias(self, client, world):
        a1, a2 = world["a1"], world["a2"]
        create_entry(client, a1, entry_date=(date.today() - timedelta(days=120)).isoformat())
        recent = create_entry(
            client, a1, entry_date=(date.today() - timedelta(days=10)).isoformat()
        )
        newest = create_entry(client, a1)
        create_entry(client, a2)
        since = date.today() - timedelta(days=90)
        with tenant_session(a1) as session:
            entries = symptoms_service.get_entries(session, auth_context(a1, world["ta"]), since)
        assert [str(e.id) for e in entries] == [recent["id"], newest["id"]]


class TestEnlaceConAutoexploracion:
    def test_enlaza_y_al_borrar_la_autoexploracion_solo_se_anula_el_enlace(self, client, world):
        a1 = world["a1"]
        exam = finished_self_exam(client, a1)
        entry = create_entry(client, a1, self_exam_id=exam["id"])
        assert entry["self_exam_id"] == exam["id"]
        headers = auth_headers(a1)
        assert client.delete(f"{API}/self-exams/{exam['id']}", headers=headers).status_code == 204
        after = client.get(f"{API}/symptoms/{entry['id']}", headers=headers).json()
        assert after["self_exam_id"] is None

    @pytest.mark.parametrize("victim", ["a2", "b1"])
    def test_no_enlaza_autoexploraciones_ajenas(self, client, world, victim, owner_engine):
        exam = finished_self_exam(client, world[victim])
        response = client.post(
            f"{API}/symptoms",
            json=entry_body(self_exam_id=exam["id"]),
            headers=auth_headers(world["a1"]),
        )
        assert response.status_code == 404
        assert ("self_exam.denied", uuid.UUID(exam["id"])) in audit_actions(
            owner_engine, world["ta"].id
        )
        mine = create_entry(client, world["a1"])
        patched = client.patch(
            f"{API}/symptoms/{mine['id']}",
            json={"self_exam_id": exam["id"]},
            headers=auth_headers(world["a1"]),
        )
        assert patched.status_code == 404

    def test_la_base_impide_enlazar_la_autoexploracion_de_otra_paciente(self, client, world):
        """Aunque el servicio fallara, la FK con patient_id lo impide (las FKs no pasan por RLS)."""
        a1, a2 = world["a1"], world["a2"]
        exam_a2 = finished_self_exam(client, a2)
        with tenant_session(a1) as session, pytest.raises(DBAPIError, match="foreign key"):
            session.execute(
                text(
                    "INSERT INTO clinical.symptom_entries (patient_id, created_by, entry_date, "
                    "side, zone, symptoms, intensity, self_exam_id) VALUES (:p, :u, current_date, "
                    "'izquierdo', 'axila', ARRAY['bulto'], 1, :e)"
                ),
                {"p": a1.patient_id, "u": a1.id, "e": exam_a2["id"]},
            )


VICTIMS = ["b1", "a2"]


class TestAccesoCruzado:
    @pytest.fixture
    def victim_entry(self, client, world, request):
        victim = world[request.param]
        return victim, create_entry(client, victim, note=SECRET_NOTE)

    @pytest.mark.parametrize("victim_entry", VICTIMS, indirect=True)
    def test_detalle_ajeno_404_igual_que_inexistente(self, client, world, victim_entry):
        _, entry = victim_entry
        headers = auth_headers(world["a1"])
        theirs = client.get(f"{API}/symptoms/{entry['id']}", headers=headers)
        missing = client.get(f"{API}/symptoms/{uuid.uuid4()}", headers=headers)
        assert theirs.status_code == missing.status_code == 404
        assert theirs.json() == missing.json()
        assert SECRET_NOTE not in theirs.text

    @pytest.mark.parametrize("victim_entry", VICTIMS, indirect=True)
    def test_no_puede_editar_ni_borrar_lo_ajeno(self, client, world, victim_entry, owner_engine):
        _, entry = victim_entry
        headers = auth_headers(world["a1"])

        def snapshot():
            with owner_engine.connect() as conn:
                return conn.execute(
                    text("SELECT to_jsonb(s) FROM clinical.symptom_entries s WHERE id = :id"),
                    {"id": entry["id"]},
                ).scalar_one()

        before = snapshot()
        patch = client.patch(
            f"{API}/symptoms/{entry['id']}", json={"intensity": 0}, headers=headers
        )
        assert patch.status_code == 404
        assert client.delete(f"{API}/symptoms/{entry['id']}", headers=headers).status_code == 404
        assert snapshot() == before

    @pytest.mark.parametrize("victim_entry", VICTIMS, indirect=True)
    def test_la_linea_de_tiempo_no_incluye_lo_ajeno(self, client, world, victim_entry):
        page = client.get(f"{API}/symptoms", headers=auth_headers(world["a1"])).json()
        assert page["total"] == 0 and page["items"] == []

    @pytest.mark.parametrize("victim_entry", VICTIMS, indirect=True)
    def test_get_entries_no_incluye_lo_ajeno(self, world, victim_entry):
        a1 = world["a1"]
        with tenant_session(a1) as session:
            entries = symptoms_service.get_entries(
                session, auth_context(a1, world["ta"]), date(2000, 1, 1)
            )
        assert entries == []

    @pytest.mark.parametrize("victim_entry", VICTIMS, indirect=True)
    def test_el_intento_se_audita_en_el_tenant_del_atacante(
        self, client, world, victim_entry, owner_engine
    ):
        victim, entry = victim_entry
        client.get(f"{API}/symptoms/{entry['id']}", headers=auth_headers(world["a1"]))
        assert ("symptom.denied", uuid.UUID(entry["id"])) in audit_actions(
            owner_engine, world["ta"].id
        )
        if victim.tenant_id != world["a1"].tenant_id:
            assert all(
                action != "symptom.denied"
                for action, _ in audit_actions(owner_engine, victim.tenant_id)
            )

    @pytest.mark.parametrize("role", ["doctor", "tenant_admin"])
    def test_el_personal_no_usa_el_diario(self, client, world, user_factory, role):
        staff = user_factory(world["ta"], role=role)
        response = client.post(f"{API}/symptoms", json=entry_body(), headers=auth_headers(staff))
        assert response.status_code == 403
