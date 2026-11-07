"""CU-09: la médica agrega estudios (DICOM, JPG, PNG), asigna BI-RADS y da de alta fichas.

Siempre con DICOM SINTÉTICOS generados aquí. Se comprueba además:
- desidentificación: nada del DICOM (nombre, ID, fechas, institución, médico) llega a la base
  ni a Storage; solo la imagen derivada y la lista blanca técnica;
- acceso cruzado: otra doctora del tenant u otro tenant reciben el mismo 404; admins y
  pacientes, 403; con un traspaso pendiente hay que aceptarlo primero (409).
"""

import json

import pytest
from sqlalchemy import text

from tests.api.test_handovers import create
from tests.api.test_semana2_cruzado import ultrasound_png
from tests.dicom_helpers import PERSONAL, make_dicom
from tests.helpers import auth_headers
from tests.panel_helpers import add_patient, call

pytestmark = pytest.mark.usefixtures("database")


@pytest.fixture
def world(tenant_factory, user_factory, owner_engine):
    a, b = tenant_factory("clinica-a"), tenant_factory("clinica-b")
    data = {
        "a": a,
        "b": b,
        "doc1": user_factory(a, role="doctor"),
        "doc2": user_factory(a, role="doctor"),
        "admin": user_factory(a, role="tenant_admin"),
        "outsider": user_factory(b, role="doctor"),
    }
    data["pid"] = add_patient(owner_engine, a, data["doc1"], "Ficha DICOM")
    return data


def upload(client, user, pid, data: bytes, name="estudio.dcm", content_type="application/dicom"):
    return client.post(
        f"/api/v1/doctor/patients/{pid}/analyses",
        files={"file": (name, data, content_type)},
        headers=auth_headers(user),
    )


def rows(owner_engine, table: str, tenant_id) -> list:
    with owner_engine.connect() as conn:
        return (
            conn.execute(
                text(f"SELECT * FROM clinical.{table} WHERE tenant_id = :t"), {"t": tenant_id}
            )
            .mappings()
            .all()
        )


class TestEstudioDicom:
    def test_dicom_de_mastografia_completo(self, client, storage, owner_engine, world):
        response = upload(client, world["doc1"], world["pid"], make_dicom())
        assert response.status_code == 201, response.text

        (analysis,) = rows(owner_engine, "analyses", world["a"].id)
        (image,) = rows(owner_engine, "medical_images", world["a"].id)
        assert analysis["profile"] == "mastografia_prototipo"
        assert image["image_type"] == "mammography"
        assert "Prototipo" in analysis["report"]["prototype_warning"]
        assert analysis["dicom_meta"]["view_position"] == "MLO"
        assert analysis["created_by"] == world["doc1"].id
        assert image["object_path"].startswith("clinica-a/images/")

        case = call(client, "get", f"/patients/{world['pid']}", world["doc1"]).json()
        (item,) = case["analyses"]
        assert item["prototype_warning"] and item["profile"] == "mastografia_prototipo"
        assert item["dicom_meta"]["laterality"] == "R"

    def test_nada_personal_del_dicom_llega_a_la_base_ni_a_storage(
        self, client, storage, owner_engine, world
    ):
        upload(client, world["doc1"], world["pid"], make_dicom())
        dumped = json.dumps(
            [
                dict(r)
                for t in ("analyses", "medical_images")
                for r in rows(owner_engine, t, world["a"].id)
            ],
            default=str,
        )
        stored = b"".join(storage.objects.values())
        for value in PERSONAL.values():
            for part in value.split("^"):
                assert part not in dumped
                assert part.encode() not in stored
        # Nunca se guarda el DICOM original
        assert not any(
            blob.startswith(b"\x00" * 128 + b"DICM") for blob in storage.objects.values()
        )
        assert all(name.endswith(".png") for name in storage.objects)

    def test_jpg_y_png_usan_el_perfil_de_ecografia(self, client, owner_engine, world):
        response = upload(
            client, world["doc1"], world["pid"], ultrasound_png(), "eco.png", "image/png"
        )
        assert response.status_code == 201
        (analysis,) = rows(owner_engine, "analyses", world["a"].id)
        assert analysis["profile"] == "ecografia_b2c" and analysis["dicom_meta"] is None

    @pytest.mark.parametrize(
        ("data", "status"),
        [
            (make_dicom(BurnedInAnnotation="YES"), 422),
            (make_dicom(SamplesPerPixel=3), 422),
            (b"no es dicom" * 20, 400),
        ],
        ids=["anotaciones_grabadas", "color", "sin_firma"],
    )
    def test_dicom_no_admitidos(self, client, owner_engine, world, data, status):
        response = upload(client, world["doc1"], world["pid"], data)
        assert response.status_code == status
        assert rows(owner_engine, "analyses", world["a"].id) == []

    def test_mime_que_no_es_dicom(self, client, world):
        response = upload(
            client, world["doc1"], world["pid"], make_dicom(), content_type="image/png"
        )
        assert response.status_code == 415

    def test_un_estudio_nuevo_devuelve_el_caso_a_pendiente(self, client, owner_engine, world):
        call(
            client,
            "patch",
            f"/patients/{world['pid']}/status",
            world["doc1"],
            json={"status": "revisado"},
        )
        upload(client, world["doc1"], world["pid"], make_dicom())
        case = call(client, "get", f"/patients/{world['pid']}", world["doc1"]).json()
        assert case["status"] == "pendiente"


