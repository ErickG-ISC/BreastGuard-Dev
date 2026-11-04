"""clinical: estado del caso validado en la base, notas editables por su autora (CU-08, CU-11)

- `patients.reviewed_by` / `reviewed_at`: los fija el trigger al marcar revisado (nadie a mano).
- Trigger de transiciones de `patients.status`:
  pendiente → en_revision | revisado; en_revision → revisado | pendiente; revisado → en_revision;
  revisado → pendiente solo de forma automática (llega un análisis nuevo).
- Trigger en `analyses`: un análisis nuevo devuelve el caso a pendiente. Corre con los
  privilegios de quien inserta (sin SECURITY DEFINER); en la sesión de una paciente no toca nada
  porque el UPDATE de `patients` es solo de la doctora.
- `case_notes`: `updated_at`, UPDATE (body) y DELETE solo de su autora; SELECT solo de doctoras
  (la paciente nunca ve las notas, ni siquiera por la regla de acceso).
- Índice para "más recientes" del panel.
- La campana de la paciente: la doctora que acepta un traspaso de fichas importadas también
  deja un aviso `share_update` a la paciente de origen (mismas condiciones que `reasignado`).

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-05

"""

import importlib
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from backend.migrations.rls import (
    CLINICAL,
    CURRENT_ROLE,
    CURRENT_USER,
    add_role_policy,
    app_role,
    assert_bypass,
    grant_app,
)

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Marca de transacción que pone el trigger de análisis para el regreso automático a pendiente
AUTO_FLAG = "app.case_status_auto"

_PREVIOUS_SIDE_WRITES = importlib.import_module(
    "backend.migrations.versions.0016_evento_reasignado"
).SIDE_WRITES_SQL
_PATIENT_NOTICE_CHECK = (
    "          IF ctx_role <> 'patient' OR NEW.kind <> 'share_received' OR NOT EXISTS ("
)
_DOCTOR_NOTICE = """          IF ctx_role = 'doctor' AND NEW.kind = 'share_update' THEN
            IF EXISTS (
                 SELECT 1 FROM control.share_packages p
                 WHERE p.id = NEW.ref_id AND p.imported_tenant_id = tenant
                   AND p.source_user_id = NEW.user_id AND p.source_tenant_id = NEW.tenant_id)
               AND EXISTS (
                 SELECT 1 FROM clinical.patients c
                 WHERE c.tenant_id = tenant AND c.source_package_id = NEW.ref_id
                   AND c.responsible_doctor_id = me) THEN
              RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Aviso no permitido desde esta sesión';
          END IF;
"""
assert _PATIENT_NOTICE_CHECK in _PREVIOUS_SIDE_WRITES
SIDE_WRITES_SQL = _PREVIOUS_SIDE_WRITES.replace(
    _PATIENT_NOTICE_CHECK, _DOCTOR_NOTICE + _PATIENT_NOTICE_CHECK, 1
)


def _has_column(table: str, column: str) -> bool:
    columns = sa.inspect(op.get_bind()).get_columns(table, schema=CLINICAL)
    return any(c["name"] == column for c in columns)


