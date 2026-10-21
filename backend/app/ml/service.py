"""Orquestación de la inferencia: fuera del event loop y con concurrencia limitada.

Render gratuito tiene ~512 MB: se permite MAX_CONCURRENT_INFERENCES (por defecto 1) a la vez y
las peticiones que esperen más de queue_timeout_seconds reciben 503.
"""

import asyncio
import io
import warnings
from dataclasses import dataclass

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
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
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
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
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
            image = await run_in_threadpool(prepare_image, data, self.settings)
            return await run_in_threadpool(run_analysis, image, self.predictor, self.settings)
        finally:
            self._semaphore.release()
