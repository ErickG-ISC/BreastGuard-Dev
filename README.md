# BreastGuard-Dev

Plataforma SaaS multitenant de **apoyo al diagnóstico** para la detección temprana de cáncer de mama.

> Herramienta de apoyo al diagnóstico. No sustituye el criterio ni la consulta médica.

## Backend (desde la raíz del repo)

```
py -3.12 -m venv venv                  # Python 3.12 (ver .python-version)
venv\Scripts\activate                  # Windows
pip install -r requirements-dev.txt
cp .env.example .env                   # llenar valores
alembic -c backend/alembic.ini upgrade head
uvicorn backend.app.main:app --reload
```

Pruebas y calidad: `pytest -q`, `ruff check .` y `ruff format .`. El CI de GitHub Actions corre lo mismo en cada push y PR.

## Frontend

```
cd frontend
npm install
npm run dev
```

## Demo de multitenencia (CU-12 y CU-13)

1. Migrar la base de desarrollo (rol dueño): `alembic -c backend/alembic.ini upgrade head`
2. Crear el primer administrador de plataforma:
   `python -m backend.scripts.create_platform_admin --email admin@ejemplo.com --name "Admin"`
3. Levantar el backend (`uvicorn backend.app.main:app --reload`) y el frontend (`npm run dev`).
4. Entrar como platform_admin → **Nueva institución** → se abre el **chequeo de aislamiento**: muestra
   que el tenant nuevo ve 0 filas ajenas y que ningún otro tenant ve las suyas.
5. Un `tenant_admin` consulta el log de su tenant en `GET /api/v1/audit`.
6. Purga de demostración: `python -m backend.scripts.purge_tenant --slug <slug> --dry-run`.

Las pruebas corren contra un Postgres local: `docker compose up -d db` y luego `pytest -q`.

Más detalle en `CLAUDE.md` y `docs/`.
