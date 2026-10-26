"""Crea o limpia un tenant de DEMOSTRACIÓN con personal invitado y datos clínicos SINTÉTICOS.

Uso, desde la raíz del repo (contra la base de DESARROLLO):
    python -m backend.scripts.seed_demo --create [--slug demo-clinica] [--admin-email tu@correo]
    python -m backend.scripts.seed_demo --clean  [--slug demo-clinica]

--create se conecta como app_user (nunca como dueño):
- en control: el tenant, un tenant_admin y dos médicos INVITADOS (sin contraseña) y cinco
  pacientes sintéticas; los enlaces de invitación se imprimen SOLO en esta terminal;
- en clinical, con el contexto del tenant nuevo: fichas, cuestionarios, autoexploraciones y
  entradas del diario. Sin imágenes (un análisis requeriría Storage y el modelo).

--clean reutiliza purge_tenant (rol dueño de DATABASE_URL) y solo acepta slugs `demo-…`: no
puede tocar ningún otro tenant.
"""

import argparse
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import Engine, create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from backend.app.content.questionnaire import QUESTIONNAIRE_VERSION, AnswersV1  # noqa: E402
from backend.app.content.risk_rules import evaluate  # noqa: E402
from backend.app.content.self_exam import SELF_EXAM_VERSION  # noqa: E402
from backend.app.db import TenantContext, new_session  # noqa: E402
from backend.app.models.clinical import (  # noqa: E402
    Patient,
    Questionnaire,
    SelfExam,
    SymptomEntry,
)
from backend.app.models.control import Tenant, User  # noqa: E402
from backend.app.services import admin_events, audit, invitations  # noqa: E402
from backend.scripts.purge_tenant import PurgeSummary, purge_tenant  # noqa: E402

DEMO_PREFIX = "demo-"
STAFF = (
    ("tenant_admin", "Administración Demo"),
    ("doctor", "Dra. Demo Uno"),
    ("doctor", "Dr. Demo Dos"),
)
# Respuestas y síntomas inventados; ninguna persona real
PATIENTS = (
    ("Paciente Demo A", 34, "none", [], ["sensibilidad"]),
    ("Paciente Demo B", 46, "first_degree", [], ["bulto", "dolor"]),
    ("Paciente Demo C", 52, "none", ["lump"], ["bulto"]),
    ("Paciente Demo D", 41, "second_degree", [], []),
    ("Paciente Demo E", 29, "none", [], ["dolor"]),
)


class DemoError(Exception):
    pass


@dataclass
class DemoResult:
    tenant_id: uuid.UUID
    links: dict[str, str] = field(default_factory=dict)


def _check_slug(slug: str) -> None:
    if not slug.startswith(DEMO_PREFIX):
        raise DemoError(
            f"Por seguridad, el tenant de demostración debe empezar por {DEMO_PREFIX!r}"
        )


def _event(
    db: Session, action: str, tenant_id: uuid.UUID, target_type: str, target_id, details=None
):
    admin_events.record(
        db,
        actor_id=None,
        actor_role="system",
        action=action,
        tenant_id=tenant_id,
        target_type=target_type,
        target_id=target_id,
        ip=None,
        details=details,
    )


