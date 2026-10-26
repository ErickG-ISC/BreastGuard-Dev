# CLAUDE.md

Guía para Claude Code (claude.ai/code) al trabajar en este repositorio.

## Resumen del proyecto

BreastGuard es una plataforma SaaS multitenant de **apoyo al diagnóstico** para la detección temprana de cáncer de mama a partir de imágenes médicas (ecografías BUSI y, en el plan médico, mastografías DICOM). Es un **proyecto escolar** con fecha límite a ~6 semanas: se prioriza un prototipo funcional y demostrable sobre la perfección. Nunca se presenta como diagnóstico; siempre es una herramienta de apoyo y el médico decide.

Dos modos de producto en una sola app:
- **B2C (pacientes)**: registro, subida de ecografía, predicción + heatmap + reporte en lenguaje sencillo, autoexploración guiada, diario de síntomas, recordatorios, blog, compartir paquete con su médico.
- **B2B (médicos / instituciones)**: panel profesional, historial de pacientes, carga DICOM, reporte técnico BI-RADS, exportación PDF (HL7 solo documentado/simulado), gestión de varios pacientes.
- **Administración de plataforma**: alta de tenants, auditoría y control de acceso.

Los casos de uso completos son CU-01 a CU-13 (ver `docs/casos-de-uso.md`).

Prioridad de implementación acordada: **1) multitenencia (CU-12, CU-13), 2) B2C (CU-01 a CU-07), 3) B2B (CU-08 a CU-11)**.

## Estructura del repositorio

- `backend/` — app FastAPI (`backend/app`)
- `frontend/` — SPA React 19 + Vite
- `backend/migrations/` + `backend/alembic.ini` — migraciones de Alembic (una sola línea hasta la Semana 1)
- `tests/` — pytest contra **Postgres real** (`pgtest.py`: base temporal y variables de prueba; `conftest.py`: fixtures; `helpers.py`: fábricas; `isolation/`: pruebas de RLS y catálogo)
- `docker-compose.yml` — Postgres 17 local para pruebas (puerto 54329)
- `infraestructure/` — reservado para despliegue/IaC; todavía no existe en el repo (git no guarda carpetas vacías). El nombre lleva ese typo a propósito; no renombrar sin avisar
- `docs/` — casos de uso (`casos-de-uso.md`) y decisiones de arquitectura (`adr/`). El guion de demo está pendiente
- `.github/workflows/ci.yml` — CI en cada push y PR: job `backend` (ruff y pytest contra un servicio Postgres 17, Python 3.12, sin TensorFlow) y job `frontend` (`npm ci`, oxlint, build y `npm run check:sw`)

El repo se inicializó con git localmente en la Fase 0 (venía de un ZIP); el remoto se conecta a mano.

## Comandos

### Backend (ejecutar desde la RAÍZ del repo, no desde `backend/`)

La app no tiene `__init__.py` y usa namespace packages con imports absolutos tipo `backend.app.models...`, por lo que debe lanzarse desde la raíz:

```
py -3.12 -m venv venv          # Windows: el "python" por defecto puede ser 3.15
venv\Scripts\activate          # Windows
pip install -r requirements-dev.txt   # producción + pytest, httpx2, ruff
cp .env.example .env           # llenar valores, ver "Configuración"
alembic -c backend/alembic.ini upgrade head   # crea/actualiza el esquema
uvicorn backend.app.main:app --reload
```

`requirements.txt` (producción, lo usa Render) y `requirements-dev.txt` están en la raíz, no en `backend/`. Las versiones están fijadas; `bcrypt` queda en 4.0.1 porque `passlib` 1.7.4 falla con versiones posteriores.

Pruebas y calidad:

```
docker compose up -d db        # Postgres local de pruebas (una vez)
pytest -q                      # pruebas contra ese Postgres (TEST_DATABASE_URL); sin él se omiten
ruff check . && ruff format .  # lint y formato (configuración en pyproject.toml)
alembic -c backend/alembic.ini upgrade head   # migra la base de DATABASE_URL (o -x dburl=...)
```

Las migraciones en producción se corren **a mano desde una computadora de desarrollo**, nunca en el build de Render.

### Frontend (`cd frontend` primero)

```
npm install
npm run dev        # servidor Vite
npm run build      # build de producción
npm run lint       # oxlint (no ESLint)
npm run preview
```

## Configuración

