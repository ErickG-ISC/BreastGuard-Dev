"""CU-09: la médica agrega análisis (JPG, PNG o DICOM), revisa con BI-RADS y da de alta fichas.

Todo con su TenantDb y solo sobre fichas de las que ES responsable (con un traspaso pendiente
hacia ella las ve, pero primero debe aceptarlo: 409). Un id ajeno o inexistente da el mismo 404.

DICOM: nunca se guarda el original. `ml.dicom.derive_image` (dentro del semáforo de la
inferencia) produce una imagen derivada sin metadatos y una lista blanca técnica para
`analyses.dicom_meta`. El modelo es el de ecografías: el perfil `mastografia_prototipo` lleva
siempre el aviso de prototipo y el BI-RADS lo asigna la médica, nunca el modelo.
"""

import os
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ml.dicom import MAX_DICOM_BYTES, is_dicom
from backend.app.ml.profiles import profile_for
from backend.app.ml.quality import ImageQualityError
from backend.app.ml.service import InferenceService
from backend.app.models.clinical import Analysis, AnalysisReview, Patient
from backend.app.schemas.cases import NewPatientIn, ReviewIn
from backend.app.services import analyses, cases
from backend.app.services.auth import AuthContext
from backend.app.services.images import read_and_validate_image
from backend.app.services.storage import SupabaseStorage

DICOM_EXTENSIONS = {".dcm", ".dicom"}
DICOM_TYPES = {"application/dicom", "application/octet-stream"}


@dataclass(frozen=True)
class Upload:
    data: bytes
    dicom: bool


async def read_upload(file: UploadFile) -> Upload:
    """DICOM por extensión (o tipo) y firma; si no, la validación JPG/PNG de siempre."""
    extension = os.path.splitext(file.filename or "")[1].lower()
    if extension in DICOM_EXTENSIONS or file.content_type == "application/dicom":
        if file.content_type not in DICOM_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="El tipo MIME no coincide con un archivo DICOM.",
            )
        data = await file.read(MAX_DICOM_BYTES + 1)
        if len(data) > MAX_DICOM_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"El archivo supera el máximo de {MAX_DICOM_BYTES // (1024 * 1024)} MB.",
            )
        if not is_dicom(data):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El archivo no es un DICOM válido (falta la firma DICM).",
            )
        return Upload(data=data, dicom=True)
    image = await read_and_validate_image(file)
    return Upload(data=image.data, dicom=False)


def _own_patient(db: Session, auth: AuthContext, patient_id: uuid.UUID, ip) -> Patient:
    patient = cases._load_patient(db, auth, patient_id, ip)
    if patient.responsible_doctor_id != auth.user_id:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Acepta primero el traspaso de esta paciente para agregarle estudios",
        )
    return patient


async def add_analysis(
    db: Session,
    storage: SupabaseStorage,
    inference: InferenceService,
    auth: AuthContext,
    patient_id: uuid.UUID,
    upload: Upload,
    ip: str | None,
) -> Analysis:
    patient_id = _own_patient(db, auth, patient_id, ip).id
    db.rollback()  # libera la conexión mientras se decodifica y analiza
    try:
        if upload.dicom:
            outcome, derived = await inference.analyze_dicom(upload.data)
            profile = profile_for(is_dicom=True, modality=derived.modality)
            meta = derived.meta
        else:
            outcome = await inference.analyze(upload.data)
            profile, meta = profile_for(is_dicom=False, modality=None), None
    except ImageQualityError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from None
    # El trigger de 0017 devuelve el caso a "pendiente" al insertar el análisis
    return analyses.store_outcome(
        db,
        storage,
        auth,
        patient_id,
        outcome,
        profile=profile,
        dicom_meta=meta,
        audit=lambda analysis_id: cases._audit(
            db, auth, "case.analysis_create", "analysis", analysis_id, ip
        ),
    )


def save_review(
    db: Session, auth: AuthContext, analysis_id: uuid.UUID, data: ReviewIn, ip: str | None
) -> AnalysisReview:
    """BI-RADS y recomendación DE LA MÉDICA (una revisión por análisis; la edita quien revisa)."""
    analysis = db.scalar(
        select(Analysis)
        .join(
            Patient,
            (Patient.tenant_id == Analysis.tenant_id) & (Patient.id == Analysis.patient_id),
        )
        .where(Analysis.id == analysis_id, cases._visible(auth))
    )
    if analysis is None:
        cases._deny(db, auth, analysis_id, ip, detail="Análisis no encontrado")
    _own_patient(db, auth, analysis.patient_id, ip)
    review = db.scalar(
        select(AnalysisReview).where(AnalysisReview.analysis_id == analysis.id).with_for_update()
    )
    now = datetime.now(UTC)
    if review is None:
        review = AnalysisReview(
            patient_id=analysis.patient_id,
            analysis_id=analysis.id,
            reviewed_by=auth.user_id,
            birads=data.birads,
            recommendation=data.recommendation,
        )
        db.add(review)
    else:
        review.birads = data.birads
        review.recommendation = data.recommendation
        review.reviewed_by = auth.user_id
        review.updated_at = now
    db.flush()
    cases._audit(db, auth, "case.review", "analysis", analysis.id, ip)
    db.commit()
    db.refresh(review)
    return review


def create_patient(db: Session, auth: AuthContext, data: NewPatientIn, ip: str | None) -> Patient:
    """Alta manual de una ficha de la institución, con ella como responsable."""
    patient = Patient(
        display_name=data.display_name.strip(),
        origin="creado",
        responsible_doctor_id=auth.user_id,
        status="pendiente",
        age_years=data.age_years,
        age_recorded_on=date.today() if data.age_years is not None else None,
    )
    db.add(patient)
    db.flush()
    cases._audit(db, auth, "case.create", "patient", patient.id, ip)
    db.commit()
    db.refresh(patient)
    return patient
