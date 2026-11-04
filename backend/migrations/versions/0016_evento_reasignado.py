"""control: la doctora registra `reasignado` al aceptar un traspaso de fichas importadas (CU-07)

Cumple lo que dice el consentimiento del paquete: si la institución asigna el caso a otra
médica, la paciente lo ve en "Mis paquetes". El evento lo escribe la doctora que acepta el
traspaso, con SU contexto, y la base solo lo acepta si:
- el paquete se importó en el tenant del contexto;
- una ficha de ese paquete tiene a la doctora del contexto como responsable (RLS de clinical);
- los nombres son los de su institución y los suyos (no puede inventarlos).

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-04

"""

import importlib
from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SIDE_WRITES_SQL = """
        CREATE OR REPLACE FUNCTION control.enforce_share_side_writes() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
          ctx_role text := NULLIF(current_setting('app.role', true), '');
          me uuid := clinical.current_user_id();
          tenant uuid := clinical.current_tenant_id();
        BEGIN
          IF ctx_role IS NULL THEN
            RETURN NEW;
          END IF;
          IF TG_TABLE_NAME = 'share_events' THEN
            IF ctx_role = 'doctor' AND NEW.kind = 'reasignado' THEN
              IF EXISTS (
                   SELECT 1 FROM control.share_packages p
                   WHERE p.id = NEW.package_id AND p.imported_tenant_id = tenant)
                 AND EXISTS (
                   SELECT 1 FROM clinical.patients c
                   WHERE c.tenant_id = tenant AND c.source_package_id = NEW.package_id
                     AND c.responsible_doctor_id = me)
                 AND NEW.doctor_name IS NOT DISTINCT FROM (
                   SELECT u.full_name FROM control.users u WHERE u.id = me)
                 AND NEW.institution_name IS NOT DISTINCT FROM (
                   SELECT t.name FROM control.tenants t WHERE t.id = tenant) THEN
                RETURN NEW;
              END IF;
              RAISE EXCEPTION 'Evento de paquete no permitido desde esta sesión';
            END IF;
            IF ctx_role <> 'patient' OR NEW.kind NOT IN ('creado', 'revocado')
               OR NEW.institution_name IS NOT NULL OR NEW.doctor_name IS NOT NULL
               OR NOT EXISTS (
                 SELECT 1 FROM control.share_packages p WHERE p.id = NEW.package_id
                   AND p.source_user_id = me
                   AND p.source_tenant_id = tenant) THEN
              RAISE EXCEPTION 'Evento de paquete no permitido desde esta sesión';
            END IF;
            RETURN NEW;
          END IF;
          -- inbox_notices
          IF TG_OP = 'UPDATE' THEN
            IF OLD.user_id IS DISTINCT FROM me THEN
              RAISE EXCEPTION 'Solo la destinataria marca sus avisos';
            END IF;
            RETURN NEW;
          END IF;
          IF ctx_role <> 'patient' OR NEW.kind <> 'share_received' OR NOT EXISTS (
               SELECT 1 FROM control.share_packages p WHERE p.id = NEW.ref_id
                 AND p.source_user_id = me
                 AND p.source_tenant_id = tenant
                 AND p.recipient_user_id = NEW.user_id) THEN
            RAISE EXCEPTION 'Aviso no permitido desde esta sesión';
          END IF;
          RETURN NEW;
        END $$
        """


def upgrade() -> None:
    op.execute(SIDE_WRITES_SQL)


def downgrade() -> None:
    # Vuelve a la función de 0015 (sin la rama de la doctora); los eventos ya escritos se quedan
    previous = importlib.import_module("backend.migrations.versions.0015_paquetes_compartidos")
    op.execute(previous.SIDE_WRITES_SQL)
