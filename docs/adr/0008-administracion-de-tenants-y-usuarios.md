# ADR 0008: Administración de tenants y usuarios

- Estado: aceptado
- Fecha: 2026-10-26
- Casos de uso: CU-12 (alta y gestión de tenants) y CU-13 (auditoría y control de acceso)

## Contexto

Hacía falta crear y **administrar** instituciones y su personal: listar, editar, desactivar,
invitar y restablecer el acceso, y purgar. Restricciones:
- el `platform_admin` no puede ver datos clínicos;
- el `tenant_admin` solo gestiona su propio tenant;
- nadie envía ni ve contraseñas.

## Decisiones

1. **Todo en `control`.**
   - Tablas nuevas `control.invitations` y `control.admin_events`, más columnas en `users` y
     `tenants` (migración 0012).
   - Las estadísticas por tenant son de control: personal, invitaciones pendientes, número de
     pacientes y último acceso. No se cuentan análisis ni datos del diario.
2. **Un solo servicio con alcance** (`services/user_admin.py`):
   - `Scope.for_actor` da "cualquier tenant" al `platform_admin` y "el tenant del JWT" al
     `tenant_admin`.
   - Solo se gestiona personal (`doctor`, `tenant_admin`). Pacientes y `platform_admin` nunca
     aparecen.
   - Un usuario fuera de alcance da el mismo 404 que uno inexistente.
   - Los `platform_admin` adicionales solo se crean con `create_platform_admin.py`, así que la API
     no puede desactivar al último.
3. **Cambio de rol limitado por la base.**
   - `app_user` recibe `UPDATE (role)` en `control.users`.
   - El trigger `enforce_staff_role_change` solo permite pasar entre `doctor` y `tenant_admin`.
   - Además se mantienen el CHECK `platform_admin ⇔ tenant_id NULL` y el trigger del b2c.
   - La API impide cambiarse el rol o desactivarse a uno mismo, y dejar un tenant sin
     `tenant_admin` activo.
4. **Invitaciones de un solo uso.**
   - Token `secrets.token_urlsafe(32)`; en la base solo se guarda su sha256.
   - Vence a las 48 h (`invite`) o a las 2 h (`reset`).
   - Una invitación nueva revoca las anteriores.
   - Se acepta con un `UPDATE … WHERE used_at IS NULL AND revoked_at IS NULL AND expires_at >
     now() RETURNING`, que resiste peticiones simultáneas.
   - El enlace usa el fragmento `#token=`: no llega al servidor ni al Referer, y la página lo quita
     de la barra.
   - Restablecer el acceso anula la contraseña y cierra las sesiones.
5. **Pérdida de acceso inmediata.**
   - `get_current_user` relee usuario y tenant en `control` **en cada petición, sin caché**.
   - Da 401 si el usuario o el tenant están inactivos, si cambió el rol o el tenant, o si el JWT
     es anterior a `users.sessions_valid_after`. El `iat` va en milisegundos, redondeado hacia
     abajo, así que un restablecimiento invalida también los tokens del mismo segundo.
   - Desactivar fija `sessions_valid_after` del usuario (o `tenants.sessions_valid_after` del
     tenant): al reactivar, los JWT de antes no reviven.
   - El login solo entrega token si la contraseña verificada sigue vigente al guardar el último
     acceso, así que no gana una carrera contra un restablecimiento.
   - Se descartó una caché: abre una ventana en la que un usuario desactivado sigue entrando, y
     con una instancia y una consulta por PK el costo es mínimo.
6. **Bitácora de plataforma** (`control.admin_events`).
   - Registra quién, acción, tenant, objetivo, cuándo e IP.
   - `details` pasa por una lista blanca de claves: nunca correos, tokens ni contraseñas.
   - Es de solo inserción para `app_user` y no tiene FK al tenant, así que sobrevive a la purga.
   - El `tenant_admin` solo ve su tenant; el alcance lo pone el servidor. De las acciones de la
     plataforma ve qué se hizo, pero no el id ni la IP de quien lo hizo.
   - En `clinical.audit_log` solo queda `tenant.create`, la fila testigo del chequeo de
     aislamiento.
7. **Purga en dos pasos.**
   - La UI la **solicita**: confirma escribiendo el slug, desactiva el tenant y lo marca.
   - La ejecuta `purge_tenant.py --pending` con el rol dueño: borra filas y el prefijo de
     Storage, y escribe `tenant.purge`.
   - Motivo: la app corre como `app_user`, sin DELETE en auditoría ni en cuentas, y nunca usa el
     rol dueño.
   - El tenant b2c no se desactiva ni se purga.
8. **Correo.** Adaptador `EMAIL_BACKEND=resend` con `urllib`, sin dependencias nuevas. Un fallo de
   envío no deshace la invitación y se puede reenviar.

## Consecuencias

- `POST /admin/tenants` ya no acepta contraseña: el primer administrador se invita.
- Sin dominio verificado, Resend solo entrega al correo dueño de la cuenta. Para la demo,
  `seed_demo.py` imprime los enlaces en la terminal del operador.
- Una purga solicitada deja los datos en la base hasta que se corre el script, pero nadie del
  tenant puede entrar.
- Los eventos administrativos de semanas anteriores quedan en `clinical.audit_log`; los nuevos
  van a `control.admin_events`.
