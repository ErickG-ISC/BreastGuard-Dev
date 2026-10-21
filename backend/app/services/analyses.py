"""CU-02: subir y analizar una ecografía, consultar el historial y eliminar un análisis.

La sesión es de get_tenant_db: RLS limita al tenant del JWT y la política de paciente a sus
propias filas. Las imágenes y heatmaps viven en Storage privado bajo {tenant_slug}/ y solo se
entregan con URLs firmadas de corta duración. Cada lectura y escritura queda auditada.
"""

import logging
import uuid
from typing import NoReturn

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.ml.quality import ImageQualityError
from backend.app.ml.service import InferenceService
from backend.app.models.clinical import Analysis, MedicalImage, Patient
from backend.app.services import audit
from backend.app.services.auth import AuthContext
from backend.app.services.images import ValidatedImage
from backend.app.services.storage import StorageError, SupabaseStorage, signed_url_ttl

logger = logging.getLogger(__name__)

NOT_FOUND = "Análisis no encontrado"


def _audit(db: Session, auth: AuthContext, action: str, resource_id, ip: str | None) -> None:
    audit.record(
        db,
        tenant_id=auth.tenant_id,
        actor_id=auth.user_id,
        actor_role=auth.role,
        action=action,
        resource_type="analysis",
        resource_id=resource_id,
        ip=ip,
    )


def _deny(db: Session, auth: AuthContext, analysis_id: uuid.UUID, ip: str | None) -> NoReturn:
    """404 uniforme (ajeno o inexistente); el intento queda en la auditoría de quien preguntó."""
    db.rollback()
    _audit(db, auth, "analysis.denied", analysis_id, ip)
    db.commit()
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)


def _remove_quietly(storage: SupabaseStorage, paths: list[str]) -> None:
    try:
        storage.remove_objects(paths)
    except StorageError:
        logger.error("No se pudieron limpiar objetos huérfanos de Storage")


async def create(
    db: Session,
    storage: SupabaseStorage,
    inference: InferenceService,
    auth: AuthContext,
    image: ValidatedImage,
    ip: str | None,
) -> Analysis:
    patient = db.scalars(select(Patient).where(Patient.user_id == auth.user_id)).first()
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ficha no encontrada")
    patient_id = patient.id
    # Libera la conexión mientras corre la inferencia (puede tardar)
    db.rollback()

    try:
        outcome = await inference.analyze(image.data)
    except ImageQualityError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from None

    image_id, analysis_id = uuid.uuid4(), uuid.uuid4()
    # Prefijo del tenant resuelto en el servidor; nombres aleatorios (nunca del cliente)
    image_path = f"{auth.tenant_slug}/images/{image_id.hex}.png"
    heatmap_path = f"{auth.tenant_slug}/heatmaps/{analysis_id.hex}.png"
    uploaded: list[str] = []
    try:
        storage.upload_bytes(image_path, outcome.clean_image_png, "image/png")
        uploaded.append(image_path)
        storage.upload_bytes(heatmap_path, outcome.heatmap_png, "image/png")
        uploaded.append(heatmap_path)
    except StorageError:
        _remove_quietly(storage, uploaded)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No se pudo guardar la imagen. Intenta de nuevo.",
        ) from None

    try:
        db.add(
            MedicalImage(
                id=image_id,
                patient_id=patient_id,
                uploaded_by=auth.user_id,
                object_path=image_path,
                image_type="BUSI",
                prediction=outcome.predicted_class,
                confidence=outcome.confidence,
            )
        )
        db.flush()
        analysis = Analysis(
            id=analysis_id,
            patient_id=patient_id,
            image_id=image_id,
            created_by=auth.user_id,
            status=outcome.status,
            predicted_class=outcome.predicted_class,
            probabilities=outcome.probabilities,
            confidence=outcome.confidence,
            model_version=outcome.model_version,
            heatmap_path=heatmap_path,
            quality_flags=outcome.flags,
            report=outcome.report,
        )
        db.add(analysis)
        db.flush()
        _audit(db, auth, "analysis.create", analysis_id, ip)
        db.commit()
    except Exception:
        db.rollback()
        _remove_quietly(storage, uploaded)
        raise
    db.refresh(analysis)
    return analysis


def list_page(
    db: Session, auth: AuthContext, limit: int, offset: int, ip: str | None
) -> tuple[list[Analysis], int]:
    total = db.scalar(select(func.count()).select_from(Analysis))
    items = list(
        db.scalars(
            select(Analysis)
            .order_by(Analysis.created_at.desc(), Analysis.id)
            .limit(limit)
            .offset(offset)
        )
    )
    _audit(db, auth, "analysis.list", None, ip)
    db.commit()
    return items, total


def _load(db: Session, auth: AuthContext, analysis_id: uuid.UUID, ip: str | None):
    row = db.execute(
        select(Analysis, MedicalImage)
        .join(
            MedicalImage,
            (MedicalImage.tenant_id == Analysis.tenant_id) & (MedicalImage.id == Analysis.image_id),
        )
        .where(Analysis.id == analysis_id)
    ).first()
    if row is None:
        _deny(db, auth, analysis_id, ip)
    analysis, image = row
    prefix = f"{auth.tenant_slug}/"
    # Defensa en profundidad: nunca firmar ni borrar rutas fuera del prefijo del tenant
    if not (image.object_path.startswith(prefix) and analysis.heatmap_path.startswith(prefix)):
        logger.error("Análisis con rutas fuera del prefijo de su tenant (id=%s)", analysis_id)
        _deny(db, auth, analysis_id, ip)
    return analysis, image


def get_with_urls(
    db: Session,
    storage: SupabaseStorage,
    auth: AuthContext,
    analysis_id: uuid.UUID,
    ip: str | None,
) -> tuple[Analysis, str, str, int]:
    analysis, image = _load(db, auth, analysis_id, ip)
    ttl = signed_url_ttl()
    try:
        image_url = storage.create_signed_url(image.object_path, ttl)
        heatmap_url = storage.create_signed_url(analysis.heatmap_path, ttl)
    except StorageError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="No se pudo generar el enlace"
        ) from None
    _audit(db, auth, "analysis.read", analysis.id, ip)
    db.commit()
    return analysis, image_url, heatmap_url, ttl


def delete(
    db: Session,
    storage: SupabaseStorage,
    auth: AuthContext,
    analysis_id: uuid.UUID,
    ip: str | None,
) -> None:
    """Derecho de eliminación: borra los archivos de Storage y luego las filas (auditado).

    Si Storage falla no se borra nada de la base (502) y se puede reintentar.
    """
    analysis, image = _load(db, auth, analysis_id, ip)
    try:
        storage.remove_objects([image.object_path, analysis.heatmap_path])
    except StorageError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No se pudo eliminar. Intenta de nuevo.",
        ) from None
    db.delete(analysis)
    db.flush()
    db.delete(image)
    db.flush()
    _audit(db, auth, "analysis.delete", analysis_id, ip)
    db.commit()
