"""Perfiles del modelo (CU-09, ADR 0011): qué se analiza, con qué avisos y cómo se guarda.

Hoy los dos perfiles usan el MISMO predictor (el modelo de ecografías). Cambiar a un modelo de
mastografía real es cambiar el perfil, no los servicios.
"""

from dataclasses import dataclass

PROTOTYPE_WARNING = (
    "Prototipo: el modelo se entrenó con ecografías y no está validado para mastografías."
)


@dataclass(frozen=True)
class Profile:
    code: str  # se guarda en analyses.profile
    image_type: str  # se guarda en medical_images.image_type
    label: str
    warning: str | None


ULTRASOUND = Profile("ecografia_b2c", "BUSI", "Ecografía", None)
MAMMOGRAPHY = Profile("mastografia_prototipo", "mammography", "Mastografía", PROTOTYPE_WARNING)
PROFILES = {p.code: p for p in (ULTRASOUND, MAMMOGRAPHY)}


def profile_for(*, is_dicom: bool, modality: str | None) -> Profile:
    """JPG o PNG y DICOM de ecografía (US): perfil de ecografía. Cualquier otro DICOM: prototipo."""
    if not is_dicom or (modality or "").upper() == "US":
        return ULTRASOUND
    return MAMMOGRAPHY
