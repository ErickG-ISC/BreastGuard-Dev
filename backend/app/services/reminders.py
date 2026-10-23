"""CU-05: recordatorios de la paciente, avisos en la app y despachador.

Todo vive en el esquema `control` (configuración, no datos clínicos; ADR 0007) y se usa con la
sesión de `get_control_db`: rol app_user SIN contexto de tenant, así que clinical es invisible
para estas consultas (RLS devuelve 0 filas y rechaza INSERT). Como control no tiene RLS, cada
consulta de la paciente filtra explícitamente por su user_id (del JWT): ver `_own_*`.
"""

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.app.models.control import Reminder, ReminderNotice, Tenant, User
from backend.app.schemas.reminders import ReminderIn
from backend.app.services import email as email_service
from backend.app.services.auth import AuthContext
from backend.app.services.reminder_schedule import next_run, zone
from backend.app.services.unsubscribe import InvalidUnsubscribeToken, make_token, read_token

logger = logging.getLogger(__name__)

BATCH_SIZE = 200
# Un correo 'pending' más viejo que esto quedó huérfano (el proceso murió antes de enviarlo)
STALE_AFTER = timedelta(minutes=10)


def _own_reminders(auth: AuthContext):
    """Único filtro de pertenencia para recordatorios: usuario Y tenant del JWT."""
    return (Reminder.user_id == auth.user_id) & (Reminder.tenant_id == auth.tenant_id)


def _own_notices(auth: AuthContext):
    return (ReminderNotice.user_id == auth.user_id) & (ReminderNotice.tenant_id == auth.tenant_id)


def _now() -> datetime:
    return datetime.now(UTC)


def list_reminders(db: Session, auth: AuthContext) -> list[Reminder]:
    return list(db.scalars(select(Reminder).where(_own_reminders(auth)).order_by(Reminder.kind)))


def upsert(db: Session, auth: AuthContext, kind: str, data: ReminderIn) -> Reminder:
    """Crea o reemplaza la configuración; la cadencia se cuenta desde hoy (fecha local)."""
    now = _now()
    anchor = now.astimezone(zone(data.timezone)).date()
    upcoming = next_run(
        frequency=data.frequency,
        interval_n=data.interval_n,
        local_time=data.local_time,
        tz_name=data.timezone,
        anchor=anchor,
        after=now,
    )
    values = data.model_dump() | {"anchor_date": anchor, "next_run_at": upcoming}
    # Un solo INSERT ... ON CONFLICT: dos guardados simultáneos no chocan con el UNIQUE
    db.execute(
        insert(Reminder)
        .values(tenant_id=auth.tenant_id, user_id=auth.user_id, kind=kind, **values)
        .on_conflict_do_update(
            constraint="uq_reminders_user_kind", set_=values | {"updated_at": now}
        )
    )
    db.commit()
    return db.scalars(select(Reminder).where(_own_reminders(auth), Reminder.kind == kind)).one()


def delete(db: Session, auth: AuthContext, kind: str) -> None:
    reminder = db.scalars(
        select(Reminder).where(_own_reminders(auth), Reminder.kind == kind)
    ).first()
    if reminder is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sin recordatorio")
    db.delete(reminder)
    db.commit()


def list_notices(
    db: Session, auth: AuthContext, unread_only: bool, limit: int
) -> list[ReminderNotice]:
    query = select(ReminderNotice).where(_own_notices(auth))
    if unread_only:
        query = query.where(ReminderNotice.read_at.is_(None))
    return list(
        db.scalars(query.order_by(ReminderNotice.due_at.desc(), ReminderNotice.id).limit(limit))
    )


def mark_read(db: Session, auth: AuthContext, notice_id: uuid.UUID) -> None:
    result = db.execute(
        update(ReminderNotice)
        .where(_own_notices(auth), ReminderNotice.id == notice_id)
        .values(read_at=_now())
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Aviso no encontrado")
    db.commit()


def unsubscribe(db: Session, token: str) -> None:
    """Quita el correo del recordatorio del token. El aviso en la app se conserva."""
    try:
        reminder_id, user_id = read_token(token)
    except InvalidUnsubscribeToken:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Enlace no válido o vencido"
        ) from None
    reminder = db.scalars(
        select(Reminder)
        .where(Reminder.id == reminder_id, Reminder.user_id == user_id)
        .with_for_update()
    ).first()
    # Mismo resultado si ya no existe: no revela nada a quien tenga un enlace viejo
    if reminder is not None and "email" in reminder.channels:
        reminder.channels = [c for c in reminder.channels if c != "email"] or ["in_app"]
        reminder.updated_at = _now()
    db.commit()


# --- Despachador -------------------------------------------------------------------------


@dataclass
class _Outgoing:
    notice_id: uuid.UUID
    reminder_id: uuid.UUID
    user_id: uuid.UUID
    email: str
    kind: str
    discreet: bool


@dataclass(frozen=True)
class DispatchResult:
    claimed: int
    emailed: int
    failed: int


