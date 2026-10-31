"""clinical: fichas de institución, acceso por médica responsable, notas y revisiones (ADR 0009)

En tres pasos sobre `clinical.patients`:
1. expandir: origen, médica responsable, estado, edad, paquete de origen (todo NULL al inicio);
2. rellenar: las fichas existentes son de la propia paciente (`origin='propio'`, su user_id);
3. restringir: NOT NULL y CHECK de coherencia entre origen, user_id y médica responsable.

Después cambia el acceso clínico en TODAS las tablas con paciente: la paciente solo ve lo suyo, la
doctora solo lo de sus pacientes y tenant_admin/platform_admin nada clínico (la auditoría
conserva su propia política). Agrega `case_notes`, `analysis_reviews` y el perfil del modelo.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.migrations.rls import (
    CLINICAL,
    CONTROL,
    CURRENT_ROLE,
    CURRENT_USER,
    add_clinical_access_policy,
    add_patient_owner_policy,
    add_role_policy,
    app_role,
    assert_bypass,
    assert_empty,
    create_tenant_table,
    enable_tenant_rls,
    grant_app,
    restrict_command,
    revoke_supabase_api_roles,
    table_exists,
    tenant_fk,
)

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tablas con patient_id y el nombre de su política por rol (las de antes de 0013)
DEPENDENT_POLICIES = {
    "medical_images": "images_by_role",
    "questionnaires": "questionnaires_by_role",
    "analyses": "analyses_by_role",
    "self_exams": "self_exams_by_role",
    "symptom_entries": "symptom_entries_by_role",
}
ORIGINS = ("propio", "importado", "creado")
STATUSES = ("pendiente", "en_revision", "revisado")
BIRADS = ("0", "1", "2", "3", "4", "4A", "4B", "4C", "5", "6")
# Quién puede modificar o borrar (además de ver la fila). La doctora solo agrega datos de sus
# pacientes y cambia el estado del caso o su revisión; lo de la paciente solo lo cambia ella.
COMMAND_RULES = {
    ("medical_images", "UPDATE"): ("patient",),
    ("medical_images", "DELETE"): ("patient",),
    ("analyses", "DELETE"): ("patient",),
    ("self_exams", "UPDATE"): ("patient",),
    ("self_exams", "DELETE"): ("patient",),
    ("symptom_entries", "UPDATE"): ("patient",),
    ("symptom_entries", "DELETE"): ("patient",),
    ("patients", "UPDATE"): ("doctor",),
    ("analysis_reviews", "UPDATE"): ("doctor",),
}


def _has_column(table: str, column: str) -> bool:
    columns = sa.inspect(op.get_bind()).get_columns(table, schema=CLINICAL)
    return any(c["name"] == column for c in columns)


def _has_constraint(name: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text("SELECT 1 FROM pg_constraint WHERE conname = :n"),
            {"n": name},
        )
        .first()
    )


def _fk_includes(name: str, column: str) -> bool:
    """¿La FK `name` ya incluye `column`? (para reemplazarla de forma idempotente)."""
    return bool(
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM pg_constraint k JOIN pg_attribute a "
                "ON a.attrelid = k.conrelid AND a.attnum = ANY (k.conkey) "
                "WHERE k.conname = :n AND a.attname = :c"
            ),
            {"n": name, "c": column},
        )
        .first()
    )


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    # Lee y reescribe fichas: con RLS forzado, un dueño sin bypass vería 0 filas sin error
    assert_bypass(op.get_bind())
    # 1. Expandir
    new_columns = (
        sa.Column("origin", sa.Text(), nullable=True),
        sa.Column("responsible_doctor_id", UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("age_years", sa.SmallInteger(), nullable=True),
        sa.Column("age_recorded_on", sa.Date(), nullable=True),
        sa.Column("source_package_id", UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in new_columns:
        if not _has_column("patients", column.name):
            op.add_column("patients", column, schema=CLINICAL)

    # 2. Rellenar: toda ficha existente es de la propia paciente (con su cuenta)
    bind = op.get_bind()
    orphans = bind.execute(
        sa.text("SELECT count(*) FROM clinical.patients WHERE origin IS NULL AND user_id IS NULL")
    ).scalar_one()
    if orphans:
        raise RuntimeError(
            f"Hay {orphans} fichas sin user_id ni origen; asígnales médica responsable antes"
        )
    op.execute("UPDATE clinical.patients SET origin = 'propio' WHERE origin IS NULL")
    op.execute("UPDATE clinical.patients SET status = 'pendiente' WHERE status IS NULL")

    # 3. Restringir
    op.alter_column("patients", "origin", nullable=False, schema=CLINICAL)
    op.alter_column("patients", "status", nullable=False, schema=CLINICAL)
    op.alter_column("patients", "status", server_default=sa.text("'pendiente'"), schema=CLINICAL)
    checks = {
        "ck_patients_origin_values": f"origin IN ({_in(ORIGINS)})",
        "ck_patients_status": f"status IN ({_in(STATUSES)})",
        # propio => cuenta propia y sin médica; importado/creado => médica y sin cuenta
        "ck_patients_origin": (
            "(origin = 'propio' AND user_id IS NOT NULL AND responsible_doctor_id IS NULL) OR "
            "(origin IN ('importado', 'creado') AND responsible_doctor_id IS NOT NULL "
            "AND user_id IS NULL)"
        ),
        "ck_patients_age": "age_years IS NULL OR age_years BETWEEN 0 AND 120",
        "ck_patients_source_package": "source_package_id IS NULL OR origin = 'importado'",
    }
    for name, sql in checks.items():
        if not _has_constraint(name):
            op.create_check_constraint(name, "patients", sql, schema=CLINICAL)
    if not _has_constraint("fk_patients_responsible_doctor"):
        tenant_fk(
            "fk_patients_responsible_doctor",
            "patients",
            ["tenant_id", "responsible_doctor_id"],
            "users",
            ["tenant_id", "id"],
            ref_schema=CONTROL,
        )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_patients_doctor_status "
        "ON clinical.patients (tenant_id, responsible_doctor_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_patients_user ON clinical.patients (tenant_id, user_id)"
    )
    # Un paquete se importa una sola vez por tenant (protege reintentos tras una caída)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_patients_source_package "
        "ON clinical.patients (tenant_id, source_package_id) WHERE source_package_id IS NOT NULL"
    )
    grant_app("patients", "UPDATE (status, updated_at)")

    # Perfil del modelo y metadatos DICOM desidentificados (lista blanca, ADR 0011)
    if not _has_column("analyses", "profile"):
        op.add_column(
            "analyses",
            sa.Column(
                "profile", sa.Text(), nullable=False, server_default=sa.text("'ecografia_b2c'")
            ),
            schema=CLINICAL,
        )
    if not _has_column("analyses", "dicom_meta"):
        op.add_column("analyses", sa.Column("dicom_meta", JSONB(), nullable=True), schema=CLINICAL)
    if not _has_constraint("ck_analyses_profile"):
        op.create_check_constraint(
            "ck_analyses_profile",
            "analyses",
            "profile IN ('ecografia_b2c', 'mastografia_prototipo')",
            schema=CLINICAL,
        )

    # Las FKs no pasan por RLS: imagen y análisis referenciados deben ser de la MISMA paciente
    # (la doctora podrá crear análisis; sin esto podría enlazar la imagen de otra paciente)
    for table, unique in (
        ("medical_images", "uq_medical_images_patient_id"),
        ("analyses", "uq_analyses_patient_id"),
    ):
        if not _has_constraint(unique):
            op.create_unique_constraint(
                unique, table, ["tenant_id", "patient_id", "id"], schema=CLINICAL
            )
    if not _fk_includes("fk_analyses_image", "patient_id"):
        op.execute("ALTER TABLE clinical.analyses DROP CONSTRAINT IF EXISTS fk_analyses_image")
        tenant_fk(
            "fk_analyses_image",
            "analyses",
            ["tenant_id", "patient_id", "image_id"],
            "medical_images",
            ["tenant_id", "patient_id", "id"],
        )

    # Notas de la médica (solo inserción: una corrección es una nota nueva)
    if create_tenant_table(
        "case_notes",
        sa.Column("patient_id", UUID(as_uuid=True), nullable=False),
        sa.Column("author_id", UUID(as_uuid=True), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "char_length(body) BETWEEN 1 AND 4000", name="ck_case_notes_body_length"
        ),
    ):
        tenant_fk(
            "fk_case_notes_patient",
            "case_notes",
            ["tenant_id", "patient_id"],
            "patients",
            ["tenant_id", "id"],
        )
        op.create_index(
            "ix_case_notes_patient",
            "case_notes",
            ["tenant_id", "patient_id", "created_at"],
            schema=CLINICAL,
        )
    enable_tenant_rls("case_notes")
    add_clinical_access_policy("case_notes", "case_notes_by_role")
    # Solo la doctora escribe notas (y siempre como autora)
    add_role_policy(
        "case_notes",
        "case_notes_author",
        None,
        command="INSERT",
        with_check_sql=f"{CURRENT_ROLE} = 'doctor' AND author_id = {CURRENT_USER}",
    )
    grant_app("case_notes", "SELECT, INSERT")

    # Revisión de la médica sobre un análisis: BI-RADS y recomendación (el modelo no asigna BI-RADS)
    if create_tenant_table(
        "analysis_reviews",
        sa.Column("patient_id", UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_id", UUID(as_uuid=True), nullable=False),
        sa.Column("birads", sa.Text(), nullable=True),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("reviewed_by", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"birads IN ({_in(BIRADS)})", name="ck_analysis_reviews_birads"),
        sa.CheckConstraint(
            "char_length(recommendation) <= 2000", name="ck_analysis_reviews_recommendation"
        ),
        sa.UniqueConstraint("tenant_id", "analysis_id", name="uq_analysis_reviews_analysis"),
    ):
        tenant_fk(
            "fk_analysis_reviews_patient",
            "analysis_reviews",
            ["tenant_id", "patient_id"],
            "patients",
            ["tenant_id", "id"],
        )
        tenant_fk(
            "fk_analysis_reviews_analysis",
            "analysis_reviews",
            ["tenant_id", "patient_id", "analysis_id"],
            "analyses",
            ["tenant_id", "patient_id", "id"],
        )
    enable_tenant_rls("analysis_reviews")
    add_clinical_access_policy("analysis_reviews", "analysis_reviews_by_role")
    add_role_policy(
        "analysis_reviews",
        "analysis_reviews_doctor_writes",
        None,
        command="INSERT",
        with_check_sql=f"{CURRENT_ROLE} = 'doctor' AND reviewed_by = {CURRENT_USER}",
    )
    grant_app("analysis_reviews", "SELECT, INSERT, UPDATE (birads, recommendation, updated_at)")

    # Acceso clínico nuevo en todas las tablas con paciente (reemplaza las políticas por rol)
    add_clinical_access_policy("patients", "patients_by_role")
    for table, policy in DEPENDENT_POLICIES.items():
        add_clinical_access_policy(table, policy)
    for (table, command), roles in COMMAND_RULES.items():
        restrict_command(table, command, roles)
    revoke_supabase_api_roles()


def downgrade() -> None:
    bind = op.get_bind()
    # Sin bypass los chequeos de abajo verían 0 filas y los DROP COLUMN borrarían datos
    assert_bypass(bind)
    for table in ("analysis_reviews", "case_notes"):
        if table_exists(table, CLINICAL):
            assert_empty(f"clinical.{table}", f"clinical.{table} tiene datos; 0013 no los borra.")
    if bind.execute(
        sa.text("SELECT 1 FROM clinical.patients WHERE origin <> 'propio' LIMIT 1")
    ).first():
        raise RuntimeError("Hay fichas de institución; el downgrade de 0013 no las borra.")
    if bind.execute(
        sa.text("SELECT 1 FROM clinical.analyses WHERE profile <> 'ecografia_b2c' LIMIT 1")
    ).first():
        raise RuntimeError("Hay análisis de mastografía; el downgrade de 0013 no los borra.")

    for table, command in COMMAND_RULES:
        if table_exists(table, CLINICAL):
            op.execute(
                f"DROP POLICY IF EXISTS {table}_{command.lower()}_by_role ON clinical.{table}"
            )
    op.execute("DROP TABLE IF EXISTS clinical.analysis_reviews")
    op.execute("DROP TABLE IF EXISTS clinical.case_notes")

    # Políticas anteriores a 0013 (mismas expresiones de 0004 y 0007-0010)
    clinical_role = f"{CURRENT_ROLE} IN ('patient', 'doctor', 'tenant_admin')"
    patient_rule = f"{clinical_role} AND ({CURRENT_ROLE} <> 'patient' OR user_id = {CURRENT_USER})"
    add_role_policy("patients", "patients_by_role", patient_rule, with_check_sql=patient_rule)
    own_ids = (
        f"patient_id IN (SELECT p.id FROM clinical.patients p WHERE p.user_id = {CURRENT_USER})"
    )
    image_rule = f"{clinical_role} AND ({CURRENT_ROLE} <> 'patient' OR {own_ids})"
    add_role_policy("medical_images", "images_by_role", image_rule, with_check_sql=image_rule)
    for table, policy in DEPENDENT_POLICIES.items():
        if table != "medical_images":
            add_patient_owner_policy(table, policy)

    if _fk_includes("fk_analyses_image", "patient_id"):
        op.execute("ALTER TABLE clinical.analyses DROP CONSTRAINT fk_analyses_image")
        tenant_fk(
            "fk_analyses_image",
            "analyses",
            ["tenant_id", "image_id"],
            "medical_images",
            ["tenant_id", "id"],
        )
    op.execute("ALTER TABLE clinical.analyses DROP CONSTRAINT IF EXISTS uq_analyses_patient_id")
    op.execute(
        "ALTER TABLE clinical.medical_images DROP CONSTRAINT IF EXISTS uq_medical_images_patient_id"
    )
    op.execute(f"REVOKE UPDATE (status, updated_at) ON clinical.patients FROM {app_role()}")
    op.execute("ALTER TABLE clinical.analyses DROP CONSTRAINT IF EXISTS ck_analyses_profile")
    op.execute("ALTER TABLE clinical.analyses DROP COLUMN IF EXISTS dicom_meta")
    op.execute("ALTER TABLE clinical.analyses DROP COLUMN IF EXISTS profile")
    op.execute("DROP INDEX IF EXISTS clinical.ux_patients_source_package")
    op.execute("DROP INDEX IF EXISTS clinical.ix_patients_user")
    op.execute("DROP INDEX IF EXISTS clinical.ix_patients_doctor_status")
    for name in (
        "fk_patients_responsible_doctor",
        "ck_patients_source_package",
        "ck_patients_age",
        "ck_patients_origin",
        "ck_patients_status",
        "ck_patients_origin_values",
    ):
        op.execute(f"ALTER TABLE clinical.patients DROP CONSTRAINT IF EXISTS {name}")
    for column in (
        "updated_at",
        "source_package_id",
        "age_recorded_on",
        "age_years",
        "status",
        "responsible_doctor_id",
        "origin",
    ):
        op.execute(f"ALTER TABLE clinical.patients DROP COLUMN IF EXISTS {column}")
