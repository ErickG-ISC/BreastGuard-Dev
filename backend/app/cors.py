"""Orígenes permitidos por CORS a partir de FRONTEND_ORIGIN, tolerante a errores de captura.

El navegador envía el origen exacto (`https://dominio`, sin barra final). Valores comunes mal
pegados en el panel de Render: sin `https://`, con comillas, espacios o barra final. Se
normalizan aquí para que no dejen el frontend sin acceso a la API.
"""

import re

DEFAULT_ORIGIN = "http://localhost:5173"
# Separadores aceptados entre orígenes: comas y cualquier espacio en blanco (saltos de línea
# incluidos; en el panel de Render es fácil pegar uno por línea). Un origen nunca tiene espacios.
_SEPARATORS = re.compile(r"[,\s]+")


def normalize_origin(value: str) -> str | None:
    origin = value.strip().strip("\"'").strip().rstrip("/")
    if not origin:
        return None
    if "://" not in origin:
        # Un dominio público sin esquema se sirve por https; localhost suele ser http
        scheme = "http" if origin.startswith(("localhost", "127.0.0.1")) else "https"
        origin = f"{scheme}://{origin}"
    return origin.lower()


def parse_origins(raw: str | None) -> list[str]:
    origins = []
    for part in _SEPARATORS.split(raw or DEFAULT_ORIGIN):
        origin = normalize_origin(part)
        if origin and origin not in origins:
            origins.append(origin)
    return origins or [DEFAULT_ORIGIN]
