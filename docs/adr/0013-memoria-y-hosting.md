# ADR 0013 — Memoria con el modelo cargado y decisión de hosting

- Estado: aceptado (Semana 5, 2026-11-07)
- Complementa a: ADR 0006 (LiteRT) y ADR 0011 (DICOM)

## Contexto
Render gratuito da unos 512 MB de RAM. Las mediciones anteriores se hicieron por separado: el
modelo con una ecografía (ADR 0006) y el DICOM sin el modelo (ADR 0011). Su suma estimaba unos
290 MB para una mastografía de 4096 px. Faltaba medir todo junto:
- TensorFlow con el modelo y la app cargados;
- una mastografía de 4096 px con el modelo cargado;
- el límite de 2 estudios a la vez.

## Medición
- **Entorno:** Docker `python:3.12-slim` con `--memory=512m --memory-swap=512m` y
  `requirements.txt` completo.
- **Modelo:** el de demostración (EfficientNet-B0 sin entrenar, `demo-effb0-untrained-1`, construido con `ml_tools/build_demo_model`).
- **Pico:** el `VmHWM` del proceso, con un proceso por escenario
  (`ml_tools/measure_memory.py`).
- **DICOM:** sintéticos de 12 bits (`tests/dicom_helpers.make_dicom`).
- **Ruta:** los estudios pasan por el `InferenceService` real, con el semáforo
  (`MAX_CONCURRENT_INFERENCES=1`) y el threadpool. Cada subida es su propia copia en memoria.

### Ecografía y TensorFlow
| Escenario | Pico de RSS | Primer análisis |
|---|---|---|
| App sola (FastAPI, SQLAlchemy, Supabase, pydicom) | 105 MB | — |
| **LiteRT con el modelo, un análisis de ecografía** | **187 MB** | 1.0 s |
| TensorFlow con el modelo y Grad-CAM, sin la app | 407 MB | 36 s (con el trazado) |
| **TensorFlow con el modelo, Grad-CAM y la app** | **479 MB** | 27 s |

TensorFlow con la app queda a 33 MB del límite, sin margen para una petición ni para un DICOM.
**TensorFlow no va en producción**, como ya decía el ADR 0006.

### Mastografía de 4096 px con el modelo cargado (LiteRT)
| DICOM | Archivo | Antes, 1 estudio | Antes, 2 a la vez | **Después, 1 estudio** | **Después, 2 a la vez** |
|---|---|---|---|---|---|
| 4096×3328, RLE | 27 MB | 429 MB | 489 MB | **304 MB** | **355 MB** |
| 4096×4096, sin compresión | 32 MB | 486 MB | 512 MB | **321 MB** | **371 MB** |
| 4096×4096, JPEG 2000 | 24 MB | 465 MB | **matado por falta de memoria** | **357 MB** | **419 MB** |

`MALLOC_ARENA_MAX=2` se probó y no cambió nada (±10 MB): el problema no era la fragmentación de glibc entre hilos.

## Qué estaba mal y qué se cambió
La estimación de 290 MB fallaba porque **el heatmap de una mastografía se calcula sobre la
imagen derivada de 2048 px**, y no sobre los 480×640 de una ecografía:

1. **Colormap con tabla** (`ml/heatmap.py`).
   - **Antes:** `_colormap` se aplicaba píxel a píxel en float32, con varias matrices temporales de unos 16 MB y un `np.stack` de unos 48 MB.
   - **Ahora:** el mapa redimensionado ya es uint8, así que se colorean sus 256 valores una vez (`_JET_LUT`) y se indexa.
   - El resultado es **idéntico** y está verificado.
2. **Lectura del DICOM sin un Dataset completo** (`ml/dicom.py`). `pydicom.pixels.pixel_array(BytesIO)` decodifica directo del archivo, sin guardar una segunda copia de PixelData.
3. **Ventana en el mismo arreglo:** las operaciones se hacen in place sobre la copia reducida en float32, sin temporales del tamaño de la imagen.
4. **`malloc_trim(0)` tras cada estudio DICOM** (`ml/service.py`, solo en Linux), antes de soltar el turno del semáforo.
   - Los decodificadores nativos (openjpeg, RLE) reservan bloques grandes fuera de Python. Sin el trim, el segundo estudio heredaba el pico del primero.
   - Con 2 JPEG 2000 bajó de 438 a 419 MB.
