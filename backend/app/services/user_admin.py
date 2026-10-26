"""Gestión del personal de un tenant (ADR 0008), compartida por platform_admin y tenant_admin.

El ALCANCE decide qué usuarios existen para quien pregunta:
- platform_admin: cualquier tenant (el que indica la ruta);
- tenant_admin: SOLO el tenant de su JWT; nunca uno que venga del cliente.

Siempre:
- solo personal (`doctor`, `tenant_admin`): pacientes y platform_admin no se gestionan aquí
  (un platform_admin no tiene tenant y nunca aparece; así la API no puede tocar al último);
- un usuario fuera de alcance responde igual que uno inexistente (404);
- sin contraseñas: el alta y el restablecimiento son por invitación de un solo uso;
- cada cambio va a la bitácora de plataforma en la misma transacción.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.control import Tenant, User
from backend.app.schemas.tenants import StaffInvite, StaffOut, StaffUpdate
from backend.app.services import admin_events, invitations
from backend.app.services import email as email_service
from backend.app.services.auth import AuthContext, get_user_by_email
from backend.app.services.tenants import (
    STAFF_ROLES,
    ConflictError,
    InvalidOperationError,
    NotFoundError,
)


@dataclass(frozen=True)
class Scope:
    actor: AuthContext
    # None = cualquier tenant (platform_admin); si no, el tenant del JWT del tenant_admin
    tenant_id: uuid.UUID | None

    @classmethod
    def for_actor(cls, actor: AuthContext) -> "Scope":
        if actor.role == "platform_admin":
            return cls(actor=actor, tenant_id=None)
        if actor.role == "tenant_admin" and actor.tenant_id is not None:
            return cls(actor=actor, tenant_id=actor.tenant_id)
        raise PermissionError("Rol sin permisos de administración")


def to_out(user: User) -> StaffOut:
    if user.hashed_password is None:
        status = "invited"
    else:
        status = "active" if user.is_active else "inactive"
    return StaffOut(
        id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        status=status,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


def _tenant_in_scope(db: Session, scope: Scope, tenant_id: uuid.UUID) -> Tenant:
    if scope.tenant_id is not None and tenant_id != scope.tenant_id:
        raise NotFoundError
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise NotFoundError
    return tenant


def _staff_in_scope(db: Session, scope: Scope, user_id: uuid.UUID, *, lock: bool = False):
    query = (
        select(User, Tenant)
        .join(Tenant, Tenant.id == User.tenant_id)
        .where(
            User.id == user_id,
            User.tenant_id.is_not(None),
            User.role.in_(STAFF_ROLES),
        )
    )
    if scope.tenant_id is not None:
        query = query.where(User.tenant_id == scope.tenant_id)
    if lock:
        query = query.with_for_update(of=User)
    row = db.execute(query).first()
    if row is None:
        raise NotFoundError
    return row


def _event(db: Session, scope: Scope, action: str, user: User, ip: str | None, details=None):
    admin_events.record(
        db,
        actor_id=scope.actor.user_id,
        actor_role=scope.actor.role,
        action=action,
        tenant_id=user.tenant_id,
        target_type="user",
        target_id=user.id,
        ip=ip,
        details=details,
    )


def list_staff(db: Session, scope: Scope, tenant_id: uuid.UUID) -> tuple[list[User], int]:
    """Personal del tenant y, de las pacientes, solo cuántas hay (minimización de datos)."""
    _tenant_in_scope(db, scope, tenant_id)
    staff = list(
        db.scalars(
            select(User)
            .where(User.tenant_id == tenant_id, User.role.in_(STAFF_ROLES))
            .order_by(User.role.desc(), User.full_name, User.id)
        )
    )
    patients = db.scalar(
        select(func.count())
        .select_from(User)
        .where(User.tenant_id == tenant_id, User.role == "patient")
    )
    return staff, patients


def invite_staff(
    db: Session,
    scope: Scope,
    tenant_id: uuid.UUID,
    data: StaffInvite,
    sender: email_service.EmailSender,
    ip: str | None,
) -> tuple[User, bool]:
    tenant = _tenant_in_scope(db, scope, tenant_id)
    if tenant.kind == "b2c":
        raise InvalidOperationError("El tenant b2c compartido solo admite pacientes")
    if not tenant.is_active:
        raise InvalidOperationError("El tenant está desactivado")
    if get_user_by_email(db, data.email):
        raise ConflictError("El email ya está registrado")
    try:
        user = User(
            tenant_id=tenant.id,
            email=data.email,
            hashed_password=None,
            full_name=data.full_name,
            role=data.role,
        )
        db.add(user)
        db.flush()
        token = invitations.issue(db, user, "invite", scope.actor.user_id)
        _event(db, scope, "user.invite", user, ip, {"role": data.role})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConflictError("El email ya está registrado") from None
    sent = invitations.send(
        sender, user=user, institution=tenant.name, purpose="invite", token=token
    )
    return user, sent


def _active_admins(db: Session, tenant_id: uuid.UUID) -> int:
    # Bloquea las filas de admins del tenant: dos cambios simultáneos no lo dejan sin admin
    ids = db.scalars(
        select(User.id)
        .where(
            User.tenant_id == tenant_id,
            User.role == "tenant_admin",
            User.is_active.is_(True),
        )
        .with_for_update()
    ).all()
    return len(ids)


def update_staff(
    db: Session, scope: Scope, user_id: uuid.UUID, data: StaffUpdate, ip: str | None
) -> User:
    user, _tenant = _staff_in_scope(db, scope, user_id, lock=True)
    changes = data.model_dump(exclude_unset=True)
    is_self = user.id == scope.actor.user_id
    if is_self and ("role" in changes or changes.get("is_active") is False):
        raise InvalidOperationError("No puedes cambiar tu propio rol ni desactivarte")

    loses_admin = (
        user.role == "tenant_admin"
        and user.is_active
        and (
            changes.get("is_active") is False
            or ("role" in changes and changes["role"] != "tenant_admin")
        )
    )
    if loses_admin and _active_admins(db, user.tenant_id) <= 1:
        raise InvalidOperationError("La institución debe conservar al menos un administrador")

    now = datetime.now(UTC)
    if "role" in changes and changes["role"] != user.role:
        previous = user.role
        user.role = changes["role"]
        # Un rol distinto al del JWT ya invalida la sesión (load_auth_context)
        _event(
            db, scope, "user.role_change", user, ip, {"role": user.role, "previous_role": previous}
        )
    if "is_active" in changes and changes["is_active"] != user.is_active:
        user.is_active = changes["is_active"]
        _event(db, scope, "user.activate" if user.is_active else "user.deactivate", user, ip)
    user.updated_at = now
    db.commit()
    return user


def resend_invitation(
    db: Session,
    scope: Scope,
    user_id: uuid.UUID,
    sender: email_service.EmailSender,
    ip: str | None,
) -> bool:
    user, tenant = _staff_in_scope(db, scope, user_id, lock=True)
    if user.hashed_password is not None:
        raise ConflictError("La cuenta ya está activa; usa restablecer acceso")
    if not user.is_active or not tenant.is_active:
        raise InvalidOperationError("La cuenta o la institución están desactivadas")
    token = invitations.issue(db, user, "invite", scope.actor.user_id)
    _event(db, scope, "user.invite_resend", user, ip)
    db.commit()
    return invitations.send(
        sender, user=user, institution=tenant.name, purpose="invite", token=token
    )


def reset_access(
    db: Session,
    scope: Scope,
    user_id: uuid.UUID,
    sender: email_service.EmailSender,
    ip: str | None,
) -> bool:
    """Anula la contraseña, cierra las sesiones abiertas y envía un enlace para fijar otra."""
    user, tenant = _staff_in_scope(db, scope, user_id, lock=True)
    if user.id == scope.actor.user_id:
        raise InvalidOperationError("No puedes restablecer tu propio acceso desde aquí")
    if not user.is_active or not tenant.is_active:
        raise InvalidOperationError("La cuenta o la institución están desactivadas")
    now = datetime.now(UTC)
    user.hashed_password = None
    user.sessions_valid_after = now
    user.updated_at = now
    token = invitations.issue(db, user, "reset", scope.actor.user_id)
    _event(db, scope, "user.access_reset", user, ip)
    db.commit()
    return invitations.send(
        sender, user=user, institution=tenant.name, purpose="reset", token=token
    )
