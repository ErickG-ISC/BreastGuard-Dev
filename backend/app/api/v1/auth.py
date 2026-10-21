from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from backend.app.api.deps import ControlDb, CurrentUser
from backend.app.api.rate_limit import rate_limit
from backend.app.schemas.auth import MeOut, Token, UserCreate, UserOut
from backend.app.services.auth import (
    EmailAlreadyRegisteredError,
    InactiveAccountError,
    RegistrationUnavailableError,
    authenticate_user,
    create_access_token,
    register_patient,
)

router = APIRouter()


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("auth_register", 5, 60))],
)
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


@router.post(
    "/token",
    response_model=Token,
    dependencies=[Depends(rate_limit("auth_token", 10, 60))],
)
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


@router.get("/me", response_model=MeOut)
def me(auth: CurrentUser):
    return MeOut(
        user_id=auth.user_id, tenant_id=auth.tenant_id, tenant_slug=auth.tenant_slug, role=auth.role
    )
