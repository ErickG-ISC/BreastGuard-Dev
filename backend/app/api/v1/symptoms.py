"""CU-04: diario de síntomas de la paciente (solo pacientes)."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from backend.app.api.client_ip import client_ip
from backend.app.api.deps import TenantDb, require_role
from backend.app.api.rate_limit import rate_limit
from backend.app.schemas.symptoms import (
    Side,
    Symptom,
    SymptomEntryIn,
    SymptomEntryOut,
    SymptomEntryPage,
    SymptomEntryUpdate,
    Zone,
)
from backend.app.services import symptoms
from backend.app.services.auth import AuthContext

router = APIRouter()

PatientUser = Annotated[AuthContext, Depends(require_role("patient"))]
WRITE_LIMIT = Depends(rate_limit("symptoms_write", 30, 60))
READ_LIMIT = Depends(rate_limit("symptoms_read", 60, 60))


@router.post(
    "",
    response_model=SymptomEntryOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[WRITE_LIMIT],
)
def create_entry(data: SymptomEntryIn, auth: PatientUser, db: TenantDb, request: Request):
    return symptoms.create(db, auth, data, client_ip(request))


@router.get("", response_model=SymptomEntryPage, dependencies=[READ_LIMIT])
def list_entries(
    auth: PatientUser,
    db: TenantDb,
    request: Request,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    symptom: Symptom | None = None,
    zone: Zone | None = None,
    side: Side | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    filters = symptoms.EntryFilters(
        date_from=date_from, date_to=date_to, symptom=symptom, zone=zone, side=side
    )
    items, total = symptoms.list_page(db, auth, filters, limit, offset, client_ip(request))
    return SymptomEntryPage(
        items=[SymptomEntryOut.model_validate(e) for e in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{entry_id}", response_model=SymptomEntryOut, dependencies=[READ_LIMIT])
def get_entry(entry_id: uuid.UUID, auth: PatientUser, db: TenantDb, request: Request):
    return symptoms.get(db, auth, entry_id, client_ip(request))


@router.patch("/{entry_id}", response_model=SymptomEntryOut, dependencies=[WRITE_LIMIT])
def update_entry(
    entry_id: uuid.UUID,
    data: SymptomEntryUpdate,
    auth: PatientUser,
    db: TenantDb,
    request: Request,
):
    return symptoms.update(db, auth, entry_id, data, client_ip(request))


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[WRITE_LIMIT])
def delete_entry(entry_id: uuid.UUID, auth: PatientUser, db: TenantDb, request: Request):
    symptoms.delete(db, auth, entry_id, client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
