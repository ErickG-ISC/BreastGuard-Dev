"""Mensaje HL7 v2.5.1 ORU^R01 SIMULADO del reporte de la médica (CU-10, ADR 0015).

SIMULACIÓN, NO PROBADA CONTRA UN SISTEMA HOSPITALARIO. Estructura: MSH, PID, OBR y una serie de
OBX. Los códigos son LOCALES (sistema `L`); `docs/hl7-integracion.md` explica qué códigos
(LOINC/RadLex) y qué transporte (MLLP, ACK) haría falta en una integración real.

- Separadores estándar `|^~\\&`; segmentos separados con CR (`\\r`), como pide el estándar.
- Todo texto que viene de datos (nombres, recomendación, versión) se ESCAPA (`\\F\\ \\S\\ \\R\\
  \\E\\ \\T\\`) y pierde los saltos de línea y caracteres de control: un nombre con `|` no
  puede inventar campos ni segmentos.
- Solo lo que pide CU-10: no hay fecha de nacimiento (solo se guarda una edad aproximada), ni
  dirección, ni identificadores externos. PID-3 es el id interno de la ficha con el tenant como
  autoridad asignadora.
- MSH-11 = `T` (entrenamiento/pruebas): ningún receptor debe tomarlo como un resultado real.
"""

from backend.app.services.reports import ReportData

FIELD, COMPONENT, REPETITION, ESCAPE, SUBCOMPONENT = "|", "^", "~", "\\", "&"
ENCODING = COMPONENT + REPETITION + ESCAPE + SUBCOMPONENT
SEGMENT_END = "\r"
VERSION = "2.5.1"
MESSAGE_TYPE = "ORU^R01^ORU_R01"
SERVICES = {
    "ecografia_b2c": ("BG-US", "Ecografía mamaria (apoyo IA)", "US"),
    "mastografia_prototipo": ("BG-MG", "Mastografía (prototipo, apoyo IA)", "MG"),
}
CLASS_TEXT = {"normal": "Normal", "benigno": "Benigno", "maligno": "Maligno"}


def escape(value) -> str:
    """Escapa un valor para un campo HL7 v2 y quita saltos de línea y caracteres de control."""
    text = "" if value is None else str(value)
    text = "".join(" " if ord(ch) < 0x20 or ord(ch) == 0x7F else ch for ch in text)
    text = text.replace(ESCAPE, "\\E\\")  # primero el carácter de escape
    for char, code in ((FIELD, "F"), (COMPONENT, "S"), (SUBCOMPONENT, "T"), (REPETITION, "R")):
        text = text.replace(char, f"\\{code}\\")
    return " ".join(text.split())


def ts(moment) -> str:
    """Fecha y hora HL7 (DTM) en UTC: YYYYMMDDHHMMSS+0000."""
    from datetime import UTC

    return moment.astimezone(UTC).strftime("%Y%m%d%H%M%S+0000")


def _segment(name: str, *fields: str) -> str:
    # Sin campos vacíos al final (forma canónica)
    values = list(fields)
    while values and values[-1] == "":
        values.pop()
    return FIELD.join([name, *values])


def _cwe(code: str, text: str, system: str = "L") -> str:
    return COMPONENT.join([escape(code), escape(text), system])


