"""Guarda común de los scripts de demostración: solo corren en el entorno de DESARROLLO.

Se exige `BREASTGUARD_ENV=development` de forma explícita (no se deduce de la URL): así un
`.env` apuntando a otra base no basta para crear cuentas demo o cambiar contraseñas.
"""

import os

DEMO_TENANT_PREFIX = "demo-"
DEMO_PATIENT_DOMAIN = "demo.invalid"


class NotDevelopmentError(RuntimeError):
    pass


def require_development() -> None:
    if os.environ.get("BREASTGUARD_ENV") != "development":
        raise NotDevelopmentError(
            "Los scripts de demostración solo corren con BREASTGUARD_ENV=development "
            "(base de desarrollo)."
        )
