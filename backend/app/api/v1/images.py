import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status

from backend.app.api.client_ip import client_ip
from backend.app.api.deps import Storage, TenantDb, require_role
from backend.app.api.rate_limit import rate_limit
from backend.app.schemas.image import ImageDetailOut, ImageOut, ImageUploadOut
from backend.app.services.auth import AuthContext
from backend.app.services.images import (
    get_image_with_url,
    list_images,
    read_and_validate_image,
    store_medical_image,
)

router = APIRouter()

PatientUser = Annotated[AuthContext, Depends(require_role("patient"))]
ClinicalUser = Annotated[AuthContext, Depends(require_role("patient", "doctor", "tenant_admin"))]


def _client_ip(request: Request) -> str | None:
    return client_ip(request)


@router.post(
    "/upload",
    response_model=ImageUploadOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("images_upload", 20, 60))],
)
async def upload_image(
    file: Annotated[UploadFile, File()],
    auth: PatientUser,
    db: TenantDb,
    storage: Storage,
    request: Request,
    image_type: Annotated[Literal["BUSI", "mammography"], Form()] = "BUSI",
):
    image = await read_and_validate_image(file)
    db_image = store_medical_image(db, storage, auth, image, image_type, _client_ip(request))
    return ImageUploadOut(message="Imagen subida correctamente", image_id=db_image.id)


@router.get("", response_model=list[ImageOut])
def get_images(auth: ClinicalUser, db: TenantDb, request: Request):
    return list_images(db, auth, _client_ip(request))


@router.get("/{image_id}", response_model=ImageDetailOut)
def get_image(
    image_id: uuid.UUID, auth: ClinicalUser, db: TenantDb, storage: Storage, request: Request
):
    image, url, ttl = get_image_with_url(db, storage, auth, image_id, _client_ip(request))
    return ImageDetailOut(
        **ImageOut.model_validate(image).model_dump(), url=url, url_expires_in=ttl
    )
