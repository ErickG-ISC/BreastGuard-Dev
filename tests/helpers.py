"""Utilidades compartidas por las pruebas (fuera de conftest para importarlas sin duplicarlo)."""

import io

from PIL import Image

from backend.app.models.user import User
from backend.app.services.auth import create_access_token

DEFAULT_PASSWORD = "contrasena-segura"


def auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def make_image_bytes(fmt: str = "PNG") -> bytes:
    """Imagen sintética diminuta; nunca se usan imágenes médicas reales."""
    buffer = io.BytesIO()
    Image.new("L", (8, 8), color=128).save(buffer, format=fmt)
    return buffer.getvalue()
