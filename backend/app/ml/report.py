"""Reporte en lenguaje sencillo, por PLANTILLAS (sin LLM). Umbrales en ml/settings.py.

Reglas: nunca afirmar un diagnóstico; ante sospecha o baja confianza, "consulta a tu médico";
un resultado normal no descarta nada; siempre el aviso de herramienta de apoyo; tono calmado.
"""

from backend.app.ml.settings import MLSettings

DISCLAIMER = "Herramienta de apoyo al diagnóstico. No sustituye el criterio ni la consulta médica."
DEMO_NOTICE = (
    "Modelo de demostración: este resultado se generó con un modelo sin entrenar y NO tiene "
    "ninguna validez. Sirve solo para probar la aplicación."
)
CLASS_LABELS = {
    "normal": "sin hallazgos destacados",
    "benigno": "hallazgo de aspecto benigno",
    "maligno": "hallazgo que conviene revisar",
}


def confidence_words(confidence: float, settings: MLSettings) -> str:
    if confidence >= settings.confidence_high:
        return "alta"
    if confidence >= settings.confidence_min:
        return "moderada"
    return "baja"


def build_report(
    predicted_class: str,
    confidence: float,
    flags: list[str],
    is_demo: bool,
    settings: MLSettings,
) -> dict:
    words = confidence_words(confidence, settings)
    percent = round(confidence * 100)
    confidence_text = (
        f"El modelo tiene una confianza {words} en esta estimación ({percent} de cada 100)."
    )

    if flags:
        level = "inconclusive"
        title = "Resultado no concluyente"
        body = [
            "El modelo no pudo dar una estimación clara para esta imagen. Puede deberse a la "
            "calidad de la imagen o a que se parece poco a las ecografías con las que se entrenó.",
            confidence_text,
        ]
        recommendation = (
            "Consulta a tu médica o médico y lleva tu estudio original. Si quieres, puedes "
            "intentar con otra imagen de mejor calidad."
        )
    elif predicted_class in settings.suspicious_classes:
        level = "attention"
        title = "Conviene revisar esta imagen con tu médico"
        body = [
            "El modelo encontró en la imagen un patrón que conviene revisar con un profesional. "
            "Esto no es un diagnóstico: muchas veces estos hallazgos resultan no ser graves, pero "
            "es importante que alguien con formación médica lo valore.",
            confidence_text,
            "El mapa de calor muestra las zonas en las que se fijó el modelo.",
        ]
        recommendation = (
            "Consulta a tu médica o médico pronto y lleva este resultado junto con tu estudio "
            "original."
        )
    elif predicted_class == "benigno":
        level = "benign_pattern"
        title = "El modelo estimó un patrón de aspecto benigno"
        body = [
            "El modelo estimó que la imagen se parece a hallazgos de aspecto benigno. Esto no es "
            "un diagnóstico y no sustituye la valoración de un profesional.",
            confidence_text,
            "El mapa de calor muestra las zonas en las que se fijó el modelo.",
        ]
        recommendation = (
            "Comenta este resultado con tu médica o médico en tu próxima consulta, sobre todo si "
            "notas algún cambio."
        )
    else:
        level = "no_findings"
        title = "El modelo no destacó hallazgos en esta imagen"
        body = [
            "El modelo no encontró patrones destacados en esta imagen. Esto no descarta nada: "
            "ninguna herramienta automática puede asegurar que no haya un problema.",
            confidence_text,
        ]
        recommendation = (
            "Sigue con tu autoexploración mensual y tus revisiones periódicas. Si notas cualquier "
            "cambio, consulta a tu médica o médico."
        )
    if words == "baja" and level != "inconclusive":
        recommendation = "La confianza es baja: consulta a tu médica o médico. " + recommendation

    report = {
        "level": level,
        "title": title,
        "summary": CLASS_LABELS.get(predicted_class, predicted_class),
        "paragraphs": body,
        "recommendation": recommendation,
        "confidence_words": words,
        "disclaimer": DISCLAIMER,
    }
    if is_demo:
        report["demo_notice"] = DEMO_NOTICE
    return report
