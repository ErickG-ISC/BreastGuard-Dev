"""DICOM SINTÉTICOS generados en la prueba (nunca archivos reales).

Llevan nombre, ID, fechas, institución y médica FALSOS para comprobar que nada de eso llega a
la imagen derivada ni a la base.
"""

import io

import numpy as np
from pydicom import Dataset
from pydicom.dataset import FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

PERSONAL = {
    "PatientName": "Sintetica^Juana",
    "PatientID": "SINT-998877",
    "PatientBirthDate": "19700101",
    "InstitutionName": "Hospital Ficticio del Norte",
    "ReferringPhysicianName": "Ficticio^Doctor",
    "StudyDate": "20260101",
    "AccessionNumber": "ACC-5544",
}


def phantom(rows: int, cols: int, *, bright_left: bool = False) -> np.ndarray:
    rng = np.random.default_rng(3)
    img = rng.gamma(2.0, 300.0, (rows, cols)).clip(0, 4000)
    if bright_left:
        img[:, : cols // 2] = 3900  # mitad izquierda casi al máximo
        img[:, cols // 2 :] = 100
    return img.astype(np.uint16)


def make_dicom(
    *,
    rows: int = 600,
    cols: int = 480,
    transfer_syntax=ExplicitVRLittleEndian,
    photometric: str = "MONOCHROME2",
    modality: str = "MG",
    pixels: np.ndarray | None = None,
    window: tuple[float, float] | None = (2000, 4000),
    **extra,
) -> bytes:
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.1.2"
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.SOPClassUID = ds.file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    for key, value in PERSONAL.items():
        setattr(ds, key, value)
    ds.Modality = modality
    ds.ViewPosition = "MLO"
    ds.ImageLaterality = "R"
    ds.ImagerPixelSpacing = [0.07, 0.07]
    ds.Rows, ds.Columns = rows, cols
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = photometric
    ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 12, 11, 0
    if window:
        ds.WindowCenter, ds.WindowWidth = window
    arr = phantom(rows, cols) if pixels is None else pixels
    ds.PixelData = arr.tobytes()
    for key, value in extra.items():
        setattr(ds, key, value)
    if transfer_syntax != ExplicitVRLittleEndian:
        ds.compress(transfer_syntax, arr)
    buffer = io.BytesIO()
    ds.save_as(buffer, enforce_file_format=True)
    return buffer.getvalue()


def with_transfer_syntax(data: bytes, uid: str) -> bytes:
    """Mismo archivo declarando otra sintaxis (para probar el rechazo sin un codificador)."""
    from pydicom import dcmread
    from pydicom.encaps import encapsulate

    ds = dcmread(io.BytesIO(data))
    ds.file_meta.TransferSyntaxUID = uid
    # Una sintaxis comprimida exige píxeles encapsulados (aquí no son un flujo válido: da igual,
    # el rechazo ocurre al leer la cabecera)
    ds.PixelData = encapsulate([ds.PixelData])
    ds["PixelData"].VR = "OB"
    buffer = io.BytesIO()
    ds.save_as(buffer, enforce_file_format=True)
    return buffer.getvalue()
