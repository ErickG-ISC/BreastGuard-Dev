"""Dependencias compartidas por todos los routers."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from backend.app.models.database import SessionLocal
from backend.app.models.user import User
from backend.app.services.auth import InvalidTokenError, decode_access_token
from backend.app.services.storage import SupabaseStorage

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


def get_db() -> Iterator[Session]:
    """Única fuente de sesiones de base de datos para los endpoints.

    En la Semana 1 se convierte en `get_tenant_db`: leerá el tenant del JWT verificado y
    entregará una sesión del engine de ese tenant. Ningún router debe crear sesiones por su
    cuenta.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(token: Annotated[str, Depends(oauth2_scheme)], db: DbSession) -> User:
    """Devuelve el usuario dueño del JWT. El usuario sale solo del token, nunca del cliente."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        user_id = decode_access_token(token)
    except InvalidTokenError:
        raise credentials_exception from None
    user = db.get(User, user_id)
    if user is None:
        raise credentials_exception
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_storage() -> SupabaseStorage:
    """Servicio de Storage; las pruebas lo reemplazan con un doble en memoria."""
    return SupabaseStorage()


Storage = Annotated[SupabaseStorage, Depends(get_storage)]
