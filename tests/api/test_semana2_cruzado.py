"""Semana 2 (CU-01 y CU-02): acceso cruzado con recursos REALES.

Dos ejes: tenant A contra tenant B, y paciente A1 contra A2 dentro del mismo tenant. Se
comprueba 404 uniforme (igual al de un id inexistente), que el dueño ve intacto lo ajeno, que
`tenant_id` del cliente se ignora o se rechaza y que la auditoría queda en el tenant del actor.
"""

import io
import uuid

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import text

from tests.helpers import auth_headers

API = "/api/v1"
NO_FACTORS = {
    "age": 30,
    "family_history_breast": "none",
    "family_history_ovarian": False,
    "brca_mutation": "no",
    "previous_biopsy": False,
    "hormone_therapy": False,
    "current_symptoms": [],
    "last_checkup": "less_than_1y",
}
TABLES = ("analyses", "medical_images", "questionnaires")


def ultrasound_png() -> bytes:
    rng = np.random.default_rng(7)
    array = rng.gamma(2.0, 30.0, (240, 320)).clip(0, 255).astype(np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(array, "L").save(buffer, format="PNG")
    return buffer.getvalue()


def create_analysis(client, user, **extra) -> dict:
    response = client.post(
        f"{API}/analyses",
        files={"file": ("eco.png", ultrasound_png(), "image/png")},
        headers=auth_headers(user),
        **extra,
    )
    assert response.status_code == 201, response.text
    return response.json()


def submit_questionnaire(client, user, age: int = 30):
    response = client.post(
        f"{API}/questionnaires",
        json={"version": "v1", "answers": {**NO_FACTORS, "age": age}},
        headers=auth_headers(user),
    )
    assert response.status_code == 201, response.text
    return response.json()


def snapshot(owner_engine, tenant_id) -> dict[str, list]:
    """Estado completo de las tablas clínicas de un tenant, leído como dueño."""
    result = {}
    with owner_engine.connect() as conn:
        for table in TABLES:
            result[table] = sorted(
                str(r)
                for r in conn.execute(
                    text(f"SELECT to_jsonb(t) FROM clinical.{table} t WHERE tenant_id = :t"),
                    {"t": tenant_id},
                ).scalars()
            )
    return result


def audit_rows(owner_engine, tenant_id) -> list:
    with owner_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT action, actor_id, resource_type, resource_id FROM clinical.audit_log "
                "WHERE tenant_id = :t ORDER BY occurred_at"
            ),
            {"t": tenant_id},
        ).all()


def count(owner_engine, sql: str, **params) -> int:
    with owner_engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


@pytest.fixture
def world(tenant_factory, user_factory):
    """Clínica A con dos pacientes (a1, a2) y clínica B con una (b1); con datos reales."""
    tenant_a, tenant_b = tenant_factory("clinica-a"), tenant_factory("clinica-b")
    return {
        "ta": tenant_a,
        "tb": tenant_b,
        "a1": user_factory(tenant_a, role="patient"),
        "a2": user_factory(tenant_a, role="patient"),
        "b1": user_factory(tenant_b, role="patient"),
    }


@pytest.fixture
def seeded(client, world):
    """Cada paciente con un análisis y un cuestionario creados por la API."""
    data = dict(world)
    for key in ("a1", "a2", "b1"):
        data[f"{key}_analysis"] = create_analysis(client, world[key])
        data[f"{key}_questionnaire"] = submit_questionnaire(client, world[key])
    return data


# (tenant del recurso, paciente que ataca) -> a1 contra b1 (otro tenant) y a1 contra a2 (mismo)
VICTIMS = ["b1", "a2"]


