"""Verifica que el bucket de imágenes médicas sea PRIVADO (sin URLs públicas).

Uso, desde la raíz del repo:
    python -m backend.scripts.check_storage
"""

import sys

from dotenv import load_dotenv

load_dotenv()

from backend.app.services.storage import SupabaseStorage  # noqa: E402


def main() -> int:
    storage = SupabaseStorage()
    if storage.is_bucket_public():
        print(
            f"El bucket {storage.bucket!r} es PÚBLICO. Hazlo privado en Supabase > Storage.",
            file=sys.stderr,
        )
        return 1
    print(f"El bucket {storage.bucket!r} es privado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
