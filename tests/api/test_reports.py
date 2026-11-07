"""CU-10: PDF y HL7 simulado de la médica, y PDF sencillo de la paciente (ADR 0015).

- Solo la médica RESPONSABLE exporta, y solo un análisis revisado (BI-RADS suyo): si no, 409.
- Doctora de otro tenant, doctora del mismo tenant que no es responsable, análisis inexistente:
  el mismo 404 y `case.denied`. Destinataria de un traspaso pendiente: 409. Pacientes y
  administradoras: 403.
- Cada exportación se audita sin contenido; el id del registro es el `report_id` del documento.
- El nombre del archivo no lleva datos personales.
"""

import io
import re
import uuid

import pytest
from fpdf import FPDF  # noqa: F401  (la dependencia de producción debe estar instalada)

from tests.api.test_analyses import upload as patient_upload
from tests.api.test_handovers import create as create_handover
from tests.helpers import auth_headers
from tests.hl7_validator import field, unescape, validate_oru_r01
from tests.panel_helpers import add_analysis, add_patient, audit_rows, call, name_users

pytestmark = pytest.mark.usefixtures("database")

NAME = "Lucía Peña | ^&~ prueba"


def pdf_text(content: bytes) -> str:
    """Texto del PDF. fpdf2 guarda el texto como glifos con ToUnicode; lo extrae pypdf si está,
    si no, se compara el texto CID: basta con que el PDF sea válido y contenga sus fuentes."""
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() for page in reader.pages)


@pytest.fixture
def world(tenant_factory, user_factory, owner_engine, storage):
    a, b = tenant_factory("clinica-a"), tenant_factory("clinica-b")
    data = {
        "a": a,
        "b": b,
        "doc1": user_factory(a, role="doctor"),
        "doc2": user_factory(a, role="doctor"),
        "admin": user_factory(a, role="tenant_admin"),
        "patient": user_factory(a, role="patient"),
        "outsider": user_factory(b, role="doctor"),
    }
    name_users(owner_engine, {data["doc1"].id: "Dra. Ana Responsable"})
    data["pid"] = add_patient(owner_engine, a, data["doc1"], NAME, age=47)
    data["aid"] = add_analysis(
        owner_engine, a, data["pid"], data["doc1"], predicted_class="maligno"
    )
    storage.objects[f"{a.slug}/heatmaps/{data['aid']}.png"] = png_bytes()
    return data


def png_bytes() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 80, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


def review(client, doctor, aid, birads="4A", recommendation="Biopsia guiada.\nControl en 6 meses"):
    response = client.put(
        f"/api/v1/doctor/analyses/{aid}/review",
        json={"birads": birads, "recommendation": recommendation},
        headers=auth_headers(doctor),
    )
    assert response.status_code == 200, response.text
    return response


def export(client, user, aid, fmt):
    return call(client, "get", f"/analyses/{aid}/report.{fmt}", user)


