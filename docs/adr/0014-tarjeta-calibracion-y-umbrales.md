# ADR 0014 — Tarjeta del modelo v2, calibración y umbrales

- Estado: aceptado (Semana 5, 2026-11-07)
- Extiende: ADR 0006 (ficha del modelo y LiteRT)

## Contexto
El modelo entrenado con BUSI todavía no existe; se entrena fuera del repo. Hace falta poder
integrarlo **sin tocar el resto**. Para eso se necesitan cuatro cosas:
- **Un solo preprocesamiento** compartido entre el entrenamiento y el servidor. Si cada lado preprocesa distinto, el modelo ve en producción imágenes que no aprendió, sin ningún error visible.
- **Calibración** de la confianza aplicada al servir.
- **Umbrales en un solo lugar**, con la posibilidad de ver su efecto antes de cambiarlos.
- Una página pública **"Acerca del modelo"** que muestre solo lo que trae la ficha.

## Decisión

### 1. Preprocesamiento compartido: `backend/app/ml/preprocess.py`
- Solo depende de numpy y Pillow. El entrenamiento lo **importa o lo copia tal cual**.
- Hace lo siguiente: convierte a RGB o gris, redimensiona sin conservar la proporción con interpolación bilineal de Pillow, y escala según el modo (`raw_0_255`, `scale_0_1`, `scale_minus1_1`).
- `PREPROCESSING_VERSION = 1`.
  - La ficha de un modelo real **debe** declarar `preprocessing_version`. Si falta o no coincide, el modelo no carga.
  - El de demostración puede omitirla.
- Se usa una **versión** y no un hash del archivo: un hash cambiaría con cualquier comentario y dejaría el modelo de producción sin cargar por un cambio inocuo.
- Lo que protege de verdad es la huella de paridad (ADR 0013). El CI falla ante cualquier cambio de los tensores, y la prueba exige que la huella sea de la versión vigente. Cambiar el comportamiento obliga a subir la versión y a regenerar las huellas y los modelos.

### 2. Tarjeta v2 (`ml/config.py`), compatible con la actual
Todos los campos nuevos son **opcionales**, pero si vienen se validan. Un valor inválido hace que la ficha no cargue: `/health` muestra `model: unavailable` y el análisis responde 503 (falla cerrado).

| Campo | Validación |
|---|---|
| `calibration` | `{"method": "temperature", "temperature": T}` con 0.05 ≤ T ≤ 20 |
| `preprocessing_version` | Igual a `PREPROCESSING_VERSION` (obligatorio si no es demo) |
| `description`, `intended_use` | Texto de 1 a 2000 caracteres |
| `training` | Objeto de textos, números o booleanos (dataset, imágenes, división por paciente…) |
| `metrics` | Números; `per_class` con clases conocidas; `confusion_matrix` de clases × clases con conteos enteros; `test_set` como texto |
| `limitations` | Lista de hasta 30 textos |
| `recommended_thresholds` | Números. **Solo informativo**: no se publica ni se aplica |

### 3. Calibración al servir
- `p_i ∝ p_i^(1/T)`, equivalente a `softmax(z/T)` sobre los logits.
- Se aplica en el predictor (`runtime._probabilities`) **antes** de construir `Prediction`. Así la confianza, el nivel del reporte, el "no concluyente" y el "sospechoso" del panel usan la probabilidad calibrada.
- T = 1, o la ficha sin `calibration`, deja la salida intacta: es el caso del modelo actual.
- Para el entrenamiento: T se ajusta en un conjunto de **validación**, nunca en el de prueba, minimizando el NLL. La ficha reporta el ECE antes y después de calibrar.

### 4. Umbrales
- Siguen **solo** en `MLSettings`: `confidence_high`, `confidence_min`, `suspicious_classes`, `malignant_attention_probability` y `max_normalized_entropy`.
- El frontend no tiene umbrales propios.
- Nunca se aplican umbrales de la ficha automáticamente.
- Si la calibración cambia, `ml_tools/threshold_effect.py` compara el escenario actual con el propuesto sobre un CSV de probabilidades de validación, sin imágenes:
  - cuántos casos cambian de nivel;
  - cuántos entran o salen de "sospechoso", con la misma regla del panel (prueba de equivalencia con `services/cases.is_suspicious`);
  - la sensibilidad en maligno.
- El cambio de `MLSettings` va después, aprobado y en un commit con su ADR.

### 5. Versiones y análisis previos
- Cada análisis guarda `model_version`, las probabilidades y el `report` en JSONB.
- **Nunca se recalculan.** Una prueba despliega otro modelo calibrado y comprueba que el `GET` de un análisis viejo devuelve exactamente lo mismo, y que leer no vuelve a pasar la imagen por el modelo.
- La versión se ve en el resultado de la paciente y en el caso de la médica.

### 6. "Acerca del modelo"
- `GET /api/v1/model/card` es público y no tiene tenant. Devuelve `ModelCard.public_view()`, una lista blanca **sin** huellas de archivos, rutas del bucket ni umbrales.
- La página `/acerca-del-modelo` está enlazada desde el pie de página público, el resultado y el caso. Muestra solo las secciones que existen en la ficha.
- Con el modelo de demostración dice "Modelo de demostración sin entrenar: no hay métricas".
- **Siempre** muestra el aviso de que no está validado para mastografía (`profiles.PROTOTYPE_WARNING`, independiente de la ficha). El perfil `mastografia_prototipo` no cambia.

### 7. Integrar el modelo nuevo
1. El entrenamiento genera, con `preprocess.py`:
   - `model.tflite`, con dos salidas: probabilidades y activaciones;
   - `head.npz`;
   - `model.keras`;
   - `model_card.json` v2, con `preprocessing_version`, `calibration`, `training`, `metrics` y `limitations`.

   Las métricas son honestas: matriz de confusión y sensibilidad en maligno, con la división por paciente.
2. `python -m backend.ml_tools.validate_model --model-dir <carpeta> --fingerprint tests/fixtures/parity_<version>.json` revisa:
   - la ficha y los sha256;
   - un análisis de humo;
   - la paridad con Keras;
   - los avisos.
3. Medir la memoria (ADR 0013) con `measure_memory` en Docker con 512 MB.
4. Si la ficha trae umbrales recomendados, correr `threshold_effect`, mostrar el efecto y decidir.
5. `upload_model.py` a un **prefijo nuevo** (`<model_version>/`) y cambiar `MODEL_PREFIX` en Render. Para volver atrás basta regresar la variable.

## Consecuencias
- Un modelo nuevo no requiere tocar código, salvo que la cabeza no sea GAP → Dense (ADR 0006) o que cambie el preprocesamiento.
- La ficha es contenido público: no debe llevar datos de pacientes ni rutas internas, y la lista blanca lo garantiza para lo que se publica.
- Los análisis hechos con el modelo de demostración conservan su versión y su aviso de demo para siempre.
- `model_version` es también el prefijo del bucket: solo letras, números, `.`, `-` y `_`
  (mismo formato que `MODEL_PREFIX`). Las claves de `training` y `metrics` son `snake_case`, 30
  como máximo; los valores de texto, hasta 2000 caracteres. Lo que se ponga ahí se publica.
- En producción conviene fijar `MODEL_CARD_SHA256` con la huella de la ficha validada.
- `upload_model` no sobrescribe una versión existente. Si una subida se corta, esa versión queda
  incompleta (el servidor la rechaza por sha256) y hay que subir con otra `model_version`.