Todos los secretos vienen de variables de entorno. Ver `.env.example` (raíz) y `frontend/.env.example`. `main.py` llama `load_dotenv()` antes de importar el resto.

Variables existentes: `RESEND_API_KEY`, `EMAIL_FROM` (invitaciones y recordatorios con `EMAIL_BACKEND=resend`), `REMINDER_CRON_SECRET`, `EMAIL_BACKEND`, `EMAIL_FROM_NAME`, `PUBLIC_APP_URL` (CU-05), `DATABASE_URL`, `SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_BUCKET`, `FRONTEND_ORIGIN`, `MODEL_BUCKET`, `MODEL_PREFIX`, `MODEL_DIR`, `MAX_CONCURRENT_INFERENCES`, `MAX_UPLOAD_MB` (opcional, 10 por defecto), y `VITE_API_URL` en el frontend.

Variables de la multitenencia (ADR 0003):
- `DATABASE_URL` — rol **dueño/migrador**; solo lo usan Alembic y los scripts de mantenimiento. La app toma de aquí solo host, puerto, base y sufijo del usuario (`postgres.<ref>` → `app_user.<ref>`), así que en Render puede ir sin la contraseña del dueño.
- `APP_DB_PASSWORD` — contraseña de `app_user`; la migración crea el rol con ella y la app se conecta con ella.
- `APP_DB_USER` — opcional, nombre del rol de la app (`app_user` por defecto).
- `APP_DATABASE_URL` — opcional, URL completa de `app_user` que sustituye a la derivada (la usan las pruebas).

Reglas de infraestructura:
- `.python-version` fija Python 3.12 (TensorFlow y SQLAlchemy van detrás de las últimas versiones de CPython). No subirlo a 3.13/3.14.
- Para Supabase usar siempre el **pooler** (Session pooler para migraciones; la app también funciona en modo transacción porque el contexto es por transacción), no "Direct connection" (solo resuelve por IPv6 y falla en Render con `Network is unreachable`).
- Render en plan gratuito se duerme y tiene ~512 MB de RAM: ver sección del modelo de IA.
- Nunca commitear `.env`, llaves ni datos médicos reales.

## Arquitectura actual (estado "esqueleto")

### Backend (`backend/app`)

- `main.py`: carga `.env`, crea `FastAPI()`, agrega `CORSMiddleware` (orígenes de `FRONTEND_ORIGIN`, separados por comas o espacios/saltos de línea; ver `cors.py`) y monta tres routers bajo `/api/v1`: `health`, `auth` (`/auth`) e `images` (`/images`).
- `db.py`: conexión de la app. Hay un solo engine, con el rol `app_user` (URL derivada de `DATABASE_URL` + `APP_DB_PASSWORD`, o `APP_DATABASE_URL`) y pool pequeño. `new_session(context)` crea sesiones; el listener `after_begin` aplica `set_config('app.tenant_id' | 'app.user_id' | 'app.role', ..., true)` en cada transacción. `assert_safe_db_role()` corre en el lifespan: la app no arranca con un rol superusuario, BYPASSRLS o distinto de `APP_DB_USER`.
- `models/base.py`: `Base` declarativa. `models/control.py` (`Tenant`, `User`) y `models/clinical.py` (`Patient`, `MedicalImage`, `AuditLog`). En `clinical`, `tenant_id` lo pone la base desde el contexto; el código no lo asigna.
- `api/deps.py`:
  - `get_control_db` / `ControlDb`: sesión sin contexto, solo para `control`.
  - `get_current_user` / `CurrentUser`: devuelve `AuthContext` (JWT verificado y releído en `control`).
  - `get_tenant_db` / `TenantDb`: sesión con contexto RLS; rechaza a `platform_admin`.
  - `require_role(...)`.
  - `get_storage` / `Storage`: punto de override en pruebas.
- `api/v1/*`: routers delgados; la lógica vive en `services/` y los esquemas Pydantic en `schemas/`.
- `/auth/register` (JSON, `extra="forbid"`): crea siempre un `patient` en el tenant `b2c` y exige el consentimiento vigente (`consent_accepted: true`, `consent_version`) y un `plan_code` simulado. En una transacción crea la cuenta (`control.users`), el consentimiento (`control.consents`), la suscripción simulada (`control.subscriptions`) y la ficha (`clinical.patients`). Ver ADR 0005.
- `api/v1/onboarding.py` (CU-01):
  - públicos: `GET /consent/current` y `GET /plans`;
  - solo pacientes: `GET/PUT /subscription/me`, `GET /questionnaire/current`, `POST /questionnaires` y `GET /questionnaires/latest`.
  - Los textos y reglas están en `backend/app/content/`: el consentimiento en markdown, el cuestionario v1 y `risk_rules.py`, que da factores a comentar y nunca una probabilidad. `/auth/token` responde 401 genérico, o 403 si la cuenta o el tenant están inactivos. El JWT lleva `sub`, `tenant_id`, `role` y `exp`.
