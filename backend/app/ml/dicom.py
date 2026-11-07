"""DICOM (CU-09): validar, decodificar y convertir a una imagen derivada SIN datos personales.

Nunca se guarda el DICOM original: solo una imagen PNG derivada (sin metadatos) y, en
`analyses.dicom_meta`, una lista blanca de datos técnicos (modalidad, vista, lateralidad,
espaciado...). Nada de nombre, ID, fechas, institución ni médico.

Orden pensado para la memoria (Render gratuito, ~512 MB; ADR 0011):
1. tamaño del archivo y firma `DICM`, ANTES de leer nada;
2. cabecera sin píxeles (`stop_before_pixels`): dimensiones, cuadros, muestras, bits,
   fotometría, sintaxis de transferencia (lista blanca) y `BurnedInAnnotation`;
3. decodificación (la única parte cara; acotada por los límites anteriores);
4. reducción por promedio de bloques EN 16 BITS antes de cualquier ventana (la copia en
   coma flotante es ya del tamaño reducido), luego reescala, ventana o VOI, MONOCHROME1
   invertida y 8 bits.

JPEG Lossless (el decodificador libre es GPL) no se admite: se rechaza con un mensaje claro.
"""

import io
import logging
import math
import time
from dataclasses import dataclass

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

MAX_DICOM_BYTES = 60 * 1024 * 1024
# Medido en Docker con 512 MB (ADR 0011): un JPEG 2000 de 5000×5000 llegaba a ~409 MB con la app y
# el modelo; 4096 cubre las mastografías habituales (3328×4096) y deja el peor caso en ~290 MB
MAX_SIDE = 4096
# Lado máximo de la imagen derivada que se analiza y se guarda
DERIVED_SIDE = 2048
MAX_DECODE_SECONDS = 10.0

# Sintaxis de transferencia admitidas (UID → nombre corto para la lista blanca de metadatos)
ALLOWED_TRANSFER_SYNTAXES = {
    "1.2.840.10008.1.2": "implicit_le",
    "1.2.840.10008.1.2.1": "explicit_le",
    "1.2.840.10008.1.2.5": "rle",
    "1.2.840.10008.1.2.4.50": "jpeg_baseline",
    "1.2.840.10008.1.2.4.90": "jpeg2000_lossless",
    "1.2.840.10008.1.2.4.91": "jpeg2000",
}
JPEG_LOSSLESS = {"1.2.840.10008.1.2.4.57", "1.2.840.10008.1.2.4.70"}
PHOTOMETRIC = {"MONOCHROME1", "MONOCHROME2"}
# Lista blanca CERRADA: un valor fuera de estos códigos se guarda como None (nunca texto libre,
# que podría traer un nombre o un ID)
MODALITIES = {"MG", "US", "CR", "DX"}
VIEWS = {"CC", "MLO", "ML", "LM", "LMO", "XCCL", "XCCM", "FB", "SIO", "AT", "RL", "RM"}
LATERALITIES = {"L", "R", "B", "U"}


class DicomError(ValueError):
    """Archivo DICOM no admitido; el mensaje es apto para mostrarse a la médica."""


@dataclass(frozen=True)
class DerivedImage:
    png: bytes  # imagen derivada en escala de grises, sin metadatos
    modality: str | None
    meta: dict  # SOLO la lista blanca técnica


def is_dicom(data: bytes) -> bool:
    return len(data) > 132 and data[128:132] == b"DICM"


def _code(value, allowed: set[str]) -> str | None:
    text = str(_first(value) or "").strip().upper()
    return text if text in allowed else None


def _first(value):
    """Primer valor de un atributo que puede ser múltiple (MultiValue de pydicom no es list)."""
    if value is None or isinstance(value, str | bytes):
        return value
    try:
        return value[0]
    except (TypeError, IndexError, KeyError):
        return value


def _floats(value, count: int) -> list[float] | None:
    try:
        numbers = [float(v) for v in list(value)]
    except (TypeError, ValueError):
        return None
    numbers = numbers[:count]
    return numbers if numbers and all(math.isfinite(n) and 0 < n < 10 for n in numbers) else None


def _header_checks(ds) -> str:
    """Valida la cabecera; un valor mal formado (p. ej. Rows no numérico) es DicomError, no 500."""
    try:
        return _check_header(ds)
    except DicomError:
        raise
    except (TypeError, ValueError, KeyError, AttributeError):
        raise DicomError("La cabecera del DICOM tiene valores no válidos.") from None


def _check_header(ds) -> str:
    transfer = str(ds.file_meta.get("TransferSyntaxUID", ""))
    if transfer in JPEG_LOSSLESS:
        raise DicomError(
            "La compresión JPEG Lossless no está soportada. Exporta el estudio sin compresión, "
            "en RLE o en JPEG 2000."
        )
    if transfer not in ALLOWED_TRANSFER_SYNTAXES:
        raise DicomError("La sintaxis de transferencia del archivo no está soportada.")
    rows, columns = int(ds.get("Rows", 0) or 0), int(ds.get("Columns", 0) or 0)
    if not (32 <= rows <= MAX_SIDE and 32 <= columns <= MAX_SIDE):
        raise DicomError(f"Dimensiones no admitidas (máximo {MAX_SIDE} px por lado).")
    if int(ds.get("NumberOfFrames", 1) or 1) != 1:
        raise DicomError("Solo se admiten imágenes de un solo cuadro.")
    if int(ds.get("SamplesPerPixel", 1) or 1) != 1:
        raise DicomError("Solo se admiten imágenes en escala de grises.")
    if int(ds.get("BitsAllocated", 0) or 0) not in (8, 16):
        raise DicomError("Profundidad de bits no admitida.")
    if str(ds.get("PhotometricInterpretation", "")) not in PHOTOMETRIC:
        raise DicomError("Interpretación fotométrica no admitida (solo MONOCHROME1 o 2).")
    if str(ds.get("BurnedInAnnotation", "NO")).upper() == "YES":
        # Puede traer nombre, fechas o identificadores DENTRO de los píxeles
        raise DicomError(
            "El estudio tiene anotaciones grabadas en la imagen y podría contener datos "
            "personales; expórtalo sin anotaciones."
        )
    return ALLOWED_TRANSFER_SYNTAXES[transfer]


