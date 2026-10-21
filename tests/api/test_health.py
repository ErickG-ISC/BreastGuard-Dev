from sqlalchemy.exc import OperationalError

from backend.app.api.deps import get_db
from backend.app.main import app


def test_health_ok(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}


def test_health_sin_base_503_sin_detalles(client):
    class BrokenSession:
        def execute(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("host secreto:5432"))

    app.dependency_overrides[get_db] = lambda: BrokenSession()

    response = client.get("/api/v1/health")

    assert response.status_code == 503
    assert "secreto" not in response.text