def create_demo(slug: str = "demo-clinica", admin_email: str | None = None) -> DemoResult:
    _check_slug(slug)
    with new_session() as db:
        if db.scalars(select(Tenant.id).where(Tenant.slug == slug)).first():
            raise DemoError(f"El tenant {slug!r} ya existe; límpialo antes con --clean")
        tenant = Tenant(slug=slug, name="Clínica de Demostración", kind="institucion", plan="pro")
        db.add(tenant)
        db.flush()
        _event(db, "tenant.create", tenant.id, "tenant", tenant.id, {"plan": "pro"})

        result = DemoResult(tenant_id=tenant.id)
        staff: list[User] = []
        for index, (role, name) in enumerate(STAFF):
            email = (
                admin_email
                if role == "tenant_admin" and admin_email
                else f"{slug}-{role}-{index}@example.com"
            )
            user = User(tenant_id=tenant.id, email=email, full_name=name, role=role)
            db.add(user)
            db.flush()
            token = invitations.issue(db, user, "invite", None)
            _event(db, "user.invite", tenant.id, "user", user.id, {"role": role})
            result.links[f"{role} <{email}>"] = invitations.invitation_url(token)
            staff.append(user)

        accounts = []
        for index, patient in enumerate(PATIENTS):
            user = User(
                tenant_id=tenant.id,
                email=f"{slug}-paciente-{index}@example.com",
                full_name=patient[0],
                role="patient",
            )
            db.add(user)
            db.flush()
            accounts.append((user, patient))
        db.commit()
        tenant_id, admin_id = tenant.id, staff[0].id
        account_ids = [(user.id, data) for user, data in accounts]

    # Datos clínicos con el contexto del tenant nuevo (RLS: solo pueden caer en este tenant)
    with new_session(TenantContext(tenant_id, admin_id, "tenant_admin")) as db:
        audit.record(
            db,
            tenant_id=tenant_id,
            actor_id=admin_id,
            actor_role="tenant_admin",
            action="tenant.create",
            resource_type="tenant",
            resource_id=tenant_id,
        )
        today = date.today()
        for user_id, (name, age, family, current, symptoms) in account_ids:
            patient = Patient(user_id=user_id, display_name=name)
            db.add(patient)
            db.flush()
            answers = AnswersV1(
                age=age,
                family_history_breast=family,
                family_history_ovarian=False,
                brca_mutation="unknown",
                previous_biopsy=False,
                hormone_therapy=False,
                current_symptoms=current,
                last_checkup="1_to_2y",
            )
            evaluation = evaluate(answers)
            db.add(
                Questionnaire(
                    patient_id=patient.id,
                    version=QUESTIONNAIRE_VERSION,
                    answers=answers.model_dump(),
                    risk_factors=evaluation.factors,
                    summary_level=evaluation.level,
                )
            )
            finished = datetime.now(UTC) - timedelta(days=10)
            exam = SelfExam(
                patient_id=patient.id,
                created_by=user_id,
                content_version=SELF_EXAM_VERSION,
                started_at=finished - timedelta(minutes=8),
                finished_at=finished,
                noticed_change="si" if symptoms else "no",
            )
            db.add(exam)
            db.flush()
            for offset, symptom in enumerate(symptoms):
                db.add(
                    SymptomEntry(
                        patient_id=patient.id,
                        created_by=user_id,
                        entry_date=today - timedelta(days=10 - offset * 3),
                        side="izquierdo",
                        zone="superior_externo",
                        symptoms=[symptom],
                        intensity=3 + offset,
                        self_exam_id=exam.id if offset == 0 else None,
                        in_period=offset == 1,
                    )
                )
        db.commit()
    return result


def clean_demo(engine: Engine, slug: str = "demo-clinica") -> PurgeSummary:
    _check_slug(slug)
    return purge_tenant(engine, slug)


def main() -> int:
    import os

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--create", action="store_true")
    action.add_argument("--clean", action="store_true")
    parser.add_argument("--slug", default="demo-clinica")
    parser.add_argument("--admin-email", help="Correo del tenant_admin (p. ej. el tuyo)")
    args = parser.parse_args()

    try:
        if args.create:
            result = create_demo(args.slug, args.admin_email)
            print(f"Tenant de demostración creado: {args.slug} ({result.tenant_id})")
            print("Enlaces de invitación (de un solo uso; no los compartas por canales públicos):")
            for who, url in result.links.items():
                print(f"  {who}: {url}")
            return 0
        engine = create_engine(os.environ["DATABASE_URL"])
        try:
            summary = clean_demo(engine, args.slug)
        finally:
            engine.dispose()
        for table, count in summary.deleted.items():
            print(f"Borradas {count} filas de {table}")
        return 0
    except Exception as exc:  # mensajes claros para el operador, sin trazas con datos
        print(f"No se pudo completar: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
