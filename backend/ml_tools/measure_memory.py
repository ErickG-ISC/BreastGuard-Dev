"""Mide la memoria (RSS) de la inferencia, para decidir si cabe en Render gratuito (~512 MB).

Pensado para correr en Linux (lee /proc/self/status), por ejemplo en Docker con --memory=512m:
    python -m backend.ml_tools.measure_memory --mode litert --model-dir /model
    python -m backend.ml_tools.measure_memory --mode tf --model-dir /model [--with-app]

- litert: importa la app completa (FastAPI, SQLAlchemy, Supabase...), carga el modelo TFLite y
  hace un análisis con mapa de calor CAM en numpy. Es lo que correría en Render.
  Con `--dicom X.dcm`, además analiza ese DICOM con el modelo cargado, y con `--concurrent 2`
  manda N estudios a la vez por `InferenceService` (el semáforo real: los N archivos quedan en
  memoria y se decodifican de uno en uno), como N subidas simultáneas de la médica.
- tf: TensorFlow + modelo Keras + Grad-CAM con GradientTape (la alternativa sin conversión).
  Con `--with-app` importa antes la app completa, para comparar con lo que habría en Render.
- dicom: importa la app completa y convierte UN archivo DICOM con `ml.dicom.derive_image` (CU-09).
  Un archivo por proceso, para que cada pico (VmHWM) sea el suyo:
    python -m backend.ml_tools.measure_memory --mode dicom --file /dicoms/x.dcm
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


def import_app() -> None:
    """Importa la app completa con variables de relleno (no se conecta a nada)."""
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


def measure_litert(model_dir: Path, dicom: Path | None = None, concurrent: int = 1) -> dict:
    steps = {"start": rss_mb()}
    import_app()
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
    if dicom is not None:
        steps.update(_dicom_with_model(predictor, dicom, concurrent))
    return steps


def _dicom_with_model(predictor, path: Path, concurrent: int) -> dict:
    """N estudios DICOM a la vez por el servicio real (semáforo y threadpool incluidos)."""
    import asyncio

    from backend.app.ml.service import InferenceService
    from backend.app.ml.settings import get_settings

    settings = get_settings()  # MAX_CONCURRENT_INFERENCES del entorno, como en Render
    service = InferenceService(predictor, settings)
    # Cada subida es su propia copia en memoria (como N cuerpos multipart distintos)
    uploads = [path.read_bytes() for _ in range(concurrent)]
    steps = {
        "dicom_file_mb": round(len(uploads[0]) / 1024 / 1024, 1),
        "dicom_concurrent": concurrent,
        "max_concurrent_inferences": settings.max_concurrent_inferences,
        "dicom_uploads_in_memory": rss_mb(),
    }

    async def run_all():
        return await asyncio.gather(*(service.analyze_dicom(u) for u in uploads))

    started = time.perf_counter()
    results = asyncio.run(run_all())
    steps["dicom_seconds_total"] = round(time.perf_counter() - started, 2)
    steps["after_dicom"] = rss_mb()
    steps["dicom_classes"] = [outcome.predicted_class for outcome, _ in results]
    return steps


def measure_dicom(path: Path) -> dict:
    """Lo que AGREGA un DICOM a la app ya cargada (el modelo se mide aparte con --mode litert)."""
    steps = {"start": rss_mb()}
    import_app()
    from backend.app.ml.dicom import derive_image
    from backend.app.ml.service import prepare_image

    steps["app_imported"] = rss_mb()
    data = path.read_bytes()
    steps["file_mb"] = round(len(data) / 1024 / 1024, 1)
    started = time.perf_counter()
    derived = derive_image(data)
    steps["derive_seconds"] = round(time.perf_counter() - started, 2)
    del data
    prepare_image(derived.png)  # el mismo paso previo al modelo que en un análisis
    steps["after_derive"] = rss_mb()
    steps["meta"] = derived.meta
    return steps


def measure_tf(model_dir: Path, with_app: bool = False) -> dict:
    steps = {"start": rss_mb()}
    if with_app:
        import_app()
        steps["app_imported"] = rss_mb()
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
    parser.add_argument("--mode", choices=["litert", "tf", "dicom"], required=True)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--file", type=Path, help="Archivo DICOM (modo dicom)")
    parser.add_argument("--dicom", type=Path, help="DICOM a analizar con el modelo (modo litert)")
    parser.add_argument("--concurrent", type=int, default=1, help="Estudios a la vez (--dicom)")
    parser.add_argument("--with-app", action="store_true", help="Importa la app (modo tf)")
    args = parser.parse_args()
    if args.mode == "dicom":
        result = measure_dicom(args.file)
    elif args.mode == "litert":
        result = measure_litert(args.model_dir, args.dicom, args.concurrent)
    else:
        result = measure_tf(args.model_dir, args.with_app)
    print(json.dumps({"mode": args.mode, **result}, indent=2))


if __name__ == "__main__":
    main()
