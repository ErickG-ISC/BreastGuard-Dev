"""Validación de un modelo NUEVO antes de subirlo al bucket (ADR 0014). Nada se sube aquí.

Comprueba, en este orden, y termina con código 1 si algo falla:
1. ficha y archivos: esquema de la tarjeta v2, sha256 de cada archivo y versión del
   preprocesamiento (lo mismo que hace el servidor al cargar: `loader._verify`);
2. carga con LiteRT y un análisis de humo sobre el conjunto sintético (salidas finitas que suman 1);
3. paridad Keras ↔ LiteRT (si hay model.keras y TensorFlow; `ml_tools/parity.py`);
4. memoria aproximada (solo Linux; la cifra oficial es la de `measure_memory` en Docker con
   512 MB, ADR 0013);
5. resumen de lo que publicará "Acerca del modelo" y avisos (sin métricas, sin calibración,
   umbrales recomendados distintos de los vigentes).

Uso, desde la raíz:
    python -m backend.ml_tools.validate_model --model-dir <carpeta> \\
        [--fingerprint tests/fixtures/parity_<version>.json]
Después: `upload_model.py` a un prefijo NUEVO y cambiar MODEL_PREFIX en Render.
"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--fingerprint", type=Path, help="Guarda la huella de paridad aquí")
    args = parser.parse_args()

    from backend.app.ml.config import ModelCardError
    from backend.app.ml.loader import ModelUnavailableError, _verify
    from backend.app.ml.runtime import LiteRTPredictor
    from backend.app.ml.service import run_analysis
    from backend.app.ml.settings import MLSettings
    from backend.ml_tools import parity
    from backend.ml_tools.measure_memory import rss_mb

    problems: list[str] = []
    warnings: list[str] = []
    report: dict = {}

    try:
        card = _verify(args.model_dir)
    except (ModelUnavailableError, ModelCardError, KeyError, ValueError) as exc:
        print(json.dumps({"ok": False, "card": f"rechazada: {exc}"}, ensure_ascii=False))
        sys.exit(1)
    report["card"] = {"model_version": card.model_version, "is_demo": card.is_demo}

    predictor = LiteRTPredictor(args.model_dir, card)
    settings = MLSettings()
    for name, image in parity.synthetic_set()[:4]:
        outcome = run_analysis(image, predictor, settings)
        values = np.array(list(outcome.probabilities.values()))
        if not np.isfinite(values).all() or abs(values.sum() - 1) > 1e-3:
            problems.append(f"salida inválida en {name}")
    report["smoke"] = "ok" if not problems else "falló"

    has_keras = (args.model_dir / "model.keras").exists()
    try:
        import tensorflow  # noqa: F401

        has_tf = True
    except ImportError:
        has_tf = False
    summary = parity.run(args.model_dir, use_keras=has_keras and has_tf)
    if "keras_comparison" in summary:
        comparison = summary["keras_comparison"]
        report["parity"] = comparison
        if comparison["failures"]:
            problems.append(f"paridad fuera de tolerancia: {comparison['failures']}")
    else:
        report["parity"] = "omitida (sin model.keras o sin TensorFlow)"
        warnings.append("Paridad con Keras sin verificar: córrela con requirements-ml.txt")
    if args.fingerprint:
        args.fingerprint.write_text(
            json.dumps(parity.fingerprint(summary), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        report["fingerprint"] = str(args.fingerprint)

    if sys.platform.startswith("linux"):
        report["memory"] = rss_mb()
        warnings.append("Memoria orientativa: la oficial es measure_memory en Docker con 512 MB")

    public = card.public_view()
    report["public_view_fields"] = sorted(public)
    if card.is_demo:
        warnings.append("Es un modelo de DEMOSTRACIÓN (is_demo)")
    if not card.metrics:
        warnings.append("La ficha no trae métricas: 'Acerca del modelo' no mostrará ninguna")
    if not card.calibrated:
        warnings.append("Sin calibración: la confianza es la salida cruda del modelo")
    if card.recommended_thresholds:
        current = asdict(settings)
        different = {
            k: (current.get(k), v)
            for k, v in card.recommended_thresholds.items()
            if current.get(k) != v
        }
        if different:
            warnings.append(
                "Umbrales recomendados distintos de los vigentes (actual, recomendado): "
                f"{different}. Evalúalos con ml_tools/threshold_effect antes de cambiarlos."
            )

    report["ok"] = not problems
    report["problems"] = problems
    report["warnings"] = warnings
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    sys.exit(0 if not problems else 1)


if __name__ == "__main__":
    main()
