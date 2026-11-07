"""Robustez de /health (revisión de la rama semana5-despliegue-docs, ADR 0016)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from backend.app.api.deps import get_control_db
from backend.app.main import app


def test_base_adelantada_responde_200(client, owner_engine):
    with owner_engine.begin() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        conn.execute(text("UPDATE alembic_version SET version_num = '9999'"))
    try:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json()["migration"] == "ahead"
    finally:
        with owner_engine.begin() as conn:
            conn.execute(text("UPDATE alembic_version SET version_num = :v"), {"v": current})


def test_error_transitorio_al_leer_la_revision_no_tumba_el_servicio(client):
    class FlakySession:
        def execute(self, statement, *args, **kwargs):
            if "alembic_version" in str(statement):
                raise RuntimeError("fallo transitorio")
            return None

        def rollback(self):
            pass

    app.dependency_overrides[get_control_db] = lambda: FlakySession()
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["migration"] == "unknown"


def test_app_user_solo_lee_alembic_version(database, owner_engine):
    from backend.app.db import get_engine

    with get_engine().connect() as conn:
        assert conn.execute(text("SELECT version_num FROM public.alembic_version")).scalar()
        with pytest.raises(ProgrammingError):
            conn.execute(text("UPDATE public.alembic_version SET version_num = 'x'"))
    with owner_engine.connect() as conn:
        for role in ("anon", "authenticated"):
            allowed = conn.execute(
                text("SELECT has_table_privilege(:r, 'public.alembic_version', 'SELECT')"),
                {"r": role},
            ).scalar()
            assert allowed is False


def test_cabeceras_tambien_en_errores(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["strict-transport-security"].startswith("max-age=")
