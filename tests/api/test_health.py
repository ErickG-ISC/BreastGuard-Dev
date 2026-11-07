from sqlalchemy.exc import OperationalError

from backend.app.api.deps import get_control_db
from backend.app.main import app


def test_health_ok(client, monkeypatch):
    from backend.app.api.v1.health import code_revisions

    monkeypatch.setenv("RENDER_GIT_COMMIT", "0123456789abcdef")
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    head, _ = code_revisions()
    assert head not in response.text  # las revisiones solo van al log
    assert response.json() == {
        "status": "ok",
        "database": "connected",
        "version": "0123456",
        "migration": "ok",
        "model": "loaded",
        "model_version": "fake-3c-1",
    }


def test_estado_de_la_migracion():
    from backend.app.api.v1.health import code_revisions, migration_state

    head, known = code_revisions()
    assert migration_state(head) == "ok"
    older = sorted(known - {head})[0]
    assert migration_state(older) == "behind"
    assert migration_state("9999") == "ahead"  # se migró antes de desplegar: correcto
    assert migration_state(None) == "behind"


def test_base_atrasada_responde_503(client, owner_engine):
    """Render no da por bueno un despliegue cuya base no se migró antes."""
    from sqlalchemy import text

    with owner_engine.begin() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        conn.execute(text("UPDATE alembic_version SET version_num = '0018'"))
    try:
        response = client.get("/api/v1/health")
        assert response.status_code == 503
        body = response.json()
        assert body["migration"] == "behind" and "schema_revision" not in body
        assert "postgres" not in response.text.lower()
    finally:
        with owner_engine.begin() as conn:
            conn.execute(text("UPDATE alembic_version SET version_num = :v"), {"v": current})


def test_sin_permiso_de_lectura_es_atrasada(client, owner_engine):
    from sqlalchemy import text

    from tests.pgtest import TEST_APP_ROLE

    with owner_engine.begin() as conn:
        conn.execute(text(f"REVOKE SELECT ON alembic_version FROM {TEST_APP_ROLE}"))
    try:
        response = client.get("/api/v1/health")
        assert response.status_code == 503
        assert response.json()["migration"] == "behind"
    finally:
        with owner_engine.begin() as conn:
            conn.execute(text(f"GRANT SELECT ON alembic_version TO {TEST_APP_ROLE}"))


def test_health_sin_base_503_sin_detalles(client):
    class BrokenSession:
        def execute(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("host secreto:5432"))

        def rollback(self):
            pass

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


def test_cabeceras_de_seguridad_en_la_api(client):
    response = client.get("/api/v1/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in response.headers["content-security-policy"]


def test_vercel_tiene_csp_y_cabeceras():
    import json
    from pathlib import Path

    config = json.loads((Path(__file__).parents[2] / "frontend" / "vercel.json").read_text())
    headers = {h["key"]: h["value"] for h in config["headers"][0]["headers"]}
    csp = headers["Content-Security-Policy"]
    assert "script-src 'self';" in csp and "'unsafe-eval'" not in csp
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "camera=()" in headers["Permissions-Policy"]
    assert config["rewrites"] == [{"source": "/(.*)", "destination": "/index.html"}]


def test_sin_documentacion_publica_fuera_de_desarrollo(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