class TestExportacionDeLaMedica:
    def test_pdf_completo_y_auditado(self, client, world, owner_engine):
        review(client, world["doc1"], world["aid"])
        response = export(client, world["doc1"], world["aid"], "pdf")
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["cache-control"] == "no-store"
        disposition = response.headers["content-disposition"]
        assert re.fullmatch(
            r'attachment; filename="breastguard-reporte-[0-9a-f]{8}\.pdf"', disposition
        )
        assert response.content.startswith(b"%PDF")

        [entry] = audit_rows(owner_engine, "case.export_pdf")
        assert entry["resource_id"] == world["aid"]
        assert entry["actor_id"] == world["doc1"].id
        assert str(entry["id"])[:8] in disposition  # el report_id ES el registro de auditoría

        text = pdf_text(response.content)
        for expected in (
            "Tenant clinica-a",  # nombre de la institución (el de tenant_factory)
            "Lucía Peña",
            "47 años",
            "Maligno",
            "90.0 %",
            "4A",
            "Biopsia guiada.",
            "Dra. Ana Responsable",
            str(entry["id"]),
            "Herramienta de apoyo al diagnóstico",
        ):
            assert expected in text, expected

    def test_hl7_estructuralmente_valido(self, client, world, owner_engine):
        review(client, world["doc1"], world["aid"])
        response = export(client, world["doc1"], world["aid"], "hl7")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/hl7-v2")
        assert response.headers["content-disposition"].endswith('.hl7"')
        message = response.content.decode("utf-8")
        segs = validate_oru_r01(message)
        msh, pid, obr, *obx = segs
        [entry] = audit_rows(owner_engine, "case.export_hl7")
        assert field(msh, 10) == str(entry["id"])
        assert field(msh, 11) == "T"  # entrenamiento: nunca un resultado real
        assert field(pid, 3).startswith(str(world["pid"]))
        # El nombre con separadores se escapa y vuelve igual
        assert unescape(field(pid, 5)) == NAME
        assert "|" not in field(pid, 5).replace("\\F\\", "")
        values = {field(o, 3).split("^")[0]: field(o, 5) for o in obx}
        assert values["BG-BIRADS"].startswith("4A^")
        assert values["BG-AI-CLASS"].startswith("maligno^")
        assert values["BG-REC"] == "Biopsia guiada. Control en 6 meses"  # sin saltos de línea
        assert values["BG-AGE"] == "47"

    def test_sin_revision_409_y_sin_auditoria_de_exportacion(self, client, world, owner_engine):
        for fmt in ("pdf", "hl7"):
            response = export(client, world["doc1"], world["aid"], fmt)
            assert response.status_code == 409
            assert "BI-RADS" in response.json()["detail"]
        assert audit_rows(owner_engine, "case.export_pdf") == []
        assert audit_rows(owner_engine, "case.export_hl7") == []

    def test_fallo_de_storage_502_sin_auditoria(self, client, world, storage, owner_engine):
        review(client, world["doc1"], world["aid"])
        storage.objects.clear()
        response = export(client, world["doc1"], world["aid"], "pdf")
        assert response.status_code == 502
        assert audit_rows(owner_engine, "case.export_pdf") == []

    def test_el_hl7_no_descarga_el_mapa_de_calor(self, client, world, storage):
        review(client, world["doc1"], world["aid"])
        storage.objects.clear()
        assert export(client, world["doc1"], world["aid"], "hl7").status_code == 200

    def test_ruta_fuera_del_prefijo_del_tenant_es_404(self, client, world, owner_engine):
        foreign = add_analysis(
            owner_engine,
            world["a"],
            world["pid"],
            world["doc1"],
            heatmap_path=f"{world['b'].slug}/heatmaps/x.png",
        )
        review(client, world["doc1"], foreign)
        assert export(client, world["doc1"], foreign, "pdf").status_code == 404


class TestAccesoCruzado:
    @pytest.mark.parametrize("fmt", ["pdf", "hl7"])
    @pytest.mark.parametrize("who", ["doc2", "outsider"])
    def test_otra_doctora_404_igual_que_inexistente(self, client, world, owner_engine, who, fmt):
        review(client, world["doc1"], world["aid"])
        real = export(client, world[who], world["aid"], fmt)
        missing = export(client, world[who], uuid.uuid4(), fmt)
        assert real.status_code == missing.status_code == 404
        assert real.json() == missing.json()
        denied = audit_rows(owner_engine, "case.denied")
        assert {row["actor_id"] for row in denied} == {world[who].id}
        assert audit_rows(owner_engine, f"case.export_{fmt}") == []

    @pytest.mark.parametrize("who", ["admin", "patient"])
    def test_admin_y_paciente_403(self, client, world, who):
        review(client, world["doc1"], world["aid"])
        for fmt in ("pdf", "hl7"):
            assert export(client, world[who], world["aid"], fmt).status_code == 403

    def test_destinataria_de_traspaso_pendiente_ve_pero_no_exporta(self, client, world):
        review(client, world["doc1"], world["aid"])
        assert create_handover(
            client, world["admin"], world["doc1"], world["doc2"]
        ).status_code in (
            200,
            201,
        )
        case = call(client, "get", f"/patients/{world['pid']}", world["doc2"])
        assert case.status_code == 200
        response = export(client, world["doc2"], world["aid"], "pdf")
        assert response.status_code == 409
        assert "traspaso" in response.json()["detail"]


