import uuid
from datetime import datetime
from ipaddress import IPv4Address, IPv6Address

from pydantic import BaseModel, ConfigDict


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    occurred_at: datetime
    actor_id: uuid.UUID
    actor_role: str
    action: str
    resource_type: str | None
    resource_id: uuid.UUID | None
    ip: IPv4Address | IPv6Address | None
