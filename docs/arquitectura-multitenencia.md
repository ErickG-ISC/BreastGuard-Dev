# Arquitectura de multitenencia de BreastGuard

Este documento describe **lo que hace el código hoy**: rama `main` más la administración de
tenants, migración 0012. Cuando algo está planeado pero no implementado, se indica. Las
decisiones están en `docs/adr/` (0002, 0003, 0004, 0007 y 0008).

## 1. Estrategia

Hay **una sola base Postgres** (Supabase) con dos esquemas:

| Esquema | Contenido | Aislamiento |
|---|---|---|
| `control` | Identidad y operación: `tenants`, `users`, `consents`, `plans`, `subscriptions`, `reminders`, `reminder_notices`, `invitations`, `admin_events` | **Sin RLS.** Cada consulta filtra en el servicio con el `user_id` y el `tenant_id` del JWT. Nunca contiene datos clínicos. |
| `clinical` | Datos de salud: `patients`, `medical_images`, `analyses`, `questionnaires`, `self_exams`, `symptom_entries`, `audit_log` | **RLS habilitado y forzado** en cada tabla, más políticas por rol. |

No hay una base por tenant (ese modelo se reemplazó en el ADR 0002). Toda fila clínica lleva
`tenant_id uuid NOT NULL DEFAULT clinical.current_tenant_id()` y su PK es `(tenant_id, id)`.

## 2. Capas de aislamiento (de afuera hacia adentro)

1. **Autenticación** (`api/deps.py:get_current_user`):
   - El JWT (HS256, 30 min) lleva `sub`, `tenant_id`, `role`, `iat` (ms) y `exp`.
   - En **cada petición** se relee el usuario y su tenant en `control` (`load_auth_context`).
   - Da 401 si el usuario o el tenant están inactivos, si cambió el rol o el tenant, o si el
     token es anterior a `users.sessions_valid_after` o a `tenants.sessions_valid_after`. Ambos se
     fijan al restablecer el acceso y al desactivar, así que reactivar no revive tokens viejos.
   - No hay caché.
2. **Autorización por rol:** `require_role(...)`. Los endpoints clínicos son de `patient`; la
   administración es de `platform_admin` (`/admin/*`) o de `tenant_admin` (`/institution/*`).
3. **Sesión de base según el tipo de dato:**
   - `get_tenant_db`, para todo lo clínico: crea la sesión con `TenantContext`. El listener
     `after_begin` de `db.py` ejecuta en **cada transacción** `set_config('app.tenant_id' |
     'app.user_id' | 'app.role', …, true)`. El `true` limita el valor a esa transacción, lo que
     hace compatible el pooler de Supabase en modo transacción. Rechaza al `platform_admin` (403).
   - `get_control_db`, solo para `control`: sesión **sin contexto**. Sobre `clinical` ve 0 filas
     y no puede insertar.
4. **Filtro explícito en el servicio:**
   - en `clinical`, `_own(auth)` filtra por la ficha de la paciente;
   - en `control`, `_own_reminders`, `_own_notices` y `user_admin._staff_in_scope`.
5. **RLS en `clinical`:**
   - Funciones `clinical.current_tenant_id()`, `current_user_id()` y `current_app_role()`
     (`LANGUAGE sql STABLE`): sin contexto devuelven NULL, así que las políticas fallan cerrado.
   - Política `tenant_isolation` (`USING` + `WITH CHECK`) sobre `tenant_id`.
   - Política RESTRICTIVE de acceso clínico (`migrations/rls.py:add_clinical_access_policy`,
     ADR 0009), igual en `USING` y `WITH CHECK`:
     - la paciente solo ve y crea lo suyo (`patients.user_id`);
     - la doctora, solo lo de sus pacientes (`patients.responsible_doctor_id`; en las tablas
       dependientes, por `EXISTS` sobre `patients`);
     - `tenant_admin` y `platform_admin` no ven nada clínico.
   - `audit_log` tiene su política propia: solo lo lee el `tenant_admin`.
6. **Integridad referencial:**
   - Las FKs entre tablas clínicas son compuestas `(tenant_id, x_id)`, y las FKs no pasan por
     RLS.
   - Las que unen filas de una misma paciente incluyen `patient_id`, así que ni siquiera dentro
     del mismo tenant se enlazan filas de otra paciente:
     - `symptom_entries → self_exams`;
     - `analyses → medical_images`;
     - `analysis_reviews → analyses`.
   - `patients.responsible_doctor_id` es FK compuesta a `control.users`. El CHECK
     `ck_patients_origin` impide fichas con cuenta y médica a la vez.
