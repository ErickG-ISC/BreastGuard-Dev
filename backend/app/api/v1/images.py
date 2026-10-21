from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from backend.app.api.deps import Storage, TenantDb, require_role
from backend.app.schemas.image import ImageUploadOut
from backend.app.services.auth import AuthContext
from backend.app.services.images import read_and_validate_image, store_medical_image

router = APIRouter()

PatientUser = Annotated[AuthContext, Depends(require_role("patient"))]


@router.post("/upload", response_model=ImageUploadOut, status_code=status.HTTP_201_CREATED)
async def upload_image(
    file: Annotated[UploadFile, File()],
    auth: PatientUser,
    db: TenantDb,
    storage: Storage,
    image_type: Annotated[Literal["BUSI", "mammography"], Form()] = "BUSI",
):
    image = await read_and_validate_image(file)
    db_image = store_medical_image(db, storage, auth, image, image_type)
    return ImageUploadOut(message="Imagen subida correctamente", image_id=db_image.id)
