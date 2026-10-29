"""Genera, en la terminal de la persona operadora, un enlace NUEVO para una cuenta invitada.

Sirve cuando el correo no llega (por ejemplo, Resend sin dominio verificado). Solo funciona para
cuentas de personal que todavía no fijan su contraseña: nunca para cuentas activas, pacientes ni
platform_admin. El enlace anterior queda revocado y la acción va a la bitácora de plataforma.

Uso, desde la raíz del repo:
    python -m backend.scripts.invitation_link --email persona@ejemplo.com

Se conecta como app_user (nunca como dueño). El enlace solo se imprime aquí; no lo pegues en
canales públicos: sirve una vez y vence en 48 horas.
"""

import argparse
import sys

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import func, select  # noqa: E402

from backend.app.db import new_session  # noqa: E402
from backend.app.models.control import Tenant, User  # noqa: E402
from backend.app.services import admin_events, invitations  # noqa: E402
from backend.app.services.tenants import STAFF_ROLES  # noqa: E402


class InvitationLinkError(Exception):
    pass


def issue_link(email: str) -> tuple[str, str]:
    """(enlace, propósito). Una cuenta que ya entró antes recibe un restablecimiento (2 h)."""
    with new_session() as db:
        row = db.execute(
            select(User, Tenant)
            .join(Tenant, Tenant.id == User.tenant_id)
            .where(func.lower(User.email) == email.strip().lower())
            .with_for_update(of=User)
        ).first()
        # Mismo mensaje para "no existe" y "no es personal": el operador ya conoce sus cuentas
        if row is None or row[0].role not in STAFF_ROLES:
            raise InvitationLinkError("No hay una cuenta de personal invitada con ese correo")
        user, tenant = row
        if user.hashed_password is not None:
            raise InvitationLinkError(
                "La cuenta ya está activa; usa 'Restablecer acceso' en la administración"
            )
        if not user.is_active or not tenant.is_active:
            raise InvitationLinkError("La cuenta o su institución están desactivadas")
        # Ya tuvo acceso: es un restablecimiento (vence en 2 h), no una invitación (48 h)
        purpose = "reset" if user.last_login_at is not None else "invite"
        token = invitations.issue(db, user, purpose, None)
        admin_events.record(
            db,
            actor_id=None,
            actor_role="system",
            action="user.invite_resend",
            tenant_id=user.tenant_id,
            target_type="user",
            target_id=user.id,
            ip=None,
            details={"purpose": purpose},
        )
        db.commit()
    return invitations.invitation_url(token), purpose


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    try:
        url, purpose = issue_link(args.email)
    except InvitationLinkError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    hours = int(invitations.TTL[purpose].total_seconds() // 3600)
    kind = "restablecimiento" if purpose == "reset" else "invitación"
    print(f"Enlace de {kind}, de un solo uso (vence en {hours} horas):")
    print(url)
    if "localhost" in url or "127.0.0.1" in url:
        print(
            "Aviso: el enlace apunta a tu equipo. Para usarlo en el despliegue, define "
            "PUBLIC_APP_URL con la URL del frontend (https://...).",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
