"""Traspaso de las pacientes de una médica a otra (0014, ADR 0009).

Dos pasos, para que la administración nunca toque datos clínicos:
1. platform_admin o tenant_admin (con su alcance de `user_admin.Scope`) crea en `control` un
   traspaso pendiente de X a Y. Desde ese momento la regla de acceso deja a Y ver a las
   pacientes de X: ninguna ficha queda sin nadie que la vea.
2. Y lo acepta con SU contexto (TenantDb): sus fichas pasan a tenerla como responsable y el
   traspaso se cierra, con auditoría clínica y bitácora de plataforma en la misma transacción.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from backend.app.models.clinical import Patient
from backend.app.models.control import PatientHandover, User
from backend.app.schemas.handovers import HandoverCreate, HandoverOut, PendingHandoverOut
from backend.app.services import admin_events, audit
from backend.app.services.auth import AuthContext
from backend.app.services.tenants import ConflictError, InvalidOperationError, NotFoundError
from backend.app.services.user_admin import Scope, _staff_in_scope, _tenant_in_scope


def _pending():
    return (PatientHandover.accepted_at.is_(None), PatientHandover.cancelled_at.is_(None))


@dataclass(frozen=True)
class _Row:
    handover: PatientHandover
    from_name: str
    to_name: str


def to_out(row: _Row) -> HandoverOut:
    h = row.handover
    if h.accepted_at is not None:
        status = "accepted"
    elif h.cancelled_at is not None:
        status = "cancelled"
    else:
        status = "pending"
    return HandoverOut(
        id=h.id,
        tenant_id=h.tenant_id,
        from_doctor_id=h.from_doctor_id,
        from_name=row.from_name,
        to_doctor_id=h.to_doctor_id,
        to_name=row.to_name,
        status=status,
        created_at=h.created_at,
        accepted_at=h.accepted_at,
        cancelled_at=h.cancelled_at,
        patients_moved=h.patients_moved,
    )


def _event(db: Session, scope: Scope, action: str, h: PatientHandover, ip, details=None) -> None:
    admin_events.record(
        db,
        actor_id=scope.actor.user_id,
        actor_role=scope.actor.role,
        action=action,
        tenant_id=h.tenant_id,
        target_type="user",
        target_id=h.from_doctor_id,
        ip=ip,
        details={"to_user_id": str(h.to_doctor_id), **(details or {})},
    )


def _rows(db: Session, *where) -> list[_Row]:
    source, target = aliased(User), aliased(User)
    query = (
        select(PatientHandover, source.full_name, target.full_name)
        .join(source, source.id == PatientHandover.from_doctor_id)
        .join(target, target.id == PatientHandover.to_doctor_id)
        .where(*where)
        .order_by(PatientHandover.created_at.desc(), PatientHandover.id)
    )
    return [_Row(h, f, t) for h, f, t in db.execute(query)]


def create(
    db: Session, scope: Scope, from_id: uuid.UUID, data: HandoverCreate, ip: str | None
) -> HandoverOut:
    source, _tenant = _staff_in_scope(db, scope, from_id, lock=True)
    target, _ = _staff_in_scope(db, scope, data.to_user_id)
    # Otro tenant responde igual que un usuario inexistente
    if target.tenant_id != source.tenant_id:
        raise NotFoundError
    if target.id == source.id:
        raise InvalidOperationError("Elige a otra médica")
    if target.role != "doctor" or not target.is_active:
        raise InvalidOperationError("Las pacientes solo pueden pasar a una doctora activa")
    chained = db.scalar(
        select(PatientHandover.id).where(
            PatientHandover.tenant_id == source.tenant_id,
            or_(
                PatientHandover.from_doctor_id == target.id,
                PatientHandover.to_doctor_id == source.id,
            ),
            *_pending(),
        )
    )
    if chained is not None:
        # Evita cadenas (X→A pendiente y A→B): las pacientes de X no llegarían a B
        raise InvalidOperationError(
            "Hay un traspaso pendiente que involucra a estas personas; acéptalo o cancélalo antes"
        )

    now = datetime.now(UTC)
    # Un traspaso nuevo de la misma médica reemplaza al pendiente
    previous = db.scalar(
        select(PatientHandover)
        .where(PatientHandover.tenant_id == source.tenant_id)
        .where(PatientHandover.from_doctor_id == source.id, *_pending())
        .with_for_update()
    )
    if previous is not None:
        previous.cancelled_at, previous.cancelled_by = now, scope.actor.user_id
        _event(db, scope, "handover.cancel", previous, ip)
        db.flush()

    handover = PatientHandover(
        tenant_id=source.tenant_id,
        from_doctor_id=source.id,
        to_doctor_id=target.id,
        created_by=scope.actor.user_id,
    )
    db.add(handover)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ConflictError("Ya hay un traspaso pendiente de esta persona") from None
    _event(db, scope, "handover.create", handover, ip)
    db.commit()
    return to_out(_Row(handover, source.full_name, target.full_name))


def list_for_tenant(db: Session, scope: Scope, tenant_id: uuid.UUID) -> list[HandoverOut]:
    _tenant_in_scope(db, scope, tenant_id)
    return [to_out(r) for r in _rows(db, PatientHandover.tenant_id == tenant_id)]


def cancel(db: Session, scope: Scope, handover_id: uuid.UUID, ip: str | None) -> HandoverOut:
    query = select(PatientHandover).where(PatientHandover.id == handover_id)
    if scope.tenant_id is not None:
        query = query.where(PatientHandover.tenant_id == scope.tenant_id)
    handover = db.scalar(query.with_for_update())
    if handover is None:
        raise NotFoundError
    if handover.accepted_at is not None or handover.cancelled_at is not None:
        raise ConflictError("El traspaso ya se aceptó o se canceló")
    handover.cancelled_at, handover.cancelled_by = datetime.now(UTC), scope.actor.user_id
    _event(db, scope, "handover.cancel", handover, ip)
    db.commit()
    (row,) = _rows(db, PatientHandover.id == handover.id)
    return to_out(row)


# --- Lado de la médica de destino (TenantDb, su propio contexto) ----------------------------


def pending_for_me(db: Session, auth: AuthContext) -> list[PendingHandoverOut]:
    rows = _rows(
        db,
        PatientHandover.tenant_id == auth.tenant_id,
        PatientHandover.to_doctor_id == auth.user_id,
        *_pending(),
    )
    return [
        PendingHandoverOut(
            id=r.handover.id, from_name=r.from_name, created_at=r.handover.created_at
        )
        for r in rows
    ]


def accept(db: Session, auth: AuthContext, handover_id: uuid.UUID, ip: str | None) -> int:
    """Pasa las fichas de la médica de origen a la del contexto. Devuelve cuántas pasaron."""
    handover = db.scalar(
        select(PatientHandover)
        .where(
            PatientHandover.id == handover_id,
            PatientHandover.tenant_id == auth.tenant_id,
            PatientHandover.to_doctor_id == auth.user_id,
            *_pending(),
        )
        .with_for_update()
    )
    if handover is None:
        # Ajeno, de otra médica, ya cerrado o inexistente: misma respuesta
        raise NotFoundError
    now = datetime.now(UTC)
    # RLS: solo ve (y solo puede dejar a su nombre) las fichas del traspaso hacia ella
    moved = db.execute(
        update(Patient)
        .where(
            Patient.tenant_id == auth.tenant_id,
            Patient.responsible_doctor_id == handover.from_doctor_id,
        )
        .values(responsible_doctor_id=auth.user_id, updated_at=now)
        .execution_options(synchronize_session=False)
    ).rowcount
    handover.accepted_at, handover.patients_moved = now, moved
    audit.record(
        db,
        tenant_id=auth.tenant_id,
        actor_id=auth.user_id,
        actor_role=auth.role,
        action="patients.handover_accept",
        resource_type="handover",
        resource_id=handover.id,
        ip=ip,
    )
    admin_events.record(
        db,
        actor_id=auth.user_id,
        actor_role="user",
        action="handover.accept",
        tenant_id=handover.tenant_id,
        target_type="user",
        target_id=handover.from_doctor_id,
        ip=ip,
        details={"to_user_id": str(handover.to_doctor_id), "patients_moved": moved},
    )
    db.commit()
    return moved
