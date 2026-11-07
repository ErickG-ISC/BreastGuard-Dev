# BreastGuard

Plataforma SaaS multitenant de **apoyo al diagnóstico** para la detección temprana de cáncer de
mama a partir de ecografías (y, como prototipo, mastografías DICOM). Proyecto escolar.

> Herramienta de apoyo al diagnóstico. No sustituye el criterio ni la consulta médica.

- **Pacientes (B2C):**
  - registro con consentimiento y cuestionario;
  - análisis de una ecografía con mapa de calor y reporte sencillo (también en PDF);
  - autoexploración guiada, diario de síntomas, recordatorios y blog;
  - compartir un paquete cifrado con su médica.
- **Médicas (B2B):**
  - panel de pacientes e importación del paquete;
  - caso con línea de tiempo, notas y BI-RADS asignado por ella;
  - estudios DICOM (prototipo);
  - exportación PDF y HL7 v2 simulado.
- **Administración:** alta de instituciones (tenants) con chequeo de aislamiento, personal, traspaso de pacientes y bitácoras.

## Arquitectura
```
React 19 + MUI (PWA, Vercel) ──HTTPS + JWT──► FastAPI (Render, 512 MB)
                                                 ├─ app_user (NOSUPERUSER, NOBYPASSRLS)
                                                 │    └─ Postgres de Supabase, una sola base:
                                                 │         control  (identidad, administración)
                                                 │         clinical (datos clínicos, RLS FORZADO)
                                                 ├─ Supabase Storage (bucket privado, URLs firmadas)
                                                 └─ Modelo LiteRT (cargado una vez; sin TensorFlow)
```
- **Multitenencia con RLS forzado** (ADR 0002 y 0003):
  - cada transacción fija `app.tenant_id`, `app.user_id` y `app.role` a partir del JWT verificado;
  - sin contexto se ven 0 filas;
  - la médica solo ve sus pacientes y las administradoras nada clínico (ADR 0009).
- **Auditoría** de todo acceso a datos de pacientes en la misma transacción (CU-13).
- **Modelo:** LiteRT con ficha versionada, calibración y paridad verificada contra Keras (ADR 0006, 0013 y 0014).

Más detalle en [docs/arquitectura-multitenencia.md](docs/arquitectura-multitenencia.md) y en los
[ADR](docs/adr/README.md). Guía para trabajar en el repo: [CLAUDE.md](CLAUDE.md).

## Estructura
| Carpeta | Contenido |
|---|---|
| `backend/app` | API FastAPI: `api/v1` (routers), `services`, `schemas`, `models`, `ml`, `content` |
| `backend/migrations` | Alembic, una sola línea (`rls.py` con los helpers de RLS) |
| `backend/scripts` | administración y demo (crear admin, purgar, datos demo, smoke test) |
| `backend/ml_tools` | herramientas LOCALES del modelo (construir, medir, paridad, validar, subir) |
| `frontend` | SPA React 19 + Vite + MUI, instalable como PWA |
| `tests` | pytest contra **Postgres real** (aislamiento, RLS, acceso cruzado) |
| `e2e` | flujos con Playwright contra un entorno local o de CI |
| `docs` | casos de uso, ADR, despliegue, demo, limitaciones |

## Instalación local
Requisitos: Python 3.12, Node 22 y Docker (para el Postgres de pruebas).

```
# Backend (siempre desde la RAÍZ del repo)
py -3.12 -m venv venv
venv\Scripts\activate                       # Windows (Linux/macOS: source venv/bin/activate)
pip install -r requirements-dev.txt
cp .env.example .env                        # llenar valores; nunca commitear .env
alembic -c backend/alembic.ini upgrade head
uvicorn backend.app.main:app --reload

# Frontend
cd frontend
npm install
cp .env.example .env                        # VITE_API_URL
npm run dev
```

Primer administrador de plataforma:
`python -m backend.scripts.create_platform_admin --email admin@ejemplo.com --name "Admin"`.

## Pruebas y calidad
```
docker compose up -d db          # Postgres 17 de pruebas (puerto 54329)
pytest -q                        # backend contra Postgres real
ruff check . && ruff format --check .
cd frontend && npm run lint && npm run build && npm run check:sw
pytest e2e -q                    # Playwright (requirements-e2e.txt + playwright install chromium)
pip-audit -r requirements-dev.txt; cd frontend && npm audit --audit-level=high
```
El CI (`.github/workflows/ci.yml`) corre lo mismo en cada push. E2E y la auditoría de
dependencias van en workflows aparte que no bloquean la fusión.

## Despliegue
Backend en **Render** (plan gratuito), frontend en **Vercel**, base de datos y Storage en
**Supabase**. Guía completa: [docs/despliegue.md](docs/despliegue.md).

1. **Migrar primero**, desde tu computadora: `alembic -c backend/alembic.ini upgrade head`. Nunca se migra en el build.
2. `git push` a `main`: Render y Vercel despliegan. Si la base quedó atrasada, `/api/v1/health` responde 503 y Render conserva la versión anterior.
3. Smoke test de solo lectura:
   `python -m backend.scripts.smoke_deployed --api https://<api>.onrender.com --web https://<app>.vercel.app`.

Demo: [docs/demo.md](docs/demo.md). Si el modelo nuevo no cabe en Render:
[docs/migracion-hosting.md](docs/migracion-hosting.md).

## Limitaciones
Modelo de demostración sin entrenar, mastografía solo como prototipo, HL7 simulado, plan gratuito
que se duerme y otras: [docs/limitaciones-conocidas.md](docs/limitaciones-conocidas.md).

Solo datos **públicos o sintéticos**: nunca imágenes ni datos de pacientes reales.
