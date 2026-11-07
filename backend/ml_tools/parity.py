"""Paridad del modelo exportado: Keras (original) contra LiteRT (lo que corre en Render).

Usa un conjunto FIJO de imágenes sintéticas (sin datos de pacientes), generado con semilla:
- misma clase en todas;
- diferencia máxima de probabilidad <= PROB_TOLERANCE;
- el mapa CAM de numpy contra Grad-CAM de TensorFlow, correlación >= CAM_MIN_CORRELATION.

Con `--write` guarda una HUELLA (tests/fixtures/parity_<version>.json) con el hash de cada
imagen, el hash del tensor de entrada y las probabilidades de LiteRT. Las pruebas rápidas del CI
(sin TensorFlow ni modelo) comprueban que el preprocesamiento sigue dando exactamente los mismos
tensores; las lentas, con el modelo, que LiteRT sigue dando las mismas probabilidades.

Requiere TensorFlow (requirements-ml.txt) para la comparación con Keras; sin él solo calcula
la huella de LiteRT (`--no-keras`).

Uso, desde la raíz:
    python -m backend.ml_tools.parity --model-dir <carpeta> [--write tests/fixtures/parity.json]
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

N_IMAGES = 24
PROB_TOLERANCE = 1e-3
CAM_MIN_CORRELATION = 0.99


def synthetic_set() -> list[tuple[str, Image.Image]]:
    """24 imágenes en escala de grises, de tamaños y texturas distintos, siempre iguales."""
    images = []
    sizes = [(360, 480), (480, 640), (600, 600), (300, 420), (720, 540), (256, 256)]
    for i in range(N_IMAGES):
        rng = np.random.default_rng(1000 + i)
        h, w = sizes[i % len(sizes)]
        kind = ("speckle", "lesion", "gradient", "mixed")[i // len(sizes) % 4]
        base = rng.gamma(2.0, 25.0 + 5 * (i % 5), (h, w))
        yy, xx = np.mgrid[0:h, 0:w]
        if kind in ("lesion", "mixed"):
            cy, cx = rng.integers(h // 4, 3 * h // 4), rng.integers(w // 4, 3 * w // 4)
            r = rng.integers(min(h, w) // 10, min(h, w) // 4)
            base = np.where((yy - cy) ** 2 + (xx - cx) ** 2 < r**2, base * 0.25, base)
        if kind in ("gradient", "mixed"):
            base = base * (0.4 + 0.6 * yy / h)
        array = base.clip(0, 255).astype(np.uint8)
        images.append((f"{i:02d}-{kind}-{w}x{h}", Image.fromarray(array, "L")))
    return images


def image_sha256(image: Image.Image) -> str:
    """Hash de los píxeles (no del PNG, que depende de la versión de zlib)."""
    return hashlib.sha256(np.asarray(image).tobytes()).hexdigest()


def tensor_sha256(tensor: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(tensor, dtype=np.float32).tobytes()).hexdigest()


def _correlation(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a.ravel() - a.mean(), b.ravel() - b.mean()
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    # Dos mapas constantes (p. ej. todo cero tras ReLU) son iguales
    return 1.0 if denom == 0 else float(a @ b / denom)


def run(model_dir: Path, use_keras: bool = True) -> dict:
    from backend.app.ml.config import ModelCard
    from backend.app.ml.heatmap import class_activation_map
    from backend.app.ml.runtime import LiteRTPredictor, to_model_input

    card = ModelCard.load(model_dir / "model_card.json")
    predictor = LiteRTPredictor(model_dir, card)
    keras_model = grad_model = dense = None
    if use_keras:
        import tensorflow as tf

        keras_model = tf.keras.models.load_model(model_dir / "model.keras")
        dense = keras_model.get_layer("predictions")
        grad_model = tf.keras.Model(
            keras_model.inputs,
            [keras_model.get_layer("top_activation").output, dense.input],
        )

    rows, failures = [], []
    for name, image in synthetic_set():
        batch = to_model_input(image, card)
        prediction = predictor.predict(image)
        litert = np.array([prediction.probabilities[c] for c in card.classes])
        row = {
            "name": name,
            "image_sha256": image_sha256(image),
            "input_sha256": tensor_sha256(batch),
            "litert_probabilities": [round(float(p), 6) for p in litert],
        }
        if keras_model is not None:
            import tensorflow as tf

            keras_probs = keras_model.predict(batch, verbose=0)[0]
            diff = float(np.max(np.abs(keras_probs - litert)))
            same_class = int(np.argmax(keras_probs)) == int(np.argmax(litert))
            target = int(np.argmax(litert))
            with tf.GradientTape() as tape:
                features, pooled = grad_model(batch)
                logit = tf.matmul(pooled, dense.kernel)[:, target] + dense.bias[target]
            grads = tape.gradient(logit, features)
            weights = tf.reduce_mean(grads, axis=(1, 2))[0].numpy()
            gradcam = np.maximum((features[0].numpy() * weights).sum(axis=-1), 0)
            gradcam = gradcam / gradcam.max() if gradcam.max() > 0 else gradcam
            cam = class_activation_map(
                prediction.features, predictor.class_weights(prediction.predicted_class)
            )
            corr = _correlation(cam, gradcam)
            row.update(max_prob_diff=round(diff, 8), same_class=same_class, cam_corr=corr)
            if diff > PROB_TOLERANCE or not same_class or corr < CAM_MIN_CORRELATION:
                failures.append(name)
        rows.append(row)

    summary = {
        "model_version": card.model_version,
        "preprocessing": card.preprocessing,
        "input_size": list(card.input_size),
        "color_mode": card.color_mode,
        "classes": list(card.classes),
        "images": rows,
    }
    if keras_model is not None:
        summary["keras_comparison"] = {
            "max_prob_diff": max(r["max_prob_diff"] for r in rows),
            "min_cam_correlation": round(min(r["cam_corr"] for r in rows), 6),
            "all_same_class": all(r["same_class"] for r in rows),
            "tolerances": {
                "prob": PROB_TOLERANCE,
                "cam_correlation": CAM_MIN_CORRELATION,
            },
            "failures": failures,
        }
    return summary


def fingerprint(summary: dict) -> dict:
    """Lo que se guarda en el repo: sin la comparación con Keras (no se reproduce en CI)."""
    keep = ("name", "image_sha256", "input_sha256", "litert_probabilities")
    return {
        **{k: v for k, v in summary.items() if k not in ("images", "keras_comparison")},
        "images": [{k: row[k] for k in keep} for row in summary["images"]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--write", type=Path, help="Guarda la huella en este archivo JSON")
    parser.add_argument("--no-keras", action="store_true", help="Sin comparar con Keras")
    args = parser.parse_args()
    summary = run(args.model_dir, use_keras=not args.no_keras)
    report = summary.get("keras_comparison")
    print(json.dumps(report or {"keras_comparison": "omitida"}, indent=2))
    if args.write:
        args.write.write_text(
            json.dumps(fingerprint(summary), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    if report and report["failures"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
