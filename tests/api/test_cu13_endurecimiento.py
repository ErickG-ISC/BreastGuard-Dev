"""CU-13 tras la revisión: IP confiable, accesos denegados, atomicidad y cruces con datos."""

import uuid

import pytest
from sqlalchemy import text

from backend.app.services import audit
from tests.helpers import DEFAULT_PASSWORD, auth_headers, make_image_bytes


def upload(client, user, headers=None):
    return client.post(
        "/api/v1/images/upload",
        files={"file": ("eco.png", make_image_bytes("PNG"), "image/png")},
        headers={**auth_headers(user), **(headers or {})},
    )


def audit_rows(owner_engine, tenant_id):
    with owner_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT action, resource_id, host(ip) AS ip FROM clinical.audit_log "
                "WHERE tenant_id = :t ORDER BY occurred_at"
            ),
            {"t": tenant_id},
        ).all()


@pytest.fixture
def two_clinics(tenant_factory, user_factory):
    data = {}
    for slug in ("clinica-a", "clinica-b"):
        tenant = tenant_factory(slug)
        data[slug] = {
            "tenant": tenant,
            "admin": user_factory(tenant, role="tenant_admin"),
            "doctor": user_factory(tenant, role="doctor"),
            "patient": user_factory(tenant, role="patient"),
        }
    return data["clinica-a"], data["clinica-b"]


class TestIpDelCliente:
    def test_x_forwarded_for_falso_no_evade_el_limite(self, client):
        form = {"username": "nadie@example.com", "password": DEFAULT_PASSWORD}
        codes = [
            client.post(
                "/api/v1/auth/token", data=form, headers={"X-Forwarded-For": f"10.0.0.{i}"}
            ).status_code
            for i in range(11)
        ]
        assert codes[-1] == 429

    def test_x_forwarded_for_falso_no_llega_a_la_auditoria(self, client, two_clinics, owner_engine):
        a, _ = two_clinics
        upload(client, a["patient"], {"X-Forwarded-For": "203.0.113.66"})
        [row] = audit_rows(owner_engine, a["tenant"].id)
        assert row.ip == "198.51.100.7"  # la IP de la conexión, no la del header

    def test_detras_de_proxy_usa_la_entrada_del_proxy(
        self, client, two_clinics, owner_engine, monkeypatch
    ):
        monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
        a, _ = two_clinics
        # El cliente intenta colar 203.0.113.66; el proxy agrega la real al final
        upload(client, a["patient"], {"X-Forwarded-For": "203.0.113.66, 192.0.2.10"})
        [row] = audit_rows(owner_engine, a["tenant"].id)
        assert row.ip == "192.0.2.10"

    def test_limites_independientes_por_ip(self, client, monkeypatch):
        monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
        form = {"username": "nadie@example.com", "password": DEFAULT_PASSWORD}
        for _ in range(10):
            client.post("/api/v1/auth/token", data=form, headers={"X-Forwarded-For": "192.0.2.1"})
        blocked = client.post(
            "/api/v1/auth/token", data=form, headers={"X-Forwarded-For": "192.0.2.1"}
        )
        other = client.post(
            "/api/v1/auth/token", data=form, headers={"X-Forwarded-For": "192.0.2.2"}
        )
        assert blocked.status_code == 429
        assert other.status_code == 401

    def test_limite_de_subidas(self, client, two_clinics):
        a, _ = two_clinics
        codes = [upload(client, a["patient"]).status_code for _ in range(21)]
        assert codes[:20] == [201] * 20
        assert codes[20] == 429


class TestAccesosDenegados:
    def test_imagen_ajena_queda_auditada_como_denegada_en_el_tenant_de_quien_pregunta(
        self, client, two_clinics, owner_engine
    ):
        a, b = two_clinics
        b_image = upload(client, b["patient"]).json()["image_id"]

        response = client.get(f"/api/v1/images/{b_image}", headers=auth_headers(a["doctor"]))

        assert response.status_code == 404
        actions = [(r.action, str(r.resource_id)) for r in audit_rows(owner_engine, a["tenant"].id)]
        assert ("image.denied", b_image) in actions
        # En B no queda rastro del intento de A
        assert all(r.action != "image.denied" for r in audit_rows(owner_engine, b["tenant"].id))

    def test_404_por_prefijo_es_identico_al_de_inexistente(self, client, two_clinics, owner_engine):
        a, _ = two_clinics
        image_id = upload(client, a["patient"]).json()["image_id"]
        with owner_engine.begin() as conn:
            conn.execute(
                text("UPDATE clinical.medical_images SET object_path = 'otro/x.png' WHERE id = :i"),
                {"i": image_id},
            )
        bad_prefix = client.get(f"/api/v1/images/{image_id}", headers=auth_headers(a["doctor"]))
        missing = client.get(f"/api/v1/images/{uuid.uuid4()}", headers=auth_headers(a["doctor"]))
        assert bad_prefix.status_code == missing.status_code == 404
        assert bad_prefix.json() == missing.json()


class TestAtomicidad:
    def test_si_falla_la_auditoria_no_queda_la_imagen(
        self, client, two_clinics, owner_engine, monkeypatch
    ):
        a, _ = two_clinics

        def boom(*args, **kwargs):
            raise RuntimeError("fallo de auditoría")

        monkeypatch.setattr(audit, "record", boom)
        with pytest.raises(RuntimeError):
            upload(client, a["patient"])
        with owner_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM clinical.medical_images")).scalar() == 0

    def test_si_falla_la_auditoria_no_se_entrega_la_lectura(
        self, client, two_clinics, monkeypatch, storage
    ):
        a, _ = two_clinics
        image_id = upload(client, a["patient"]).json()["image_id"]

        def boom(*args, **kwargs):
            raise RuntimeError("fallo de auditoría")

        monkeypatch.setattr(audit, "record", boom)
        with pytest.raises(RuntimeError):
            client.get(f"/api/v1/images/{image_id}", headers=auth_headers(a["doctor"]))


class TestCrucesConDatosEnAmbosTenants:
    def test_listado_de_tenant_admin_solo_trae_su_tenant(self, client, two_clinics):
        a, b = two_clinics
        a_image = upload(client, a["patient"]).json()["image_id"]
        upload(client, b["patient"])

        response = client.get(
            "/api/v1/images",
            params={"tenant_id": str(b["tenant"].id)},
            headers={**auth_headers(a["admin"]), "X-Tenant-Id": str(b["tenant"].id)},
        )

        assert [img["id"] for img in response.json()] == [a_image]

    def test_log_filtrado_por_actor_de_otro_tenant_devuelve_vacio(self, client, two_clinics):
        a, b = two_clinics
        upload(client, b["patient"])
        response = client.get(
            "/api/v1/audit",
            params={"actor_id": str(b["patient"].id)},
            headers=auth_headers(a["admin"]),
        )
        assert response.status_code == 200
        assert response.json() == []

    def test_la_auditoria_no_guarda_rutas_ni_tokens(self, client, two_clinics, owner_engine):
        a, _ = two_clinics
        image_id = upload(client, a["patient"]).json()["image_id"]
        client.get(f"/api/v1/images/{image_id}", headers=auth_headers(a["doctor"]))
        with owner_engine.connect() as conn:
            dump = " ".join(
                str(v)
                for row in conn.execute(text("SELECT * FROM clinical.audit_log")).all()
                for v in row
            )
        assert "clinica-a/" not in dump
        assert "eyJ" not in dump  # prefijo de un JWT
