"""Supabase Storage con bucket PRIVADO: rutas por tenant y URLs firmadas de corta duración.

La app nunca genera URLs públicas. La llave de servicio salta las políticas de Storage, así
que el aislamiento de archivos depende del prefijo `{tenant_slug}/` calculado en el servidor y
de validar la fila (visible por RLS) antes de firmar (ADR 0002, riesgo residual aceptado).
"""

import logging
import os
import re
from functools import lru_cache

from supabase import Client, create_client

logger = logging.getLogger(__name__)

DEFAULT_SIGNED_URL_TTL = 300
LIST_PAGE_SIZE = 100


class StorageError(Exception):
    """Falló una operación de Storage."""


@lru_cache
def _get_client() -> Client:
    # Se crea al primer uso, no al importar, para que la app (y las pruebas) arranquen sin
    # credenciales reales.
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def signed_url_ttl() -> int:
    return int(os.environ.get("SIGNED_URL_TTL_SECONDS", DEFAULT_SIGNED_URL_TTL))


class SupabaseStorage:
    def __init__(self, bucket: str | None = None) -> None:
        self.bucket = bucket or os.environ.get("SUPABASE_BUCKET", "medical-images")

    def _bucket(self):
        return _get_client().storage.from_(self.bucket)

    def upload_file(self, file_path: str, object_name: str, content_type: str) -> None:
        try:
            with open(file_path, "rb") as f:
                self._bucket().upload(object_name, f, {"content-type": content_type})
        except Exception as exc:
            # Solo el tipo de error: el mensaje podría incluir rutas o datos de la petición
            logger.error("Fallo al subir un objeto a Storage (%s)", type(exc).__name__)
            raise StorageError from exc

    def upload_bytes(self, object_name: str, data: bytes, content_type: str) -> None:
        try:
            self._bucket().upload(object_name, data, {"content-type": content_type})
        except Exception as exc:
            logger.error("Fallo al subir un objeto a Storage (%s)", type(exc).__name__)
            raise StorageError from exc

    def remove_objects(self, object_names: list[str]) -> None:
        """Borra objetos concretos (eliminación de un análisis)."""
        try:
            self._bucket().remove(object_names)
        except Exception as exc:
            logger.error("Fallo al borrar objetos de Storage (%s)", type(exc).__name__)
            raise StorageError from exc

    def create_signed_url(self, object_name: str, expires_in: int) -> str:
        try:
            result = self._bucket().create_signed_url(object_name, expires_in)
        except Exception as exc:
            logger.error("Fallo al firmar una URL de Storage (%s)", type(exc).__name__)
            raise StorageError from exc
        url = result.get("signedURL") or result.get("signedUrl")
        if not url:
            raise StorageError
        return url

    def is_bucket_public(self) -> bool:
        return bool(_get_client().storage.get_bucket(self.bucket).public)

    def remove_prefix(self, prefix: str) -> int:
        """Borra todos los objetos bajo un prefijo de tenant (`{slug}/`). Solo para la purga."""
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,40}/", prefix):
            raise ValueError("El prefijo debe ser exactamente '{slug}/'")
        bucket = self._bucket()
        paths: list[str] = []
        pending = [prefix.rstrip("/")]
        while pending:
            folder = pending.pop()
            offset = 0
            while True:
                # Supabase pagina el listado (100 por defecto): recorrer todas las páginas
                page = bucket.list(folder, {"limit": LIST_PAGE_SIZE, "offset": offset})
                for entry in page:
                    path = f"{folder}/{entry['name']}"
                    # En Supabase, las "carpetas" se listan sin id
                    if entry.get("id") is None:
                        pending.append(path)
                    else:
                        paths.append(path)
                if len(page) < LIST_PAGE_SIZE:
                    break
                offset += LIST_PAGE_SIZE
        for start in range(0, len(paths), 100):
            bucket.remove(paths[start : start + 100])
        return len(paths)
