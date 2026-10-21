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


def test_frontend_origin_tolera_errores_de_captura():
    from backend.app.cors import parse_origins

    raw = ' https://app.vercel.app/ , "breastguardfrontend.vercel.app", localhost:5173,, '
    assert parse_origins(raw) == [
        "https://app.vercel.app",
        "https://breastguardfrontend.vercel.app",
        "http://localhost:5173",
    ]
    assert parse_origins(None) == ["http://localhost:5173"]
    assert parse_origins("  ") == ["http://localhost:5173"]


def test_frontend_origin_un_origen_por_linea():
    """Caso real de Render: los orígenes quedaron separados por un salto de línea."""
    from backend.app.cors import parse_origins

    assert parse_origins("https://breastguardfrontend.vercel.app\nhttp://localhost:5173") == [
        "https://breastguardfrontend.vercel.app",
        "http://localhost:5173",
    ]
    assert parse_origins("https://a.vercel.app https://b.vercel.app\r\n") == [
        "https://a.vercel.app",
        "https://b.vercel.app",
    ]


def test_cors_permite_el_origen_configurado(client):
    from backend.app.main import frontend_origins

    origin = frontend_origins[0]
    response = client.get("/api/v1/plans", headers={"Origin": origin})
    assert response.headers["access-control-allow-origin"] == origin
    blocked = client.get("/api/v1/plans", headers={"Origin": "https://otro.example"})
    assert "access-control-allow-origin" not in blocked.headers
