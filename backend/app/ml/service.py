"""Orquestación de la inferencia: fuera del event loop y con concurrencia limitada.

Render gratuito tiene ~512 MB: se permite MAX_CONCURRENT_INFERENCES (por defecto 1) a la vez y
las peticiones que esperen más de queue_timeout_seconds reciben 503.
"""

import asyncio
import ctypes
import io
import logging
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from fastapi import HTTPException, status
from fastapi.concurrency import run_in_threadpool
from PIL import Image, ImageOps, UnidentifiedImageError

from backend.app.ml.heatmap import generate_heatmap
from backend.app.ml.quality import (
    ImageQualityError,
    QualityIssue,
    check_image,
    prediction_flags,
)
from backend.app.ml.report import build_report
from backend.app.ml.runtime import Predictor
from backend.app.ml.settings import MLSettings

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # solo para anotaciones; pydicom se importa al primer DICOM
    from backend.app.ml.dicom import DerivedImage


def _load_malloc_trim():
    """`malloc_trim` de glibc (solo Linux, como en Render); en otro sistema no hace nada."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        trim = ctypes.CDLL("libc.so.6").malloc_trim
    except (OSError, AttributeError):
        # Sin glibc (p. ej. musl/Alpine): la app funciona, pero sin esta mitigación
        logger.warning("malloc_trim no disponible; la memoria tras un DICOM no se devuelve")
        return None
    trim.argtypes = [ctypes.c_size_t]
    trim.restype = ctypes.c_int
    return trim


_MALLOC_TRIM = _load_malloc_trim()


def release_memory() -> None:
    """Devuelve al sistema la memoria libre del heap nativo tras un estudio DICOM.

    Los decodificadores (openjpeg, RLE) reservan bloques grandes fuera de Python; sin esto el
    proceso conserva el pico del estudio anterior y dos estudios seguidos se suman (ADR 0013).
    """
    if _MALLOC_TRIM is not None:
        _MALLOC_TRIM(0)


class ModelOutputError(RuntimeError):
    """El modelo devolvió valores inválidos (NaN, inf o probabilidades que no suman 1)."""


@dataclass(frozen=True)
class AnalysisOutcome:
    status: str  # completed | inconclusive
    predicted_class: str
    probabilities: dict[str, float]
    confidence: float
    model_version: str
    flags: list[str]
    report: dict
    clean_image_png: bytes  # imagen sin metadatos (EXIF), lista para guardar
    heatmap_png: bytes


def prepare_image(data: bytes, settings: MLSettings | None = None) -> Image.Image:
    """Abre, corrige la orientación (EXIF), reduce y DESCARTA los metadatos.

    El tamaño se comprueba ANTES de decodificar los píxeles (bombas de descompresión).
    """
    settings = settings or MLSettings()
    unreadable = ImageQualityError(
        [
            QualityIssue(
                "unreadable", "No se pudo leer la imagen. Prueba con otro archivo JPG o PNG."
            )
        ]
    )
    try:
        # Image.open solo lee la cabecera: el tamaño se valida antes de decodificar píxeles.
        # max_pixels está muy por debajo del umbral de advertencia de Pillow, así que no hace
        # falta tocar filtros de warnings (estado global, inseguro entre hilos).
        with Image.open(io.BytesIO(data)) as raw:
            width, height = raw.size
            if width * height > settings.max_pixels:
                raise ImageQualityError(
                    [QualityIssue("too_large", "La imagen es demasiado grande.")]
                )
            limit = (settings.max_side_px, settings.max_side_px)
            raw.draft("RGB", limit)  # JPEG: decodifica ya reducida
            oriented = ImageOps.exif_transpose(raw)
            if oriented.mode not in ("RGB", "L"):
                oriented = oriented.convert("RGB")
            oriented.thumbnail(limit, Image.Resampling.LANCZOS)
            # Reconstruir desde los píxeles crea una imagen sin `info` (EXIF, GPS, ICC, XMP)
            return Image.fromarray(np.asarray(oriented))
    except ImageQualityError:
        raise
    except Image.DecompressionBombError:
        raise ImageQualityError(
            [QualityIssue("too_large", "La imagen es demasiado grande.")]
        ) from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise unreadable from None


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def run_analysis(image: Image.Image, predictor: Predictor, settings: MLSettings) -> AnalysisOutcome:
    """Trabajo síncrono (CPU): se llama desde el threadpool."""
    issues = check_image(image, settings)
    if issues:
        raise ImageQualityError(issues)
    prediction = predictor.predict(image)
    flags = prediction_flags(prediction, settings)
    if "invalid_output" in flags or not np.isfinite(prediction.features).all():
        # Nunca se reporta ni se guarda una salida inválida del modelo
        raise ModelOutputError
    heatmap = generate_heatmap(image, predictor, prediction=prediction)
    report = build_report(
        prediction.predicted_class,
        prediction.confidence,
        flags,
        predictor.card.is_demo,
        settings,
    )
    return AnalysisOutcome(
        status="inconclusive" if flags else "completed",
        predicted_class=prediction.predicted_class,
        probabilities=prediction.probabilities,
        confidence=prediction.confidence,
        model_version=predictor.card.model_version,
        flags=flags,
        report=report,
        clean_image_png=_png(image),
        heatmap_png=heatmap.overlay_png,
    )


class InferenceService:
    def __init__(self, predictor: Predictor | None, settings: MLSettings) -> None:
        self.predictor = predictor
        self.settings = settings
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_inferences)

    @property
    def available(self) -> bool:
        return self.predictor is not None

    async def analyze(self, data: bytes) -> AnalysisOutcome:
        return await self._guarded(lambda: data)

    async def analyze_dicom(self, data: bytes) -> tuple[AnalysisOutcome, "DerivedImage"]:
        """Decodifica el DICOM y lo analiza bajo el MISMO semáforo: un estudio a la vez en RAM.

        Un DICOM no admitido lanza HTTP 422 con el mensaje de `DicomError`.
        """
        from backend.app.ml.dicom import DicomError, derive_image

        derived: list = []

        def convert() -> bytes:
            try:
                derived.append(derive_image(data))
            except DicomError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
                ) from None
            return derived[0].png

        outcome = await self._guarded(convert, convert_in_thread=True)
        return outcome, derived[0]

    async def _guarded(self, source, *, convert_in_thread: bool = False) -> AnalysisOutcome:
        if self.predictor is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="El servicio de análisis no está disponible en este momento.",
            )
        try:
            await asyncio.wait_for(self._semaphore.acquire(), self.settings.queue_timeout_seconds)
        except TimeoutError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Hay muchos análisis en curso. Intenta de nuevo en un momento.",
            ) from None
        try:
            data = await run_in_threadpool(source) if convert_in_thread else source()
            image = await run_in_threadpool(prepare_image, data, self.settings)
            try:
                return await run_in_threadpool(run_analysis, image, self.predictor, self.settings)
            except ModelOutputError:
                logger.error("El modelo devolvió una salida inválida; análisis descartado")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="No se pudo analizar la imagen. Intenta de nuevo más tarde.",
                ) from None
        finally:
            try:
                if convert_in_thread:
                    # Antes de soltar el turno: el siguiente estudio no hereda este pico
                    await run_in_threadpool(release_memory)
            finally:
                # Aunque la liberación se cancele o falle, el turno SIEMPRE se devuelve
                self._semaphore.release()
