# ADR 0015 — Reportes PDF y HL7 v2 simulado (CU-10)

- Estado: aceptado (Semana 5, 2026-11-07)

## Contexto
CU-10 pide que la médica exporte el reporte de un caso como PDF e intercambie el resultado con
sistemas hospitalarios. Para un proyecto escolar, HL7 se **documenta y se simula**: no hay un
HIS o RIS real contra el cual probar. Opcionalmente, la paciente descarga su resultado en PDF.

## Decisión

### Rutas y reglas comunes
| Ruta | Quién | Formato |
|---|---|---|
| `GET /doctor/analyses/{id}/report.pdf` | médica responsable | PDF técnico |
| `GET /doctor/analyses/{id}/report.hl7` | médica responsable | HL7 v2.5.1 ORU^R01 (`application/hl7-v2`) |
| `GET /analyses/{id}/report.pdf` | paciente dueña | PDF sencillo |

- **Siempre con `TenantDb`** (RLS) y, además, el filtro explícito:
  - la médica usa `cases._visible` y debe ser la **responsable**. Con un traspaso pendiente, la de destino ve el caso pero recibe 409 al exportar;
  - la paciente usa `analyses._own`.
- **Ajeno o inexistente:** el mismo 404, con `case.denied` o `analysis.denied`. Pacientes y administradoras reciben 403 en las rutas de la médica.
- **Solo un análisis revisado:** con un BI-RADS asignado por una médica; si no, 409 "Asigna el BI-RADS…".
  - Tras un traspaso aceptado, la nueva responsable puede exportar la revisión de la anterior. El reporte dice quién la hizo ("Revisado por") y la ex responsable ya no ve el análisis (404).
  - Los 409 se auditan como `case.export_denied`, sin contenido. Los 404 se registran como `case.denied`, con el id del análisis.
- **Conexión:** la transacción se suelta antes de descargar de Storage y de generar el archivo, porque el pool es chico. La auditoría va en otra transacción con el mismo contexto.
- **Mapa de calor:** se descarga con `storage.download_bytes` solo si su ruta tiene el prefijo `{tenant_slug}/`. El HL7 no lo descarga.
- **Auditoría** sin contenido clínico: `case.export_pdf`, `case.export_hl7` y `analysis.export_pdf`.
  - **El id del registro de auditoría es el `report_id`** que lleva el documento (MSH-10 en HL7, el pie en el PDF). Así un reporte se rastrea hasta su exportación sin agregar columnas a `audit_log` (`audit.record(entry_id=…)`).
  - Si falla Storage (502) o la validación (404/409), no se registra ninguna exportación.
- **Respuesta:**
  - `Content-Disposition: attachment` con `breastguard-reporte-<report_id[:8]>.pdf|.hl7`, sin datos personales;
  - `Cache-Control: no-store` y `X-Content-Type-Options: nosniff`;
  - límite de 10 por minuto.

  CORS expone `Content-Disposition` para que el frontend lea el nombre.
- **Frontend:** la descarga va con axios, el token en el header y un `blob`. **Nunca con el token en la URL.** Si hay error, se lee el `detail` del blob.

### PDF (`services/report_pdf.py`)
- **fpdf2 2.9.0**, en Python puro, con **DejaVu Sans** (Unicode completo) en `backend/app/content/fonts/`.
  - fpdf2 es **LGPL-3.0**: se usa como librería sin modificarla, lo cual es compatible.
  - Su dependencia `fonttools` es MIT. La fuente tiene la licencia Bitstream Vera/DejaVu, que acompaña al archivo.
  - Se descartó ReportLab, que es más pesada.
- **Médica:**
  - institución y paciente (nombre y edad aproximada = edad registrada + años transcurridos);
  - fecha y tipo del estudio;
  - clase, confianza, estado y versión del modelo;
  - mapa de calor;
  - BI-RADS y recomendación **de la médica**, autora y fecha de la revisión;
  - id del reporte y fecha de emisión;
  - avisos: herramienta de apoyo, prototipo de mastografía si aplica, modelo de demostración si aplica.
- **Paciente:** su reporte en lenguaje sencillo, tal como se guardó, más el mapa de calor y los avisos. Sin BI-RADS.
- **Metadatos:** los del PDF (título, autor) son genéricos.
- **Memoria:** el mapa se reduce a 1024 px antes de incrustarlo. En el peor caso medido (PNG de 2048×1664 incomprimible, Docker con 512 MB), la generación suma unos 31 MB y el PDF pesa 2.3 MB.

### HL7 v2.5.1 ORU^R01 simulado (`services/hl7.py`, sin dependencias)
- **Segmentos:** `MSH`, `PID`, `OBR` y `OBX` (clase del modelo, confianza, versión del modelo, BI-RADS de la médica, recomendación, edad aproximada y un OBX por aviso).
- **Identificación:**
  - **MSH-11 = `T`** (entrenamiento): ningún receptor debe tomarlo como un resultado real;
  - receptor `SIMULADO`;
  - códigos **locales** (`L`).
- **Escapado:** todo texto que viene de datos se escapa (`\F\ \S\ \T\ \R\ \E\`) y pierde los CR, LF y caracteres de control. Un nombre con `|` o un CR no puede inventar campos ni segmentos.
- **Datos:** sin fecha de nacimiento, dirección ni identificadores externos. PID-3 es el id interno de la ficha, con el slug del tenant como autoridad.
- **Pruebas:** validador estructural propio (`tests/hl7_validator.py`):
  - orden de segmentos y separadores;
  - tipo y versión;
  - número de campos;
  - numeración de los OBX y tipos de valor;
  - NM numéricos;
  - escapes válidos;
  - ida y vuelta de un nombre con separadores.
- **UI:** "HL7 v2 (ORU^R01): simulación, no probada contra un sistema hospitalario".
- **Integración real:** cómo sería se describe en `docs/hl7-integracion.md`.

## Consecuencias
- No hay migración: el `report_id` reutiliza el id de la auditoría.
- La exportación queda en la bitácora del tenant (`GET /audit`) como cualquier acceso a datos de pacientes (CU-13).
- Si la médica cambia la revisión, un PDF nuevo refleja la revisión vigente. Los anteriores conservan su `report_id` y su fecha.
- HL7 sigue siendo una simulación. Conectarlo a un hospital exigiría el trabajo de `docs/hl7-integracion.md`.
