"""CU-03: autoexploración guiada (iniciar, terminar, historial, última y eliminar).

La sesión es de get_tenant_db: RLS limita al tenant del JWT y la política de paciente a sus
propias filas; además cada consulta filtra explícitamente por la ficha de la paciente. La nota
es texto libre sensible: nunca se registra en logs ni en la auditoría (solo el id del recurso).
"""

import uuid
from datetime import UTC, datetime
from typing import NoReturn

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.content.self_exam import SELF_EXAM_VERSION
from backend.app.models.clinical import Patient, SelfExam
from backend.app.schemas.self_exam import SelfExamFinishIn
from backend.app.services import audit
from backend.app.services.auth import AuthContext

NOT_FOUND = "Autoexploración no encontrada"


def _audit(db: Session, auth: AuthContext, action: str, resource_id, ip: str | None) -> None:
    audit.record(
        db,
        tenant_id=auth.tenant_id,
        actor_id=auth.user_id,
        actor_role=auth.role,
        action=action,
        resource_type="self_exam",
        resource_id=resource_id,
        ip=ip,
    )


def _deny(db: Session, auth: AuthContext, exam_id: uuid.UUID, ip: str | None) -> NoReturn:
    """404 uniforme (ajena o inexistente); el intento queda en la auditoría de quien preguntó."""
    db.rollback()
    _audit(db, auth, "self_exam.denied", exam_id, ip)
    db.commit()
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)


def _own(auth: AuthContext):
    """Pertenencia explícita además de RLS: solo la ficha de esta paciente."""
    own_patient = select(Patient.id).where(Patient.user_id == auth.user_id).scalar_subquery()
    return SelfExam.patient_id == own_patient


def _load(
    db: Session, auth: AuthContext, exam_id: uuid.UUID, ip: str | None, *, lock: bool = False
) -> SelfExam:
    query = select(SelfExam).where(SelfExam.id == exam_id, _own(auth))
    if lock:
        # Dos "terminar" simultáneos: el segundo espera al primero y luego ve finished_at
        query = query.with_for_update(of=SelfExam)
    exam = db.scalars(query).first()
    if exam is None:
        _deny(db, auth, exam_id, ip)
    return exam


def start(db: Session, auth: AuthContext, ip: str | None) -> SelfExam:
    patient = db.scalars(select(Patient).where(Patient.user_id == auth.user_id)).first()
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ficha no encontrada")
    exam = SelfExam(
        patient_id=patient.id, created_by=auth.user_id, content_version=SELF_EXAM_VERSION
    )
    db.add(exam)
    db.flush()
    _audit(db, auth, "self_exam.start", exam.id, ip)
    db.commit()
    db.refresh(exam)
    return exam


def finish(
    db: Session, auth: AuthContext, exam_id: uuid.UUID, data: SelfExamFinishIn, ip: str | None
) -> SelfExam:
    exam = _load(db, auth, exam_id, ip, lock=True)
    if exam.finished_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Esta autoexploración ya se terminó"
        )
    exam.finished_at = datetime.now(UTC)
    exam.noticed_change = data.noticed_change
    exam.note = data.note
    db.flush()
    _audit(db, auth, "self_exam.finish", exam.id, ip)
    db.commit()
    db.refresh(exam)
    return exam


def list_page(
    db: Session, auth: AuthContext, limit: int, offset: int, ip: str | None
) -> tuple[list[SelfExam], int]:
    total = db.scalar(select(func.count()).select_from(SelfExam).where(_own(auth)))
    items = list(
        db.scalars(
            select(SelfExam)
            .where(_own(auth))
            .order_by(SelfExam.started_at.desc(), SelfExam.id)
            .limit(limit)
            .offset(offset)
        )
    )
    _audit(db, auth, "self_exam.list", None, ip)
    db.commit()
    return items, total


def latest(db: Session, auth: AuthContext, ip: str | None) -> SelfExam:
    """La última autoexploración TERMINADA (la "vez pasada" con la que se compara)."""
    exam = db.scalars(
        select(SelfExam)
        .where(_own(auth), SelfExam.finished_at.is_not(None))
        .order_by(SelfExam.finished_at.desc(), SelfExam.id)
    ).first()
    if exam is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Aún no terminas ninguna autoexploración"
        )
    _audit(db, auth, "self_exam.read", exam.id, ip)
    db.commit()
    return exam


def get(db: Session, auth: AuthContext, exam_id: uuid.UUID, ip: str | None) -> SelfExam:
    exam = _load(db, auth, exam_id, ip)
    _audit(db, auth, "self_exam.read", exam.id, ip)
    db.commit()
    return exam


def delete(db: Session, auth: AuthContext, exam_id: uuid.UUID, ip: str | None) -> None:
    exam = _load(db, auth, exam_id, ip)
    db.delete(exam)
    db.flush()
    _audit(db, auth, "self_exam.delete", exam_id, ip)
    db.commit()