5. **Escape sin tocar código:** `MAX_STUDIES_IN_FLIGHT` sale del entorno (1 o 2, 2 por defecto; otro valor impide arrancar). Con 1, el peor caso es el de un estudio, 357 MB. El estudio que llega mientras otro está en curso espera hasta 20 s y luego recibe 503.

## Paridad LiteRT contra Keras
`ml_tools/parity.py` usa 24 imágenes sintéticas fijas, con semilla, de 6 tamaños y 4 texturas:

| Medida | Resultado | Tolerancia |
|---|---|---|
| Misma clase | 24 de 24 | todas |
| Diferencia máxima de probabilidad | 3e-08 | ≤ 1e-3 |
| Correlación mínima del CAM de numpy contra Grad-CAM de TF | 1.000 | ≥ 0.99 |

La huella `tests/fixtures/parity_demo-effb0-untrained-1.json` guarda, para cada imagen, el hash de los píxeles, el hash del tensor de entrada y las probabilidades de LiteRT:
- **en el CI,** sin TensorFlow ni modelo, comprueba que el preprocesamiento da **exactamente los mismos tensores**;
- **con el modelo** (`-m slow`), comprueba que LiteRT da las mismas probabilidades.

Se generó en Linux (Docker) y se reprodujo exacta en Windows.

**ONNX Runtime:** no hace falta. LiteRT da paridad exacta y cabe. Se reconsidera solo si un modelo futuro trae operaciones que LiteRT no soporta.

## Decisión
- **Seguir en Render gratuito con LiteRT.**
  - Todos los escenarios reales quedan por debajo de 400 MB.
  - El único que pasa es el extremo teórico, 2 JPEG 2000 de 4096×4096 a la vez, con 419 MB: 82 % de 512 y 93 MB de margen.
  - Se acepta, con la válvula `MAX_STUDIES_IN_FLIGHT=1`.
- **No hay migración de hosting.** Las alternativas se documentan en
  `docs/migracion-hosting.md` por si un modelo futuro no cabe. No se cambia de proveedor sin aprobación.
- **Modelo nuevo:** antes de subirlo se repiten estas mediciones con él (`measure_memory`, mismo contenedor) y la paridad, y se guarda su huella. Si su RSS supera el actual en más de 60 MB, se revisa esta decisión.

## Cómo repetirlo
```
# 1. Modelo de demostración (contenedor de herramientas con TensorFlow; no es la imagen de Render)
docker run --rm -v "<repo>:/repo:ro" -v "<salida>:/out" -w /repo python:3.12-slim \
  sh -c "pip install -r requirements.txt tensorflow-cpu==2.21.0 && python -m backend.ml_tools.build_demo_model --out /out"
# 2. Paridad y huella
python -m backend.ml_tools.parity --model-dir <salida> --write tests/fixtures/parity_<version>.json
# 3. Memoria, en un contenedor con --memory=512m --memory-swap=512m y requirements.txt
python -m backend.ml_tools.measure_memory --mode litert --model-dir /model
python -m backend.ml_tools.measure_memory --mode litert --model-dir /model --dicom x.dcm --concurrent 2
python -m backend.ml_tools.measure_memory --mode tf --model-dir /model --with-app
```

## Consecuencias
- La cifra del ADR 0011 ("peor caso de unos 290 MB") se corrige aquí: con el modelo cargado y estos cambios, una mastografía de 4096 px usa entre 304 y 357 MB.
- `malloc_trim` es específico de glibc. En Windows y macOS no hace nada, y la medición de referencia es la de Linux.
- En Render el servidor uvicorn suma unos MB que la medición no incluye. Después del despliegue hay que mirar **Metrics → Memory** tras un DICOM (ver `docs/despliegue.md`).