class TestAnalisisAjenos:
    @pytest.mark.parametrize("victim", VICTIMS)
    @pytest.mark.parametrize("method", ["GET", "DELETE"])
    def test_detalle_y_borrado_ajenos_dan_el_mismo_404_que_un_id_inexistente(
        self, client, seeded, storage, owner_engine, victim, method
    ):
        attacker = seeded["a1"]
        victim_tenant = seeded["ta"] if victim == "a2" else seeded["tb"]
        before = snapshot(owner_engine, victim_tenant.id)
        objects_before = dict(storage.objects)
        storage.signed.clear()
        storage.removed.clear()
        target = seeded[f"{victim}_analysis"]["id"]

        foreign = client.request(method, f"{API}/analyses/{target}", headers=auth_headers(attacker))
        missing = client.request(
            method, f"{API}/analyses/{uuid.uuid4()}", headers=auth_headers(attacker)
        )

        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json()
        assert storage.signed == [] and storage.removed == []
        assert storage.objects == objects_before
        assert snapshot(owner_engine, victim_tenant.id) == before
        # La auditoría del tenant de la víctima solo trae el intento a nombre del atacante,
        # y únicamente cuando comparten tenant; nunca algo a nombre de la víctima
        denials = [
            r for r in audit_rows(owner_engine, victim_tenant.id) if r.action == "analysis.denied"
        ]
        assert {r.actor_id for r in denials} == ({attacker.id} if victim == "a2" else set())

    def test_el_intento_cruzado_se_audita_solo_en_el_tenant_del_atacante(
        self, client, seeded, owner_engine
    ):
        target = seeded["b1_analysis"]["id"]
        b_before = audit_rows(owner_engine, seeded["tb"].id)

        client.get(f"{API}/analyses/{target}", headers=auth_headers(seeded["a1"]))
        client.delete(f"{API}/analyses/{target}", headers=auth_headers(seeded["a1"]))

        denied = [
            r for r in audit_rows(owner_engine, seeded["ta"].id) if r.action.endswith("denied")
        ]
        assert len(denied) == 2
        assert {r.actor_id for r in denied} == {seeded["a1"].id}
        assert audit_rows(owner_engine, seeded["tb"].id) == b_before

    @pytest.mark.parametrize("victim", VICTIMS)
    def test_listado_nunca_incluye_analisis_ajenos(self, client, seeded, victim):
        page = client.get(f"{API}/analyses", headers=auth_headers(seeded["a1"])).json()
        ids = [i["id"] for i in page["items"]]
        assert ids == [seeded["a1_analysis"]["id"]]
        assert page["total"] == 1
        assert seeded[f"{victim}_analysis"]["id"] not in ids

    def test_el_propio_dueno_si_sigue_viendo_su_analisis(self, client, seeded):
        response = client.get(
            f"{API}/analyses/{seeded['a2_analysis']['id']}", headers=auth_headers(seeded["a2"])
        )
        assert response.status_code == 200

    @pytest.mark.parametrize("victim", VICTIMS)
    def test_urls_firmadas_solo_llevan_el_prefijo_del_tenant_del_actor(
        self, client, seeded, storage, victim
    ):
        storage.signed.clear()
        client.get(
            f"{API}/analyses/{seeded[f'{victim}_analysis']['id']}",
            headers=auth_headers(seeded["a1"]),
        )
        client.get(
            f"{API}/analyses/{seeded['a1_analysis']['id']}", headers=auth_headers(seeded["a1"])
        )
        assert storage.signed and all(p.startswith("clinica-a/") for p in storage.signed)


class TestTenantIdDelClienteEnAnalisis:
    SPOOF_HEADER = "X-Tenant-Id"

    def _spoof(self, seeded):
        tenant_b = str(seeded["tb"].id)
        return {"tenant_id": tenant_b}, {self.SPOOF_HEADER: tenant_b}

    def test_crear_con_tenant_en_query_header_y_formulario_guarda_en_el_tenant_del_jwt(
        self, client, world, storage, owner_engine
    ):
        tenant_b = str(world["tb"].id)
        response = client.post(
            f"{API}/analyses",
            params={"tenant_id": tenant_b},
            data={"tenant_id": tenant_b},
            files={"file": ("eco.png", ultrasound_png(), "image/png")},
            headers={**auth_headers(world["a1"]), self.SPOOF_HEADER: tenant_b},
        )
        assert response.status_code == 201
        assert all(p.startswith("clinica-a/") for p in storage.objects)
        assert (
            count(
                owner_engine,
                "SELECT count(*) FROM clinical.analyses WHERE tenant_id = :t",
                t=world["ta"].id,
            )
            == 1
        )
        assert (
            count(
                owner_engine,
                "SELECT count(*) FROM clinical.analyses WHERE tenant_id = :t",
                t=world["tb"].id,
            )
            == 0
        )
        assert audit_rows(owner_engine, world["tb"].id) == []

    @pytest.mark.parametrize("method", ["GET", "DELETE"])
    def test_detalle_y_borrado_con_tenant_de_b_siguen_dando_404(
        self, client, seeded, owner_engine, method
    ):
        params, headers = self._spoof(seeded)
        before = snapshot(owner_engine, seeded["tb"].id)
        response = client.request(
            method,
            f"{API}/analyses/{seeded['b1_analysis']['id']}",
            params=params,
            headers={**auth_headers(seeded["a1"]), **headers},
        )
        assert response.status_code == 404
        assert snapshot(owner_engine, seeded["tb"].id) == before

    def test_listado_con_tenant_de_b_sigue_mostrando_solo_lo_propio(self, client, seeded):
        params, headers = self._spoof(seeded)
        page = client.get(
            f"{API}/analyses",
            params=params,
            headers={**auth_headers(seeded["a1"]), **headers},
        ).json()
        assert [i["id"] for i in page["items"]] == [seeded["a1_analysis"]["id"]]


