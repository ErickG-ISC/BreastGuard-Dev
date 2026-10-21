import logging
import os
from functools import lru_cache

from supabase import Client, create_client

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """No se pudo subir el archivo a Storage."""


@lru_cache
def _get_client() -> Client:
    # Se crea al primer uso, no al importar, para que la app (y las pruebas) arranquen sin
    # credenciales reales.
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


class SupabaseStorage:
    def __init__(self, bucket: str | None = None) -> None:
        self.bucket = bucket or os.environ.get("SUPABASE_BUCKET", "medical-images")

    def upload_file(self, file_path: str, object_name: str, content_type: str) -> str:
        """Sube el archivo y devuelve su URL.

        Pendiente (brecha 3): bucket privado y URLs firmadas de corta duración.
        """
        bucket = _get_client().storage.from_(self.bucket)
        try:
            with open(file_path, "rb") as f:
                bucket.upload(object_name, f, {"content-type": content_type})
        except Exception as exc:
            # Solo el tipo de error: el mensaje podría incluir rutas o datos de la petición
            logger.error("Fallo al subir un objeto a Storage (%s)", type(exc).__name__)
            raise StorageError from exc
        return bucket.get_public_url(object_name)

    def remove_prefix(self, prefix: str) -> int:
        """Borra todos los objetos bajo un prefijo de tenant (`{slug}/`). Solo para la purga."""
        if not prefix.endswith("/") or prefix.count("/") != 1:
            raise ValueError("El prefijo debe ser exactamente '{slug}/'")
        bucket = _get_client().storage.from_(self.bucket)
        paths: list[str] = []
        pending = [prefix.rstrip("/")]
        while pending:
            folder = pending.pop()
            for entry in bucket.list(folder):
                path = f"{folder}/{entry['name']}"
                # En Supabase, las "carpetas" se listan sin id
                if entry.get("id") is None:
                    pending.append(path)
                else:
                    paths.append(path)
        for start in range(0, len(paths), 100):
            bucket.remove(paths[start : start + 100])
        return len(paths)
