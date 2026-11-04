"""Escenario de demostración por el FLUJO REAL: pacientes B2C comparten y la doctora importa.

Uso, desde la raíz del repo (contra la base de DESARROLLO):
    python -m backend.scripts.demo_flow --create --slug demo-clinica-norte [--doctor-email x]
    python -m backend.scripts.demo_flow --clean

--create (como app_user, con los mismos servicios que usa la API):
- registra pacientes SINTÉTICAS en el tenant b2c, siempre con correo `demo-paciente-…@example.com`;
- cada una analiza imágenes sintéticas, responde el cuestionario, hace una autoexploración y
  anota en su diario, y comparte un paquete;
- la doctora del tenant `demo-…` lo importa: quedan casos sospechosos y otros normales.

Los resultados son de GUION: el predictor es un doble con probabilidades fijas y versión
`demo-guion` (el modelo real no está entrenado). Nunca usar con datos ni imágenes reales.

--clean (rol dueño, como purge_tenant): borra SOLO las cuentas `demo-paciente-…@example.com` del
b2c, sus datos, sus paquetes y las copias importadas en tenants `demo-…`, y sus archivos.
"""

import argparse
import asyncio
import io
import secrets
import sys
import uuid
from dataclasses import dataclass, field
from datetime import date

from dotenv import load_dotenv

load_dotenv()

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from sqlalchemy import Engine, select, text  # noqa: E402

from backend.app.content.consent import current_consent  # noqa: E402
from backend.app.content.questionnaire import QUESTIONNAIRE_VERSION, AnswersV1  # noqa: E402
from backend.app.content.share_consent import current_share_consent  # noqa: E402
from backend.app.db import TenantContext, new_session  # noqa: E402
from backend.app.ml.config import ModelCard  # noqa: E402
from backend.app.ml.runtime import FakePredictor  # noqa: E402
from backend.app.ml.service import InferenceService  # noqa: E402
from backend.app.ml.settings import MLSettings  # noqa: E402
from backend.app.models.control import Tenant, User  # noqa: E402
from backend.app.schemas.auth import UserCreate  # noqa: E402
from backend.app.schemas.self_exam import SelfExamFinishIn  # noqa: E402
from backend.app.schemas.shares import ShareCreate  # noqa: E402
from backend.app.schemas.symptoms import SymptomEntryIn  # noqa: E402
from backend.app.services import (  # noqa: E402
    analyses,
    questionnaire,
    self_exams,
    share_import,
    shares,
    symptoms,
)
from backend.app.services.auth import AuthContext, register_patient  # noqa: E402
from backend.app.services.images import ValidatedImage  # noqa: E402

DEMO_PREFIX = "demo-"
EMAIL_PATTERN = "demo-paciente-%@example.com"
CARD = {
    "model_version": "demo-guion",
    "is_demo": True,
    "classes": ["normal", "benigno", "maligno"],
    "input_size": [224, 224],
    "color_mode": "rgb",
    "preprocessing": "raw_0_255",
    "files": {},
}
SUSPICIOUS = {"normal": 0.05, "benigno": 0.1, "maligno": 0.85}
NORMAL = {"normal": 0.9, "benigno": 0.07, "maligno": 0.03}
BENIGN = {"normal": 0.1, "benigno": 0.85, "maligno": 0.05}
# (nombre, edad, probabilidades de cada análisis en orden, ¿notó un cambio?)
PATIENTS = [
    ("Marisol Vega (demo)", 47, [NORMAL, SUSPICIOUS], "si"),
    ("Daniela Ruiz (demo)", 52, [SUSPICIOUS], "no_segura"),
    ("Paula Herrera (demo)", 38, [NORMAL], "no"),
    ("Carmen Ibarra (demo)", 61, [BENIGN, NORMAL], "no"),
]


class DemoFlowError(Exception):
    pass


@dataclass
class FlowResult:
    imported: list[str] = field(default_factory=list)
    suspicious: list[str] = field(default_factory=list)


