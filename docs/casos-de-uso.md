Casos de uso o Escenarios 
A. Actor: Paciente / Usuaria (modelo B2C) 
CU-01: Registro y evaluación inicial de riesgo 
Escenario: María, 34 años, se entera de la app por redes sociales tras leer sobre la importancia de la detección temprana. Se registra, completa un breve cuestionario de antecedentes (edad, historial familiar, síntomas previos) y elige un plan de suscripción. La app le explica qué tipo de imágenes puede subir (ecografías tipo BUSI) y le recuerda que no sustituye una consulta médica. 
Objetivo: Onboarding + consentimiento informado + activación de cuenta de pago. 
CU-02: Subida de imagen de ultrasonido y obtención de predicción 
Escenario: María recibió sus imágenes de ultrasonido mamario en una clínica y las tiene en su celular en formato JPG. Las sube desde la app móvil. El sistema procesa la imagen, genera una predicción (benigno/maligno/normal, con nivel de confianza), un heatmap superpuesto mostrando la zona de interés, y un reporte en lenguaje comprensible para ella (no un reporte clínico técnico), con una recomendación clara de "consulta a tu médico" cuando el resultado sea sospechoso. 
Objetivo: Caso de uso central del producto B2C — valor principal que paga la usuaria. 
CU-03: Autoexploración guiada 
Escenario: Es el primer domingo del mes y María recibe una notificación push: "Es momento de tu autoexploración". Abre la app, que la guía paso a paso con imágenes/video mostrando las posiciones correctas, qué buscar (bultos, cambios de textura, retracciones) y cuánto tiempo dedicar a cada zona. Al finalizar, le pregunta si notó algo distinto a la vez pasada. 
Objetivo: Educación + adherencia + generación de dato longitudinal. 
CU-04: Registro en el diario de síntomas 
Escenario: Tras la autoexploración, María registra en el diario que sintió sensibilidad en el seno izquierdo, adjunta una nota de texto libre y selecciona el "mapa corporal" para marcar la zona exacta. Días después, revisa el historial en forma de línea de tiempo para ver si el síntoma es recurrente o coincide con su ciclo menstrual. 
Objetivo: Trazabilidad de cambios en el tiempo, insumo posterior para consulta médica. 
CU-05: Configuración de recordatorios personalizados 
Escenario: María prefiere hacerse la autoexploración cada 28 días en vez del "primer domingo del mes" por defecto. Configura la frecuencia, el canal (push, email o ambos) y el horario. También activa un recordatorio adicional para repetirse su análisis de imagen cada
6 meses. 
Objetivo: Personalización que sostiene el hábito de prevención (retención del SaaS). 
CU-06: Consulta de contenido informativo / blog 
Escenario: Tras un resultado con nivel de confianza moderado, María se siente ansiosa. Entra a la sección de blog y encuentra artículos validados médicamente sobre "qué significa un resultado BI-RADS 3", testimonios y una sección de preguntas frecuentes. La app le sugiere contenido relacionado a partir de su último resultado. 
Objetivo: Reducir ansiedad, aportar valor educativo, aumentar tiempo de uso de la plataforma. 
CU-07: Compartir información con su oncólogo 
Escenario: María tiene cita con su oncóloga la próxima semana. Desde su cuenta, genera un "paquete de información" (resultados de análisis previos, heatmaps, diario de síntomas de los últimos 3 meses) y lo envía mediante un código o enlace seguro a la cuenta profesional de su médica, quien podrá revisarlo antes o durante la consulta. 
Objetivo: Puente entre el mundo B2C y B2B; principal ventaja de tener ambos modos en una sola app. 
B. Actor: Médico / Oncólogo (modelo B2B) 
CU-08: Revisión de caso enviado por una paciente 
Escenario: La Dra. Torres recibe una notificación de que María compartió su información. Ingresa a su panel profesional y visualiza el historial completo: imágenes, heatmaps, predicciones del modelo avanzado, y la línea de tiempo del diario de síntomas, todo organizado cronológicamente para apoyar la anamnesis clínica. 
Objetivo: Reducir tiempo de consulta, mejorar la calidad de la información clínica disponible. 
CU-09: Análisis de mastografía con modelo clínico avanzado 
Escenario: La Dra. Torres carga una mastografía en formato DICOM proveniente del sistema PACS de su hospital. El sistema, usando un modelo más robusto que el de la versión B2C, genera la predicción, el heatmap y un reporte técnico con terminología BI-RADS, listo para adjuntar al expediente clínico. 
Objetivo: Diferenciador clave del plan médico: compatibilidad DICOM y modelos de mayor precisión.
CU-10: Integración con sistema médico institucional 
Escenario: El hospital donde trabaja la Dra. Torres usa un sistema de expediente clínico electrónico (HIS/RIS). Ella exporta el reporte generado por la plataforma directamente a ese sistema (o lo descarga como PDF/HL7) para mantener un único expediente centralizado del paciente. 
Objetivo: Caso de uso de interoperabilidad — importante para adopción institucional. 
CU-11: Gestión de múltiples pacientes 
Escenario: La Dra. Torres tiene una lista de 40 pacientes activas en la plataforma. Desde su dashboard filtra por "resultados pendientes de revisión" o "casos con hallazgos sospechosos" para priorizar su día. 
Objetivo: Eficiencia operativa del médico que fomenta el uso recurrente de la herramienta (retención B2B). 
C. Actor: Administrador de plataforma / Tenant 
CU-12: Alta de un nuevo tenant institucional (clínica/hospital) 
Escenario: Una clínica privada decide contratar el plan B2B para su equipo de 5 oncólogos. El equipo de administración de la plataforma da de alta un nuevo tenant, lo que configura el aislamiento forzado por la base de datos (RLS) para esa institución, garantizando que sus datos jamás se mezclen con los de otro tenant. 
Objetivo: Sustenta tu requerimiento de aislamiento total de multitenencia; importante para cumplimiento normativo (datos médicos sensibles). 
CU-13: Auditoría y control de acceso 
Escenario: Un administrador de TI de la clínica necesita confirmar quién accedió al expediente de una paciente en los últimos 30 días, por una solicitud de auditoría interna. Consulta el log de accesos del tenant, que solo muestra actividad de ese tenant específico. 
Objetivo: Seguridad, trazabilidad y confianza — relevante para un sistema de salud.