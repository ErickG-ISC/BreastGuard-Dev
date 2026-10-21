import io
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from PIL import Image
from sqlalchemy.orm import Session

from backend.app.models.image import MedicalImage
from backend.app.models.user import User
from backend.app.services.storage import StorageError, SupabaseStorage

# Extensiones aceptadas -> MIME esperado. DICOM llega con CU-09 (requiere pydicom).
ALLOWED_EXTENSIONS = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
# Formato real detectado por Pillow -> (extensión con la que se guarda, MIME)
ALLOWED_FORMATS = {"JPEG": (".jpg", "image/jpeg"), "PNG": (".png", "image/png")}


@dataclass(frozen=True)
class ValidatedImage:
    data: bytes
    extension: str
    content_type: str


def max_upload_bytes() -> int:
    return int(os.environ.get("MAX_UPLOAD_MB", "10")) * 1024 * 1024


async def read_and_validate_image(file: UploadFile) -> ValidatedImage:
    """Valida extensión, MIME, tamaño y que el contenido abra como imagen JPG/PNG.

    El nombre del archivo del cliente solo se usa para leer la extensión; nunca forma parte
    de una ruta local ni de Storage.
    """
    extension = os.path.splitext(file.filename or "")[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Tipo de archivo no permitido. Usa JPG o PNG.",
        )
    if file.content_type != ALLOWED_EXTENSIONS[extension]:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="El tipo MIME no coincide con la extensión del archivo.",
        )

    limit = max_upload_bytes()
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"El archivo supera el máximo de {limit // (1024 * 1024)} MB.",
        )

    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
            detected = img.format
    except Exception:
        detected = None
    if detected not in ALLOWED_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo no es una imagen JPG o PNG válida.",
        )

    stored_extension, content_type = ALLOWED_FORMATS[detected]
    return ValidatedImage(data=data, extension=stored_extension, content_type=content_type)


def store_medical_image(
    db: Session,
    storage: SupabaseStorage,
    user: User,
    image: ValidatedImage,
    image_type: str,
) -> MedicalImage:
    """Sube la imagen a Storage y registra la fila; el temporal se borra siempre."""
    temp_path = Path(tempfile.gettempdir()) / f"{uuid.uuid4().hex}{image.extension}"
    try:
        temp_path.write_bytes(image.data)
        object_name = f"uploads/{user.id}/{uuid.uuid4().hex}{image.extension}"
        try:
            image_url = storage.upload_file(str(temp_path), object_name, image.content_type)
        except StorageError:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="No se pudo guardar la imagen. Intenta de nuevo.",
            ) from None

        db_image = MedicalImage(user_id=user.id, image_path=image_url, image_type=image_type)
        db.add(db_image)
        db.commit()
        db.refresh(db_image)
        return db_image
    finally:
        temp_path.unlink(missing_ok=True)
