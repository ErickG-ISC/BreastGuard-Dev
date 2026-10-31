# ADR 0009: Fichas de institución y acceso clínico por rol

- Estado: aceptado
- Fecha: 2026-10-30
- Casos de uso: CU-07 (importar paquete), CU-08 (caso), CU-09 (DICOM) y CU-11 (panel)
- Resuelve el pendiente 5 de CLAUDE.md

## Contexto

Hasta la migración 0012, `clinical.patients` solo representaba a la paciente B2C con cuenta. Las
políticas por rol dejaban a `doctor` y `tenant_admin` ver **todo** su tenant (incluso las fichas
propias de pacientes con cuenta) y, a nivel de base, modificarlo.

La Semana 4 necesita además dos clases de ficha sin cuenta:
- la paciente que una doctora **importa** de un paquete;
- la que **crea** a mano.

En ambos casos solo su médica responsable debe verlas.

## Decisiones

1. **Se extiende `clinical.patients`** en lugar de crear otra tabla: las tablas dependientes
   (imágenes, análisis, diario...) siguen apuntando a una sola ficha.
   - Columnas nuevas: `origin` (`propio | importado | creado`), `responsible_doctor_id`, `status`
     (`pendiente | en_revision | revisado`), `age_years` + `age_recorded_on`, `source_package_id`
     y `updated_at`.
   - Edad, no fecha de nacimiento: es la edad a la fecha de importación o de alta. Es un dato
     menos identificable.
   - `source_package_id` es un uuid sin FK (no hay referencias de `clinical` a tablas de `control`
     que no sean identidad). Un índice único parcial `(tenant_id, source_package_id)` impide
     importar dos veces el mismo paquete en un tenant y sirve de guarda tras una caída.
2. **Migración 0013 en tres pasos**:
   1. expandir (todo NULL);
   2. rellenar: toda ficha existente queda `propio` con su `user_id`. Si hay fichas sin cuenta, la
      migración se detiene;
   3. restringir con NOT NULL y CHECK.

   CHECK `ck_patients_origin`:
   - `propio` ⇒ `user_id` presente y sin médica;
   - `importado | creado` ⇒ médica presente y sin `user_id`.

   La médica responsable lleva FK compuesta `(tenant_id, responsible_doctor_id) → control.users`.
   El downgrade se niega si hay fichas de institución, notas, revisiones o análisis de mastografía.
3. **Una sola regla de acceso clínico** (`rls.clinical_access_rule`, política RESTRICTIVE en
   `patients`, `medical_images`, `questionnaires`, `analyses`, `self_exams`, `symptom_entries`,
   `case_notes` y `analysis_reviews`; `USING` y `WITH CHECK` iguales):
   - `patient`: `user_id = current_user_id()`;
   - `doctor`: `responsible_doctor_id = current_user_id()`;
   - en las dependientes, la misma condición por `EXISTS` sobre `patients` con
     `(tenant_id, patient_id)`;
   - `tenant_admin` y `platform_admin`: **nada clínico**. `audit_log` conserva su política propia
     (es de acceso, no clínico; CU-13).

   La doctora tampoco ve las fichas *propias* de pacientes con cuenta de su tenant: llegan a ella
   solo por importación (CU-07).
4. **Las FKs no pasan por RLS**, así que las que unen filas de la misma paciente incluyen
   `patient_id`:
   - `analyses → medical_images (tenant_id, patient_id, id)`;
   - `analysis_reviews → analyses (tenant_id, patient_id, id)`.

   Sin esto, una doctora con dos pacientes podría colgar la imagen o el análisis de una en el caso
   de la otra. Es el mismo patrón que `symptom_entries → self_exams` (0010).
5. **Tablas nuevas**:
   - `clinical.case_notes`: solo inserción. La política `INSERT` exige `doctor` y
     `author_id = current_user_id()`. Corregir es escribir otra nota.
   - `clinical.analysis_reviews`: BI-RADS (CHECK de categorías) y recomendación **de la médica**;
     el modelo nunca asigna BI-RADS. Una por análisis. `INSERT` solo `doctor` con
     `reviewed_by = current_user_id()`; `UPDATE` solo de `birads`, `recommendation` y
     `updated_at`.
6. **Privilegios por columna**:
   - en `patients` la app solo actualiza `status` y `updated_at`: ni el origen ni la responsable
     ni el `user_id` cambian una vez creados;
   - `analyses` gana `profile` (`ecografia_b2c | mastografia_prototipo`) y `dicom_meta` (lista
     blanca desidentificada, ADR 0011).
7. **Comandos por rol** (`rls.restrict_command`, `COMMAND_RULES` en 0013): políticas RESTRICTIVE
   `FOR UPDATE` / `FOR DELETE` además de la regla de acceso.
   - Solo la paciente modifica o borra lo suyo: UPDATE y DELETE de `medical_images`,
     `self_exams` y `symptom_entries`, y DELETE de `analyses`. La doctora **ve** los datos de sus
     pacientes y **agrega** (análisis, notas, revisiones), pero no altera el diario ni los
     resultados.
   - Solo la doctora cambia el estado del caso (UPDATE de `patients`) y su revisión (UPDATE de
     `analysis_reviews`).
   - El catálogo (`tests/isolation/catalogo.py`) exige en toda tabla clínica una política
     RESTRICTIVE de lectura (USING) y otra de inserción (WITH CHECK); una tabla con solo
     `tenant_isolation` hace fallar la prueba.
   - La migración llama a `assert_bypass` al subir y al bajar: con un dueño sin BYPASSRLS, sus
     chequeos verían 0 filas y el downgrade borraría columnas con datos.
