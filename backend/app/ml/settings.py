"""Umbrales y configuración del análisis, en UN solo lugar.

Los umbrales son orientativos y deben calibrarse con el modelo real y métricas honestas.
"""

import os
from dataclasses import dataclass, field
from functools import lru_cache


@dataclass(frozen=True)
class MLSettings:
    # Origen del modelo (no se commitea): carpeta local o bucket privado de Supabase
    model_dir: str = "/tmp/breastguard-model"
    model_bucket: str = "ml-models"
    model_prefix: str = "demo-effb0-untrained-1"
    # Las pruebas lo desactivan: usan un predictor doble
    load_on_startup: bool = True
    # Render gratuito (~512 MB): una inferencia a la vez
    max_concurrent_inferences: int = 1
    queue_timeout_seconds: float = 30.0
    # Reporte
    confidence_high: float = 0.85
    confidence_min: float = 0.60
    suspicious_classes: frozenset[str] = field(default_factory=lambda: frozenset({"maligno"}))
    # Calidad de entrada
    min_side_px: int = 128
    max_mean_saturation: float = 0.15  # 0–1; una ecografía es casi gris
    min_pixel_stddev: float = 6.0  # 0–255; menos es una imagen casi uniforme
    max_normalized_entropy: float = 0.97  # 1 = probabilidades totalmente repartidas


@lru_cache
def get_settings() -> MLSettings:
    return MLSettings(
        model_dir=os.environ.get("MODEL_DIR", MLSettings.model_dir),
        model_bucket=os.environ.get("MODEL_BUCKET", MLSettings.model_bucket),
        model_prefix=os.environ.get("MODEL_PREFIX", MLSettings.model_prefix),
        max_concurrent_inferences=int(os.environ.get("MAX_CONCURRENT_INFERENCES", "1")),
        load_on_startup=os.environ.get("MODEL_LOAD_ON_STARTUP", "1") != "0",
    )
