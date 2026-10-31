"""Administración de plataforma (CU-12, ADR 0008). Solo platform_admin; solo esquema control.

El platform_admin gestiona tenants y su personal, pero no ve datos clínicos: las estadísticas
son de control. Cada cambio queda en la bitácora de plataforma (control.admin_events).
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from backend.app.api.client_ip import client_ip
from backend.app.api.deps import ControlDb, Sender, require_role
from backend.app.api.rate_limit import rate_limit
from backend.app.schemas.handovers import HandoverCreate, HandoverList, HandoverOut
from backend.app.schemas.tenants import (
    AdminEventOut,
    AdminEventPage,
    InvitationSent,
    IsolationReport,
    PurgeRequest,
    StaffInvite,
    StaffInvited,
    StaffList,
    StaffOut,
    StaffUpdate,
    TenantCreate,
    TenantCreated,
    TenantOut,
    TenantPage,
    TenantSummary,
    TenantUpdate,
)
from backend.app.services import admin_events, handovers, invitations, user_admin
from backend.app.services import tenants as service
from backend.app.services.auth import AuthContext

router = APIRouter()

PlatformAdmin = Annotated[AuthContext, Depends(require_role("platform_admin"))]
WRITE_LIMIT = Depends(rate_limit("admin_write", 60, 60))


def _summary(item: service.TenantWithStats) -> TenantSummary:
    return TenantSummary(**TenantOut.model_validate(item.tenant).model_dump(), stats=item.stats)


def admin_errors(exc: Exception) -> HTTPException:
    """Traduce errores de servicio; 404 uniforme para lo inexistente o fuera de alcance."""
    if isinstance(exc, service.NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontrado")
    if isinstance(exc, service.ConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, service.InvalidOperationError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    raise exc


ADMIN_ERRORS = (service.NotFoundError, service.ConflictError, service.InvalidOperationError)


# --- Tenants -------------------------------------------------------------------------------


@router.get("/tenants", response_model=TenantPage)
def list_tenants(
    auth: PlatformAdmin,
    db: ControlDb,
    q: Annotated[str | None, Query(max_length=100)] = None,
    active: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    items, total = service.list_tenants(db, q=q, active=active, limit=limit, offset=offset)
    return TenantPage(items=[_summary(i) for i in items], total=total, limit=limit, offset=offset)


@router.post(
    "/tenants",
    response_model=TenantCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[WRITE_LIMIT],
)
def create_tenant(
    data: TenantCreate, auth: PlatformAdmin, db: ControlDb, sender: Sender, request: Request
):
    try:
        tenant, admin, token = service.create_tenant(db, auth, data, client_ip(request))
    except ADMIN_ERRORS as exc:
        raise admin_errors(exc) from None
    sent = invitations.send(
        sender, user=admin, institution=tenant.name, purpose="invite", token=token
    )
    return TenantCreated(
        tenant=TenantOut.model_validate(tenant), admin_user_id=admin.id, email_sent=sent
    )


@router.get("/tenants/{tenant_id}", response_model=TenantSummary)
def get_tenant(tenant_id: uuid.UUID, auth: PlatformAdmin, db: ControlDb):
    try:
        return _summary(service.get_tenant(db, tenant_id))
    except ADMIN_ERRORS as exc:
        raise admin_errors(exc) from None


@router.patch("/tenants/{tenant_id}", response_model=TenantSummary, dependencies=[WRITE_LIMIT])
def update_tenant(
    tenant_id: uuid.UUID, data: TenantUpdate, auth: PlatformAdmin, db: ControlDb, request: Request
):
    try:
        return _summary(service.update_tenant(db, auth, tenant_id, data, client_ip(request)))
    except ADMIN_ERRORS as exc:
        raise admin_errors(exc) from None


@router.post(
    "/tenants/{tenant_id}/purge-request",
    response_model=TenantSummary,
    dependencies=[WRITE_LIMIT],
)
def request_purge(
    tenant_id: uuid.UUID, data: PurgeRequest, auth: PlatformAdmin, db: ControlDb, request: Request
):
    """Solo SOLICITA la purga (desactiva y marca); la ejecuta purge_tenant.py --pending."""
    try:
        item = service.request_purge(db, auth, tenant_id, data.confirm_slug, client_ip(request))
    except ADMIN_ERRORS as exc:
        raise admin_errors(exc) from None
    return _summary(item)


@router.delete(
    "/tenants/{tenant_id}/purge-request",
    response_model=TenantSummary,
    dependencies=[WRITE_LIMIT],
)
def cancel_purge(tenant_id: uuid.UUID, auth: PlatformAdmin, db: ControlDb, request: Request):
    try:
        return _summary(service.cancel_purge(db, auth, tenant_id, client_ip(request)))
    except ADMIN_ERRORS as exc:
        raise admin_errors(exc) from None


@router.post(
    "/tenants/{tenant_id}/isolation-check",
    response_model=IsolationReport,
    dependencies=[Depends(rate_limit("admin_isolation_check", 10, 60))],
)
def isolation_check(tenant_id: uuid.UUID, auth: PlatformAdmin):
    try:
        return service.isolation_check(auth, tenant_id)
    except ADMIN_ERRORS as exc:
        raise admin_errors(exc) from None


# --- Personal de cualquier tenant --------------------------------------------------------


@router.get("/tenants/{tenant_id}/users", response_model=StaffList)
def list_staff(tenant_id: uuid.UUID, auth: PlatformAdmin, db: ControlDb):
    try:
        staff, patients = user_admin.list_staff(db, user_admin.Scope.for_actor(auth), tenant_id)
    except ADMIN_ERRORS as exc:
        raise admin_errors(exc) from None
    return StaffList(items=[user_admin.to_out(u) for u in staff], patients=patients)


@router.post(
    "/tenants/{tenant_id}/users",
    response_model=StaffInvited,
    status_code=status.HTTP_201_CREATED,
    dependencies=[WRITE_LIMIT],
)
def invite_staff(
    tenant_id: uuid.UUID,
    data: StaffInvite,
    auth: PlatformAdmin,
    db: ControlDb,
    sender: Sender,
    request: Request,
):
    try:
        user, sent = user_admin.invite_staff(
            db, user_admin.Scope.for_actor(auth), tenant_id, data, sender, client_ip(request)
        )
    except ADMIN_ERRORS as exc:
        raise admin_errors(exc) from None
    return StaffInvited(user=user_admin.to_out(user), email_sent=sent)


@router.patch("/users/{user_id}", response_model=StaffOut, dependencies=[WRITE_LIMIT])
def update_staff(
    user_id: uuid.UUID, data: StaffUpdate, auth: PlatformAdmin, db: ControlDb, request: Request
):
    try:
        user = user_admin.update_staff(
            db, user_admin.Scope.for_actor(auth), user_id, data, client_ip(request)
        )
    except ADMIN_ERRORS as exc:
        raise admin_errors(exc) from None
    return user_admin.to_out(user)


@router.post(
    "/users/{user_id}/invitation", response_model=InvitationSent, dependencies=[WRITE_LIMIT]
)
def resend_invitation(
    user_id: uuid.UUID, auth: PlatformAdmin, db: ControlDb, sender: Sender, request: Request
):
    try:
        sent = user_admin.resend_invitation(
            db, user_admin.Scope.for_actor(auth), user_id, sender, client_ip(request)
        )
    except ADMIN_ERRORS as exc:
        raise admin_errors(exc) from None
    return InvitationSent(email_sent=sent)


@router.post(
    "/users/{user_id}/reset-access", response_model=InvitationSent, dependencies=[WRITE_LIMIT]
)
def reset_access(
    user_id: uuid.UUID, auth: PlatformAdmin, db: ControlDb, sender: Sender, request: Request
):
    try:
        sent = user_admin.reset_access(
            db, user_admin.Scope.for_actor(auth), user_id, sender, client_ip(request)
        )
    except ADMIN_ERRORS as exc:
        raise admin_errors(exc) from None
    return InvitationSent(email_sent=sent)


# --- Traspaso de pacientes entre médicas (0014) -----------------------------------------


@router.post(
    "/users/{user_id}/handover",
    response_model=HandoverOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[WRITE_LIMIT],
)
def create_handover(
    user_id: uuid.UUID, data: HandoverCreate, auth: PlatformAdmin, db: ControlDb, request: Request
):
    try:
        return handovers.create(
            db, user_admin.Scope.for_actor(auth), user_id, data, client_ip(request)
        )
    except ADMIN_ERRORS as exc:
        raise admin_errors(exc) from None


@router.get("/tenants/{tenant_id}/handovers", response_model=HandoverList)
def list_handovers(tenant_id: uuid.UUID, auth: PlatformAdmin, db: ControlDb):
    try:
        items = handovers.list_for_tenant(db, user_admin.Scope.for_actor(auth), tenant_id)
    except ADMIN_ERRORS as exc:
        raise admin_errors(exc) from None
    return HandoverList(items=items)


@router.delete("/handovers/{handover_id}", response_model=HandoverOut, dependencies=[WRITE_LIMIT])
def cancel_handover(handover_id: uuid.UUID, auth: PlatformAdmin, db: ControlDb, request: Request):
    try:
        return handovers.cancel(
            db, user_admin.Scope.for_actor(auth), handover_id, client_ip(request)
        )
    except ADMIN_ERRORS as exc:
        raise admin_errors(exc) from None


# --- Bitácora de plataforma ---------------------------------------------------------------


@router.get("/events", response_model=AdminEventPage)
def list_events(
    auth: PlatformAdmin,
    db: ControlDb,
    tenant_id: uuid.UUID | None = None,
    action: Annotated[str | None, Query(max_length=64)] = None,
    date_from: Annotated[datetime | None, Query(alias="from")] = None,
    date_to: Annotated[datetime | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    filters = admin_events.EventFilters(
        tenant_id=tenant_id, action=action, date_from=date_from, date_to=date_to
    )
    items, total = admin_events.list_events(
        db, only_tenant=None, filters=filters, limit=limit, offset=offset
    )
    return AdminEventPage(
        items=[AdminEventOut.model_validate(e) for e in items],
        total=total,
        limit=limit,
        offset=offset,
    )