- `/health` solo hace `SELECT 1` con `get_control_db` (503 genérico si falla). El esquema lo crea **Alembic** (`backend/migrations/`, helpers RLS en `backend/migrations/rls.py`); nunca `create_all`.
- `services/auth.py`: hash bcrypt, JWT, `register_patient`, `authenticate_user` y `load_auth_context`.
- `services/images.py`: valida la subida (extensión y MIME JPG/PNG, tamaño `MAX_UPLOAD_MB`, que abra con Pillow) y sube a `{tenant_slug}/images/{uuid}.{ext}` con un temporal uuid que se borra en `finally`. La fila guarda `object_path`, no una URL. DICOM se rechaza hasta CU-09.
- `services/storage.py`: bucket **privado** de Supabase Storage (cliente creado al primer uso): `upload_file`, `create_signed_url` (TTL `SIGNED_URL_TTL_SECONDS`, 300 s por defecto) y `remove_prefix` (purga). Nunca URLs públicas. Los fallos se registran solo por tipo (`StorageError`, 502). No se usa AWS/S3.
- `services/audit.py`: `record(...)` inserta en `clinical.audit_log` con Core y sin RETURNING, en la misma transacción que la acción. `list_entries(...)` sirve a `GET /audit`.
- Administración (ADR 0008; resumen en `docs/arquitectura-multitenencia.md`):
  - `services/tenants.py` + `api/v1/admin.py` (solo `platform_admin`, solo `control`):
    - tenants con filtros, paginación y estadísticas de control (personal, invitaciones, conteo de pacientes, último acceso);
    - alta atómica con el primer `tenant_admin` **invitado** (sin contraseña);
    - editar nombre y plan (`basic|pro|enterprise`; el tipo es fijo);
    - desactivar y reactivar;
    - solicitar y cancelar la purga (`confirm_slug`). La purga la ejecuta `purge_tenant.py --pending` con el rol dueño;
    - `isolation-check` (READ ONLY, solo conteos).
  - `services/user_admin.py`: personal (`doctor`/`tenant_admin`) con alcance (`Scope.for_actor`).
    - El `platform_admin` gestiona cualquier tenant (`/admin/tenants/{id}/users`, `/admin/users/{id}`); el `tenant_admin`, solo el de su JWT (`api/v1/institution.py`, `/institution/*`).
    - Operaciones: invitar, cambiar rol, activar o desactivar, reenviar invitación y restablecer acceso.
    - Fuera de alcance da 404. Pacientes y `platform_admin` nunca aparecen.
    - Nadie puede cambiarse el rol, desactivarse ni dejar el tenant sin admin.
  - `services/invitations.py`: tokens de un solo uso (solo el sha256 en `control.invitations`; 48 h invitar, 2 h restablecer). Enlace `PUBLIC_APP_URL/invitacion#token=`. Públicos: `POST /auth/invitations/inspect` y `/accept`.
  - Sesiones: el JWT lleva `iat` en ms; `load_auth_context` rechaza tokens anteriores a `users.sessions_valid_after` (restablecer acceso). `/auth/token` actualiza `last_login_at`.
  - `services/admin_events.py`: bitácora de plataforma `control.admin_events`, solo inserción, `details` con lista blanca. `GET /admin/events` (todo) y `GET /institution/events` (su tenant).
  - Trigger `enforce_staff_role_change`: el rol solo cambia entre `doctor` y `tenant_admin`.
