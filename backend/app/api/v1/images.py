from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.app.models.database import SessionLocal
from backend.app.models.image import MedicalImage
from backend.app.services.storage import upload_file_to_storage
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
    file_path = f"temp/{uuid.uuid4()}{file.filename}"
    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())

    # Subir a Supabase Storage
    object_name = f"uploads/{user_id}/{uuid.uuid4()}{file.filename}"
    image_url = upload_file_to_storage(file_path, object_name)
    if not image_url:
        raise HTTPException(status_code=500, detail="Failed to upload image to storage")

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
