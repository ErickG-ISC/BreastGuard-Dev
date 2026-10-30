"""Utilidades compartidas por las pruebas (fuera de conftest para importarlas sin duplicarlo)."""

import io
import uuid
from dataclasses import dataclass
from functools import lru_cache

from PIL import Image
from sqlalchemy import Engine, text

from backend.app.content.consent import CURRENT_CONSENT_VERSION, current_consent
from backend.app.db import TenantContext, new_session
from backend.app.services.auth import create_access_token, get_password_hash

DEFAULT_PASSWORD = "contrasena-segura"


def registration(email: str, full_name: str = "Paciente", **overrides) -> dict:
    """Cuerpo válido de /auth/register: consentimiento vigente aceptado y plan simulado."""
    return {
        "email": email,
        "password": DEFAULT_PASSWORD,
        "full_name": full_name,
        "consent_accepted": True,
        "consent_version": CURRENT_CONSENT_VERSION,
        "consent_sha256": current_consent().sha256,
        "plan_code": "basico",
        **overrides,
    }


@dataclass(frozen=True)
class TestTenant:
    __test__ = False  # no es una clase de pruebas

    id: uuid.UUID
    slug: str


@dataclass(frozen=True)
class TestUser:
    __test__ = False

    id: uuid.UUID
    tenant_id: uuid.UUID | None
    role: str
    email: str
    patient_id: uuid.UUID | None = None


@lru_cache
def default_password_hash() -> str:
    return get_password_hash(DEFAULT_PASSWORD)


def insert_tenant(engine: Engine, slug: str, *, kind: str = "institucion", active: bool = True):
    """Inserta un tenant como dueño (preparación de datos, no verifica RLS)."""
    with engine.begin() as conn:
        tenant_id = conn.execute(
            text(
                "INSERT INTO control.tenants (slug, name, kind, plan, is_active) "
                "VALUES (:slug, :name, :kind, 'basic', :active) RETURNING id"
            ),
            {"slug": slug, "name": f"Tenant {slug}", "kind": kind, "active": active},
        ).scalar_one()
    return TestTenant(id=tenant_id, slug=slug)


def insert_user(
    engine: Engine,
    tenant,
    *,
    role: str = "patient",
    email: str | None = None,
    active: bool = True,
) -> TestUser:
    """Inserta un usuario (y su ficha si es paciente) como dueño."""
    email = email or f"{role}-{uuid.uuid4().hex[:8]}@example.com"
    tenant_id = None if role == "platform_admin" else tenant.id
    with engine.begin() as conn:
        user_id = conn.execute(
            text(
                "INSERT INTO control.users "
                "(tenant_id, email, hashed_password, full_name, role, is_active) "
                "VALUES (:tenant_id, :email, :pw, 'Usuario de prueba', :role, :active) RETURNING id"
            ),
            {
                "tenant_id": tenant_id,
                "email": email,
                "pw": default_password_hash(),
                "role": role,
                "active": active,
            },
        ).scalar_one()
        patient_id = None
        if role == "patient":
            patient_id = conn.execute(
                text(
                    "INSERT INTO clinical.patients (tenant_id, user_id, display_name, origin) "
                    "VALUES (:tenant_id, :user_id, 'Paciente de prueba', 'propio') RETURNING id"
                ),
                {"tenant_id": tenant_id, "user_id": user_id},
            ).scalar_one()
    return TestUser(id=user_id, tenant_id=tenant_id, role=role, email=email, patient_id=patient_id)


def auth_headers(user: TestUser) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def tenant_session(user: TestUser):
    """Sesión de app_user con el contexto RLS del usuario (para probar RLS directamente)."""
    return new_session(TenantContext(user.tenant_id, user.id, user.role))


def make_image_bytes(fmt: str = "PNG") -> bytes:
    """Imagen sintética diminuta; nunca se usan imágenes médicas reales."""
    buffer = io.BytesIO()
    Image.new("L", (8, 8), color=128).save(buffer, format=fmt)
    return buffer.getvalue()
