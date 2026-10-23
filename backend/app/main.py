from dotenv import load_dotenv

load_dotenv()

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.v1 import (
    admin,
    analyses,
    audit,
    auth,
    blog,
    health,
    images,
    internal,
    onboarding,
    reminders,
    self_exams,
    symptoms,
)
from backend.app.cors import parse_origins
from backend.app.db import assert_safe_db_role
from backend.app.ml.loader import load_predictor
from backend.app.ml.service import InferenceService
from backend.app.ml.settings import get_settings
from backend.app.services import blog as blog_service

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Falla cerrado: sin rol seguro (no superusuario, no BYPASSRLS) la app no arranca
    assert_safe_db_role()
    # El contenido del blog se valida al arrancar (las pruebas lo validan antes, en CI)
    blog_service.load_all()
    # El modelo se carga UNA vez aquí, nunca por petición. Si falla, la app arranca igual y
    # el análisis responde 503 (lo indica /health).
    settings = get_settings()
    predictor = None
    if settings.load_on_startup:
        try:
            predictor = load_predictor(settings)
        except Exception as exc:
            logger.error(
                "No se pudo cargar el modelo (%s); análisis no disponible", type(exc).__name__
            )
    app.state.inference = InferenceService(predictor, settings)
    yield


app = FastAPI(lifespan=lifespan)

# Tolerante a errores de captura (sin https://, comillas, espacios, barra final)
frontend_origins = parse_origins(os.environ.get("FRONTEND_ORIGIN"))
# Los orígenes no son secretos: se registran para poder verificar CORS en los logs de Render
logger.warning("CORS: orígenes permitidos %s", frontend_origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_store_api(request: Request, call_next):
    """Las respuestas de la API (datos clínicos, URLs firmadas) no se guardan en cachés HTTP."""
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1/auth")
app.include_router(images.router, prefix="/api/v1/images")
app.include_router(admin.router, prefix="/api/v1/admin")
app.include_router(audit.router, prefix="/api/v1/audit")
app.include_router(onboarding.router, prefix="/api/v1")
app.include_router(analyses.router, prefix="/api/v1/analyses")
app.include_router(self_exams.router, prefix="/api/v1")
app.include_router(symptoms.router, prefix="/api/v1/symptoms")
app.include_router(reminders.router, prefix="/api/v1")
app.include_router(internal.router, prefix="/api/v1")
app.include_router(blog.router, prefix="/api/v1")


@app.get("/")
def read_root():
    return {"message": "Bienvenido a BreastGuard"}
