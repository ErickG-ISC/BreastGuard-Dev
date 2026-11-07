"""Respuesta común de las exportaciones (CU-10): descarga, sin caché y sin datos en el nombre."""

from fastapi import Response

from backend.app.services.reports import Export


def download(export: Export) -> Response:
    return Response(
        content=export.content,
        media_type=export.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{export.filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
