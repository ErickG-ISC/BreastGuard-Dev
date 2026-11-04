"""CU-11: panel de la médica (búsqueda, contadores, filtros, orden y traspasos).

Cubre autenticación y roles, aislamiento entre médicas y tenants, "sospechoso" de una sola fuente,
paginación, escape de comodines LIKE y marcas de traspaso.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from tests.api.test_handovers import accept, create
from tests.helpers import auth_headers
from tests.panel_helpers import (
    DOCTOR_ROUTES,
    add_analysis,
    add_patient,
    audit_rows,
    call,
    name_users,
    set_status_as_owner,
)

NOW = datetime.now(UTC)


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
        "patient": user_factory(a, role="patient"),
        "platform": user_factory(role="platform_admin"),
    }
    name_users(
        owner_engine,
        {
            data["doc1"].id: "Dra. Uno",
            data["doc2"].id: "Dra. Dos",
        },
    )
    return data


def search(client, user, **body):
    return call(client, "post", "/patients/search", user, json=body)


def names(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [i["display_name"] for i in response.json()["items"]]


@pytest.fixture
def populated(owner_engine, world):
    """Siete fichas de doc1 con todos los casos del panel."""
    a, doc = world["a"], world["doc1"]

    def make(name, *, created=None, analysis=None, status="pendiente"):
        pid = add_patient(owner_engine, a, doc, name, created_at=created or NOW)
        if analysis is not None:
            add_analysis(owner_engine, a, pid, doc, **analysis)
        if status != "pendiente":
            set_status_as_owner(owner_engine, pid, status)
        return pid

    ids = {
        "S1": make(
            "S1 maligno revisado",
            analysis={"predicted_class": "maligno", "created_at": NOW - timedelta(days=1)},
            status="revisado",
        ),
        "S2": make(
            "S2 flag pendiente",
            analysis={
                "flags": ["notable_malignant_probability"],
                "created_at": NOW - timedelta(days=2),
            },
        ),
        "P1": make(
            "P1 normal pendiente",
            analysis={"created_at": NOW - timedelta(hours=1)},
        ),
        "NC": make(
            "NC no concluyente",
            analysis={
                "predicted_class": "benigno",
                "flags": ["low_confidence"],
                "status": "inconclusive",
                "created_at": NOW - timedelta(hours=2),
            },
        ),
        "P2": make(
            "P2 sin analisis en revision", created=NOW - timedelta(hours=3), status="en_revision"
        ),
        "SIN": make("SIN analisis pendiente", created=NOW - timedelta(hours=4)),
        "R1": make(
            "R1 normal revisada",
            analysis={"created_at": NOW - timedelta(minutes=30)},
            status="revisado",
        ),
    }
    return ids


class TestAccesoYRoles:
    @pytest.mark.parametrize(("method", "path", "kwargs"), DOCTOR_ROUTES)
    def test_sin_token_y_token_invalido_dan_401(self, client, method, path, kwargs):
        path = path.format(pid=uuid.uuid4(), nid=uuid.uuid4())
        assert call(client, method, path, **kwargs).status_code == 401
        response = getattr(client, method)(
            f"/api/v1/doctor{path}", headers={"Authorization": "Bearer basura"}, **kwargs
        )
        assert response.status_code == 401

    @pytest.mark.parametrize("role", ["admin", "patient", "platform"])
    @pytest.mark.parametrize(("method", "path", "kwargs"), DOCTOR_ROUTES)
    def test_otros_roles_reciben_403(self, client, world, role, method, path, kwargs):
        path = path.format(pid=uuid.uuid4(), nid=uuid.uuid4())
        assert call(client, method, path, world[role], **kwargs).status_code == 403

    def test_403_no_audita_en_ningun_tenant(self, client, world, owner_engine):
        search(client, world["patient"])
        assert audit_rows(owner_engine) == []


class TestAislamiento:
    def test_colega_y_otro_tenant_no_ven_las_fichas(self, client, owner_engine, world, populated):
        for other in ("doc2", "doc_b"):
            page = search(client, world[other]).json()
            assert page["items"] == [] and page["total"] == 0
            summary = call(client, "get", "/patients/summary", world[other]).json()
            assert summary == {"pending_review": 0, "suspicious": 0, "active": 0}
        assert len(search(client, world["doc1"]).json()["items"]) == 7

    def test_ficha_propia_de_paciente_con_cuenta_no_aparece(self, client, world, populated):
        # La paciente del tenant tiene ficha 'propio': la doctora no la ve
        assert "Paciente de prueba" not in names(search(client, world["doc1"], limit=50))

    def test_busqueda_se_audita_como_list_sin_el_texto_buscado(
        self, client, owner_engine, world, populated
    ):
        search(client, world["doc1"], q="S1 maligno")
        (row,) = audit_rows(owner_engine, "case.list")
        assert row["tenant_id"] == world["a"].id and row["actor_id"] == world["doc1"].id
        assert "S1" not in str(row)


class TestValidacion:
    @pytest.mark.parametrize(
        "body",
        [
            {"limit": 0},
            {"limit": 51},
            {"offset": -1},
            {"filter": "todos"},
            {"q": "x" * 101},
            {"q": "a\u0000b"},
            {"tenant_id": str(uuid.uuid4())},
            {"limit": "diez"},
        ],
    )
    def test_entrada_invalida_da_422(self, client, world, body):
        assert search(client, world["doc1"], **body).status_code == 422

    def test_tenant_id_del_cliente_no_cambia_el_tenant_efectivo(self, client, world, populated):
        # En la query o en un header se ignora; el tenant sale del JWT
        response = client.post(
            "/api/v1/doctor/patients/search",
            params={"tenant_id": str(world["b"].id)},
            headers={**auth_headers(world["doc1"]), "X-Tenant-Id": str(world["b"].id)},
            json={},
        )
        assert response.status_code == 200 and response.json()["total"] == 7


class TestContadoresYFiltros:
    def test_summary(self, client, world, populated):
        summary = call(client, "get", "/patients/summary", world["doc1"]).json()
        # pendientes: S2, P1, NC, P2, SIN. Sospechosas: S1 y S2 (NC solo low_confidence no cuenta)
        assert summary == {"pending_review": 5, "suspicious": 2, "active": 7}

    def test_summary_no_audita_pero_search_si(self, client, owner_engine, world, populated):
        call(client, "get", "/patients/summary", world["doc1"])
        assert audit_rows(owner_engine, "case.list") == []

    @pytest.mark.parametrize(
        ("filter_", "expected"),
        [
            ("todas", {"S1", "S2", "P1", "NC", "P2", "SIN", "R1"}),
            ("pendientes", {"S2", "P1", "NC", "P2", "SIN"}),
            ("sospechosos", {"S1", "S2"}),
            ("revisadas", {"S1", "R1"}),
        ],
    )
    def test_cada_filtro(self, client, world, populated, filter_, expected):
        page = search(client, world["doc1"], filter=filter_).json()
        assert {i["display_name"].split()[0] for i in page["items"]} == expected
        assert page["total"] == len(expected)

    def test_no_concluyente_no_es_sospechosa(self, client, world, populated):
        items = {
            i["display_name"].split()[0]: i for i in search(client, world["doc1"]).json()["items"]
        }
        assert items["NC"]["last_analysis"]["suspicious"] is False
        assert items["NC"]["last_analysis"]["inconclusive"] is True
        assert items["S1"]["last_analysis"]["suspicious"] is True
        assert items["S2"]["last_analysis"]["suspicious"] is True
        assert items["SIN"]["last_analysis"] is None
        assert items["P1"]["last_analysis"]["suspicious"] is False

    def test_solo_cuenta_el_ultimo_analisis(self, client, owner_engine, world):
        a, doc = world["a"], world["doc1"]
        pid = add_patient(owner_engine, a, doc, "Mejoro")
        add_analysis(
            owner_engine, a, pid, doc, predicted_class="maligno", created_at=NOW - timedelta(days=3)
        )
        add_analysis(owner_engine, a, pid, doc, created_at=NOW - timedelta(days=1))
        assert call(client, "get", "/patients/summary", doc).json()["suspicious"] == 0
        assert search(client, world["doc1"], filter="sospechosos").json()["total"] == 0

    def test_orden_sospechosas_luego_pendientes_luego_recientes(self, client, world, populated):
        order = [i.split()[0] for i in names(search(client, world["doc1"]))]
        assert order == ["S2", "S1", "P1", "NC", "P2", "SIN", "R1"]


class TestBusquedaYPaginacion:
    @pytest.fixture
    def named(self, owner_engine, world):
        for name in ("Ana 100%", "Ana_Z", "AnaZZ", "Ruta\\x", "María López"):
            add_patient(owner_engine, world["a"], world["doc1"], name)

    def test_busqueda_sin_distinguir_mayusculas(self, client, world, named):
        assert sorted(names(search(client, world["doc1"], q="ANA"))) == [
            "Ana 100%",
            "AnaZZ",
            "Ana_Z",
        ]
        assert names(search(client, world["doc1"], q="  maría ")) == ["María López"]

    def test_porcentaje_se_escapa(self, client, world, named):
        assert names(search(client, world["doc1"], q="%")) == ["Ana 100%"]

    def test_guion_bajo_se_escapa(self, client, world, named):
        assert names(search(client, world["doc1"], q="_")) == ["Ana_Z"]
        assert names(search(client, world["doc1"], q="Ana_Z")) == ["Ana_Z"]

    def test_contrabarra_se_escapa(self, client, world, named):
        assert names(search(client, world["doc1"], q="\\")) == ["Ruta\\x"]

    def test_q_en_blanco_no_filtra(self, client, world, named):
        assert search(client, world["doc1"], q="   ").json()["total"] == 5

    def test_busqueda_se_combina_con_filtro(self, client, world, populated):
        assert names(search(client, world["doc1"], q="normal", filter="revisadas")) == [
            "R1 normal revisada"
        ]

    def test_paginacion(self, client, world, populated):
        seen = []
        for offset in (0, 3, 6):
            page = search(client, world["doc1"], limit=3, offset=offset).json()
            assert page["total"] == 7 and page["limit"] == 3 and page["offset"] == offset
            seen += [i["display_name"] for i in page["items"]]
        assert [n.split()[0] for n in seen] == ["S2", "S1", "P1", "NC", "P2", "SIN", "R1"]
        past_end = search(client, world["doc1"], limit=3, offset=9).json()
        assert past_end["items"] == [] and past_end["total"] == 7


class TestTraspasos:
    @pytest.fixture
    def handover_world(self, owner_engine, world):
        a = world["a"]
        mine = add_patient(owner_engine, a, world["doc1"], "Mia")
        theirs = add_patient(owner_engine, a, world["doc2"], "Suya")
        return mine, theirs

    def test_traspaso_pendiente_hacia_ella_aparece_marcado(self, client, world, handover_world):
        _, theirs = handover_world
        assert create(client, world["admin"], world["doc2"], world["doc1"]).status_code == 201
        items = {i["display_name"]: i for i in search(client, world["doc1"]).json()["items"]}
        assert set(items) == {"Mia", "Suya"}
        assert items["Suya"]["handover_from"] == "Dra. Dos" and items["Suya"]["handover_to"] is None
        assert items["Mia"]["handover_from"] is None and items["Mia"]["handover_to"] is None
        summary = call(client, "get", "/patients/summary", world["doc1"]).json()
        assert summary["active"] == 2
        case = call(client, "get", f"/patients/{theirs}", world["doc1"]).json()
        assert case["handover_from"] == "Dra. Dos"

    def test_propias_con_traspaso_pendiente_desde_ella_llevan_handover_to(
        self, client, world, handover_world
    ):
        mine, _ = handover_world
        create(client, world["admin"], world["doc1"], world["doc2"])
        items = {i["display_name"]: i for i in search(client, world["doc1"]).json()["items"]}
        assert items["Mia"]["handover_to"] == "Dra. Dos"
        case = call(client, "get", f"/patients/{mine}", world["doc1"]).json()
        assert case["handover_to"] == "Dra. Dos"

    def test_aceptado_hacia_otra_desaparece_y_pasa_a_la_destinataria(
        self, client, world, handover_world
    ):
        mine, _ = handover_world
        handover = create(client, world["admin"], world["doc1"], world["doc2"]).json()
        assert accept(client, world["doc2"], handover["id"]).status_code == 200
        assert names(search(client, world["doc1"])) == []
        assert call(client, "get", f"/patients/{mine}", world["doc1"]).status_code == 404
        items = search(client, world["doc2"]).json()["items"]
        assert sorted(i["display_name"] for i in items) == ["Mia", "Suya"]
        assert all(i["handover_from"] is None for i in items)

    def test_otra_colega_no_ve_el_traspaso_pendiente(
        self, client, world, handover_world, user_factory
    ):
        third = user_factory(world["a"], role="doctor")
        create(client, world["admin"], world["doc1"], world["doc2"])
        assert search(client, third).json()["total"] == 0
