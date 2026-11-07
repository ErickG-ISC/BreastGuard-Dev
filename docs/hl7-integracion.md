# Integración con un HIS o RIS real (HL7 v2): lo que falta

BreastGuard genera un **ORU^R01 v2.5.1 simulado** (ADR 0015): estructuralmente válido, con
códigos locales y `MSH-11 = T`. **No se ha probado contra ningún sistema hospitalario.** Esta
guía describe qué haría falta para una integración real; nada de esto está implementado.

## 1. Acuerdo con el hospital (antes de escribir código)
- **Perfil de interfaz** del hospital: versión (2.3, 2.5.1…), segmentos obligatorios, Z-segments propios y tabla de códigos. Cada hospital tiene el suyo.
- **Identificación de la paciente:** el número de expediente del hospital (MRN), no el id interno de BreastGuard.
  - Hace falta un mapeo ficha ↔ MRN, que hoy no existe. La institución lo capturaría al dar de alta o importar la ficha.
  - Incluiría también el `PID-3` con la autoridad asignadora del hospital.
- **Orden de origen:**
  - en radiología, el resultado responde a una orden del RIS (ORM^O01 u OML^O21). Su número va en `OBR-2` y `OBR-3`, y el número de acceso en `OBR-18` o `OBR-20`;
  - hoy BreastGuard usa el id del análisis porque no recibe órdenes.
- **Médica intérprete:** el identificador profesional de la médica (cédula o el id del hospital) en `OBR-32`.

## 2. Códigos estándar
| Dato | Hoy (simulado) | En producción |
|---|---|---|
| Estudio | `BG-US`, `BG-MG` (`L`) | LOINC del procedimiento (p. ej. ecografía de mama, mastografía) o el código del catálogo del RIS |
| Categoría BI-RADS | `BG-BIRADS` (`L`) | LOINC de "BI-RADS assessment category" y valores con códigos LOINC o RadLex; verificar los vigentes en loinc.org |
| Resultado del modelo | `BG-AI-*` (`L`) | Sin código estándar: enviarlo como observación local claramente marcada como apoyo de IA, o no enviarlo |
| Unidades | UCUM | UCUM |

Antes de producción se valida el mensaje con la herramienta del hospital o con un validador
de perfiles (p. ej. NIST HL7 v2).

## 3. Transporte
- **MLLP** (Minimal Lower Layer Protocol) sobre **TLS**, o una VPN hacia el motor de interfaces del hospital. Nunca HL7 en claro por internet.
- **Motor de interfaces** (Mirth Connect / NextGen Connect, Rhapsody, etc.) como intermediario: transforma al perfil del hospital, encola, reintenta y registra.
- **Acuse de recibo:**
  - `MSH-15` y `MSH-16` en `AL` o `ER` en lugar de `NE`;
  - procesar `ACK` con `MSA-1` = `AA`, `AE` o `AR`;
  - reintentos con el mismo `MSH-10`, que el receptor deduplica.
- **Cola persistente:** un envío no puede perderse si Render se duerme. Haría falta una tabla de salida con estado (pendiente, enviado, confirmado, error) y un despachador.

## 4. Alternativa moderna: FHIR
Si el hospital tiene una API FHIR R4, el equivalente es:
- un `DiagnosticReport` con `Observation`s (BI-RADS, recomendación, resultado del modelo como observación con `method` = IA);
- la `Patient` referenciada por identificador del hospital;
- el PDF como `Binary` o `DocumentReference`.

Autenticación con SMART on FHIR (OAuth2).

## 5. Seguridad y cumplimiento
- Consentimiento de la paciente para enviar sus datos al hospital, y registro de cada envío en la auditoría, como hoy con la exportación.
- Minimización: solo los campos del perfil acordado.
- El resultado del modelo nunca se envía como diagnóstico. Si el hospital lo acepta, va marcado como apoyo, con la versión del modelo y los avisos.
- Contrato de tratamiento de datos con la institución, y revisión de la normativa aplicable (en México, la NOM-024-SSA3-2012 sobre sistemas de información de registro electrónico para la salud).

## 6. Lo que sí existe hoy
- `GET /doctor/analyses/{id}/report.hl7`: el mensaje simulado, descargable, solo para la médica responsable y auditado (`case.export_hl7`).
- `tests/hl7_validator.py`: el validador estructural que usan las pruebas.
