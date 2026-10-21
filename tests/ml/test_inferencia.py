"""Servicio de inferencia con un predictor doble (rápidas, sin modelo ni TensorFlow)."""

import asyncio
import io

import numpy as np
import pytest
from fastapi import HTTPException
from PIL import Image

from backend.app.ml.config import ModelCard, ModelCardError
from backend.app.ml.heatmap import class_activation_map, generate_heatmap
from backend.app.ml.quality import (
    ImageQualityError,
    check_image,
    normalized_entropy,
    prediction_flags,
)
from backend.app.ml.report import DEMO_NOTICE, DISCLAIMER, build_report
from backend.app.ml.runtime import FakePredictor, Prediction, to_model_input
from backend.app.ml.service import (
    InferenceService,
    prepare_image,
    run_analysis,
)
from backend.app.ml.settings import MLSettings

SETTINGS = MLSettings()
CARD3 = {
    "model_version": "fake-3",
    "classes": ["normal", "benigno", "maligno"],
    "input_size": [224, 224],
    "preprocessing": "raw_0_255",
}
FORBIDDEN = ("tienes cáncer", "estás sana", "estas sana", "diagnóstico de", "no tienes cáncer")


def ultrasound(size=(320, 240)) -> Image.Image:
    rng = np.random.default_rng(1)
    return Image.fromarray(rng.gamma(2.0, 30.0, size[::-1]).clip(0, 255).astype(np.uint8), "L")


def png_bytes(image: Image.Image, fmt="PNG", **kwargs) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **kwargs)
    return buffer.getvalue()


class TestFichaDelModelo:
    def test_modelo_de_dos_clases_con_nombres_en_ingles(self):
        card = ModelCard.from_dict({**CARD3, "classes": ["benign", "malignant"]})
        assert card.classes == ("benigno", "maligno")

    @pytest.mark.parametrize(
        "change",
        [
            {"classes": ["benigno"]},
            {"classes": ["normal", "normal"]},
            {"classes": ["gato", "perro"]},
            {"preprocessing": "magia"},
            {"color_mode": "cmyk"},
        ],
    )
    def test_fichas_invalidas(self, change):
        with pytest.raises(ModelCardError):
            ModelCard.from_dict({**CARD3, **change})


class TestPreprocesamiento:
    def test_raw_0_255_no_divide(self):
        card = ModelCard.from_dict(CARD3)
        tensor = to_model_input(Image.new("L", (10, 10), 200), card)
        assert tensor.shape == (1, 224, 224, 3)
        assert tensor.max() == pytest.approx(200.0)

    def test_scale_0_1(self):
        card = ModelCard.from_dict({**CARD3, "preprocessing": "scale_0_1"})
        assert to_model_input(Image.new("L", (10, 10), 255), card).max() == pytest.approx(1.0)

    def test_escala_de_grises(self):
        card = ModelCard.from_dict({**CARD3, "color_mode": "grayscale", "input_size": [96, 96]})
        assert to_model_input(Image.new("RGB", (10, 10)), card).shape == (1, 96, 96, 1)


class TestMapaDeCalor:
    def test_cam_se_concentra_donde_hay_activacion(self):
        features = np.zeros((7, 7, 4), dtype=np.float32)
        features[2, 5, 1] = 3.0
        weights = np.array([0.0, 2.0, 0.0, 0.0], dtype=np.float32)
        cam = class_activation_map(features, weights)
        assert np.unravel_index(cam.argmax(), cam.shape) == (2, 5)
        assert cam.max() == pytest.approx(1.0)

    def test_cam_sin_activacion_positiva_es_cero(self):
        cam = class_activation_map(np.ones((7, 7, 2)), np.array([-1.0, -1.0]))
        assert cam.max() == 0.0

    def test_overlay_con_el_tamano_original(self):
        predictor = FakePredictor(ModelCard.from_dict(CARD3))
        heatmap = generate_heatmap(ultrasound((300, 200)), predictor)
        with Image.open(io.BytesIO(heatmap.overlay_png)) as overlay:
            assert overlay.size == (300, 200)


