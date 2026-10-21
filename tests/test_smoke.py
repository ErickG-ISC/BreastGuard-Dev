from fastapi.testclient import TestClient

from backend.app.main import app


def test_raiz_responde():
    response = TestClient(app).get("/")
    assert response.status_code == 200
