"""Efecto de cambiar la calibración o los umbrales ANTES de aplicarlos (ADR 0014).

Lee un CSV de probabilidades de VALIDACIÓN (sin imágenes ni datos de pacientes) que produce el
entrenamiento, con una fila por imagen:

    label,normal,benigno,maligno        (también benign/malignant; `label` es opcional)
    maligno,0.10,0.30,0.60

Las probabilidades son las SALIDAS CRUDAS del modelo (antes de calibrar). Compara el escenario
actual (los umbrales de MLSettings y la temperatura actual) con el propuesto, usando el MISMO
código que el servidor (`prediction_flags`, `build_report`) y la misma definición de
"sospechoso" que el panel de la médica (`services/cases.is_suspicious`):

- cuántos casos cambian de nivel (sin hallazgos / patrón benigno / atención / no concluyente);
- cuántos entran o salen de "sospechoso";
- con `label`: sensibilidad en maligno (maligno real que queda en atención o sospechoso).

Nada se aplica solo: el cambio de MLSettings va después, en un commit con su ADR.

Uso:
    python -m backend.ml_tools.threshold_effect --predictions val.csv \\
        --temperature 1.4 --set confidence_min=0.55 --set malignant_attention_probability=0.2
"""

import argparse
import csv
import json
from collections import Counter
from dataclasses import fields, replace
from pathlib import Path

import numpy as np

from backend.app.ml.config import ALIASES, Calibration
from backend.app.ml.quality import prediction_flags
from backend.app.ml.report import build_report
from backend.app.ml.runtime import Prediction
from backend.app.ml.settings import MLSettings

TUNABLE = (
    "confidence_high",
    "confidence_min",
    "malignant_attention_probability",
    "max_normalized_entropy",
)
SUSPICIOUS_FLAG = "notable_malignant_probability"


def read_predictions(path: Path) -> tuple[list[str], list[np.ndarray], list[str | None]]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        columns = [c for c in reader.fieldnames or [] if c != "label"]
        classes = [ALIASES[c.strip().lower()] for c in columns]
        if sorted(classes) != sorted(set(classes)) or len(classes) not in (2, 3):
            raise SystemExit("El CSV debe tener 2 o 3 columnas de clase distintas")
        probs, labels = [], []
        for row in reader:
            probs.append(np.array([float(row[c]) for c in columns]))
            label = (row.get("label") or "").strip().lower()
            labels.append(ALIASES[label] if label else None)
    return classes, probs, labels


def evaluate(classes, raw: np.ndarray, temperature: float, settings: MLSettings) -> dict:
    calibrated = Calibration("temperature", temperature).apply(raw)
    prediction = Prediction(
        probabilities={c: float(p) for c, p in zip(classes, calibrated, strict=True)},
        features=np.zeros((1, 1, 1), dtype=np.float32),
    )
    flags = prediction_flags(prediction, settings)
    report = build_report(prediction.predicted_class, prediction.confidence, flags, False, settings)
    suspicious = prediction.predicted_class in settings.suspicious_classes or (
        SUSPICIOUS_FLAG in flags
    )
    return {"level": report["level"], "suspicious": suspicious, "class": prediction.predicted_class}


def compare(
    classes, probs, labels, current: tuple[float, MLSettings], proposed: tuple[float, MLSettings]
) -> dict:
    before = [evaluate(classes, p, current[0], current[1]) for p in probs]
    after = [evaluate(classes, p, proposed[0], proposed[1]) for p in probs]
    transitions = Counter(
        f"{b['level']} -> {a['level']}"
        for b, a in zip(before, after, strict=True)
        if b["level"] != a["level"]
    )

    def summary(results):
        out = {
            "levels": dict(Counter(r["level"] for r in results)),
            "suspicious": sum(r["suspicious"] for r in results),
        }
        malignant = [r for r, label in zip(results, labels, strict=True) if label == "maligno"]
        if malignant:
            # Un maligno real "se ve" si queda sospechoso o con nivel de atención/no concluyente
            seen = sum(
                r["suspicious"] or r["level"] in ("attention", "inconclusive") for r in malignant
            )
            out["malignant_cases"] = len(malignant)
            out["malignant_flagged"] = seen
            out["malignant_sensitivity"] = round(seen / len(malignant), 4)
        return out

    return {
        "n": len(probs),
        "current": summary(before),
        "proposed": summary(after),
        "changed_level": sum(transitions.values()),
        "transitions": dict(transitions.most_common()),
        "entered_suspicious": sum(
            a["suspicious"] and not b["suspicious"] for b, a in zip(before, after, strict=True)
        ),
        "left_suspicious": sum(
            b["suspicious"] and not a["suspicious"] for b, a in zip(before, after, strict=True)
        ),
    }


def parse_overrides(items: list[str]) -> dict[str, float]:
    out = {}
    for item in items:
        key, _, value = item.partition("=")
        if key not in TUNABLE:
            raise SystemExit(f"Umbral desconocido: {key} (permitidos: {', '.join(TUNABLE)})")
        out[key] = float(value)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--current-temperature", type=float, default=1.0)
    parser.add_argument("--temperature", type=float, default=1.0, help="Temperatura propuesta")
    parser.add_argument("--set", action="append", default=[], help="umbral=valor propuesto")
    args = parser.parse_args()
    classes, probs, labels = read_predictions(args.predictions)
    current = MLSettings()
    proposed = replace(current, **parse_overrides(args.set))
    result = compare(
        classes, probs, labels, (args.current_temperature, current), (args.temperature, proposed)
    )
    result["thresholds"] = {
        "current": {f.name: getattr(current, f.name) for f in fields(current) if f.name in TUNABLE},
        "proposed": {
            f.name: getattr(proposed, f.name) for f in fields(proposed) if f.name in TUNABLE
        },
        "temperature": {"current": args.current_temperature, "proposed": args.temperature},
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
