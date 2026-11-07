"""Estado del servicio, sin datos sensibles (ADR 0016).

- `version`: el commit desplegado (RENDER_GIT_COMMIT, 7 caracteres) o `dev`;
- `migration`: la revisión de Alembic de la base comparada con la del código:
  - `ok`: iguales;
  - `ahead`: la base tiene una revisión que este código no conoce (se migró antes de desplegar,
    que es el orden correcto): responde 200;
  - `behind`: la base está atrasada respecto del código (o `app_user` no tiene permiso para leer
    la revisión, es decir, falta la 0019): responde **503**, así Render no da por bueno un
    despliegue sin migrar y deja el anterior;
  - `unknown`: otro error al leer la revisión con la base accesible: 200 (un fallo transitorio
    no saca de servicio a una instancia sana; queda en el log);
- `model` y `model_version`.

Las revisiones concretas solo van al log: no ayudan a ningún cliente.

Nunca expone host, usuario, cadena de conexión ni detalles de error (solo el tipo, en el log).
"""

import logging
import os
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from backend.app.api.deps import ControlDb
from backend.app.api.rate_limit import rate_limit
from backend.app.ml.deps import Inference

logger = logging.getLogger(__name__)

router = APIRouter()
MIGRATIONS = Path(__file__).resolve().parents[3] / "migrations"


@lru_cache
def code_revisions() -> tuple[str, frozenset[str]]:
    """(head, todas las revisiones) del código desplegado. Una sola línea de Alembic."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    script = ScriptDirectory.from_config(config)
    return script.get_current_head(), frozenset(r.revision for r in script.walk_revisions())


def deployed_version() -> str:
    commit = os.environ.get("RENDER_GIT_COMMIT", "")
    return commit[:7] if commit else "dev"


def migration_state(db_revision: str | None) -> str:
    head, known = code_revisions()
    if db_revision == head:
        return "ok"
    if db_revision is not None and db_revision not in known:
        return "ahead"
    return "behind"


# Generoso: Render consulta el health check cada pocos segundos
HEALTH_LIMIT = Depends(rate_limit("health", 120, 60))
INSUFFICIENT_PRIVILEGE = "42501"
UNKNOWN = "unknown"


def _read_revision(db) -> tuple[str | None, bool]:
    """(revisión, base accesible). Una sola consulta en el caso normal."""
    try:
        return db.execute(text("SELECT version_num FROM public.alembic_version")).scalar(), True
    except DBAPIError as exc:
        db.rollback()
        if getattr(exc.orig, "pgcode", None) == INSUFFICIENT_PRIVILEGE:
            return None, True  # sin la 0019: la base está atrasada respecto del código
        logger.error("Health check: no se pudo leer la revisión (%s)", type(exc).__name__)
    except Exception as exc:
        db.rollback()
        logger.error("Health check: no se pudo leer la revisión (%s)", type(exc).__name__)
    # ¿La base responde? Si sí, la revisión solo es "desconocida" (no se saca de servicio)
    try:
        db.execute(text("SELECT 1"))
        return UNKNOWN, True
    except Exception as exc:
        # El detalle va al log; la respuesta no expone host ni cadena de conexión
        logger.error("Health check: la base de datos no responde (%s)", type(exc).__name__)
        return None, False


@router.get("/health", dependencies=[HEALTH_LIMIT])
def health_check(db: ControlDb, inference: Inference):
    db_revision, reachable = _read_revision(db)
    if not reachable:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "error", "database": "unavailable", "version": deployed_version()},
        )
    migration = UNKNOWN if db_revision == UNKNOWN else migration_state(db_revision)
    body = {
        "status": "error" if migration == "behind" else "ok",
        "database": "connected",
        "version": deployed_version(),
        "migration": migration,
        "model": "loaded" if inference.available else "unavailable",
    }
    if inference.available:
        body["model_version"] = inference.predictor.card.model_version
    if migration == "behind":
        head, _ = code_revisions()
        logger.error(
            "Health check: la base (%s) está atrasada respecto del código (%s)", db_revision, head
        )
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=body)
    return body
