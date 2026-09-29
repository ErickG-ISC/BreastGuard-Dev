from fastapi import FastAPI
from backend.app.api.v1 import health, auth, images

app = FastAPI()
app.include_router(health.router,prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1/auth")
app.include_router(images.router, prefix="/api/v1/images")

@app.get("/")
def read_root():
    return {"message": "Bienvenido a BreastGuard"}