- `api/v1/analyses.py` + `services/analyses.py` (CU-02, solo pacientes):
  - `POST /analyses` (multipart, 10/min) valida y analiza. Guarda la imagen limpia en `{slug}/images/` y el heatmap en `{slug}/heatmaps/`, luego `medical_images` + `analyses`, y audita. Devuelve el reporte y las URLs firmadas.
  - `GET /analyses` (paginado) y `GET /analyses/{id}` dan el reporte con las URLs firmadas de la imagen y del heatmap.
  - `DELETE /analyses/{id}` borra primero los objetos de Storage y después las filas, con auditoría. Si Storage falla responde 502 y no borra nada.
  - Si el análisis es ajeno o no existe, la respuesta es la misma (404) y se registra `analysis.denied`.
  - Tabla `clinical.analyses` (0008): RLS forzado, política de paciente y FKs compuestas a `patients` y `medical_images`; solo SELECT, INSERT y DELETE.
- `api/v1/self_exams.py` + `services/self_exams.py` (CU-03, solo pacientes salvo la guía):
  - `GET /self-exam/guide` (público): guía versionada en `content/self_exam_v1.json` (BORRADOR, 6 pasos, sin temporizador).
  - `POST /self-exams` (iniciar), `POST /self-exams/{id}/finish` (`noticed_change`: `si|no|no_segura` y nota opcional; terminar dos veces da 409), `GET /self-exams` (paginado), `GET /self-exams/latest` (última terminada), `GET` y `DELETE /self-exams/{id}`.
  - Tabla `clinical.self_exams` (0009): RLS forzado, política de paciente, `UNIQUE (tenant_id, patient_id, id)` como destino de la FK del diario. La nota es sensible: nunca en logs ni en la auditoría (`self_exam.start|finish|read|list|delete|denied`).
- `api/v1/symptoms.py` + `services/symptoms.py` (CU-04, solo pacientes): `POST /symptoms`, `GET /symptoms` (filtros `from`, `to`, `symptom`, `zone`, `side`; paginado), `GET`, `PATCH` (parcial) y `DELETE /symptoms/{id}` (borrado real).
  - Tabla `clinical.symptom_entries` (0010): códigos fijos de lado, zona y síntomas (CHECK), intensidad 0–10, nota (máx. 2000), ciclo opcional. FK `(tenant_id, patient_id, self_exam_id) → self_exams` con `ON DELETE SET NULL (self_exam_id)`: la base impide enlazar la autoexploración de otra paciente aunque sea del mismo tenant (las FKs no pasan por RLS). `tenant_fk` acepta `ondelete`.
  - `get_entries(db, auth, since)` es la función reutilizable para el paquete de CU-07; no audita (audita quien la llama).
  - Auditoría `symptom.create|read|list|update|delete|denied`, sin contenido de la nota. El engine usa `hide_parameters=True` para que ningún error vuelque notas en logs.
- `api/v1/reminders.py` + `services/reminders.py` (CU-05, ADR 0007): `GET /reminders`, `PUT` y `DELETE /reminders/{self_exam|repeat_analysis}`, `GET /notices?unread=`, `POST /notices/{id}/read` (solo pacientes) y `POST /reminders/unsubscribe` (público, token firmado de audiencia propia).
  - Tablas `control.reminders` y `control.reminder_notices` (0011), **en control, sin RLS**: solo configuración. Toda consulta pasa por `_own_reminders` / `_own_notices` (user_id + tenant_id del JWT).
  - `services/reminder_schedule.py`: `next_run` puro (primer domingo, cada N días, cada N meses; zonas IANA con `tzdata`; huecos de horario hacia adelante, horas ambiguas a la primera).
  - Despachador `POST /internal/reminders/dispatch` (header `X-Cron-Secret` = `REMINDER_CRON_SECRET`, 32+ caracteres; sin él responde 503): `FOR UPDATE SKIP LOCKED` + `UNIQUE (reminder_id, due_at)`, un aviso aunque haya atrasos, correo fuera de la transacción. Usa la sesión de control sin contexto: nunca ve `clinical`. Lo llama `.github/workflows/reminders.yml` cada 15 min (secret `REMINDER_CRON_SECRET` y variable `API_URL` en GitHub). Local: `python -m backend.scripts.dispatch_reminders`.
  - `services/email.py`: `EMAIL_BACKEND=console` (solo registra el destinatario enmascarado) o `resend` (`RESEND_API_KEY`, `EMAIL_FROM`; con `urllib`, sin SDK). Modo discreto por defecto: sin marca ni tema. Siempre lleva enlace de baja (`PUBLIC_APP_URL/baja?token=`).
