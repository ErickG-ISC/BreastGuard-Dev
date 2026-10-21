import logging

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from backend.app.api.deps import ControlDb
from backend.app.ml.deps import Inference

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
def health_check(db: ControlDb, inference: Inference):
    """Solo chequeo de estado. El esquema se crea con Alembic, no aquí."""
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        # El detalle va al log; la respuesta no expone host ni cadena de conexión
        logger.error("Health check: la base de datos no responde (%s)", type(exc).__name__)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "error", "database": "unavailable"},
        )
    model = "loaded" if inference.available else "unavailable"
    return {"status": "ok", "database": "connected", "model": model}