def _downscale(pixels: np.ndarray) -> np.ndarray:
    """Promedio por bloques en el tipo original (sin una copia en coma flotante completa)."""
    height, width = pixels.shape
    factor = max(1, math.ceil(max(height, width) / DERIVED_SIDE))
    if factor == 1:
        return pixels.astype(np.float32)
    h, w = height // factor, width // factor
    blocks = pixels[: h * factor, : w * factor].reshape(h, factor, w, factor)
    return blocks.mean(axis=(1, 3), dtype=np.float32)


def _window(ds, values: np.ndarray) -> np.ndarray:
    try:
        slope = float(_first(ds.get("RescaleSlope", 1)) or 1)
        intercept = float(_first(ds.get("RescaleIntercept", 0)) or 0)
    except (TypeError, ValueError):
        raise DicomError("La cabecera del DICOM tiene valores no válidos.") from None
    if not (math.isfinite(slope) and math.isfinite(intercept)) or slope == 0:
        raise DicomError("La cabecera del DICOM tiene valores no válidos.")
    values = values * slope + intercept
    try:
        center = float(_first(ds.get("WindowCenter")))
        width = float(_first(ds.get("WindowWidth")))
    except (TypeError, ValueError):
        center = width = None
    if center is None or not width or width <= 1 or not math.isfinite(center + width):
        # Sin ventana útil: percentiles, robustos ante píxeles extremos (marcas, bordes)
        low, high = np.percentile(values, (0.5, 99.5))
    else:
        low, high = center - width / 2, center + width / 2
    if high <= low:
        raise DicomError("La imagen es uniforme; no se puede analizar.")
    scaled = np.clip((values - low) / (high - low), 0.0, 1.0)
    if str(ds.PhotometricInterpretation) == "MONOCHROME1":
        scaled = 1.0 - scaled  # en MONOCHROME1 el valor mínimo es blanco
    return (scaled * 255.0 + 0.5).astype(np.uint8)


def derive_image(data: bytes) -> DerivedImage:
    """Valida y convierte un DICOM en una imagen derivada. Lanza DicomError si no se admite."""
    from pydicom import dcmread
    from pydicom.errors import InvalidDicomError

    if len(data) > MAX_DICOM_BYTES:
        raise DicomError(f"El archivo supera el máximo de {MAX_DICOM_BYTES // (1024 * 1024)} MB.")
    if not is_dicom(data):
        raise DicomError("El archivo no es un DICOM válido (falta la firma DICM).")
    try:
        header = dcmread(io.BytesIO(data), stop_before_pixels=True)
    except (InvalidDicomError, ValueError, TypeError, KeyError, EOFError, OSError):
        raise DicomError("No se pudo leer la cabecera del DICOM.") from None
    transfer = _header_checks(header)

    started = time.monotonic()
    try:
        ds = dcmread(io.BytesIO(data))
        if "PixelData" not in ds:
            raise DicomError("El archivo no contiene una imagen.")
        pixels = ds.pixel_array
    except DicomError:
        raise
    except Exception:  # decodificadores nativos: cualquier fallo es "archivo dañado"
        raise DicomError("No se pudo decodificar la imagen del DICOM.") from None
    elapsed = time.monotonic() - started
    if elapsed > MAX_DECODE_SECONDS:
        # No se puede interrumpir a media decodificación; el tope real son tamaño y dimensiones
        logger.warning("Decodificación DICOM lenta (%.1f s); rechazada", elapsed)
        raise DicomError("El estudio tardó demasiado en procesarse.")
    if pixels.ndim != 2 or pixels.shape != (int(ds.Rows), int(ds.Columns)):
        raise DicomError("La imagen decodificada no coincide con su cabecera.")

    reduced = _downscale(pixels)
    del pixels, ds  # liberar la matriz completa antes de la ventana
    derived = Image.fromarray(_window(header, reduced), mode="L")
    buffer = io.BytesIO()
    derived.save(buffer, format="PNG")  # sin metadatos: se construye desde los píxeles

    spacing = _floats(header.get("PixelSpacing") or header.get("ImagerPixelSpacing") or [], 2)
    meta = {
        "modality": _code(header.get("Modality"), MODALITIES),
        "view_position": _code(header.get("ViewPosition"), VIEWS),
        "laterality": _code(
            header.get("ImageLaterality") or header.get("Laterality"), LATERALITIES
        ),
        "pixel_spacing_mm": spacing,
        "rows": int(header.Rows),
        "columns": int(header.Columns),
        "photometric": str(header.PhotometricInterpretation),
        "bits_stored": int(header.get("BitsStored", 0) or 0) or None,
        "transfer_syntax": transfer,
    }
    return DerivedImage(png=buffer.getvalue(), modality=meta["modality"], meta=meta)
