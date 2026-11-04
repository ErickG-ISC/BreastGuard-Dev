"""Purga de un tenant (script de mantenimiento con el rol dueño)."""

import pytest
from sqlalchemy import text

from backend.app.db import get_engine
from backend.app.services import storage as storage_module
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


def test_purga_borra_imagenes_y_conserva_platform_admins(populated, owner_engine, user_factory):
    a = populated["clinica-a"]
    root = user_factory(role="platform_admin")
    with owner_engine.begin() as conn:
        patient_id = conn.execute(
            text("SELECT id FROM clinical.patients WHERE tenant_id = :t"), {"t": a.id}
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO clinical.medical_images (tenant_id, patient_id, uploaded_by, "
                "object_path, image_type) VALUES (:t, :p, :u, 'clinica-a/images/x.png', 'BUSI')"
            ),
            {"t": a.id, "p": patient_id, "u": root.id},
        )

    summary = purge_tenant(owner_engine, "clinica-a")

    assert summary.deleted["clinical.medical_images"] == 1
    with owner_engine.connect() as conn:
        kept = conn.execute(
            text("SELECT count(*) FROM control.users WHERE id = :id"), {"id": root.id}
        ).scalar_one()
    assert kept == 1


def test_purga_exige_bypassrls(populated):
    with pytest.raises(PurgeError, match="BYPASSRLS"):
        purge_tenant(get_engine(), "clinica-a")


class FakeBucket:
    def __init__(self, folders: dict[str, list[str]], files: dict[str, list[str]]) -> None:
        self.folders = folders
        self.files = files
        self.removed: list[str] = []

    def list(self, folder, options):
        entries = [{"name": n, "id": None} for n in self.folders.get(folder, [])]
        entries += [{"name": n, "id": "x"} for n in self.files.get(folder, [])]
        start = options["offset"]
        return entries[start : start + options["limit"]]

    def remove(self, paths):
        self.removed.extend(paths)


class FakeClient:
    def __init__(self, bucket) -> None:
        self.storage = self
        self._bucket = bucket

    def from_(self, name):
        return self._bucket


def test_remove_prefix_pagina_y_recorre_subcarpetas(monkeypatch):
    names = [f"img{i}.png" for i in range(250)]
    bucket = FakeBucket({"clinica-a": ["images"]}, {"clinica-a/images": names})
    monkeypatch.setattr(storage_module, "_get_client", lambda: FakeClient(bucket))

    removed = storage_module.SupabaseStorage(bucket="b").remove_prefix("clinica-a/")

    assert removed == 250
    assert len(set(bucket.removed)) == 250
    assert all(p.startswith("clinica-a/images/") for p in bucket.removed)


@pytest.mark.parametrize(
    "prefix",
    [
        "",
        "/",
        "a/b/",
        "clinica-a",
        "../x/",
        "Mayus/",
        # transfer/ solo con el uuid de UN paquete, nunca entero ni con subcarpetas
        "transfer/",
        "transfer/../x/",
        "transfer/" + "a" * 32 + "/x/",
        "transfer/" + "A" * 32 + "/",
    ],
)
def test_remove_prefix_rechaza_prefijos_peligrosos(prefix):
    with pytest.raises(ValueError):
        storage_module.SupabaseStorage(bucket="b").remove_prefix(prefix)


def _package(conn, source, recipient_id=None) -> str:
    """Paquete mínimo como dueño (preparación de datos); devuelve su prefijo."""
    package_id = conn.execute(text("SELECT gen_random_uuid()")).scalar_one()
    prefix = f"transfer/{package_id.hex}/"
    conn.execute(
        text(
            "INSERT INTO control.share_packages (id, source_tenant_id, source_user_id, "
            "key_hash, expires_at, recipient_user_id, sections, analyses_count, size_bytes, "
            "consent_version, consent_sha256, consented_at, object_prefix) VALUES (:id, :t, :u, "
            ":h, now() + interval '1 day', :r, '{}'::jsonb, 0, 0, 'v', 'x', now(), :p)"
        ),
        {
            "id": package_id,
            "t": source.tenant_id,
            "u": source.id,
            "h": package_id.hex * 2,
            "r": recipient_id,
            "p": prefix,
        },
    )
    return prefix


def test_purga_con_paquetes_hacia_sus_medicas_y_de_sus_pacientes(
    populated, owner_engine, user_factory, b2c_tenant
):
    """Un paquete dirigido a una médica de la institución no bloquea la purga (ON DELETE SET
    NULL); los paquetes de sus pacientes se borran y se devuelven sus prefijos de transfer/."""
    a = populated["clinica-a"]
    doctor = user_factory(a, role="doctor")
    outsider = user_factory(b2c_tenant, role="patient")
    own_patient = user_factory(a, role="patient")
    with owner_engine.begin() as conn:
        _package(conn, outsider, recipient_id=doctor.id)
        own_prefix = _package(conn, own_patient)

    summary = purge_tenant(owner_engine, "clinica-a")

    assert summary.deleted["control.share_packages"] == 1
    assert summary.transfer_prefixes == [own_prefix]
    with owner_engine.connect() as conn:
        survivor = conn.execute(text("SELECT recipient_user_id FROM control.share_packages")).one()
    assert survivor.recipient_user_id is None