class TestPdfDeLaPaciente:
    def test_su_propio_resultado(self, client, user_factory, b2c_tenant, owner_engine):
        ana = user_factory(b2c_tenant, role="patient")
        created = patient_upload(client, ana).json()
        response = client.get(
            f"/api/v1/analyses/{created['id']}/report.pdf", headers=auth_headers(ana)
        )
        assert response.status_code == 200
        assert response.content.startswith(b"%PDF")
        assert re.search(
            r'filename="breastguard-reporte-[0-9a-f]{8}\.pdf"',
            response.headers["content-disposition"],
        )
        [entry] = audit_rows(owner_engine, "analysis.export_pdf")
        assert entry["resource_id"] == uuid.UUID(created["id"])
        text = pdf_text(response.content)
        assert created["report"]["title"] in text
        assert "BI-RADS" not in text
        assert "Herramienta de apoyo al diagnóstico" in text

    def test_otra_paciente_404(self, client, user_factory, b2c_tenant, tenant_factory):
        ana = user_factory(b2c_tenant, role="patient")
        eva = user_factory(b2c_tenant, role="patient")
        created = patient_upload(client, ana).json()
        for intruder in (eva, user_factory(tenant_factory("clinica-z"), role="patient")):
            real = client.get(
                f"/api/v1/analyses/{created['id']}/report.pdf", headers=auth_headers(intruder)
            )
            missing = client.get(
                f"/api/v1/analyses/{uuid.uuid4()}/report.pdf", headers=auth_headers(intruder)
            )
            assert real.status_code == missing.status_code == 404


class TestRevisionDeAislamiento:
    """Casos que pidió la revisión de aislamiento de la rama (ADR 0015)."""

    def test_los_409_se_auditan_sin_contenido(self, client, world, owner_engine):
        assert export(client, world["doc1"], world["aid"], "pdf").status_code == 409
        [entry] = audit_rows(owner_engine, "case.export_denied")
        assert entry["resource_type"] == "analysis"
        assert entry["resource_id"] == world["aid"]

    def test_denegado_registra_el_analisis(self, client, world, owner_engine):
        review(client, world["doc1"], world["aid"])
        export(client, world["outsider"], world["aid"], "pdf")
        [entry] = audit_rows(owner_engine, "case.denied")
        assert entry["resource_type"] == "analysis"

    def test_ex_responsable_tras_traspaso_aceptado_404(self, client, world):
        from tests.api.test_handovers import accept

        review(client, world["doc1"], world["aid"])
        handover = create_handover(client, world["admin"], world["doc1"], world["doc2"]).json()
        assert accept(client, world["doc2"], handover["id"]).status_code == 200
        assert export(client, world["doc1"], world["aid"], "pdf").status_code == 404
        # La nueva responsable exporta; el reporte dice quién hizo la revisión
        assert export(client, world["doc2"], world["aid"], "hl7").status_code == 200

    def test_hl7_resiste_inyeccion(self, client, world, owner_engine):
        hostile = "Ana\rMSH|^~\&|FALSO\nOBX|99|ST|x\u2028y ~&^|\\"
        with owner_engine.begin() as conn:
            from sqlalchemy import text

            conn.execute(
                text("UPDATE clinical.patients SET display_name = :n WHERE id = :i"),
                {"n": hostile, "i": world["pid"]},
            )
        name_users(owner_engine, {world["doc1"].id: "Dra.|Inyección^\r\nPID|x"})
        review(client, world["doc1"], world["aid"], recommendation=hostile)
        message = export(client, world["doc1"], world["aid"], "hl7").content.decode()
        segs = validate_oru_r01(message)
        assert [s[0] for s in segs].count("MSH") == 1
        assert [s[0] for s in segs].count("PID") == 1
        assert len([s for s in segs if s[0] == "OBX"]) == len(segs) - 3
        assert message.count("\r") == len(segs)

    def test_paciente_con_ruta_fuera_del_prefijo_404(
        self, client, user_factory, b2c_tenant, owner_engine
    ):
        from sqlalchemy import text

        ana = user_factory(b2c_tenant, role="patient")
        created = patient_upload(client, ana).json()
        with owner_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE clinical.analyses SET heatmap_path = 'otro/heatmaps/x.png' "
                    "WHERE id = :i"
                ),
                {"i": created["id"]},
            )
        response = client.get(
            f"/api/v1/analyses/{created['id']}/report.pdf", headers=auth_headers(ana)
        )
        assert response.status_code == 404

    def test_metadatos_del_pdf_sin_datos_personales(self, client, world):
        pypdf = pytest.importorskip("pypdf")
        review(client, world["doc1"], world["aid"])
        content = export(client, world["doc1"], world["aid"], "pdf").content
        meta = pypdf.PdfReader(io.BytesIO(content)).metadata
        assert "Lucía" not in str(dict(meta)) and "Ana Responsable" not in str(dict(meta))
