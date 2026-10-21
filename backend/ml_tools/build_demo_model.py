"""Construye y exporta el MODELO DE DEMOSTRACIÓN (EfficientNet-B0 sin entrenar, 3 clases).

No entrena nada: solo sirve para probar el flujo y medir memoria mientras no exista el modelo
real. Sus resultados no tienen validez y la app lo anuncia (`is_demo: true`).

Requiere TensorFlow (requirements-ml.txt); la app en producción NO lo necesita.

Uso, desde la raíz del repo:
    python -m backend.ml_tools.build_demo_model --out C:/ruta/fuera/del/repo/demo-model
Genera: model.keras, model.tflite (salidas: probabilidades y activaciones de la última capa
convolucional), head.npz (pesos del Dense para CAM) y model_card.json.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

MODEL_VERSION = "demo-effb0-untrained-1"
CLASSES = ["normal", "benigno", "maligno"]
INPUT_SIZE = 224
# El EfficientNet de Keras trae Rescaling + Normalization DENTRO del modelo: espera píxeles
# en 0–255. Dividir entre 255 antes (como hacía el prototipo) da resultados absurdos.
PREPROCESSING = "raw_0_255"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(out: Path) -> dict:
    import tensorflow as tf
    from tensorflow import keras

    keras.utils.set_random_seed(42)
    base = keras.applications.EfficientNetB0(
        weights=None, include_top=False, input_shape=(INPUT_SIZE, INPUT_SIZE, 3)
    )
    features = base.output  # activaciones de la última capa convolucional (7x7x1280)
    pooled = keras.layers.GlobalAveragePooling2D(name="avg_pool")(features)
    probabilities = keras.layers.Dense(len(CLASSES), activation="softmax", name="predictions")(
        pooled
    )
    classifier = keras.Model(base.input, probabilities, name="breastguard_demo")
    exporter = keras.Model(base.input, [probabilities, features], name="breastguard_demo_cam")

    out.mkdir(parents=True, exist_ok=True)
    classifier.save(out / "model.keras")

    converter = tf.lite.TFLiteConverter.from_keras_model(exporter)
    (out / "model.tflite").write_bytes(converter.convert())

    kernel, bias = classifier.get_layer("predictions").get_weights()
    np.savez(out / "head.npz", kernel=kernel.astype(np.float32), bias=bias.astype(np.float32))

    # Verificación: misma imagen, mismas probabilidades en Keras y en TFLite
    from ai_edge_litert.interpreter import Interpreter

    sample = np.random.default_rng(0).integers(0, 256, (1, INPUT_SIZE, INPUT_SIZE, 3))
    sample = sample.astype(np.float32)
    keras_probs = classifier.predict(sample, verbose=0)[0]
    interpreter = Interpreter(model_path=str(out / "model.tflite"))
    interpreter.allocate_tensors()
    interpreter.set_tensor(interpreter.get_input_details()[0]["index"], sample)
    interpreter.invoke()
    tflite_probs = next(
        interpreter.get_tensor(d["index"])[0]
        for d in interpreter.get_output_details()
        if tuple(d["shape"]) == (1, len(CLASSES))
    )
    max_diff = float(np.max(np.abs(keras_probs - tflite_probs)))

    card = {
        "model_version": MODEL_VERSION,
        "is_demo": True,
        "description": "EfficientNet-B0 SIN ENTRENAR. Solo para pruebas de flujo y memoria.",
        "classes": CLASSES,
        "input_size": [INPUT_SIZE, INPUT_SIZE],
        "color_mode": "rgb",
        "preprocessing": PREPROCESSING,
        "head": "global_average_pooling+dense_softmax",
        "files": {name: sha256(out / name) for name in ("model.tflite", "head.npz")},
        "keras_vs_tflite_max_abs_diff": max_diff,
    }
    (out / "model_card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    return card


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    card = build(args.out)
    print(json.dumps(card, indent=2))


if __name__ == "__main__":
    main()
