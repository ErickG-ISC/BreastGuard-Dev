"""Token de baja de un recordatorio (enlace del correo, sin iniciar sesión).

JWT firmado con SECRET_KEY y audiencia propia: no sirve como token de sesión ni al revés. Solo
lleva ids (recordatorio y usuario), nunca datos de salud.
"""

import uuid
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt

from backend.app.services.auth import ALGORITHM, SECRET_KEY

AUDIENCE = "breastguard-unsubscribe"
TOKEN_TTL = timedelta(days=90)


class InvalidUnsubscribeToken(Exception):
    pass


def make_token(reminder_id: uuid.UUID, user_id: uuid.UUID, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    claims = {
        "aud": AUDIENCE,
        "rid": str(reminder_id),
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + TOKEN_TTL).timestamp()),
    }
    return jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)


def read_token(token: str) -> tuple[uuid.UUID, uuid.UUID]:
    """(reminder_id, user_id) de un token válido; si no, InvalidUnsubscribeToken."""
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            options={"require_aud": True, "require_exp": True, "require_sub": True},
        )
        return uuid.UUID(payload["rid"]), uuid.UUID(payload["sub"])
    except (JWTError, KeyError, ValueError, TypeError):
        raise InvalidUnsubscribeToken from None
