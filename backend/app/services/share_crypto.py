"""Código y cifrado del paquete compartido (CU-07, ADR 0010).

- El código son 16 bytes aleatorios (128 bits) en base32 Crockford: 26 caracteres en grupos.
  Viaja solo con la paciente (pantalla, QR o el fragmento `#c=` de la URL); el servidor nunca lo
  guarda.
- Del código se derivan con HKDF-SHA256 dos valores independientes:
  - la llave AES-256-GCM con la que se cifran el contenido y cada imagen;
  - un identificador de búsqueda, del que el servidor guarda solo `HMAC(SECRET_KEY, id)`.
  Quien tenga la base de datos no puede descifrar nada, y sin `SECRET_KEY` tampoco puede
  probar códigos contra el hash.
- Cada objeto lleva un nonce aleatorio y, como datos asociados, el id del paquete y el nombre
  del objeto: no se puede mover un archivo cifrado a otro paquete o a otro lugar sin que falle.
"""

import hashlib
import hmac
import os
import secrets
import uuid
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

CODE_BYTES = 16
CODE_LENGTH = 26  # ceil(128 / 5)
GROUPS = (5, 5, 5, 5, 6)
NONCE_BYTES = 12
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_DECODE = {c: i for i, c in enumerate(_ALPHABET)}
# Lecturas habituales de un código dictado o copiado a mano (Crockford)
_DECODE.update({"O": 0, "I": 1, "L": 1})


class InvalidCode(ValueError):
    """El texto no es un código bien formado (no dice nada sobre si existe)."""


class DecryptionError(Exception):
    """Llave incorrecta o contenido alterado."""


@dataclass(frozen=True)
class ShareSecret:
    code: str  # agrupado, para mostrar
    key: bytes  # AES-256
    lookup_hash: str  # lo único que guarda el servidor


def _encode(raw: bytes) -> str:
    number = int.from_bytes(raw, "big")
    chars = []
    for _ in range(CODE_LENGTH):
        chars.append(_ALPHABET[number & 31])
        number >>= 5
    return "".join(reversed(chars))


def _decode(text: str) -> bytes:
    if len(text) != CODE_LENGTH:
        raise InvalidCode
    number = 0
    for char in text:
        if char not in _DECODE:
            raise InvalidCode
        number = (number << 5) | _DECODE[char]
    # 26 × 5 = 130 bits: los 2 de más deben ser cero
    if number >> (CODE_BYTES * 8):
        raise InvalidCode
    return number.to_bytes(CODE_BYTES, "big")


def _group(text: str) -> str:
    parts, start = [], 0
    for size in GROUPS:
        parts.append(text[start : start + size])
        start += size
    return "-".join(parts)


def normalize(code: str) -> str:
    """Quita guiones y espacios y pasa a mayúsculas; valida la forma, no la existencia."""
    compact = "".join(code.split()).replace("-", "").upper()
    return _encode(_decode(compact))


def _hkdf(raw: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(raw)


def _secret_key() -> bytes:
    return os.environ["SECRET_KEY"].encode("utf-8")


def _from_raw(raw: bytes) -> ShareSecret:
    lookup = _hkdf(raw, b"breastguard/share/v1/lookup")
    return ShareSecret(
        code=_group(_encode(raw)),
        key=_hkdf(raw, b"breastguard/share/v1/key"),
        lookup_hash=hmac.new(_secret_key(), lookup, hashlib.sha256).hexdigest(),
    )


def new_secret() -> ShareSecret:
    return _from_raw(secrets.token_bytes(CODE_BYTES))


def from_code(code: str) -> ShareSecret:
    """Reconstruye llave y hash a partir del código que trae la médica (InvalidCode si no sirve)."""
    return _from_raw(_decode(normalize(code)))


def same_hash(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("ascii"), b.encode("ascii"))


def _aad(package_id: uuid.UUID, name: str) -> bytes:
    return package_id.bytes + name.encode("utf-8")


def encrypt(key: bytes, package_id: uuid.UUID, name: str, data: bytes) -> bytes:
    nonce = secrets.token_bytes(NONCE_BYTES)
    return nonce + AESGCM(key).encrypt(nonce, data, _aad(package_id, name))


def decrypt(key: bytes, package_id: uuid.UUID, name: str, blob: bytes) -> bytes:
    if len(blob) <= NONCE_BYTES:
        raise DecryptionError
    try:
        return AESGCM(key).decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], _aad(package_id, name))
    except InvalidTag:
        raise DecryptionError from None
