from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.app.models.database import SessionLocal
from backend.app.models.image import MedicalImage
from backend.app.services.storage import store_uploaded_file
import uuid
import os

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/upload")
async def upload_image(
    file: UploadFile = File(...),
    user_id: int = 1,  # En producción, usa el ID del usuario autenticado
    image_type: str = "BUSI",  # "BUSI" o "mammography"
    db: Session = Depends(get_db)
):
    # Guardar archivo temporalmente
    os.makedirs("temp", exist_ok=True)
    file_path = f"temp/{uuid.uuid4()}{file.filename}"
    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())

    # Guardar la imagen (local en la EC2 por defecto, o S3 si STORAGE_BACKEND=s3)
    object_name = f"{user_id}/{uuid.uuid4()}{file.filename}"
    image_url = store_uploaded_file(file_path, object_name)
    if not image_url:
        raise HTTPException(status_code=500, detail="Failed to store uploaded image")

    # Guardar en DB
    db_image = MedicalImage(
        user_id=user_id,
        image_path=image_url,
        image_type=image_type
    )
    db.add(db_image)
    db.commit()
    db.refresh(db_image)

    # Eliminar archivo temporal
    os.remove(file_path)

    return {"message": "Image uploaded successfully", "image_id": db_image.id}
