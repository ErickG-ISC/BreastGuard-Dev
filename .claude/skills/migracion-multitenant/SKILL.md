---
name: migracion-multitenant
description: Crea, revisa y aplica migraciones de Alembic en BreastGuard para la base de control y para todas las bases de tenant (una base física por tenant). Úsalo cuando se agregue o cambie un modelo, tabla, columna o índice, al dar de alta un tenant nuevo, o cuando el usuario pida "migrar" o "actualizar el esquema".
disable-model-invocation: false
---

# Migración multitenant (BreastGuard)

Hay **dos tipos de base** y cada una tiene su propia línea de migraciones:

| Base | Qué contiene | Alembic | Cómo se aplica |
|---|---|---|---|
| **Control** | `tenants` (con `dsn_cifrado`), usuarios globales, roles | `backend/alembic_control/` | una sola vez con `CONTROL_DATABASE_URL` |
| **Tenant** | pacientes, imágenes, resultados, diario, auditoría, paquetes compartidos | `backend/alembic_tenant/` | **en cada base de tenant** con `migrate_all_tenants` |

Si todavía no existen estas carpetas o el script, créalas primero (ver "Preparación inicial") y avisa al usuario.

## Reglas

1. Nunca uses `Base.metadata.create_all` ni modifiques esquemas a mano en la base.
2. Toda migración de tenant debe ser **idempotente** y compatible con bases ya existentes (`IF NOT EXISTS`, comprobaciones con el inspector de SQLAlchemy antes de crear o borrar).
3. Un cambio que va a ambas líneas (raro) se hace en **dos migraciones separadas**, una por línea.
4. Migraciones destructivas (borrar columnas o tablas, cambiar tipos) requieren confirmación explícita del usuario y un plan de datos; propón primero una migración aditiva.
5. Contra bases que no sean de desarrollo, **no ejecutes nada sin que el usuario lo autorice expresamente**. Por defecto trabaja contra bases locales o de desarrollo.
6. No imprimas ni registres DSN, contraseñas ni la llave `TENANT_DSN_KEY`. Muestra solo el `slug` del tenant.
7. Con Supabase usa siempre la cadena del Session pooler.

## Preparación inicial (solo si falta)

1. `pip install alembic` (agrégalo a `requirements.txt`).
2. Crea `backend/alembic_control/` y `backend/alembic_tenant/` con su `env.py`:
   - control: lee `CONTROL_DATABASE_URL` y usa solo los modelos de la base de control (metadata separada).
   - tenant: **recibe la URL por argumento** (`-x dburl=...` o configuración programática), no desde variables de entorno fijas, y usa solo la metadata de modelos de tenant.
3. Separa los modelos en dos `Base`/metadata: `ControlBase` y `TenantBase`, para que cada autogenerate vea solo lo suyo.
4. Crea `backend/scripts/migrate_all_tenants.py` (ver abajo).
5. Quita la creación de tablas de `/health`.

## Flujo para un cambio de esquema

1. **Identifica la línea** (control o tenant) según el modelo modificado.
2. **Genera la revisión** contra una base de desarrollo:
   - control: `alembic -c backend/alembic_control/alembic.ini revision --autogenerate -m "<descripcion>"`
   - tenant: `alembic -c backend/alembic_tenant/alembic.ini -x dburl=<URL_DEV> revision --autogenerate -m "<descripcion>"`
3. **Revisa el archivo generado a mano**: el autogenerate se equivoca con nombres de constraints, enums y tipos. Corrige, agrega idempotencia y escribe un `downgrade()` correcto.
4. **Aplica en desarrollo** y prueba subir y bajar una revisión:
   - `upgrade head`, luego `downgrade -1`, luego `upgrade head`.
5. **Aplica a todos los tenants** con el script: `python -m backend.scripts.migrate_all_tenants`.
   - Primero con `--dry-run` para listar qué tenants y qué revisión tiene cada uno.
6. **Verifica**: todas las bases quedan en la misma revisión (`--check` del script) y corre `pytest -q`, incluida la prueba de migraciones.
7. Invoca el subagente `tenant-isolation-reviewer` si la migración toca auditoría, archivos o relaciones entre usuarios y recursos.

## Script `migrate_all_tenants`

Comportamiento esperado:

- Lee la lista de tenants activos de la base de control, descifra cada DSN con `TENANT_DSN_KEY` **solo en memoria**.
- Para cada tenant aplica `upgrade head` de la línea de tenant, en secuencia (pocas bases; la claridad importa más que la velocidad).
- Un fallo en un tenant **no detiene a los demás**: registra el error por `slug`, continúa y termina con código de salida distinto de cero y un resumen.
- Opciones: `--dry-run`, `--check` (verifica que todas estén en `head`), `--tenant <slug>` (uno solo).
- El resumen imprime `slug`, revisión anterior y revisión nueva; nunca DSN.

## Alta de un tenant nuevo (CU-12)

Al crear un tenant, el endpoint de `platform_admin` debe:

1. Registrar la fila en `tenants` con el DSN cifrado.
2. Verificar conexión a la nueva base.
3. Ejecutar `upgrade head` de la línea de tenant **solo para esa base**.
4. Crear el primer `tenant_admin` en el tenant y su registro de auditoría.
5. Si algo falla a medias, marcar el tenant como inactivo y reportar el error; no dejar un tenant a medio provisionar activo.

## Qué reportar al terminar

- Línea afectada (control o tenant) y nombre de la revisión.
- Resultado de upgrade, downgrade y upgrade de nuevo en desarrollo.
- Salida resumida del script (tenants migrados / fallidos), sin DSN.
- Si la migración es destructiva o requiere acción manual en las bases reales, dilo claramente.