- `api/v1/blog.py` + `services/blog.py` (CU-06, público, sin tenant): `GET /blog`, `GET /blog/faq` y `GET /blog/{slug}`. Artículos en `content/blog/*.md` con metadatos entre `---` (parser propio, sin PyYAML; se validan al arrancar). Sin `revisado_por` la UI muestra "Contenido educativo general · borrador", nunca "validado". "Recomendado para ti" lo arma el frontend con `GET /analyses?limit=1`. Lo pendiente de revisión médica está en `docs/contenido-pendiente-de-revision.md`.
- `api/v1/images.py`: `POST /upload` (paciente), `GET /images` y `GET /images/{id}` (con URL firmada; ajena o inexistente da el mismo 404). Lecturas, subidas y accesos denegados (`image.denied`) auditados.
- `api/v1/audit.py`: `GET /audit` para `tenant_admin` con filtros `from`, `to`, `actor_id`, `limit` y `offset`.
- `api/rate_limit.py`: límites por IP y ruta: `/auth/token` 10/min, `/auth/register` 5/min, `/images/upload` 20/min. La IP sale de `api/client_ip.py`: ignora `X-Forwarded-For` salvo con `TRUSTED_PROXY_HOPS` (en Render, `1`; ver ADR 0004).
- `backend/scripts/`:
  - `create_platform_admin.py`: como `app_user`, pide la contraseña;
  - `purge_tenant.py`: rol dueño con BYPASSRLS, confirma escribiendo el slug, tiene `--dry-run` y `--pending` (las purgas solicitadas en la UI); conserva `control.admin_events`;
  - `seed_demo.py`: `--create` crea un tenant `demo-…` con personal invitado y datos clínicos sintéticos (como `app_user`); `--clean` lo purga y solo acepta slugs `demo-`;
  - `check_storage.py`: verifica que el bucket sea privado.

### Frontend (`frontend/src`)

SPA estándar: `main.jsx` monta `App.jsx` (tema, `AuthProvider` y rutas con `react-router-dom`). UI con MUI (`@mui/material`, `@emotion/*`) y `axios`. Lint con `oxlint`.
- `theme.js`: **tema único** (paleta clara/oscura, tipografía del sistema, radios, botones, campos, tarjetas). Las páginas no definen colores ni radios propios; el fondo de visores de imagen es `imaging.main`.
- `components/icons.jsx`: íconos de Material como `SvgIcon` (sin `@mui/icons-material`).
- `components/PatientShell.jsx` + `patientNav.js`: app de paciente con barra inferior en móvil (Inicio, Analizar, Historial, Diario, Más) y barra lateral en escritorio (≥ md), según `docs/wireframes/`. Las rutas de paciente son hijas del shell (`<Outlet/>`); `Layout.jsx` queda para páginas públicas y de administración.
- PWA con `vite-plugin-pwa`: solo precache de estáticos; `scripts/check-sw.mjs` (`npm run check:sw`) falla si el SW cachea algo más.
- `api/client.js`: axios con el Bearer del JWT, guardado en `sessionStorage`; un 401 cierra la sesión.
- `auth/AuthContext.jsx`: login (`/auth/token`) y el usuario actual (`/auth/me`).
- `components/ProtectedRoute.jsx` (por rol) y `components/Layout.jsx`, con el aviso de herramienta de apoyo.
- Rutas públicas: `/`, `/login`, `/registro`. Paciente: `/paciente`, `/cuestionario`, `/analizar`, `/resultado/:id`, `/historial`, `/diario`, `/mas`, `/autoexploracion`, `/recordatorios`, `/informacion`, `/informacion/:slug`. Públicas: `/baja` (confirmar baja del correo) e `/invitacion` (fijar contraseña con el enlace).
- `components/AdminShell.jsx` (barra lateral D04, cajón en móvil) y `components/admin/` (`StaffManager`, `EventsLog`, `IsolationDialog`), compartidos por:
  - `platform_admin`: `/admin/tenants`, `/admin/tenants/:id` (datos, usuarios, bitácora, chequeo, desactivar y solicitar purga) y `/admin/auditoria`;
  - `tenant_admin`: `/institucion/usuarios` y `/institucion/bitacora`.

### Brechas conocidas (resolver en este orden)

Resueltas en la Fase 0: usuario de `/images/upload` tomado del JWT (antes `user_id=1`), temporales con uuid y limpieza en `finally`, validación de subidas, `get_db` unificado, Alembic, pytest, ruff y CI.