def _unsubscribe_url(reminder_id: uuid.UUID, user_id: uuid.UUID) -> str:
    base = os.environ.get("PUBLIC_APP_URL", "http://localhost:5173").rstrip("/")
    return f"{base}/baja?token={make_token(reminder_id, user_id)}"


def _stale_pending(db: Session, now: datetime) -> list[_Outgoing]:
    """Correos que quedaron en 'pending' porque el proceso murió entre el reclamo y el envío.

    Se reintentan una vez en un despacho posterior (pasados STALE_AFTER) y terminan en 'sent' o
    'failed'. Solo si el recordatorio todavía pide correo (la paciente pudo darse de baja).
    """
    rows = db.execute(
        select(ReminderNotice, Reminder, User.email)
        .join(Reminder, Reminder.id == ReminderNotice.reminder_id)
        .join(User, (User.id == Reminder.user_id) & (User.tenant_id == Reminder.tenant_id))
        .join(Tenant, Tenant.id == Reminder.tenant_id)
        .where(
            ReminderNotice.email_status == "pending",
            ReminderNotice.created_at < now - STALE_AFTER,
            Reminder.channels.contains(["email"]),
            User.is_active.is_(True),
            Tenant.is_active.is_(True),
        )
        .order_by(ReminderNotice.created_at)
        .limit(BATCH_SIZE)
        .with_for_update(of=ReminderNotice, skip_locked=True)
    ).all()
    return [
        _Outgoing(
            notice_id=notice.id,
            reminder_id=reminder.id,
            user_id=reminder.user_id,
            email=address,
            kind=notice.kind,
            discreet=reminder.discreet,
        )
        for notice, reminder, address in rows
    ]


def _claim(db: Session, now: datetime) -> tuple[int, list[_Outgoing]]:
    """Reclama los vencidos, crea sus avisos y reprograma, en UNA transacción.

    FOR UPDATE SKIP LOCKED: dos despachos simultáneos nunca toman el mismo recordatorio, y al
    terminar ya no está vencido (next_run_at avanzó). El UNIQUE (reminder_id, due_at) es la
    segunda barrera contra avisos duplicados.
    """
    rows = db.execute(
        select(Reminder, User.email)
        .join(User, (User.id == Reminder.user_id) & (User.tenant_id == Reminder.tenant_id))
        .join(Tenant, Tenant.id == Reminder.tenant_id)
        .where(
            Reminder.active.is_(True),
            Reminder.next_run_at <= now,
            User.is_active.is_(True),
            Tenant.is_active.is_(True),
        )
        .order_by(Reminder.next_run_at)
        .limit(BATCH_SIZE)
        .with_for_update(of=Reminder, skip_locked=True)
    ).all()

    outgoing: list[_Outgoing] = []
    for reminder, address in rows:
        wants_email = "email" in reminder.channels
        notice_id = db.scalar(
            insert(ReminderNotice)
            .values(
                tenant_id=reminder.tenant_id,
                user_id=reminder.user_id,
                reminder_id=reminder.id,
                kind=reminder.kind,
                due_at=reminder.next_run_at,
                email_status="pending" if wants_email else "none",
            )
            .on_conflict_do_nothing(constraint="uq_reminder_notices_due")
            .returning(ReminderNotice.id)
        )
        # Si estuvo dormido, la siguiente se calcula desde ahora: sin ráfagas de atrasados
        reminder.next_run_at = next_run(
            frequency=reminder.frequency,
            interval_n=reminder.interval_n,
            local_time=reminder.local_time,
            tz_name=reminder.timezone,
            anchor=reminder.anchor_date,
            after=max(now, reminder.next_run_at),
        )
        reminder.last_run_at = now
        if notice_id is not None and wants_email:
            outgoing.append(
                _Outgoing(
                    notice_id=notice_id,
                    reminder_id=reminder.id,
                    user_id=reminder.user_id,
                    email=address,
                    kind=reminder.kind,
                    discreet=reminder.discreet,
                )
            )
    outgoing.extend(_stale_pending(db, now))
    db.commit()
    return len(rows), outgoing


def dispatch(
    db: Session, sender: email_service.EmailSender, now: datetime | None = None
) -> DispatchResult:
    """Un ciclo del despachador. Un correo que falla no detiene a los demás."""
    now = now or _now()
    claimed, outgoing = _claim(db, now)

    sent, failed = [], []
    for item in outgoing:
        message = email_service.compose(
            to=item.email,
            kind=item.kind,
            discreet=item.discreet,
            unsubscribe_url=_unsubscribe_url(item.reminder_id, item.user_id),
        )
        try:
            sender.send(message)
            sent.append(item.notice_id)
        except Exception as exc:  # cualquier fallo del proveedor: se registra y se sigue
            logger.warning("No se pudo enviar el aviso %s (%s)", item.notice_id, type(exc).__name__)
            failed.append(item.notice_id)

    for ids, value in ((sent, "sent"), (failed, "failed")):
        if ids:
            db.execute(
                update(ReminderNotice)
                .where(ReminderNotice.id.in_(ids))
                .values(email_status=value)
                .execution_options(synchronize_session=False)
            )
    db.commit()
    return DispatchResult(claimed=claimed, emailed=len(sent), failed=len(failed))
