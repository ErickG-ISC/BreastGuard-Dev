---
name: nuevo-endpoint
description: Crea un endpoint nuevo en BreastGuard siguiendo las reglas de multitenencia con RLS: ruta, esquemas Pydantic, servicio, dependencia de sesión (get_tenant_db o get_control_db), auditoría y pruebas con acceso cruzado en Postgres. Úsalo cuando el usuario pida agregar o implementar un endpoint, ruta o caso de uso (CU-xx) del backend.
---

# Nuevo endpoint (BreastGuard)

Sigue estos pasos en orden. Antes de empezar, relee la sección "Arquitectura objetivo: multitenencia" de `CLAUDE.md`; sus reglas no se negocian.

## 0. Entender qué se pide

- Identifica el caso de uso (CU-xx) en `docs/casos-de-uso.md` y el actor (`patient`, `doctor`, `tenant_admin`, `platform_admin`).
- Si el endpoint es grande o toca varias tablas, propón un plan corto y espera aprobación antes de codificar.
- Pregunta solo lo que no puedas deducir del caso de uso. No inventes requisitos.

## 1. Revisar lo existente

- Lee `backend/app/api/v1/` para ver el estilo de los routers y cómo se monta cada uno en `main.py`.
- Lee los modelos en `backend/app/models/` y los servicios en `backend/app/services/` que vayas a reutilizar.
- Recuerda: se ejecuta desde la raíz y los imports son absolutos (`backend.app...`); no hay `__init__.py`.

## 2. Esquemas (`backend/app/schemas/<recurso>.py`)

- Pydantic v2: un esquema de **entrada** y uno de **salida** por operación. Nunca devuelvas el modelo ORM directo.
- La entrada **no incluye** `tenant_id`, `user_id` ni `role`: salen del JWT.
- Valida tipos, longitudes y rangos; para archivos valida MIME, extensión y tamaño máximo.

## 3. Servicio (`backend/app/services/<recurso>.py`)

- Toda la lógica de negocio va aquí; el router solo orquesta.
- Recibe la `Session` como parámetro; **nunca** importa un engine ni crea sesiones. Para datos clínicos es la de `get_tenant_db` (con contexto RLS); para el esquema `control`, la de `get_control_db`.
- No llames a `set_config` ni cambies el contexto: lo aplica la dependencia en cada transacción.
- SQLAlchemy 2.0 con `select()`. Verifica siempre que el recurso pertenezca al usuario o a su rol antes de devolverlo o modificarlo.
- Si el recurso no existe **o** no pertenece al usuario, responde igual (404) para no revelar existencia.
- Usa `logging`, nunca `print`, y no registres datos clínicos ni tokens.

## 4. Router (`backend/app/api/v1/<recurso>.py`)

- Router delgado. Dependencias obligatorias:
  - sesión: `TenantDb` (alias de `Depends(get_tenant_db)`) para datos clínicos, o `ControlDb` solo para el esquema `control`
  - usuario: `CurrentUser` (alias de `Depends(get_current_user)`)
  - rol: `Depends(require_role("doctor"))` (o el que corresponda); los endpoints de plataforma exigen `platform_admin`.
- Define `response_model`, códigos de estado correctos y `HTTPException` con mensajes claros.
- Si el endpoint toca datos de pacientes (lectura o escritura), llama a `services/audit.record(...)` en la misma transacción (quién, acción, recurso, cuándo, IP), sin datos clínicos.
- Si maneja archivos: nombre aleatorio (uuid), ruta con prefijo `{tenant_slug}/` tomado de `CurrentUser`, limpieza de temporales en `finally` y URLs firmadas de corta duración en bucket privado (nunca URL pública).
- Registra el router en `main.py` bajo `/api/v1/<prefijo>`.

## 5. Modelo y migración (solo si hay tablas nuevas o cambios)

- Crea o modifica el modelo en `backend/app/models/`.
- Usa la skill `migracion-rls`: toda tabla de `clinical` se crea con los helpers de `backend/migrations/rls.py` (tenant_id, RLS forzado, políticas, FKs compuestas y permisos). No uses `Base.metadata.create_all`.

## 6. Pruebas (`tests/api/test_<recurso>.py`)

Delega en el subagente `test-writer` o escribe tú mismo, cubriendo como mínimo:

1. Camino feliz con el rol correcto.
2. 401 sin token o con token inválido; 403 con rol incorrecto.
3. **Acceso cruzado (obligatorio, en Postgres)**: usuario del tenant A contra recurso del tenant B → 403/404 sin revelar existencia, y nada cambia en las filas de B.
4. Que un `tenant_id` enviado por el cliente se ignora.
5. Validación de entrada (422) y de archivos si aplica.
6. Registro de auditoría con el `tenant_id` correcto e invisible desde otro tenant.

## 7. Verificación final

1. `ruff check . && ruff format .`
2. `pytest -q` (suite completa, no solo lo nuevo).
3. Invoca el subagente `tenant-isolation-reviewer` sobre el diff y corrige todo hallazgo crítico o medio.
4. Actualiza `CLAUDE.md` o `docs/adr/` solo si el cambio altera la arquitectura.

## 8. Entrega

Resume en pocas líneas: archivos creados o modificados, el CU que resuelve, resultado de pruebas y del revisor de aislamiento, y cualquier decisión pendiente. Commits pequeños en español con prefijo (`feat:`, `test:`, `docs:`), en una rama por caso de uso.
