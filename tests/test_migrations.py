from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from backend.app.models.base import Base

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "backend" / "alembic.ini"
APP_TABLES = {"users", "medical_images"}


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 'migraciones.db').as_posix()}"


def alembic_config(db_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.attributes["dburl"] = db_url
    return config


def table_names(db_url: str) -> set[str]:
    engine = create_engine(db_url)
    try:
        return set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()


def test_upgrade_downgrade_upgrade(db_url):
    config = alembic_config(db_url)

    command.upgrade(config, "head")
    assert table_names(db_url) == APP_TABLES

    command.downgrade(config, "base")
    assert table_names(db_url) == set()

    command.upgrade(config, "head")
    assert table_names(db_url) == APP_TABLES


def test_migracion_coincide_con_los_modelos(db_url):
    command.upgrade(alembic_config(db_url), "head")

    engine = create_engine(db_url)
    try:
        with engine.connect() as connection:
            diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    finally:
        engine.dispose()
    assert diff == []


def test_idempotente_sobre_base_creada_con_create_all(db_url):
    # Bases existentes (Supabase de desarrollo) se crearon con el antiguo create_all de /health
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    engine.dispose()

    config = alembic_config(db_url)
    command.upgrade(config, "head")
    command.upgrade(config, "head")

    assert table_names(db_url) == APP_TABLES


def test_downgrade_no_borra_tablas_con_datos(db_url):
    config = alembic_config(db_url)
    command.upgrade(config, "head")
    engine = create_engine(db_url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (email) VALUES ('a@example.com')"))
    engine.dispose()

    with pytest.raises(RuntimeError, match="tiene datos"):
        command.downgrade(config, "base")
    assert table_names(db_url) == APP_TABLES


def test_env_no_requiere_database_url_si_recibe_dburl(db_url, monkeypatch):
    monkeypatch.delenv("DATABASE_URL")
    command.upgrade(alembic_config(db_url), "head")
    assert table_names(db_url) == APP_TABLES
