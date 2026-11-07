# ADR 0011: DICOM y perfiles del modelo

- Estado: aceptado
- Fecha: 2026-11-06
- Caso de uso: CU-09 (carga y análisis de estudios DICOM por la médica)

## Contexto

La médica necesita subir mastografías DICOM a sus fichas y ver un reporte técnico. El modelo
actual se entrenó (o se entrenará) con ecografías BUSI: **no es válido para mastografías**. Un
DICOM además trae datos personales en su cabecera y, a veces, grabados en los píxeles. Render
gratuito tiene ~512 MB de RAM.

## Decisiones

1. **Dependencias, todas MIT y con versiones de más de dos semanas:** `pydicom 3.0.2`,
   `pylibjpeg 2.1.0`, `pylibjpeg-openjpeg 2.6.0` (JPEG 2000) y `pylibjpeg-rle 2.2.0`.
   - JPEG Baseline lo decodifica Pillow, que ya estaba instalado.
   - **JPEG Lossless no se admite**: su decodificador libre (`pylibjpeg-libjpeg`) es GPL v3. Se
     rechaza con un mensaje que pide exportar sin compresión, en RLE o en JPEG 2000.
2. **Validación antes de decodificar** (`ml/dicom.py`):
   - archivo de 60 MB como máximo y firma `DICM`;
   - cabecera leída sin píxeles: lados de 32 a 4096 px, un solo cuadro, una muestra, 8 o 16
     bits, MONOCHROME1 o 2, sintaxis de transferencia en lista blanca;
   - `BurnedInAnnotation=YES` se rechaza, porque puede traer datos personales en la imagen.

   La decodificación no se puede interrumpir a media ejecución: el tope real lo ponen el tamaño y
   las dimensiones. Si tarda más de 10 s, se rechaza después.
3. **Conversión pensada para la memoria:**
   1. reducción por promedio de bloques en el tipo original, antes de la ventana (la copia en
      coma flotante ya es del tamaño reducido, 2048 px de lado);
   2. reescala (`RescaleSlope` y `RescaleIntercept`);
   3. ventana del DICOM o percentiles 0.5 a 99.5 si no la tiene;
   4. MONOCHROME1 invertida;
   5. 8 bits.

   Corre **dentro del semáforo de la inferencia** (`InferenceService.analyze_dicom`): un estudio
   a la vez en memoria.
4. **Desidentificación:**
   - el DICOM original **nunca se guarda**;
   - en Storage solo queda la imagen derivada en PNG, construida desde los píxeles y sin
     metadatos, más su mapa de calor;
   - `analyses.dicom_meta` lleva una lista blanca técnica: modalidad, vista, lateralidad,
     espaciado de píxel, filas, columnas, fotometría, bits y sintaxis;
   - nunca nombre, ID, fechas, institución ni médicos. Una prueba lo comprueba con un DICOM
     sintético que trae todos esos campos.
5. **Perfiles del modelo** (`ml/profiles.py`):
   - `ecografia_b2c`: JPG, PNG o DICOM de ecografía (`US`);
   - `mastografia_prototipo`: cualquier otro DICOM, con el aviso permanente "Prototipo: el modelo
     se entrenó con ecografías y no está validado para mastografías" en el reporte y en pantalla.

   Hoy los dos usan el mismo predictor. Cambiar a un modelo de mastografía (CBIS-DDSM, INbreast,
   VinDr-Mammo) es cambiar el perfil.
6. **Rutas de la médica** (`services/doctor_analyses.py`), solo sobre fichas de las que es
   responsable; con un traspaso pendiente, 409 hasta aceptarlo:

   | Ruta | Para qué |
   |---|---|
   | `POST /doctor/patients/{id}/analyses` | DICOM, JPG o PNG; 10 por minuto |
   | `PUT /doctor/analyses/{id}/review` | BI-RADS y recomendación |
   | `POST /doctor/patients` | Alta manual (`origin='creado'`) |

   - **Guardado compartido:** se reutiliza el de CU-02 (`analyses.store_outcome`), con rutas
     `{slug}/images|heatmaps/` del JWT.
   - **Regreso a pendiente:** el trigger de 0017 devuelve el caso a pendiente con cada estudio
     nuevo.
7. **El BI-RADS lo asigna la médica, nunca el modelo.**
   - **Desviación del wireframe D03:** dice "BI-RADS sugerido", pero el modelo no sugiere
     ninguna categoría.
   - Hay una revisión por análisis. Migración 0018: quien la edita queda como autora (UPDATE de
     `reviewed_by`, con una política que solo deja poner el propio id).
   - El PDF y el HL7 llegan en la Semana 5.

8. **Revisión de aislamiento** (sin hallazgos críticos; los medios se corrigieron):
   - **Lista blanca cerrada en `dicom_meta`:** la modalidad, la vista y la lateralidad se
     guardan solo si son códigos conocidos; un texto libre (que podría ser un nombre) queda en
     `null`.
   - **Memoria:**
     - el middleware `BodySizeLimit` rechaza con 413, antes de leer, todo cuerpo mayor que
       60 MB + 1 MB (FastAPI procesa el multipart antes de las dependencias);
     - como máximo 2 estudios en vuelo, con la lectura incluida; si no hay lugar en 20 s, 503.
   - **Falla cerrado:** un DICOM sin modalidad se trata como mastografía. En JPG o PNG la médica
     declara si es ecografía o mastografía. Un perfil desconocido muestra el aviso.
   - **Datos grabados en los píxeles:** si el DICOM no lo declara, el servidor no puede
     detectarlos. La médica confirma en cada subida que la imagen no muestra datos personales
     (requerido también por el servidor). Es una limitación consciente.
   - **Errores:** una cabecera mal formada da 422, no 500. Dos primeras revisiones simultáneas
     dan 409.

## Memoria (medida)

Docker `python:3.12-slim` con `--memory=512m` y `requirements.txt` completo
(`ml_tools/measure_memory.py --mode dicom`, un proceso por archivo). DICOM sintéticos con
textura, de 12 bits:

| Archivo | Tamaño | Decodificación | Pico con la app (108 MB sola) |
|---|---|---|---|
| 3328×2560, JPEG 2000 | 6 MB | 5.0 s | 190 MB |
| 4096×3328, RLE | 14 MB | 4.1 s | 210 MB |
| 5000×5000, sin compresión | 48 MB | 1.3 s | 269 MB |
| 5000×5000, JPEG 2000 | 18 MB | 7.1 s | 333 MB |

- El modelo LiteRT suma ~76 MB (pico de 184 MB con la app, ADR 0006).
- Con 5000 px el peor caso llegaba a ~409 MB, por encima del margen de 400 MB que se fijó. Por eso
  **el límite es 4096 px**: cubre las mastografías habituales (3328×4096) y deja el peor caso en
  ~290 MB.
- **Corrección (ADR 0013):** esa suma no incluía el mapa de calor sobre la imagen derivada de
  2048 px. Medido todo junto con el modelo cargado, el pico llegaba a 429–486 MB. Tras los
  cambios del ADR 0013 queda en 304–357 MB con un estudio y 419 MB con dos JPEG 2000 a la vez.

## Consecuencias

- Los estudios en JPEG Lossless hay que convertirlos antes de subirlos.
- Un DICOM con anotaciones grabadas no se acepta, aunque sea útil.
- El resultado del modelo en mastografías es solo demostrativo, y la interfaz lo dice siempre.
