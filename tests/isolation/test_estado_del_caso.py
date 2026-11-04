"""Migración 0017 probada directamente en Postgres como `app_user`.

- trigger de transiciones de `patients.status` y `reviewed_*` que solo escribe el trigger;
- trigger que devuelve el caso a pendiente cuando entra un análisis;
- `case_notes`: UPDATE (body, updated_at) y DELETE solo de su autora, SELECT solo de doctoras;
- catálogo: políticas, triggers, privilegios y que las funciones no sean SECURITY DEFINER.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.helpers import tenant_session
from tests.isolation.test_rls_por_tabla import app_privilege
from tests.panel_helpers import (
    add_note,
    add_patient,
    insert_analysis,
    patient_row,
    set_status_as_owner,
)

pytestmark = pytest.mark.usefixtures("database")

VALID = [
    ("pendiente", "en_revision"),
    ("pendiente", "revisado"),
    ("en_revision", "revisado"),
    ("en_revision", "pendiente"),
    ("revisado", "en_revision"),
]
INVALID = [
    ("pendiente", "pendiente"),
    ("en_revision", "en_revision"),
    ("revisado", "revisado"),
    ("revisado", "pendiente"),
]


@pytest.fixture
def world(tenant_factory, user_factory):
    a, b = tenant_factory("clinica-a"), tenant_factory("clinica-b")
    return {
        "a": a,
        "b": b,
        "doc1": user_factory(a, role="doctor"),
        "doc2": user_factory(a, role="doctor"),
        "doc_b": user_factory(b, role="doctor"),
        "admin": user_factory(a, role="tenant_admin"),
        "patient": user_factory(a, role="patient"),
    }


def update_status(user, pid, new_status) -> int:
    with tenant_session(user) as session:
        result = session.execute(
            text("UPDATE clinical.patients SET status = :s WHERE id = :i"),
            {"s": new_status, "i": pid},
        )
        session.commit()
        return result.rowcount


def at_status(owner_engine, world, status):
    pid = add_patient(owner_engine, world["a"], world["doc1"])
    if status != "pendiente":
        set_status_as_owner(owner_engine, pid, status)
    return pid


class TestTransiciones:
    @pytest.mark.parametrize(("start", "target"), VALID)
    def test_validas_como_la_doctora(self, owner_engine, world, start, target):
        pid = at_status(owner_engine, world, start)
        assert update_status(world["doc1"], pid, target) == 1
        row = patient_row(owner_engine, pid)
        assert row["status"] == target
        if target == "revisado":
            assert row["reviewed_by"] == world["doc1"].id and row["reviewed_at"] is not None
        else:
            assert row["reviewed_by"] is None and row["reviewed_at"] is None

    @pytest.mark.parametrize(("start", "target"), INVALID)
    def test_invalidas_fallan_en_la_base(self, owner_engine, world, start, target):
        pid = at_status(owner_engine, world, start)
        with pytest.raises(DBAPIError, match="Transición de estado no permitida"):
            update_status(world["doc1"], pid, target)
        assert patient_row(owner_engine, pid)["status"] == start

    def test_estado_fuera_del_catalogo_falla(self, owner_engine, world):
        pid = at_status(owner_engine, world, "pendiente")
        with pytest.raises(DBAPIError):
            update_status(world["doc1"], pid, "aprobado")

    def test_el_trigger_tambien_rige_al_dueño(self, owner_engine, world):
        pid = at_status(owner_engine, world, "revisado")
        with pytest.raises(DBAPIError, match="Transición de estado no permitida"):
            set_status_as_owner(owner_engine, pid, "pendiente")

    @pytest.mark.parametrize("actor", ["doc2", "doc_b", "admin", "patient"])
    def test_otros_usuarios_no_cambian_el_estado(self, owner_engine, world, actor):
        pid = at_status(owner_engine, world, "pendiente")
        try:
            affected = update_status(world[actor], pid, "revisado")
        except DBAPIError:
            affected = 0  # sin privilegio de columna / política: tampoco cambia nada
        assert affected == 0
        assert patient_row(owner_engine, pid)["status"] == "pendiente"


class TestRevisionProtegida:
    @pytest.mark.parametrize("column", ["reviewed_by", "reviewed_at"])
    def test_la_doctora_no_escribe_reviewed_a_mano(self, owner_engine, world, column):
        pid = at_status(owner_engine, world, "revisado")
        before = patient_row(owner_engine, pid)
        value = ":me" if column == "reviewed_by" else "now()"
        with tenant_session(world["doc1"]) as session, pytest.raises(DBAPIError):
            session.execute(
                text(f"UPDATE clinical.patients SET {column} = {value} WHERE id = :i"),
                {"i": pid, "me": world["doc2"].id},
            )
        assert patient_row(owner_engine, pid) == before

    def test_ni_el_dueño_cambia_reviewed_sin_cambiar_el_estado(self, owner_engine, world):
        pid = at_status(owner_engine, world, "revisado")
        with (
            owner_engine.begin() as conn,
            pytest.raises(DBAPIError, match="La revisión solo cambia junto con el estado"),
        ):
            conn.execute(
                text("UPDATE clinical.patients SET reviewed_at = now() WHERE id = :i"), {"i": pid}
            )

    def test_el_trigger_pisa_reviewed_enviado_junto_con_el_estado(self, owner_engine, world):
        # Aunque se intente, el trigger fija quién revisó (la doctora del contexto)
        pid = at_status(owner_engine, world, "pendiente")
        with owner_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE clinical.patients SET status = 'revisado', reviewed_by = :x, "
                    "reviewed_at = '2001-01-01' WHERE id = :i"
                ),
                {"i": pid, "x": world["doc2"].id},
            )
        row = patient_row(owner_engine, pid)
        assert row["reviewed_by"] != world["doc2"].id
        assert row["reviewed_at"].year != 2001


class TestAnalisisReabre:
    def test_insertar_como_dueño_devuelve_a_pendiente(self, owner_engine, world):
        pid = at_status(owner_engine, world, "revisado")
        with owner_engine.begin() as conn:
            insert_analysis(conn, world["a"], pid, world["doc1"])
        row = patient_row(owner_engine, pid)
        assert row["status"] == "pendiente" and row["reviewed_by"] is None

    def test_insertar_como_la_doctora_devuelve_a_pendiente(self, owner_engine, world):
        pid = at_status(owner_engine, world, "revisado")
        with tenant_session(world["doc1"]) as session:
            insert_analysis(session.connection(), world["a"], pid, world["doc1"])
            session.commit()
        row = patient_row(owner_engine, pid)
        assert row["status"] == "pendiente"
        assert row["reviewed_by"] is None and row["reviewed_at"] is None

    @pytest.mark.parametrize("start", ["en_revision", "revisado"])
    def test_tambien_desde_en_revision(self, owner_engine, world, start):
        pid = at_status(owner_engine, world, start)
        with owner_engine.begin() as conn:
            insert_analysis(conn, world["a"], pid, world["doc1"])
        assert patient_row(owner_engine, pid)["status"] == "pendiente"

    def test_pendiente_sigue_pendiente_sin_error(self, owner_engine, world):
        pid = at_status(owner_engine, world, "pendiente")
        with owner_engine.begin() as conn:
            insert_analysis(conn, world["a"], pid, world["doc1"])
        assert patient_row(owner_engine, pid)["status"] == "pendiente"

    def test_la_bandera_automatica_no_queda_activa(self, owner_engine, world):
        pid = at_status(owner_engine, world, "revisado")
        with tenant_session(world["doc1"]) as session:
            insert_analysis(session.connection(), world["a"], pid, world["doc1"])
            flag = session.execute(
                text("SELECT current_setting('app.case_status_auto', true)")
            ).scalar_one()
            assert flag in (None, "")
            session.commit()

    def test_no_se_puede_reabrir_a_mano_con_la_bandera(self, owner_engine, world):
        # La bandera es de transacción: sin análisis nuevo, revisado → pendiente sigue prohibido
        pid = at_status(owner_engine, world, "revisado")
        with pytest.raises(DBAPIError, match="Transición de estado no permitida"):
            update_status(world["doc1"], pid, "pendiente")


class TestNotasEnLaBase:
    @pytest.fixture
    def note(self, owner_engine, world):
        pid = add_patient(owner_engine, world["a"], world["doc1"])
        return pid, add_note(owner_engine, world["a"], pid, world["doc1"], "original")

    def test_la_paciente_nunca_ve_notas(self, owner_engine, world, note):
        # Hay notas en su tenant, pero la regla SELECT es solo de doctoras
        for user in ("patient", "admin"):
            with tenant_session(world[user]) as session:
                count = session.execute(text("SELECT count(*) FROM clinical.case_notes")).scalar()
            assert count == 0, user

    def test_la_paciente_con_ficha_propia_tampoco_ve_notas_de_su_ficha(self, owner_engine, world):
        # Una nota sobre la ficha de la propia paciente (insertada como dueño)
        patient = world["patient"]
        add_note(owner_engine, world["a"], patient.patient_id, world["doc1"], "sobre ella")
        with tenant_session(patient) as session:
            assert session.execute(text("SELECT count(*) FROM clinical.case_notes")).scalar() == 0

    def test_colega_y_otro_tenant_no_ven_la_nota(self, owner_engine, world, note):
        for user in ("doc2", "doc_b"):
            with tenant_session(world[user]) as session:
                assert (
                    session.execute(text("SELECT count(*) FROM clinical.case_notes")).scalar() == 0
                )

    def test_la_autora_edita_body_y_updated_at(self, owner_engine, world, note):
        _, nid = note
        with tenant_session(world["doc1"]) as session:
            result = session.execute(
                text(
                    "UPDATE clinical.case_notes SET body = 'nuevo', updated_at = now() "
                    "WHERE id = :i"
                ),
                {"i": nid},
            )
            session.commit()
        assert result.rowcount == 1
        with owner_engine.connect() as conn:
            body, updated = conn.execute(
                text("SELECT body, updated_at FROM clinical.case_notes")
            ).one()
        assert body == "nuevo" and updated is not None

    @pytest.mark.parametrize("column", ["author_id", "patient_id", "tenant_id", "created_at"])
    def test_la_autora_no_cambia_otras_columnas(self, owner_engine, world, note, column):
        _, nid = note
        value = {
            "author_id": ":other",
            "patient_id": ":other",
            "tenant_id": ":other",
            "created_at": "now()",
        }[column]
        with tenant_session(world["doc1"]) as session, pytest.raises(DBAPIError):
            session.execute(
                text(f"UPDATE clinical.case_notes SET {column} = {value} WHERE id = :i"),
                {"i": nid, "other": world["doc2"].id},
            )

    @pytest.mark.parametrize("actor", ["doc2", "doc_b", "admin", "patient"])
    def test_ajenas_no_editan_ni_borran_con_sql_directo(self, owner_engine, world, note, actor):
        _, nid = note
        with tenant_session(world[actor]) as session:
            updated = session.execute(
                text("UPDATE clinical.case_notes SET body = 'hack' WHERE id = :i"), {"i": nid}
            ).rowcount
            deleted = session.execute(
                text("DELETE FROM clinical.case_notes WHERE id = :i"), {"i": nid}
            ).rowcount
            session.commit()
        assert updated == 0 and deleted == 0
        with owner_engine.connect() as conn:
            assert conn.execute(text("SELECT body FROM clinical.case_notes")).scalar_one() == (
                "original"
            )

    def test_colega_con_la_ficha_por_traspaso_pendiente_no_toca_la_nota(
        self, client, owner_engine, world, note
    ):
        from tests.api.test_handovers import create

        create(client, world["admin"], world["doc1"], world["doc2"])
        _, nid = note
        with tenant_session(world["doc2"]) as session:
            # Ve la nota (lectura de doctoras), pero no es la autora
            assert session.execute(text("SELECT count(*) FROM clinical.case_notes")).scalar() == 1
            assert (
                session.execute(
                    text("UPDATE clinical.case_notes SET body = 'x' WHERE id = :i"), {"i": nid}
                ).rowcount
                == 0
            )
            assert (
                session.execute(
                    text("DELETE FROM clinical.case_notes WHERE id = :i"), {"i": nid}
                ).rowcount
                == 0
            )
            session.commit()

    def test_la_autora_borra_la_suya(self, owner_engine, world, note):
        _, nid = note
        with tenant_session(world["doc1"]) as session:
            assert (
                session.execute(
                    text("DELETE FROM clinical.case_notes WHERE id = :i"), {"i": nid}
                ).rowcount
                == 1
            )
            session.commit()
        with owner_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM clinical.case_notes")).scalar_one() == 0

    def test_no_se_puede_escribir_una_nota_a_nombre_de_otra(self, owner_engine, world, note):
        pid, _ = note
        with tenant_session(world["doc1"]) as session, pytest.raises(DBAPIError):
            session.execute(
                text(
                    "INSERT INTO clinical.case_notes (id, patient_id, author_id, body) "
                    "VALUES (gen_random_uuid(), :p, :a, 'falsa')"
                ),
                {"p": pid, "a": world["doc2"].id},
            )


class TestCatalogo:
    def test_privilegios_de_app_user_en_case_notes(self, owner_engine):
        assert app_privilege(owner_engine, "case_notes", "UPDATE", "body")
        assert app_privilege(owner_engine, "case_notes", "UPDATE", "updated_at")
        for column in ("id", "tenant_id", "patient_id", "author_id", "created_at"):
            assert not app_privilege(owner_engine, "case_notes", "UPDATE", column), column
        assert app_privilege(owner_engine, "case_notes", "DELETE")
        assert app_privilege(owner_engine, "case_notes", "INSERT")
        assert app_privilege(owner_engine, "case_notes", "SELECT")

    def test_privilegios_de_patients_solo_estado(self, owner_engine):
        assert app_privilege(owner_engine, "patients", "UPDATE", "status")
        for column in ("reviewed_by", "reviewed_at", "origin", "user_id"):
            assert not app_privilege(owner_engine, "patients", "UPDATE", column), column

    @pytest.mark.parametrize(
        ("policy", "command"),
        [
            ("case_notes_doctor_read", "SELECT"),
            ("case_notes_author_update", "UPDATE"),
            ("case_notes_author_delete", "DELETE"),
        ],
    )
    def test_politicas_de_notas(self, owner_engine, policy, command):
        with owner_engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT cmd, permissive, qual, with_check FROM pg_policies "
                    "WHERE schemaname = 'clinical' AND tablename = 'case_notes' "
                    "AND policyname = :p"
                ),
                {"p": policy},
            ).one_or_none()
        assert row is not None, policy
        assert row.cmd == command
        assert "doctor" in row.qual
        if command == "UPDATE":
            assert "author_id" in row.qual and "author_id" in row.with_check

    @pytest.mark.parametrize(
        ("trigger", "table"),
        [
            ("trg_patients_case_status", "patients"),
            ("trg_patients_case_review", "patients"),
            ("trg_analyses_reopen_case", "analyses"),
        ],
    )
    def test_triggers_existen_y_estan_habilitados(self, owner_engine, trigger, table):
        with owner_engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT t.tgenabled, c.relname FROM pg_trigger t "
                    "JOIN pg_class c ON c.oid = t.tgrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'clinical' AND t.tgname = :t AND NOT t.tgisinternal"
                ),
                {"t": trigger},
            ).one_or_none()
        assert row is not None, trigger
        assert row.relname == table and row.tgenabled == "O"

    def test_las_funciones_de_los_triggers_no_son_security_definer(self, owner_engine):
        with owner_engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT p.proname, p.prosecdef FROM pg_proc p "
                    "JOIN pg_namespace n ON n.oid = p.pronamespace "
                    "WHERE n.nspname = 'clinical' AND p.proname IN "
                    "('enforce_case_status', 'protect_case_review', 'reopen_case_on_analysis')"
                )
            ).all()
        assert {r.proname for r in rows} == {
            "enforce_case_status",
            "protect_case_review",
            "reopen_case_on_analysis",
        }
        assert not any(r.prosecdef for r in rows)
