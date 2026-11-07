"""Validador ESTRUCTURAL de HL7 v2 para las pruebas (no sustituye a un motor de interfaces).

Comprueba lo que un receptor necesita para poder leer el mensaje: segmentos separados por CR,
MSH con los separadores estándar, tipo y versión, orden ORU^R01 (MSH, PID, OBR, OBX+), número de
campos dentro de lo que define v2.5.1, OBX numerados y con tipos válidos, NM numéricos y ningún
separador ni carácter de control suelto dentro de los valores.
"""

import re

MAX_FIELDS = {"MSH": 21, "PID": 39, "OBR": 50, "OBX": 25}
VALUE_TYPES = {"CWE", "NM", "ST", "TX"}
ESCAPES = {"F": "|", "S": "^", "T": "&", "R": "~", "E": "\\"}


class HL7Error(AssertionError):
    pass


def segments(message: str) -> list[list[str]]:
    if not message.endswith("\r") or "\n" in message:
        raise HL7Error("Los segmentos deben terminar en CR y no llevar LF")
    out = []
    for raw in message[:-1].split("\r"):
        if not raw:
            raise HL7Error("Segmento vacío")
        if any(ord(c) < 0x20 for c in raw):
            raise HL7Error("Carácter de control dentro de un segmento")
        out.append(raw.split("|"))
    return out


def field(segment: list[str], number: int) -> str:
    """Campo N según la numeración HL7 (en MSH, MSH-1 es el propio separador)."""
    if segment[0] == "MSH":
        return "|" if number == 1 else (segment[number - 1] if number - 1 < len(segment) else "")
    return segment[number] if number < len(segment) else ""


def unescape(value: str) -> str:
    return re.sub(r"\\([FSTRE])\\", lambda m: ESCAPES[m.group(1)], value)


def validate_oru_r01(message: str) -> list[list[str]]:
    segs = segments(message)
    names = "".join(s[0] + "," for s in segs)
    if not re.fullmatch(r"MSH,PID,OBR,(OBX,)+", names):
        raise HL7Error(f"Orden de segmentos inválido para ORU^R01: {names}")
    msh = segs[0]
    if not message.startswith("MSH|^~\\&|"):
        raise HL7Error("MSH-1/MSH-2 deben ser | y ^~\\&")
    if field(msh, 9) != "ORU^R01^ORU_R01":
        raise HL7Error(f"MSH-9 inválido: {field(msh, 9)}")
    if field(msh, 12) != "2.5.1":
        raise HL7Error("MSH-12 debe ser 2.5.1")
    if not field(msh, 10):
        raise HL7Error("MSH-10 (id de control) vacío")
    if not re.fullmatch(r"\d{14}[+-]\d{4}", field(msh, 7)):
        raise HL7Error("MSH-7 no es una fecha DTM")
    for seg in segs:
        count = len(seg) if seg[0] == "MSH" else len(seg) - 1
        if count > MAX_FIELDS[seg[0]]:
            raise HL7Error(f"{seg[0]} tiene {count} campos (máximo {MAX_FIELDS[seg[0]]})")
        for value in seg[1:] if seg[0] != "MSH" else seg[2:]:
            # Un "\" solo puede aparecer como parte de una secuencia de escape válida
            if re.sub(r"\\[FSTRE]\\", "", value).count("\\"):
                raise HL7Error(f"Escape inválido en {seg[0]}: {value!r}")
    for index, obx in enumerate(segs[3:], start=1):
        if field(obx, 1) != str(index):
            raise HL7Error("OBX-1 debe numerarse 1, 2, 3…")
        if field(obx, 2) not in VALUE_TYPES:
            raise HL7Error(f"OBX-2 inválido: {field(obx, 2)}")
        if field(obx, 2) == "NM" and not re.fullmatch(r"-?\d+(\.\d+)?", field(obx, 5)):
            raise HL7Error(f"OBX NM no numérico: {field(obx, 5)}")
        if field(obx, 11) != "F":
            raise HL7Error("OBX-11 debe ser F")
    return segs
