"""CU-07: la paciente comparte una copia cifrada con su médica (ADR 0010).

Crear (TenantDb de la paciente):
1. lee BAJO RLS y con su filtro de pertenencia lo que eligió (análisis propios, diario de 90
   días, cuestionario) y valida que cada ruta de Storage empiece por `{su_slug}/`: solo se
   copian objetos que la paciente posee y las rutas salen de sus filas, nunca del cliente;
2. suelta la conexión, descarga cada imagen y heatmap, los cifra con la llave del código
   (AES-GCM) y los sube a `transfer/{uuid}/`; el contenido (JSON) va cifrado en `payload.bin`;
3. en una transacción: fila en `control.share_packages` (solo el HMAC del código), evento
   `creado`, aviso a la destinataria si es una doctora activa y `share.create` en su auditoría;
4. el código se devuelve una sola vez. Si algo falla, se borra lo subido.

Revocar y limpiar solo tocan control y Storage; nunca leen `clinical`.
La importación (CU-08) llega en la rama siguiente.
"""

import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from backend.app.content.share_consent import current_share_consent
from backend.app.models.clinical import Analysis, MedicalImage, Patient, Questionnaire, SelfExam
from backend.app.models.control import InboxNotice, ShareEvent, SharePackage, Tenant, User
from backend.app.schemas.shares import ShareCreate, ShareCreated, ShareEventOut, ShareOut
from backend.app.services import audit, share_crypto, symptoms
from backend.app.services import email as email_service
from backend.app.services.auth import AuthContext
from backend.app.services.storage import StorageError, SupabaseStorage

logger = logging.getLogger(__name__)

PAYLOAD_NAME = "payload.bin"
PAYLOAD_FORMAT = 1
DIARY_DAYS = 90
MAX_BYTES = 25 * 1024 * 1024
MAX_ACTIVE = 5
CLEANUP_BATCH = 50
NOT_FOUND = "Paquete no encontrado"


def _audit(db: Session, auth: AuthContext, action: str, package_id, ip: str | None) -> None:
    audit.record(
        db,
        tenant_id=auth.tenant_id,
        actor_id=auth.user_id,
        actor_role=auth.role,
        action=action,
        resource_type="share",
        resource_id=package_id,
        ip=ip,
    )


def import_link(code: str) -> str:
    """Enlace con el código en el FRAGMENTO: no llega al servidor, a los logs ni al Referer."""
    base = os.environ.get("PUBLIC_APP_URL", "http://localhost:5173").rstrip("/")
    return f"{base}/importar#c={code}"


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


@dataclass
class _Snapshot:
    """Lo leído bajo RLS antes de soltar la conexión: datos y rutas de Storage propias."""

    payload: dict
    objects: list[tuple[str, str]]  # (ruta de origen en Storage, nombre cifrado en transfer/)


def _read_own(db: Session, auth: AuthContext, data: ShareCreate) -> _Snapshot:
    patient = db.scalars(select(Patient).where(Patient.user_id == auth.user_id)).first()
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ficha no encontrada")
    prefix = f"{auth.tenant_slug}/"
    objects: list[tuple[str, str]] = []
    payload: dict = {"format": PAYLOAD_FORMAT, "patient": {}}

    if data.analysis_ids:
        rows = db.execute(
            select(Analysis, MedicalImage)
            .join(
                MedicalImage,
                (MedicalImage.tenant_id == Analysis.tenant_id)
                & (MedicalImage.id == Analysis.image_id),
            )
            .where(Analysis.patient_id == patient.id, Analysis.id.in_(data.analysis_ids))
            .order_by(Analysis.created_at)
        ).all()
        if len(rows) != len(data.analysis_ids):
            # Ajeno o inexistente: misma respuesta, sin decir cuál
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Algún análisis elegido no está disponible",
            )
        analyses = []
        for analysis, image in rows:
            if not (
                image.object_path.startswith(prefix) and analysis.heatmap_path.startswith(prefix)
            ):
                logger.error("Análisis con rutas fuera de su tenant (id=%s)", analysis.id)
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Algún análisis elegido no está disponible",
                )
            image_name, heatmap_name = f"{uuid.uuid4().hex}.bin", f"{uuid.uuid4().hex}.bin"
            objects += [(image.object_path, image_name), (analysis.heatmap_path, heatmap_name)]
            analyses.append(
                {
                    "created_at": _iso(analysis.created_at),
                    "status": analysis.status,
                    "predicted_class": analysis.predicted_class,
                    "probabilities": analysis.probabilities,
                    "confidence": analysis.confidence,
                    "model_version": analysis.model_version,
                    "quality_flags": analysis.quality_flags,
                    "report": analysis.report,
                    "profile": analysis.profile,
                    "image": image_name,
                    "heatmap": heatmap_name,
                }
            )
        payload["analyses"] = analyses

    if data.include_diary:
        since = date.today() - timedelta(days=DIARY_DAYS)
        exams = list(
            db.scalars(
                select(SelfExam)
                .where(
                    SelfExam.patient_id == patient.id,
                    SelfExam.finished_at.is_not(None),
                    SelfExam.started_at >= datetime.combine(since, datetime.min.time(), UTC),
                )
                .order_by(SelfExam.started_at)
            )
        )
        refs = {exam.id: f"e{index}" for index, exam in enumerate(exams)}
        payload["self_exams"] = [
            {
                "ref": refs[exam.id],
                "content_version": exam.content_version,
                "started_at": _iso(exam.started_at),
                "finished_at": _iso(exam.finished_at),
                "noticed_change": exam.noticed_change,
                "note": exam.note if data.include_notes else None,
            }
            for exam in exams
        ]
        payload["symptoms"] = [
            {
                "entry_date": entry.entry_date.isoformat(),
                "side": entry.side,
                "zone": entry.zone,
                "symptoms": list(entry.symptoms),
                "intensity": entry.intensity,
                "note": entry.note if data.include_notes else None,
                "self_exam_ref": refs.get(entry.self_exam_id),
                "cycle_day": entry.cycle_day,
                "in_period": entry.in_period,
            }
            for entry in symptoms.get_entries(db, auth, since)
        ]

    latest = db.scalars(
        select(Questionnaire)
        .where(Questionnaire.patient_id == patient.id)
        .order_by(Questionnaire.created_at.desc())
    ).first()
    if data.include_questionnaire and latest is not None:
        payload["questionnaire"] = {
            "version": latest.version,
            "answers": latest.answers,
            "risk_factors": latest.risk_factors,
            "summary_level": latest.summary_level,
            "created_at": _iso(latest.created_at),
        }
    if data.include_identity:
        payload["patient"]["display_name"] = patient.display_name
        age = (latest.answers or {}).get("age") if latest is not None else None
        if isinstance(age, int):
            # Edad a la fecha del cuestionario, nunca fecha de nacimiento (ADR 0009)
            payload["patient"]["age_years"] = age
            payload["patient"]["age_recorded_on"] = latest.created_at.date().isoformat()
    return _Snapshot(payload=payload, objects=objects)


