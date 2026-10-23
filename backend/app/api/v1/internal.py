"""Endpoints internos para tareas programadas (no los usa el frontend).

`POST /internal/reminders/dispatch` lo llama el workflow programado de GitHub Actions con el
header `X-Cron-Secret`. Sin REMINDER_CRON_SECRET configurado responde 503 (falla cerrado).
Corre con la sesión de control (app_user sin contexto): nunca ve datos clínicos (ADR 0007).
"""

import hmac
import os
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status

from backend.app.api.deps import ControlDb
from backend.app.api.rate_limit import rate_limit
from backend.app.schemas.reminders import DispatchOut
from backend.app.services import email as email_service
from backend.app.services import reminders

router = APIRouter()

MIN_SECRET_LENGTH = 32


def require_cron_secret(x_cron_secret: Annotated[str | None, Header()] = None) -> None:
    expected = os.environ.get("REMINDER_CRON_SECRET", "")
    if len(expected) < MIN_SECRET_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Despachador desactivado"
        )
    if not x_cron_secret or not hmac.compare_digest(
        x_cron_secret.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autorizado")


def get_email_sender() -> email_service.EmailSender:
    """Punto de override en pruebas."""
    return email_service.get_sender()


@router.post(
    "/internal/reminders/dispatch",
    response_model=DispatchOut,
    dependencies=[
        Depends(rate_limit("reminders_dispatch", 6, 60)),
        Depends(require_cron_secret),
    ],
)
def dispatch_reminders(
    db: ControlDb,
    sender: Annotated[email_service.EmailSender, Depends(get_email_sender)],
):
    result = reminders.dispatch(db, sender)
    return DispatchOut(claimed=result.claimed, emailed=result.emailed, failed=result.failed)
