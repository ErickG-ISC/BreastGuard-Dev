import io
import logging
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from fastapi import HTTPException, UploadFile, status
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ml.quality import ImageQualityError
from backend.app.ml.service import prepare_image
from backend.app.models.clinical import MedicalImage, Patient
from backend.app.services import audit
from backend.app.services.auth import AuthContext
from backend.app.services.storage import StorageError, SupabaseStorage, signed_url_ttl

logger = logging.getLogger(__name__)

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


def strip_metadata(data: bytes, extension: str) -> bytes:
    """Re-codifica la imagen desde sus píxeles: sin EXIF, GPS ni otros metadatos."""
    try:
        clean = prepare_image(data)
    except ImageQualityError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from None
    buffer = io.BytesIO()
    clean.save(buffer, format="JPEG" if extension == ".jpg" else "PNG")
    return buffer.getvalue()


def store_medical_image(
    db: Session,
    storage: SupabaseStorage,
    auth: AuthContext,
    image: ValidatedImage,
    image_type: str,
    ip: str | None,
) -> MedicalImage:
    """Sube la imagen al prefijo del tenant y registra la fila; el temporal se borra siempre.

    `db` es una sesión de get_tenant_db: RLS limita todo al tenant (y a la paciente) del JWT.
    """
    patient = db.scalars(select(Patient).where(Patient.user_id == auth.user_id)).first()
    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No se encontró tu ficha de paciente"
        )

    image_id = uuid.uuid4()
    # Prefijo del tenant resuelto en el servidor (nunca del cliente)
    object_name = f"{auth.tenant_slug}/images/{image_id.hex}{image.extension}"
    temp_path = Path(tempfile.gettempdir()) / f"{uuid.uuid4().hex}{image.extension}"
    try:
        # Se guarda la imagen reconstruida sin metadatos (EXIF/GPS), nunca el original
        temp_path.write_bytes(strip_metadata(image.data, image.extension))
        try:
            storage.upload_file(str(temp_path), object_name, image.content_type)
        except StorageError:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="No se pudo guardar la imagen. Intenta de nuevo.",
            ) from None

        db_image = MedicalImage(
            id=image_id,
            patient_id=patient.id,
            uploaded_by=auth.user_id,
            object_path=object_name,
            image_type=image_type,
        )
        db.add(db_image)
        db.flush()
        _audit(db, auth, "image.upload", image_id, ip)
        db.commit()
        return db_image
    finally:
        temp_path.unlink(missing_ok=True)


def _audit(
    db: Session, auth: AuthContext, action: str, resource_id: uuid.UUID | None, ip: str | None
) -> None:
    audit.record(
        db,
        tenant_id=auth.tenant_id,
        actor_id=auth.user_id,
        actor_role=auth.role,
        action=action,
        resource_type="medical_image",
        resource_id=resource_id,
        ip=ip,
    )


def _deny(db: Session, auth: AuthContext, image_id: uuid.UUID, ip: str | None) -> NoReturn:
    """Registra el intento denegado en el tenant de quien preguntó y responde 404 uniforme.

    Solo guarda el id solicitado (lo envió el propio usuario): no revela si existe en otro lado.
    """
    db.rollback()
    _audit(db, auth, "image.denied", image_id, ip)
    db.commit()
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Imagen no encontrada")


def list_images(db: Session, auth: AuthContext, ip: str | None) -> list[MedicalImage]:
    """RLS limita al tenant; la política por rol limita a la paciente sus propias imágenes."""
    images = list(db.scalars(select(MedicalImage).order_by(MedicalImage.created_at.desc())))
    _audit(db, auth, "image.list", None, ip)
    db.commit()
    return images


def get_image_with_url(
    db: Session, storage: SupabaseStorage, auth: AuthContext, image_id: uuid.UUID, ip: str | None
) -> tuple[MedicalImage, str, int]:
    """Imagen visible por RLS + URL firmada. Ajena o inexistente responden igual (404)."""
    image = db.scalars(select(MedicalImage).where(MedicalImage.id == image_id)).first()
    if image is None:
        _deny(db, auth, image_id, ip)
    # Defensa en profundidad: nunca firmar una ruta fuera del prefijo del tenant
    if not image.object_path.startswith(f"{auth.tenant_slug}/"):
        logger.error("Imagen con ruta fuera del prefijo de su tenant (id=%s)", image.id)
        _deny(db, auth, image_id, ip)
    ttl = signed_url_ttl()
    try:
        url = storage.create_signed_url(image.object_path, ttl)
    except StorageError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="No se pudo generar el enlace"
        ) from None
    _audit(db, auth, "image.read", image.id, ip)
    db.commit()
    return image, url, ttl
