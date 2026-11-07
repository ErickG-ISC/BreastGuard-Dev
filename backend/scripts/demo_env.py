"""Guarda común de los scripts de demostración: solo corren en el entorno de DESARROLLO.

Dos condiciones explícitas (ninguna se deduce sola):
- `BREASTGUARD_ENV=development`;
- `DEMO_DB_REF` igual al identificador de la base de `DATABASE_URL`: el ref del proyecto de
  Supabase (el sufijo del usuario `postgres.<ref>` del pooler) o, sin sufijo, `host/base`.
Así un `.env` que apunte a otra base no basta para crear cuentas demo ni cambiar contraseñas.
"""

import os

from sqlalchemy.engine import make_url

DEMO_TENANT_PREFIX = "demo-"
DEMO_PATIENT_DOMAIN = "demo.invalid"


class NotDevelopmentError(RuntimeError):
    pass


def database_ref() -> str:
    """Identificador de la base de DATABASE_URL (no incluye contraseñas)."""
    url = make_url(os.environ["DATABASE_URL"])
    username = url.username or ""
    if "." in username:
        return username.split(".", 1)[1]
    return f"{url.host}/{url.database}"


def require_development() -> None:
    if os.environ.get("BREASTGUARD_ENV") != "development":
        raise NotDevelopmentError(
            "Los scripts de demostración solo corren con BREASTGUARD_ENV=development "
            "(base de desarrollo)."
        )
    expected = os.environ.get("DEMO_DB_REF", "")
    actual = database_ref()
    if expected != actual:
        raise NotDevelopmentError(
            f"DEMO_DB_REF no coincide con la base de DATABASE_URL ({actual}). Si esa es la base "
            "de desarrollo, ejecútalo con DEMO_DB_REF=<ese valor>."
        )
