# ADR 0007: Recordatorios en el esquema `control` y despachador sin contexto clínico

- Estado: aceptado
- Fecha: 2026-10-22
- Casos de uso: CU-05 (recordatorios); relacionado con CU-03 y CU-04

## Contexto

Los recordatorios (autoexploración y repetir análisis) los tiene que disparar un proceso
programado que recorre **todas** las pacientes de **todos** los tenants. Si esa configuración
viviera en `clinical`, el despachador necesitaría leerla sin contexto de tenant, y para eso haría
falta una de dos cosas: un rol que ignore RLS o una excepción en las políticas. Ambas romperían la
regla "ninguna sesión sin contexto toca datos clínicos".

## Decisión

1. `control.reminders` y `control.reminder_notices` viven en `control`, sin RLS. Guardan solo
   configuración e identidad: tipo, frecuencia, hora, zona horaria, canales, modo discreto y
   fechas de ejecución. **No guardan datos de salud**: ni resultados, ni síntomas, ni notas.
2. El despachador usa la misma conexión `app_user` (NOSUPERUSER NOBYPASSRLS) **sin contexto**.
   En `clinical` eso significa 0 filas visibles y `INSERT` rechazado, así que aunque alguien
   agregue por error una consulta clínica, la base no devuelve nada. No hay rol ni engine nuevo,
   y nunca se usa el rol dueño.
3. Como `control` no tiene RLS, la pertenencia la garantiza el servicio:
   - todas las consultas de la paciente pasan por `_own_reminders` y `_own_notices`, que filtran
     por `user_id` **y** `tenant_id` del JWT;
   - la FK `(tenant_id, user_id) → users` impide asociar un recordatorio a un usuario de otro
     tenant.
4. Reclamo idempotente:
   - `SELECT … FOR UPDATE OF reminders SKIP LOCKED`, luego crear el aviso y avanzar
     `next_run_at`, todo en una sola transacción;
   - el `UNIQUE (reminder_id, due_at)` es la segunda barrera contra avisos duplicados;
   - los correos se envían fuera de la transacción, uno por uno, y un fallo solo marca
     `email_status = 'failed'`.
5. El endpoint `POST /internal/reminders/dispatch` exige el header `X-Cron-Secret`, comparado con
   `hmac.compare_digest`. Sin `REMINDER_CRON_SECRET` (32+ caracteres) responde 503: falla
   cerrado. Lo llama un workflow programado de GitHub Actions cada 15 minutos, que de paso
   despierta a Render.
6. Correo:
   - en modo discreto (por defecto) el correo no menciona la marca ni el tema;
   - siempre lleva un enlace de baja con un JWT de audiencia propia, que no sirve como sesión;
   - la baja es un `POST` desde una página, para que los escáneres de enlaces no den de baja a
     nadie;
   - por ahora el único adaptador es `console`.

## Consecuencias

- El aviso dentro de la app no depende del correo: la demo funciona aunque no haya proveedor.
- Si el despachador estuvo dormido, se genera **un** aviso y el siguiente se calcula desde
  ahora, sin ráfagas de avisos atrasados.
- Si el proceso muere entre el reclamo y el envío, el aviso queda en `pending`; un despacho
  posterior lo reintenta pasados 10 minutos (si la paciente sigue queriendo correo). Dos
  despachos muy seguidos podrían reintentar el mismo correo huérfano: es raro (el workflow
  tiene `concurrency` y corre cada 15 min) y solo duplicaría un correo, nunca un aviso.
- Las pruebas (`tests/api/test_dispatcher.py`) registran todo el SQL del despacho y fallan si
  aparece `clinical.` o si la sesión tiene `app.tenant_id`.
- Un olvido del filtro de pertenencia en `control` filtraría configuración ajena. Lo mitigan la
  función única de filtro, las pruebas de acceso cruzado y la revisión.
