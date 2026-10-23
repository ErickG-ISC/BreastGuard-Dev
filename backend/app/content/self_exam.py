"""Guía de autoexploración vigente (CU-03), versionada en un archivo JSON (borrador académico)."""

import json
from functools import lru_cache
from pathlib import Path

SELF_EXAM_VERSION = "v1"
_FILES = {"v1": "self_exam_v1.json"}


@lru_cache
def current_guide() -> dict:
    path = Path(__file__).with_name(_FILES[SELF_EXAM_VERSION])
    guide = json.loads(path.read_text(encoding="utf-8"))
    if guide["version"] != SELF_EXAM_VERSION:
        raise RuntimeError("La versión del archivo de la guía no coincide con la vigente")
    return guide
