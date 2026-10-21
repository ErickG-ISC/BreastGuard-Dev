from dotenv import load_dotenv

load_dotenv()

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.v1 import health, auth, images

app = FastAPI()

frontend_origins = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins,
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