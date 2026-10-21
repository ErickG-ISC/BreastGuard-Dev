from sqlalchemy.exc import OperationalError

from backend.app.api.deps import get_control_db
from backend.app.main import app


def test_health_ok(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected", "model": "loaded"}


def test_health_sin_base_503_sin_detalles(client):
    class BrokenSession:
        def execute(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("host secreto:5432"))

    app.dependency_overrides[get_control_db] = lambda: BrokenSession()

    response = client.get("/api/v1/health")

    assert response.status_code == 503
    assert "secreto" not in response.text


def test_la_api_no_permite_cache_http(client):
    response = client.get("/api/v1/health")
    assert response.headers["cache-control"] == "no-store"


def test_frontend_origin_tolera_espacios_y_barra_final(monkeypatch):
    import importlib

    import backend.app.main as main

    monkeypatch.setenv("FRONTEND_ORIGIN", " https://app.vercel.app/ , http://localhost:5173")
    reloaded = importlib.reload(main)
    try:
        assert reloaded.frontend_origins == ["https://app.vercel.app", "http://localhost:5173"]
    finally:
        monkeypatch.undo()
        importlib.reload(main)
