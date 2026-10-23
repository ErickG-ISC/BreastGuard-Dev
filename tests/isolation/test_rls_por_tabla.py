"""(b) y (c) RLS probado tabla por tabla, conectados como el rol de la app.

Las tablas se toman del catálogo de Postgres y de los modelos. Cada tabla necesita una "receta"
(`RECIPES`) que sepa poblarla; si alguien agrega una tabla a `clinical` sin receta, la prueba
`test_toda_tabla_clinica_tiene_receta` falla y obliga a cubrirla en lugar de dejarla sin probar.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from backend.app.db import new_session
from backend.app.models import clinical as _clinical  # noqa: F401  (registra las tablas)
from backend.app.models.base import Base
from tests.helpers import tenant_session
from tests.pgtest import TEST_APP_ROLE

pytestmark = pytest.mark.usefixtures("database")

MODEL_TABLES = sorted(t.name for t in Base.metadata.tables.values() if t.schema == "clinical")
MODEL_FKS = sorted(
    fk.name
    for t in Base.metadata.tables.values()
    if t.schema == "clinical"
    for fk in t.foreign_key_constraints
)


@dataclass
class Seed:
    """Fila sembrada en un tenant, con las filas de apoyo que necesitó."""

    id: uuid.UUID
    parents: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Recipe:
    # parents(conn, tenant_id, actor) -> filas de apoyo que ya existen en ese tenant
    parents: Callable
    # insert(conn, tenant_id | None, actor, parents, overrides) -> id de la fila
    insert: Callable
    update_column: str  # columna sobre la que se intenta UPDATE
    update_value: str  # literal SQL
    # FK compuesta -> (seed de B, mundo) -> columnas que apuntan a una fila de B
    cross_fk: dict[str, Callable] = field(default_factory=dict)


def _insert_patient(conn, tenant_id, actor, parents, overrides):
    values = {"id": uuid.uuid4(), "name": "Ficha de prueba", "user_id": None, **overrides}
    columns, binds = ["id", "display_name", "user_id"], [":id", ":name", ":user_id"]
    if tenant_id is not None:
        columns.append("tenant_id")
        binds.append(":tenant_id")
        values["tenant_id"] = tenant_id
    conn.execute(
        text(f"INSERT INTO clinical.patients ({', '.join(columns)}) VALUES ({', '.join(binds)})"),
        values,
    )
    return values["id"]


def _insert_image(conn, tenant_id, actor, parents, overrides):
    values = {
        "id": uuid.uuid4(),
        "patient_id": parents["patient_id"],
        "uploaded_by": actor.id,
        **overrides,
    }
    columns = ["id", "patient_id", "uploaded_by", "object_path", "image_type"]
    binds = [":id", ":patient_id", ":uploaded_by", "'x/images/y.png'", "'BUSI'"]
    if tenant_id is not None:
        columns.append("tenant_id")
        binds.append(":tenant_id")
        values["tenant_id"] = tenant_id
    conn.execute(
        text(
            f"INSERT INTO clinical.medical_images ({', '.join(columns)}) "
            f"VALUES ({', '.join(binds)})"
        ),
        values,
    )
    return values["id"]


def _insert_audit(conn, tenant_id, actor, parents, overrides):
    values = {"id": uuid.uuid4(), "actor_id": actor.id, **overrides}
    columns = ["id", "actor_id", "actor_role", "action"]
    binds = [":id", ":actor_id", "'tenant_admin'", "'prueba'"]
    if tenant_id is not None:
        columns.append("tenant_id")
        binds.append(":tenant_id")
        values["tenant_id"] = tenant_id
    conn.execute(
        text(f"INSERT INTO clinical.audit_log ({', '.join(columns)}) VALUES ({', '.join(binds)})"),
        values,
    )
    return values["id"]


def _insert_questionnaire(conn, tenant_id, actor, parents, overrides):
    values = {"id": uuid.uuid4(), "patient_id": parents["patient_id"], **overrides}
    columns = ["id", "patient_id", "version", "answers", "risk_factors", "summary_level"]
    binds = [":id", ":patient_id", "'v1'", "'{}'::jsonb", "'[]'::jsonb", "'sin_factores'"]
    if tenant_id is not None:
        columns.append("tenant_id")
        binds.append(":tenant_id")
        values["tenant_id"] = tenant_id
    conn.execute(
        text(
            f"INSERT INTO clinical.questionnaires ({', '.join(columns)}) "
            f"VALUES ({', '.join(binds)})"
        ),
        values,
    )
    return values["id"]


def _insert_analysis(conn, tenant_id, actor, parents, overrides):
    values = {
        "id": uuid.uuid4(),
        "patient_id": parents["patient_id"],
        "image_id": parents["image_id"],
        "created_by": actor.id,
        **overrides,
    }
    columns = [
        "id",
        "patient_id",
        "image_id",
        "created_by",
        "status",
        "predicted_class",
        "probabilities",
        "confidence",
        "model_version",
        "heatmap_path",
        "quality_flags",
        "report",
    ]
    binds = [
        ":id",
        ":patient_id",
        ":image_id",
        ":created_by",
        "'completed'",
        "'normal'",
        "'{}'::jsonb",
        "0.9",
        "'fake'",
        "'x/heatmaps/y.png'",
        "'[]'::jsonb",
        "'{}'::jsonb",
    ]
    if tenant_id is not None:
        columns.append("tenant_id")
        binds.append(":tenant_id")
        values["tenant_id"] = tenant_id
    conn.execute(
        text(f"INSERT INTO clinical.analyses ({', '.join(columns)}) VALUES ({', '.join(binds)})"),
        values,
    )
    return values["id"]


def _insert_self_exam(conn, tenant_id, actor, parents, overrides):
    values = {
        "id": uuid.uuid4(),
        "patient_id": parents["patient_id"],
        "created_by": actor.id,
        **overrides,
    }
    # Terminada, para que el UPDATE de `note` respete el CHECK de la tabla
    columns = ["id", "patient_id", "created_by", "content_version", "finished_at", "noticed_change"]
    binds = [":id", ":patient_id", ":created_by", "'v1'", "now()", "'no'"]
    if tenant_id is not None:
        columns.append("tenant_id")
        binds.append(":tenant_id")
        values["tenant_id"] = tenant_id
    conn.execute(
        text(f"INSERT INTO clinical.self_exams ({', '.join(columns)}) VALUES ({', '.join(binds)})"),
        values,
    )
    return values["id"]


def _image_parent(conn, tenant_id, actor):
    parents = _patient_parent(conn, tenant_id, actor)
    parents["image_id"] = _insert_image(conn, tenant_id, actor, parents, {})
    return parents


def _patient_parent(conn, tenant_id, actor):
    return {"patient_id": _insert_patient(conn, tenant_id, actor, {}, {})}


RECIPES: dict[str, Recipe] = {
    "patients": Recipe(
        parents=lambda conn, tenant_id, actor: {},
        insert=_insert_patient,
        update_column="display_name",
        update_value="'cambiado'",
        cross_fk={"fk_patients_user": lambda seed_b, world: {"user_id": world.doctor_b.id}},
    ),
    "medical_images": Recipe(
        parents=_patient_parent,
        insert=_insert_image,
        update_column="prediction",
        update_value="'cambiado'",
        cross_fk={
            "fk_medical_images_patient": lambda seed_b, world: {
                "patient_id": seed_b.parents["patient_id"]
            }
        },
    ),
    "questionnaires": Recipe(
        parents=_patient_parent,
        insert=_insert_questionnaire,
        update_column="summary_level",
        update_value="'cambiado'",
        cross_fk={
            "fk_questionnaires_patient": lambda seed_b, world: {
                "patient_id": seed_b.parents["patient_id"]
            }
        },
    ),
    "analyses": Recipe(
        parents=_image_parent,
        insert=_insert_analysis,
        update_column="status",
        update_value="'inconclusive'",
        cross_fk={
            "fk_analyses_patient": lambda seed_b, world: {
                "patient_id": seed_b.parents["patient_id"]
            },
            "fk_analyses_image": lambda seed_b, world: {"image_id": seed_b.parents["image_id"]},
        },
    ),
    "self_exams": Recipe(
        parents=_patient_parent,
        insert=_insert_self_exam,
        update_column="note",
        update_value="'cambiado'",
        cross_fk={
            "fk_self_exams_patient": lambda seed_b, world: {
                "patient_id": seed_b.parents["patient_id"]
            }
        },
    ),
    "audit_log": Recipe(
        parents=lambda conn, tenant_id, actor: {},
        insert=_insert_audit,
        update_column="action",
        update_value="'cambiado'",
    ),
}


@dataclass
class World:
    a: object
    b: object
    admin_a: object
    admin_b: object
    doctor_b: object


@pytest.fixture
def world(tenant_factory, user_factory) -> World:
    a, b = tenant_factory("clinica-a"), tenant_factory("clinica-b")
    return World(
        a=a,
        b=b,
        admin_a=user_factory(a, role="tenant_admin"),
        admin_b=user_factory(b, role="tenant_admin"),
        doctor_b=user_factory(b, role="doctor"),
    )


def seed(owner_engine, table: str, tenant, actor) -> Seed:
    """Inserta una fila en `table` para `tenant` como dueño (solo preparación de datos)."""
    recipe = RECIPES[table]
    with owner_engine.begin() as conn:
        parents = recipe.parents(conn, tenant.id, actor)
        row_id = recipe.insert(conn, tenant.id, actor, parents, {})
    return Seed(id=row_id, parents=parents)


def owner_count(owner_engine, table: str, where: str = "true", **params) -> int:
    with owner_engine.connect() as conn:
        return conn.execute(
            text(f"SELECT count(*) FROM clinical.{table} WHERE {where}"), params
        ).scalar_one()


def app_privilege(owner_engine, table: str, privilege: str, column: str | None = None) -> bool:
    with owner_engine.connect() as conn:
        params = {"r": TEST_APP_ROLE, "t": f"clinical.{table}", "p": privilege}
        if column:
            sql = "SELECT has_column_privilege(:r, :t, :c, :p)"
            params["c"] = column
        else:
            sql = "SELECT has_table_privilege(:r, :t, :p)"
        return conn.execute(text(sql), params).scalar_one()


def test_toda_tabla_clinica_tiene_receta(owner_engine):
    """Una tabla nueva en clinical hace fallar esta prueba hasta que se sepa poblar."""
    with owner_engine.connect() as conn:
        catalog = set(
            conn.scalars(
                text(
                    "SELECT c.relname FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'clinical' AND c.relkind IN ('r', 'p')"
                )
            )
        )
        catalog_fks = set(
            conn.scalars(
                text(
                    "SELECT k.conname FROM pg_constraint k JOIN pg_namespace n "
                    "ON n.oid = k.connamespace WHERE n.nspname = 'clinical' AND k.contype = 'f'"
                )
            )
        )
    covered_fks = {name for recipe in RECIPES.values() for name in recipe.cross_fk}
    assert catalog == set(RECIPES), (
        f"Tablas de clinical sin receta en RECIPES (o receta sobrante): {catalog ^ set(RECIPES)}"
    )
    assert set(MODEL_TABLES) == catalog, "Los modelos y la base migrada no coinciden"
    assert catalog_fks == covered_fks == set(MODEL_FKS), (
        f"FKs sin receta de cruce entre tenants: {catalog_fks ^ covered_fks}"
    )


@pytest.mark.parametrize("table", MODEL_TABLES)
class TestSinContextoPorTabla:
    def test_se_ven_cero_filas(self, owner_engine, world, table):
        seed(owner_engine, table, world.a, world.admin_a)
        seed(owner_engine, table, world.b, world.admin_b)
        assert owner_count(owner_engine, table) == 2  # las filas existen: no es un 0 vacuo
        with new_session() as session:
            count = session.execute(text(f"SELECT count(*) FROM clinical.{table}")).scalar_one()
        assert count == 0

    def test_insert_sin_tenant_falla(self, owner_engine, world, table):
        recipe = RECIPES[table]
        with owner_engine.begin() as conn:
            parents = recipe.parents(conn, world.a.id, world.admin_a)
        with new_session() as session, pytest.raises(DBAPIError, match="row-level|null value"):
            recipe.insert(session, None, world.admin_a, parents, {})
        assert owner_count(owner_engine, table) == 0

    def test_insert_con_tenant_explicito_falla_por_politica(self, owner_engine, world, table):
        recipe = RECIPES[table]
        with owner_engine.begin() as conn:
            parents = recipe.parents(conn, world.a.id, world.admin_a)
        with new_session() as session, pytest.raises(DBAPIError, match="row-level"):
            recipe.insert(session, world.a.id, world.admin_a, parents, {})


@pytest.mark.parametrize("table", MODEL_TABLES)
class TestConContextoDeAPorTabla:
    def test_solo_se_ven_filas_de_a(self, owner_engine, world, table):
        mine = seed(owner_engine, table, world.a, world.admin_a)
        theirs = seed(owner_engine, table, world.b, world.admin_b)
        with tenant_session(world.admin_a) as session:
            tenants = set(session.scalars(text(f"SELECT tenant_id FROM clinical.{table}")))
            ids = set(session.scalars(text(f"SELECT id FROM clinical.{table}")))
        assert tenants == {world.a.id}
        assert mine.id in ids and theirs.id not in ids

    def test_update_sobre_filas_de_b_afecta_cero(self, owner_engine, world, table):
        recipe = RECIPES[table]
        theirs = seed(owner_engine, table, world.b, world.admin_b)
        sql = (
            f"UPDATE clinical.{table} SET {recipe.update_column} = {recipe.update_value} "
            "WHERE id = :id"
        )
        privileged = app_privilege(owner_engine, table, "UPDATE", recipe.update_column)
        self._atacar_y_verificar(owner_engine, world, table, theirs, sql, privileged)

    def test_delete_sobre_filas_de_b_afecta_cero(self, owner_engine, world, table):
        theirs = seed(owner_engine, table, world.b, world.admin_b)
        privileged = app_privilege(owner_engine, table, "DELETE")
        sql = f"DELETE FROM clinical.{table} WHERE id = :id"
        self._atacar_y_verificar(owner_engine, world, table, theirs, sql, privileged)

    @staticmethod
    def _atacar_y_verificar(owner_engine, world, table, theirs, sql, privileged):
        with owner_engine.connect() as conn:
            before = conn.execute(
                text(f"SELECT to_jsonb(t) FROM clinical.{table} t WHERE id = :id"),
                {"id": theirs.id},
            ).scalar_one()

        with tenant_session(world.admin_a) as session:
            if privileged:
                assert session.execute(text(sql), {"id": theirs.id}).rowcount == 0
            else:
                # Sin privilegio la base ni siquiera llega a evaluar filas (p. ej. audit_log)
                with pytest.raises(DBAPIError, match="permission denied"):
                    session.execute(text(sql), {"id": theirs.id})
            session.rollback()

        with owner_engine.connect() as conn:
            after = conn.execute(
                text(f"SELECT to_jsonb(t) FROM clinical.{table} t WHERE id = :id"),
                {"id": theirs.id},
            ).scalar_one()
        assert after == before, "la fila de B cambió o desapareció"

        if privileged:
            # Control positivo: el mismo SQL sí afecta 1 fila en el contexto de B (no es vacuo)
            with tenant_session(world.admin_b) as session:
                assert session.execute(text(sql), {"id": theirs.id}).rowcount == 1
                session.rollback()

    def test_insert_con_tenant_id_de_b_falla_por_with_check(self, owner_engine, world, table):
        recipe = RECIPES[table]
        seed_b = seed(owner_engine, table, world.b, world.admin_b)
        with owner_engine.begin() as conn:
            parents_a = recipe.parents(conn, world.a.id, world.admin_a)

        # Control positivo: con el tenant propio el mismo INSERT funciona
        with tenant_session(world.admin_a) as session:
            recipe.insert(session, world.a.id, world.admin_a, parents_a, {})
            session.rollback()

        # Con el tenant de B falla por WITH CHECK, incluso con filas de apoyo reales de B
        with tenant_session(world.admin_a) as session, pytest.raises(DBAPIError, match="row-level"):
            recipe.insert(session, world.b.id, world.admin_a, seed_b.parents, {})
        assert owner_count(owner_engine, table, "tenant_id = :t", t=world.b.id) == 1
        assert owner_count(owner_engine, table, "tenant_id = :t", t=world.a.id) == 0


def _fk_cases():
    for table, recipe in sorted(RECIPES.items()):
        for fk_name in sorted(recipe.cross_fk):
            yield pytest.param(table, fk_name, id=fk_name)


@pytest.mark.parametrize(("table", "fk_name"), list(_fk_cases()))
def test_fk_compuesta_cruzada_falla(owner_engine, world, table, fk_name):
    recipe = RECIPES[table]
    seed_b = seed(owner_engine, table, world.b, world.admin_b)
    cross = recipe.cross_fk[fk_name](seed_b, world)
    with owner_engine.begin() as conn:
        parents_a = recipe.parents(conn, world.a.id, world.admin_a)

    with tenant_session(world.admin_a) as session, pytest.raises(DBAPIError, match="foreign key"):
        recipe.insert(session, None, world.admin_a, parents_a, cross)
        session.flush()
    # Control positivo: sin la referencia cruzada la misma fila sí se inserta
    with tenant_session(world.admin_a) as session:
        recipe.insert(session, None, world.admin_a, parents_a, {})
        session.rollback()
