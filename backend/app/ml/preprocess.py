"""Preprocesamiento ÚNICO de la imagen al tensor del modelo, compartido con el entrenamiento.

Este archivo solo depende de numpy y Pillow para que el entrenamiento (fuera de este repo) lo
importe o lo copie TAL CUAL. Entrenar con otro preprocesamiento da un modelo que en el servidor
ve imágenes distintas a las que aprendió, sin ningún error visible.

Reglas:
- Si cambia el comportamiento (tamaño, interpolación, color o escala), se sube
  PREPROCESSING_VERSION. La huella de paridad (tests/fixtures/parity_*.json) falla en el CI ante
  cualquier cambio de los tensores, así que nadie lo cambia sin darse cuenta.
- La ficha del modelo declara `preprocessing_version`; si no coincide con la de aquí, el modelo
  NO se carga (ADR 0014).
"""

import numpy as np
from PIL import Image

PREPROCESSING_VERSION = 1
MODES = ("raw_0_255", "scale_0_1", "scale_minus1_1")
COLOR_MODES = ("rgb", "grayscale")


def to_tensor(
    image: Image.Image,
    input_size: tuple[int, int],
    color_mode: str = "rgb",
    preprocessing: str = "raw_0_255",
) -> np.ndarray:
    """Imagen PIL -> tensor (1, alto, ancho, canales) float32.

    - Convierte a RGB (o a gris), redimensiona a `input_size` (alto, ancho) con interpolación
      bilineal de Pillow, sin conservar la proporción.
    - `raw_0_255`: píxeles 0–255 (el EfficientNet de Keras normaliza DENTRO del modelo);
      `scale_0_1`: entre 255; `scale_minus1_1`: a [-1, 1].
    """
    if color_mode not in COLOR_MODES:
        raise ValueError(f"color_mode no soportado: {color_mode}")
    if preprocessing not in MODES:
        raise ValueError(f"Preprocesamiento no soportado: {preprocessing}")
    height, width = input_size
    mode = "RGB" if color_mode == "rgb" else "L"
    resized = image.convert(mode).resize((width, height), Image.Resampling.BILINEAR)
    array = np.asarray(resized, dtype=np.float32)
    if array.ndim == 2:
        array = array[..., np.newaxis]
    if preprocessing == "scale_0_1":
        array = array / 255.0
    elif preprocessing == "scale_minus1_1":
        array = array / 127.5 - 1.0
    return array[np.newaxis, ...]
