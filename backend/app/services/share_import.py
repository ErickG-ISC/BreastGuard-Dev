"""CU-08: la médica importa un paquete como COPIA en su propio tenant (ADR 0010).

Dos sesiones, ninguna cruza tenants:
- `control` (sin contexto): reclamar, liberar y confirmar el paquete; nunca lee `clinical`;
- `db` (TenantDb de la doctora): crear la ficha `importado` y copiar el contenido, bajo RLS de
  SU tenant y con ella como responsable.

Fases:
1. Reclamar: `UPDATE ... SET status='importando' WHERE key_hash = HMAC(código) AND vigente AND
   (sin destinataria o es ella) AND (activo o un reclamo suyo de hace más de 10 min)`. Solo una
   petición gana; cualquier otra recibe el mismo 404 ("no válido, usado o vencido").
2. Descifrar en memoria (la etiqueta de AES-GCM prueba que la llave es la correcta).
3. Copiar en una transacción del tenant de la doctora, con auditoría `share.import`.
   Si algo falla: rollback, se borra lo subido y se libera el reclamo (se puede reintentar).
4. Confirmar en control (`importado`, evento con nombres de institución y médica) y borrar el
   contenido de `transfer/`. Si el proceso muere entre 3 y 4, el reintento encuentra la ficha
   por el índice único `source_package_id` y solo confirma: nunca duplica.

Intentos fallidos: 5 por cuenta en 15 minutos (después, 429). Un código válido para OTRA
destinataria suma al paquete; a los 5, el paquete se revoca.
"""

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.api.rate_limit import limiter
from backend.app.models.clinical import (
    Analysis,
    MedicalImage,
    Patient,
    Questionnaire,
    SelfExam,
    SymptomEntry,
)
from backend.app.models.control import InboxNotice, ShareEvent, SharePackage, Tenant, User
from backend.app.services import audit, share_crypto
from backend.app.services.shares import PAYLOAD_NAME
from backend.app.services.storage import StorageError, SupabaseStorage

logger = logging.getLogger(__name__)

NOT_FOUND = "Código no válido, usado o vencido"
FAIL_LIMIT, FAIL_WINDOW = 5, 15 * 60
PACKAGE_FAIL_LIMIT = 5
STALE_CLAIM = timedelta(minutes=10)


@dataclass(frozen=True)
class ImportResult:
    patient_id: uuid.UUID
    analyses: int
    symptoms: int
    already_imported: bool


def _fail_key(user_id: uuid.UUID) -> tuple[str, str]:
    return ("share_import_fail", str(user_id))


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)


def _count_failure(control: Session, auth, lookup_hash: str | None) -> HTTPException:
    """Suma el fallo a la cuenta y, si el código es de un paquete activo ajeno, al paquete."""
    if lookup_hash is not None:
        package = control.scalar(
            select(SharePackage)
            .where(
                SharePackage.key_hash == lookup_hash,
                SharePackage.status == "activo",
                SharePackage.expires_at > datetime.now(UTC),
            )
            .with_for_update()
        )
        if package is not None:
            package.failed_attempts += 1
            control.add(ShareEvent(package_id=package.id, kind="intento_fallido"))
            if package.failed_attempts >= PACKAGE_FAIL_LIMIT:
                package.status = "revocado"
                control.add(ShareEvent(package_id=package.id, kind="revocado"))
            control.commit()
    if limiter.hit(_fail_key(auth.user_id), FAIL_LIMIT, FAIL_WINDOW) is not None:
        return _too_many()
    return _not_found()


def _too_many() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Demasiados intentos fallidos. Espera unos minutos.",
    )


def _claim(control: Session, auth, lookup_hash: str):
    now = datetime.now(UTC)
    row = control.execute(
        update(SharePackage)
        .where(
            SharePackage.key_hash == lookup_hash,
            SharePackage.expires_at > now,
            or_(
                SharePackage.recipient_user_id.is_(None),
                SharePackage.recipient_user_id == auth.user_id,
            ),
            or_(
                SharePackage.status == "activo",
                and_(
                    SharePackage.status == "importando",
                    SharePackage.claimed_by == auth.user_id,
                    SharePackage.claimed_at < now - STALE_CLAIM,
                ),
            ),
        )
        .values(status="importando", claimed_by=auth.user_id, claimed_at=now)
        .returning(SharePackage.id, SharePackage.key_hash, SharePackage.object_prefix)
    ).first()
    control.commit()
    return row


