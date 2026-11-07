"""CU-11 y CU-08: panel y caso de la médica, con su contexto RLS (TenantDb).

Quién ve qué lo decide la base (ADR 0009): la doctora solo ve sus fichas y las de un traspaso
pendiente hacia ella. Además, cada consulta lleva ese mismo filtro EXPLÍCITO (defensa en
profundidad) y todo id ajeno o inexistente responde el mismo 404, auditado como `case.denied`.

"Sospechoso" sale de una sola fuente: el último análisis tiene una clase de
`MLSettings.suspicious_classes` o la marca `notable_malignant_probability`, que
`ml.quality.prediction_flags` puso al analizar con `malignant_attention_probability`.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import NoReturn

from fastapi import HTTPException, status
from sqlalchemy import and_, case, delete, func, literal, or_, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend.app.ml.profiles import PROFILES
from backend.app.ml.settings import get_settings
from backend.app.models.clinical import (
    Analysis,
    AnalysisReview,
    CaseNote,
    MedicalImage,
    Patient,
    Questionnaire,
    SelfExam,
    SymptomEntry,
)
from backend.app.models.control import PatientHandover, User
from backend.app.schemas.cases import (
    CaseAnalysisOut,
    CaseNoteIn,
    CaseNoteOut,
    CaseOut,
    CaseQuestionnaireOut,
    CaseSelfExamOut,
    CaseSymptomOut,
    LastAnalysisOut,
    PanelPage,
    PanelRow,
    PanelSummary,
    PatientSearch,
    ReviewOut,
)
from backend.app.services import audit
from backend.app.services.auth import AuthContext
from backend.app.services.storage import StorageError, SupabaseStorage, signed_url_ttl

logger = logging.getLogger(__name__)

NOT_FOUND = "Paciente no encontrada"
NOTE_NOT_FOUND = "Nota no encontrada"
NOTABLE_FLAG = "notable_malignant_probability"
PENDING_STATES = ("pendiente", "en_revision")
DIARY_DAYS = 90


def _audit(db: Session, auth: AuthContext, action: str, resource_type: str, resource_id, ip):
    audit.record(
        db,
        tenant_id=auth.tenant_id,
        actor_id=auth.user_id,
        actor_role=auth.role,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip=ip,
    )


def _deny(db: Session, auth: AuthContext, resource_id, ip, detail: str = NOT_FOUND) -> NoReturn:
    db.rollback()
    _audit(db, auth, "case.denied", "patient", resource_id, ip)
    db.commit()
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _pending_handovers():
    return PatientHandover.accepted_at.is_(None), PatientHandover.cancelled_at.is_(None)


def _incoming_sources(auth: AuthContext):
    """Médicas de origen de un traspaso pendiente hacia la del contexto (como en la regla RLS)."""
    return select(PatientHandover.from_doctor_id).where(
        PatientHandover.tenant_id == auth.tenant_id,
        PatientHandover.to_doctor_id == auth.user_id,
        *_pending_handovers(),
    )


def _visible(auth: AuthContext):
    """El mismo criterio que la política de la base, escrito de forma explícita."""
    return and_(
        Patient.tenant_id == auth.tenant_id,
        Patient.origin.in_(("importado", "creado")),
        or_(
            Patient.responsible_doctor_id == auth.user_id,
            Patient.responsible_doctor_id.in_(_incoming_sources(auth)),
        ),
    )


def is_suspicious(predicted_class: str, quality_flags: list) -> bool:
    return predicted_class in get_settings().suspicious_classes or NOTABLE_FLAG in (
        quality_flags or []
    )


def _latest_analysis():
    return (
        select(
            Analysis.id.label("id"),
            Analysis.created_at.label("created_at"),
            Analysis.predicted_class.label("predicted_class"),
            Analysis.confidence.label("confidence"),
            Analysis.status.label("status"),
            Analysis.quality_flags.label("quality_flags"),
        )
        .where(Analysis.tenant_id == Patient.tenant_id, Analysis.patient_id == Patient.id)
        .order_by(Analysis.created_at.desc(), Analysis.id.desc())
        .limit(1)
        .lateral("latest")
    )


def _suspicious_expr(latest):
    classes = sorted(get_settings().suspicious_classes)
    return and_(
        latest.c.id.is_not(None),
        or_(latest.c.predicted_class.in_(classes), latest.c.quality_flags.contains([NOTABLE_FLAG])),
    )


def _handover_names(db: Session, auth: AuthContext) -> tuple[dict[uuid.UUID, str], str | None]:
    """Origen → nombre de los traspasos hacia ella, y destino del pendiente desde ella."""
    incoming = dict(
        db.execute(
            select(PatientHandover.from_doctor_id, User.full_name)
            .join(User, User.id == PatientHandover.from_doctor_id)
            .where(
                PatientHandover.tenant_id == auth.tenant_id,
                PatientHandover.to_doctor_id == auth.user_id,
                *_pending_handovers(),
            )
        ).all()
    )
    outgoing = db.scalar(
        select(User.full_name)
        .join(PatientHandover, PatientHandover.to_doctor_id == User.id)
        .where(
            PatientHandover.tenant_id == auth.tenant_id,
            PatientHandover.from_doctor_id == auth.user_id,
            *_pending_handovers(),
        )
    )
    return incoming, outgoing


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search(db: Session, auth: AuthContext, data: PatientSearch, ip: str | None) -> PanelPage:
    latest = _latest_analysis()
    suspicious = _suspicious_expr(latest)
    conditions = [_visible(auth)]
    if data.q and data.q.strip():
        conditions.append(
            Patient.display_name.ilike(f"%{_escape_like(data.q.strip())}%", escape="\\")
        )
    if data.filter == "pendientes":
        conditions.append(Patient.status.in_(PENDING_STATES))
    elif data.filter == "revisadas":
        conditions.append(Patient.status == "revisado")
    elif data.filter == "sospechosos":
        conditions.append(suspicious)

    base = select(Patient).outerjoin(latest, literal(True)).where(*conditions)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.execute(
        select(Patient, latest, suspicious.label("suspicious"))
        .outerjoin(latest, literal(True))
        .where(*conditions)
        .order_by(
            case((suspicious, 0), else_=1),
            case((Patient.status.in_(PENDING_STATES), 0), else_=1),
            func.coalesce(latest.c.created_at, Patient.created_at).desc(),
            Patient.id,
        )
        .limit(data.limit)
        .offset(data.offset)
    ).all()
    incoming, outgoing = _handover_names(db, auth)
    items = []
    for row in rows:
        patient = row.Patient
        last = None
        if row.id is not None:
            last = LastAnalysisOut(
                created_at=row.created_at,
                predicted_class=row.predicted_class,
                confidence=row.confidence,
                inconclusive=row.status == "inconclusive",
                suspicious=bool(row.suspicious),
            )
        mine = patient.responsible_doctor_id == auth.user_id
        items.append(
            PanelRow(
                id=patient.id,
                display_name=patient.display_name,
                age_years=patient.age_years,
                origin=patient.origin,
                status=patient.status,
                created_at=patient.created_at,
                last_analysis=last,
                handover_from=None if mine else incoming.get(patient.responsible_doctor_id),
                handover_to=outgoing if mine else None,
            )
        )
    # Sin el texto buscado: la auditoría nunca guarda datos personales
    _audit(db, auth, "case.list", "patient", None, ip)
    db.commit()
    return PanelPage(items=items, total=total, limit=data.limit, offset=data.offset)


def summary(db: Session, auth: AuthContext, ip: str | None = None) -> PanelSummary:
    latest = _latest_analysis()
    suspicious = _suspicious_expr(latest)
    row = db.execute(
        select(
            func.count().filter(Patient.status.in_(PENDING_STATES)),
            func.count().filter(suspicious),
            func.count(),
        )
        .select_from(Patient)
        .outerjoin(latest, literal(True))
        .where(_visible(auth))
    ).one()
    _audit(db, auth, "case.summary", "patient", None, ip)
    db.commit()
    return PanelSummary(pending_review=row[0], suspicious=row[1], active=row[2])


def _load_patient(db: Session, auth: AuthContext, patient_id: uuid.UUID, ip, *, lock=False):
    query = select(Patient).where(Patient.id == patient_id, _visible(auth))
    if lock:
        query = query.with_for_update()
    patient = db.scalar(query)
    if patient is None:
        _deny(db, auth, patient_id, ip)
    return patient


def _names(db: Session, ids: set) -> dict[uuid.UUID, str]:
    ids = {i for i in ids if i is not None}
    if not ids:
        return {}
    return dict(db.execute(select(User.id, User.full_name).where(User.id.in_(ids))).all())


def _review_out(review, names: dict, auth: AuthContext) -> ReviewOut | None:
    if review is None:
        return None
    return ReviewOut(
        birads=review.birads,
        recommendation=review.recommendation,
        reviewed_by_name=names.get(review.reviewed_by, "Médica"),
        mine=review.reviewed_by == auth.user_id,
        updated_at=review.updated_at or review.created_at,
    )


def _note_out(note: CaseNote, names: dict, auth: AuthContext) -> CaseNoteOut:
    return CaseNoteOut(
        id=note.id,
        body=note.body,
        author_id=note.author_id,
        author_name=names.get(note.author_id, "Médica"),
        mine=note.author_id == auth.user_id,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


def get_case(
    db: Session, storage: SupabaseStorage, auth: AuthContext, patient_id: uuid.UUID, ip
) -> CaseOut:
    patient = _load_patient(db, auth, patient_id, ip)
    prefix = f"{auth.tenant_slug}/"
    ttl = signed_url_ttl()
    rows = db.execute(
        select(Analysis, MedicalImage)
        .join(
            MedicalImage,
            (MedicalImage.tenant_id == Analysis.tenant_id) & (MedicalImage.id == Analysis.image_id),
        )
        .where(Analysis.patient_id == patient.id)
        .order_by(Analysis.created_at.desc(), Analysis.id)
    ).all()
    reviews = {
        r.analysis_id: r
        for r in db.scalars(select(AnalysisReview).where(AnalysisReview.patient_id == patient.id))
    }
    reviewers = _names(db, {r.reviewed_by for r in reviews.values()})
    analyses = []
    for analysis, image in rows:
        # Pertenencia: fila visible por RLS Y rutas bajo el prefijo del tenant del JWT
        if not (image.object_path.startswith(prefix) and analysis.heatmap_path.startswith(prefix)):
            logger.error("Análisis con rutas fuera de su tenant (id=%s)", analysis.id)
            continue
        try:
            image_url = storage.create_signed_url(image.object_path, ttl)
            heatmap_url = storage.create_signed_url(analysis.heatmap_path, ttl)
        except StorageError:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail="No se pudo generar el enlace"
            ) from None
        analyses.append(
            CaseAnalysisOut(
                id=analysis.id,
                created_at=analysis.created_at,
                status=analysis.status,
                predicted_class=analysis.predicted_class,
                probabilities=analysis.probabilities,
                confidence=analysis.confidence,
                model_version=analysis.model_version,
                quality_flags=analysis.quality_flags,
                report=analysis.report,
                profile=analysis.profile,
                suspicious=is_suspicious(analysis.predicted_class, analysis.quality_flags),
                image_url=image_url,
                heatmap_url=heatmap_url,
                dicom_meta=analysis.dicom_meta,
                prototype_warning=PROFILES[analysis.profile].warning
                if analysis.profile in PROFILES
                else None,
                review=_review_out(reviews.get(analysis.id), reviewers, auth),
            )
        )

    since = date.today() - timedelta(days=DIARY_DAYS)
    entries = list(
        db.scalars(
            select(SymptomEntry)
            .where(SymptomEntry.patient_id == patient.id, SymptomEntry.entry_date >= since)
            .order_by(SymptomEntry.entry_date.desc(), SymptomEntry.created_at.desc())
        )
    )
    linked = {e.self_exam_id for e in entries if e.self_exam_id}
    exams = list(
        db.scalars(
            select(SelfExam)
            .where(
                SelfExam.patient_id == patient.id,
                or_(
                    SelfExam.started_at >= datetime.combine(since, datetime.min.time(), UTC),
                    SelfExam.id.in_(linked) if linked else literal(False),
                ),
            )
            .order_by(SelfExam.started_at.desc())
        )
    )
    questionnaire = db.scalars(
        select(Questionnaire)
        .where(Questionnaire.patient_id == patient.id)
        .order_by(Questionnaire.created_at.desc())
    ).first()
    notes = list(
        db.scalars(
            select(CaseNote)
            .where(CaseNote.patient_id == patient.id)
            .order_by(CaseNote.created_at.desc(), CaseNote.id)
        )
    )
    names = _names(db, {n.author_id for n in notes} | {patient.reviewed_by})
    incoming, outgoing = _handover_names(db, auth)
    mine = patient.responsible_doctor_id == auth.user_id
    out = CaseOut(
        id=patient.id,
        display_name=patient.display_name,
        age_years=patient.age_years,
        age_recorded_on=patient.age_recorded_on,
        origin=patient.origin,
        status=patient.status,
        created_at=patient.created_at,
        reviewed_by_name=names.get(patient.reviewed_by),
        reviewed_at=patient.reviewed_at,
        handover_from=None if mine else incoming.get(patient.responsible_doctor_id),
        handover_to=outgoing if mine else None,
        analyses=analyses,
        self_exams=[
            CaseSelfExamOut(
                id=e.id,
                started_at=e.started_at,
                finished_at=e.finished_at,
                noticed_change=e.noticed_change,
                note=e.note,
            )
            for e in exams
        ],
        symptoms=[
            CaseSymptomOut(
                id=s.id,
                entry_date=s.entry_date,
                side=s.side,
                zone=s.zone,
                symptoms=list(s.symptoms),
                intensity=s.intensity,
                note=s.note,
                self_exam_id=s.self_exam_id,
                cycle_day=s.cycle_day,
                in_period=s.in_period,
            )
            for s in entries
        ],
        questionnaire=CaseQuestionnaireOut(
            version=questionnaire.version,
            answers=questionnaire.answers,
            risk_factors=questionnaire.risk_factors,
            summary_level=questionnaire.summary_level,
            created_at=questionnaire.created_at,
        )
        if questionnaire is not None
        else None,
        notes=[_note_out(n, names, auth) for n in notes],
        signed_url_ttl=ttl,
    )
    _audit(db, auth, "case.read", "patient", patient.id, ip)
    db.commit()
    return out


@dataclass(frozen=True)
class StatusResult:
    status: str
    reviewed_at: datetime | None


def set_status(
    db: Session, auth: AuthContext, patient_id: uuid.UUID, new_status: str, ip
) -> StatusResult:
    patient = _load_patient(db, auth, patient_id, ip, lock=True)
    if patient.responsible_doctor_id != auth.user_id:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Acepta primero el traspaso de esta paciente para cambiar su estado",
        )
    try:
        db.execute(
            update(Patient)
            .where(Patient.id == patient.id, Patient.tenant_id == auth.tenant_id)
            .values(status=new_status, updated_at=datetime.now(UTC))
            .execution_options(synchronize_session=False)
        )
    except DBAPIError as exc:
        db.rollback()
        if "Transición de estado no permitida" in str(exc.orig):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Ese cambio de estado no es válido"
            ) from None
        raise
    _audit(db, auth, "case.status", "patient", patient.id, ip)
    db.commit()
    db.refresh(patient)
    return StatusResult(status=patient.status, reviewed_at=patient.reviewed_at)


def add_note(
    db: Session, auth: AuthContext, patient_id: uuid.UUID, data: CaseNoteIn, ip
) -> CaseNoteOut:
    patient = _load_patient(db, auth, patient_id, ip)
    note = CaseNote(patient_id=patient.id, author_id=auth.user_id, body=data.body)
    db.add(note)
    db.flush()
    _audit(db, auth, "case.note_create", "case_note", note.id, ip)
    db.commit()
    db.refresh(note)
    return _note_out(note, _names(db, {auth.user_id}), auth)


def _own_note(db: Session, auth: AuthContext, note_id: uuid.UUID, ip) -> CaseNote:
    note = db.scalar(
        select(CaseNote)
        .join(
            Patient, (Patient.tenant_id == CaseNote.tenant_id) & (Patient.id == CaseNote.patient_id)
        )
        .where(CaseNote.id == note_id, CaseNote.author_id == auth.user_id, _visible(auth))
        .with_for_update(of=CaseNote)
    )
    if note is None:
        # Ajena (otra autora, otra paciente u otro tenant) o inexistente: mismo 404
        db.rollback()
        _audit(db, auth, "case.denied", "case_note", note_id, ip)
        db.commit()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOTE_NOT_FOUND)
    return note


def update_note(
    db: Session, auth: AuthContext, note_id: uuid.UUID, data: CaseNoteIn, ip
) -> CaseNoteOut:
    note = _own_note(db, auth, note_id, ip)
    note.body = data.body
    note.updated_at = datetime.now(UTC)
    _audit(db, auth, "case.note_update", "case_note", note.id, ip)
    db.commit()
    db.refresh(note)
    return _note_out(note, _names(db, {auth.user_id}), auth)


def delete_note(db: Session, auth: AuthContext, note_id: uuid.UUID, ip) -> None:
    note = _own_note(db, auth, note_id, ip)
    db.execute(delete(CaseNote).where(CaseNote.id == note.id, CaseNote.tenant_id == auth.tenant_id))
    _audit(db, auth, "case.note_delete", "case_note", note_id, ip)
    db.commit()
