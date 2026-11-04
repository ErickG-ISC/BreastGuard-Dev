# ADR 0012: Panel y caso de la médica

- Estado: aceptado
- Fecha: 2026-11-05
- Casos de uso: CU-11 (panel de pacientes) y CU-08 (revisión del caso)

## Contexto

Con la importación (ADR 0010) y las fichas de institución (ADR 0009), la médica necesita:
- ver de un vistazo a sus pacientes, con prioridad para las sospechosas;
- abrir el caso con su historial;
- anotar y marcar el caso como revisado.

Todo con la regla "la doctora solo ve a sus pacientes" (más las de un traspaso pendiente hacia
ella) y sin acceso clínico para la administración.

## Decisiones

1. **Rutas** (`api/v1/doctor.py` + `services/cases.py`, solo `doctor`, `TenantDb`):

   | Ruta | Para qué |
   |---|---|
   | `POST /doctor/patients/search` | Lista con filtro `todas`, `pendientes`, `sospechosos` o `revisadas`, búsqueda por nombre y paginación |
   | `GET /doctor/patients/summary` | Contadores |
   | `GET /doctor/patients/{id}` | El caso |
   | `PATCH /doctor/patients/{id}/status` | Cambiar el estado |
   | `POST /doctor/patients/{id}/notes`, `PATCH` y `DELETE /doctor/notes/{id}` | Notas |

   - **Búsqueda por POST:** el nombre buscado nunca va en la URL, ni en los logs de acceso de
     Render ni en el historial del navegador. El caso se abre por id.
   - **Filtro explícito además de RLS:** cada consulta lleva el mismo criterio que la política
     (`_visible`).
   - **Respuesta uniforme:** un id ajeno o inexistente da el mismo 404, auditado como
     `case.denied`.
   - **Auditoría** `case.list|read|status|note_create|note_update|note_delete`, sin el texto
     buscado ni el contenido de las notas.
2. **"Sospechoso", de una sola fuente:** el último análisis tiene una clase de
   `MLSettings.suspicious_classes` o la marca `notable_malignant_probability`. Esa marca la pone
   `ml.quality.prediction_flags` al analizar, con `malignant_attention_probability`.
   - El umbral no se repite en ninguna consulta.
   - Un resultado no concluyente solo por calidad (`low_confidence`, `high_uncertainty`) se muestra
     como "No concluyente", pero no cuenta como sospechoso.
   - Orden: sospechosos, luego pendientes, luego el análisis más reciente (o el alta, si no hay
     análisis).
3. **Estado del caso validado en la base** (migración 0017, trigger `enforce_case_status`):

   | Desde | Hacia |
   |---|---|
   | pendiente | en_revision, revisado |
   | en_revision | revisado, pendiente |
   | revisado | en_revision ("reabrir") |
   | revisado | pendiente, **solo de forma automática** |

   - Lo demás, incluido repetir el mismo estado, falla.
   - `reviewed_by` y `reviewed_at` los fija el trigger al revisar y los borra al reabrir; nadie
     puede escribirlos a mano (`protect_case_review`).
   - **Regreso automático:** un análisis nuevo devuelve el caso a pendiente (trigger en
     `analyses`, sin `SECURITY DEFINER`). En la sesión de una paciente no hace nada, porque el
     UPDATE de `patients` es solo de doctoras.
   - **Traspaso pendiente:** la ficha no cambia de estado hasta que la doctora lo acepte (409).
4. **Notas** (`case_notes`):
   - la autora las crea, edita y borra (políticas RESTRICTIVE `FOR UPDATE` y `FOR DELETE` con
     `author_id` igual a ella);
   - solo las doctoras las leen (RESTRICTIVE `FOR SELECT`): la paciente nunca las ve;
   - una colega que ve la ficha por un traspaso ve las notas, pero no las modifica.
5. **Imágenes del caso:** URLs firmadas de corta duración, solo para filas visibles por RLS y con
   el prefijo `{slug}/` del JWT, igual que en CU-02.
6. **Pantallas:**
   - `/medico` (panel, D01): contadores, filtros, búsqueda, tabla en escritorio y tarjetas en
     móvil; conserva los traspasos y el aviso de paquetes;
   - `/medico/pacientes/:id` (caso, D02): línea de tiempo, visor con opacidad del mapa de calor,
     diario ligado a autoexploraciones, cuestionario, notas y estado;
   - espacio reservado para DICOM y el reporte técnico (rama D);
   - el aviso de herramienta de apoyo usa la constante única del proyecto.
7. **Campana de la paciente:** al confirmar una importación o aceptar un traspaso de fichas
   importadas, se crea un aviso `share_update` para la paciente de origen. `GET /notices` lo une
   a sus recordatorios. El trigger de 0017 solo deja a la doctora responsable crearlo, y solo para
   la paciente de ese paquete.
8. **Escenario de demostración** (`backend/scripts/demo_flow.py`):
   - usa los mismos servicios de la API;
   - pacientes `demo-paciente-…@example.com` en el b2c comparten, y la doctora de un tenant
     `demo-…` importa;
   - los resultados son de guion (predictor doble, versión `demo-guion`);
   - `--clean` solo borra esas cuentas y sus copias en tenants `demo-…`, y se niega si alguna
     copia está en otro tenant.

## Rendimiento

`EXPLAIN (ANALYZE, BUFFERS)` como `app_user` en contexto de doctora, en Postgres 17 local:
**5 000 fichas de una sola doctora** (peor caso; 7 500 en total) y 3 análisis por ficha.

| Consulta | Plan | Tiempo |
|---|---|---|
| Panel: 20 filas ordenadas por prioridad | `patients` completa de la doctora + `LATERAL` con `Index Scan Backward` en `ix_analyses_patient` por ficha; top-N heapsort | 68 ms |
| Contadores | Igual, con agregado | 67 ms |

- El orden por "sospechoso" obliga a evaluar todas sus fichas, así que el costo es lineal. Lo
  domina la comprobación RLS de cada análisis (un `EXISTS` sobre `patients_pkey` por fila).
- Postgres elige `Seq Scan` en `patients` porque la doctora tiene 2/3 de la tabla. Con muchas
  médicas usa `ix_patients_doctor_status` (ADR 0009: ~2 ms con 200 fichas).
- Plan si alguna médica real pasa de ~5 000 fichas o de ~100 ms: guardar `last_analysis_at` y
  `last_suspicious` en `patients`, mantenidos por el trigger de 0017. La regla seguiría calculada
  en un solo lugar.

## Pendientes

- `GET /images` y `GET /images/{id}` siguen aceptando al personal. Le responden vacío o 404 por
  RLS, sin fuga. Restringirlos a pacientes obliga a reescribir unas 15 pruebas de la Semana 1;
  queda para la rama de pruebas.
- Alta manual de pacientes (`origin='creado'`): llega con la rama D (DICOM).