def _release(control: Session, auth, package_id: uuid.UUID) -> None:
    try:
        control.rollback()
        control.execute(
            update(SharePackage)
            .where(
                SharePackage.id == package_id,
                SharePackage.status == "importando",
                SharePackage.claimed_by == auth.user_id,
            )
            .values(status="activo", claimed_by=None, claimed_at=None)
        )
        control.commit()
    except SQLAlchemyError:
        # Si ni esto funciona, el reclamo vence solo a los 10 minutos
        logger.error("No se pudo liberar el reclamo de un paquete")


def _remove_quietly(storage: SupabaseStorage, names: list[str]) -> None:
    if not names:
        return
    try:
        storage.remove_objects(names)
    except StorageError:
        logger.error("No se pudieron limpiar objetos de una importación fallida")


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _copy(
    db: Session,
    storage: SupabaseStorage,
    auth,
    package_id: uuid.UUID,
    prefix: str,
    key: bytes,
    payload: dict,
    uploaded: list[str],
    ip: str | None,
) -> tuple[uuid.UUID, int, int]:
    def read(name: str) -> bytes:
        return share_crypto.decrypt(key, package_id, name, storage.download_bytes(prefix + name))

    person = payload.get("patient") or {}
    patient = Patient(
        display_name=person.get("display_name")
        or f"Paciente importada el {date.today().isoformat()}",
        origin="importado",
        responsible_doctor_id=auth.user_id,
        status="pendiente",
        age_years=person.get("age_years"),
        age_recorded_on=date.fromisoformat(person["age_recorded_on"])
        if person.get("age_recorded_on")
        else None,
        source_package_id=package_id,
    )
    db.add(patient)
    db.flush()

    analyses = payload.get("analyses") or []
    for item in analyses:
        image_id, analysis_id = uuid.uuid4(), uuid.uuid4()
        # Rutas nuevas bajo el prefijo del tenant de la doctora, calculadas en el servidor
        image_path = f"{auth.tenant_slug}/images/{image_id.hex}.png"
        heatmap_path = f"{auth.tenant_slug}/heatmaps/{analysis_id.hex}.png"
        storage.upload_bytes(image_path, read(item["image"]), "image/png")
        uploaded.append(image_path)
        storage.upload_bytes(heatmap_path, read(item["heatmap"]), "image/png")
        uploaded.append(heatmap_path)
        profile = item.get("profile", "ecografia_b2c")
        db.add(
            MedicalImage(
                id=image_id,
                patient_id=patient.id,
                uploaded_by=auth.user_id,
                object_path=image_path,
                image_type="BUSI" if profile == "ecografia_b2c" else "mammography",
                prediction=item["predicted_class"],
                confidence=item["confidence"],
            )
        )
        db.flush()
        db.add(
            Analysis(
                id=analysis_id,
                patient_id=patient.id,
                image_id=image_id,
                created_by=auth.user_id,
                status=item["status"],
                predicted_class=item["predicted_class"],
                probabilities=item["probabilities"],
                confidence=item["confidence"],
                model_version=item["model_version"],
                heatmap_path=heatmap_path,
                quality_flags=item["quality_flags"],
                report=item["report"],
                profile=profile,
                created_at=_dt(item.get("created_at")),
            )
        )

    refs: dict[str, uuid.UUID] = {}
    for exam in payload.get("self_exams") or []:
        exam_id = uuid.uuid4()
        refs[exam["ref"]] = exam_id
        db.add(
            SelfExam(
                id=exam_id,
                patient_id=patient.id,
                created_by=auth.user_id,
                content_version=exam["content_version"],
                started_at=_dt(exam["started_at"]),
                finished_at=_dt(exam["finished_at"]),
                noticed_change=exam["noticed_change"],
                note=exam.get("note"),
            )
        )
    db.flush()
    entries = payload.get("symptoms") or []
    for entry in entries:
        db.add(
            SymptomEntry(
                patient_id=patient.id,
                created_by=auth.user_id,
                entry_date=date.fromisoformat(entry["entry_date"]),
                side=entry["side"],
                zone=entry["zone"],
                symptoms=entry["symptoms"],
                intensity=entry["intensity"],
                note=entry.get("note"),
                self_exam_id=refs.get(entry.get("self_exam_ref")),
                cycle_day=entry.get("cycle_day"),
                in_period=entry.get("in_period"),
            )
        )
    questionnaire = payload.get("questionnaire")
    if questionnaire:
        db.add(
            Questionnaire(
                patient_id=patient.id,
                version=questionnaire["version"],
                answers=questionnaire["answers"],
                risk_factors=questionnaire["risk_factors"],
                summary_level=questionnaire["summary_level"],
                created_at=_dt(questionnaire.get("created_at")),
            )
        )
    audit.record(
        db,
        tenant_id=auth.tenant_id,
        actor_id=auth.user_id,
        actor_role=auth.role,
        action="share.import",
        resource_type="share",
        resource_id=package_id,
        ip=ip,
    )
    db.commit()
    return patient.id, len(analyses), len(entries)


