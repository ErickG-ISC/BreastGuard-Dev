"""Administración de plataforma (CU-12, ADR 0008): tenants en el esquema control.

Solo lo usa el platform_admin, que NO tiene acceso a datos clínicos: las estadísticas son de
control (personal, invitaciones, pacientes como conteo, último acceso). Cada cambio queda en la
bitácora de plataforma (control.admin_events) en la misma transacción.

La única escritura en clinical es el registro `tenant.create` en la auditoría del tenant nuevo,
con su contexto aplicado solo a esa transacción: es la fila testigo del chequeo de aislamiento.
La purga NO se ejecuta aquí: la UI la solicita y la hace purge_tenant.py con el rol dueño.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import case, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db import TenantContext, apply_context, new_session, set_transaction_context
from backend.app.models.control import Tenant, User
from backend.app.schemas.tenants import (
    IsolationReport,
    TenantCreate,
    TenantStats,
    TenantUpdate,
)
from backend.app.services import admin_events, audit, invitations
from backend.app.services.auth import AuthContext, get_password_hash, get_user_by_email

_TABLE_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")
STAFF_ROLES = ("doctor", "tenant_admin")


class ConflictError(Exception):
    """Slug o email ya en uso, o estado incompatible."""


class NotFoundError(Exception):
    pass


class InvalidOperationError(Exception):
    pass


@dataclass(frozen=True)
class TenantWithStats:
    tenant: Tenant
    stats: TenantStats


def _event(
    db: Session,
    actor: AuthContext,
    action: str,
    tenant_id: uuid.UUID,
    target_type: str,
    target_id: uuid.UUID,
    ip: str | None,
    details: dict | None = None,
) -> None:
    admin_events.record(
        db,
        actor_id=actor.user_id,
        actor_role=actor.role,
        action=action,
        tenant_id=tenant_id,
        target_type=target_type,
        target_id=target_id,
        ip=ip,
        details=details,
    )


def create_tenant(
    db: Session, actor: AuthContext, data: TenantCreate, ip: str | None
) -> tuple[Tenant, User, str]:
    """Tenant + primer tenant_admin INVITADO + bitácora + auditoría, en UNA transacción.

    Devuelve el token de invitación en claro para enviarlo DESPUÉS del commit.
    """
    if db.scalars(select(Tenant.id).where(Tenant.slug == data.slug)).first():
        raise ConflictError("El slug ya está en uso")
    if get_user_by_email(db, data.admin_email):
        raise ConflictError("El email del administrador ya está registrado")
    try:
        tenant = Tenant(slug=data.slug, name=data.name, kind="institucion", plan=data.plan)
        db.add(tenant)
        db.flush()
        admin = User(
            tenant_id=tenant.id,
            email=data.admin_email,
            hashed_password=None,
            full_name=data.admin_full_name,
            role="tenant_admin",
        )
        db.add(admin)
        db.flush()
        token = invitations.issue(db, admin, "invite", actor.user_id)
        _event(db, actor, "tenant.create", tenant.id, "tenant", tenant.id, ip, {"plan": data.plan})
        _event(db, actor, "user.invite", tenant.id, "user", admin.id, ip, {"role": "tenant_admin"})
        # Fila testigo del chequeo de aislamiento, en la auditoría DEL tenant nuevo
        set_transaction_context(db, TenantContext(tenant.id, actor.user_id, actor.role))
        audit.record(
            db,
            tenant_id=tenant.id,
            actor_id=actor.user_id,
            actor_role=actor.role,
            action="tenant.create",
            resource_type="tenant",
            resource_id=tenant.id,
            ip=ip,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConflictError("El slug o el email ya están en uso") from None
    except Exception:
        db.rollback()
        raise
    return tenant, admin, token


def _stats_subquery():
    staff = User.role.in_(STAFF_ROLES)
    return (
        select(
            User.tenant_id.label("tenant_id"),
            func.count().filter(staff).label("staff"),
            func.count()
            .filter(staff, User.is_active.is_(True), User.hashed_password.is_not(None))
            .label("staff_active"),
            func.count().filter(staff, User.hashed_password.is_(None)).label("pending"),
            func.count().filter(User.role == "patient").label("patients"),
            func.max(User.last_login_at).label("last_login_at"),
        )
        .where(User.tenant_id.is_not(None))
        .group_by(User.tenant_id)
        .subquery()
    )


def _with_stats(rows) -> list[TenantWithStats]:
    return [
        TenantWithStats(
            tenant=tenant,
            stats=TenantStats(
                staff=staff or 0,
                staff_active=staff_active or 0,
                invitations_pending=pending or 0,
                patients=patients or 0,
                last_login_at=last_login_at,
            ),
        )
        for tenant, staff, staff_active, pending, patients, last_login_at in rows
    ]


def _select_with_stats():
    stats = _stats_subquery()
    return select(
        Tenant,
        stats.c.staff,
        stats.c.staff_active,
        stats.c.pending,
        stats.c.patients,
        stats.c.last_login_at,
    ).outerjoin(stats, stats.c.tenant_id == Tenant.id)


def list_tenants(
    db: Session, *, q: str | None, active: bool | None, limit: int, offset: int
) -> tuple[list[TenantWithStats], int]:
    conditions = []
    if q:
        pattern = f"%{q.strip().lower()}%"
        conditions.append(or_(func.lower(Tenant.name).like(pattern), Tenant.slug.like(pattern)))
    if active is not None:
        conditions.append(Tenant.is_active.is_(active))
    total = db.scalar(select(func.count()).select_from(Tenant).where(*conditions))
    rows = db.execute(
        _select_with_stats()
        .where(*conditions)
        # El b2c compartido primero; luego por fecha de alta
        .order_by(case((Tenant.kind == "b2c", 0), else_=1), Tenant.created_at, Tenant.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return _with_stats(rows), total


def get_tenant(db: Session, tenant_id: uuid.UUID) -> TenantWithStats:
    rows = db.execute(_select_with_stats().where(Tenant.id == tenant_id)).all()
    if not rows:
        raise NotFoundError
    return _with_stats(rows)[0]


def update_tenant(
    db: Session, actor: AuthContext, tenant_id: uuid.UUID, data: TenantUpdate, ip: str | None
) -> TenantWithStats:
    tenant = db.scalars(select(Tenant).where(Tenant.id == tenant_id).with_for_update()).first()
    if tenant is None:
        raise NotFoundError
    changes = data.model_dump(exclude_unset=True)
    if changes.get("is_active") is False and tenant.kind == "b2c":
        # Bloquearía a todas las pacientes y el registro público
        raise InvalidOperationError("El tenant b2c compartido no se desactiva")
    if changes.get("is_active") is True and tenant.purge_requested_at is not None:
        raise InvalidOperationError("Cancela primero la purga solicitada")
    fields = sorted(
        k for k in ("name", "plan") if k in changes and changes[k] != getattr(tenant, k)
    )
    for name in fields:
        setattr(tenant, name, changes[name])
    if fields:
        details = {"fields": fields} | ({"plan": changes["plan"]} if "plan" in fields else {})
        _event(db, actor, "tenant.update", tenant.id, "tenant", tenant.id, ip, details)
    if "is_active" in changes and changes["is_active"] != tenant.is_active:
        tenant.is_active = changes["is_active"]
        if not tenant.is_active:
            # Al reactivar, los JWT de antes de la desactivación no deben revivir
            tenant.sessions_valid_after = datetime.now(UTC)
        action = "tenant.activate" if tenant.is_active else "tenant.deactivate"
        _event(db, actor, action, tenant.id, "tenant", tenant.id, ip)
    db.commit()
    return get_tenant(db, tenant_id)


def request_purge(
    db: Session, actor: AuthContext, tenant_id: uuid.UUID, confirm_slug: str, ip: str | None
) -> TenantWithStats:
    """Desactiva y marca el tenant; el borrado lo hace purge_tenant.py --pending (rol dueño)."""
    tenant = db.scalars(select(Tenant).where(Tenant.id == tenant_id).with_for_update()).first()
    if tenant is None:
        raise NotFoundError
    if tenant.kind == "b2c":
        raise InvalidOperationError("El tenant b2c compartido no se purga")
    if confirm_slug.strip() != tenant.slug:
        raise InvalidOperationError("El identificador escrito no coincide")
    if tenant.purge_requested_at is not None:
        raise ConflictError("La purga ya está solicitada")
    tenant.is_active = False
    tenant.sessions_valid_after = datetime.now(UTC)
    tenant.purge_requested_at = datetime.now(UTC)
    tenant.purge_requested_by = actor.user_id
    _event(db, actor, "tenant.purge_request", tenant.id, "tenant", tenant.id, ip)
    db.commit()
    return get_tenant(db, tenant_id)


def cancel_purge(
    db: Session, actor: AuthContext, tenant_id: uuid.UUID, ip: str | None
) -> TenantWithStats:
    tenant = db.scalars(select(Tenant).where(Tenant.id == tenant_id).with_for_update()).first()
    if tenant is None:
        raise NotFoundError
    if tenant.purge_requested_at is None:
        raise ConflictError("No hay purga solicitada")
    # El tenant sigue inactivo: reactivarlo es una decisión aparte
    tenant.purge_requested_at = None
    tenant.purge_requested_by = None
    _event(db, actor, "tenant.purge_cancel", tenant.id, "tenant", tenant.id, ip)
    db.commit()
    return get_tenant(db, tenant_id)


def create_platform_admin(db: Session, email: str, full_name: str, password: str) -> User:
    """Solo para backend/scripts/create_platform_admin.py."""
    if get_user_by_email(db, email):
        raise ConflictError("El email ya está registrado")
    user = User(
        tenant_id=None,
        email=email,
        hashed_password=get_password_hash(password),
        full_name=full_name,
        role="platform_admin",
    )
    db.add(user)
    db.commit()
    return user


def _clinical_tables(db: Session) -> list[str]:
    names = db.scalars(
        text(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'clinical' AND c.relkind IN ('r', 'p') ORDER BY c.relname"
        )
    ).all()
    for name in names:
        if not _TABLE_NAME.match(name):
            raise RuntimeError("Nombre de tabla inesperado en clinical")
    return list(names)


def _count(db: Session, table: str, where: str, **params) -> int:
    return db.execute(
        text(f"SELECT count(*) FROM clinical.{table} WHERE {where}"), params
    ).scalar_one()


def isolation_check(actor: AuthContext, tenant_id: uuid.UUID) -> IsolationReport:
    """Demuestra, conectado como app_user, que el tenant no ve filas ajenas y nadie ve las suyas.

    Transacción READ ONLY que siempre termina en rollback; devuelve solo conteos. Como fila
    testigo usa la auditoría del alta del tenant (existe al menos `tenant.create`).
    """
    with new_session() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        try:
            tenant = db.get(Tenant, tenant_id)
            if tenant is None:
                raise NotFoundError
            slug = tenant.slug  # el rollback final expira los objetos
            role = db.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            ).one()
            tables = _clinical_tables(db)
            others = db.scalars(select(Tenant.id).where(Tenant.id != tenant_id)).all()
            conn = db.connection()

            without_context = sum(_count(db, t, "true") for t in tables)

            # Contexto del tenant revisado (como tenant_admin, que también ve la auditoría)
            apply_context(conn, TenantContext(tenant_id, actor.user_id, "tenant_admin"))
            foreign = sum(_count(db, t, "tenant_id <> :t", t=tenant_id) for t in tables)
            witness = sum(_count(db, t, "tenant_id = :t", t=tenant_id) for t in tables)

            seen_by_others = 0
            for other_id in others:
                apply_context(conn, TenantContext(other_id, actor.user_id, "tenant_admin"))
                seen_by_others += sum(_count(db, t, "tenant_id = :t", t=tenant_id) for t in tables)
        finally:
            db.rollback()

    safe_role = not (role.rolsuper or role.rolbypassrls)
    conclusive = witness > 0 and bool(tables) and len(others) > 0
    return IsolationReport(
        tenant_slug=slug,
        app_role_without_bypass=safe_role,
        rows_visible_without_context=without_context,
        foreign_rows_visible_to_tenant=foreign,
        tenant_rows_visible_to_others=seen_by_others,
        tenant_has_witness_rows=witness > 0,
        other_tenants_checked=len(others),
        tables_checked=tables,
        conclusive=conclusive,
        passed=(
            conclusive
            and safe_role
            and without_context == 0
            and foreign == 0
            and seen_by_others == 0
        ),
    )
