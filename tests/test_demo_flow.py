"""Escenario de demostración por el flujo real (backend/scripts/demo_flow.py)."""

import pytest
from sqlalchemy import text

from backend.app.db import TenantContext, new_session
from backend.app.schemas.cases import PatientSearch
from backend.app.services import cases
from backend.app.services.auth import AuthContext
from backend.scripts.demo_flow import DemoFlowError, clean_flow, create_flow

pytestmark = pytest.mark.usefixtures("database")


@pytest.fixture
def demo(tenant_factory, user_factory, b2c_tenant):
    tenant = tenant_factory("demo-clinica-norte")
    return {
        "tenant": tenant,
        "doctor": user_factory(tenant, role="doctor"),
        # Datos reales de otras personas que la limpieza nunca debe tocar
        "real_patient": user_factory(b2c_tenant, role="patient"),
        "other_doctor": user_factory(tenant_factory("clinica-real"), role="doctor"),
    }


def count(owner_engine, sql: str, **params) -> int:
    with owner_engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


def test_crea_casos_por_el_flujo_real_y_los_limpia(owner_engine, storage, demo):
    result = create_flow(storage, "demo-clinica-norte")
    assert len(result.imported) == 4 and len(result.suspicious) == 2

    doctor = demo["doctor"]
    auth = AuthContext(doctor.id, demo["tenant"].id, "demo-clinica-norte", "doctor")
    with new_session(TenantContext(demo["tenant"].id, doctor.id, "doctor")) as db:
        summary = cases.summary(db, auth)
        page = cases.search(db, auth, PatientSearch(filter="sospechosos"), None)
    assert summary.active == 4 and summary.suspicious == 2
    assert {row.display_name for row in page.items} == set(result.suspicious)
    assert any(name.startswith("demo-clinica-norte/") for name in storage.objects)

    deleted = clean_flow(owner_engine, storage)
    assert deleted["control.users"] == 4
    assert (
        count(
            owner_engine,
            "SELECT count(*) FROM control.users WHERE email LIKE 'demo-paciente-%@example.com'",
        )
        == 0
    )
    assert (
        count(
            owner_engine,
            "SELECT count(*) FROM clinical.patients WHERE tenant_id = :t",
            t=demo["tenant"].id,
        )
        == 0
    )
    assert count(owner_engine, "SELECT count(*) FROM control.share_packages") == 0
    assert storage.objects == {}
    # La paciente real y el otro tenant siguen intactos
    assert (
        count(
            owner_engine,
            "SELECT count(*) FROM clinical.patients WHERE user_id = :u",
            u=demo["real_patient"].id,
        )
        == 1
    )
    assert (
        count(
            owner_engine,
            "SELECT count(*) FROM control.users WHERE id = :u",
            u=demo["other_doctor"].id,
        )
        == 1
    )


def test_solo_tenants_de_demostracion(storage, demo):
    with pytest.raises(DemoFlowError, match="demostración"):
        create_flow(storage, "clinica-real")


def test_sin_cuentas_demo_no_borra_nada(owner_engine, storage, demo):
    assert clean_flow(owner_engine, storage) == {}