def _confirm(control: Session, storage: SupabaseStorage, auth, package_id: uuid.UUID) -> None:
    package = control.scalar(
        select(SharePackage).where(SharePackage.id == package_id).with_for_update()
    )
    now = datetime.now(UTC)
    package.status = "importado"
    package.imported_at = now
    package.imported_tenant_id = auth.tenant_id
    tenant = control.get(Tenant, auth.tenant_id)
    doctor = control.get(User, auth.user_id)
    control.add(
        ShareEvent(
            package_id=package_id,
            kind="importado",
            institution_name=tenant.name,
            doctor_name=doctor.full_name,
        )
    )
    # Su aviso de "tienes un paquete", si lo tenía, queda leído
    control.execute(
        update(InboxNotice)
        .where(
            InboxNotice.user_id == auth.user_id,
            InboxNotice.ref_id == package_id,
            InboxNotice.read_at.is_(None),
        )
        .values(read_at=now)
    )
    control.commit()
    try:
        storage.remove_prefix(package.object_prefix)
    except StorageError:
        logger.error("No se pudo borrar el contenido de un paquete importado; lo hará la limpieza")
        return
    package.objects_deleted_at = datetime.now(UTC)
    control.commit()


def import_package(
    control: Session,
    db: Session,
    storage: SupabaseStorage,
    auth,
    code: str,
    ip: str | None,
) -> ImportResult:
    if limiter.blocked(_fail_key(auth.user_id), FAIL_LIMIT, FAIL_WINDOW):
        raise _too_many()
    try:
        secret = share_crypto.from_code(code)
    except share_crypto.InvalidCode:
        raise _count_failure(control, auth, None) from None

    row = _claim(control, auth, secret.lookup_hash)
    if row is None:
        mine = control.scalar(
            select(SharePackage.id).where(
                SharePackage.key_hash == secret.lookup_hash,
                SharePackage.status == "importando",
                SharePackage.claimed_by == auth.user_id,
            )
        )
        if mine is not None:
            # Un intento suyo sigue en curso (o murió hace menos de 10 minutos)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La importación de este código sigue en curso. Intenta en unos minutos.",
            )
        raise _count_failure(control, auth, secret.lookup_hash)
    package_id, prefix = row.id, row.object_prefix
    if not share_crypto.same_hash(row.key_hash, secret.lookup_hash):  # defensa en profundidad
        _release(control, auth, package_id)
        raise _not_found()

    uploaded: list[str] = []
    try:
        blob = storage.download_bytes(prefix + PAYLOAD_NAME)
        payload = json.loads(share_crypto.decrypt(secret.key, package_id, PAYLOAD_NAME, blob))
        existing = db.scalar(select(Patient.id).where(Patient.source_package_id == package_id))
        if existing is not None:
            # Una importación anterior suya se copió pero no se confirmó: solo confirmar
            db.rollback()
            result = ImportResult(existing, 0, 0, already_imported=True)
        else:
            patient_id, analyses, symptoms = _copy(
                db, storage, auth, package_id, prefix, secret.key, payload, uploaded, ip
            )
            result = ImportResult(patient_id, analyses, symptoms, already_imported=False)
    except (StorageError, share_crypto.DecryptionError, SQLAlchemyError, KeyError, ValueError):
        db.rollback()
        _remove_quietly(storage, uploaded)
        _release(control, auth, package_id)
        logger.error("Falló la importación de un paquete; se liberó el reclamo")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No se pudo importar el paquete. Intenta de nuevo.",
        ) from None
    _confirm(control, storage, auth, package_id)
    return result