Resueltas en la Semana 1 (rama `semana1-modelo`): roles asignados (sin `is_medical`), prefijo `{tenant_slug}/` en Storage y `object_path` en lugar de URL.

También en la Semana 1: bucket privado con URLs firmadas, límite de peticiones, auditoría de accesos (CU-13) y alta de tenants con chequeo de aislamiento (CU-12).

Pendientes:
1. El modelo no está conectado al flujo de subida y es binario (benigno/maligno); CU-02 pide también "normal" (BUSI tiene las tres clases).
2. Si falla el commit después de subir a Storage, queda un objeto huérfano.
3. El límite de peticiones es en memoria (una sola instancia); con varias instancias haría falta un almacén compartido.
4. `legacy.users` conserva emails y hashes del prototipo; borrar el esquema `legacy` cuando ya no haga falta.
5. La política de paciente deja a `doctor` y `tenant_admin` hacer UPDATE/DELETE en las tablas de la paciente (self_exams, symptom_entries) a nivel de base; hoy solo la app lo impide (endpoints solo de paciente). Decidir en la Semana 4 si se restringe por comando.
6. Correo: Resend sin dominio verificado solo entrega al correo dueño de la cuenta.
7. La purga desde la UI solo se solicita; la ejecuta una persona con `purge_tenant.py --pending`.

## Arquitectura objetivo: multitenencia con RLS (REGLAS INNEGOCIABLES)

Modelo: **una sola base Postgres (Supabase) con Row Level Security forzado** (ADR 0002, que reemplaza el modelo de una base por tenant). Identidad y roles en el ADR 0003.

- **Esquema `control`**: `tenants` (id uuid, slug, nombre, tipo `b2c|institucion`, plan, activo) y `users` (id uuid, `tenant_id`, `role`, activo). Sin RLS; solo identidad y administración, nunca datos clínicos.
- **Esquema `clinical`**: todo dato clínico (`patients`, `medical_images`, `audit_log` y futuras tablas). Cada tabla lleva `tenant_id uuid NOT NULL DEFAULT clinical.current_tenant_id()`, PK `(tenant_id, id)`, RLS **habilitado y forzado** y la política `tenant_isolation` (`USING` + `WITH CHECK` sobre `tenant_id = (SELECT clinical.current_tenant_id())`). Sin contexto se ven 0 filas y los `INSERT` fallan.
- **Roles de base**: el dueño/migrador (`DATABASE_URL`) solo para Alembic y scripts; la app corre **siempre** como `app_user` (`NOSUPERUSER NOBYPASSRLS`, sin DDL; en `audit_log` solo `SELECT, INSERT`). La app no arranca si su rol es superusuario o BYPASSRLS (el `postgres` de Supabase lo es).
- **Roles de aplicación**: `patient`, `doctor`, `tenant_admin`, `platform_admin`. El JWT incluye `sub`, `tenant_id` y `role`. El registro público solo crea `patient` en el tenant `b2c`. El `platform_admin` es **control-only**: no tiene tenant ni acceso a datos clínicos.
- **Resolución de tenant**: un solo engine de `app_user` con pool pequeño. `get_tenant_db` aplica en **cada transacción** `set_config('app.tenant_id' | 'app.user_id' | 'app.role', <del JWT>, true)`; nunca `SET` de sesión (compatible con el pooler en modo transacción). `get_control_db` no lleva contexto y solo sirve para el esquema `control` (login, registro, `/health`, administración).

Reglas que nunca se rompen:
1. **Ninguna sesión sin contexto toca datos clínicos.** Todo endpoint clínico usa `get_tenant_db`; la app nunca usa el rol dueño ni crea engines propios.
2. **El `tenant_id`, el `user_id` y el `role` salen solo del JWT verificado** (y releído en `control`), jamás de un parámetro, header o body enviado por el cliente.
3. Toda tabla de `clinical` se crea con los helpers de `backend/migrations/rls.py` (`create_tenant_table`, `enable_tenant_rls`, `tenant_fk`, `grant_app`). Las referencias entre tablas clínicas son **FKs compuestas** `(tenant_id, x_id)`. La prueba de catálogo falla si una tabla queda sin RLS forzado o sin política, o si aparece una vista sin `security_invoker` o una función `SECURITY DEFINER`.
4. Archivos en Storage con prefijo `{tenant_slug}/...` en bucket **privado**; se valida pertenencia (fila visible por RLS y prefijo correcto) antes de firmar una URL de corta duración. Nunca URLs públicas.
5. Cada acceso a datos de pacientes escribe un registro en `clinical.audit_log` del tenant, en la misma transacción (quién, acción, recurso, cuándo, IP; sin datos clínicos ni tokens) (CU-13).
6. Una sola línea de Alembic; toda migración es idempotente y probada con upgrade → downgrade → upgrade en Postgres.
7. Todo endpoint nuevo incluye una prueba de **acceso cruzado** contra Postgres real: un usuario del tenant A no puede leer, modificar ni referenciar datos del tenant B (403/404 sin revelar existencia).
8. Las tablas no se exponen por la Data API de Supabase (esquemas no expuestos y permisos revocados a `anon`/`authenticated`).

