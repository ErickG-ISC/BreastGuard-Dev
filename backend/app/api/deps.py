"""Dependencias compartidas: sesiones (control / tenant), usuario autenticado, roles y Storage."""

from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from backend.app.db import TenantContext, new_session
from backend.app.services.auth import (
    AuthContext,
    InvalidTokenError,
    decode_access_token,
    load_auth_context,
)
from backend.app.services.storage import SupabaseStorage

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


def get_control_db() -> Iterator[Session]:
    """Sesión SIN contexto de tenant: solo para el esquema control (login, registro, admin).

    Las tablas de clinical devuelven 0 filas con esta sesión (RLS falla cerrado).
    """
    db = new_session()
    try:
        yield db
    finally:
        db.close()


ControlDb = Annotated[Session, Depends(get_control_db)]


def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> AuthContext:
    """Usuario del JWT verificado y releído en control. Nada sale del cliente."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        claims = decode_access_token(token)
    except InvalidTokenError:
        raise credentials_exception from None
    # Sesión corta: no retiene una conexión del pool durante toda la petición
    with new_session() as db:
        auth = load_auth_context(db, claims)
    if auth is None:
        raise credentials_exception
    return auth


CurrentUser = Annotated[AuthContext, Depends(get_current_user)]


def get_tenant_db(auth: CurrentUser) -> Iterator[Session]:
    """Sesión clínica: cada transacción aplica tenant_id, user_id y role del JWT verificado."""
    if auth.tenant_id is None:
        # platform_admin: control-only, sin acceso a datos clínicos (ADR 0003)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Sin acceso a datos clínicos"
        )
    db = new_session(TenantContext(auth.tenant_id, auth.user_id, auth.role))
    try:
        yield db
    finally:
        db.close()


TenantDb = Annotated[Session, Depends(get_tenant_db)]


def require_role(*roles: str) -> Callable[[AuthContext], AuthContext]:
    def checker(auth: CurrentUser) -> AuthContext:
        if auth.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para esta acción"
            )
        return auth

    return checker


def get_storage() -> SupabaseStorage:
    """Servicio de Storage; las pruebas lo reemplazan con un doble en memoria."""
    return SupabaseStorage()


Storage = Annotated[SupabaseStorage, Depends(get_storage)]