class TestCuestionarioAjeno:
    def test_latest_no_refleja_el_cuestionario_de_otros(self, client, world):
        submit_questionnaire(client, world["a2"], age=50)
        submit_questionnaire(client, world["b1"], age=60)
        response = client.get(f"{API}/questionnaires/latest", headers=auth_headers(world["a1"]))
        assert response.status_code == 404

    def test_latest_devuelve_el_propio_aunque_otros_hayan_enviado_despues(self, client, world):
        mine = submit_questionnaire(client, world["a1"], age=30)
        submit_questionnaire(client, world["a2"], age=55)
        submit_questionnaire(client, world["b1"], age=65)
        latest = client.get(f"{API}/questionnaires/latest", headers=auth_headers(world["a1"]))
        assert latest.status_code == 200
        assert latest.json()["id"] == mine["id"]

    def test_envio_con_tenant_en_query_y_header_guarda_en_el_tenant_del_jwt(
        self, client, world, owner_engine
    ):
        tenant_b = str(world["tb"].id)
        response = client.post(
            f"{API}/questionnaires",
            params={"tenant_id": tenant_b},
            json={"version": "v1", "answers": NO_FACTORS},
            headers={**auth_headers(world["a1"]), "X-Tenant-Id": tenant_b},
        )
        assert response.status_code == 201
        with owner_engine.connect() as conn:
            row = conn.execute(
                text("SELECT tenant_id, patient_id FROM clinical.questionnaires")
            ).one()
        assert row.tenant_id == world["ta"].id and row.patient_id == world["a1"].patient_id
        assert audit_rows(owner_engine, world["tb"].id) == []

    @pytest.mark.parametrize("key", ["tenant_id", "patient_id"])
    def test_cuerpo_con_tenant_o_paciente_se_rechaza_y_no_guarda_nada(
        self, client, world, owner_engine, key
    ):
        payload = {"version": "v1", "answers": NO_FACTORS, key: str(world["b1"].patient_id)}
        response = client.post(
            f"{API}/questionnaires", json=payload, headers=auth_headers(world["a1"])
        )
        assert response.status_code == 422
        assert count(owner_engine, "SELECT count(*) FROM clinical.questionnaires") == 0
        assert audit_rows(owner_engine, world["ta"].id) == []

    def test_las_lecturas_se_auditan_solo_en_el_tenant_del_actor(
        self, client, seeded, owner_engine
    ):
        b_before = audit_rows(owner_engine, seeded["tb"].id)
        client.get(f"{API}/questionnaires/latest", headers=auth_headers(seeded["a1"]))
        rows = audit_rows(owner_engine, seeded["ta"].id)
        assert ("questionnaire.read", seeded["a1"].id) in [(r.action, r.actor_id) for r in rows]
        assert audit_rows(owner_engine, seeded["tb"].id) == b_before


class TestSuscripcionAjena:
    def _set_plan(self, client, user, code):
        response = client.put(
            f"{API}/subscription/me", json={"plan_code": code}, headers=auth_headers(user)
        )
        assert response.status_code == 200
        return response.json()

    def test_cambiar_mi_plan_no_toca_el_de_otros(self, client, world, owner_engine):
        self._set_plan(client, world["b1"], "premium")
        self._set_plan(client, world["a2"], "plus")
        self._set_plan(client, world["a1"], "basico")

        def plans():
            with owner_engine.connect() as conn:
                return dict(
                    conn.execute(text("SELECT user_id, plan_code FROM control.subscriptions")).all()
                )

        assert plans() == {
            world["b1"].id: "premium",
            world["a2"].id: "plus",
            world["a1"].id: "basico",
        }

    @pytest.mark.parametrize("key", ["user_id", "tenant_id"])
    def test_cuerpo_con_user_o_tenant_se_rechaza_y_no_cambia_el_plan_ajeno(
        self, client, world, owner_engine, key
    ):
        self._set_plan(client, world["b1"], "premium")
        value = str(world["b1"].id if key == "user_id" else world["tb"].id)
        response = client.put(
            f"{API}/subscription/me",
            json={"plan_code": "basico", key: value},
            headers=auth_headers(world["a1"]),
        )
        assert response.status_code == 422
        with owner_engine.connect() as conn:
            plan = conn.execute(
                text("SELECT plan_code FROM control.subscriptions WHERE user_id = :u"),
                {"u": world["b1"].id},
            ).scalar_one()
        assert plan == "premium"

    def test_query_y_header_con_otro_usuario_o_tenant_se_ignoran(self, client, world):
        self._set_plan(client, world["b1"], "premium")
        response = client.get(
            f"{API}/subscription/me",
            params={"user_id": str(world["b1"].id), "tenant_id": str(world["tb"].id)},
            headers={**auth_headers(world["a1"]), "X-Tenant-Id": str(world["tb"].id)},
        )
        assert response.status_code == 404  # a1 no tiene plan; el de b1 no se filtra

        own = self._set_plan(client, world["a1"], "plus")
        again = client.get(
            f"{API}/subscription/me",
            params={"user_id": str(world["b1"].id)},
            headers=auth_headers(world["a1"]),
        )
        assert again.json()["plan"]["code"] == own["plan"]["code"] == "plus"
