"""Cambios de memoria del ADR 0013: mismos resultados con menos memoria."""

import asyncio
import io

import numpy as np
import pytest
from fastapi import HTTPException
from PIL import Image
from pydicom import dcmread

from backend.app.ml import heatmap, service
from backend.app.ml.dicom import DicomError, derive_image
from tests.dicom_helpers import make_dicom


def _overlay_original(image: Image.Image, cam: np.ndarray) -> bytes:
    """La superposición de antes del ADR 0013 (colormap en float píxel a píxel)."""
    base = image.convert("RGB")
    heat = Image.fromarray((cam * 255).astype(np.uint8), mode="L").resize(
        base.size, Image.Resampling.BILINEAR
    )
    colored = Image.fromarray(
        heatmap._colormap(np.asarray(heat, dtype=np.float32) / 255.0), mode="RGB"
    )
    blended = Image.blend(base, colored, heatmap.OVERLAY_ALPHA)
    buffer = io.BytesIO()
    blended.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def test_tabla_de_color_identica_al_colormap():
    values = np.arange(256, dtype=np.uint8)
    assert np.array_equal(heatmap._JET_LUT[values], heatmap._colormap(values / np.float32(255)))


def test_superposicion_identica_a_la_anterior():
    rng = np.random.default_rng(5)
    image = Image.fromarray(rng.integers(0, 256, (300, 410), dtype=np.uint8), "L")
    cam = rng.random((7, 7)).astype(np.float32)
    new = Image.open(io.BytesIO(heatmap.overlay(image, cam)))
    old = Image.open(io.BytesIO(_overlay_original(image, cam)))
    assert np.array_equal(np.asarray(new), np.asarray(old))


def test_release_memory_no_falla_en_ningun_sistema():
    service.release_memory()  # en Linux llama a malloc_trim; en otros no hace nada


def test_dicom_sin_pixel_data_se_rechaza():
    ds = dcmread(io.BytesIO(make_dicom(rows=64, cols=64)))
    del ds.PixelData
    buffer = io.BytesIO()
    ds.save_as(buffer, enforce_file_format=True)
    with pytest.raises(DicomError):
        derive_image(buffer.getvalue())


@pytest.mark.parametrize("photometric", ["MONOCHROME2", "MONOCHROME1"])
def test_ventana_en_su_lugar_da_lo_mismo(photometric):
    """La ventana in place da el mismo PNG que la fórmula directa."""
    rng = np.random.default_rng(9)
    pixels = rng.integers(0, 4000, (256, 200), dtype=np.uint16)
    derived = derive_image(make_dicom(rows=256, cols=200, pixels=pixels, photometric=photometric))
    got = np.asarray(Image.open(io.BytesIO(derived.png)))
    low, high = 2000 - 4000 / 2, 2000 + 4000 / 2  # ventana de make_dicom
    expected = np.clip((pixels.astype(np.float32) - low) / (high - low), 0.0, 1.0)
    if photometric == "MONOCHROME1":
        expected = 1.0 - expected
    expected = (expected * 255.0 + 0.5).astype(np.uint8)
    assert np.array_equal(got, expected)


def test_el_servicio_libera_memoria_tras_cada_dicom(monkeypatch, predictor):
    from backend.app.ml.service import InferenceService
    from backend.app.ml.settings import MLSettings

    calls = []
    monkeypatch.setattr(service, "release_memory", lambda: calls.append(1))
    svc = InferenceService(predictor, MLSettings())
    asyncio.run(svc.analyze_dicom(make_dicom(rows=600, cols=480)))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(svc.analyze_dicom(b"no es un dicom"))
    assert exc.value.status_code == 422
    assert len(calls) == 2  # también cuando el estudio falla
