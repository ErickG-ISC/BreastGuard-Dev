---
name: migracion-rls
description: Crea, revisa y aplica migraciones de Alembic en BreastGuard (una sola base Postgres con esquemas control y clinical y Row Level Security forzado). Úsalo cuando se agregue o cambie un modelo, tabla, columna, índice o política RLS, o cuando el usuario pida "migrar" o "actualizar el esquema".
---

# Migración con RLS (BreastGuard)

Hay **una sola base** y **una sola línea de migraciones** (`backend/migrations/`, `backend/alembic.ini`). Ver ADR 0001, 0002 y 0003.

| Esquema | Qué contiene | RLS |
|---|---|---|
| `control` | `tenants`, `users` (identidad y roles) | no; lo protegen los permisos de `app_user` |
| `clinical` | todo dato clínico y `audit_log` | **habilitado y forzado** en cada tabla |

## Reglas

1. Nunca uses `Base.metadata.create_all` ni cambies el esquema a mano.
2. Toda tabla de `clinical` se crea con los helpers de `backend/migrations/rls.py`, nunca con `op.create_table` suelto:
   - `create_tenant_table(name, *columns)`: agrega `tenant_id uuid NOT NULL DEFAULT clinical.current_tenant_id()` y la PK `(tenant_id, id)`.
   - `enable_tenant_rls(name)`: hace `ENABLE` + `FORCE ROW LEVEL SECURITY` y crea la política `tenant_isolation` con `USING` y `WITH CHECK`.
   - `add_role_policy(name, policy, using_sql, command=..., restrictive=True)`: agrega una política restrictiva por rol (por ejemplo, un paciente solo ve lo suyo).
   - `tenant_fk(name, columns, ref_table, ref_columns)`: crea una FK **compuesta** que siempre incluye `tenant_id`.
   - `grant_app(name, privileges)`: otorga permisos mínimos al rol de la app (`APP_DB_USER`). Nunca DDL; en tablas de bitácora, solo `SELECT, INSERT`.
3. Las políticas usan `(SELECT clinical.current_tenant_id())`, `(SELECT clinical.current_user_id())` y `(SELECT clinical.current_app_role())`. Fallan cerrado: sin contexto se ven 0 filas.
4. Prohibido en `clinical`:
   - vistas sin `WITH (security_invoker = true)`;
   - funciones `SECURITY DEFINER`;
   - FKs simples a ids clínicos;
   - tablas sin `tenant_id`.

   La prueba de catálogo (`tests/isolation/test_catalog.py`) falla si aparece cualquiera de estos.
5. Las migraciones son **idempotentes** (`IF NOT EXISTS`, `DROP POLICY IF EXISTS` antes de `CREATE POLICY`, comprobaciones con el inspector).
6. El `downgrade` no borra datos en silencio y **nunca borra roles** de Postgres, porque son de todo el clúster.
7. Las migraciones destructivas (borrar columnas o tablas, cambiar tipos) requieren confirmación explícita del usuario y un plan de datos. Propón primero una migración aditiva.
8. Solo bases de desarrollo, salvo autorización expresa del usuario. En producción las migraciones se corren a mano desde una computadora de desarrollo, nunca en el build de Render.
9. No imprimas ni registres `DATABASE_URL`, `APP_DB_PASSWORD` ni contraseñas. La contraseña de `app_user` entra a la migración por `set_config` y `format('%L')`, nunca interpolada en el SQL.
10. Con Supabase, corre las migraciones por el **Session pooler** (puerto 5432).
11. Nada en `public`: las tablas de la app viven en `control`/`clinical`, que no se exponen por la Data API.

## Flujo para un cambio de esquema

1. **Identifica el esquema** (`control` o `clinical`) y actualiza el modelo en `backend/app/models/control.py` o `clinical.py`.
2. **Genera la revisión** contra la base de pruebas local (`docker compose up -d db`):
   `alembic -c backend/alembic.ini -x dburl=<URL_DEV> revision --autogenerate -m "<descripcion>"`
3. **Reescribe el archivo a mano** con los helpers de `rls.py`. El autogenerate no conoce RLS, políticas ni permisos, y se equivoca con constraints compuestas.
4. **Prueba en Postgres**:
   - `pytest tests/test_migrations.py` (upgrade → downgrade → upgrade, idempotencia y coincidencia con los modelos);
   - `pytest tests/isolation` (catálogo y aislamiento).
5. **Aplica en desarrollo** solo si el usuario lo pide: `alembic -c backend/alembic.ini upgrade head`.
6. Invoca el subagente `tenant-isolation-reviewer` sobre el diff.

## Qué reportar al terminar

- Esquema afectado y nombre de la revisión.
- Resultado de upgrade, downgrade y upgrade de nuevo en Postgres, y de la prueba de catálogo.
- Si la migración es destructiva o requiere acción manual en la base real, dilo claramente.
