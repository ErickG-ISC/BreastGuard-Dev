from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, UploadFile, status

from backend.app.api.deps import CurrentUser, DbSession, Storage
from backend.app.schemas.image import ImageUploadOut
from backend.app.services.images import read_and_validate_image, store_medical_image

router = APIRouter()


@router.post("/upload", response_model=ImageUploadOut, status_code=status.HTTP_201_CREATED)
async def upload_image(
    file: Annotated[UploadFile, File()],
    current_user: CurrentUser,
    db: DbSession,
    storage: Storage,
    image_type: Annotated[Literal["BUSI", "mammography"], Form()] = "BUSI",
):
    image = await read_and_validate_image(file)
    db_image = store_medical_image(db, storage, current_user, image, image_type)
    return ImageUploadOut(message="Imagen subida correctamente", image_id=db_image.id)
