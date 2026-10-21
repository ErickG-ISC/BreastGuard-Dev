import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserCreate(BaseModel):
    """Registro público: solo crea pacientes en el tenant B2C. No acepta rol ni tenant."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=1, max_length=200)
    # Consentimiento explícito: sin `true` y la versión vigente no se crea la cuenta
    consent_accepted: Literal[True]
    consent_version: str = Field(min_length=1, max_length=50)
    # Huella del texto que se mostró: prueba de que se aceptó exactamente esa versión
    consent_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_code: str = Field(min_length=1, max_length=50)

    @field_validator("password")
    @classmethod
    def password_fits_bcrypt(cls, value: str) -> str:
        # bcrypt solo usa los primeros 72 bytes; rechazar en lugar de truncar en silencio
        if len(value.encode("utf-8")) > 72:
            raise ValueError("La contraseña no puede superar 72 bytes")
        return value


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: str
    tenant_id: uuid.UUID | None


class MeOut(BaseModel):
    user_id: uuid.UUID
    tenant_id: uuid.UUID | None
    tenant_slug: str | None
    role: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
