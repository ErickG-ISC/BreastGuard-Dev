"""Corre un ciclo del despachador de recordatorios (CU-05) desde la terminal.

Uso, desde la raíz del repo:
    python -m backend.scripts.dispatch_reminders

Hace lo mismo que `POST /api/v1/internal/reminders/dispatch` (el que llama el workflow
programado), sin necesitar el secreto. Se conecta como app_user SIN contexto de tenant: solo
toca el esquema control. Con EMAIL_BACKEND=console los correos solo se registran en el log.
"""

import logging
import sys

from dotenv import load_dotenv

load_dotenv()

from backend.app.db import new_session  # noqa: E402
from backend.app.services import email as email_service  # noqa: E402
from backend.app.services import reminders  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with new_session() as db:
        result = reminders.dispatch(db, email_service.get_sender())
    print(f"Reclamados: {result.claimed} · correos: {result.emailed} · fallidos: {result.failed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
