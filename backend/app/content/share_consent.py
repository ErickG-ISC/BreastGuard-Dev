"""Consentimiento para compartir un paquete con la médica (CU-07, BORRADOR) y su huella."""

import hashlib
from functools import lru_cache
from pathlib import Path

from backend.app.content.consent import ConsentText

CURRENT_SHARE_CONSENT_VERSION = "share-2026-11-v1"
_FILES = {"share-2026-11-v1": "share_consent_v1.md"}


@lru_cache
def current_share_consent() -> ConsentText:
    path = Path(__file__).with_name(_FILES[CURRENT_SHARE_CONSENT_VERSION])
    body = path.read_text(encoding="utf-8")
    return ConsentText(
        version=CURRENT_SHARE_CONSENT_VERSION,
        text=body,
        sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
    )
