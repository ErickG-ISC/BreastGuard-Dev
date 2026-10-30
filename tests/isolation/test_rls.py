"""RLS a nivel de base, conectados como el rol de la app (nunca como dueño)."""

import uuid

import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import DBAPIError

from backend.app.db import TenantContext, get_engine, new_session
from backend.app.models.clinical import AuditLog
from backend.migrations.rls import assert_bypass
from tests.helpers import tenant_session

CLINICAL_TABLES = ("patients", "medical_images", "audit_log")


def insert_image(session, patient_id, uploaded_by):
    image_id = uuid.uuid4()
    session.execute(
        text(
            "INSERT INTO clinical.medical_images (id, patient_id, uploaded_by, object_path, "
            "image_type) VALUES (:id, :p, :u, 'x/images/y.png', 'BUSI')"
        ),
        {"id": image_id, "p": patient_id, "u": uploaded_by},
    )
    return image_id


@pytest.fixture
def two_tenants(tenant_factory, user_factory, owner_engine):
    """Tenant A y B, cada uno con un médico, una paciente y una imagen de esa paciente."""
    data = {}
    for slug in ("clinica-a", "clinica-b"):
        tenant = tenant_factory(slug)
        doctor = user_factory(tenant, role="doctor")
        patient = user_factory(tenant, role="patient")
        with owner_engine.begin() as conn:
            image_id = conn.execute(
                text(
                    "INSERT INTO clinical.medical_images (tenant_id, patient_id, uploaded_by, "
                    "object_path, image_type) VALUES (:t, :p, :u, :path, 'BUSI') RETURNING id"
                ),
                {
                    "t": tenant.id,
                    "p": patient.patient_id,
                    "u": patient.id,
                    "path": f"{slug}/images/x.png",
                },
            ).scalar_one()
        data[slug] = {"tenant": tenant, "doctor": doctor, "patient": patient, "image": image_id}
    return data["clinica-a"], data["clinica-b"]


def count(session, table: str, where: str = "true", **params) -> int:
    return session.execute(
        text(f"SELECT count(*) FROM clinical.{table} WHERE {where}"), params
    ).scalar_one()


class TestSinContexto:
    def test_se_ven_cero_filas(self, two_tenants):
        with new_session() as session:
            for table in CLINICAL_TABLES:
                assert count(session, table) == 0

    def test_insert_falla(self, two_tenants):
        a, _ = two_tenants
        # Sin contexto, tenant_id queda NULL (NOT NULL) o choca con la política: nunca se inserta
        with new_session() as session, pytest.raises(DBAPIError, match="row-level|null value"):
            session.execute(
                text("INSERT INTO clinical.patients (display_name) VALUES ('sin contexto')")
            )


class TestConContextoDeA:
    def test_solo_ve_filas_de_a(self, two_tenants):
        a, b = two_tenants
        # La paciente es quien ve su ficha e imagen (ADR 0009: la doctora solo a sus pacientes)
        with tenant_session(a["patient"]) as session:
            assert count(session, "patients") == 1
            assert count(session, "medical_images") == 1
            assert count(session, "patients", "tenant_id = :b", b=b["tenant"].id) == 0
            assert count(session, "medical_images", "id = :img", img=b["image"]) == 0

    def test_update_y_delete_sobre_b_afectan_cero_filas(self, two_tenants, owner_engine):
        a, b = two_tenants
        with tenant_session(a["doctor"]) as session:
            updated = session.execute(
                text("UPDATE clinical.medical_images SET prediction = 'x' WHERE id = :id"),
                {"id": b["image"]},
            ).rowcount
            deleted = session.execute(
                text("DELETE FROM clinical.medical_images WHERE id = :id"), {"id": b["image"]}
            ).rowcount
            session.commit()
        assert updated == 0 and deleted == 0
        with owner_engine.connect() as conn:
            row = conn.execute(
                text("SELECT prediction FROM clinical.medical_images WHERE id = :id"),
                {"id": b["image"]},
            ).one()
        assert row.prediction is None

    def test_insert_con_tenant_id_de_b_falla_por_with_check(self, two_tenants):
        a, b = two_tenants
        with tenant_session(a["doctor"]) as session, pytest.raises(DBAPIError, match="row-level"):
            session.execute(
                text("INSERT INTO clinical.patients (tenant_id, display_name) VALUES (:t, 'x')"),
                {"t": b["tenant"].id},
            )

    def test_fk_compuesta_hacia_paciente_de_b_falla(self, two_tenants):
        a, b = two_tenants
        # Desde 0013 la política de A ya lo rechaza (la ficha de B no es suya); la FK sola, sin
        # RLS, se prueba en test_rls_por_tabla.test_fk_compuesta_cruzada_falla
        with (
            tenant_session(a["doctor"]) as session,
            pytest.raises(DBAPIError, match="row-level|foreign key"),
        ):
            insert_image(session, b["patient"].patient_id, a["doctor"].id)
            session.flush()

    def test_ficha_no_puede_apuntar_a_usuario_de_otro_tenant(self, two_tenants):
        a, b = two_tenants
        # Contexto forjado: tenant A con el user_id de una paciente de B. La política lo deja
        # pasar (user_id = el del contexto) y la FK compuesta lo detiene.
        forged = TenantContext(a["tenant"].id, b["patient"].id, "patient")
        with new_session(forged) as session, pytest.raises(DBAPIError, match="foreign key"):
            session.execute(
                text(
                    "INSERT INTO clinical.patients (user_id, display_name, origin) "
                    "VALUES (:u, 'x', 'propio')"
                ),
                {"u": b["patient"].id},
            )
            session.flush()