class TestCalidad:
    def test_ecografia_sintetica_pasa(self):
        assert check_image(ultrasound(), SETTINGS) == []

    @pytest.mark.parametrize(
        ("image", "code"),
        [
            (ultrasound((64, 64)), "too_small"),
            (Image.new("RGB", (300, 300), (200, 30, 40)), "color_image"),
            (Image.new("L", (300, 300), 128), "uniform"),
        ],
    )
    def test_rechazos(self, image, code):
        assert code in {issue.code for issue in check_image(image, SETTINGS)}

    def test_baja_confianza_y_alta_incertidumbre(self):
        uniform = Prediction(
            {"normal": 0.34, "benigno": 0.33, "maligno": 0.33}, np.zeros((1, 1, 1))
        )
        assert {"low_confidence", "high_uncertainty"} <= set(prediction_flags(uniform, SETTINGS))
        clear = Prediction({"normal": 0.95, "benigno": 0.04, "maligno": 0.01}, np.zeros((1, 1, 1)))
        assert prediction_flags(clear, SETTINGS) == []
        assert normalized_entropy({"a": 0.5, "b": 0.5}) == pytest.approx(1.0)


class TestReporte:
    @pytest.mark.parametrize(
        ("cls", "conf", "flags", "level"),
        [
            ("maligno", 0.9, [], "attention"),
            ("benigno", 0.9, [], "benign_pattern"),
            ("normal", 0.9, [], "no_findings"),
            ("normal", 0.4, ["low_confidence"], "inconclusive"),
        ],
    )
    def test_niveles_y_reglas(self, cls, conf, flags, level):
        report = build_report(cls, conf, flags, is_demo=False, settings=SETTINGS)
        text = " ".join([report["title"], *report["paragraphs"], report["recommendation"]]).lower()
        assert report["level"] == level
        assert report["disclaimer"] == DISCLAIMER
        assert "confianza" in text
        assert not any(phrase in text for phrase in FORBIDDEN)
        if level in ("attention", "inconclusive"):
            assert "consulta a tu médica o médico" in text
        if level == "no_findings":
            assert "no descarta" in text and "autoexploración" in text

    def test_confianza_baja_recomienda_consultar(self):
        report = build_report("normal", 0.55, [], is_demo=False, settings=SETTINGS)
        assert report["confidence_words"] == "baja"
        assert report["recommendation"].startswith("La confianza es baja: consulta")

    def test_aviso_de_modelo_de_demostracion(self):
        assert build_report("normal", 0.9, [], True, SETTINGS)["demo_notice"] == DEMO_NOTICE
        assert "demo_notice" not in build_report("normal", 0.9, [], False, SETTINGS)


class TestServicio:
    def test_analisis_completo_de_tres_clases(self):
        predictor = FakePredictor(
            ModelCard.from_dict(CARD3), {"normal": 0.05, "benigno": 0.1, "maligno": 0.85}
        )
        outcome = run_analysis(ultrasound(), predictor, SETTINGS)
        assert outcome.status == "completed"
        assert outcome.predicted_class == "maligno"
        assert outcome.model_version == "fake-3"
        assert outcome.report["level"] == "attention"
        assert outcome.heatmap_png.startswith(b"\x89PNG")

    def test_modelo_de_dos_clases(self):
        card = ModelCard.from_dict({**CARD3, "classes": ["benign", "malignant"]})
        outcome = run_analysis(
            ultrasound(), FakePredictor(card, {"benigno": 0.9, "maligno": 0.1}), SETTINGS
        )
        assert set(outcome.probabilities) == {"benigno", "maligno"}
        assert outcome.predicted_class == "benigno"

    def test_baja_confianza_es_no_concluyente(self):
        predictor = FakePredictor(ModelCard.from_dict(CARD3))  # probabilidades uniformes
        outcome = run_analysis(ultrasound(), predictor, SETTINGS)
        assert outcome.status == "inconclusive"
        assert outcome.report["level"] == "inconclusive"

    def test_imagen_a_color_se_rechaza_sin_inferir(self):
        predictor = FakePredictor(ModelCard.from_dict(CARD3))
        with pytest.raises(ImageQualityError):
            run_analysis(Image.new("RGB", (300, 300), (200, 30, 40)), predictor, SETTINGS)
        assert predictor.calls == 0

    def test_se_eliminan_los_metadatos_exif(self):
        exif = Image.Exif()
        exif[0x010F] = "MarcaDelTelefono"  # Make
        exif[0x8825] = {2: (19.0, 26.0, 0.0)}  # GPSInfo
        data = png_bytes(ultrasound().convert("RGB"), fmt="JPEG", exif=exif)
        with Image.open(io.BytesIO(data)) as original:
            assert original.getexif()
        clean = prepare_image(data)
        assert "exif" not in clean.info
        stored = run_analysis(
            clean, FakePredictor(ModelCard.from_dict(CARD3), {"normal": 0.9}), SETTINGS
        ).clean_image_png
        with Image.open(io.BytesIO(stored)) as saved:
            assert not saved.getexif()
            assert b"MarcaDelTelefono" not in stored

    def test_sin_modelo_responde_503(self):
        service = InferenceService(None, SETTINGS)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(service.analyze(png_bytes(ultrasound())))
        assert exc.value.status_code == 503

    def test_cola_llena_responde_503(self):
        settings = MLSettings(queue_timeout_seconds=0.05)
        service = InferenceService(FakePredictor(ModelCard.from_dict(CARD3)), settings)

        async def scenario():
            await service._semaphore.acquire()  # otro análisis ocupa el único lugar
            try:
                await service.analyze(png_bytes(ultrasound()))
            finally:
                service._semaphore.release()

        with pytest.raises(HTTPException) as exc:
            asyncio.run(scenario())
        assert exc.value.status_code == 503


