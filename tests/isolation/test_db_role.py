"""(a) La app se conecta con un rol sin superusuario ni BYPASSRLS; si no, las demás pruebas
de aislamiento pasarían en falso."""

import pytest
from sqlalchemy import text

from backend.app.db import DatabaseConfigError, assert_safe_db_role, get_engine
from tests.pgtest import TEST_APP_ROLE

pytestmark = pytest.mark.usefixtures("database")


def test_la_app_usa_un_rol_sin_bypass():
    with get_engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT current_user AS name, rolsuper, rolbypassrls FROM pg_roles "
                "WHERE rolname = current_user"
            )
        ).one()
    assert row.name == TEST_APP_ROLE
    assert not row.rolsuper
    assert not row.rolbypassrls
    assert_safe_db_role()


def test_la_app_no_arranca_con_el_rol_dueno(owner_engine):
    with pytest.raises(DatabaseConfigError):
        assert_safe_db_role(owner_engine)


def test_la_app_no_arranca_sin_contrasena_de_app(monkeypatch):
    from backend.app.db import app_database_url

    monkeypatch.delenv("APP_DATABASE_URL")
    monkeypatch.delenv("APP_DB_PASSWORD")
    with pytest.raises(DatabaseConfigError):
        app_database_url()


def test_url_derivada_nunca_usa_la_contrasena_del_dueno(monkeypatch):
    from backend.app.db import app_database_url

    monkeypatch.delenv("APP_DATABASE_URL")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://postgres.abcref:clave-dueno@pooler.example.com:6543/postgres"
    )
    monkeypatch.setenv("APP_DB_PASSWORD", "clave-app")
    monkeypatch.setenv("APP_DB_USER", "app_user")
    url = app_database_url()
    assert url.username == "app_user.abcref"
    assert url.password == "clave-app"
    assert url.host == "pooler.example.com" and url.port == 6543
