# ADR 0006 — Inferencia con LiteRT y mapa de calor CAM en numpy

- Estado: aceptado (Semana 2, 2026-10-22)

## Contexto
Render gratuito da unos 512 MB de RAM. El modelo es un EfficientNet-B0 de Keras. El modelo real aún no existe, así que se usa uno de **demostración** (EfficientNet-B0 sin entrenar, 3 clases, `is_demo: true`).

## Medición
Contenedor `python:3.12-slim --memory=512m`, misma imagen sintética, `backend/ml_tools/measure_memory.py`.

| Ruta | Pico de RSS | Primer análisis |
|---|---|---|
| **LiteRT** + CAM numpy, **con la app completa** (FastAPI, SQLAlchemy, Supabase) | **184 MB** | 0.8 s |
| TensorFlow-CPU + Grad-CAM (GradientTape), **sin** la app | 443 MB | 2.3 s |

TensorFlow solo, al importarse, ya ocupa unos 350 MB. Con la app encima rondaría 510 MB: no cabe.

## Decisión
- **Producción sin TensorFlow.**
  - `requirements.txt` usa `ai-edge-litert==2.3.0`, que tiene wheels para Linux y Windows.
  - TensorFlow pasa a `requirements-ml.txt`, solo para las herramientas locales de `backend/ml_tools/`.
- **Exportación.** El modelo se exporta a `.tflite` con dos salidas: las probabilidades y las activaciones de la última capa convolucional.
  - Los pesos del Dense van en `head.npz`.
  - `model_card.json` es la **única fuente** de clases (2 o 3, con alias en inglés), tamaño de entrada, preprocesamiento y `model_version`, y lleva el sha256 de cada archivo.
- **Mapa de calor** con `generate_heatmap(image, model)`.
  - Para cabezas GAP → Dense, el Grad-CAM de la logit de clase es exactamente el CAM, Σ w_c,k · A_k.
  - Se calcula en numpy y se superpone con Pillow.
  - Una prueba lenta lo compara contra el Grad-CAM de TensorFlow sobre el modelo exportado: coinciden con tolerancia 1e-3.
- **Preprocesamiento.** El EfficientNet de Keras normaliza **dentro** del modelo y espera píxeles de 0 a 255 (`raw_0_255`). El prototipo dividía entre 255, un error que daba resultados absurdos.
- **Origen del modelo.** Bucket privado `ml-models/{model_version}/`.
  - El lifespan lo descarga a `MODEL_DIR` si falta, verifica el sha256 y lo carga **una sola vez**.
  - Si falla, la app arranca igual: `/health` muestra `model: unavailable` y el análisis responde 503.
- **Concurrencia.** Inferencia en el threadpool con un semáforo (`MAX_CONCURRENT_INFERENCES=1`) y espera máxima de 30 s; después, 503.
- **Entradas.**
  - Se rechazan las imágenes chicas, a color o casi uniformes.
  - La baja confianza o la alta incertidumbre dan un resultado `inconclusive`.
  - El EXIF se descarta siempre.

## Consecuencias
- Cambiar de modelo es exportar, subir con `backend/ml_tools/upload_model.py` y cambiar `MODEL_PREFIX`; no hay que tocar código si la cabeza es GAP → Dense.
- Si un modelo futuro tiene otra cabeza (por ejemplo, varias capas densas), el CAM deja de ser exacto: habrá que exportar el gradiente o cambiar `generate_heatmap`.
- El arranque en frío descarga unos 16 MB por arranque (segundos).
- Los resultados del modelo de demostración no tienen validez, y la app lo dice en pantalla y en el reporte.