7. **Permisos por columna:** `app_user` solo puede actualizar las columnas listadas en cada
   migración (`grant_app`).
   - `audit_log` y `admin_events` son de solo inserción.
   - Triggers en `control.users`: el b2c solo admite pacientes (`enforce_b2c_patients`) y el rol
     solo cambia entre `doctor` y `tenant_admin` (`enforce_staff_role_change`).

## 3. Roles de Postgres

| Rol | Uso | Atributos |
|---|---|---|
| Dueño (`postgres` de Supabase, `DATABASE_URL`) | Alembic y scripts de mantenimiento (`purge_tenant.py`), desde una computadora de desarrollo | Superusuario o BYPASSRLS. **La app nunca lo usa.** |
| `app_user` (`APP_DB_USER`) | La app en Render y los scripts que crean datos (`seed_demo.py`, `create_platform_admin.py`) | `LOGIN NOINHERIT`, NOSUPERUSER, NOBYPASSRLS, sin DDL |
| `anon`, `authenticated`, `service_role` (Data API de Supabase) | — | Sin ningún permiso sobre `control` ni `clinical` (`revoke_supabase_api_roles` en cada migración) |

La app no arranca si su rol es superusuario, tiene BYPASSRLS o no es `APP_DB_USER`
(`db.assert_safe_db_role`, en el lifespan). La URL de `app_user` se deriva de `DATABASE_URL`
(host, base y sufijo `.<ref>` del pooler) más `APP_DB_PASSWORD`. En Render, `DATABASE_URL` va sin
la contraseña del dueño.

## 4. Flujo de una petición clínica

Ejemplo: `GET /api/v1/symptoms` de una paciente.

1. CORS y rate limit en memoria, por IP y ruta. La IP sale de `client_ip`, con
   `TRUSTED_PROXY_HOPS=1` en Render.
2. `get_current_user` verifica la firma y la expiración del JWT y relee usuario y tenant en
   `control`.
3. `require_role("patient")`.
4. `get_tenant_db` abre una sesión de `app_user`; al empezar la transacción se aplica
   `set_config(... , true)` con el tenant, el usuario y el rol del JWT.
5. El servicio consulta con `_own(auth)` y RLS agrega `tenant_id = current_tenant_id()` más la
   política de paciente.
6. `audit.record(...)` inserta `symptom.list` en `clinical.audit_log`, en la **misma transacción**.
7. Commit. La respuesta lleva `Cache-Control: no-store`.

Si el recurso es ajeno o no existe, la respuesta es el mismo 404 y se audita `*.denied` en el
tenant de quien preguntó.

## 5. Almacenamiento (Supabase Storage)

- Buckets **privados**: `medical_images` y `ml-models`.
- Rutas `{tenant_slug}/images/{uuid}.{ext}` y `{tenant_slug}/heatmaps/{uuid}.png`. El prefijo lo
  pone el servidor desde el `AuthContext`.
- Antes de firmar o borrar se comprueba que la fila sea visible por RLS **y** que la ruta empiece
  por `{slug}/`.
- URLs firmadas de 300 s (`SIGNED_URL_TTL_SECONDS`); nunca URLs públicas.
- `remove_prefix` exige exactamente `{slug}/` y solo lo usa la purga.
- Se quita el EXIF de las imágenes antes de guardarlas.
- La llave `service_role` de Storage solo vive en el backend.

## 6. Auditoría

| Registro | Dónde | Qué |
|---|---|---|
| Accesos a datos de pacientes (CU-13) | `clinical.audit_log` del tenant, misma transacción que la acción | Quién, rol, acción (`analysis.read`, `symptom.update`, `*.denied`…), recurso, cuándo e IP. Nunca contenido: las notas libres no se registran, y el engine usa `hide_parameters=True` para que un error tampoco las vuelque. Lo lee el `tenant_admin` (`GET /audit`). |
| Cambios administrativos (ADR 0008) | `control.admin_events` | Quién, acción, tenant, objetivo, cuándo e IP; `details` con lista blanca (sin correos ni tokens). Solo inserción. Plataforma: `GET /admin/events`; institución: `GET /institution/events`, siempre con el alcance de su tenant. |

Los logs de la aplicación no llevan datos clínicos ni tokens: los correos aparecen enmascarados y
de los errores solo se registra el tipo.

## 7. Administración de tenants (ADR 0008)

- **Alta** (`POST /admin/tenants`): en una transacción crea el tenant, el primer `tenant_admin`
  **invitado** (sin contraseña), la invitación, los eventos y la fila testigo `tenant.create` en
  `clinical.audit_log`. El correo se envía después del commit.