def _ultrasound(seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    array = rng.gamma(2.0, 30.0, (360, 480)).clip(0, 255).astype(np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(array, "L").save(buffer, format="PNG")
    return buffer.getvalue()


def _doctor(slug: str, doctor_email: str | None) -> tuple[Tenant, User]:
    if not slug.startswith(DEMO_PREFIX):
        raise DemoFlowError(f"Solo tenants de demostración ({DEMO_PREFIX}…)")
    with new_session() as db:
        tenant = db.scalars(select(Tenant).where(Tenant.slug == slug)).first()
        if tenant is None or tenant.kind != "institucion":
            raise DemoFlowError(f"No existe la institución de demostración {slug!r}")
        query = select(User).where(
            User.tenant_id == tenant.id, User.role == "doctor", User.is_active.is_(True)
        )
        if doctor_email:
            query = query.where(User.email == doctor_email.lower())
        doctor = db.scalars(query.order_by(User.created_at)).first()
        if doctor is None:
            raise DemoFlowError("El tenant no tiene una doctora activa con ese correo")
        db.expunge_all()
        return tenant, doctor


def create_flow(storage, slug: str, doctor_email: str | None = None) -> FlowResult:
    tenant, doctor = _doctor(slug, doctor_email)
    doctor_auth = AuthContext(doctor.id, tenant.id, tenant.slug, "doctor")
    consent = current_consent()
    with new_session() as control:
        b2c_id = control.scalar(select(Tenant.id).where(Tenant.slug == "b2c"))
        plan = control.scalar(text("SELECT code FROM control.plans ORDER BY sort LIMIT 1"))
    result = FlowResult()
    predictor = FakePredictor(ModelCard.from_dict(CARD), NORMAL)
    inference = InferenceService(predictor, MLSettings())

    for index, (name, age, runs, noticed) in enumerate(PATIENTS):
        with new_session() as control:
            user = register_patient(
                control,
                UserCreate(
                    email=f"demo-paciente-{uuid.uuid4().hex[:10]}@example.com",
                    password=secrets.token_urlsafe(18),  # nadie inicia sesión con ella
                    full_name=name,
                    consent_accepted=True,
                    consent_version=consent.version,
                    consent_sha256=consent.sha256,
                    plan_code=plan,
                ),
            )
            user_id = user.id
        auth = AuthContext(user_id, b2c_id, "b2c", "patient")
        with new_session(TenantContext(b2c_id, user_id, "patient")) as db:
            analysis_ids = []
            for run, probabilities in enumerate(runs):
                predictor.probabilities = probabilities
                analysis = asyncio.run(
                    analyses.create(
                        db,
                        storage,
                        inference,
                        auth,
                        ValidatedImage(_ultrasound(index * 10 + run), "png", "image/png"),
                        None,
                    )
                )
                analysis_ids.append(analysis.id)
            questionnaire.submit(
                db,
                auth,
                QUESTIONNAIRE_VERSION,
                AnswersV1(
                    age=age,
                    family_history_breast="first_degree" if index % 2 == 0 else "none",
                    family_history_ovarian=False,
                    brca_mutation="unknown",
                    previous_biopsy=index == 1,
                    hormone_therapy=False,
                    current_symptoms=["lump"] if noticed == "si" else [],
                    last_checkup="more_than_2y" if index < 2 else "less_than_1y",
                ),
                None,
            )
            exam = self_exams.start(db, auth, None)
            self_exams.finish(db, auth, exam.id, SelfExamFinishIn(noticed_change=noticed), None)
            symptoms.create(
                db,
                auth,
                SymptomEntryIn(
                    entry_date=date.today(),
                    side="izquierdo",
                    zone="superior_externo",
                    symptoms=["bulto"] if noticed == "si" else ["sensibilidad"],
                    intensity=3 + index,
                    self_exam_id=exam.id,
                ),
                None,
            )
            created = shares.create(
                db,
                storage,
                lambda message: None,
                auth,
                ShareCreate(
                    analysis_ids=analysis_ids,
                    include_diary=True,
                    include_questionnaire=True,
                    include_identity=True,
                    consent_accepted=True,
                    consent_version=current_share_consent().version,
                ),
                None,
            )
        with (
            new_session() as control,
            new_session(TenantContext(tenant.id, doctor.id, "doctor")) as db,
        ):
            share_import.import_package(control, db, storage, doctor_auth, created.code, None)
        result.imported.append(name)
        if runs[-1] is SUSPICIOUS:
            result.suspicious.append(name)
    return result


def clean_flow(engine: Engine, storage) -> dict[str, int]:
    """Rol dueño con BYPASSRLS. Solo cuentas demo del b2c y copias en tenants demo-…"""
    deleted: dict[str, int] = {}
    with engine.begin() as conn:
        if not conn.execute(
            text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).scalar_one():
            raise DemoFlowError("La limpieza requiere el rol dueño con BYPASSRLS")
        users = list(
            conn.scalars(
                text(
                    "SELECT u.id FROM control.users u JOIN control.tenants t ON t.id = u.tenant_id "
                    "WHERE t.slug = 'b2c' AND u.role = 'patient' AND u.email LIKE :p"
                ),
                {"p": EMAIL_PATTERN},
            )
        )
        if not users:
            return deleted
        packages = conn.execute(
            text(
                "SELECT id, object_prefix FROM control.share_packages "
                "WHERE source_user_id = ANY(:u)"
            ),
            {"u": users},
        ).all()
        package_ids = [p.id for p in packages]
        copies_elsewhere = conn.scalar(
            text(
                "SELECT count(*) FROM clinical.patients p "
                "JOIN control.tenants t ON t.id = p.tenant_id "
                "WHERE p.source_package_id = ANY(:k) AND t.slug NOT LIKE 'demo-%'"
            ),
            {"k": package_ids},
        )
        if copies_elsewhere:
            raise DemoFlowError(
                "Algún paquete demo se importó en un tenant que no es de demostración; "
                "no se borra nada (revísalo a mano)"
            )
        patients = list(
            conn.scalars(
                text(
                    "SELECT id FROM clinical.patients "
                    "WHERE user_id = ANY(:u) OR source_package_id = ANY(:k)"
                ),
                {"u": users, "k": package_ids},
            )
        )
        paths = list(
            conn.scalars(
                text(
                    "SELECT object_path FROM clinical.medical_images WHERE patient_id = ANY(:p) "
                    "UNION ALL SELECT heatmap_path FROM clinical.analyses "
                    "WHERE patient_id = ANY(:p)"
                ),
                {"p": patients},
            )
        )
        for table in (
            "analysis_reviews",
            "case_notes",
            "analyses",
            "medical_images",
            "symptom_entries",
            "self_exams",
            "questionnaires",
            "patients",
        ):
            column = "id" if table == "patients" else "patient_id"
            result = conn.execute(
                text(f"DELETE FROM clinical.{table} WHERE {column} = ANY(:p)"), {"p": patients}
            )
            deleted[f"clinical.{table}"] = result.rowcount
        result = conn.execute(
            text("DELETE FROM clinical.audit_log WHERE actor_id = ANY(:u)"), {"u": users}
        )
        deleted["clinical.audit_log"] = result.rowcount
        for table, where in (
            ("inbox_notices", "user_id = ANY(:u) OR ref_id = ANY(:k)"),
            ("share_packages", "source_user_id = ANY(:u)"),
            ("reminder_notices", "user_id = ANY(:u)"),
            ("reminders", "user_id = ANY(:u)"),
            ("consents", "user_id = ANY(:u)"),
            ("subscriptions", "user_id = ANY(:u)"),
            ("users", "id = ANY(:u)"),
        ):
            result = conn.execute(
                text(f"DELETE FROM control.{table} WHERE {where}"), {"u": users, "k": package_ids}
            )
            deleted[f"control.{table}"] = result.rowcount
    # Archivos después del commit (Storage no es transaccional)
    if paths:
        storage.remove_objects(paths)
    for package in packages:
        storage.remove_prefix(package.object_prefix)
    deleted["storage"] = len(paths)
    return deleted


def main() -> int:
    import os

    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    from backend.app.services.storage import SupabaseStorage

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--create", action="store_true")
    action.add_argument("--clean", action="store_true")
    parser.add_argument("--slug", default="demo-clinica-norte")
    parser.add_argument("--doctor-email")
    args = parser.parse_args()
    target = make_url(os.environ["DATABASE_URL"])
    print(f"Base de destino: {target.host}:{target.port}/{target.database}")
    try:
        if args.create:
            result = create_flow(SupabaseStorage(), args.slug, args.doctor_email)
            print(f"Importadas en {args.slug}: {', '.join(result.imported)}")
            print(f"Sospechosas: {', '.join(result.suspicious)}")
            return 0
        typed = input("Esto borra las pacientes demo-paciente-… y sus copias. Escribe 'demo': ")
        if typed.strip() != "demo":
            print("Confirmación incorrecta; no se borró nada.", file=sys.stderr)
            return 1
        engine = create_engine(os.environ["DATABASE_URL"])
        try:
            deleted = clean_flow(engine, SupabaseStorage())
        finally:
            engine.dispose()
        for name, count in deleted.items():
            print(f"Borrados {count} de {name}")
        return 0
    except Exception as exc:  # mensaje claro para el operador, sin trazas con datos
        print(f"No se pudo completar: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
