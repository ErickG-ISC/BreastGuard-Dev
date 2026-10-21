"""Crea el primer platform_admin (control-only, sin tenant ni acceso clínico).

Uso, desde la raíz del repo:
    python -m backend.scripts.create_platform_admin --email admin@ejemplo.com --name "Admin"

Se conecta como app_user (nunca como dueño) y pide la contraseña sin mostrarla.
"""

import argparse
import getpass
import sys

from dotenv import load_dotenv

load_dotenv()

from backend.app.db import new_session  # noqa: E402
from backend.app.services.tenants import ConflictError, create_platform_admin  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()

    password = getpass.getpass("Contraseña: ")
    if len(password) < 12:
        print("La contraseña debe tener al menos 12 caracteres.", file=sys.stderr)
        return 1
    if password != getpass.getpass("Repite la contraseña: "):
        print("Las contraseñas no coinciden.", file=sys.stderr)
        return 1

    with new_session() as db:
        try:
            user = create_platform_admin(db, args.email, args.name, password)
        except ConflictError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    print(f"platform_admin creado: {user.id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
