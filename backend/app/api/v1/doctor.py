"""Rutas de la médica. Solo `doctor`, siempre con su contexto RLS (TenantDb).

- traspasos de pacientes hacia ella (0014);
- importar un paquete compartido como copia en su tenant (CU-08, ADR 0010);
- sus avisos internos (p. ej. "tienes un paquete").

- panel (CU-11) y caso (CU-08): lista, contadores, caso completo, estado y notas;
- estudios de la médica (CU-09): JPG, PNG o DICOM, revisión BI-RADS y alta manual de fichas.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status

from backend.app.api.client_ip import client_ip
from backend.app.api.deps import ControlDb, Storage, TenantDb, require_role
from backend.app.api.rate_limit import rate_limit
from backend.app.ml.deps import Inference
from backend.app.schemas.cases import (
    CaseNoteIn,
    CaseNoteOut,
    CaseOut,
    CaseStatusIn,
    CreatedOut,
    NewPatientIn,
    PanelPage,
    PanelSummary,
    PatientSearch,
    ReviewIn,
    ReviewOut,
)
from backend.app.schemas.handovers import HandoverAccepted, PendingHandoverOut
from backend.app.schemas.shares import InboxNoticeOut, ShareImport, ShareImported
from backend.app.services import cases, doctor_analyses, handovers, notices, share_import
from backend.app.services.auth import AuthContext
from backend.app.services.tenants import NotFoundError

router = APIRouter()

DoctorUser = Annotated[AuthContext, Depends(require_role("doctor"))]
WRITE_LIMIT = Depends(rate_limit("doctor_write", 30, 60))


@router.get("/handovers", response_model=list[PendingHandoverOut])
def list_pending_handovers(auth: DoctorUser, db: TenantDb):
    return handovers.pending_for_me(db, auth)


@router.post(
    "/handovers/{handover_id}/accept", response_model=HandoverAccepted, dependencies=[WRITE_LIMIT]
)
def accept_handover(handover_id: uuid.UUID, auth: DoctorUser, db: TenantDb, request: Request):
    try:
        moved = handovers.accept(db, auth, handover_id, client_ip(request))
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontrado") from None
    return HandoverAccepted(patients_moved=moved)


@router.post(
    "/shares/import",
    response_model=ShareImported,
    dependencies=[Depends(rate_limit("doctor_share_import", 10, 60))],
)
def import_share(
    data: ShareImport,
    auth: DoctorUser,
    control: ControlDb,
    db: TenantDb,
    storage: Storage,
    request: Request,
):
    result = share_import.import_package(control, db, storage, auth, data.code, client_ip(request))
    return ShareImported(
        patient_id=result.patient_id,
        analyses=result.analyses,
        symptoms=result.symptoms,
        already_imported=result.already_imported,
    )


@router.get("/notices", response_model=list[InboxNoticeOut])
def list_notices(auth: DoctorUser, db: TenantDb):
    return notices.list_own(db, auth)


@router.post("/notices/{notice_id}/read", status_code=204, dependencies=[WRITE_LIMIT])
def read_notice(notice_id: uuid.UUID, auth: DoctorUser, db: TenantDb):
    notices.mark_read(db, auth, notice_id)


# --- Panel y caso -----------------------------------------------------------------------

READ_LIMIT = Depends(rate_limit("doctor_read", 120, 60))


@router.post("/patients/search", response_model=PanelPage, dependencies=[READ_LIMIT])
def search_patients(data: PatientSearch, auth: DoctorUser, db: TenantDb, request: Request):
    return cases.search(db, auth, data, client_ip(request))


@router.get("/patients/summary", response_model=PanelSummary, dependencies=[READ_LIMIT])
def patients_summary(auth: DoctorUser, db: TenantDb, request: Request):
    return cases.summary(db, auth, client_ip(request))


@router.get("/patients/{patient_id}", response_model=CaseOut, dependencies=[READ_LIMIT])
def get_case(
    patient_id: uuid.UUID, auth: DoctorUser, db: TenantDb, storage: Storage, request: Request
):
    return cases.get_case(db, storage, auth, patient_id, client_ip(request))


@router.patch("/patients/{patient_id}/status", dependencies=[WRITE_LIMIT])
def set_case_status(
    patient_id: uuid.UUID, data: CaseStatusIn, auth: DoctorUser, db: TenantDb, request: Request
):
    result = cases.set_status(db, auth, patient_id, data.status, client_ip(request))
    return {"status": result.status, "reviewed_at": result.reviewed_at}


@router.post(
    "/patients/{patient_id}/notes",
    response_model=CaseNoteOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[WRITE_LIMIT],
)
def add_note(
    patient_id: uuid.UUID, data: CaseNoteIn, auth: DoctorUser, db: TenantDb, request: Request
):
    return cases.add_note(db, auth, patient_id, data, client_ip(request))


@router.patch("/notes/{note_id}", response_model=CaseNoteOut, dependencies=[WRITE_LIMIT])
def update_note(
    note_id: uuid.UUID, data: CaseNoteIn, auth: DoctorUser, db: TenantDb, request: Request
):
    return cases.update_note(db, auth, note_id, data, client_ip(request))


@router.delete(
    "/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[WRITE_LIMIT]
)
def delete_note(note_id: uuid.UUID, auth: DoctorUser, db: TenantDb, request: Request):
    cases.delete_note(db, auth, note_id, client_ip(request))


# --- Estudios de la médica (CU-09) --------------------------------------------------------

STUDY_LIMIT = Depends(rate_limit("doctor_analysis", 10, 60))


@router.post(
    "/patients",
    response_model=CreatedOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[WRITE_LIMIT],
)
def create_patient(data: NewPatientIn, auth: DoctorUser, db: TenantDb, request: Request):
    patient = doctor_analyses.create_patient(db, auth, data, client_ip(request))
    return CreatedOut(id=patient.id)


@router.post(
    "/patients/{patient_id}/analyses",
    response_model=CreatedOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[STUDY_LIMIT],
)
async def add_analysis(
    patient_id: uuid.UUID,
    auth: DoctorUser,
    db: TenantDb,
    storage: Storage,
    inference: Inference,
    request: Request,
    file: UploadFile = File(...),
):
    upload = await doctor_analyses.read_upload(file)
    analysis = await doctor_analyses.add_analysis(
        db, storage, inference, auth, patient_id, upload, client_ip(request)
    )
    return CreatedOut(id=analysis.id)


@router.put("/analyses/{analysis_id}/review", response_model=ReviewOut, dependencies=[WRITE_LIMIT])
def save_review(
    analysis_id: uuid.UUID, data: ReviewIn, auth: DoctorUser, db: TenantDb, request: Request
):
    review = doctor_analyses.save_review(db, auth, analysis_id, data, client_ip(request))
    return ReviewOut(
        birads=review.birads,
        recommendation=review.recommendation,
        reviewed_by_name="Tú",
        mine=True,
        updated_at=review.updated_at or review.created_at,
    )
