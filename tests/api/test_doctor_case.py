"""CU-08: caso de la médica (lectura con URLs firmadas, estado y notas).

Acceso cruzado (otra médica del mismo tenant y médica de otro tenant) con 404 idéntico al de un
id inexistente, auditoría `case.denied` solo en el tenant de quien pregunta, notas solo de su
autora y URLs firmadas solo bajo el prefijo del tenant.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from tests.api.test_handovers import accept, create
from tests.panel_helpers import (
    add_analysis,
    add_note,
    add_patient,
    audit_rows,
    call,
    name_users,
    patient_row,
    set_status_as_owner,
)

SECRET = "TEXTO-CLINICO-SECRETO-4711"


@pytest.fixture
def world(tenant_factory, user_factory, owner_engine):
    a, b = tenant_factory("clinica-a"), tenant_factory("clinica-b")
    data = {
        "a": a,
        "b": b,
        "doc1": user_factory(a, role="doctor"),
        "doc2": user_factory(a, role="doctor"),
        "doc_b": user_factory(b, role="doctor"),
        "admin": user_factory(a, role="tenant_admin"),
    }
    name_users(owner_engine, {data["doc1"].id: "Dra. Uno", data["doc2"].id: "Dra. Dos"})
    data["pid"] = add_patient(owner_engine, a, data["doc1"], "Paciente A")
    data["pid_b"] = add_patient(owner_engine, b, data["doc_b"], "Paciente B")
    return data


def status_of(client, user, pid, new):
    return call(client, "patch", f"/patients/{pid}/status", user, json={"status": new})


class TestCasoCompleto:
    def test_caso_con_urls_firmadas_y_auditoria(self, client, storage, owner_engine, world):
        a, doc, pid = world["a"], world["doc1"], world["pid"]
        analysis_id = add_analysis(owner_engine, a, pid, doc, predicted_class="maligno")
        response = call(client, "get", f"/patients/{pid}", doc)
        assert response.status_code == 200, response.text
        case = response.json()
        assert case["display_name"] == "Paciente A" and case["status"] == "pendiente"
        (analysis,) = case["analyses"]
        assert analysis["id"] == str(analysis_id) and analysis["suspicious"] is True
        for key, folder in (("image_url", "images"), ("heatmap_url", "heatmaps")):
            assert analysis[key].startswith(f"https://storage.test/signed/clinica-a/{folder}/")
            assert f"expires_in={case['signed_url_ttl']}" in analysis[key]
        (row,) = audit_rows(owner_engine, "case.read")
        assert row["tenant_id"] == a.id and row["resource_id"] == pid
        assert row["actor_id"] == doc.id

    def test_caso_vacio(self, client, world):
        case = call(client, "get", f"/patients/{world['pid']}", world["doc1"]).json()
        assert case["analyses"] == [] and case["notes"] == [] and case["questionnaire"] is None
        assert case["self_exams"] == [] and case["symptoms"] == []


class TestUrlsFirmadas:
    def test_solo_se_firman_rutas_del_prefijo_del_tenant(
        self, client, storage, owner_engine, world
    ):
        a, doc, pid = world["a"], world["doc1"], world["pid"]
        add_analysis(owner_engine, a, pid, doc)
        # Otro tenant con su propio análisis: nunca debe firmarse
        add_analysis(owner_engine, world["b"], world["pid_b"], world["doc_b"])
        case = call(client, "get", f"/patients/{pid}", doc).json()
        assert len(case["analyses"]) == 1
        assert storage.signed and all(p.startswith("clinica-a/") for p in storage.signed)
        assert not any("clinica-b" in p for p in storage.signed)

    @pytest.mark.parametrize(
        ("image_path", "heatmap_path"),
        [
            ("clinica-b/images/x.png", None),
            (None, "clinica-b/heatmaps/x.png"),
            ("clinica-a-evil/images/x.png", None),  # prefijo parecido, sin la barra
            ("../clinica-a/images/x.png", None),
        ],
    )
    def test_ruta_de_otro_prefijo_no_se_firma(
        self, client, storage, owner_engine, world, image_path, heatmap_path
    ):
        add_analysis(
            owner_engine,
            world["a"],
            world["pid"],
            world["doc1"],
            image_path=image_path,
            heatmap_path=heatmap_path,
        )
        case = call(client, "get", f"/patients/{world['pid']}", world["doc1"]).json()
        assert case["analyses"] == []
        assert storage.signed == []

    def test_fallo_de_storage_da_502(self, client, storage, owner_engine, world):
        add_analysis(owner_engine, world["a"], world["pid"], world["doc1"])
        storage.fail_sign = True
        response = call(client, "get", f"/patients/{world['pid']}", world["doc1"])
        assert response.status_code == 502


class TestAislamientoDelCaso:
    @pytest.fixture
    def note(self, owner_engine, world):
        return add_note(owner_engine, world["a"], world["pid"], world["doc1"], SECRET)

    def _paths(self, world, note):
        pid = world["pid"]
        return [
            ("get", f"/patients/{pid}", {}),
            ("patch", f"/patients/{pid}/status", {"json": {"status": "revisado"}}),
            ("post", f"/patients/{pid}/notes", {"json": {"body": "intruso"}}),
            ("patch", f"/notes/{note}", {"json": {"body": "intruso"}}),
            ("delete", f"/notes/{note}", {}),
        ]

    @pytest.mark.parametrize("intruder", ["doc2", "doc_b"])
    def test_404_identico_al_de_un_id_inexistente(
        self, client, owner_engine, world, note, intruder
    ):
        user = world[intruder]
        for method, path, kwargs in self._paths(world, note):
            real = call(client, method, path, user, **kwargs)
            fake_path = path.replace(str(world["pid"]), str(uuid.uuid4())).replace(
                str(note), str(uuid.uuid4())
            )
            fake = call(client, method, fake_path, user, **kwargs)
            assert real.status_code == fake.status_code == 404, (method, path)
            assert real.json() == fake.json(), (method, path)

    @pytest.mark.parametrize("intruder", ["doc2", "doc_b"])
    def test_nada_cambia_tras_los_intentos(self, client, owner_engine, world, note, intruder):
        before = patient_row(owner_engine, world["pid"])
        for method, path, kwargs in self._paths(world, note):
            call(client, method, path, world[intruder], **kwargs)
        assert patient_row(owner_engine, world["pid"]) == before
        with owner_engine.connect() as conn:
            rows = conn.execute(text("SELECT body FROM clinical.case_notes")).scalars().all()
        assert rows == [SECRET]

    def test_denied_se_audita_en_el_tenant_de_quien_pregunta(
        self, client, owner_engine, world, note
    ):
        call(client, "get", f"/patients/{world['pid']}", world["doc2"])
        call(client, "get", f"/patients/{world['pid']}", world["doc_b"])
        call(client, "patch", f"/notes/{note}", world["doc_b"], json={"body": "x"})
        rows = audit_rows(owner_engine, "case.denied")
        by_tenant = {}
        for row in rows:
            by_tenant.setdefault(row["tenant_id"], []).append(row)
        assert {r["actor_id"] for r in by_tenant[world["a"].id]} == {world["doc2"].id}
        assert {r["actor_id"] for r in by_tenant[world["b"].id]} == {world["doc_b"].id}
        assert len(by_tenant[world["a"].id]) == 1 and len(by_tenant[world["b"].id]) == 2
        # El recurso ajeno no deja rastro en el tenant dueño
        assert all(r["actor_id"] != world["doc1"].id for r in rows)

    def test_el_intruso_no_ve_el_caso_en_su_panel(self, client, world):
        for user in ("doc2", "doc_b"):
            page = call(client, "post", "/patients/search", world[user], json={}).json()
            assert all(i["id"] != str(world["pid"]) for i in page["items"])

    def test_la_dueña_si_ve_su_caso_tras_los_intentos(self, client, world, note):
        call(client, "get", f"/patients/{world['pid']}", world["doc2"])
        assert call(client, "get", f"/patients/{world['pid']}", world["doc1"]).status_code == 200


class TestEstadoApi:
    @pytest.mark.parametrize(
        ("start", "target"),
        [
            ("pendiente", "en_revision"),
            ("pendiente", "revisado"),
            ("en_revision", "revisado"),
            ("en_revision", "pendiente"),
            ("revisado", "en_revision"),
        ],
    )
    def test_transiciones_validas(self, client, owner_engine, world, start, target):
        if start != "pendiente":
            set_status_as_owner(owner_engine, world["pid"], start)
        response = status_of(client, world["doc1"], world["pid"], target)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == target
        assert patient_row(owner_engine, world["pid"])["status"] == target
        (row,) = audit_rows(owner_engine, "case.status")
        assert row["tenant_id"] == world["a"].id

    @pytest.mark.parametrize(
        ("start", "target"),
        [
            ("pendiente", "pendiente"),
            ("en_revision", "en_revision"),
            ("revisado", "revisado"),
            ("revisado", "pendiente"),
        ],
    )
    def test_transiciones_invalidas_dan_409(self, client, owner_engine, world, start, target):
        if start != "pendiente":
            set_status_as_owner(owner_engine, world["pid"], start)
        before = patient_row(owner_engine, world["pid"])
        response = status_of(client, world["doc1"], world["pid"], target)
        assert response.status_code == 409, response.text
        assert patient_row(owner_engine, world["pid"]) == before
        assert audit_rows(owner_engine, "case.status") == []

    def test_estado_desconocido_o_campo_extra_da_422(self, client, world):
        pid = world["pid"]
        assert status_of(client, world["doc1"], pid, "aprobado").status_code == 422
        response = call(
            client,
            "patch",
            f"/patients/{pid}/status",
            world["doc1"],
            json={"status": "revisado", "reviewed_by": str(world["doc2"].id)},
        )
        assert response.status_code == 422

    def test_revisado_fija_quien_y_cuando_y_reabrir_lo_limpia(self, client, owner_engine, world):
        pid, doc = world["pid"], world["doc1"]
        response = status_of(client, doc, pid, "revisado")
        assert response.json()["reviewed_at"] is not None
        row = patient_row(owner_engine, pid)
        assert row["reviewed_by"] == doc.id and row["reviewed_at"] is not None
        case = call(client, "get", f"/patients/{pid}", doc).json()
        assert case["reviewed_by_name"] == "Dra. Uno" and case["reviewed_at"] is not None

        reopened = status_of(client, doc, pid, "en_revision")
        assert reopened.json() == {"status": "en_revision", "reviewed_at": None}
        row = patient_row(owner_engine, pid)
        assert row["reviewed_by"] is None and row["reviewed_at"] is None
        case = call(client, "get", f"/patients/{pid}", doc).json()
        assert case["reviewed_by_name"] is None

    def test_el_cliente_no_puede_fijar_reviewed_by(self, client, world):
        # extra="forbid" lo impide en la API; la base lo impide en SQL (test_estado_del_caso)
        response = call(
            client,
            "patch",
            f"/patients/{world['pid']}/status",
            world["doc1"],
            json={"status": "revisado", "reviewed_at": "2020-01-01T00:00:00Z"},
        )
        assert response.status_code == 422

    def test_ficha_con_traspaso_pendiente_no_cambia_de_estado_hasta_aceptar(
        self, client, owner_engine, world
    ):
        pid = world["pid"]
        handover = create(client, world["admin"], world["doc1"], world["doc2"]).json()
        response = status_of(client, world["doc2"], pid, "revisado")
        assert response.status_code == 409
        assert patient_row(owner_engine, pid)["status"] == "pendiente"
        # Tampoco la de origen mientras el traspaso sigue pendiente: sigue siendo suya
        assert accept(client, world["doc2"], handover["id"]).status_code == 200
        assert status_of(client, world["doc2"], pid, "revisado").status_code == 200
        assert patient_row(owner_engine, pid)["reviewed_by"] == world["doc2"].id

    def test_analisis_nuevo_devuelve_el_caso_a_pendiente(self, client, owner_engine, world):
        pid, doc = world["pid"], world["doc1"]
        status_of(client, doc, pid, "revisado")
        add_analysis(owner_engine, world["a"], pid, doc)
        row = patient_row(owner_engine, pid)
        assert row["status"] == "pendiente"
        assert row["reviewed_by"] is None and row["reviewed_at"] is None
        # Y desde pendiente se puede volver a revisar
        assert status_of(client, doc, pid, "revisado").status_code == 200


class TestNotas:
    def test_crear_editar_y_borrar_las_propias(self, client, owner_engine, world):
        pid, doc = world["pid"], world["doc1"]
        created = call(client, "post", f"/patients/{pid}/notes", doc, json={"body": "primera"})
        assert created.status_code == 201, created.text
        note = created.json()
        assert note["mine"] is True and note["author_name"] == "Dra. Uno"
        assert note["body"] == "primera" and note["updated_at"] is None

        edited = call(client, "patch", f"/notes/{note['id']}", doc, json={"body": "editada"})
        assert edited.status_code == 200
        assert edited.json()["body"] == "editada" and edited.json()["updated_at"] is not None

        case = call(client, "get", f"/patients/{pid}", doc).json()
        assert [n["body"] for n in case["notes"]] == ["editada"]

        deleted = call(client, "delete", f"/notes/{note['id']}", doc)
        assert deleted.status_code == 204
        assert call(client, "get", f"/patients/{pid}", doc).json()["notes"] == []
        actions = {r["action"] for r in audit_rows(owner_engine)}
        assert {"case.note_create", "case.note_update", "case.note_delete"} <= actions

    def test_la_colega_no_edita_ni_borra_notas_ajenas(self, client, owner_engine, world):
        note = add_note(owner_engine, world["a"], world["pid"], world["doc1"], "mia")
        # Con la ficha visible por traspaso pendiente, la nota sigue siendo de su autora
        create(client, world["admin"], world["doc1"], world["doc2"])
        case = call(client, "get", f"/patients/{world['pid']}", world["doc2"]).json()
        assert case["notes"][0]["mine"] is False
        assert (
            call(client, "patch", f"/notes/{note}", world["doc2"], json={"body": "x"}).status_code
            == 404
        )
        assert call(client, "delete", f"/notes/{note}", world["doc2"]).status_code == 404
        with owner_engine.connect() as conn:
            assert conn.execute(text("SELECT body FROM clinical.case_notes")).scalar_one() == "mia"

    @pytest.mark.parametrize("body", ["", "   ", "\n\t ", "a\u0000b", "x" * 4001])
    def test_nota_invalida_da_422(self, client, owner_engine, world, body):
        pid = world["pid"]
        assert (
            call(client, "post", f"/patients/{pid}/notes", world["doc1"], json={"body": body})
        ).status_code == 422
        note = add_note(owner_engine, world["a"], pid, world["doc1"])
        response = call(client, "patch", f"/notes/{note}", world["doc1"], json={"body": body})
        assert response.status_code == 422

    def test_campos_faltantes_o_extra_dan_422(self, client, world):
        pid = world["pid"]
        assert (
            call(client, "post", f"/patients/{pid}/notes", world["doc1"], json={}).status_code
            == 422
        )
        response = call(
            client,
            "post",
            f"/patients/{pid}/notes",
            world["doc1"],
            json={"body": "ok", "author_id": str(world["doc2"].id)},
        )
        assert response.status_code == 422

    def test_la_autora_sale_del_jwt(self, client, owner_engine, world):
        pid = world["pid"]
        call(client, "post", f"/patients/{pid}/notes", world["doc1"], json={"body": "ok"})
        with owner_engine.connect() as conn:
            row = conn.execute(text("SELECT author_id, tenant_id FROM clinical.case_notes")).one()
        assert row == (world["doc1"].id, world["a"].id)

    def test_el_contenido_de_la_nota_nunca_llega_a_la_auditoria(self, client, owner_engine, world):
        pid, doc = world["pid"], world["doc1"]
        created = call(client, "post", f"/patients/{pid}/notes", doc, json={"body": SECRET}).json()
        call(client, "patch", f"/notes/{created['id']}", doc, json={"body": SECRET + "-2"})
        call(client, "get", f"/patients/{pid}", doc)
        call(client, "delete", f"/notes/{created['id']}", doc)
        rows = audit_rows(owner_engine)
        assert len(rows) >= 4
        assert not any("SECRETO" in str(row) for row in rows)
        assert not any(SECRET in str(row.values()) for row in rows)

    def test_nota_en_ficha_ajena_da_404_sin_crear_nada(self, client, owner_engine, world):
        response = call(
            client, "post", f"/patients/{world['pid']}/notes", world["doc_b"], json={"body": "x"}
        )
        assert response.status_code == 404
        with owner_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM clinical.case_notes")).scalar_one() == 0


class TestVentanaDelDiario:
    def test_diario_de_mas_de_90_dias_no_se_incluye(self, client, owner_engine, world):
        # Documenta DIARY_DAYS: lo viejo no va en el caso salvo ligado a una autoexploración
        pid = world["pid"]
        old = (datetime.now(UTC) - timedelta(days=200)).date()
        with owner_engine.begin() as conn:
            for day in (old, datetime.now(UTC).date()):
                conn.execute(
                    text(
                        "INSERT INTO clinical.symptom_entries (tenant_id, id, patient_id, "
                        "created_by, entry_date, side, zone, symptoms, intensity) "
                        "VALUES (:t, gen_random_uuid(), :p, :u, :d, 'izquierdo', 'axila', "
                        "ARRAY['dolor'], 3)"
                    ),
                    {"t": world["a"].id, "p": pid, "u": world["doc1"].id, "d": day},
                )
        case = call(client, "get", f"/patients/{pid}", world["doc1"]).json()
        assert len(case["symptoms"]) == 1