**Alta de tenant (CU-12)**: endpoint solo para `platform_admin` que, en **una transacción atómica**, crea el tenant, su slug, el primer `tenant_admin` y el registro de auditoría. Tras crearlo, el chequeo de aislamiento demuestra como `app_user` que el tenant nuevo ve 0 filas ajenas y nadie ve las suyas. Debe ser demostrable en vivo.

**Compartir con el médico (CU-07)** cruza tenants. Se resuelve sin excepciones de política entre tenants: la paciente genera un paquete (resultados, heatmaps, diario) con un token de un solo uso y expiración corta; la doctora lo **importa como copia** en su tenant. El token se invalida tras el primer uso y queda auditado en ambos lados.

## Modelo de IA

Estado: **modelo de demostración** (EfficientNet-B0 sin entrenar, 3 clases, `is_demo: true`); el modelo real con BUSI aún no existe. Reentrenar o entrenar se hace FUERA de este repo; limitarlo a 3-4 días en la semana 5. Ver ADR 0006.

- **Producción sin TensorFlow.** La inferencia corre con **LiteRT** (`ai-edge-litert`): pico de 184 MB de RSS con la app completa, frente a ~443 MB de TensorFlow solo, medido en Docker con 512 MB. TensorFlow está solo en `requirements-ml.txt`, para `backend/ml_tools/` (`build_demo_model`, `measure_memory`, `upload_model`).
- **`model_card.json`** es la única fuente de clases (2 o 3, con alias benign/malignant), tamaño de entrada, preprocesamiento (`raw_0_255` para el EfficientNet de Keras, que normaliza **dentro**), `model_version` y sha256 de cada archivo.
- **Carga:** el modelo se carga **una sola vez** en el lifespan, desde `MODEL_DIR` o descargado del bucket privado `MODEL_BUCKET/MODEL_PREFIX`. Si falla, `/health` muestra `model: unavailable` y el análisis responde 503.
- **`backend/app/ml/`:**
  - `runtime.py`: `LiteRTPredictor` y `FakePredictor` para pruebas;
  - `heatmap.py`: `generate_heatmap(image, model)`. Para GAP → Dense, el CAM en numpy equivale exactamente a Grad-CAM; una prueba lenta lo compara con TensorFlow;
  - `quality.py`: rechaza imágenes chicas, a color o uniformes, y marca baja confianza o alta incertidumbre como `inconclusive`;
  - `report.py`: plantillas, sin LLM;
  - `settings.py`: **todos** los umbrales;
  - `service.py`: threadpool, semáforo `MAX_CONCURRENT_INFERENCES` y descarte del EXIF.
- **Salida:** clase (`normal|benigno|maligno`), probabilidades, confianza, `model_version`, heatmap superpuesto y reporte sencillo. El reporte técnico BI-RADS (B2B) llega con el panel médico.
- **DICOM (B2B):** leer con `pydicom`, convertir a imagen normalizada y pasarla por el modelo. BUSI son ecografías: un modelo entrenado en ellas **no es válido para mastografías**. Mostrar siempre que es un prototipo; un modelo real de mastografía requeriría otro dataset (CBIS-DDSM, INbreast, VinDr-Mammo).
- Reportar métricas honestas (matriz de confusión, sensibilidad en maligno). Dividir train/test sin fuga de datos entre imágenes del mismo paciente o serie.

## Seguridad, privacidad y avisos

