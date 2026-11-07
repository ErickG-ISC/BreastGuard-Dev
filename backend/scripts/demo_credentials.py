"""Credenciales de demostración: emitir, revisar y bloquear (solo base de DESARROLLO).

Uso, desde la raíz del repo, con `BREASTGUARD_ENV=development`:
    python -m backend.scripts.demo_credentials --issue --email doc@example.com [--email ...]
    python -m backend.scripts.demo_credentials --check
    python -m backend.scripts.demo_credentials --lock

- --issue: contraseña ALEATORIA y fuerte (24 caracteres) para cuentas SINTÉTICAS de demo:
  personal `@example.com` de un tenant `demo-…` o pacientes `@demo.invalid` del b2c. Se imprime
  UNA vez en esta terminal y no se guarda en ningún archivo. Anula sus invitaciones pendientes y
  cierra sus sesiones anteriores.
- --check: revisa TODAS las cuentas activas con contraseña de los tenants `demo-…` y las pacientes
  demo contra contraseñas débiles conocidas (sin imprimir nada secreto). Sale con 1 si encuentra
  alguna.
- --lock: desactiva las cuentas sintéticas de demo (para después de la presentación).

Corre como app_user (nunca como dueño) y no toca cuentas reales aunque estén en un tenant demo.
"""

import argparse
import secrets
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import and_, or_, select, update  # noqa: E402

from backend.app.db import new_session  # noqa: E402
from backend.app.models.control import Invitation, Tenant, User  # noqa: E402
from backend.app.services.auth import get_password_hash, verify_password  # noqa: E402
from backend.scripts.demo_env import (  # noqa: E402
    DEMO_PATIENT_DOMAIN,
    DEMO_TENANT_PREFIX,
    require_development,
)

PASSWORD_BYTES = 18  # 24 caracteres en base64 url-safe
# Contraseñas débiles que nunca deben quedar en una cuenta de demo
WEAK_PASSWORDS = (
    "contrasena-segura",
    "password",
    "password123",
    "12345678",
    "123456789",
    "demo",
    "demo1234",
    "breastguard",
    "BreastGuard1",
    "qwerty123",
    "admin123",
    "doctora123",
)


class CredentialError(ValueError):
    pass


def _synthetic():
    """Cuentas sintéticas: personal @example.com de un tenant demo, o pacientes @demo.invalid."""
    return or_(
        and_(
            Tenant.slug.startswith(DEMO_TENANT_PREFIX),
            User.email.endswith("@example.com"),
            User.role.in_(("doctor", "tenant_admin")),
        ),
        and_(
            Tenant.slug == "b2c",
            User.role == "patient",
            User.email.endswith(f"@{DEMO_PATIENT_DOMAIN}"),
        ),
    )


@dataclass(frozen=True)
class Issued:
    email: str
    role: str
    tenant: str
    password: str


def issue(emails: list[str]) -> list[Issued]:
    require_development()
    now = datetime.now(UTC)
    issued: list[Issued] = []
    with new_session() as db:
        for email in emails:
            row = db.execute(
                select(User, Tenant.slug)
                .join(Tenant, Tenant.id == User.tenant_id)
                .where(User.email == email.lower(), _synthetic(), User.is_active.is_(True))
                .with_for_update(of=User)
            ).first()
            if row is None:
                raise CredentialError(
                    f"{email} no es una cuenta sintética activa de demo (personal @example.com de "
                    f"un tenant {DEMO_TENANT_PREFIX}… o paciente @{DEMO_PATIENT_DOMAIN})"
                )
            user, slug = row
            password = secrets.token_urlsafe(PASSWORD_BYTES)
            user.hashed_password = get_password_hash(password)
            user.sessions_valid_after = now
            user.updated_at = now
            db.execute(
                update(Invitation)
                .where(
                    Invitation.user_id == user.id,
                    Invitation.used_at.is_(None),
                    Invitation.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            issued.append(Issued(user.email, user.role, slug, password))
        db.commit()
    return issued


@dataclass(frozen=True)
class CheckResult:
    with_password: int
    weak: list[str]


def check() -> CheckResult:
    """Cuentas activas con contraseña en tenants demo y pacientes demo, contra la lista débil."""
    require_development()
    with new_session() as db:
        users = db.execute(
            select(User.email, User.hashed_password)
            .join(Tenant, Tenant.id == User.tenant_id)
            .where(
                User.is_active.is_(True),
                User.hashed_password.is_not(None),
                or_(
                    Tenant.slug.startswith(DEMO_TENANT_PREFIX),
                    User.email.endswith(f"@{DEMO_PATIENT_DOMAIN}"),
                ),
            )
        ).all()
    weak = [
        email
        for email, hashed in users
        if any(verify_password(candidate, hashed) for candidate in WEAK_PASSWORDS)
    ]
    return CheckResult(with_password=len(users), weak=weak)


def lock() -> int:
    require_development()
    now = datetime.now(UTC)
    with new_session() as db:
        ids = list(
            db.scalars(
                select(User.id)
                .join(Tenant, Tenant.id == User.tenant_id)
                .where(_synthetic(), User.is_active.is_(True))
            )
        )
        if ids:
            db.execute(
                update(User)
                .where(User.id.in_(ids))
                .values(is_active=False, sessions_valid_after=now, updated_at=now)
            )
        db.commit()
    return len(ids)


def _mask(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:3]}***@{domain}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--issue", action="store_true")
    action.add_argument("--check", action="store_true")
    action.add_argument("--lock", action="store_true")
    parser.add_argument("--email", action="append", default=[])
    args = parser.parse_args()
    try:
        if args.issue:
            if not args.email:
                print("Indica al menos un --email", file=sys.stderr)
                return 1
            print("Credenciales de demostración (se muestran UNA vez; no las guardes en el repo):")
            for item in issue(args.email):
                print(f"  {item.tenant:<24} {item.role:<13} {item.email}  {item.password}")
            return 0
        if args.check:
            result = check()
            print(f"Cuentas demo activas con contraseña: {result.with_password}")
            if result.weak:
                print("Con contraseña DÉBIL (cámbiala o bloquéala):", file=sys.stderr)
                for email in result.weak:
                    print(f"  {_mask(email)}", file=sys.stderr)
                return 1
            print("Ninguna usa una contraseña débil conocida.")
            return 0
        print(f"Cuentas sintéticas de demo desactivadas: {lock()}")
        return 0
    except Exception as exc:  # mensaje claro, sin trazas con datos
        print(f"No se pudo completar: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
