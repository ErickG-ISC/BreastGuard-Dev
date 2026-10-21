"""Purga de un tenant (script de mantenimiento con el rol dueño)."""

import pytest
from sqlalchemy import text

from backend.scripts.purge_tenant import PurgeError, purge_tenant


def counts(owner_engine, tenant_id) -> dict[str, int]:
    tables = {
        "patients": "clinical.patients",
        "audit": "clinical.audit_log",
        "users": "control.users",
        "tenants": "control.tenants",
    }
    with owner_engine.connect() as conn:
        result = {}
        for key, table in tables.items():
            column = "id" if key == "tenants" else "tenant_id"
            result[key] = conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE {column} = :t"), {"t": tenant_id}
            ).scalar_one()
        return result


@pytest.fixture
def populated(tenant_factory, user_factory, owner_engine):
    tenants = {}
    for slug in ("clinica-a", "clinica-b"):
        tenant = tenant_factory(slug)
        user_factory(tenant, role="patient")
        admin = user_factory(tenant, role="tenant_admin")
        with owner_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO clinical.audit_log (tenant_id, actor_id, actor_role, action) "
                    "VALUES (:t, :a, 'tenant_admin', 'prueba')"
                ),
                {"t": tenant.id, "a": admin.id},
            )
        tenants[slug] = tenant
    return tenants


def test_purga_solo_el_tenant_indicado(populated, owner_engine):
    a, b = populated["clinica-a"], populated["clinica-b"]
    before_b = counts(owner_engine, b.id)

    summary = purge_tenant(owner_engine, "clinica-a")

    assert counts(owner_engine, a.id) == {"patients": 0, "audit": 0, "users": 0, "tenants": 0}
    assert counts(owner_engine, b.id) == before_b
    assert summary.deleted["clinical.patients"] == 1


def test_dry_run_no_borra(populated, owner_engine):
    a = populated["clinica-a"]
    before = counts(owner_engine, a.id)
    summary = purge_tenant(owner_engine, "clinica-a", dry_run=True)
    assert counts(owner_engine, a.id) == before
    assert summary.deleted["control.users"] == 2


def test_b2c_requiere_confirmacion_extra(owner_engine):
    with pytest.raises(PurgeError, match="allow-b2c"):
        purge_tenant(owner_engine, "b2c")


def test_tenant_inexistente(owner_engine):
    with pytest.raises(PurgeError, match="No existe"):
        purge_tenant(owner_engine, "no-existe")
