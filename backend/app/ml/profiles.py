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


def profile_for(*, is_dicom: bool, modality: str | None, declared: str | None = None) -> Profile:
    """Falla cerrado: solo es ecografía lo que lo dice con certeza.

    - DICOM: ecografía solo con `Modality=US`; sin modalidad o con otra, prototipo.
    - JPG o PNG: lo declara la médica (`ecografia` o `mastografia`); sin declarar, prototipo.
    """
    if is_dicom:
        return ULTRASOUND if (modality or "").upper() == "US" else MAMMOGRAPHY
    return ULTRASOUND if declared == "ecografia" else MAMMOGRAPHY


def warning_for(code: str | None) -> str | None:
    """Aviso de un perfil guardado; un perfil desconocido lleva el aviso (falla cerrado)."""
    profile = PROFILES.get(code or "")
    return profile.warning if profile is not None else PROTOTYPE_WARNING
