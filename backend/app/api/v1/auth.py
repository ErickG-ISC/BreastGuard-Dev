from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import update

from backend.app.api.client_ip import client_ip
from backend.app.api.deps import ControlDb, CurrentUser
from backend.app.api.rate_limit import rate_limit
from backend.app.models.control import User
from backend.app.schemas.auth import MeOut, Token, UserCreate, UserOut
from backend.app.schemas.tenants import InvitationAcceptIn, InvitationInfoOut, InvitationTokenIn
from backend.app.services import invitations
from backend.app.services.auth import (
    ConsentVersionError,
    EmailAlreadyRegisteredError,
    InactiveAccountError,
    RegistrationUnavailableError,
    UnknownPlanError,
    authenticate_user,
    create_access_token,
    register_patient,
)

router = APIRouter()

INVALID_INVITATION = "El enlace no es válido, ya se usó o venció. Pide uno nuevo."


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("auth_register", 5, 60))],
)
def register(data: UserCreate, db: ControlDb, request: Request):
    """Registro público: siempre crea una paciente en el tenant B2C, con consentimiento y plan."""
    try:
        return register_patient(db, data, client_ip(request))
    except ConsentVersionError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Debes aceptar la versión vigente del consentimiento informado",
        ) from None
    except UnknownPlanError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Plan no disponible"
        ) from None
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
    token = create_access_token(user)
    # Solo si la contraseña verificada sigue siendo la vigente: si un restablecimiento ganó la
    # carrera, no se entrega token
    updated = db.execute(
        update(User)
        .where(
            User.id == user.id,
            User.hashed_password == user.hashed_password,
            User.is_active.is_(True),
        )
        .values(last_login_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    ).rowcount
    db.commit()
    if updated != 1:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=token)


@router.get("/me", response_model=MeOut)
def me(auth: CurrentUser):
    return MeOut(
        user_id=auth.user_id, tenant_id=auth.tenant_id, tenant_slug=auth.tenant_slug, role=auth.role
    )


@router.post(
    "/invitations/inspect",
    response_model=InvitationInfoOut,
    dependencies=[Depends(rate_limit("auth_invitation_inspect", 10, 60))],
)
def inspect_invitation(data: InvitationTokenIn, db: ControlDb):
    """Público: datos mínimos para la pantalla de invitación (correo enmascarado)."""
    try:
        info = invitations.inspect(db, data.token)
    except invitations.InvalidInvitationError:
        raise HTTPException(status_code=400, detail=INVALID_INVITATION) from None
    return InvitationInfoOut(**info.__dict__)


@router.post(
    "/invitations/accept",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit("auth_invitation_accept", 5, 60))],
)
def accept_invitation(data: InvitationAcceptIn, db: ControlDb, request: Request):
    """Público: fija la contraseña con un token de un solo uso; luego se inicia sesión normal."""
    try:
        invitations.accept(db, data.token, data.password, client_ip(request))
    except invitations.InvalidInvitationError:
        raise HTTPException(status_code=400, detail=INVALID_INVITATION) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
