"""Piezas puras de CU-10: escapado HL7 y edad aproximada (sin base de datos)."""

from datetime import date

import pytest

from backend.app.services.hl7 import escape
from backend.app.services.reports import approximate_age, filename
from tests.hl7_validator import unescape


@pytest.mark.parametrize(
    "raw",
    ["Ana | López", "a^b&c~d\e", "\F\ literal", "x" * 300, "Ñandú Pérez"],
)
def test_escape_ida_y_vuelta(raw):
    escaped = escape(raw)
    assert "|" not in escaped and "^" not in escaped and "&" not in escaped and "~" not in escaped
    assert unescape(escaped) == raw


@pytest.mark.parametrize("raw", ["línea 1\rMSH|^~\&|FALSO", "a\nb", "a\tb\x00c"])
def test_escape_no_deja_inventar_segmentos(raw):
    escaped = escape(raw)
    assert "\r" not in escaped and "\n" not in escaped
    assert not any(ord(c) < 0x20 for c in escaped)


@pytest.mark.parametrize(
    ("age", "recorded", "today", "expected"),
    [
        (40, date(2024, 6, 1), date(2026, 5, 31), 41),
        (40, date(2024, 6, 1), date(2026, 6, 1), 42),
        (40, None, date(2026, 6, 1), 40),
        (None, date(2024, 6, 1), date(2026, 6, 1), None),
        (40, date(2027, 1, 1), date(2026, 6, 1), 40),  # fecha futura: no resta
    ],
)
def test_edad_aproximada(age, recorded, today, expected):
    assert approximate_age(age, recorded, today) == expected


def test_nombre_de_archivo_sin_datos_personales():
    import uuid

    report_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert filename(report_id, "pdf") == "breastguard-reporte-12345678.pdf"
