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
- `tests/` — pytest (`conftest.py` con fixtures; `helpers.py` con utilidades importables)
- `infraestructure/` — reservado para despliegue/IaC; todavía no existe en el repo (git no guarda carpetas vacías). El nombre lleva ese typo a propósito; no renombrar sin avisar
- `docs/` — casos de uso (`casos-de-uso.md`) y decisiones de arquitectura (`adr/`). El guion de demo está pendiente
- `.github/workflows/ci.yml` — CI: ruff y pytest en cada push y PR (Python 3.12, sin TensorFlow)

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
pytest -q                      # pruebas (SQLite en memoria + doble de Storage; no leen .env)
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

Variables existentes: `DATABASE_URL`, `SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_BUCKET`, `FRONTEND_ORIGIN`, `MODEL_PATH`, `MAX_UPLOAD_MB` (opcional, 10 por defecto), y `VITE_API_URL` en el frontend.

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

- `main.py`: carga `.env`, crea `FastAPI()`, agrega `CORSMiddleware` (orígenes de `FRONTEND_ORIGIN`, separados por coma) y monta tres routers bajo `/api/v1`: `health`, `auth` (`/auth`) e `images` (`/images`).
- `models/base.py`: `Base` declarativa, sin efectos secundarios (la importan los modelos y `backend/migrations/env.py`).
- `models/database.py`: `engine` y `SessionLocal` globales leídos de `DATABASE_URL` (único engine global; **esto debe cambiar**, ver multitenencia).
- `models/user.py` (`User`) y `models/image.py` (`MedicalImage`), relacionados por `MedicalImage.user_id -> User.id`.
- `api/deps.py`: dependencias compartidas. `get_db` es el **único** punto que entrega sesiones (alias `DbSession`); `get_current_user` (alias `CurrentUser`) lee el Bearer token y devuelve el `User`; `get_storage` (alias `Storage`) entrega el servicio de Storage y es el punto de override en pruebas. En la Semana 1, `get_db` se divide en `get_control_db` (login/registro, que aún no tienen JWT) y `get_tenant_db` (ver `docs/adr/0001-alembic-y-migraciones.md`).
- `api/v1/*`: routers delgados; la lógica vive en `services/`, y los esquemas Pydantic de entrada/salida en `schemas/`.
- `/auth/register` recibe JSON (`UserCreate`) y devuelve `UserOut`; `/auth/token` (formulario OAuth2) devuelve `Token` o 401.
- `/health` solo hace `SELECT 1` (503 genérico si falla). El esquema lo crea **Alembic** (`backend/migrations/`); nunca `create_all`.
- `services/auth.py`: hash con `passlib`/bcrypt y JWT con `python-jose` (`sub` = id del usuario, `exp` y `sub` obligatorios); también `create_user`, `authenticate_user` y `get_user_by_email`. Los endpoints viven en `api/v1/auth.py`.
- `services/images.py`: valida la subida (extensión y MIME JPG/PNG, tamaño `MAX_UPLOAD_MB`, que abra con Pillow), escribe un temporal con nombre uuid en el directorio temporal del sistema (lo borra en `finally`) y sube a Storage como `uploads/{user_id}/{uuid}.{ext}`. El nombre del archivo del cliente nunca forma parte de una ruta. DICOM se rechaza hasta CU-09.
- `services/ml_model.py`: `BreastCancerModel` envuelve un modelo **Keras/TensorFlow** (`.h5`, ruta en `MODEL_PATH`, por defecto `models/breast_cancer_model.h5`). El `.h5` no está en el repo y **ningún router lo invoca aún**.
- `services/storage.py`: `SupabaseStorage.upload_file` sube al bucket de Supabase Storage (cliente creado al primer uso) y devuelve la URL pública, que se guarda en `MedicalImage.image_path`. Los fallos se registran solo por tipo y se lanzan como `StorageError` (502). No se usa AWS/S3.

### Frontend (`frontend/src`)

SPA estándar: `main.jsx` monta `App.jsx`, que define rutas con `react-router-dom` (hoy solo `/` → `pages/Home.jsx`). UI con MUI (`@mui/material`, `@emotion/*`) y `axios`. Lint con `oxlint`.

### Brechas conocidas (resolver en este orden)

Resueltas en la Fase 0: usuario de `/images/upload` tomado del JWT (antes `user_id=1`), temporales con uuid y limpieza en `finally`, validación de subidas, `get_db` unificado, Alembic, pytest, ruff y CI.

Pendientes:
1. Las URLs públicas de Supabase Storage no sirven para datos médicos: pasar a bucket privado con URLs firmadas de corta duración (guardar la ruta del objeto, no la URL).
2. El modelo no está conectado al flujo de subida y es binario (benigno/maligno); CU-02 pide también "normal" (BUSI tiene las tres clases).
3. Sin rate limit en `/auth/token` ni `/images/upload`.
4. `is_medical` lo declara el propio usuario al registrarse; se sustituye por roles asignados en la Semana 1.
5. Si falla el commit después de subir a Storage, queda un objeto huérfano.
6. La ruta `uploads/{user_id}/...` es provisional: en la Semana 1 pasa a `{tenant_slug}/...` con el slug resuelto en el servidor.

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

Estado: EfficientNet-B0 en **Keras/TensorFlow** (`.h5`) entrenado con BUSI. Hay planes de reentrenar con un dataset más completo; limitar esa tarea a 3-4 días en la semana 5 y, si no mejora, conservar el modelo actual.

- Cargar el modelo **una sola vez** al iniciar la app (lifespan de FastAPI), nunca por petición.
- Usar `tensorflow-cpu`. Si Render se queda sin RAM, convertir a TFLite u ONNX (`tf2onnx`) o mover la inferencia a otro servicio; decidir midiendo, no suponiendo.
- Heatmap con Grad-CAM (`tf.GradientTape` sobre la última capa convolucional). Mantenerlo detrás de una función `generate_heatmap(image, model)` fácil de reemplazar.
- Salida del servicio: clase (`normal|benigno|maligno`), confianza, heatmap superpuesto. Dos "perfiles" de reporte: **sencillo** (paciente, B2C) y **técnico con terminología BI-RADS** (médico, B2B).
- **DICOM (B2B)**: leer con `pydicom`, convertir a imagen normalizada y pasarla por el modelo. BUSI son ecografías: un modelo entrenado en ellas **no es válido para mastografías**. Mostrar siempre en pantalla que es un prototipo; un modelo real de mastografía requeriría otro dataset (CBIS-DDSM, INbreast, VinDr-Mammo) y queda como trabajo futuro.
- Reportar métricas honestas (matriz de confusión, sensibilidad en maligno). Dividir train/test sin fuga de datos entre imágenes del mismo paciente/serie.

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