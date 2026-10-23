"""CU-04: diario de síntomas (crear, línea de tiempo con filtros, detalle, editar y borrar).

La sesión es de get_tenant_db: RLS limita al tenant del JWT y la política de paciente a sus
propias filas; además cada consulta filtra explícitamente por la ficha de la paciente. La nota
es texto libre sensible: nunca se registra en logs ni en la auditoría (solo el id del recurso).

`get_entries(db, auth, since)` es la función reutilizable para el paquete de CU-07 (últimos
3 meses); no audita por sí misma: audita quien la llama, con su propia acción.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import NoReturn

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.clinical import Patient, SelfExam, SymptomEntry
from backend.app.schemas.symptoms import SymptomEntryIn, SymptomEntryUpdate
from backend.app.services import audit
from backend.app.services.auth import AuthContext

NOT_FOUND = "Registro del diario no encontrado"
SELF_EXAM_NOT_FOUND = "Autoexploración no encontrada"


@dataclass(frozen=True)
class EntryFilters:
    date_from: date | None = None
    date_to: date | None = None
    symptom: str | None = None
    zone: str | None = None
    side: str | None = None


def _audit(
    db: Session,
    auth: AuthContext,
    action: str,
    resource_id,
    ip: str | None,
    resource_type: str = "symptom_entry",
) -> None:
    audit.record(
        db,
        tenant_id=auth.tenant_id,
        actor_id=auth.user_id,
        actor_role=auth.role,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip=ip,
    )


def _deny(db: Session, auth: AuthContext, entry_id: uuid.UUID, ip: str | None) -> NoReturn:
    """404 uniforme (ajena o inexistente); el intento queda en la auditoría de quien preguntó."""
    db.rollback()
    _audit(db, auth, "symptom.denied", entry_id, ip)
    db.commit()
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)


def _own_patient_id(auth: AuthContext):
    return select(Patient.id).where(Patient.user_id == auth.user_id).scalar_subquery()


def _own(auth: AuthContext):
    """Pertenencia explícita además de RLS: solo la ficha de esta paciente."""
    return SymptomEntry.patient_id == _own_patient_id(auth)


def _check_self_exam(
    db: Session, auth: AuthContext, self_exam_id: uuid.UUID | None, ip: str | None
) -> None:
    """El enlace solo puede apuntar a una autoexploración propia (la FK también lo exige)."""
    if self_exam_id is None:
        return
    exists = db.scalar(
        select(SelfExam.id).where(
            SelfExam.id == self_exam_id, SelfExam.patient_id == _own_patient_id(auth)
        )
    )
    if exists is None:
        db.rollback()
        _audit(db, auth, "self_exam.denied", self_exam_id, ip, resource_type="self_exam")
        db.commit()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=SELF_EXAM_NOT_FOUND)


def _load(db: Session, auth: AuthContext, entry_id: uuid.UUID, ip: str | None) -> SymptomEntry:
    entry = db.scalars(select(SymptomEntry).where(SymptomEntry.id == entry_id, _own(auth))).first()
    if entry is None:
        _deny(db, auth, entry_id, ip)
    return entry


def _filtered(auth: AuthContext, filters: EntryFilters):
    conditions = [_own(auth)]
    if filters.date_from is not None:
        conditions.append(SymptomEntry.entry_date >= filters.date_from)
    if filters.date_to is not None:
        conditions.append(SymptomEntry.entry_date <= filters.date_to)
    if filters.symptom is not None:
        conditions.append(SymptomEntry.symptoms.contains([filters.symptom]))
    if filters.zone is not None:
        conditions.append(SymptomEntry.zone == filters.zone)
    if filters.side is not None:
        # "ambos" también aparece al filtrar por un lado concreto
        conditions.append(SymptomEntry.side.in_([filters.side, "ambos"]))
    return conditions


def create(db: Session, auth: AuthContext, data: SymptomEntryIn, ip: str | None) -> SymptomEntry:
    patient = db.scalars(select(Patient).where(Patient.user_id == auth.user_id)).first()
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ficha no encontrada")
    patient_id = patient.id
    _check_self_exam(db, auth, data.self_exam_id, ip)
    entry = SymptomEntry(patient_id=patient_id, created_by=auth.user_id, **data.model_dump())
    db.add(entry)
    db.flush()
    _audit(db, auth, "symptom.create", entry.id, ip)
    db.commit()
    db.refresh(entry)
    return entry


def list_page(
    db: Session,
    auth: AuthContext,
    filters: EntryFilters,
    limit: int,
    offset: int,
    ip: str | None,
) -> tuple[list[SymptomEntry], int]:
    conditions = _filtered(auth, filters)
    total = db.scalar(select(func.count()).select_from(SymptomEntry).where(*conditions))
    items = list(
        db.scalars(
            select(SymptomEntry)
            .where(*conditions)
            .order_by(
                SymptomEntry.entry_date.desc(), SymptomEntry.created_at.desc(), SymptomEntry.id
            )
            .limit(limit)
            .offset(offset)
        )
    )
    _audit(db, auth, "symptom.list", None, ip)
    db.commit()
    return items, total


def get_entries(db: Session, auth: AuthContext, since: date) -> list[SymptomEntry]:
    """Entradas propias desde `since` (incluido), de la más antigua a la más reciente.

    Para el paquete de CU-07. Corre bajo RLS con el contexto de la paciente; no audita.
    """
    return list(
        db.scalars(
            select(SymptomEntry)
            .where(_own(auth), SymptomEntry.entry_date >= since)
            .order_by(SymptomEntry.entry_date, SymptomEntry.created_at, SymptomEntry.id)
        )
    )


def get(db: Session, auth: AuthContext, entry_id: uuid.UUID, ip: str | None) -> SymptomEntry:
    entry = _load(db, auth, entry_id, ip)
    _audit(db, auth, "symptom.read", entry.id, ip)
    db.commit()
    return entry


def update(
    db: Session,
    auth: AuthContext,
    entry_id: uuid.UUID,
    data: SymptomEntryUpdate,
    ip: str | None,
) -> SymptomEntry:
    entry = _load(db, auth, entry_id, ip)
    changes = data.model_dump(exclude_unset=True)
    if "self_exam_id" in changes:
        _check_self_exam(db, auth, changes["self_exam_id"], ip)
    for name, value in changes.items():
        setattr(entry, name, value)
    entry.updated_at = datetime.now(UTC)
    db.flush()
    _audit(db, auth, "symptom.update", entry.id, ip)
    db.commit()
    db.refresh(entry)
    return entry


def delete(db: Session, auth: AuthContext, entry_id: uuid.UUID, ip: str | None) -> None:
    entry = _load(db, auth, entry_id, ip)
    db.delete(entry)
    db.flush()
    _audit(db, auth, "symptom.delete", entry_id, ip)
    db.commit()
