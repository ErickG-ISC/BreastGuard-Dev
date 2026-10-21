import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db import TenantContext, set_transaction_context
from backend.app.models.clinical import Patient
from backend.app.models.control import ROLES, Tenant, User
from backend.app.schemas.auth import UserCreate

SECRET_KEY = os.environ["SECRET_KEY"]
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
B2C_TENANT_SLUG = "b2c"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class InvalidTokenError(Exception):
    """El JWT no es válido, expiró o sus claims no son coherentes."""


class InactiveAccountError(Exception):
    """La cuenta o su institución están desactivadas."""


class EmailAlreadyRegisteredError(Exception):
    pass


class RegistrationUnavailableError(Exception):
    """No existe (o está inactivo) el tenant B2C donde se registran las pacientes."""


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    tenant_id: uuid.UUID | None
    role: str


@dataclass(frozen=True)
class AuthContext:
    """Usuario autenticado, verificado contra el esquema control en cada petición."""

    user_id: uuid.UUID
    tenant_id: uuid.UUID | None
    tenant_slug: str | None
    role: str


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


@lru_cache
def _dummy_hash() -> str:
    return get_password_hash("contrasena-de-relleno")


def create_access_token(user: User, expires_delta: timedelta | None = None) -> str:
    expire = datetime.now(UTC) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    claims = {
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id) if user.tenant_id else None,
        "role": user.role,
        "exp": expire,
    }
    return jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> TokenClaims:
    """Verifica firma, expiración y coherencia de los claims (sub, tenant_id, role)."""
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"require_exp": True, "require_sub": True},
        )
        role = payload["role"]
        raw_tenant = payload["tenant_id"]
        claims = TokenClaims(
            user_id=uuid.UUID(payload["sub"]),
            tenant_id=uuid.UUID(raw_tenant) if raw_tenant is not None else None,
            role=role,
        )
    except (JWTError, KeyError, TypeError, ValueError, AttributeError):
        raise InvalidTokenError from None
    if claims.role not in ROLES or (claims.role == "platform_admin") != (claims.tenant_id is None):
        raise InvalidTokenError
    return claims


def load_auth_context(db: Session, claims: TokenClaims) -> AuthContext | None:
    """Relee usuario y tenant: un usuario/tenant inactivo o un rol cambiado invalida el token."""
    row = db.execute(
        select(User, Tenant)
        .outerjoin(Tenant, User.tenant_id == Tenant.id)
        .where(User.id == claims.user_id)
    ).first()
    if row is None:
        return None
    user, tenant = row
    if not user.is_active or user.role != claims.role or user.tenant_id != claims.tenant_id:
        return None
    if tenant is not None and not tenant.is_active:
        return None
    return AuthContext(
        user_id=user.id,
        tenant_id=user.tenant_id,
        tenant_slug=tenant.slug if tenant else None,
        role=user.role,
    )


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalars(select(User).where(func.lower(User.email) == email.lower())).first()


def register_patient(db: Session, data: UserCreate) -> User:
    """Crea la cuenta (control) y la ficha clínica (b2c) en UNA transacción."""
    tenant = db.scalars(
        select(Tenant).where(Tenant.slug == B2C_TENANT_SLUG, Tenant.is_active.is_(True))
    ).first()
    if tenant is None:
        raise RegistrationUnavailableError
    if get_user_by_email(db, data.email):
        raise EmailAlreadyRegisteredError
    user = User(
        tenant_id=tenant.id,
        email=data.email,
        hashed_password=get_password_hash(data.password),
        full_name=data.full_name,
        role="patient",
    )
    try:
        db.add(user)
        db.flush()
        # Alta documentada (ADR 0002): contexto del tenant b2c solo para insertar la ficha
        set_transaction_context(db, TenantContext(tenant.id, user.id, "patient"))
        db.add(Patient(user_id=user.id, display_name=data.full_name))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise EmailAlreadyRegisteredError from None
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    """None si el email no existe o la contraseña no coincide (mismo costo en ambos casos)."""
    user = get_user_by_email(db, email)
    if user is None:
        verify_password(password, _dummy_hash())
        return None
    if not verify_password(password, user.hashed_password):
        return None
    tenant = db.get(Tenant, user.tenant_id) if user.tenant_id else None
    if not user.is_active or (tenant is not None and not tenant.is_active):
        raise InactiveAccountError
    return user
