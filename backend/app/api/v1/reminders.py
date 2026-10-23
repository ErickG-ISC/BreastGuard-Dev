"""CU-05: configuración de recordatorios y avisos en la app (solo pacientes) y baja por correo.

Usa ControlDb (sin contexto de tenant): los recordatorios son configuración en `control`. La
pertenencia la garantiza el servicio filtrando por el user_id y el tenant_id del JWT.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from backend.app.api.deps import ControlDb, require_role
from backend.app.api.rate_limit import rate_limit
from backend.app.schemas.reminders import Kind, NoticeOut, ReminderIn, ReminderOut, UnsubscribeIn
from backend.app.services import reminders
from backend.app.services.auth import AuthContext

router = APIRouter()

PatientUser = Annotated[AuthContext, Depends(require_role("patient"))]
READ_LIMIT = Depends(rate_limit("reminders_read", 60, 60))
WRITE_LIMIT = Depends(rate_limit("reminders_write", 30, 60))


@router.get("/reminders", response_model=list[ReminderOut], dependencies=[READ_LIMIT])
def list_reminders(auth: PatientUser, db: ControlDb):
    return reminders.list_reminders(db, auth)


@router.put("/reminders/{kind}", response_model=ReminderOut, dependencies=[WRITE_LIMIT])
def save_reminder(kind: Kind, data: ReminderIn, auth: PatientUser, db: ControlDb):
    return reminders.upsert(db, auth, kind, data)


@router.delete(
    "/reminders/{kind}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[WRITE_LIMIT]
)
def delete_reminder(kind: Kind, auth: PatientUser, db: ControlDb):
    reminders.delete(db, auth, kind)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/reminders/unsubscribe",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit("reminders_unsubscribe", 10, 60))],
)
def unsubscribe(data: UnsubscribeIn, db: ControlDb):
    """Público: el enlace del correo lleva un token firmado (sin iniciar sesión)."""
    reminders.unsubscribe(db, data.token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/notices", response_model=list[NoticeOut], dependencies=[READ_LIMIT])
def list_notices(
    auth: PatientUser,
    db: ControlDb,
    unread: bool = False,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
):
    return reminders.list_notices(db, auth, unread, limit)


@router.post(
    "/notices/{notice_id}/read", status_code=status.HTTP_204_NO_CONTENT, dependencies=[WRITE_LIMIT]
)
def mark_notice_read(notice_id: uuid.UUID, auth: PatientUser, db: ControlDb):
    reminders.mark_read(db, auth, notice_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
