import logging

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from backend.app.api.deps import DbSession

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
def health_check(db: DbSession):
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
    return {"status": "ok", "database": "connected"}