class TestPoliticasPorRol:
    def test_paciente_solo_ve_su_ficha_e_imagenes(self, two_tenants, user_factory, owner_engine):
        a, _ = two_tenants
        other = user_factory(a["tenant"], role="patient")
        with tenant_session(other) as session:
            assert count(session, "patients") == 1
            assert count(session, "medical_images") == 0
            assert count(session, "medical_images", "id = :img", img=a["image"]) == 0

    def test_paciente_no_sube_imagen_a_ficha_ajena(self, two_tenants, user_factory):
        a, _ = two_tenants
        other = user_factory(a["tenant"], role="patient")
        with tenant_session(other) as session, pytest.raises(DBAPIError, match="row-level"):
            insert_image(session, a["patient"].patient_id, other.id)

    def test_contexto_sin_rol_ve_cero_filas(self, two_tenants):
        a, _ = two_tenants
        ctx = TenantContext(a["tenant"].id, a["doctor"].id, "")
        with new_session(ctx) as session:
            assert count(session, "patients") == 0
            assert count(session, "medical_images") == 0


class TestContextoPorTransaccion:
    def test_commit_y_segunda_transaccion_conservan_el_contexto(self, two_tenants):
        a, _ = two_tenants
        with tenant_session(a["patient"]) as session:
            assert count(session, "patients") == 1
            session.commit()
            assert count(session, "patients") == 1  # el listener reaplica el contexto

    def test_conexion_reutilizada_no_arrastra_contexto(self, two_tenants):
        a, b = two_tenants
        # El pool reutiliza conexiones: tras A, una sesión de B y otra sin contexto no ven A
        with tenant_session(a["patient"]) as session:
            assert count(session, "medical_images") == 1
        with tenant_session(b["patient"]) as session:
            assert count(session, "medical_images", "id = :img", img=a["image"]) == 0
        with new_session() as session:
            assert count(session, "medical_images") == 0
            assert session.execute(
                text("SELECT current_setting('app.tenant_id', true)")
            ).scalar() in (
                None,
                "",
            )


