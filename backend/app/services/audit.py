"""Bitácora de auditoría por tenant (CU-13): quién, acción, recurso, cuándo e IP.

Nunca guarda datos clínicos ni tokens. Se escribe en la MISMA transacción que la acción: si la
auditoría falla, la acción también. Se inserta con Core y sin RETURNING (ver AuditLog).
"""

import ipaddress
import uuid

from sqlalchemy import insert
from sqlalchemy.orm import Session

from backend.app.models.clinical import AuditLog


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
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    actor_role: str,
    action: str,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    ip: str | None = None,
) -> None:
    """Inserta un registro; RLS exige que tenant_id y actor_id coincidan con el contexto."""
    db.execute(
        insert(AuditLog).values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip=_clean_ip(ip),
        )
    )
