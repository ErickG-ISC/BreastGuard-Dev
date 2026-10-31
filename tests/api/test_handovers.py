"""Traspaso de pacientes entre médicas (0014): la administración lo crea sin ver datos clínicos
y la médica de destino lo acepta con su propio contexto.

Incluye acceso cruzado entre tenants y entre médicas del mismo tenant.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.helpers import auth_headers, tenant_session
from tests.isolation.test_rls_por_tabla import RECIPES, seed
from tests.pgtest import TEST_APP_ROLE

API = "/api/v1"


@pytest.fixture
def clinics(tenant_factory, user_factory):
    data = {}
    for key in ("a", "b"):
        tenant = tenant_factory(f"clinica-{key}")
        data[key] = {
            "tenant": tenant,
            "admin": user_factory(tenant, role="tenant_admin"),
            "doc1": user_factory(tenant, role="doctor"),
            "doc2": user_factory(tenant, role="doctor"),
            "doc3": user_factory(tenant, role="doctor"),
        }
    return data["a"], data["b"]


def visible_patients(user) -> set:
    with tenant_session(user) as session:
        return set(session.scalars(text("SELECT id FROM clinical.patients")))


def create(client, actor, source, target, *, platform=False):
    prefix = "admin" if platform else "institution"
    return client.post(
        f"{API}/{prefix}/users/{source.id}/handover",
        json={"to_user_id": str(target.id)},
        headers=auth_headers(actor),
    )


def accept(client, doctor, handover_id):
    return client.post(f"{API}/doctor/handovers/{handover_id}/accept", headers=auth_headers(doctor))


def responsibles(owner_engine, ids) -> set:
    with owner_engine.connect() as conn:
        return set(
            conn.scalars(
                text("SELECT responsible_doctor_id FROM clinical.patients WHERE id = ANY(:ids)"),
                {"ids": list(ids)},
            )
        )


class TestFlujo:
    def test_traspaso_completo(self, client, owner_engine, clinics):
        a, _ = clinics
        mine = {seed(owner_engine, "patients", a["tenant"], a["doc1"]).id for _ in range(3)}
        analysis = seed(owner_engine, "analyses", a["tenant"], a["doc1"])
        mine.add(analysis.parents["patient_id"])
        assert visible_patients(a["doc2"]) == set()

        response = create(client, a["admin"], a["doc1"], a["doc2"])
        assert response.status_code == 201
        handover = response.json()
        assert handover["status"] == "pending" and handover["patients_moved"] is None

        # Pendiente: la de destino ya las ve (y lo que depende de ellas); la admin, nada
        assert visible_patients(a["doc2"]) == mine
        with tenant_session(a["doc2"]) as session:
            ids = set(session.scalars(text("SELECT id FROM clinical.analyses")))
        assert ids == {analysis.id}
        assert visible_patients(a["admin"]) == set()

        pending = client.get(f"{API}/doctor/handovers", headers=auth_headers(a["doc2"])).json()
        assert [p["id"] for p in pending] == [handover["id"]]
        assert client.get(f"{API}/doctor/handovers", headers=auth_headers(a["doc3"])).json() == []

        accepted = accept(client, a["doc2"], handover["id"])
        assert accepted.status_code == 200 and accepted.json() == {"patients_moved": 4}
        assert responsibles(owner_engine, mine) == {a["doc2"].id}
        assert visible_patients(a["doc1"]) == set()
        assert visible_patients(a["doc2"]) == mine

        listed = client.get(f"{API}/institution/handovers", headers=auth_headers(a["admin"]))
        (item,) = listed.json()["items"]
        assert item["status"] == "accepted" and item["patients_moved"] == 4
        with owner_engine.connect() as conn:
            audit = conn.execute(
                text(
                    "SELECT actor_id, resource_id FROM clinical.audit_log "
                    "WHERE action = 'patients.handover_accept'"
                )
            ).all()
            events = list(
                conn.scalars(
                    text(
                        "SELECT action FROM control.admin_events WHERE tenant_id = :t "
                        "ORDER BY occurred_at"
                    ),
                    {"t": a["tenant"].id},
                )
            )
        assert [(r.actor_id, str(r.resource_id)) for r in audit] == [(a["doc2"].id, handover["id"])]
        assert events == ["handover.create", "handover.accept"]

    def test_funciona_con_la_medica_de_origen_desactivada(self, client, owner_engine, clinics):
        a, _ = clinics
        patient = seed(owner_engine, "patients", a["tenant"], a["doc1"]).id
        deactivated = client.patch(
            f"{API}/institution/users/{a['doc1'].id}",
            json={"is_active": False},
            headers=auth_headers(a["admin"]),
        )
        assert deactivated.status_code == 200
        handover = create(client, a["admin"], a["doc1"], a["doc2"]).json()
        assert accept(client, a["doc2"], handover["id"]).json() == {"patients_moved": 1}
        assert responsibles(owner_engine, {patient}) == {a["doc2"].id}

    def test_platform_admin_crea_traspasos_en_cualquier_tenant(
        self, client, owner_engine, clinics, user_factory
    ):
        a, _ = clinics
        platform = user_factory(role="platform_admin")
        response = create(client, platform, a["doc1"], a["doc2"], platform=True)
        assert response.status_code == 201
        listed = client.get(
            f"{API}/admin/tenants/{a['tenant'].id}/handovers", headers=auth_headers(platform)
        )
        assert [h["id"] for h in listed.json()["items"]] == [response.json()["id"]]
        # Aun así, platform_admin no ve datos clínicos
        assert accept(client, platform, response.json()["id"]).status_code == 403


class TestAccesoCruzado:
    def test_otra_medica_no_acepta_ni_ve_el_traspaso(self, client, owner_engine, clinics):
        a, b = clinics
        patient = seed(owner_engine, "patients", a["tenant"], a["doc1"]).id
        handover = create(client, a["admin"], a["doc1"], a["doc2"]).json()
        for intruder in (a["doc3"], b["doc1"]):
            assert accept(client, intruder, handover["id"]).status_code == 404
            assert visible_patients(intruder) == set()
        assert responsibles(owner_engine, {patient}) == {a["doc1"].id}

    def test_segunda_aceptacion_da_el_mismo_404(self, client, owner_engine, clinics):
        a, _ = clinics
        seed(owner_engine, "patients", a["tenant"], a["doc1"])
        handover = create(client, a["admin"], a["doc1"], a["doc2"]).json()
        assert accept(client, a["doc2"], handover["id"]).status_code == 200
        again = accept(client, a["doc2"], handover["id"])
        missing = accept(client, a["doc2"], "00000000-0000-0000-0000-000000000000")
        assert again.status_code == missing.status_code == 404
        assert again.json() == missing.json()

    def test_admin_de_otro_tenant_no_crea_ni_cancela(self, client, owner_engine, clinics):
        a, b = clinics
        seed(owner_engine, "patients", a["tenant"], a["doc1"])
        # Origen o destino de otro tenant: 404, como un usuario inexistente
        assert create(client, b["admin"], a["doc1"], a["doc2"]).status_code == 404
        assert create(client, a["admin"], a["doc1"], b["doc1"]).status_code == 404
        handover = create(client, a["admin"], a["doc1"], a["doc2"]).json()
        cancelled = client.delete(
            f"{API}/institution/handovers/{handover['id']}", headers=auth_headers(b["admin"])
        )
        assert cancelled.status_code == 404
        listed = client.get(f"{API}/institution/handovers", headers=auth_headers(b["admin"]))
        assert listed.json()["items"] == []
        assert visible_patients(b["doc1"]) == set()

    def test_durante_el_traspaso_no_crea_fichas_a_nombre_de_la_de_origen(
        self, client, owner_engine, clinics
    ):
        a, _ = clinics
        create(client, a["admin"], a["doc1"], a["doc2"])
        with (
            tenant_session(a["doc2"]) as session,
            pytest.raises(DBAPIError, match="row-level"),
        ):
            RECIPES["patients"].insert(session, None, a["doc2"], {}, {"responsible": a["doc1"].id})


class TestReglas:
    @pytest.mark.parametrize("target", ["admin", "doc1", "inactive"])
    def test_destino_invalido_422(self, client, clinics, user_factory, target):
        a, _ = clinics
        if target == "inactive":
            destination = user_factory(a["tenant"], role="doctor", active=False)
        else:
            destination = a[target]
        assert create(client, a["admin"], a["doc1"], destination).status_code == 422

    def test_un_traspaso_nuevo_reemplaza_al_pendiente(self, client, owner_engine, clinics):
        a, _ = clinics
        patient = seed(owner_engine, "patients", a["tenant"], a["doc1"]).id
        first = create(client, a["admin"], a["doc1"], a["doc2"]).json()
        second = create(client, a["admin"], a["doc1"], a["doc3"]).json()
        assert visible_patients(a["doc2"]) == set()
        assert visible_patients(a["doc3"]) == {patient}
        assert accept(client, a["doc2"], first["id"]).status_code == 404
        assert accept(client, a["doc3"], second["id"]).status_code == 200

    def test_no_se_encadenan_traspasos(self, client, clinics):
        a, _ = clinics
        assert create(client, a["admin"], a["doc1"], a["doc2"]).status_code == 201
        # doc2 → doc3 con doc1 → doc2 pendiente: las pacientes de doc1 no llegarían a doc3
        assert create(client, a["admin"], a["doc2"], a["doc3"]).status_code == 422
        assert create(client, a["admin"], a["doc3"], a["doc1"]).status_code == 422

    def test_cancelar_quita_la_visibilidad(self, client, owner_engine, clinics):
        a, _ = clinics
        seed(owner_engine, "patients", a["tenant"], a["doc1"])
        handover = create(client, a["admin"], a["doc1"], a["doc2"]).json()
        url = f"{API}/institution/handovers/{handover['id']}"
        cancelled = client.delete(url, headers=auth_headers(a["admin"]))
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
        assert visible_patients(a["doc2"]) == set()
        assert client.delete(url, headers=auth_headers(a["admin"])).status_code == 409
        assert accept(client, a["doc2"], handover["id"]).status_code == 404


def handover_row(owner_engine, handover_id):
    with owner_engine.connect() as conn:
        return conn.execute(
            text("SELECT * FROM control.patient_handovers WHERE id = :id"), {"id": handover_id}
        ).one()


class TestDefensaEnLaBase:
    """Lo que la base impide aunque un error de la app lo intentara (revisión de aislamiento)."""

    def test_una_sesion_de_doctora_no_crea_traspasos(self, clinics):
        a, _ = clinics
        with (
            tenant_session(a["doc2"]) as session,
            pytest.raises(DBAPIError, match="solo se crean desde la administración"),
        ):
            session.execute(
                text(
                    "INSERT INTO control.patient_handovers (tenant_id, from_doctor_id, "
                    "to_doctor_id) VALUES (:t, :f, :me)"
                ),
                {"t": a["tenant"].id, "f": a["doc1"].id, "me": a["doc2"].id},
            )

    def test_la_doctora_solo_acepta_lo_suyo_y_no_cancela(self, client, owner_engine, clinics):
        a, _ = clinics
        handover = create(client, a["admin"], a["doc1"], a["doc2"]).json()
        attempts = [
            (a["doc3"], "accepted_at = now()"),  # no es la de destino
            (a["doc2"], "cancelled_at = now()"),  # la de destino tampoco cancela
        ]
        for doctor, change in attempts:
            with (
                tenant_session(doctor) as session,
                pytest.raises(DBAPIError, match="Solo la médica de destino"),
            ):
                session.execute(
                    text(f"UPDATE control.patient_handovers SET {change} WHERE id = :id"),
                    {"id": handover["id"]},
                )
        row = handover_row(owner_engine, handover["id"])
        assert row.accepted_at is None and row.cancelled_at is None

    def test_no_pasa_sus_fichas_a_la_medica_de_origen(self, client, owner_engine, clinics):
        a, _ = clinics
        own = seed(owner_engine, "patients", a["tenant"], a["doc2"]).id
        create(client, a["admin"], a["doc1"], a["doc2"])
        with (
            tenant_session(a["doc2"]) as session,
            pytest.raises(DBAPIError, match="row-level"),
        ):
            session.execute(
                text("UPDATE clinical.patients SET responsible_doctor_id = :x WHERE id = :id"),
                {"x": a["doc1"].id, "id": own},
            )
        assert responsibles(owner_engine, {own}) == {a["doc2"].id}

    def test_un_traspaso_en_otro_tenant_no_abre_nada_aqui(self, client, owner_engine, clinics):
        a, b = clinics
        seed(owner_engine, "patients", a["tenant"], a["doc1"])
        create(client, b["admin"], b["doc1"], b["doc2"])
        # Aun con un traspaso pendiente hacia ella en B, no ve fichas de A
        assert visible_patients(b["doc2"]) == set()

    def test_permisos_minimos_de_la_app(self, owner_engine):
        with owner_engine.connect() as conn:

            def can(privilege, column=None):
                if column:
                    sql = "SELECT has_column_privilege(:r, 'control.patient_handovers', :c, :p)"
                    return conn.execute(
                        text(sql), {"r": TEST_APP_ROLE, "c": column, "p": privilege}
                    ).scalar_one()
                sql = "SELECT has_table_privilege(:r, 'control.patient_handovers', :p)"
                return conn.execute(text(sql), {"r": TEST_APP_ROLE, "p": privilege}).scalar_one()

            assert can("SELECT") and can("INSERT")
            assert not can("DELETE") and not can("TRUNCATE")
            for column in ("tenant_id", "from_doctor_id", "to_doctor_id", "created_by"):
                assert not can("UPDATE", column), column
            for column in ("accepted_at", "patients_moved", "cancelled_at", "cancelled_by"):
                assert can("UPDATE", column), column


class TestDestinoQueYaNoPuedeAceptar:
    @pytest.mark.parametrize("change", [{"is_active": False}, {"role": "tenant_admin"}])
    def test_se_cancela_y_deja_de_ver(self, client, owner_engine, clinics, change):
        a, _ = clinics
        seed(owner_engine, "patients", a["tenant"], a["doc1"])
        handover = create(client, a["admin"], a["doc1"], a["doc2"]).json()
        response = client.patch(
            f"{API}/institution/users/{a['doc2'].id}", json=change, headers=auth_headers(a["admin"])
        )
        assert response.status_code == 200
        assert handover_row(owner_engine, handover["id"]).cancelled_at is not None
        # Ya se puede traspasar a otra doctora
        assert create(client, a["admin"], a["doc1"], a["doc3"]).status_code == 201
