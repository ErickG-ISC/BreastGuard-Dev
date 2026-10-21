"""Orquestación de la inferencia: fuera del event loop y con concurrencia limitada.

Render gratuito tiene ~512 MB: se permite MAX_CONCURRENT_INFERENCES (por defecto 1) a la vez y
las peticiones que esperen más de queue_timeout_seconds reciben 503.
"""

import asyncio
import io
from dataclasses import dataclass

import numpy as np
from fastapi import HTTPException, status
from fastapi.concurrency import run_in_threadpool
from PIL import Image, ImageOps

from backend.app.ml.heatmap import generate_heatmap
from backend.app.ml.quality import QualityIssue, check_image, prediction_flags
from backend.app.ml.report import build_report
from backend.app.ml.runtime import Predictor
from backend.app.ml.settings import MLSettings


class ImageQualityError(Exception):
    def __init__(self, issues: list[QualityIssue]) -> None:
        super().__init__(issues[0].message)
        self.issues = issues


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


def prepare_image(data: bytes) -> Image.Image:
    """Abre, corrige la orientación (EXIF) y DESCARTA los metadatos (ubicación del teléfono)."""
    with Image.open(io.BytesIO(data)) as raw:
        oriented = ImageOps.exif_transpose(raw)
        if oriented.mode not in ("RGB", "L"):
            oriented = oriented.convert("RGB")
        # Reconstruir desde los píxeles crea una imagen sin `info` (EXIF, GPS, ICC, comentarios)
        return Image.fromarray(np.asarray(oriented))


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
            image = await run_in_threadpool(prepare_image, data)
            return await run_in_threadpool(run_analysis, image, self.predictor, self.settings)
        finally:
            self._semaphore.release()
