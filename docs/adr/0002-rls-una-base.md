# ADR 0002 — Una sola base Postgres con RLS forzado (reemplaza "una base por tenant")

- Estado: aceptado (Semana 1, 2026-10-21). Reemplaza la parte multi-base del ADR 0001 y de la versión anterior de CLAUDE.md.

## Contexto
El diseño original era una base física por tenant más una base de control. En el plan gratuito eso cuesta proyectos, conexiones y migraciones por base que no podemos pagar. Necesitamos un aislamiento que **un error de código no pueda romper**, no solo filtros `WHERE tenant_id = ...` en la aplicación.

## Decisión
- **Una base Postgres** (Supabase) con dos esquemas: `control` (tenants, usuarios, roles) y `clinical` (todo dato clínico y la bitácora de auditoría). Ninguno está expuesto por la Data API.
- **Dos roles de base:**
  - el **dueño/migrador** (`DATABASE_URL`) solo corre Alembic y scripts de mantenimiento;
  - la app corre siempre como **`app_user`**: `NOSUPERUSER NOBYPASSRLS`, sin DDL, y en `audit_log` solo `SELECT, INSERT`.
  - La app se niega a arrancar si su rol es superusuario o BYPASSRLS, porque el `postgres` de Supabase tiene BYPASSRLS.
- **RLS habilitado y forzado** en toda tabla de `clinical`:
  - `tenant_id uuid NOT NULL DEFAULT clinical.current_tenant_id()`;
  - PK `(tenant_id, id)`;
  - política `tenant_isolation` con `USING` y `WITH CHECK` sobre `tenant_id = (SELECT clinical.current_tenant_id())`.
- **Falla cerrado:** `current_tenant_id()` es `NULLIF(current_setting('app.tenant_id', true), '')::uuid`. Sin contexto se ven 0 filas y los `INSERT` fallan.
- **FKs compuestas** `(tenant_id, x_id)` entre tablas clínicas: la base impide referenciar filas de otro tenant.
- **Contexto por transacción:** al iniciar cada transacción se ejecuta `set_config(..., true)` para `app.tenant_id`, `app.user_id` y `app.role`, con valores del JWT verificado. Nunca hay `SET` de sesión, así que funciona con el pooler de Supabase en modo transacción.
- **Políticas restrictivas por rol** encima de la de tenant (un paciente solo ve sus filas; solo `tenant_admin` lee la auditoría).
- **Un solo engine** (rol `app_user`, pool pequeño). Hay dos dependencias: `get_tenant_db` (con contexto, para datos clínicos) y `get_control_db` (sin contexto, para identidad y administración).
- Storage: prefijo `{tenant_slug}/`, bucket privado y URLs firmadas de corta duración.
- CU-07 sigue siendo "importar como copia": no habrá políticas que crucen tenants.

## Detalles de seguridad (revisión de diseño)
- **Contexto rancio**: el listener `after_begin` vive en el `sessionmaker` de la app y solo actúa si la sesión trae contexto (`session.info`), así que `get_control_db` nunca lo aplica. La app no usa autocommit. El pool hace `rollback` al devolver cada conexión (`reset_on_return`), y con eso caducan los `set_config(..., true)`. Hay pruebas para `commit()` seguido de otra consulta en la misma sesión y para dos peticiones de tenants distintos sobre la misma conexión.
- **Conexión de la app, que falla cerrado**:
  - la app nunca usa la contraseña de `DATABASE_URL`;
  - si faltan `APP_DB_PASSWORD` y `APP_DATABASE_URL`, no arranca;
  - al arrancar verifica `NOT rolsuper`, `NOT rolbypassrls` y que `current_user` sea el rol esperado (`APP_DB_USER`).
- **`app_user` no es dueño de nada** ni tiene `CREATE` en `control`, `clinical` ni `public`, así que no puede hacer `ALTER TABLE ... NO FORCE` ni `DROP POLICY`. El dueño de todo es el migrador. Se revoca `CREATE ON SCHEMA public FROM PUBLIC`.
- **Data API**: las migraciones revocan todo a `anon`, `authenticated` y `service_role` sobre los esquemas, tablas, funciones y secuencias de `control`/`clinical` (y sobre `public.alembic_version`). También ajustan `ALTER DEFAULT PRIVILEGES` en esos esquemas. La prueba de catálogo lo verifica cuando esos roles existen. Que los esquemas no estén en "Exposed schemas" y que la Data API esté desactivada se configura en el panel de Supabase.
- **Políticas por rol**: exigen un rol no nulo; un `app.role` o `app.user_id` nulo da 0 filas. En `audit_log`, el `WITH CHECK` del `INSERT` obliga `actor_id = app.user_id`.
- **Altas que escriben en otro tenant**: el alta de un tenant (CU-12) y el registro de pacientes aplican `set_config(..., true)` al tenant correspondiente **dentro de su propia transacción** y solo para insertar sus filas iniciales. Usan el mismo rol `app_user`, nunca el dueño. Son las únicas funciones que lo hacen (`services/tenants.py`, `services/auth.py`).
- **Chequeo de aislamiento**: corre en una transacción `READ ONLY` que termina en rollback y no inserta nada. Usa como fila testigo el registro `tenant.create` de la auditoría del tenant nuevo y devuelve solo conteos.
- **Riesgo residual de Storage**: la llave de servicio de Supabase salta las políticas de Storage. El aislamiento de archivos depende del prefijo `{tenant_slug}/` calculado en el servidor y de validar la fila (visible por RLS) antes de firmar. Riesgo aceptado para el prototipo.

## Consecuencias
- RLS deja de ser "último recurso": es la barrera principal, y la aplicación filtra además por usuario o rol.
- Toda tabla nueva de `clinical` se crea con los helpers de `backend/migrations/rls.py`. Una prueba de catálogo falla si alguna tabla queda sin RLS forzado o sin política, si hay vistas sin `security_invoker` o si hay funciones `SECURITY DEFINER`.
- Las pruebas de aislamiento corren contra Postgres real (SQLite no tiene RLS).
- No hay respaldo ni restauración por tenant; purgar un tenant es `DELETE` de sus filas (script con confirmación).
- Desaparecen `TENANT_DSN_KEY`, `CONTROL_DATABASE_URL` y `migrate_all_tenants`: hay una sola línea de Alembic contra una sola base.
