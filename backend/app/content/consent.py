"""Texto del consentimiento informado vigente (borrador académico) y su huella."""

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CURRENT_CONSENT_VERSION = "2026-10-v1"
_FILES = {"2026-10-v1": "consent_v1.md"}


@dataclass(frozen=True)
class ConsentText:
    version: str
    text: str
    sha256: str


@lru_cache
def current_consent() -> ConsentText:
    path = Path(__file__).with_name(_FILES[CURRENT_CONSENT_VERSION])
    body = path.read_text(encoding="utf-8")
    return ConsentText(
        version=CURRENT_CONSENT_VERSION,
        text=body,
        sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
    )