class TestAuditoria:
    def test_audit_log_es_de_solo_insercion(self, two_tenants):
        a, _ = two_tenants
        admin_ctx = TenantContext(a["tenant"].id, a["doctor"].id, "tenant_admin")
        with new_session(admin_ctx) as session:
            session.execute(
                text(
                    "INSERT INTO clinical.audit_log (id, actor_id, actor_role, action) "
                    "VALUES (:id, :actor, 'tenant_admin', 'prueba')"
                ),
                {"id": uuid.uuid4(), "actor": a["doctor"].id},
            )
            session.commit()
            for sql in (
                "UPDATE clinical.audit_log SET action = 'x'",
                "DELETE FROM clinical.audit_log",
                "TRUNCATE clinical.audit_log",
            ):
                with pytest.raises(DBAPIError, match="permission denied"):
                    session.execute(text(sql))
                session.rollback()

    def test_no_se_inserta_con_actor_ajeno(self, two_tenants):
        a, _ = two_tenants
        with tenant_session(a["doctor"]) as session, pytest.raises(DBAPIError, match="row-level"):
            session.execute(
                text(
                    "INSERT INTO clinical.audit_log (id, actor_id, actor_role, action) "
                    "VALUES (:id, :actor, 'doctor', 'x')"
                ),
                {"id": uuid.uuid4(), "actor": a["patient"].id},
            )

    def test_solo_tenant_admin_lee_el_log(self, two_tenants):
        a, _ = two_tenants
        admin_ctx = TenantContext(a["tenant"].id, a["doctor"].id, "tenant_admin")
        with new_session(admin_ctx) as session:
            session.execute(
                text(
                    "INSERT INTO clinical.audit_log (id, actor_id, actor_role, action) "
                    "VALUES (:id, :actor, 'tenant_admin', 'prueba')"
                ),
                {"id": uuid.uuid4(), "actor": a["doctor"].id},
            )
            session.commit()
            assert count(session, "audit_log") == 1
        with tenant_session(a["doctor"]) as session:
            assert count(session, "audit_log") == 0


class TestRevisionDeSeguridad:
    def test_contexto_platform_admin_ve_cero_filas(self, two_tenants):
        a, _ = two_tenants
        ctx = TenantContext(a["tenant"].id, a["doctor"].id, "platform_admin")
        with new_session(ctx) as session:
            assert count(session, "patients") == 0
            assert count(session, "medical_images") == 0

    def test_paciente_no_modifica_ni_borra_imagenes_ajenas(self, two_tenants, user_factory):
        a, _ = two_tenants
        other = user_factory(a["tenant"], role="patient")
        with tenant_session(other) as session:
            updated = session.execute(
                text("UPDATE clinical.medical_images SET prediction = 'x' WHERE id = :id"),
                {"id": a["image"]},
            ).rowcount
            deleted = session.execute(
                text("DELETE FROM clinical.medical_images WHERE id = :id"), {"id": a["image"]}
            ).rowcount
        assert updated == 0 and deleted == 0

    @pytest.mark.parametrize(
        "sql",
        [
            "UPDATE clinical.medical_images SET object_path = 'otro/images/x.png'",
            "UPDATE clinical.medical_images SET patient_id = gen_random_uuid()",
            "UPDATE clinical.patients SET user_id = NULL",
            "DELETE FROM clinical.patients",
        ],
    )
    def test_columnas_y_operaciones_no_permitidas(self, two_tenants, sql):
        a, _ = two_tenants
        with tenant_session(a["doctor"]) as session:
            with pytest.raises(DBAPIError, match="permission denied"):
                session.execute(text(sql))

    @pytest.mark.parametrize("role_key", ["doctor", "patient"])
    def test_auditoria_se_inserta_con_core_para_cualquier_rol(self, two_tenants, role_key):
        a, _ = two_tenants
        user = a[role_key]
        with tenant_session(user) as session:
            session.execute(
                insert(AuditLog).values(
                    id=uuid.uuid4(),
                    tenant_id=user.tenant_id,
                    actor_id=user.id,
                    actor_role=user.role,
                    action="prueba",
                )
            )
            session.commit()

    def test_auditoria_con_returning_falla_para_no_admin(self, two_tenants):
        # Documenta por qué el servicio de auditoría no usa session.add (RETURNING)
        a, _ = two_tenants
        doctor = a["doctor"]
        with tenant_session(doctor) as session, pytest.raises(DBAPIError, match="row-level"):
            session.execute(
                insert(AuditLog)
                .values(id=uuid.uuid4(), actor_id=doctor.id, actor_role="doctor", action="x")
                .returning(AuditLog.id)
            )

    def test_b2c_solo_admite_pacientes(self, b2c_tenant, user_factory):
        with pytest.raises(DBAPIError, match="solo admite"):
            user_factory(b2c_tenant, role="doctor")

    def test_migraciones_de_datos_exigen_bypassrls(self, database):
        with get_engine().connect() as conn, pytest.raises(RuntimeError, match="BYPASSRLS"):
            assert_bypass(conn)