class TestRevisionDeSeguridad:
    def test_imagen_enorme_se_rechaza_antes_de_decodificar(self):
        settings = MLSettings(max_pixels=10_000)
        data = png_bytes(Image.new("L", (200, 200)))
        with pytest.raises(ImageQualityError, match="demasiado grande"):
            prepare_image(data, settings)

    def test_bomba_de_descompresion_es_422_no_500(self, monkeypatch):
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
        with pytest.raises(ImageQualityError):
            prepare_image(png_bytes(Image.new("L", (100, 100))), MLSettings())

    @pytest.mark.parametrize("data", [b"no es una imagen", b"\x89PNG\r\n\x1a\n" + b"\x00" * 30])
    def test_bytes_ilegibles(self, data):
        with pytest.raises(ImageQualityError, match="No se pudo leer"):
            prepare_image(data)

    def test_imagen_grande_se_reduce(self):
        clean = prepare_image(png_bytes(ultrasound((3000, 1500))), MLSettings(max_side_px=1024))
        assert max(clean.size) == 1024

    def test_orientacion_exif_se_aplica_y_se_descarta(self):
        exif = Image.Exif()
        exif[0x0112] = 6  # rotar 90°
        data = png_bytes(ultrasound((300, 200)).convert("RGB"), fmt="JPEG", exif=exif)
        clean = prepare_image(data)
        assert clean.size == (200, 300)
        assert not clean.getexif()

    def test_probabilidad_de_maligno_notable_no_da_sin_hallazgos(self):
        probs = {"normal": 0.62, "benigno": 0.01, "maligno": 0.37}
        predictor = FakePredictor(ModelCard.from_dict(CARD3), probs)
        outcome = run_analysis(ultrasound(), predictor, SETTINGS)
        assert "notable_malignant_probability" in outcome.flags
        assert outcome.status == "inconclusive"
        assert outcome.report["level"] == "inconclusive"
        assert "consulta a tu médica o médico" in outcome.report["recommendation"].lower()

    @pytest.mark.parametrize(
        "probs",
        [
            {"normal": float("nan"), "benigno": 0.0, "maligno": 0.0},
            {"normal": 0.9, "benigno": 0.9, "maligno": 0.9},
            {"normal": float("inf"), "benigno": 0.0, "maligno": 0.0},
        ],
    )
    def test_salida_invalida_es_no_concluyente(self, probs):
        prediction = Prediction(probs, np.zeros((1, 1, 1)))
        assert prediction_flags(prediction, SETTINGS) == ["invalid_output"]

    def test_lock_impide_inferencias_solapadas(self):
        import threading
        import time

        from backend.app.ml.runtime import LiteRTPredictor

        active, overlaps = [0], []

        class SlowInterpreter:
            def set_tensor(self, *a):
                active[0] += 1
                if active[0] > 1:
                    overlaps.append(True)
                time.sleep(0.01)

            def invoke(self):
                time.sleep(0.01)

            def get_tensor(self, index):
                active[0] -= 1 if index == "features" else 0
                if index == "probs":
                    return np.array([[0.2, 0.3, 0.5]])
                return np.zeros((1, 7, 7, 2))

        predictor = LiteRTPredictor.__new__(LiteRTPredictor)
        predictor.card = ModelCard.from_dict(CARD3)
        predictor._interpreter = SlowInterpreter()
        predictor._input, predictor._probs_index, predictor._features_index = 0, "probs", "features"
        predictor._lock = threading.Lock()
        threads = [
            threading.Thread(target=predictor.predict, args=(ultrasound(),)) for _ in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert overlaps == []
