"""Migraciones en Postgres real: cada prueba usa una base nueva y la borra al terminar."""

import uuid

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from backend.app.models import clinical, control  # noqa: F401  (registra las tablas)
from backend.app.models.base import Base
from tests.helpers import default_password_hash
from tests.pgtest import (
    OWNER_URL,
    alembic_config,
    create_database,
    drop_database,
    ensure_supabase_api_roles,
)

APP_SCHEMAS = {"control", "clinical"}
CONTROL_TABLES = {"tenants", "users", "consents", "plans", "subscriptions"}
CLINICAL_TABLES = {
    "patients",
    "medical_images",
    "audit_log",
    "questionnaires",
    "analyses",
    "self_exams",
}


@pytest.fixture
def fresh_db(postgres_available):
    name = f"bg_mig_{uuid.uuid4().hex[:10]}"
    ensure_supabase_api_roles()
    create_database(name)
    url = OWNER_URL.set(database=name).render_as_string(hide_password=False)
    engine = create_engine(url)
    try:
        yield url, engine
    finally:
        engine.dispose()
        drop_database(name)


def tables(engine, schema: str) -> set[str]:
    return set(inspect(engine).get_table_names(schema=schema)) - {"alembic_version"}


def test_upgrade_downgrade_upgrade(fresh_db):
    url, engine = fresh_db
    config = alembic_config(url)

    command.upgrade(config, "head")
    assert tables(engine, "control") == CONTROL_TABLES
    assert tables(engine, "clinical") == CLINICAL_TABLES

    command.downgrade(config, "base")
    assert not inspect(engine).has_schema("clinical")
    assert tables(engine, "public") == set()

    command.upgrade(config, "head")
    assert tables(engine, "clinical") == CLINICAL_TABLES


def test_upgrade_head_dos_veces_es_idempotente(fresh_db):
    url, engine = fresh_db
    command.upgrade(alembic_config(url), "head")
    command.upgrade(alembic_config(url), "head")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM control.tenants")).scalar_one() == 1


def test_migracion_coincide_con_los_modelos(fresh_db):
    url, engine = fresh_db
    command.upgrade(alembic_config(url), "head")

    def include_name(name, type_, parent_names):
        return name in APP_SCHEMAS if type_ == "schema" else True

    with engine.connect() as conn:
        context = MigrationContext.configure(
            conn, opts={"include_schemas": True, "include_name": include_name}
        )
        assert compare_metadata(context, Base.metadata) == []


def test_migra_usuarios_del_prototipo_como_pacientes_b2c(fresh_db):
    url, engine = fresh_db
    config = alembic_config(url)
    command.upgrade(config, "0001")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (email, hashed_password, full_name, is_medical) VALUES "
                "('ana@example.com', :pw, 'Ana', false), "
                "('doc@example.com', :pw, 'Doc', true), "
                "('rota@example.com', NULL, 'Sin password', false)"
            ),
            {"pw": default_password_hash()},
        )
        conn.execute(
            text("INSERT INTO medical_images (user_id, image_path) VALUES (1, 'http://x/y.png')")
        )

    command.upgrade(config, "head")

    with engine.connect() as conn:
        users = conn.execute(
            text(
                "SELECT u.email, u.role, u.hashed_password, t.slug FROM control.users u "
                "JOIN control.tenants t ON t.id = u.tenant_id ORDER BY u.email"
            )
        ).all()
        assert [(u.email, u.role, u.slug) for u in users] == [
            ("ana@example.com", "patient", "b2c"),
            ("doc@example.com", "patient", "b2c"),  # is_medical era autodeclarado
        ]
        assert all(u.hashed_password == default_password_hash() for u in users)
        assert conn.execute(text("SELECT count(*) FROM clinical.patients")).scalar_one() == 2
        assert conn.execute(text("SELECT count(*) FROM legacy.users")).scalar_one() == 3
        assert conn.execute(text("SELECT count(*) FROM legacy.medical_images")).scalar_one() == 1
    assert tables(engine, "public") == set()

    # Sin datos nuevos, el downgrade devuelve las tablas a public
    command.downgrade(config, "0004")
    assert tables(engine, "public") == {"users", "medical_images"}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM control.users")).scalar_one() == 0


def test_downgrade_no_borra_datos_nuevos(fresh_db):
    url, engine = fresh_db
    config = alembic_config(url)
    command.upgrade(config, "head")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO control.users (email, hashed_password, full_name, role) "
                "VALUES ('admin@example.com', 'x', 'Admin', 'platform_admin')"
            )
        )

    with pytest.raises(RuntimeError, match="creados después de migrar"):
        command.downgrade(config, "base")
    assert tables(engine, "control") == CONTROL_TABLES


def test_env_no_requiere_database_url_si_recibe_dburl(fresh_db, monkeypatch):
    url, engine = fresh_db
    monkeypatch.delenv("DATABASE_URL")
    command.upgrade(alembic_config(url), "head")
    assert tables(engine, "control") == CONTROL_TABLES


def test_downgrade_no_borra_datos_clinicos(fresh_db):
    url, engine = fresh_db
    config = alembic_config(url)
    command.upgrade(config, "head")
    with engine.begin() as conn:
        b2c = conn.execute(text("SELECT id FROM control.tenants WHERE slug = 'b2c'")).scalar_one()
        conn.execute(
            text(
                "INSERT INTO clinical.audit_log (tenant_id, actor_id, actor_role, action) "
                "VALUES (:t, gen_random_uuid(), 'tenant_admin', 'prueba')"
            ),
            {"t": b2c},
        )

    with pytest.raises(RuntimeError, match="tiene datos"):
        command.downgrade(config, "0003")
    assert tables(engine, "clinical") == CLINICAL_TABLES
