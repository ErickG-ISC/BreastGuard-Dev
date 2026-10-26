"""seed_demo.py: crea un tenant de demostración sintético y lo limpia sin tocar a nadie más."""

import pytest
from sqlalchemy import text

from backend.scripts.seed_demo import DemoError, clean_demo, create_demo
from tests.helpers import auth_headers

pytestmark = pytest.mark.usefixtures("database")


def counts(owner_engine, tenant_id) -> dict[str, int]:
    tables = [
        "clinical.patients",
        "clinical.questionnaires",
        "clinical.self_exams",
        "clinical.symptom_entries",
        "clinical.audit_log",
        "control.users",
        "control.invitations",
    ]
    with owner_engine.connect() as conn:
        return {
            t: conn.execute(
                text(f"SELECT count(*) FROM {t} WHERE tenant_id = :t"), {"t": tenant_id}
            ).scalar_one()
            for t in tables
        }


def test_crea_y_limpia_sin_afectar_otros_tenants(
    owner_engine, tenant_factory, user_factory, client
):
    other = tenant_factory("clinica-real")
    doctor = user_factory(other, role="doctor")
    other_before = counts(owner_engine, other.id)

    result = create_demo("demo-clinica", admin_email="yo@example.com")
    created = counts(owner_engine, result.tenant_id)
    assert created["control.users"] == 3 + 5
    assert created["control.invitations"] == 3
    assert created["clinical.patients"] == 5
    assert created["clinical.questionnaires"] == 5
    assert created["clinical.self_exams"] == 5
    assert created["clinical.symptom_entries"] == 5
    assert created["clinical.audit_log"] == 1  # fila testigo del chequeo de aislamiento
    assert any("yo@example.com" in who for who in result.links)
    assert all("#token=" in url for url in result.links.values())
    # El personal queda invitado: nadie tiene contraseña todavía
    with owner_engine.connect() as conn:
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM control.users "
                    "WHERE tenant_id = :t AND hashed_password IS NOT NULL"
                ),
                {"t": result.tenant_id},
            ).scalar_one()
            == 0
        )

    assert counts(owner_engine, other.id) == other_before
    with pytest.raises(DemoError, match="ya existe"):
        create_demo("demo-clinica")

    clean_demo(owner_engine, "demo-clinica")
    assert all(v == 0 for v in counts(owner_engine, result.tenant_id).values())
    assert counts(owner_engine, other.id) == other_before
    assert client.get("/api/v1/auth/me", headers=auth_headers(doctor)).status_code == 200


@pytest.mark.parametrize("slug", ["clinica-real", "b2c", "demo"])
def test_solo_slugs_de_demostracion(owner_engine, slug):
    with pytest.raises(DemoError):
        create_demo(slug)
    with pytest.raises(DemoError):
        clean_demo(owner_engine, slug)
