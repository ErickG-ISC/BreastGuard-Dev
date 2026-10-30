"""Acceso clínico por rol (ADR 0009), probado como el rol de la app.

- La paciente ve solo lo suyo (por `user_id`).
- La doctora ve solo a sus pacientes (por `responsible_doctor_id`), ni las de otra doctora de su
  mismo tenant ni las de otro tenant.
- tenant_admin y platform_admin no ven nada clínico (la auditoría sigue su propia política).
- Las FKs no pasan por RLS: las compuestas con `patient_id` impiden enlazar filas de otra paciente.
- Los CHECK de `patients` mantienen coherentes origen, cuenta y médica responsable.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from backend.app.db import TenantContext, new_session
from tests.helpers import tenant_session
from tests.isolation.test_rls_por_tabla import MODEL_TABLES, RECIPES, seed

pytestmark = pytest.mark.usefixtures("database")

CLINICAL_TABLES = [t for t in MODEL_TABLES if t != "audit_log"]


@pytest.fixture
def clinics(tenant_factory, user_factory):
    a, b = tenant_factory("clinica-a"), tenant_factory("clinica-b")
    return {
        "a": a,
        "b": b,
        "doctor_a1": user_factory(a, role="doctor"),
        "doctor_a2": user_factory(a, role="doctor"),
        "doctor_b": user_factory(b, role="doctor"),
        "admin_a": user_factory(a, role="tenant_admin"),
    }


def visible_ids(user, table: str) -> set:
    with tenant_session(user) as session:
        return set(session.scalars(text(f"SELECT id FROM clinical.{table}")))


@pytest.mark.parametrize("table", CLINICAL_TABLES)
class TestDoctoraSoloSusPacientes:
    def test_otra_doctora_del_mismo_tenant_no_ve_la_fila(self, owner_engine, clinics, table):
        mine = seed(owner_engine, table, clinics["a"], clinics["doctor_a1"])
        theirs = seed(owner_engine, table, clinics["a"], clinics["doctor_a2"])
        assert visible_ids(clinics["doctor_a1"], table) == {mine.id}
        assert visible_ids(clinics["doctor_a2"], table) == {theirs.id}

    def test_doctora_de_otro_tenant_no_ve_la_fila(self, owner_engine, clinics, table):
        seed(owner_engine, table, clinics["a"], clinics["doctor_a1"])
        assert visible_ids(clinics["doctor_b"], table) == set()

    def test_tenant_admin_no_ve_datos_clinicos(self, owner_engine, clinics, table):
        seed(owner_engine, table, clinics["a"], clinics["doctor_a1"])
        assert visible_ids(clinics["admin_a"], table) == set()

    def test_otra_doctora_no_puede_escribir_filas_de_la_paciente(
        self, owner_engine, clinics, table
    ):
        if table == "patients":
            pytest.skip("una ficha nueva no tiene filas de apoyo ajenas")
        recipe = RECIPES[table]
        # Filas de apoyo (ficha, imagen, análisis...) de una paciente de la doctora a2
        with owner_engine.begin() as conn:
            theirs = recipe.parents(conn, clinics["a"].id, clinics["doctor_a2"])
        # Control positivo: la responsable sí escribe con esas filas de apoyo
        with tenant_session(clinics["doctor_a2"]) as session:
            recipe.insert(session, None, clinics["doctor_a2"], theirs, {})
            session.rollback()
        with (
            tenant_session(clinics["doctor_a1"]) as session,
            pytest.raises(DBAPIError, match="row-level|foreign key"),
        ):
            recipe.insert(session, None, clinics["doctor_a1"], theirs, {})
            session.flush()

    def test_tenant_admin_no_puede_escribir(self, owner_engine, clinics, table):
        recipe = RECIPES[table]
        with owner_engine.begin() as conn:
            parents = recipe.parents(conn, clinics["a"].id, clinics["doctor_a1"])
        with (
            tenant_session(clinics["admin_a"]) as session,
            pytest.raises(DBAPIError, match="row-level|foreign key"),
        ):
            recipe.insert(session, None, clinics["admin_a"], parents, {})
            session.flush()


class TestPaciente:
    def test_la_paciente_ve_solo_su_ficha(self, owner_engine, clinics, user_factory):
        maria = user_factory(clinics["a"], role="patient")
        other = user_factory(clinics["a"], role="patient")
        seed(owner_engine, "patients", clinics["a"], clinics["doctor_a1"])
        assert visible_ids(maria, "patients") == {maria.patient_id}
        assert other.patient_id not in visible_ids(maria, "patients")

    def test_la_doctora_no_ve_fichas_propias_de_pacientes_con_cuenta(self, clinics, user_factory):
        maria = user_factory(clinics["a"], role="patient")
        assert maria.patient_id not in visible_ids(clinics["doctor_a1"], "patients")

    def test_platform_admin_no_ve_datos_clinicos(self, owner_engine, clinics):
        seed(owner_engine, "patients", clinics["a"], clinics["doctor_a1"])
        # Aun con un tenant forzado en el contexto, el rol no da acceso clínico
        context = TenantContext(clinics["a"].id, uuid.uuid4(), "platform_admin")
        with new_session(context) as session:
            for table in CLINICAL_TABLES:
                count = session.execute(text(f"SELECT count(*) FROM clinical.{table}"))
                assert count.scalar_one() == 0, table


class TestDoctoraNoSeAsignaPacientesAjenas:
    def test_no_crea_fichas_con_otra_responsable(self, clinics):
        doctor = clinics["doctor_a1"]
        with tenant_session(doctor) as session, pytest.raises(DBAPIError, match="row-level"):
            RECIPES["patients"].insert(
                session, None, doctor, {}, {"responsible": clinics["doctor_a2"].id}
            )

    def test_no_reasigna_ni_cambia_el_origen(self, owner_engine, clinics):
        mine = seed(owner_engine, "patients", clinics["a"], clinics["doctor_a1"])
        for column, value in (
            ("responsible_doctor_id", f"'{clinics['doctor_a2'].id}'"),
            ("origin", "'importado'"),
            ("user_id", "NULL"),
        ):
            with (
                tenant_session(clinics["doctor_a1"]) as session,
                pytest.raises(DBAPIError, match="permission denied"),
            ):
                session.execute(
                    text(f"UPDATE clinical.patients SET {column} = {value} WHERE id = :id"),
                    {"id": mine.id},
                )

    def test_si_cambia_el_estado_de_sus_pacientes(self, owner_engine, clinics):
        mine = seed(owner_engine, "patients", clinics["a"], clinics["doctor_a1"])
        theirs = seed(owner_engine, "patients", clinics["a"], clinics["doctor_a2"])
        sql = text("UPDATE clinical.patients SET status = 'revisado' WHERE id = :id")
        with tenant_session(clinics["doctor_a1"]) as session:
            assert session.execute(sql, {"id": mine.id}).rowcount == 1
            assert session.execute(sql, {"id": theirs.id}).rowcount == 0
            session.rollback()

    def test_notas_y_revisiones_solo_con_ella_como_autora(self, owner_engine, clinics):
        doctor = clinics["doctor_a1"]
        mine = seed(owner_engine, "analysis_reviews", clinics["a"], doctor)
        for table, column in (("case_notes", "author_id"), ("analysis_reviews", "reviewed_by")):
            parents = RECIPES[table].parents
            with owner_engine.begin() as conn:
                support = parents(conn, clinics["a"].id, doctor)
            with tenant_session(doctor) as session, pytest.raises(DBAPIError, match="row-level"):
                RECIPES[table].insert(
                    session, None, doctor, support, {column: clinics["doctor_a2"].id}
                )
        assert mine.id in visible_ids(doctor, "analysis_reviews")


class TestFkMismaPaciente:
    """Las FKs no pasan por RLS: imagen, análisis y revisión deben ser de la misma paciente."""

    def test_analisis_con_imagen_de_otra_paciente_de_la_misma_doctora(self, owner_engine, clinics):
        doctor = clinics["doctor_a1"]
        first = seed(owner_engine, "medical_images", clinics["a"], doctor)
        second = seed(owner_engine, "medical_images", clinics["a"], doctor)
        parents = {"patient_id": first.parents["patient_id"], "image_id": second.id}
        with tenant_session(doctor) as session, pytest.raises(DBAPIError, match="foreign key"):
            RECIPES["analyses"].insert(session, None, doctor, parents, {})
            session.flush()

    def test_revision_con_analisis_de_otra_paciente_de_la_misma_doctora(
        self, owner_engine, clinics
    ):
        doctor = clinics["doctor_a1"]
        first = seed(owner_engine, "analyses", clinics["a"], doctor)
        second = seed(owner_engine, "analyses", clinics["a"], doctor)
        parents = {"patient_id": first.parents["patient_id"], "analysis_id": second.id}
        with tenant_session(doctor) as session, pytest.raises(DBAPIError, match="foreign key"):
            RECIPES["analysis_reviews"].insert(session, None, doctor, parents, {})
            session.flush()


def _owner_insert_patient(owner_engine, tenant, **columns):
    values = {"tenant_id": tenant.id, "display_name": "Ficha", **columns}
    names = ", ".join(values)
    binds = ", ".join(f":{k}" for k in values)
    with owner_engine.begin() as conn:
        conn.execute(text(f"INSERT INTO clinical.patients ({names}) VALUES ({binds})"), values)


class TestChecksDePatients:
    @pytest.mark.parametrize(
        ("label", "columns"),
        [
            ("propio_con_responsable", {"origin": "propio", "user": True, "doctor": True}),
            ("propio_sin_cuenta", {"origin": "propio"}),
            ("creado_sin_responsable", {"origin": "creado"}),
            ("importado_con_cuenta", {"origin": "importado", "user": True, "doctor": True}),
            ("origen_desconocido", {"origin": "otro", "doctor": True}),
            ("estado_desconocido", {"origin": "creado", "doctor": True, "status": "x"}),
            ("edad_imposible", {"origin": "creado", "doctor": True, "age_years": 130}),
            ("paquete_en_ficha_creada", {"origin": "creado", "doctor": True, "package": True}),
        ],
    )
    def test_combinaciones_invalidas_fallan(
        self, owner_engine, clinics, user_factory, label, columns
    ):
        columns = dict(columns)
        values = {"origin": columns.pop("origin")}
        if columns.pop("user", False):
            values["user_id"] = user_factory(clinics["a"], role="doctor").id
        if columns.pop("doctor", False):
            values["responsible_doctor_id"] = clinics["doctor_a1"].id
        if columns.pop("package", False):
            values["source_package_id"] = uuid.uuid4()
        values.update(columns)
        with pytest.raises(DBAPIError, match="check constraint"):
            _owner_insert_patient(owner_engine, clinics["a"], **values)

    def test_un_paquete_se_importa_una_sola_vez_por_tenant(self, owner_engine, clinics):
        package = uuid.uuid4()
        row = {
            "origin": "importado",
            "responsible_doctor_id": clinics["doctor_a1"].id,
            "source_package_id": package,
        }
        _owner_insert_patient(owner_engine, clinics["a"], **row)
        with pytest.raises(DBAPIError, match="ux_patients_source_package"):
            _owner_insert_patient(owner_engine, clinics["a"], **row)
        # En otro tenant el mismo id no choca (cada tenant tiene su copia)
        _owner_insert_patient(
            owner_engine, clinics["b"], **{**row, "responsible_doctor_id": clinics["doctor_b"].id}
        )

    def test_la_responsable_debe_ser_del_mismo_tenant(self, owner_engine, clinics):
        with pytest.raises(DBAPIError, match="fk_patients_responsible_doctor"):
            _owner_insert_patient(
                owner_engine,
                clinics["a"],
                origin="creado",
                responsible_doctor_id=clinics["doctor_b"].id,
            )