- Todo resultado y reporte lleva el aviso: *"Herramienta de apoyo al diagnóstico. No sustituye el criterio ni la consulta médica."*
- Consentimiento informado explícito en el registro (CU-01), guardado con fecha y versión del texto.
- Usar solo datos públicos o sintéticos para pruebas y demo. Nunca imágenes de pacientes reales.
- Validar subidas: tipo MIME y extensión permitidos (JPG/PNG/DICOM), tamaño máximo, y rechazar archivos que no abran como imagen.
- No registrar (log) datos clínicos ni tokens. Contraseñas siempre con bcrypt; JWT con expiración corta.
- Limitar tasa en `/auth/token` y `/images/upload`.

## Frontend

- Un solo código React **responsive** (móvil y escritorio) e instalable como **PWA** (`vite-plugin-pwa`). Empaquetado nativo con Capacitor queda como extra futuro.
- Se mantiene MUI y `axios` (ya instalados); no introducir otra librería de UI. Estado de servidor con TanStack Query cuando se agregue.
- Rutas protegidas por rol; la UI de paciente y la de médico comparten componentes pero tienen layouts separados.
- Probar siempre en ancho móvil (~390 px) además de escritorio.
- Recordatorios: por **email** con job programado (push web es opcional; en iPhone solo funciona con la PWA instalada).

## Convenciones de código

- Python 3.12, tipado con type hints, Pydantic v2 para esquemas, SQLAlchemy 2.0 (estilo `select()`), funciones de servicio separadas de los routers (routers delgados).
- Esquemas de entrada/salida en archivos separados de los modelos de base de datos; nunca devolver el modelo ORM directo.
- Errores con `HTTPException` y mensajes claros; sin `print`, usar `logging`.
- Comentarios y mensajes de commit en español; identificadores de código en inglés. Commits pequeños con prefijo (`feat:`, `fix:`, `test:`, `docs:`, `chore:`).
- Una rama por caso de uso (`cu-02-prediccion`, etc.) y PR con descripción de qué CU resuelve.

## Cómo trabajar en este repo (flujo para Claude Code)

1. Para cualquier cambio grande (multitenencia, nuevo caso de uso), **propón primero un plan** y espera aprobación antes de escribir código.
2. Antes de implementar un endpoint, revisa las reglas de multitenencia de arriba.
3. Escribe o actualiza pruebas junto con el código; incluye el caso de acceso cruzado entre tenants.
4. Corre `ruff` y `pytest` antes de dar algo por terminado.
5. Si una decisión afecta la arquitectura, regístrala en `docs/adr/` en pocas líneas.
6. No agregues dependencias pesadas sin avisar: el despliegue en Render tiene RAM limitada.
7. No toques `.env`, no imprimas secretos y no ejecutes nada destructivo contra bases que no sean de desarrollo.

## Plan por fases (6 semanas)

- **Fase 0 (2 días)**: auditar el prototipo, cerrar brechas 1 y 2, agregar Alembic, pytest, ruff y CI básico en GitHub Actions.
- **Semana 1 — Multitenencia**: esquemas `control`/`clinical` con RLS forzado, roles de base, resolución de tenant por transacción, roles de aplicación, alta de tenant con chequeo de aislamiento (CU-12), log de auditoría (CU-13).
- **Semana 2 — B2C núcleo**: registro con consentimiento y cuestionario (CU-01), subida + predicción + heatmap + reporte sencillo (CU-02).
- **Semana 3 — B2C complementario**: autoexploración guiada, diario con mapa corporal, recordatorios, blog (CU-03 a CU-06).
- **Semana 4 — Puente y B2B**: compartir paquete (CU-07), panel médico y lista de pacientes con filtros (CU-08, CU-11), carga DICOM (CU-09).
- **Semana 5**: reentrenamiento u optimización del modelo, PDF y HL7 documentado/simulado (CU-10), pruebas y despliegue estable.
- **Semana 6**: pulido, datos de demo, guion de demo, documentación, buffer.

Orden de recorte si hay retraso: HL7 real → push → video de autoexploración → blog dinámico. **No se recorta**: multitenencia, subida + predicción, panel médico básico.

## Demo final (guion mínimo)

1. Crear un tenant nuevo en vivo y mostrar su base separada.
2. Paciente B2C sube una ecografía y recibe predicción, heatmap y reporte sencillo.
3. La paciente comparte el paquete; la doctora lo importa y lo revisa en su panel.
4. Mostrar que un usuario de otro tenant no puede ver esos datos.
5. Activar el backend de Render antes de la demo (el plan gratuito tarda ~1 min en despertar).