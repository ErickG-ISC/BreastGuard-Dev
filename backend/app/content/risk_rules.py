"""Reglas ORIENTATIVAS de factores a comentar con el médico (CU-01).

Simples, transparentes y en un solo lugar. No calculan una probabilidad de cáncer ni dan un
diagnóstico: solo señalan respuestas que vale la pena conversar en consulta. Borrador académico:
revisar con un profesional de la salud.
"""

from collections.abc import Callable
from dataclasses import dataclass

from backend.app.content.questionnaire import AnswersV1

# Niveles del resumen, de menor a mayor urgencia de consulta
LEVEL_NONE = "sin_factores"
LEVEL_DISCUSS = "factores_a_comentar"
LEVEL_SYMPTOMS = "sintomas_a_consultar"

LEVEL_MESSAGES = {
    LEVEL_NONE: (
        "No reportaste factores que destacar. Aun así, mantén tu autoexploración mensual y tus "
        "revisiones periódicas."
    ),
    LEVEL_DISCUSS: (
        "Algunas de tus respuestas son factores que conviene comentar con tu médica o médico en "
        "tu próxima consulta. Tenerlos no significa que tengas una enfermedad."
    ),
    LEVEL_SYMPTOMS: (
        "Mencionaste cambios que conviene revisar con un profesional pronto. Agenda una consulta; "
        "la mayoría de estos cambios tienen causas benignas, pero deben evaluarse."
    ),
}

# Edad desde la que la NOM-041-SSA2 recomienda la mastografía de tamizaje
SCREENING_AGE = 40


@dataclass(frozen=True)
class Rule:
    code: str
    label: str
    kind: str  # "factor" (a comentar) o "symptom" (a consultar pronto)
    applies: Callable[[AnswersV1], bool]


RULES: list[Rule] = [
    Rule(
        "age_screening",
        f"Tienes {SCREENING_AGE} años o más: edad de tamizaje recomendada",
        "factor",
        lambda a: a.age >= SCREENING_AGE,
    ),
    Rule(
        "family_first_degree",
        "Familiar directa (madre, hermana o hija) con cáncer de mama",
        "factor",
        lambda a: a.family_history_breast == "first_degree",
    ),
    Rule(
        "family_ovarian",
        "Familiar cercana con cáncer de ovario",
        "factor",
        lambda a: a.family_history_ovarian,
    ),
    Rule(
        "brca",
        "Mutación BRCA conocida",
        "factor",
        lambda a: a.brca_mutation == "yes",
    ),
    Rule(
        "previous_biopsy",
        "Biopsia de mama previa",
        "factor",
        lambda a: a.previous_biopsy,
    ),
    Rule(
        "hormone_therapy",
        "Uso de terapia hormonal de reemplazo",
        "factor",
        lambda a: a.hormone_therapy,
    ),
    Rule(
        "no_recent_checkup",
        "Más de 2 años (o nunca) sin revisión de mama con un profesional",
        "factor",
        lambda a: a.last_checkup in ("never", "more_than_2y"),
    ),
    Rule(
        "current_symptoms",
        "Cambios o síntomas actuales en la mama",
        "symptom",
        lambda a: bool(a.current_symptoms),
    ),
]


@dataclass(frozen=True)
class Evaluation:
    factors: list[dict]
    level: str
    message: str


def evaluate(answers: AnswersV1) -> Evaluation:
    matched = [rule for rule in RULES if rule.applies(answers)]
    if any(rule.kind == "symptom" for rule in matched):
        level = LEVEL_SYMPTOMS
    elif matched:
        level = LEVEL_DISCUSS
    else:
        level = LEVEL_NONE
    factors = [{"code": r.code, "label": r.label, "kind": r.kind} for r in matched]
    return Evaluation(factors=factors, level=level, message=LEVEL_MESSAGES[level])