- **Chequeo de aislamiento** (`POST /admin/tenants/{id}/isolation-check`):
  - corre como `app_user` en una transacción READ ONLY que termina en rollback;
  - comprueba que sin contexto se ven 0 filas, que el tenant no ve filas ajenas y que ningún otro
    tenant ve las suyas;
  - devuelve solo conteos.
- **Desactivación:** la del tenant o la del usuario es efectiva en la siguiente petición (capa 1).
  Desactivar y `reset-access` fijan `sessions_valid_after`, así que un JWT anterior no revive al reactivar.
- **Purga:** la UI la solicita (desactiva y marca); el script `purge_tenant.py --pending` con el
  rol dueño la ejecuta. El tenant b2c no se desactiva ni se purga.
- **Recordatorios (ADR 0007):** el despachador usa la sesión de control sin contexto, así que no
  puede ver `clinical` aunque quisiera.

## 6 bis. Compartir con la médica (CU-07 y CU-08, ADR 0010)

La paciente y la médica están en tenants distintos y **ninguna política cruza tenants**. La
paciente genera una copia cifrada y la médica la importa en su propio tenant:
- **Lo único compartido es `control`:** `share_packages` (HMAC del código y metadatos),
  `share_events` e `inbox_notices`. Nunca hay datos clínicos, y los triggers impiden escribir
  desde sesiones ajenas.
- **El contenido** va cifrado en Storage bajo `transfer/{uuid}/`; la llave solo existe en el
  código.
- **La copia** se escribe con la sesión `TenantDb` de la doctora, bajo RLS de su tenant. El
  reclamo y la confirmación usan una sesión de control sin contexto, que nunca lee `clinical`.
- **Auditoría en ambos lados:** `share.create`/`share.revoke` en el tenant de la paciente y
  `share.import` en el de la médica.

## 6 ter. Panel y caso de la médica (ADR 0012)

- Toda consulta del panel y del caso corre en el `TenantDb` de la doctora y lleva, además de RLS,
  el mismo filtro explícito (sus fichas y las de un traspaso pendiente hacia ella).
- **Ids y búsqueda:** el caso se abre por id; el nombre buscado va en el cuerpo de un POST, nunca
  en la URL.
- **En la base:**
  - el estado del caso solo cambia por transiciones válidas (trigger);
  - un análisis nuevo lo devuelve a pendiente;
  - las notas solo las edita su autora y la paciente no puede leerlas.

## 6 quater. Estudios DICOM de la médica (ADR 0011)

- **Contexto:** se suben con el `TenantDb` de la doctora, solo a fichas de las que es
  responsable; las rutas de Storage salen del JWT (`{slug}/images|heatmaps/`).
- **Desidentificación:** el DICOM original nunca se guarda; en la base solo queda una lista
  blanca técnica. Ningún dato personal del estudio llega a `clinical` ni a Storage.

## 6 quinquies. Reportes PDF y HL7 (CU-10, ADR 0015)

- La médica exporta solo análisis de fichas de las que es **responsable**:
  - mismo `TenantDb` y filtro `_visible` que el caso;
  - con un traspaso pendiente, la de destino ve el caso pero recibe 409;
  - sin una revisión con BI-RADS, 409.
- La paciente exporta solo su propio análisis (`analyses._own`).
- El mapa de calor se descarga solo si su ruta tiene el prefijo `{tenant_slug}/`, y la conexión se suelta antes de ir a Storage.
- Cada exportación queda en `clinical.audit_log` del tenant (`case.export_pdf`, `case.export_hl7`, `analysis.export_pdf`; los rechazos como `case.denied` o `case.export_denied`), sin contenido. El id de ese registro **es** el `report_id` del documento.
- El nombre del archivo no lleva datos personales y la respuesta es `no-store`.

## 7 bis. Traspaso de pacientes entre médicas (ADR 0009, migración 0014)

Las fichas de institución solo las ve su médica responsable. Si ella se va, la administración no
puede moverlas porque no tiene acceso clínico. El traspaso va en dos pasos:

1. **La administración lo crea en `control`.** `tenant_admin` o `platform_admin`, con su alcance,
   inserta en `control.patient_handovers` un traspaso pendiente de X a Y. Lleva solo ids y fechas.
2. **Visibilidad previa a la aceptación.** Mientras el traspaso está pendiente, la regla de acceso
   (`clinical_access_rule(..., handover=True)`) deja a Y ver y agregar datos a las fichas de X:
   - la subconsulta a `control.patient_handovers` se filtra por tenant y destino del contexto;
   - solo cuentan los traspasos pendientes (ni aceptados ni cancelados);
   - es la **única excepción** a "la doctora solo ve a sus pacientes", y nunca cruza tenants.
