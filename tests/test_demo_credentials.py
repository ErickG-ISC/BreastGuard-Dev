"""Credenciales de demostración: fuertes, solo cuentas sintéticas y solo en desarrollo."""

import pytest
from sqlalchemy import text

from backend.app.services.auth import get_password_hash, verify_password
from backend.scripts import demo_credentials
from backend.scripts.demo_credentials import CredentialError, check, issue, lock
from backend.scripts.demo_env import NotDevelopmentError, database_ref
from backend.scripts.seed_demo import create_demo

pytestmark = pytest.mark.usefixtures("database")


@pytest.fixture
def development(monkeypatch):
    monkeypatch.setenv("BREASTGUARD_ENV", "development")
    monkeypatch.setenv("DEMO_DB_REF", database_ref())


@pytest.fixture
def demo(development, owner_engine, tenant_factory, user_factory, b2c_tenant):
    create_demo("demo-cred")
    data = {
        "real_in_demo": user_factory(
            tenant_factory("demo-otro"), role="doctor", email="persona.real@tec.mx"
        ),
        "real_patient": user_factory(b2c_tenant, role="patient", email="real@example.com"),
        "demo_patient": user_factory(
            b2c_tenant, role="patient", email="demo-paciente-1@demo.invalid"
        ),
    }
    # Las fábricas usan la contraseña de pruebas, que está en la lista débil: aquí, una fuerte
    with owner_engine.begin() as conn:
        conn.execute(
            text("UPDATE control.users SET hashed_password = :h WHERE hashed_password IS NOT NULL"),
            {"h": get_password_hash("Fuerte-y-larga-0b1c2d3e4f")},
        )
    return data


def staff(owner_engine, slug: str) -> list[str]:
    with owner_engine.connect() as conn:
        return list(
            conn.scalars(
                text(
                    "SELECT u.email FROM control.users u JOIN control.tenants t "
                    "ON t.id = u.tenant_id WHERE t.slug = :s AND u.role <> 'patient' "
                    "ORDER BY u.email"
                ),
                {"s": slug},
            )
        )


def hashed(owner_engine, email: str) -> str | None:
    with owner_engine.connect() as conn:
        return conn.scalar(
            text("SELECT hashed_password FROM control.users WHERE email = :e"), {"e": email}
        )


def test_emite_contrasenas_fuertes_y_distintas(owner_engine, demo):
    emails = staff(owner_engine, "demo-cred") + ["demo-paciente-1@demo.invalid"]
    issued = issue(emails)
    passwords = [item.password for item in issued]
    assert len(set(passwords)) == len(passwords)
    assert all(len(p) >= 24 for p in passwords)
    for item in issued:
        assert verify_password(item.password, hashed(owner_engine, item.email))
    # Las invitaciones pendientes quedan anuladas
    with owner_engine.connect() as conn:
        pending = conn.scalar(
            text(
                "SELECT count(*) FROM control.invitations i JOIN control.users u "
                "ON u.id = i.user_id WHERE u.email = ANY(:e) AND i.used_at IS NULL "
                "AND i.revoked_at IS NULL"
            ),
            {"e": emails},
        )
    assert pending == 0
    assert check().weak == []


@pytest.mark.parametrize("who", ["real_in_demo", "real_patient"])
def test_no_toca_cuentas_reales(owner_engine, demo, who):
    before = hashed(owner_engine, demo[who].email)
    with pytest.raises(CredentialError):
        issue([demo[who].email])
    assert hashed(owner_engine, demo[who].email) == before


def test_detecta_contrasenas_debiles_y_bloquea_las_sinteticas(owner_engine, demo):
    (email,) = staff(owner_engine, "demo-cred")[:1]
    with owner_engine.begin() as conn:
        conn.execute(
            text("UPDATE control.users SET hashed_password = :h WHERE email = :e"),
            {"h": get_password_hash("demo1234"), "e": email},
        )
    assert check().weak == [email]

    locked = lock()
    assert locked >= 1
    with owner_engine.connect() as conn:
        active = conn.scalar(
            text("SELECT is_active FROM control.users WHERE email = :e"), {"e": email}
        )
        real = conn.scalar(
            text("SELECT is_active FROM control.users WHERE email = :e"),
            {"e": demo["real_in_demo"].email},
        )
    assert active is False and real is True
    assert check().weak == []  # bloqueada ya no cuenta


def test_solo_en_desarrollo(monkeypatch):
    monkeypatch.delenv("BREASTGUARD_ENV", raising=False)
    for action in (lambda: issue(["x@example.com"]), check, lock):
        with pytest.raises(NotDevelopmentError):
            action()
    monkeypatch.setenv("BREASTGUARD_ENV", "production")
    with pytest.raises(NotDevelopmentError):
        check()


def test_la_lista_debil_incluye_la_contrasena_de_pruebas():
    assert "contrasena-segura" in demo_credentials.WEAK_PASSWORDS


def test_otra_base_se_niega(development, monkeypatch):
    monkeypatch.setenv("DEMO_DB_REF", "otro-proyecto")
    with pytest.raises(NotDevelopmentError, match="DEMO_DB_REF"):
        check()


def test_mayusculas_y_dominios_parecidos(owner_engine, demo, tenant_factory, user_factory):
    tenant = tenant_factory("demo-mayus")
    shouting = user_factory(tenant, role="doctor", email="Doc.Grande@Example.COM")
    lookalike = user_factory(tenant, role="doctor", email="doc@example.com.evil")
    # Mayúsculas: la cuenta sintética sí se emite y se bloquea (como el login, sin distinguir)
    (issued,) = issue(["doc.grande@example.com"])
    assert issued.email == shouting.email
    lock()
    with owner_engine.connect() as conn:
        active = dict(
            conn.execute(
                text("SELECT email, is_active FROM control.users WHERE email = ANY(:e)"),
                {"e": [shouting.email, lookalike.email]},
            ).all()
        )
    assert active[shouting.email] is False
    # Un dominio que solo se parece no es sintético: no se toca
    assert active[lookalike.email] is True
    with pytest.raises(CredentialError):
        issue([lookalike.email])