def _resolve_recipient(db: Session, email: str | None) -> User | None:
    """Solo si es una doctora activa de una institución activa. Nunca se le dice a la paciente."""
    if not email:
        return None
    return db.scalars(
        select(User)
        .join(Tenant, Tenant.id == User.tenant_id)
        .where(
            func.lower(User.email) == email,
            User.role == "doctor",
            User.is_active.is_(True),
            Tenant.kind == "institucion",
            Tenant.is_active.is_(True),
        )
    ).first()


def _remove_quietly(storage: SupabaseStorage, names: list[str]) -> None:
    if not names:
        return
    try:
        storage.remove_objects(names)
    except StorageError:
        logger.error("No se pudieron limpiar objetos del paquete; los borrará la limpieza")


def create(
    db: Session,
    storage: SupabaseStorage,
    sender: email_service.EmailSender,
    auth: AuthContext,
    data: ShareCreate,
    ip: str | None,
) -> ShareCreated:
    consent = current_share_consent()
    if data.consent_version != consent.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El texto de consentimiento cambió; léelo de nuevo",
        )
    now = datetime.now(UTC)
    active = db.scalar(
        select(func.count())
        .select_from(SharePackage)
        .where(
            SharePackage.source_tenant_id == auth.tenant_id,
            SharePackage.source_user_id == auth.user_id,
            SharePackage.status == "activo",
            SharePackage.expires_at > now,
        )
    )
    if active >= MAX_ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya tienes {MAX_ACTIVE} paquetes activos; revoca alguno antes",
        )
    snapshot = _read_own(db, auth, data)
    # Libera la conexión mientras se copian y cifran los archivos
    db.rollback()

    package_id = uuid.uuid4()
    prefix = f"transfer/{package_id.hex}/"
    secret = share_crypto.new_secret()
    uploaded: list[str] = []
    size = 0
    try:
        for source, name in snapshot.objects:
            plain = storage.download_bytes(source)
            size += len(plain)
            if size > MAX_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="El paquete supera 25 MB; elige menos análisis",
                )
            target = prefix + name
            storage.upload_bytes(
                target,
                share_crypto.encrypt(secret.key, package_id, name, plain),
                "application/octet-stream",
            )
            uploaded.append(target)
        body = json.dumps(snapshot.payload, ensure_ascii=False).encode("utf-8")
        size += len(body)
        storage.upload_bytes(
            prefix + PAYLOAD_NAME,
            share_crypto.encrypt(secret.key, package_id, PAYLOAD_NAME, body),
            "application/octet-stream",
        )
        uploaded.append(prefix + PAYLOAD_NAME)
    except StorageError:
        _remove_quietly(storage, uploaded)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No se pudo preparar el paquete. Intenta de nuevo.",
        ) from None
    except HTTPException:
        _remove_quietly(storage, uploaded)
        raise

    sections = {
        "analyses": bool(data.analysis_ids),
        "diary": data.include_diary,
        "questionnaire": "questionnaire" in snapshot.payload,
        "notes": data.include_notes,
        "identity": data.include_identity,
    }
    try:
        recipient = _resolve_recipient(db, data.recipient_email)
        expires_at = datetime.now(UTC) + timedelta(hours=data.expires_in_hours)
        db.add(
            SharePackage(
                id=package_id,
                source_tenant_id=auth.tenant_id,
                source_user_id=auth.user_id,
                key_hash=secret.lookup_hash,
                expires_at=expires_at,
                recipient_email=data.recipient_email,
                recipient_user_id=recipient.id if recipient else None,
                sections=sections,
                analyses_count=len(data.analysis_ids),
                size_bytes=size,
                consent_version=consent.version,
                consent_sha256=consent.sha256,
                consented_at=datetime.now(UTC),
                object_prefix=prefix,
            )
        )
        db.flush()
        db.add(ShareEvent(package_id=package_id, kind="creado"))
        if recipient is not None:
            db.add(
                InboxNotice(
                    tenant_id=recipient.tenant_id,
                    user_id=recipient.id,
                    kind="share_received",
                    ref_id=package_id,
                )
            )
        _audit(db, auth, "share.create", package_id, ip)
        db.commit()
    except Exception:
        db.rollback()
        _remove_quietly(storage, uploaded)
        raise

    if recipient is not None:
        try:
            sender.send(email_service.compose_share_notice(to=recipient.email))
        except Exception as exc:  # el aviso en la app ya quedó; el correo es un extra
            logger.warning("No se pudo enviar el aviso del paquete (%s)", type(exc).__name__)
    return ShareCreated(
        id=package_id, code=secret.code, link=import_link(secret.code), expires_at=expires_at
    )


