"""Invitaciones y restablecimiento de acceso de un solo uso (ADR 0008).

- Nadie envía ni ve contraseñas: la persona invitada elige la suya con un enlace.
- El token (`secrets.token_urlsafe(32)`) solo existe en el enlace; en la base se guarda su
  sha256. Emitir uno nuevo revoca los anteriores del mismo usuario.
- El enlace usa `#token=` (fragmento): no viaja al servidor ni queda en logs ni en el Referer.
- Aceptar es un UPDATE condicional (`used_at IS NULL AND revoked_at IS NULL AND expires_at >
  now()`): de un solo uso aunque lleguen dos peticiones a la vez.
"""

import hashlib
import logging
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from backend.app.models.control import Invitation, Tenant, User
from backend.app.services import admin_events
from backend.app.services import email as email_service
from backend.app.services.auth import get_password_hash

logger = logging.getLogger(__name__)

TTL = {"invite": timedelta(hours=48), "reset": timedelta(hours=2)}


class InvalidInvitationError(Exception):
    """Token inexistente, usado, revocado o vencido (mismo error para no revelar cuál)."""


@dataclass(frozen=True)
class InvitationInfo:
    email_masked: str
    full_name: str
    institution: str
    purpose: str


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def issue(db: Session, user: User, purpose: str, created_by: uuid.UUID | None) -> str:
    """Crea una invitación (sin commit) y devuelve el token en claro, que solo va al correo."""
    if user.tenant_id is None:
        raise ValueError("Los platform_admin no se invitan por la app")
    now = _now()
    db.execute(
        update(Invitation)
        .where(
            Invitation.user_id == user.id,
            Invitation.used_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .values(revoked_at=now)
        .execution_options(synchronize_session=False)
    )
    token = secrets.token_urlsafe(32)
    db.add(
        Invitation(
            tenant_id=user.tenant_id,
            user_id=user.id,
            purpose=purpose,
            token_hash=_hash(token),
            expires_at=now + TTL[purpose],
            created_by=created_by,
        )
    )
    db.flush()
    return token


def invitation_url(token: str) -> str:
    base = os.environ.get("PUBLIC_APP_URL", "http://localhost:5173").rstrip("/")
    return f"{base}/invitacion#token={token}"


def send(
    sender: email_service.EmailSender,
    *,
    user: User,
    institution: str,
    purpose: str,
    token: str,
) -> bool:
    """Envía el correo DESPUÉS del commit. Si falla, la invitación queda y se puede reenviar."""
    message = email_service.compose_invitation(
        to=user.email,
        name=user.full_name,
        institution=institution,
        purpose=purpose,
        url=invitation_url(token),
        hours=int(TTL[purpose].total_seconds() // 3600),
    )
    try:
        sender.send(message)
        return True
    except Exception as exc:  # cualquier fallo del proveedor: no deshace la invitación
        logger.warning("No se pudo enviar la invitación (%s)", type(exc).__name__)
        return False


def _open_invitation(token: str):
    return (
        Invitation.token_hash == _hash(token),
        Invitation.used_at.is_(None),
        Invitation.revoked_at.is_(None),
        Invitation.expires_at > func.now(),
    )


def inspect(db: Session, token: str) -> InvitationInfo:
    row = db.execute(
        select(Invitation, User, Tenant)
        .join(User, (User.id == Invitation.user_id) & (User.tenant_id == Invitation.tenant_id))
        .join(Tenant, Tenant.id == Invitation.tenant_id)
        .where(*_open_invitation(token), User.is_active.is_(True), Tenant.is_active.is_(True))
    ).first()
    if row is None:
        raise InvalidInvitationError
    invitation, user, tenant = row
    return InvitationInfo(
        email_masked=email_service.mask(user.email),
        full_name=user.full_name,
        institution=tenant.name,
        purpose=invitation.purpose,
    )


def accept(db: Session, token: str, password: str, ip: str | None) -> None:
    """Marca la invitación usada y fija la contraseña, en una transacción."""
    claimed = db.execute(
        update(Invitation)
        .where(*_open_invitation(token))
        .values(used_at=func.now())
        .returning(Invitation.user_id, Invitation.tenant_id, Invitation.purpose)
        .execution_options(synchronize_session=False)
    ).first()
    if claimed is None:
        db.rollback()
        raise InvalidInvitationError
    user = db.scalars(
        select(User).where(User.id == claimed.user_id, User.tenant_id == claimed.tenant_id)
    ).first()
    tenant = db.get(Tenant, claimed.tenant_id)
    if user is None or not user.is_active or tenant is None or not tenant.is_active:
        db.rollback()
        raise InvalidInvitationError
    now = _now()
    user.hashed_password = get_password_hash(password)
    user.updated_at = now
    # Cualquier sesión anterior (p. ej. antes de un restablecimiento) deja de valer
    user.sessions_valid_after = now
    admin_events.record(
        db,
        actor_id=user.id,
        actor_role="user",
        action="user.invite_accept",
        tenant_id=user.tenant_id,
        target_type="user",
        target_id=user.id,
        ip=ip,
        details={"purpose": claimed.purpose},
    )
    db.commit()