def oru_r01(data: ReportData) -> str:
    service_code, service_text, section = SERVICES.get(
        data.profile, ("BG-STUDY", "Estudio (apoyo IA)", "OTH")
    )
    issued = ts(data.issued_at)
    observed = ts(data.study_date)
    control_id = str(data.report_id)

    msh = (
        "MSH"
        + FIELD
        + FIELD.join(
            [
                ENCODING,  # MSH-2 (MSH-1 es el propio separador)
                "BREASTGUARD",  # MSH-3 aplicación emisora
                escape(data.tenant_slug),  # MSH-4 institución emisora
                "SIMULADO",  # MSH-5 aplicación receptora
                "SIMULADO",  # MSH-6 institución receptora
                issued,  # MSH-7
                "",  # MSH-8
                MESSAGE_TYPE,  # MSH-9
                control_id,  # MSH-10
                "T",  # MSH-11 entrenamiento: NO es un resultado real
                VERSION,  # MSH-12
                "",  # MSH-13
                "",  # MSH-14
                "NE",  # MSH-15 sin acuse de recibo (simulación)
                "NE",  # MSH-16
                "",  # MSH-17
                "UNICODE UTF-8",  # MSH-18
            ]
        )
    )
    pid = _segment(
        "PID",
        "1",  # PID-1
        "",  # PID-2
        COMPONENT.join([str(data.patient_ref), "", "", escape(data.tenant_slug), "PI"]),  # PID-3
        "",  # PID-4
        escape(data.patient_name),  # PID-5: el nombre tal como se registró (sin separar)
    )
    obr = _segment(
        "OBR",
        "1",  # OBR-1
        COMPONENT.join([str(data.analysis_id), "BREASTGUARD"]),  # OBR-2 orden del emisor
        COMPONENT.join([str(data.analysis_id), "BREASTGUARD"]),  # OBR-3 orden del ejecutor
        _cwe(service_code, service_text),  # OBR-4
        "",  # OBR-5
        "",  # OBR-6
        observed,  # OBR-7 fecha del estudio
        *[""] * 14,  # OBR-8 a OBR-21
        ts(data.reviewed_at or data.issued_at),  # OBR-22 fecha del resultado
        "",  # OBR-23
        section,  # OBR-24 sección (US/MG)
        "F",  # OBR-25 resultado final (revisado por la médica)
        *[""] * 6,  # OBR-26 a OBR-31
        SUBCOMPONENT + escape(data.reviewer_name),  # OBR-32 intérprete (apellido = nombre)
    )

    observations: list[tuple[str, str, str, str, str]] = [
        # (tipo, identificador, sub-id, valor, unidades)
        (
            "CWE",
            _cwe("BG-AI-CLASS", "Clase estimada por el modelo (apoyo, no diagnóstico)"),
            "",
            _cwe(data.predicted_class, CLASS_TEXT.get(data.predicted_class, data.predicted_class)),
            "",
        ),
        (
            "NM",
            _cwe("BG-AI-CONF", "Confianza del modelo"),
            "",
            f"{data.confidence * 100:.1f}",
            COMPONENT.join(["%", "porcentaje", "UCUM"]),
        ),
        ("ST", _cwe("BG-AI-MODEL", "Versión del modelo"), "", escape(data.model_version), ""),
        (
            "CWE",
            _cwe("BG-BIRADS", "Categoría BI-RADS asignada por la médica"),
            "",
            _cwe(data.birads, f"BI-RADS {data.birads}"),
            "",
        ),
        (
            "TX",
            _cwe("BG-REC", "Recomendación de la médica"),
            "",
            escape(data.recommendation or ""),
            "",
        ),
    ]
    if data.approx_age is not None:
        observations.append(
            (
                "NM",
                _cwe("BG-AGE", "Edad aproximada"),
                "",
                str(data.approx_age),
                COMPONENT.join(["a", "años", "UCUM"]),
            )
        )
    for index, warning in enumerate(data.warnings, start=1):
        observations.append(("TX", _cwe("BG-WARN", "Aviso"), str(index), escape(warning), ""))

    obx = [
        _segment(
            "OBX",
            str(i),  # OBX-1
            kind,  # OBX-2
            identifier,  # OBX-3
            sub_id,  # OBX-4
            value,  # OBX-5
            units,  # OBX-6
            "",  # OBX-7
            "",  # OBX-8
            "",  # OBX-9
            "",  # OBX-10
            "F",  # OBX-11 final
            "",  # OBX-12
            "",  # OBX-13
            observed,  # OBX-14
        )
        for i, (kind, identifier, sub_id, value, units) in enumerate(observations, start=1)
    ]
    return SEGMENT_END.join([msh, pid, obr, *obx]) + SEGMENT_END
