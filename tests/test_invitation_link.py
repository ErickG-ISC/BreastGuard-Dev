"""invitation_link.py: enlace nuevo solo para personal invitado, con bitácora."""

import pytest
from sqlalchemy import text

from backend.scripts.invitation_link import InvitationLinkError, issue_link
from tests.helpers import DEFAULT_PASSWORD

pytestmark = pytest.mark.usefixtures("database")


def invited(owner_engine, tenant, email, role="doctor"):
    with owner_engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO control.users (tenant_id, email, full_name, role) "
                "VALUES (:t, :e, 'Invitada', :r) RETURNING id"
            ),
            {"t": tenant.id, "e": email, "r": role},
        ).scalar_one()


def test_genera_enlace_que_sirve_y_revoca_el_anterior(client, owner_engine, tenant_factory):
    tenant = tenant_factory("clinica-a")
    invited(owner_engine, tenant, "doc@a.example.com")
    first, purpose = issue_link("DOC@a.example.com")
    second, _ = issue_link("doc@a.example.com")
    assert purpose == "invite"
    old, new = (url.split("#token=")[1] for url in (first, second))

    stale = client.post(
        "/api/v1/auth/invitations/accept", json={"token": old, "password": DEFAULT_PASSWORD}
    )
    fresh = client.post(
        "/api/v1/auth/invitations/accept", json={"token": new, "password": DEFAULT_PASSWORD}
    )
    assert stale.status_code == 400 and fresh.status_code == 204
    with owner_engine.connect() as conn:
        actions = conn.execute(
            text("SELECT action, actor_role FROM control.admin_events ORDER BY occurred_at")
        ).all()
    assert actions == [("user.invite_resend", "system")] * 2 + [("user.invite_accept", "user")]


def test_no_sirve_para_cuentas_activas_pacientes_ni_admins(
    owner_engine, tenant_factory, user_factory, b2c_tenant
):
    tenant = tenant_factory("clinica-a")
    active = user_factory(tenant, role="doctor")
    patient = user_factory(b2c_tenant, role="patient")
    root = user_factory(role="platform_admin")
    for email in (active.email, patient.email, root.email, "nadie@example.com"):
        with pytest.raises(InvitationLinkError):
            issue_link(email)


def test_no_sirve_si_la_institucion_esta_desactivada(owner_engine, tenant_factory):
    tenant = tenant_factory("clinica-a", active=False)
    invited(owner_engine, tenant, "doc@a.example.com")
    with pytest.raises(InvitationLinkError, match="desactivad"):
        issue_link("doc@a.example.com")


def test_cuenta_restablecida_recibe_enlace_de_restablecimiento(owner_engine, tenant_factory):
    tenant = tenant_factory("clinica-a")
    user_id = invited(owner_engine, tenant, "doc@a.example.com")
    with owner_engine.begin() as conn:
        conn.execute(
            text("UPDATE control.users SET last_login_at = now() WHERE id = :u"), {"u": user_id}
        )
    _, purpose = issue_link("doc@a.example.com")
    assert purpose == "reset"
    with owner_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT i.purpose, i.expires_at - i.created_at < interval '3 hours', e.details "
                "FROM control.invitations i, control.admin_events e WHERE i.user_id = :u"
            ),
            {"u": user_id},
        ).one()
    assert row[0] == "reset" and row[1] is True and row[2] == {"purpose": "reset"}


def test_tenant_admin_invitado_si_recibe_enlace(owner_engine, tenant_factory):
    tenant = tenant_factory("clinica-a")
    invited(owner_engine, tenant, "admin@a.example.com", role="tenant_admin")
    url, purpose = issue_link("admin@a.example.com")
    assert "#token=" in url and purpose == "invite"


def test_cuenta_desactivada_no_recibe_enlace(owner_engine, tenant_factory):
    tenant = tenant_factory("clinica-a")
    user_id = invited(owner_engine, tenant, "doc@a.example.com")
    with owner_engine.begin() as conn:
        conn.execute(
            text("UPDATE control.users SET is_active = false WHERE id = :u"), {"u": user_id}
        )
    with pytest.raises(InvitationLinkError, match="desactivad"):
        issue_link("doc@a.example.com")