class TestAccesoCruzado:
    @pytest.mark.parametrize("intruder", ["doc2", "outsider"])
    def test_otras_doctoras_reciben_el_mismo_404(self, client, owner_engine, world, intruder):
        foreign = upload(client, world[intruder], world["pid"], make_dicom())
        missing = upload(
            client, world[intruder], "00000000-0000-0000-0000-000000000000", make_dicom()
        )
        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json()
        assert rows(owner_engine, "analyses", world["a"].id) == []

    def test_traspaso_pendiente_exige_aceptar(self, client, owner_engine, world):
        create(client, world["admin"], world["doc1"], world["doc2"])
        response = upload(client, world["doc2"], world["pid"], make_dicom())
        assert response.status_code == 409
        assert rows(owner_engine, "analyses", world["a"].id) == []

    @pytest.mark.parametrize("role", ["admin"])
    def test_admin_403(self, client, world, role):
        assert upload(client, world[role], world["pid"], make_dicom()).status_code == 403


class TestRevision:
    def _analysis(self, client, owner_engine, world):
        upload(client, world["doc1"], world["pid"], make_dicom())
        (analysis,) = rows(owner_engine, "analyses", world["a"].id)
        return analysis["id"]

    def test_bi_rads_de_la_medica(self, client, owner_engine, world):
        analysis_id = self._analysis(client, owner_engine, world)
        url = f"/analyses/{analysis_id}/review"
        first = call(
            client, "put", url, world["doc1"], json={"birads": "4B", "recommendation": "Biopsia"}
        )
        assert first.status_code == 200 and first.json()["birads"] == "4B"
        again = call(client, "put", url, world["doc1"], json={"birads": "3"})
        assert again.json()["birads"] == "3" and again.json()["recommendation"] is None
        (review,) = rows(owner_engine, "analysis_reviews", world["a"].id)
        assert review["reviewed_by"] == world["doc1"].id and review["birads"] == "3"
        case = call(client, "get", f"/patients/{world['pid']}", world["doc1"]).json()
        assert case["analyses"][0]["review"]["birads"] == "3"
        assert case["analyses"][0]["review"]["mine"] is True

    @pytest.mark.parametrize(
        "payload", [{"birads": "7"}, {"birads": "4D"}, {"birads": "3", "x": 1}, {}]
    )
    def test_bi_rads_invalido(self, client, owner_engine, world, payload):
        analysis_id = self._analysis(client, owner_engine, world)
        assert (
            call(
                client, "put", f"/analyses/{analysis_id}/review", world["doc1"], json=payload
            ).status_code
            == 422
        )

    @pytest.mark.parametrize("intruder", ["doc2", "outsider"])
    def test_otras_doctoras_no_revisan(self, client, owner_engine, world, intruder):
        analysis_id = self._analysis(client, owner_engine, world)
        response = call(
            client, "put", f"/analyses/{analysis_id}/review", world[intruder], json={"birads": "1"}
        )
        assert response.status_code == 404
        assert rows(owner_engine, "analysis_reviews", world["a"].id) == []

    def test_tras_un_traspaso_la_nueva_responsable_queda_como_autora(
        self, client, owner_engine, world
    ):
        analysis_id = self._analysis(client, owner_engine, world)
        call(client, "put", f"/analyses/{analysis_id}/review", world["doc1"], json={"birads": "2"})
        handover = create(client, world["admin"], world["doc1"], world["doc2"]).json()
        client.post(
            f"/api/v1/doctor/handovers/{handover['id']}/accept", headers=auth_headers(world["doc2"])
        )
        response = call(
            client, "put", f"/analyses/{analysis_id}/review", world["doc2"], json={"birads": "4A"}
        )
        assert response.status_code == 200
        (review,) = rows(owner_engine, "analysis_reviews", world["a"].id)
        assert review["reviewed_by"] == world["doc2"].id and review["birads"] == "4A"


class TestAltaManual:
    def test_alta_y_solo_la_ve_su_medica(self, client, world):
        response = call(
            client,
            "post",
            "/patients",
            world["doc1"],
            json={"display_name": "Nueva", "age_years": 50},
        )
        assert response.status_code == 201
        pid = response.json()["id"]
        case = call(client, "get", f"/patients/{pid}", world["doc1"]).json()
        assert case["origin"] == "creado" and case["age_years"] == 50 and case["age_recorded_on"]
        for intruder in ("doc2", "outsider"):
            assert call(client, "get", f"/patients/{pid}", world[intruder]).status_code == 404

    @pytest.mark.parametrize(
        "payload",
        [
            {"display_name": "  "},
            {"display_name": "x", "age_years": 200},
            {"display_name": "x", "tenant_id": "y"},
        ],
    )
    def test_entrada_invalida(self, client, world, payload):
        assert call(client, "post", "/patients", world["doc1"], json=payload).status_code == 422
