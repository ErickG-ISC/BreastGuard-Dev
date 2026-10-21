"""Administración de plataforma (CU-12): tenants y usuarios en el esquema control.

Solo lo usa el platform_admin. Las únicas escrituras en clinical son los registros de
auditoría de cada alta, con el contexto del tenant afectado aplicado solo a esa transacción
(ADR 0002). El chequeo de aislamiento es de solo lectura y siempre termina en rollback.
"""

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db import TenantContext, apply_context, new_session, set_transaction_context
from backend.app.models.control import Tenant, User
from backend.app.schemas.tenants import IsolationReport, TenantCreate, TenantUserCreate
from backend.app.services import audit
from backend.app.services.auth import AuthContext, get_password_hash, get_user_by_email

_TABLE_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


class ConflictError(Exception):
    """Slug o email ya en uso."""


class NotFoundError(Exception):
    pass


class InvalidOperationError(Exception):
    pass


def _audit_in_tenant(
    db: Session,
    actor: AuthContext,
    tenant_id: uuid.UUID,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID,
    ip: str | None,
) -> None:
    """Registra una acción del platform_admin en la auditoría DEL tenant afectado."""
    set_transaction_context(db, TenantContext(tenant_id, actor.user_id, actor.role))
    audit.record(
        db,
        tenant_id=tenant_id,
        actor_id=actor.user_id,
        actor_role=actor.role,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip=ip,
    )


def create_tenant(
    db: Session, actor: AuthContext, data: TenantCreate, ip: str | None
) -> tuple[Tenant, User]:
    """Tenant + slug + primer tenant_admin + auditoría en UNA transacción: todo o nada."""
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
            hashed_password=get_password_hash(data.admin_password),
            full_name=data.admin_full_name,
            role="tenant_admin",
        )
        db.add(admin)
        db.flush()
        _audit_in_tenant(db, actor, tenant.id, "tenant.create", "tenant", tenant.id, ip)
        _audit_in_tenant(db, actor, tenant.id, "user.create", "user", admin.id, ip)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConflictError("El slug o el email ya están en uso") from None
    except Exception:
        db.rollback()
        raise
    return tenant, admin


def list_tenants(db: Session) -> list[Tenant]:
    return list(db.scalars(select(Tenant).order_by(Tenant.created_at)))


def set_tenant_active(
    db: Session, actor: AuthContext, tenant_id: uuid.UUID, active: bool, ip: str | None
) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise NotFoundError
    if tenant.kind == "b2c" and not active:
        # Bloquearía a todas las pacientes y el registro público
        raise InvalidOperationError("El tenant b2c no se desactiva desde la API")
    tenant.is_active = active
    db.flush()
    action = "tenant.activate" if active else "tenant.deactivate"
    _audit_in_tenant(db, actor, tenant.id, action, "tenant", tenant.id, ip)
    db.commit()
    return tenant


def create_tenant_user(
    db: Session, actor: AuthContext, tenant_id: uuid.UUID, data: TenantUserCreate, ip: str | None
) -> User:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise NotFoundError
    if tenant.kind == "b2c":
        raise InvalidOperationError("El tenant b2c solo admite pacientes (registro público)")
    if get_user_by_email(db, data.email):
        raise ConflictError("El email ya está registrado")
    try:
        user = User(
            tenant_id=tenant.id,
            email=data.email,
            hashed_password=get_password_hash(data.password),
            full_name=data.full_name,
            role=data.role,
        )
        db.add(user)
        db.flush()
        _audit_in_tenant(db, actor, tenant.id, "user.create", "user", user.id, ip)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConflictError("El email ya está registrado") from None
    return user


def set_user_active(
    db: Session, actor: AuthContext, user_id: uuid.UUID, active: bool, ip: str | None
) -> User:
    user = db.get(User, user_id)
    if user is None or user.tenant_id is None:
        # Los platform_admin no se gestionan por API
        raise NotFoundError
    user.is_active = active
    user.updated_at = datetime.now(UTC)
    db.flush()
    action = "user.activate" if active else "user.deactivate"
    _audit_in_tenant(db, actor, user.tenant_id, action, "user", user.id, ip)
    db.commit()
    return user


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
