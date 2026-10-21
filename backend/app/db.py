"""Conexión de la app: un solo engine con el rol `app_user` y contexto RLS por transacción.

La app nunca usa el rol dueño (ADR 0002 y 0003). Toma de `DATABASE_URL` solo host, puerto,
base y el sufijo del usuario del pooler de Supabase; la contraseña es `APP_DB_PASSWORD`.
"""

import logging
import os
import uuid
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

TENANT_CONTEXT_KEY = "tenant_context"


class DatabaseConfigError(RuntimeError):
    """Configuración de base insegura o incompleta: la app no debe arrancar."""


@dataclass(frozen=True)
class TenantContext:
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    role: str


def app_db_user() -> str:
    return os.environ.get("APP_DB_USER", "app_user")


def app_database_url() -> URL:
    explicit = os.environ.get("APP_DATABASE_URL")
    if explicit:
        return make_url(explicit)
    owner_url = os.environ.get("DATABASE_URL")
    password = os.environ.get("APP_DB_PASSWORD")
    if not owner_url or not password:
        # Falla cerrado: nunca se cae a las credenciales del dueño
        raise DatabaseConfigError(
            "Faltan DATABASE_URL o APP_DB_PASSWORD para conectar como app_user"
        )
    owner = make_url(owner_url)
    username = owner.username or ""
    # Pooler de Supabase: el usuario es "<rol>.<ref_del_proyecto>"
    suffix = username.split(".", 1)[1] if "." in username else ""
    role = app_db_user()
    return owner.set(username=f"{role}.{suffix}" if suffix else role, password=password)


@lru_cache
def get_engine() -> Engine:
    # Pool pequeño: el plan gratuito limita las conexiones. pool_reset_on_return="rollback"
    # (default) garantiza que ningún set_config local sobreviva al devolver la conexión.
    return create_engine(
        app_database_url(),
        pool_size=3,
        max_overflow=2,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_reset_on_return="rollback",
    )


SessionFactory = sessionmaker(autoflush=False, expire_on_commit=False)


def new_session(context: TenantContext | None = None) -> Session:
    """Sesión de app_user. Con `context`, cada transacción aplica el contexto RLS."""
    session = SessionFactory(bind=get_engine())
    if context is not None:
        session.info[TENANT_CONTEXT_KEY] = context
    return session


def apply_context(connection, context: TenantContext) -> None:
    """set_config LOCAL (por transacción): compatible con el pooler en modo transacción."""
    connection.execute(
        text(
            "SELECT set_config('app.tenant_id', :tenant_id, true), "
            "set_config('app.user_id', :user_id, true), "
            "set_config('app.role', :role, true)"
        ),
        {
            "tenant_id": str(context.tenant_id),
            "user_id": str(context.user_id),
            "role": context.role,
        },
    )


@event.listens_for(SessionFactory, "after_begin")
def _apply_tenant_context(session: Session, transaction, connection) -> None:
    # Se ejecuta en CADA transacción: tras un commit, la siguiente vuelve a tener contexto
    context = session.info.get(TENANT_CONTEXT_KEY)
    if context is not None:
        apply_context(connection, context)


def set_transaction_context(session: Session, context: TenantContext) -> None:
    """Contexto solo para la transacción en curso de una sesión de control.

    Uso restringido a las altas documentadas en el ADR 0002 (registro de pacientes y alta de
    tenant), que insertan las primeras filas clínicas de un tenant.
    """
    apply_context(session.connection(), context)


def assert_safe_db_role(engine: Engine | None = None) -> None:
    """La app se niega a arrancar con un rol superusuario, BYPASSRLS o distinto del esperado."""
    engine = engine or get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT current_user AS name, rolsuper, rolbypassrls "
                "FROM pg_roles WHERE rolname = current_user"
            )
        ).one()
    if row.rolsuper or row.rolbypassrls:
        raise DatabaseConfigError(
            "La app está conectada con un rol SUPERUSER o BYPASSRLS: RLS no protegería nada"
        )
    if row.name != app_db_user():
        raise DatabaseConfigError(
            f"La app debe conectarse como {app_db_user()!r}, no como {row.name!r}"
        )
    logger.info("Conexión de base verificada: rol sin privilegios de bypass")