8. **`seed_demo`** crea las pacientes de demostración como fichas `creado` con la primera médica
   como responsable, sin cuentas.

9. **Traspaso de pacientes entre médicas** (migración 0014). Si una doctora se desactiva o deja
   de serlo, sus fichas no deben quedar invisibles para todos. La administración no puede moverlas
   (no tiene acceso clínico), así que el traspaso va en dos pasos:
   1. `tenant_admin` o `platform_admin` (con el alcance de `user_admin.Scope`) crea en
      `control.patient_handovers` un traspaso pendiente de X a Y. Lleva solo ids y fechas.
   2. Con el traspaso pendiente, la regla de acceso (`clinical_access_rule(..., handover=True)`)
      deja a Y ver a las pacientes de X y todo lo que depende de ellas. Las fichas nunca quedan sin
      nadie que las vea.
   3. Y lo acepta con **su** contexto (`POST /doctor/handovers/{id}/accept`, TenantDb): un UPDATE
      de `responsible_doctor_id` a su nombre, con `audit_log` y `admin_events` en la misma
      transacción.

   Reglas:
   - la app puede escribir `responsible_doctor_id`, pero la regla de acceso solo deja ponerse a
     una misma (o dejar a la de un traspaso hacia ella);
   - una política INSERT impide que una doctora cree fichas a nombre de otra;
   - un solo traspaso pendiente por médica de origen (uno nuevo reemplaza al anterior);
   - sin cadenas: no se crea si origen o destino ya están en otro traspaso pendiente;
   - el destino es una doctora activa del mismo tenant (otro tenant da 404);
   - cancelar quita la visibilidad de inmediato;
   - al desactivar a la doctora de destino o quitarle el rol, sus traspasos pendientes se
     cancelan;
   - `control` no tiene RLS y `app_user` es el mismo rol de las sesiones clínicas, así que el
     trigger `control.enforce_handover_writes` hace dos cosas: impide que una sesión con contexto
     de paciente o doctora cree traspasos, y solo deja que la doctora de destino marque como
     aceptado uno pendiente hacia ella;
   - en UPDATE de `patients`, el WITH CHECK exige que la fila resultante quede a nombre de la
     doctora del contexto. No puede pasar sus fichas a la médica de origen de un traspaso.

   No se usan funciones `SECURITY DEFINER` ni contextos fabricados: toda escritura clínica sale
   del JWT de quien la hace. Mientras no exista el panel médico, la doctora acepta en `/medico`.

## Rendimiento

`EXPLAIN (ANALYZE, BUFFERS)` como `app_user` con contexto de doctora, sobre Postgres 17 local:
- 3 tenants y 30 doctoras;
- 6 000 fichas, 18 000 análisis y 60 000 entradas de diario.

| Consulta | Plan | Tiempo |
|---|---|---|
| Panel: sus pacientes no revisadas + último análisis (LATERAL), filtro "maligno", 20 filas | Bitmap en `ix_patients_doctor_status` + `Index Scan Backward` en `ix_analyses_patient` por paciente | 1.1–2.3 ms |
| Contadores del panel | Bitmap en `ix_patients_doctor_status` | 0.3–0.4 ms |
| Caso: análisis de una paciente | `Index Scan Backward` en `ix_analyses_patient` | 0.7 ms |
| Caso: diario de 90 días | `Index Scan` en `ix_symptom_entries_patient` | 0.5 ms |

- Ningún `Seq Scan`.
- El `EXISTS` de la política se resuelve como un subplan con hash, evaluado **una vez por
  consulta** (las 200 fichas de la doctora), no una vez por fila.
- Todos los índices empiezan por `tenant_id`.
- Con la regla de traspasos de 0014 los tiempos son iguales (0.2–1.7 ms). La subconsulta a
  `control.patient_handovers` aparece en el plan pero no se ejecuta cuando no hay traspasos
  pendientes; cuando los hay, usa el índice parcial `ix_patient_handovers_to`.

## Consecuencias

- Pruebas de las Semanas 1 y 3 que usaban a `doctor` o `tenant_admin` como lectores de fichas
  propias se adaptaron: la lectora es la paciente, o el resultado esperado es "no ve nada". La
  intención (contexto A solo ve A) no cambia. La única prueba de la Semana 3 que se invierte es
  `test_el_personal_no_ve_autoexploraciones_de_pacientes_ajenas` (antes
  `test_el_personal_ve_solo_su_tenant`).
- El chequeo de aislamiento (CU-12) sigue usando `audit_log` como fila testigo.
- Endpoints clínicos para el personal (panel, caso, importación) llegarán en las ramas siguientes;
  los de paciente no cambian.
- Pendientes que quedan registrados:
  - `GET /images` y `GET /images/{id}` siguen aceptando al personal y hoy le responden vacío o
    404 (con `image.denied`). Se limitarán con el panel médico.
  - Un downgrade de 0013 descarta `status` y la edad de las fichas `propio`, que nacieron en 0013.
