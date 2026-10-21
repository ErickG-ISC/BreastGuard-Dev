from tests.helpers import DEFAULT_PASSWORD, registration


def test_login_limitado_a_10_por_minuto(client):
    form = {"username": "nadie@example.com", "password": DEFAULT_PASSWORD}
    codes = [client.post("/api/v1/auth/token", data=form).status_code for _ in range(11)]
    assert codes[:10] == [401] * 10
    assert codes[10] == 429


def test_registro_limitado_con_retry_after(client):
    for i in range(5):
        client.post(
            "/api/v1/auth/register",
            json=registration(f"p{i}@example.com"),
        )
    response = client.post(
        "/api/v1/auth/register",
        json=registration("p9@example.com"),
    )
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) >= 1


def test_los_limites_son_por_ruta(client):
    form = {"username": "nadie@example.com", "password": DEFAULT_PASSWORD}
    for _ in range(10):
        client.post("/api/v1/auth/token", data=form)
    response = client.post(
        "/api/v1/auth/register",
        json=registration("nueva@example.com"),
    )
    assert response.status_code == 201
