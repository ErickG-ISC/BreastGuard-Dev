"""Exportación de reportes (CU-10, ADR 0015): PDF y HL7 v2 simulado para la médica, y PDF sencillo
para la paciente.

Reglas, iguales para todo formato:
- siempre con el TenantDb de quien exporta (RLS) y, además, el filtro explícito de pertenencia:
  la médica, solo análisis de fichas de las que es RESPONSABLE (`cases._visible` + responsable;
  con un traspaso pendiente la de destino ve el caso pero no lo exporta); la paciente, solo los
  suyos (`analyses._own`). Ajeno o inexistente: el mismo 404 y un registro `*.denied`;
- la médica exporta solo un análisis REVISADO (con BI-RADS asignado por una médica, que figura
  como autora en el reporte): si no, 409. Los 409 también se auditan (`case.export_denied`);
- el mapa de calor se descarga solo si su ruta tiene el prefijo del tenant;
- cada exportación queda en la auditoría (`case.export_pdf`, `case.export_hl7`,
  `analysis.export_pdf`) sin contenido clínico, y el id de ese registro ES el `report_id` que
  lleva el documento;
- el nombre del archivo no lleva datos personales.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import NoReturn

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ml.profiles import PROFILES, warning_for
from backend.app.ml.report import DISCLAIMER
from backend.app.models.clinical import Analysis, AnalysisReview, Patient
from backend.app.models.control import Tenant
from backend.app.services import analyses, audit, cases
from backend.app.services.auth import AuthContext
from backend.app.services.storage import StorageError, SupabaseStorage

logger = logging.getLogger(__name__)

ANALYSIS_NOT_FOUND = "Análisis no encontrado"
NEEDS_REVIEW = "Asigna el BI-RADS y tu recomendación antes de exportar el reporte."
NEEDS_HANDOVER = "Acepta primero el traspaso de esta paciente para exportar sus reportes."


@dataclass(frozen=True)
class ReportData:
    report_id: uuid.UUID
    issued_at: datetime
    institution: str
    tenant_slug: str
    patient_ref: uuid.UUID
    patient_name: str
    approx_age: int | None
    analysis_id: uuid.UUID
    study_date: datetime
    profile: str
    profile_label: str
    predicted_class: str
    confidence: float
    model_version: str
    is_demo: bool
    analysis_status: str
    warnings: tuple[str, ...]
    heatmap_png: bytes | None
    # De la médica (None en el PDF de la paciente)
    birads: str | None = None
    recommendation: str | None = None
    reviewer_name: str | None = None
    reviewed_at: datetime | None = None
    # Reporte en lenguaje sencillo, tal como se guardó (PDF de la paciente)
    plain_report: dict | None = None


@dataclass(frozen=True)
class Export:
    content: bytes
    filename: str
    media_type: str


def approximate_age(age_years: int | None, recorded_on: date | None, today: date) -> int | None:
    """Edad aproximada hoy a partir de la edad registrada en una fecha (sin fecha de nacimiento)."""
    if age_years is None:
        return None
    if recorded_on is None:
        return age_years
    years = today.year - recorded_on.year
    if (today.month, today.day) < (recorded_on.month, recorded_on.day):
        years -= 1
    return age_years + max(years, 0)


def filename(report_id: uuid.UUID, extension: str) -> str:
    return f"breastguard-reporte-{str(report_id)[:8]}.{extension}"


def _warnings(analysis: Analysis) -> tuple[str, ...]:
    items = [DISCLAIMER]
    prototype = warning_for(analysis.profile)
    if prototype:
        items.append(prototype)
    demo = (analysis.report or {}).get("demo_notice")
    if demo:
        items.append(demo)
    return tuple(items)


def _refuse(db: Session, auth: AuthContext, analysis_id, ip, code: int, detail: str) -> NoReturn:
    """Rechazo auditado sin contenido: `case.denied` (404 uniforme, ajeno o inexistente) o
    `case.export_denied` (409: traspaso pendiente o sin revisión)."""
    db.rollback()
    action = "case.denied" if code == status.HTTP_404_NOT_FOUND else "case.export_denied"
    cases._audit(db, auth, action, "analysis", analysis_id, ip)
    db.commit()
    raise HTTPException(status_code=code, detail=detail)


def _heatmap(storage: SupabaseStorage, path: str) -> bytes:
    try:
        return storage.download_bytes(path)
    except StorageError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No se pudo preparar el reporte. Intenta de nuevo.",
        ) from None


def _institution(db: Session, auth: AuthContext) -> str:
    return db.scalar(select(Tenant.name).where(Tenant.id == auth.tenant_id)) or auth.tenant_slug


def doctor_report(
    db: Session,
    storage: SupabaseStorage,
    auth: AuthContext,
    analysis_id: uuid.UUID,
    ip,
    *,
    with_heatmap: bool = True,
) -> ReportData:
    """Datos del reporte de la médica (sin auditar todavía: ver `record_export`)."""
    row = db.execute(
        select(Analysis, Patient)
        .join(
            Patient,
            (Patient.tenant_id == Analysis.tenant_id) & (Patient.id == Analysis.patient_id),
        )
        .where(Analysis.id == analysis_id, cases._visible(auth))
    ).first()
    not_found, conflict = status.HTTP_404_NOT_FOUND, status.HTTP_409_CONFLICT
    if row is None:
        _refuse(db, auth, analysis_id, ip, not_found, ANALYSIS_NOT_FOUND)
    analysis, patient = row
    if patient.responsible_doctor_id != auth.user_id:
        _refuse(db, auth, analysis_id, ip, conflict, NEEDS_HANDOVER)
    if not analysis.heatmap_path.startswith(f"{auth.tenant_slug}/"):
        logger.error("Análisis con rutas fuera del prefijo de su tenant (id=%s)", analysis_id)
        _refuse(db, auth, analysis_id, ip, not_found, ANALYSIS_NOT_FOUND)
    review = db.scalar(select(AnalysisReview).where(AnalysisReview.analysis_id == analysis.id))
    if review is None or not review.birads:
        _refuse(db, auth, analysis_id, ip, conflict, NEEDS_REVIEW)
    names = cases._names(db, {review.reviewed_by})
    now = datetime.now(UTC)
    heatmap_path = analysis.heatmap_path
    data = dict(
        report_id=uuid.uuid4(),
        issued_at=now,
        institution=_institution(db, auth),
        tenant_slug=auth.tenant_slug,
        patient_ref=patient.id,
        patient_name=patient.display_name,
        approx_age=approximate_age(patient.age_years, patient.age_recorded_on, now.date()),
        analysis_id=analysis.id,
        study_date=analysis.created_at,
        profile=analysis.profile,
        profile_label=_profile_label(analysis.profile),
        predicted_class=analysis.predicted_class,
        confidence=analysis.confidence,
        model_version=analysis.model_version,
        is_demo="demo_notice" in (analysis.report or {}),
        analysis_status=analysis.status,
        warnings=_warnings(analysis),
        birads=review.birads,
        recommendation=review.recommendation,
        reviewer_name=names.get(review.reviewed_by, "Médica"),
        reviewed_at=review.updated_at or review.created_at,
    )
    # Se suelta la transacción (y la conexión del pool, que es chico) antes de ir a Storage y
    # generar el archivo; la auditoría abre otra transacción con el mismo contexto
    db.rollback()
    heatmap = _heatmap(storage, heatmap_path) if with_heatmap else None
    return ReportData(**data, heatmap_png=heatmap)


def patient_report(
    db: Session, storage: SupabaseStorage, auth: AuthContext, analysis_id: uuid.UUID, ip
) -> ReportData:
    """Datos del PDF sencillo de la paciente: solo sus análisis (RLS + `analyses._own`)."""
    analysis, _image = analyses._load(db, auth, analysis_id, ip)
    patient = db.scalar(select(Patient).where(Patient.id == analysis.patient_id))
    now = datetime.now(UTC)
    heatmap_path = analysis.heatmap_path  # prefijo ya validado por analyses._load
    data = dict(
        report_id=uuid.uuid4(),
        issued_at=now,
        institution="BreastGuard",
        tenant_slug=auth.tenant_slug,
        patient_ref=patient.id,
        patient_name=patient.display_name,
        approx_age=approximate_age(patient.age_years, patient.age_recorded_on, now.date()),
        analysis_id=analysis.id,
        study_date=analysis.created_at,
        profile=analysis.profile,
        profile_label=_profile_label(analysis.profile),
        predicted_class=analysis.predicted_class,
        confidence=analysis.confidence,
        model_version=analysis.model_version,
        is_demo="demo_notice" in (analysis.report or {}),
        analysis_status=analysis.status,
        warnings=_warnings(analysis),
        plain_report=analysis.report,
    )
    db.rollback()  # suelta la conexión antes de Storage y del PDF (ver doctor_report)
    return ReportData(**data, heatmap_png=_heatmap(storage, heatmap_path))


def _profile_label(code: str | None) -> str:
    profile = PROFILES.get(code or "")
    return profile.label if profile is not None else "Estudio"


def record_export(db: Session, auth: AuthContext, data: ReportData, action: str, ip) -> None:
    """Audita la exportación (sin contenido) con el report_id como id del registro y confirma."""
    audit.record(
        db,
        tenant_id=auth.tenant_id,
        actor_id=auth.user_id,
        actor_role=auth.role,
        action=action,
        resource_type="analysis",
        resource_id=data.analysis_id,
        ip=ip,
        entry_id=data.report_id,
    )
    db.commit()


def export_doctor_pdf(db, storage, auth, analysis_id, ip) -> Export:
    from backend.app.services.report_pdf import doctor_pdf

    data = doctor_report(db, storage, auth, analysis_id, ip)
    content = doctor_pdf(data)
    record_export(db, auth, data, "case.export_pdf", ip)
    return Export(content, filename(data.report_id, "pdf"), "application/pdf")


def export_doctor_hl7(db, storage, auth, analysis_id, ip) -> Export:
    from backend.app.services.hl7 import oru_r01

    data = doctor_report(db, storage, auth, analysis_id, ip, with_heatmap=False)
    content = oru_r01(data).encode("utf-8")
    record_export(db, auth, data, "case.export_hl7", ip)
    return Export(content, filename(data.report_id, "hl7"), "application/hl7-v2")


def export_patient_pdf(db, storage, auth, analysis_id, ip) -> Export:
    from backend.app.services.report_pdf import patient_pdf

    data = patient_report(db, storage, auth, analysis_id, ip)
    content = patient_pdf(data)
    record_export(db, auth, data, "analysis.export_pdf", ip)
    return Export(content, filename(data.report_id, "pdf"), "application/pdf")
