"""Cuestionario de antecedentes v1 (CU-01): preguntas y validación de respuestas.

Borrador académico; las preguntas y las reglas de `risk_rules.py` deben revisarse con un
profesional de la salud antes de cualquier uso real.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

QUESTIONNAIRE_VERSION = "v1"

FamilyHistory = Literal["none", "first_degree", "second_degree", "unknown"]
YesNoUnknown = Literal["yes", "no", "unknown"]
Symptom = Literal["lump", "nipple_discharge", "skin_changes", "nipple_changes", "pain"]
LastCheckup = Literal["never", "less_than_1y", "1_to_2y", "more_than_2y"]


class AnswersV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    age: int = Field(ge=18, le=110)
    family_history_breast: FamilyHistory
    family_history_ovarian: bool
    brca_mutation: YesNoUnknown
    previous_biopsy: bool
    hormone_therapy: bool
    current_symptoms: list[Symptom] = Field(default_factory=list, max_length=5)
    last_checkup: LastCheckup


# Definición para el frontend: mismas claves que AnswersV1
QUESTIONS = [
    {"id": "age", "type": "number", "label": "¿Cuántos años tienes?", "min": 18, "max": 110},
    {
        "id": "family_history_breast",
        "type": "choice",
        "label": "¿Alguna familiar ha tenido cáncer de mama?",
        "options": [
            {"value": "none", "label": "No"},
            {"value": "first_degree", "label": "Sí, madre, hermana o hija"},
            {"value": "second_degree", "label": "Sí, abuela, tía o prima"},
            {"value": "unknown", "label": "No lo sé"},
        ],
    },
    {
        "id": "family_history_ovarian",
        "type": "boolean",
        "label": "¿Alguna familiar cercana ha tenido cáncer de ovario?",
    },
    {
        "id": "brca_mutation",
        "type": "choice",
        "label": "¿Te han dicho que tienes una mutación genética BRCA1 o BRCA2?",
        "options": [
            {"value": "yes", "label": "Sí"},
            {"value": "no", "label": "No"},
            {"value": "unknown", "label": "No lo sé / no me he hecho la prueba"},
        ],
    },
    {
        "id": "previous_biopsy",
        "type": "boolean",
        "label": "¿Te han hecho alguna biopsia de mama?",
    },
    {
        "id": "hormone_therapy",
        "type": "boolean",
        "label": "¿Usas o has usado terapia hormonal de reemplazo?",
    },
    {
        "id": "current_symptoms",
        "type": "multi",
        "label": "¿Notas actualmente alguno de estos cambios? (puedes elegir varios o ninguno)",
        "options": [
            {"value": "lump", "label": "Un bulto o zona más dura"},
            {"value": "nipple_discharge", "label": "Salida de líquido por el pezón"},
            {"value": "skin_changes", "label": "Cambios en la piel (hundimiento, enrojecimiento)"},
            {"value": "nipple_changes", "label": "Cambios en el pezón (se hunde o cambia)"},
            {"value": "pain", "label": "Dolor persistente en una zona"},
        ],
    },
    {
        "id": "last_checkup",
        "type": "choice",
        "label": "¿Cuándo fue tu última revisión de mama con un profesional?",
        "options": [
            {"value": "never", "label": "Nunca"},
            {"value": "less_than_1y", "label": "Hace menos de 1 año"},
            {"value": "1_to_2y", "label": "Hace 1 o 2 años"},
            {"value": "more_than_2y", "label": "Hace más de 2 años"},
        ],
    },
]
