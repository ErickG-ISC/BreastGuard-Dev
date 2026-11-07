"""CU-09: conversión de DICOM a imagen derivada (sin base de datos)."""

import io

import numpy as np
import pytest
from PIL import Image
from pydicom.uid import JPEG2000Lossless, RLELossless

from backend.app.ml import dicom
from backend.app.ml.dicom import DicomError, derive_image
from backend.app.ml.profiles import MAMMOGRAPHY, ULTRASOUND, profile_for
from tests.dicom_helpers import PERSONAL, make_dicom, phantom, with_transfer_syntax


def pixels_of(png: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(png)))


class TestConversion:
    @pytest.mark.parametrize("syntax", [None, RLELossless, JPEG2000Lossless])
    def test_sin_compresion_rle_y_jpeg2000(self, syntax):
        kwargs = {"transfer_syntax": syntax} if syntax else {}
        derived = derive_image(make_dicom(**kwargs))
        image = Image.open(io.BytesIO(derived.png))
        assert image.mode == "L" and image.size == (480, 600)
        assert derived.modality == "MG"

    def test_monochrome1_se_invierte(self):
        bright_left = phantom(200, 200, bright_left=True)
        normal = pixels_of(derive_image(make_dicom(rows=200, cols=200, pixels=bright_left)).png)
        inverted = pixels_of(
            derive_image(
                make_dicom(rows=200, cols=200, pixels=bright_left, photometric="MONOCHROME1")
            ).png
        )
        assert normal[:, :100].mean() > normal[:, 100:].mean()
        assert inverted[:, :100].mean() < inverted[:, 100:].mean()

    def test_sin_ventana_usa_percentiles(self):
        derived = derive_image(make_dicom(window=None))
        values = pixels_of(derived.png)
        assert values.min() == 0 and values.max() == 255

    def test_imagen_grande_se_reduce_antes_de_analizar(self):
        derived = derive_image(make_dicom(rows=3000, cols=2400))
        assert max(Image.open(io.BytesIO(derived.png)).size) <= dicom.DERIVED_SIDE


class TestDesidentificacion:
    def test_ni_la_imagen_ni_los_metadatos_llevan_datos_personales(self):
        derived = derive_image(make_dicom())
        image = Image.open(io.BytesIO(derived.png))
        assert image.info == {} or set(image.info) <= {"dpi"}  # sin texto ni EXIF
        flat = repr(derived.meta) + derived.png.decode("latin-1")
        for value in PERSONAL.values():
            assert value not in flat
            assert value.split("^")[0] not in flat
        assert set(derived.meta) == {
            "modality",
            "view_position",
            "laterality",
            "pixel_spacing_mm",
            "rows",
            "columns",
            "photometric",
            "bits_stored",
            "transfer_syntax",
        }
        assert derived.meta["view_position"] == "MLO" and derived.meta["laterality"] == "R"
        assert derived.meta["pixel_spacing_mm"] == [0.07, 0.07]

    def test_anotaciones_grabadas_se_rechazan(self):
        with pytest.raises(DicomError, match="anotaciones grabadas"):
            derive_image(make_dicom(BurnedInAnnotation="YES"))


class TestValidacion:
    def test_sin_firma_dicm(self):
        with pytest.raises(DicomError, match="firma DICM"):
            derive_image(b"\x00" * 200)

    def test_archivo_demasiado_grande(self, monkeypatch):
        monkeypatch.setattr(dicom, "MAX_DICOM_BYTES", 1000)
        with pytest.raises(DicomError, match="supera el máximo"):
            derive_image(make_dicom())

    def test_dimensiones_fuera_del_limite_antes_de_decodificar(self, monkeypatch):
        monkeypatch.setattr(dicom, "MAX_SIDE", 400)
        with pytest.raises(DicomError, match="Dimensiones"):
            derive_image(make_dicom())

    @pytest.mark.parametrize(
        ("extra", "message"),
        [
            ({"NumberOfFrames": 3}, "un solo cuadro"),
            ({"SamplesPerPixel": 3}, "escala de grises"),
            ({"PhotometricInterpretation": "RGB"}, "fotométrica"),
            ({"BitsAllocated": 32}, "bits"),
        ],
    )
    def test_cabeceras_no_admitidas(self, extra, message):
        with pytest.raises(DicomError, match=message):
            derive_image(make_dicom(**extra))

    def test_jpeg_lossless_tiene_mensaje_claro(self):
        data = with_transfer_syntax(make_dicom(), "1.2.840.10008.1.2.4.70")
        with pytest.raises(DicomError, match="JPEG Lossless"):
            derive_image(data)

    def test_sintaxis_desconocida(self):
        data = with_transfer_syntax(make_dicom(), "1.2.840.10008.1.2.4.80")  # JPEG-LS
        with pytest.raises(DicomError, match="sintaxis"):
            derive_image(data)

    def test_pixeles_corruptos(self):
        data = make_dicom(transfer_syntax=RLELossless)
        with pytest.raises(DicomError):
            derive_image(data[: len(data) // 2])

    def test_imagen_uniforme(self):
        flat = np.full((200, 200), 1000, dtype=np.uint16)
        with pytest.raises(DicomError, match="uniforme"):
            derive_image(make_dicom(rows=200, cols=200, pixels=flat, window=None))


class TestPerfiles:
    def test_dicom_de_mastografia_usa_el_perfil_prototipo(self):
        assert profile_for(is_dicom=True, modality="MG") is MAMMOGRAPHY
        assert MAMMOGRAPHY.warning and "Prototipo" in MAMMOGRAPHY.warning

    def test_ecografias_y_jpg(self):
        assert profile_for(is_dicom=True, modality="US") is ULTRASOUND
        assert profile_for(is_dicom=False, modality=None, declared="ecografia") is ULTRASOUND

    def test_falla_cerrado(self):
        assert profile_for(is_dicom=True, modality=None) is MAMMOGRAPHY
        assert profile_for(is_dicom=False, modality=None) is MAMMOGRAPHY


class TestCabecerasHostiles:
    def test_valores_mal_formados_son_dicom_error(self):
        with pytest.raises(DicomError):
            derive_image(make_dicom(RescaleSlope="inf"))

    def test_solo_codigos_de_la_lista_blanca(self):
        derived = derive_image(make_dicom(ViewPosition="PEREZ^ANA", Modality="XX"))
        assert derived.meta["view_position"] is None and derived.meta["modality"] is None
