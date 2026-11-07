"""Ningún log lleva datos clínicos, secretos ni tokens (CLAUDE.md, ADR 0016).

Recorre el flujo completo con TODOS los loggers capturados en DEBUG: registro e inicio de sesión,
análisis, autoexploración y diario con notas, compartir, importar, nota y revisión de la médica,
exportación PDF y HL7, y errores (contraseña mala, código de paquete inválido). Después busca en
los registros capturados cada dato sensible usado en el recorrido.
"""

import logging

import pytest

from tests.api.test_share_import import do_import, shared
from tests.api.test_share_import import world as share_world  # noqa: F401  (fixture)
from tests.helpers import DEFAULT_PASSWORD, auth_headers, registration

API = "/api/v1"
NOTE = "nota-sensible-de-la-paciente-7Q"
DOCTOR_NOTE = "nota-sensible-de-la-medica-3Z"
RECOMMENDATION = "recomendacion-sensible-9K"
EMAIL = "registro-logs@example.com"
NAME = "Paciente Logs Sensible"


@pytest.fixture
def world(share_world):  # noqa: F811
    return share_world


def test_ningun_log_lleva_datos_sensibles(client, world, caplog, storage):
    caplog.set_level(logging.DEBUG)
    secrets: list[str] = [NOTE, DOCTOR_NOTE, RECOMMENDATION, EMAIL, NAME, DEFAULT_PASSWORD]

    # Registro e inicio de sesión (y un intento fallido)
    assert client.post(f"{API}/auth/register", json=registration(EMAIL, NAME)).status_code == 201
    token = client.post(
        f"{API}/auth/token", data={"username": EMAIL, "password": DEFAULT_PASSWORD}
    ).json()["access_token"]
    client.post(f"{API}/auth/token", data={"username": EMAIL, "password": "mala-" + NAME})
    secrets.append(token)
    me = {"Authorization": f"Bearer {token}"}
    client.post(
        f"{API}/symptoms",
        json={
            "entry_date": "2026-01-10",
            "side": "izquierdo",
            "zone": "axila",
            "symptoms": ["dolor"],
            "intensity": 3,
            "note": NOTE,
        },
        headers=me,
    )

    # Compartir e importar (el código del paquete es un secreto)
    doctor = world["doctor"]
    # Paquete dirigido: el aviso por correo (backend de consola) registra la dirección ENMASCARADA
    package = shared(client, world, recipient_email=doctor.email)
    secrets += [package["code"], doctor.email]
    secrets.append(auth_headers(doctor)["Authorization"].split()[1])
    assert do_import(client, world["outsider"], "0" * 26).status_code in (404, 429)
    imported = do_import(client, doctor, package["code"])
    assert imported.status_code in (200, 201), imported.text
    pid = imported.json()["patient_id"]

    # La médica anota, revisa y exporta
    case = client.get(f"{API}/doctor/patients/{pid}", headers=auth_headers(doctor)).json()
    client.post(
        f"{API}/doctor/patients/{pid}/notes",
        json={"body": DOCTOR_NOTE},
        headers=auth_headers(doctor),
    )
    aid = case["analyses"][0]["id"]
    client.put(
        f"{API}/doctor/analyses/{aid}/review",
        json={"birads": "3", "recommendation": RECOMMENDATION},
        headers=auth_headers(doctor),
    )
    for fmt in ("pdf", "hl7"):
        assert (
            client.get(
                f"{API}/doctor/analyses/{aid}/report.{fmt}", headers=auth_headers(doctor)
            ).status_code
            == 200
        )
    # Un fallo de Storage también se registra solo por tipo
    storage.objects.clear()
    client.get(f"{API}/doctor/analyses/{aid}/report.pdf", headers=auth_headers(doctor))

    logged = "\n".join(f"{r.name} {r.getMessage()} {r.exc_text or ''}" for r in caplog.records)
    # Guarda contra un falso verde: los logs del backend sí se capturaron
    backend_names = {r.name for r in caplog.records if r.name.startswith("backend.")}
    assert "backend.app.services.email" in backend_names
    leaked = [s for s in secrets if s and s in logged]
    assert leaked == [], f"Datos sensibles en los logs: {[s[:12] + '…' for s in leaked]}"
