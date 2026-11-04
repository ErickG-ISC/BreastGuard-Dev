"""Avisos internos de `control.inbox_notices` (solo tipo e id; nunca datos clínicos).

Toda consulta filtra por el usuario y el tenant del JWT; el trigger de 0015 además impide
marcar como leído un aviso ajeno.
"""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.control import InboxNotice
from backend.app.services.auth import AuthContext


def _own(auth: AuthContext):
    return InboxNotice.user_id == auth.user_id, InboxNotice.tenant_id == auth.tenant_id


def list_own(db: Session, auth: AuthContext) -> list[InboxNotice]:
    return list(
        db.scalars(
            select(InboxNotice)
            .where(*_own(auth))
            .order_by(InboxNotice.read_at.is_not(None), InboxNotice.created_at.desc())
            .limit(30)
        )
    )


def mark_read(db: Session, auth: AuthContext, notice_id: uuid.UUID) -> None:
    notice = db.scalar(select(InboxNotice).where(InboxNotice.id == notice_id, *_own(auth)))
    if notice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Aviso no encontrado")
    if notice.read_at is None:
        notice.read_at = datetime.now(UTC)
        db.commit()
