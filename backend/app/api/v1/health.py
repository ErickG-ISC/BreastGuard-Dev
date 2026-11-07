"""Estado del servicio, sin datos sensibles (ADR 0016).

- `version`: el commit desplegado (RENDER_GIT_COMMIT, 7 caracteres) o `dev`;
- `migration`: la revisión de Alembic de la base comparada con la del código:
  - `ok`: iguales;
  - `ahead`: la base tiene una revisión que este código no conoce (se migró antes de desplegar,
    que es el orden correcto): responde 200;
  - `behind`: la base está atrasada respecto del código (o no se puede leer la revisión):
    responde **503**, así Render no da por bueno un despliegue sin migrar y deja el anterior;
- `model` y `model_version`.

Nunca expone host, usuario, cadena de conexión ni detalles de error (solo el tipo, en el log).
"""

import logging
import os
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from backend.app.api.deps import ControlDb
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


@router.get("/health")
def health_check(db: ControlDb, inference: Inference):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        # El detalle va al log; la respuesta no expone host ni cadena de conexión
        logger.error("Health check: la base de datos no responde (%s)", type(exc).__name__)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "error", "database": "unavailable", "version": deployed_version()},
        )
    try:
        db_revision = db.execute(text("SELECT version_num FROM public.alembic_version")).scalar()
    except Exception as exc:
        # Sin permiso de lectura (0019 sin aplicar) también es "atrasada"
        logger.error("Health check: no se pudo leer la revisión (%s)", type(exc).__name__)
        db.rollback()
        db_revision = None
    migration = migration_state(db_revision)
    head, _ = code_revisions()
    body = {
        "status": "ok" if migration != "behind" else "error",
        "database": "connected",
        "version": deployed_version(),
        "migration": migration,
        "schema_revision": db_revision,
        "code_revision": head,
        "model": "loaded" if inference.available else "unavailable",
    }
    if inference.available:
        body["model_version"] = inference.predictor.card.model_version
    if migration == "behind":
        logger.error(
            "Health check: la base (%s) está atrasada respecto del código (%s)", db_revision, head
        )
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=body)
    return body