3. **Y lo acepta con su propio contexto** (`POST /doctor/handovers/{id}/accept`, TenantDb): un
   UPDATE de `responsible_doctor_id` a su nombre, con `audit_log` y `admin_events` en la misma
   transacción. Mientras no lo acepte, no puede cambiar el estado de esas fichas.

Defensas en la base (control no tiene RLS y `app_user` también es el rol de las sesiones clínicas):
- **Trigger `control.enforce_handover_writes`:** una sesión con contexto de paciente o doctora no
  crea traspasos. Solo la doctora de destino marca como aceptado uno pendiente hacia ella.
- **Fichas a nombre propio:** el WITH CHECK del UPDATE de `patients` y la política
  `patients_insert_own_doctor` solo dejan fichas a nombre de la doctora del contexto.
- **Coherencia:**
  - un pendiente por médica de origen, y sin cadenas;
  - destino: una doctora activa del mismo tenant;
  - al desactivar a la destinataria o quitarle el rol, sus pendientes se cancelan;
  - cancelar quita la visibilidad de inmediato.
- **Riesgo residual:** una administradora con una segunda cuenta de doctora (otro correo) podría
  traspasarse pacientes. Queda en la bitácora `handover.create` y en la auditoría clínica de la
  aceptación.

## 8. Pruebas

Corren contra **Postgres 17 real**: Docker en local y un servicio en CI. `tests/pgtest.py` crea
una base temporal, aplica las migraciones y usa el rol `bg_app_test` (NOBYPASSRLS).

- **Catálogo** (`tests/isolation/test_catalog.py`, `catalogo.py`):
  - toda tabla de `clinical` con RLS habilitado y forzado y con política exacta;
  - sin vistas sin `security_invoker` ni funciones `SECURITY DEFINER`;
  - grants por columna;
  - roles de la Data API sin acceso.
- **RLS tabla por tabla** (`test_rls_por_tabla.py`):
  - cada tabla necesita una receta para poblarla;
  - sin contexto se ven 0 filas;
  - UPDATE y DELETE cruzados afectan 0 filas, con control positivo;
  - `WITH CHECK` rechaza el tenant ajeno;
  - cada FK compuesta rechaza referencias cruzadas, como la app y también sin RLS (como dueño).
- **Acceso por rol** (`test_acceso_clinico_por_rol.py`):
  - doctora contra doctora, del mismo tenant y de otro;
  - `tenant_admin` y `platform_admin` sin acceso clínico;
  - FKs de la misma paciente;
  - CHECK de `patients`.
- **Matriz de endpoints** (`tests/api/test_acceso_cruzado_endpoints.py`):
  - todo endpoint no público da 401 sin token, con token inválido o expirado y con un esquema
    distinto de Bearer, y 403 por rol;
  - `test_revision_aislamiento.py` falla si aparece una ruta sin declarar.
- **Acceso cruzado con datos reales** por caso de uso (`test_semana2_cruzado.py`,
  `test_semana3_cruzado.py`, `test_admin_users.py`, …): paciente contra otra paciente del mismo
  tenant y contra otro tenant, 404 uniforme, dueño intacto y auditoría en el tenant correcto.
- **Migraciones:** upgrade → downgrade → upgrade, idempotencia, comparación con los modelos y
  downgrades que se niegan a borrar datos.

## 9. Limitaciones conocidas

- **Compartir con la médica (CU-07/CU-08):** implementado (sección 6 bis, ADR 0010). Es el
  único flujo entre tenants y no usa excepciones de política: el paquete cifrado se importa como
  copia en el tenant de la médica.
- **`control` no tiene RLS:** su aislamiento depende del filtro del servicio, cubierto por pruebas
  cruzadas. Una regresión en ese filtro no la detendría la base.
- **Rate limit en memoria:** vale para una sola instancia.
- **Objetos huérfanos en Storage** si falla el commit después de subirlos.
- **Purga no inmediata:** la UI solo la solicita; hasta correr el script, los datos siguen en la
  base, con el tenant desactivado.
- **Correo:** Resend sin dominio verificado solo entrega al correo dueño de la cuenta.
- **Exposición de esquemas en la Data API:** los permisos se revocan en cada migración, pero que
  `control` y `clinical` no estén *expuestos* en Supabase (Settings → API) se configura a mano y
  ninguna prueba automática lo verifica.
- **Esquema `legacy`:** conserva el prototipo original; queda pendiente borrarlo.
- **Auditoría administrativa anterior a 0012:** quedó en `clinical.audit_log`, sin migrar.
- **`app_user` lee `public.alembic_version`** (0019), solo para que `/health` compare la revisión
  de la base con la del código. Los roles de la Data API siguen sin acceso.
- Lista general (modelo, infraestructura y riesgos aceptados): `docs/limitaciones-conocidas.md`.
