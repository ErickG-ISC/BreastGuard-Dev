"""El smoke test de despliegue, ejecutado contra la app local (TestClient), sin red."""

import pytest

from backend.scripts import smoke_deployed
from backend.scripts.smoke_deployed import Result

pytestmark = pytest.mark.usefixtures("database")


def via(client):
    def fetch(method, url, headers):
        path = url.removeprefix("http://api.test")
        response = client.request(method, path, headers=headers)
        return Result(response.status_code, dict(response.headers), response.content)

    return fetch


def test_la_api_local_pasa_el_smoke_test(client):
    checks = smoke_deployed.run("http://api.test", None, fetch=via(client))
    failed = [text for ok, text in checks if not ok]
    assert failed == []
    assert len(checks) > 15


def test_detecta_una_ruta_protegida_abierta(client, monkeypatch):
    monkeypatch.setattr(smoke_deployed, "PROTECTED", ["/plans"])  # pública: debe fallar
    checks = smoke_deployed.run("http://api.test", None, fetch=via(client))
    assert any(not ok and "/plans" in text for ok, text in checks)


def test_solo_hace_lecturas(client):
    methods = []
    inner = via(client)

    def spy(method, url, headers):
        methods.append(method)
        return inner(method, url, headers)

    smoke_deployed.run("http://api.test", None, fetch=spy)
    assert set(methods) <= {"GET", "OPTIONS"}
