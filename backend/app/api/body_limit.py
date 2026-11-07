"""Tope global del cuerpo de la petición, ANTES de que nadie lo lea (memoria de Render, ADR 0011).

FastAPI procesa el multipart antes de las dependencias de la ruta, así que el límite por
`Content-Length` tiene que ir aquí. El mayor archivo permitido es un DICOM de 60 MB; cada ruta
mantiene además su propio límite (10 MB para imágenes).
"""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.app.ml.dicom import MAX_DICOM_BYTES

# Margen del multipart sobre el archivo (cabeceras, nombre, campos del formulario)
MAX_BODY_BYTES = MAX_DICOM_BYTES + 1024 * 1024


class BodySizeLimit:
    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            length = dict(scope.get("headers") or []).get(b"content-length")
            try:
                too_big = length is not None and int(length) > self.max_bytes
            except ValueError:
                too_big = False
            if too_big:
                response = JSONResponse(
                    {"detail": "La petición supera el tamaño máximo permitido."}, status_code=413
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
