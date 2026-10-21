"""Cuestionario de antecedentes (CU-01). Sesión de get_tenant_db: RLS limita a la paciente."""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.content.questionnaire import QUESTIONNAIRE_VERSION, AnswersV1
from backend.app.content.risk_rules import LEVEL_MESSAGES, evaluate
from backend.app.models.clinical import Patient, Questionnaire
from backend.app.schemas.onboarding import QuestionnaireOut
from backend.app.services import audit
from backend.app.services.auth import AuthContext

DISCLAIMER = "Herramienta de apoyo al diagnóstico. No sustituye el criterio ni la consulta médica."


def _record(db: Session, auth: AuthContext, action: str, questionnaire_id, ip: str | None) -> None:
    audit.record(
        db,
        tenant_id=auth.tenant_id,
        actor_id=auth.user_id,
        actor_role=auth.role,
        action=action,
        resource_type="questionnaire",
        resource_id=questionnaire_id,
        ip=ip,
    )


def _to_out(row: Questionnaire) -> QuestionnaireOut:
    return QuestionnaireOut(
        id=row.id,
        version=row.version,
        created_at=row.created_at,
        factors=row.risk_factors,
        level=row.summary_level,
        message=LEVEL_MESSAGES[row.summary_level],
        disclaimer=DISCLAIMER,
    )


def submit(
    db: Session, auth: AuthContext, version: str, answers: AnswersV1, ip: str | None
) -> QuestionnaireOut:
    if version != QUESTIONNAIRE_VERSION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="La versión del cuestionario no es la vigente",
        )
    patient = db.scalars(select(Patient).where(Patient.user_id == auth.user_id)).first()
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ficha no encontrada")
    evaluation = evaluate(answers)
    row = Questionnaire(
        patient_id=patient.id,
        version=version,
        answers=answers.model_dump(),
        risk_factors=evaluation.factors,
        summary_level=evaluation.level,
    )
    db.add(row)
    db.flush()
    _record(db, auth, "questionnaire.create", row.id, ip)
    db.commit()
    db.refresh(row)
    return _to_out(row)


def latest(db: Session, auth: AuthContext, ip: str | None) -> QuestionnaireOut:
    """El más reciente de la paciente (RLS y la política de paciente limitan las filas)."""
    row = db.scalars(select(Questionnaire).order_by(Questionnaire.created_at.desc())).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Aún no respondes el cuestionario"
        )
    _record(db, auth, "questionnaire.read", row.id, ip)
    db.commit()
    return _to_out(row)
