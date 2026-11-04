"""Semana 4, de punta a punta en el backend: la paciente B2C comparte, la doctora importa, la ve
en el panel, abre el caso, anota, marca revisado, y la paciente solo ve "importado" (CU-07, CU-08,
CU-11).
"""

import pytest

from tests.api.test_share_import import do_import, shared
from tests.helpers import auth_headers
from tests.panel_helpers import call

API = "/api/v1"


@pytest.fixture
def world(tenant_factory, user_factory, b2c_tenant):
    clinic, other = tenant_factory("clinica-a"), tenant_factory("clinica-b")
    return {
        "clinic": clinic,
        "maria": user_factory(b2c_tenant, role="patient"),
        "doctor": user_factory(clinic, role="doctor"),
        "colleague": user_factory(clinic, role="doctor"),
        "outsider": user_factory(other, role="doctor"),
    }


def test_flujo_completo_comparte_importa_revisa(client, storage, world):
    doctor, maria = world["doctor"], world["maria"]

    package = shared(client, world)
    imported = do_import(client, doctor, package["code"])
    assert imported.status_code == 200, imported.text
    patient_id = imported.json()["patient_id"]

    # Panel: aparece como pendiente y cuenta en el resumen
    page = call(client, "post", "/patients/search", doctor, json={}).json()
    assert [i["id"] for i in page["items"]] == [patient_id]
    row = page["items"][0]
    assert row["origin"] == "importado" and row["status"] == "pendiente"
    assert row["last_analysis"] is not None and row["age_years"] == 44
    summary = call(client, "get", "/patients/summary", doctor).json()
    assert summary["pending_review"] == 1 and summary["active"] == 1

    storage.signed.clear()  # lo firmado antes es de la paciente (b2c)
    # Caso: análisis con URLs firmadas del tenant, diario ligado a su autoexploración, cuestionario
    case = call(client, "get", f"/patients/{patient_id}", doctor).json()
    (analysis,) = case["analyses"]
    assert analysis["image_url"].startswith("https://storage.test/signed/clinica-a/images/")
    assert analysis["heatmap_url"].startswith("https://storage.test/signed/clinica-a/heatmaps/")
    (entry,) = case["symptoms"]
    assert entry["zone"] == "axila" and entry["side"] == "izquierdo"
    assert entry["self_exam_id"] in {e["id"] for e in case["self_exams"]}
    assert case["questionnaire"] is not None and case["questionnaire"]["version"] == "v1"
    assert case["notes"] == [] and case["status"] == "pendiente"
    assert all(path.startswith("clinica-a/") for path in storage.signed)

    # Nota: crear y editar
    note = call(
        client, "post", f"/patients/{patient_id}/notes", doctor, json={"body": "Control en 6 meses"}
    ).json()
    edited = call(
        client, "patch", f"/notes/{note['id']}", doctor, json={"body": "Control en 3 meses"}
    )
    assert edited.json()["body"] == "Control en 3 meses" and edited.json()["updated_at"]

    # Revisar: el panel la muestra revisada y el resumen baja
    reviewed = call(
        client, "patch", f"/patients/{patient_id}/status", doctor, json={"status": "revisado"}
    )
    assert reviewed.status_code == 200 and reviewed.json()["status"] == "revisado"
    page = call(client, "post", "/patients/search", doctor, json={"filter": "revisadas"}).json()
    assert [i["id"] for i in page["items"]] == [patient_id]
    assert (
        call(client, "post", "/patients/search", doctor, json={"filter": "pendientes"}).json()[
            "total"
        ]
        == 0
    )
    summary = call(client, "get", "/patients/summary", doctor).json()
    assert summary["pending_review"] == 0 and summary["active"] == 1
    case = call(client, "get", f"/patients/{patient_id}", doctor).json()
    assert case["status"] == "revisado" and case["reviewed_at"] is not None
    assert [n["body"] for n in case["notes"]] == ["Control en 3 meses"]

    # La paciente ve "importado" y nada más (ni nota ni estado de la médica)
    (item,) = client.get(f"{API}/shares", headers=auth_headers(maria)).json()["items"]
    assert item["status"] == "importado"
    assert "Control" not in str(item) and "revisado" not in item["status"]

    # Otros no ven el caso
    for other in ("colleague", "outsider"):
        assert call(client, "get", f"/patients/{patient_id}", world[other]).status_code == 404
        assert call(client, "post", "/patients/search", world[other], json={}).json()["total"] == 0


def test_la_paciente_no_entra_a_las_rutas_de_la_medica(client, world):
    package = shared(client, world)
    patient_id = do_import(client, world["doctor"], package["code"]).json()["patient_id"]
    for path in (f"/patients/{patient_id}", "/patients/summary"):
        assert call(client, "get", path, world["maria"]).status_code == 403
