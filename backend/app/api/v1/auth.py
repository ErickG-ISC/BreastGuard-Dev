from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from backend.app.api.deps import ControlDb
from backend.app.schemas.auth import Token, UserCreate, UserOut
from backend.app.services.auth import (
    EmailAlreadyRegisteredError,
    InactiveAccountError,
    RegistrationUnavailableError,
    authenticate_user,
    create_access_token,
    register_patient,
)

router = APIRouter()


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(data: UserCreate, db: ControlDb):
    """Registro público: siempre crea una paciente en el tenant B2C."""
    try:
        return register_patient(db, data)
    except EmailAlreadyRegisteredError:
        raise HTTPException(status_code=400, detail="El email ya está registrado") from None
    except RegistrationUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El registro no está disponible en este momento",
        ) from None


@router.post("/token", response_model=Token)
def login(form_data: Annotated[OAuth2PasswordRequestForm, Depends()], db: ControlDb):
    try:
        user = authenticate_user(db, form_data.username, form_data.password)
    except InactiveAccountError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La cuenta o la institución están desactivadas",
        ) from None
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_access_token(user))
