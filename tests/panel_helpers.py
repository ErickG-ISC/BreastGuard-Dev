"""Fábricas compartidas por las pruebas del panel y el caso de la médica (CU-11, CU-08).

Todo se siembra como dueño (solo preparación de datos); lo que se verifica se hace con la API o
con sesiones de `app_user`.
"""

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import text

API = "/api/v1/doctor"
DOCTOR_ROUTES = [
    ("post", "/patients/search", {"json": {}}),
    ("get", "/patients/summary", {}),
    ("get", "/patients/{pid}", {}),
    ("patch", "/patients/{pid}/status", {"json": {"status": "revisado"}}),
    ("post", "/patients/{pid}/notes", {"json": {"body": "hola"}}),
    ("patch", "/notes/{nid}", {"json": {"body": "hola"}}),
    ("delete", "/notes/{nid}", {}),
]


def call(client, method: str, path: str, user=None, **kwargs):
    from tests.helpers import auth_headers

    headers = auth_headers(user) if user is not None else {}
    return getattr(client, method)(f"{API}{path}", headers=headers, **kwargs)


def name_users(owner_engine, names: dict) -> None:
    """Pone nombres distinguibles a los usuarios: name_users(engine, {user.id: "Dra. Uno"})."""
    with owner_engine.begin() as conn:
        for user_id, full_name in names.items():
            conn.execute(
                text("UPDATE control.users SET full_name = :n WHERE id = :i"),
                {"n": full_name, "i": user_id},
            )


def add_patient(
    owner_engine, tenant, doctor, name="Ficha de prueba", *, created_at=None, age=40
) -> uuid.UUID:
    pid = uuid.uuid4()
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO clinical.patients (tenant_id, id, display_name, origin, "
                "responsible_doctor_id, age_years, created_at) "
                "VALUES (:t, :id, :n, 'creado', :d, :age, :c)"
            ),
            {
                "t": tenant.id,
                "id": pid,
                "n": name,
                "d": doctor.id,
                "age": age,
                "c": created_at or datetime.now(UTC),
            },
        )
    return pid


def insert_analysis(
    conn,
    tenant,
    patient_id,
    actor,
    *,
    predicted_class="normal",
    flags=(),
    created_at=None,
    status="completed",
    image_path=None,
    heatmap_path=None,
) -> uuid.UUID:
    """Imagen + análisis con rutas bajo el prefijo del tenant (o las indicadas)."""
    image_id, analysis_id = uuid.uuid4(), uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO clinical.medical_images "
            "(tenant_id, id, patient_id, uploaded_by, object_path, image_type) "
            "VALUES (:t, :id, :p, :u, :path, 'BUSI')"
        ),
        {
            "t": tenant.id,
            "id": image_id,
            "p": patient_id,
            "u": actor.id,
            "path": image_path or f"{tenant.slug}/images/{image_id}.png",
        },
    )
    conn.execute(
        text(
            "INSERT INTO clinical.analyses (tenant_id, id, patient_id, image_id, created_by, "
            "status, predicted_class, probabilities, confidence, model_version, heatmap_path, "
            "quality_flags, report, created_at) "
            "VALUES (:t, :id, :p, :img, :u, :status, :cls, CAST(:probs AS jsonb), 0.9, 'fake', "
            ":heat, CAST(:flags AS jsonb), '{}'::jsonb, :c)"
        ),
        {
            "t": tenant.id,
            "id": analysis_id,
            "p": patient_id,
            "img": image_id,
            "u": actor.id,
            "status": status,
            "cls": predicted_class,
            "probs": json.dumps({predicted_class: 0.9}),
            "heat": heatmap_path or f"{tenant.slug}/heatmaps/{analysis_id}.png",
            "flags": json.dumps(list(flags)),
            "c": created_at or datetime.now(UTC),
        },
    )
    return analysis_id


def add_analysis(owner_engine, tenant, patient_id, actor, **kwargs) -> uuid.UUID:
    with owner_engine.begin() as conn:
        return insert_analysis(conn, tenant, patient_id, actor, **kwargs)


def set_status_as_owner(owner_engine, patient_id, new_status) -> None:
    with owner_engine.begin() as conn:
        conn.execute(
            text("UPDATE clinical.patients SET status = :s WHERE id = :i"),
            {"s": new_status, "i": patient_id},
        )


def add_note(owner_engine, tenant, patient_id, author, body="nota de prueba") -> uuid.UUID:
    nid = uuid.uuid4()
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO clinical.case_notes (tenant_id, id, patient_id, author_id, body) "
                "VALUES (:t, :id, :p, :a, :b)"
            ),
            {"t": tenant.id, "id": nid, "p": patient_id, "a": author.id, "b": body},
        )
    return nid


def patient_row(owner_engine, patient_id) -> dict:
    with owner_engine.connect() as conn:
        return dict(
            conn.execute(text("SELECT * FROM clinical.patients WHERE id = :i"), {"i": patient_id})
            .mappings()
            .one()
        )


def audit_rows(owner_engine, action: str | None = None) -> list[dict]:
    sql = "SELECT * FROM clinical.audit_log"
    params = {}
    if action:
        sql += " WHERE action = :a"
        params = {"a": action}
    with owner_engine.connect() as conn:
        return [dict(r) for r in conn.execute(text(sql), params).mappings()]
