"""Mide la memoria (RSS) de la inferencia, para decidir si cabe en Render gratuito (~512 MB).

Pensado para correr en Linux (lee /proc/self/status), por ejemplo en Docker con --memory=512m:
    python -m backend.ml_tools.measure_memory --mode litert --model-dir /model
    python -m backend.ml_tools.measure_memory --mode tf --model-dir /model

- litert: importa la app completa (FastAPI, SQLAlchemy, Supabase...), carga el modelo TFLite y
  hace un análisis con mapa de calor CAM en numpy. Es lo que correría en Render.
- tf: TensorFlow + modelo Keras + Grad-CAM con GradientTape (la alternativa sin conversión).
"""

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np


def rss_mb() -> dict:
    values = {}
    with open("/proc/self/status", encoding="ascii") as f:
        for line in f:
            if line.startswith(("VmRSS:", "VmHWM:")):
                key, amount, _ = line.split()
                values[key.rstrip(":")] = round(int(amount) / 1024, 1)
    return {"rss_mb": values.get("VmRSS"), "peak_rss_mb": values.get("VmHWM")}


def synthetic_ultrasound() -> "Image.Image":  # noqa: F821
    from PIL import Image

    rng = np.random.default_rng(0)
    speckle = rng.gamma(2.0, 30.0, (480, 640)).clip(0, 255).astype(np.uint8)
    return Image.fromarray(speckle, mode="L")


def measure_litert(model_dir: Path) -> dict:
    steps = {"start": rss_mb()}
    for name, value in {
        "DATABASE_URL": "postgresql://u@localhost/db",
        "APP_DB_PASSWORD": "x",
        "SECRET_KEY": "x",
        "SUPABASE_URL": "http://localhost:1",
        "SUPABASE_KEY": "x",
        "MODEL_LOAD_ON_STARTUP": "0",
    }.items():
        os.environ.setdefault(name, value)
    import backend.app.main  # noqa: F401  (toda la app, como en Render)
    from backend.app.ml.config import ModelCard
    from backend.app.ml.runtime import LiteRTPredictor
    from backend.app.ml.service import run_analysis
    from backend.app.ml.settings import MLSettings

    steps["app_imported"] = rss_mb()
    predictor = LiteRTPredictor(model_dir, ModelCard.load(model_dir / "model_card.json"))
    steps["model_loaded"] = rss_mb()
    image = synthetic_ultrasound()
    started = time.perf_counter()
    outcome = run_analysis(image, predictor, MLSettings())
    steps["after_analysis"] = rss_mb()
    for _ in range(3):
        run_analysis(image, predictor, MLSettings())
    steps["after_4_analyses"] = rss_mb()
    steps["first_analysis_seconds"] = round(time.perf_counter() - started, 3)
    steps["class"] = outcome.predicted_class
    return steps


def measure_tf(model_dir: Path) -> dict:
    steps = {"start": rss_mb()}
    import tensorflow as tf

    steps["tf_imported"] = rss_mb()
    model = tf.keras.models.load_model(model_dir / "model.keras")
    steps["model_loaded"] = rss_mb()
    image = np.asarray(synthetic_ultrasound().convert("RGB").resize((224, 224)), dtype=np.float32)
    batch = image[np.newaxis, ...]
    conv = model.get_layer("top_activation")
    grad_model = tf.keras.Model(model.inputs, [conv.output, model.output])
    started = time.perf_counter()
    with tf.GradientTape() as tape:
        features, probs = grad_model(batch)
        score = probs[:, int(tf.argmax(probs[0]))]
    grads = tape.gradient(score, features)
    weights = tf.reduce_mean(grads, axis=(1, 2))
    tf.nn.relu(tf.reduce_sum(features * weights[:, None, None, :], axis=-1)).numpy()
    steps["after_gradcam"] = rss_mb()
    steps["first_gradcam_seconds"] = round(time.perf_counter() - started, 3)
    return steps


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=["litert", "tf"], required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    args = parser.parse_args()
    result = measure_litert(args.model_dir) if args.mode == "litert" else measure_tf(args.model_dir)
    print(json.dumps({"mode": args.mode, **result}, indent=2))


if __name__ == "__main__":
    main()
