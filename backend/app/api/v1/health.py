from fastapi import APIRouter
from backend.models.database import engine,Base

router = APIRouter()

@router.get("/health")

def health_check():
    try:
        Base.metadata.create_all(bind=engine) #Crea tablas si no existen
        return{"status":"ok","database":"connected"}
    except Exception as e:
        return{"status":"error","message":str(e)}