def _visible_status(package: SharePackage, now: datetime) -> str:
    if package.status in ("activo", "importando") and package.expires_at <= now:
        return "caducado"
    return package.status


def _own_packages(auth: AuthContext):
    return (
        SharePackage.source_tenant_id == auth.tenant_id,
        SharePackage.source_user_id == auth.user_id,
    )


def list_own(db: Session, auth: AuthContext) -> list[ShareOut]:
    packages = list(
        db.scalars(
            select(SharePackage)
            .where(*_own_packages(auth))
            .order_by(SharePackage.created_at.desc(), SharePackage.id)
            .limit(50)
        )
    )
    events: dict[uuid.UUID, list[ShareEvent]] = {p.id: [] for p in packages}
    if packages:
        for event in db.scalars(
            select(ShareEvent)
            .where(ShareEvent.package_id.in_(events))
            .order_by(ShareEvent.occurred_at, ShareEvent.id)
        ):
            events[event.package_id].append(event)
    now = datetime.now(UTC)
    return [
        ShareOut(
            id=p.id,
            status=_visible_status(p, now),
            created_at=p.created_at,
            expires_at=p.expires_at,
            sections=p.sections,
            analyses_count=p.analyses_count,
            recipient_email=p.recipient_email,
            events=[ShareEventOut.model_validate(e) for e in events[p.id]],
        )
        for p in packages
    ]


def revoke(
    db: Session, storage: SupabaseStorage, auth: AuthContext, package_id: uuid.UUID, ip
) -> None:
    package = db.scalar(
        select(SharePackage)
        .where(SharePackage.id == package_id, *_own_packages(auth))
        .with_for_update()
    )
    if package is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    if _visible_status(package, datetime.now(UTC)) != "activo":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="El paquete ya no está activo"
        )
    package.status = "revocado"
    db.add(ShareEvent(package_id=package.id, kind="revocado"))
    _audit(db, auth, "share.revoke", package.id, ip)
    db.commit()
    # Sin el código el contenido ya es ilegible; borrarlo es higiene. Si falla, lo hará la limpieza
    try:
        storage.remove_prefix(package.object_prefix)
    except StorageError:
        logger.error("No se pudo borrar el contenido de un paquete revocado")
        return
    package.objects_deleted_at = datetime.now(UTC)
    db.commit()


@dataclass(frozen=True)
class CleanupResult:
    expired: int
    purged: int
    failed: int


def cleanup(db: Session, storage: SupabaseStorage) -> CleanupResult:
    """Tarea programada (sesión de control sin contexto): caduca y borra contenido cerrado."""
    expired = list(
        db.scalars(
            update(SharePackage)
            .where(
                SharePackage.status.in_(("activo", "importando")),
                SharePackage.expires_at <= func.now(),
            )
            .values(status="caducado")
            .returning(SharePackage.id)
        )
    )
    for package_id in expired:
        db.add(ShareEvent(package_id=package_id, kind="caducado"))
    db.commit()

    closed = list(
        db.scalars(
            select(SharePackage)
            .where(
                SharePackage.status.in_(("revocado", "caducado", "importado")),
                SharePackage.objects_deleted_at.is_(None),
            )
            .order_by(SharePackage.created_at)
            .limit(CLEANUP_BATCH)
            .with_for_update(skip_locked=True)
        )
    )
    purged = failed = 0
    for package in closed:
        try:
            storage.remove_prefix(package.object_prefix)
        except StorageError:
            failed += 1
            continue
        package.objects_deleted_at = datetime.now(UTC)
        purged += 1
    db.commit()
    return CleanupResult(expired=len(expired), purged=purged, failed=failed)
