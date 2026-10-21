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

## Consecuencias
- RLS deja de ser "último recurso": es la barrera principal, y la aplicación filtra además por usuario o rol.
- Toda tabla nueva de `clinical` se crea con los helpers de `backend/migrations/rls.py`. Una prueba de catálogo falla si alguna tabla queda sin RLS forzado o sin política, si hay vistas sin `security_invoker` o si hay funciones `SECURITY DEFINER`.
- Las pruebas de aislamiento corren contra Postgres real (SQLite no tiene RLS).
- No hay respaldo ni restauración por tenant; purgar un tenant es `DELETE` de sus filas (script con confirmación).
- Desaparecen `TENANT_DSN_KEY`, `CONTROL_DATABASE_URL` y `migrate_all_tenants`: hay una sola línea de Alembic contra una sola base.
