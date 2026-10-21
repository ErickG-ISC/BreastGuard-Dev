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
- `infraestructure/` — vacío, reservado para despliegue/IaC (el nombre tiene ese typo a propósito; no renombrar sin avisar)
- `docs/` — casos de uso, decisiones de arquitectura (ADR) y guion de demo

## Comandos

### Backend (ejecutar desde la RAÍZ del repo, no desde `backend/`)

La app no tiene `__init__.py` y usa namespace packages con imports absolutos tipo `backend.app.models...`, por lo que debe lanzarse desde la raíz:

```
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
cp .env.example .env           # llenar valores, ver "Configuración"
uvicorn backend.app.main:app --reload
```

`requirements.txt` está en la raíz, no en `backend/`.

Pruebas y calidad (una vez configuradas; ver Fase 0):

```
pytest -q                      # pruebas
ruff check . && ruff format .  # lint y formato
alembic -c backend/alembic.ini upgrade head                 # base de control
python -m backend.scripts.migrate_all_tenants               # migra TODAS las bases de tenant
```

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

Variables existentes: `DATABASE_URL`, `SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_BUCKET`, `FRONTEND_ORIGIN`, `MODEL_PATH`, y `VITE_API_URL` en el frontend.

Variables nuevas que introduce la multitenencia (agregarlas a `.env.example` sin valores reales):
- `CONTROL_DATABASE_URL` — base de control (reemplaza el rol actual de `DATABASE_URL`).
- `TENANT_DSN_KEY` — llave Fernet para cifrar las cadenas de conexión de cada tenant en la tabla `tenants`.

Reglas de infraestructura:
- `.python-version` fija Python 3.12 (TensorFlow y SQLAlchemy van detrás de las últimas versiones de CPython). No subirlo a 3.13/3.14.
- Para Supabase usar siempre la cadena del **Session pooler**, no "Direct connection" (solo resuelve por IPv6 y falla en Render con `Network is unreachable`).
- Render en plan gratuito se duerme y tiene ~512 MB de RAM: ver sección del modelo de IA.
- Nunca commitear `.env`, llaves ni datos médicos reales.

## Arquitectura actual (estado "esqueleto")

### Backend (`backend/app`)

- `main.py`: carga `.env`, crea `FastAPI()`, agrega `CORSMiddleware` (orígenes de `FRONTEND_ORIGIN`, separados por coma) y monta tres routers bajo `/api/v1`: `health`, `auth` (`/auth`) e `images` (`/images`).
- `models/database.py`: `engine`, `SessionLocal` y `Base` (único engine global; **esto debe cambiar**, ver multitenencia).
- `models/user.py` (`User`) y `models/image.py` (`MedicalImage`), relacionados por `MedicalImage.user_id -> User.id`.
- Cada router define su propio `get_db()` local. **Debe unificarse** en una dependencia compartida que entregue la sesión del tenant.
- `/health` además crea las tablas (`Base.metadata.create_all`). **No hay Alembic todavía; reemplazar por migraciones.**
- `services/auth.py`: hash con `passlib`/bcrypt y JWT con `python-jose` (`/register`, `/token`).
- `services/ml_model.py`: `BreastCancerModel` envuelve un modelo **Keras/TensorFlow** (`.h5`, ruta en `MODEL_PATH`, por defecto `models/breast_cancer_model.h5`). El `.h5` no está en el repo y **ningún router lo invoca aún**.
- `services/storage.py`: sube imágenes a un bucket de Supabase Storage; lo usa `/images/upload`, que escribe primero en `temp/` local y guarda la URL pública en `MedicalImage.image_path`. No se usa AWS/S3.

### Frontend (`frontend/src`)

SPA estándar: `main.jsx` monta `App.jsx`, que define rutas con `react-router-dom` (hoy solo `/` → `pages/Home.jsx`). UI con MUI (`@mui/material`, `@emotion/*`) y `axios`. Lint con `oxlint`.

### Brechas conocidas (resolver en este orden)

1. `/images/upload` usa `user_id=1` por defecto en lugar del usuario autenticado. **Es un hueco de seguridad**: conectar `services/auth.get_current_user` antes de construir nada más sobre ese endpoint.
2. Archivos temporales en `temp/` sin nombres únicos ni limpieza; usar nombres aleatorios (uuid) y borrar en `finally`.
3. Las URLs públicas de Supabase Storage no sirven para datos médicos: pasar a bucket privado con URLs firmadas de corta duración.
4. El modelo no está conectado al flujo de subida y es binario (benigno/maligno); CU-02 pide también "normal" (BUSI tiene las tres clases).
5. Sin pruebas, sin migraciones, sin CI.

## Arquitectura objetivo: multitenencia (REGLAS INNEGOCIABLES)

Modelo: **una base de datos física por tenant**, más una base de control.

- **Base de control**: tabla `tenants` (id, slug, nombre, tipo `b2c|institucion`, `dsn_cifrado`, plan, activo) y datos de identidad global (usuarios con `tenant_id` y rol). Autenticación y JWT viven aquí.
- **Bases de tenant** (2 o 3 para la demo): una compartida para pacientes B2C y una por clínica. Alojadas en Supabase (si el plan gratuito lo permite) o Azure Database for PostgreSQL Flexible Server (cuenta de estudiante). Row Level Security es **último recurso**, no la estrategia principal.
- **Roles**: `patient`, `doctor`, `tenant_admin`, `platform_admin`. El JWT incluye `sub`, `tenant_id` y `role`.
- **Resolución de tenant**: una dependencia de FastAPI lee `tenant_id` del JWT, busca el tenant en la base de control, descifra su DSN y entrega una `Session` de SQLAlchemy del engine correcto (engines cacheados por tenant con tamaño de pool pequeño; los pools son limitados en el plan gratuito).

Reglas que nunca se rompen:
1. **Prohibido usar un engine/sesión global** para datos de negocio. Todo endpoint obtiene la sesión mediante la dependencia compartida `get_tenant_db`.
2. **El `tenant_id` sale solo del JWT verificado**, jamás de un parámetro, header o body enviado por el cliente.
3. Ninguna consulta mezcla datos de dos tenants. No hay JOINs entre bases.
4. Archivos en Storage con prefijo/bucket por tenant (`{tenant_slug}/...`), validando pertenencia antes de firmar una URL.
5. Cada acceso a datos de pacientes escribe un registro de auditoría en la base del tenant (quién, qué, cuándo, IP). El log de auditoría es por tenant (CU-13).
6. Toda migración debe poder correr en todas las bases de tenant (`migrate_all_tenants`) y ser idempotente.
7. Todo endpoint nuevo incluye una prueba de **acceso cruzado**: un usuario del tenant A no puede leer ni modificar datos del tenant B.

**Alta de tenant (CU-12)**: endpoint solo para `platform_admin` que crea la fila en `tenants`, aprovisiona/asigna la base, corre migraciones y crea el primer `tenant_admin`. Debe ser demostrable en vivo.

**Compartir con el médico (CU-07)** cruza tenants. Se resuelve sin consultas entre bases: la paciente genera un paquete (resultados, heatmaps, diario) con un token de un solo uso y expiración corta; la doctora lo **importa como copia** en su tenant. El token se invalida tras el primer uso y queda auditado en ambos lados.

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
- **Semana 1 — Multitenencia**: base de control, `tenants`, resolución de tenant, roles, migraciones multi-base, alta de tenant (CU-12), log de auditoría (CU-13).
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