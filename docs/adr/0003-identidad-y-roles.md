# ADR 0003 — Identidad, roles y conexión de la app

- Estado: aceptado (Semana 1, 2026-10-21)

## Decisión
- **Usuarios en `control.users`**: id `uuid`, `tenant_id`, `role` (`patient`, `doctor`, `tenant_admin`, `platform_admin`) e `is_active`. El email es único global (`lower(email)`), porque el login no pide tenant.
- **`control` sin RLS**:
  - el login busca por email sin conocer el tenant, y el `platform_admin` administra todos los tenants;
  - aquí no hay datos clínicos;
  - lo protegen los permisos de `app_user` (sin `DELETE` ni DDL) y que solo se accede con `get_control_db`.
- **El rol nunca lo declara el usuario.**
  - El registro público solo crea `patient` en el tenant compartido `b2c`.
  - `tenant_admin` y `doctor` los crea el `platform_admin`.
  - El primer `platform_admin` se crea con `backend/scripts/create_platform_admin.py`.
  - `is_medical` se elimina.
- **`platform_admin` es control-only.** Tiene `tenant_id NULL` (`CHECK` en la tabla), `get_tenant_db` lo rechaza, y aunque no lo hiciera su contexto sería nulo y vería 0 filas.
  - Hay dos excepciones acotadas, ambas en servicios de alta:
    - la creación de un tenant escribe el registro `tenant.create` en la auditoría del tenant nuevo;
    - el chequeo de aislamiento cuenta filas en una transacción que siempre hace rollback y devuelve solo conteos.
- **Referencias de `clinical` a `control`:**
  - la única FK es la compuesta `clinical.patients(tenant_id, user_id) → control.users(tenant_id, id)`, que garantiza que la ficha apunta a un usuario del mismo tenant;
  - `uploaded_by` y `actor_id` no llevan FK: son atribución histórica y deben sobrevivir al usuario;
  - `clinical.patients` separa la ficha clínica de la cuenta: en CU-07 una clínica importa a una paciente que no tiene cuenta en ese tenant (`user_id NULL`).
- **JWT**: `sub` (uuid), `tenant_id` (uuid o null), `role` y `exp`. En cada petición se relee el usuario en `control`; si está inactivo, su tenant está inactivo o el rol o tenant ya no coinciden, la respuesta es 401.
- **Conexión de la app**: la URL de `app_user` se deriva de `DATABASE_URL`. Se toma el host, el puerto y la base; el usuario `postgres.<ref>` pasa a `app_user.<ref>` y la contraseña se toma de `APP_DB_PASSWORD`. `APP_DATABASE_URL` es un override opcional (pruebas). En Render, `DATABASE_URL` puede ir **sin la contraseña del dueño**.
- **Migraciones en producción**: manuales desde una computadora de desarrollo, nunca en el build de Render.
