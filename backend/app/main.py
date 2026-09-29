import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.api.v1 import health, auth, images

load_dotenv()

app = FastAPI()

# Orígenes permitidos para el frontend (ver .env.example). Por defecto, abierto para desarrollo.
allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in allowed_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router,prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1/auth")
app.include_router(images.router, prefix="/api/v1/images")

@app.get("/")
def read_root():
    return {"message": "Bienvenido a BreastGuard"}