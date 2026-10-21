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

Más detalle en `CLAUDE.md` y `docs/`.