def upgrade() -> None:
    assert_bypass(op.get_bind())
    for column in (
        sa.Column("reviewed_by", UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    ):
        if not _has_column("patients", column.name):
            op.add_column("patients", column, schema=CLINICAL)
    if not _has_column("case_notes", "updated_at"):
        op.add_column(
            "case_notes",
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            schema=CLINICAL,
        )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION clinical.enforce_case_status() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
          auto boolean := coalesce(current_setting('{AUTO_FLAG}', true), '') = 'on';
        BEGIN
          IF NEW.status IS NOT DISTINCT FROM OLD.status THEN
            RAISE EXCEPTION 'Transición de estado no permitida: % → %', OLD.status, NEW.status;
          END IF;
          IF NOT (
               (OLD.status = 'pendiente' AND NEW.status IN ('en_revision', 'revisado'))
            OR (OLD.status = 'en_revision' AND NEW.status IN ('revisado', 'pendiente'))
            OR (OLD.status = 'revisado' AND NEW.status = 'en_revision')
            OR (OLD.status = 'revisado' AND NEW.status = 'pendiente' AND auto)) THEN
            RAISE EXCEPTION 'Transición de estado no permitida: % → %', OLD.status, NEW.status;
          END IF;
          IF NEW.status = 'revisado' THEN
            NEW.reviewed_by := clinical.current_user_id();
            NEW.reviewed_at := now();
          ELSE
            NEW.reviewed_by := NULL;
            NEW.reviewed_at := NULL;
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_patients_case_status ON clinical.patients")
    op.execute(
        "CREATE TRIGGER trg_patients_case_status BEFORE UPDATE OF status ON clinical.patients "
        "FOR EACH ROW EXECUTE FUNCTION clinical.enforce_case_status()"
    )
    # reviewed_* solo los escribe el trigger: tampoco cambian sin cambiar el estado
    op.execute(
        """
        CREATE OR REPLACE FUNCTION clinical.protect_case_review() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.status IS NOT DISTINCT FROM OLD.status AND (
               NEW.reviewed_by IS DISTINCT FROM OLD.reviewed_by
            OR NEW.reviewed_at IS DISTINCT FROM OLD.reviewed_at) THEN
            RAISE EXCEPTION 'La revisión solo cambia junto con el estado';
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_patients_case_review ON clinical.patients")
    op.execute(
        "CREATE TRIGGER trg_patients_case_review BEFORE UPDATE ON clinical.patients "
        "FOR EACH ROW EXECUTE FUNCTION clinical.protect_case_review()"
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION clinical.reopen_case_on_analysis() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          PERFORM set_config('{AUTO_FLAG}', 'on', true);
          UPDATE clinical.patients SET status = 'pendiente', updated_at = now()
          WHERE tenant_id = NEW.tenant_id AND id = NEW.patient_id AND status <> 'pendiente';
          PERFORM set_config('{AUTO_FLAG}', '', true);
          RETURN NULL;
        END $$
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_analyses_reopen_case ON clinical.analyses")
    op.execute(
        "CREATE TRIGGER trg_analyses_reopen_case AFTER INSERT ON clinical.analyses "
        "FOR EACH ROW EXECUTE FUNCTION clinical.reopen_case_on_analysis()"
    )

    # Notas: solo doctoras las leen; editar y borrar, solo su autora
    doctor = f"{CURRENT_ROLE} = 'doctor'"
    author = f"{doctor} AND author_id = {CURRENT_USER}"
    add_role_policy("case_notes", "case_notes_doctor_read", doctor, command="SELECT")
    add_role_policy(
        "case_notes", "case_notes_author_update", author, command="UPDATE", with_check_sql=author
    )
    add_role_policy("case_notes", "case_notes_author_delete", author, command="DELETE")
    grant_app("case_notes", "UPDATE (body, updated_at), DELETE")

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_patients_doctor_created "
        "ON clinical.patients (tenant_id, responsible_doctor_id, created_at)"
    )
    op.execute(SIDE_WRITES_SQL)


def downgrade() -> None:
    assert_bypass(op.get_bind())
    op.execute(_PREVIOUS_SIDE_WRITES)
    op.execute("DROP INDEX IF EXISTS clinical.ix_patients_doctor_created")
    op.execute(f"REVOKE UPDATE (body, updated_at), DELETE ON clinical.case_notes FROM {app_role()}")
    for policy in (
        "case_notes_author_delete",
        "case_notes_author_update",
        "case_notes_doctor_read",
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON clinical.case_notes")
    op.execute("DROP TRIGGER IF EXISTS trg_analyses_reopen_case ON clinical.analyses")
    op.execute("DROP FUNCTION IF EXISTS clinical.reopen_case_on_analysis()")
    op.execute("DROP TRIGGER IF EXISTS trg_patients_case_review ON clinical.patients")
    op.execute("DROP FUNCTION IF EXISTS clinical.protect_case_review()")
    op.execute("DROP TRIGGER IF EXISTS trg_patients_case_status ON clinical.patients")
    op.execute("DROP FUNCTION IF EXISTS clinical.enforce_case_status()")
    # Columnas que nacieron en 0017 (la fecha de edición y la última revisión)
    op.execute("ALTER TABLE clinical.case_notes DROP COLUMN IF EXISTS updated_at")
    op.execute("ALTER TABLE clinical.patients DROP COLUMN IF EXISTS reviewed_at")
    op.execute("ALTER TABLE clinical.patients DROP COLUMN IF EXISTS reviewed_by")
