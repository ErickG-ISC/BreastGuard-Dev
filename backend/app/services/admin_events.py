"""Bitácora de plataforma (ADR 0008): cambios administrativos en el esquema control.

Quién, acción, tenant, objetivo, cuándo e IP. Sin datos sensibles: `details` solo admite claves
de una lista blanca (nombres de campos cambiados, rol y plan), nunca correos, tokens ni
contraseñas. La tabla es de solo inserción para app_user (sin UPDATE ni DELETE).

Se escribe en la MISMA transacción que la acción: si la acción se revierte, el evento también.
"""

import ipaddress
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from backend.app.models.control import AdminEvent

ALLOWED_DETAIL_KEYS = {
    "fields",
    "role",
    "previous_role",
    "plan",
    "purpose",
    "email_sent",
    # Traspasos de pacientes (0014): a quién y cuántas fichas pasaron, nunca cuáles
    "to_user_id",
    "patients_moved",
}


@dataclass(frozen=True)
class EventFilters:
    tenant_id: uuid.UUID | None = None
    action: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


def _clean_ip(ip: str | None) -> str | None:
    if not ip:
        return None
    try:
        return str(ipaddress.ip_address(ip))
    except ValueError:
        return None


def record(
    db: Session,
    *,
    actor_id: uuid.UUID | None,
    actor_role: str,
    action: str,
    tenant_id: uuid.UUID | None,
    target_type: str,
    target_id: uuid.UUID | None,
    ip: str | None,
    details: dict | None = None,
) -> None:
    details = details or {}
    unknown = set(details) - ALLOWED_DETAIL_KEYS
    if unknown:
        # Programación defensiva: una clave nueva debe revisarse antes de guardarse
        raise ValueError(f"Claves no permitidas en la bitácora: {sorted(unknown)}")
    db.execute(
        insert(AdminEvent).values(
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            tenant_id=tenant_id,
            target_type=target_type,
            target_id=target_id,
            ip=_clean_ip(ip),
            details=details,
        )
    )


def list_events(
    db: Session,
    *,
    only_tenant: uuid.UUID | None,
    filters: EventFilters,
    limit: int,
    offset: int,
) -> tuple[list[AdminEvent], int]:
    """`only_tenant` es el alcance obligatorio del tenant_admin (de su JWT); None = plataforma."""
    conditions = []
    if only_tenant is not None:
        conditions.append(AdminEvent.tenant_id == only_tenant)
    if filters.tenant_id is not None:
        conditions.append(AdminEvent.tenant_id == filters.tenant_id)
    if filters.action:
        conditions.append(AdminEvent.action == filters.action)
    if filters.date_from is not None:
        conditions.append(AdminEvent.occurred_at >= filters.date_from)
    if filters.date_to is not None:
        conditions.append(AdminEvent.occurred_at <= filters.date_to)
    total = db.scalar(select(func.count()).select_from(AdminEvent).where(*conditions))
    items = list(
        db.scalars(
            select(AdminEvent)
            .where(*conditions)
            .order_by(AdminEvent.occurred_at.desc(), AdminEvent.id)
            .limit(limit)
            .offset(offset)
        )
    )
    return items, total
