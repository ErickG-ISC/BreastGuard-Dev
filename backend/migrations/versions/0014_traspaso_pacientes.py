"""control.patient_handovers: traspaso de las pacientes de una médica a otra (ADR 0009)

Las fichas de institución solo las ve su médica responsable. Si ella se va (se desactiva o deja
de ser doctora), nadie más las vería. El traspaso se hace en dos pasos, sin que la
administración lea datos clínicos:

1. tenant_admin o platform_admin crea en `control` un traspaso pendiente (de X a Y): solo ids;
2. desde ese momento la regla de acceso deja a Y ver a las pacientes de X; Y lo acepta con SU
   contexto y la ficha pasa a tenerla como responsable (UPDATE de `responsible_doctor_id`).

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from backend.migrations.rls import (
    CONTROL,
    CURRENT_ROLE,
    CURRENT_USER,
    add_clinical_access_policy,
    add_role_policy,
    app_role,
    assert_empty,
    grant_app,
    restrict_command,
    revoke_supabase_api_roles,
    table_exists,
)

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCESS_POLICIES = {
    "patients": "patients_by_role",
    "medical_images": "images_by_role",
    "questionnaires": "questionnaires_by_role",
    "analyses": "analyses_by_role",
    "self_exams": "self_exams_by_role",
    "symptom_entries": "symptom_entries_by_role",
    "case_notes": "case_notes_by_role",
    "analysis_reviews": "analysis_reviews_by_role",
}


def _access_policies(handover: bool) -> None:
    for table, policy in ACCESS_POLICIES.items():
        add_clinical_access_policy(table, policy, handover=handover)


def upgrade() -> None:
    if not table_exists("patient_handovers", CONTROL):
        op.create_table(
            "patient_handovers",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("from_doctor_id", UUID(as_uuid=True), nullable=False),
            sa.Column("to_doctor_id", UUID(as_uuid=True), nullable=False),
            sa.Column("created_by", UUID(as_uuid=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("patients_moved", sa.Integer(), nullable=True),
            sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cancelled_by", UUID(as_uuid=True), nullable=True),
            # Origen y destino del mismo tenant (FK compuesta, igual que las fichas)
            sa.ForeignKeyConstraint(
                ["tenant_id", "from_doctor_id"],
                ["control.users.tenant_id", "control.users.id"],
                name="fk_patient_handovers_from",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "to_doctor_id"],
                ["control.users.tenant_id", "control.users.id"],
                name="fk_patient_handovers_to",
            ),
            sa.CheckConstraint(
                "from_doctor_id <> to_doctor_id", name="ck_patient_handovers_distinct"
            ),
            sa.CheckConstraint(
                "accepted_at IS NULL OR cancelled_at IS NULL", name="ck_patient_handovers_closed"
            ),
            schema=CONTROL,
        )
    # Un solo traspaso pendiente por médica de origen (evita cadenas ambiguas)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_patient_handovers_pending "
        "ON control.patient_handovers (tenant_id, from_doctor_id) "
        "WHERE accepted_at IS NULL AND cancelled_at IS NULL"
    )
    # La regla de acceso lo consulta por destino en cada petición de la doctora
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_patient_handovers_to "
        "ON control.patient_handovers (tenant_id, to_doctor_id) "
        "WHERE accepted_at IS NULL AND cancelled_at IS NULL"
    )
    grant_app(
        "patient_handovers",
        "SELECT, INSERT, UPDATE (accepted_at, patients_moved, cancelled_at, cancelled_by)",
        schema=CONTROL,
    )

    # control no tiene RLS y app_user es el mismo rol de las sesiones clínicas: la base impide
    # que una sesión con contexto de paciente o doctora cree traspasos (solo la administración,
    # que usa sesiones de control sin contexto). La doctora solo puede ACEPTAR uno hacia ella.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION control.enforce_handover_writes() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
          ctx_role text := NULLIF(current_setting('app.role', true), '');
        BEGIN
          IF ctx_role IS NULL THEN
            RETURN NEW;
          END IF;
          IF TG_OP = 'INSERT' THEN
            RAISE EXCEPTION 'Los traspasos solo se crean desde la administración';
          END IF;
          IF ctx_role <> 'doctor'
             OR OLD.to_doctor_id IS DISTINCT FROM clinical.current_user_id()
             OR OLD.accepted_at IS NOT NULL OR OLD.cancelled_at IS NOT NULL
             OR NEW.accepted_at IS NULL
             OR NEW.cancelled_at IS NOT NULL OR NEW.cancelled_by IS NOT NULL THEN
            RAISE EXCEPTION 'Solo la médica de destino acepta un traspaso pendiente';
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_patient_handovers_writes ON control.patient_handovers")
    op.execute(
        "CREATE TRIGGER trg_patient_handovers_writes BEFORE INSERT OR UPDATE "
        "ON control.patient_handovers FOR EACH ROW "
        "EXECUTE FUNCTION control.enforce_handover_writes()"
    )

    _access_policies(handover=True)
    # Aceptar = la doctora se pone a sí misma como responsable. Ni al crear ni al actualizar
    # puede dejar una ficha a nombre de otra (tampoco de la médica de origen de un traspaso).
    grant_app("patients", "UPDATE (responsible_doctor_id)")
    own_doctor = f"{CURRENT_ROLE} <> 'doctor' OR responsible_doctor_id = {CURRENT_USER}"
    add_role_policy(
        "patients", "patients_insert_own_doctor", None, command="INSERT", with_check_sql=own_doctor
    )
    # Reemplaza la de 0013 (USING = WITH CHECK = rol doctor): la fila resultante es suya
    add_role_policy(
        "patients",
        "patients_update_by_role",
        f"{CURRENT_ROLE} = 'doctor'",
        command="UPDATE",
        with_check_sql=f"{CURRENT_ROLE} = 'doctor' AND responsible_doctor_id = {CURRENT_USER}",
    )
    revoke_supabase_api_roles()


def downgrade() -> None:
    if table_exists("patient_handovers", CONTROL):
        assert_empty(
            "control.patient_handovers", "control.patient_handovers tiene datos; 0014 no los borra."
        )
    op.execute("DROP POLICY IF EXISTS patients_insert_own_doctor ON clinical.patients")
    restrict_command("patients", "UPDATE", ("doctor",))  # la de 0013
    op.execute(f"REVOKE UPDATE (responsible_doctor_id) ON clinical.patients FROM {app_role()}")
    _access_policies(handover=False)
    op.execute("DROP TABLE IF EXISTS control.patient_handovers")
    op.execute("DROP FUNCTION IF EXISTS control.enforce_handover_writes()")
