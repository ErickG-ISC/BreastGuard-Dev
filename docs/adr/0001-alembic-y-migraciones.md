# ADR 0001 — Alembic para el esquema y fin de `create_all`

- Estado: aceptado (Fase 0, 2026-10-20)

## Contexto
`/health` creaba las tablas con `Base.metadata.create_all` en cada llamada. No había historial de esquema ni forma de aplicar cambios a varias bases, requisito de la multitenencia (una base física por tenant).

## Decisión
- El esquema se gestiona solo con Alembic: `alembic -c backend/alembic.ini upgrade head` desde la raíz. `/health` queda como chequeo (`SELECT 1`).
- Por ahora hay **una sola línea de migraciones** en `backend/migrations/`. En la Semana 1 se separa en `alembic_control/` y `alembic_tenant/` (ver skill `migracion-multitenant`).
- `env.py` toma la URL de `config.attributes["dburl"]`, luego `-x dburl=...` y luego `DATABASE_URL`, para que el script `migrate_all_tenants` pueda migrar cada base sin variables de entorno fijas.
- Toda migración es **idempotente**: la `0001` revisa con el inspector qué tablas existen, así que las bases creadas con el antiguo `create_all` se actualizan con `upgrade head` sin `stamp` manual.
- Una prueba compara la migración contra los modelos (`compare_metadata`) para detectar modelos sin migración.

## Consecuencias
- Cambiar un modelo exige una revisión nueva; la prueba de `compare_metadata` falla si se olvida.
- Las pruebas de API usan SQLite en memoria con `create_all` solo como atajo de velocidad; las migraciones se prueban aparte.
- Pendiente para la Semana 1: `get_db` no puede convertirse tal cual en `get_tenant_db`, porque login y registro no tienen JWT. Hará falta `get_control_db` (identidad, tenants) separado de `get_tenant_db` (datos de negocio), y quitar `engine`/`SessionLocal` globales de `models/database.py`.
