# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

BreastGuard is an early-stage, multi-tenant SaaS for breast cancer detection from medical images (BUSI ultrasound and mammography). A FastAPI backend accepts image uploads, stores them in S3, runs a TensorFlow/Keras classifier (benign/malignant), and persists results in Postgres; a React/Vite frontend consumes the API. The codebase is at "skeleton" stage (see commit `12c04b7`) — several pieces described below are stubbed, inconsistent, or not yet wired together.

Repo layout:
- `backend/` — FastAPI app (`backend/app`)
- `frontend/` — React 19 + Vite SPA
- `infraestructure/` — currently empty, reserved for IaC/deployment config

## Commands

### Backend (run from the repo root, not from `backend/`)

The app has no `__init__.py` files and relies on namespace packages with absolute imports like `backend.app.models...`, so it must be launched from the repository root:

```
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload
```

There is no test suite in the backend yet.

### Frontend (`cd frontend` first)

```
npm install
npm run dev        # Vite dev server
npm run build       # production build
npm run lint         # oxlint
npm run preview     # preview the production build
```

There is no test suite configured in the frontend yet.

## Architecture

### Backend (`backend/app`)

- `main.py` creates the `FastAPI()` app and mounts three routers, all under `/api/v1`: `health`, `auth` (prefixed further with `/auth`), and `images` (prefixed further with `/images`).
- `models/database.py` defines the SQLAlchemy `engine`, `SessionLocal`, and declarative `Base`. `api/v1/health.py`'s `/health` endpoint doubles as the table-creation step (`Base.metadata.create_all`) — there's no separate migration tool (no Alembic).
- `models/user.py` (`User`) and `models/image.py` (`MedicalImage`) are the two SQLAlchemy models, related via `MedicalImage.user_id -> User.id`. Each router (`auth.py`, `images.py`) opens its own DB session with a local `get_db()` dependency rather than a shared one.
- `services/auth.py` handles password hashing (`passlib`/bcrypt) and JWT issuance/verification (`python-jose`) for the `/api/v1/auth` routes (`/register`, `/token`).
- `services/ml_model.py` wraps a Keras model (`BreastCancerModel`) expected at `models/breast_cancer_model.h5` relative to the working directory; it is not yet called from any router — image upload does not currently trigger a prediction.
- `services/s3.py` wraps `boto3` for uploading images to S3 and is called from `api/v1/images.py`'s `/upload` endpoint, which writes the incoming file to a local `temp/` directory before pushing it to S3 and recording the resulting URL on `MedicalImage.image_path`.

Known inconsistencies to be aware of when touching this area:
- `models/user.py` and `models/image.py` import `Base` from `backend.models.database`, while everything else (`main.py`, the `api/v1/*` routers, `services/*`) uses `backend.app.models.database`. The former path is wrong given the actual package layout and will fail to import.
- `models/database.py` imports `declarative` from `sqlalchemy.ext.declarative` (removed/renamed API) but then calls `declarative_base()`, which isn't imported — this module will raise at import time as written.
- Secrets are hardcoded as placeholder literals rather than read from environment/config: the Postgres URL (with password) in `models/database.py`, `SECRET_KEY` in `services/auth.py`, and AWS keys in `services/s3.py`. Treat these as needing to move to env vars before any real deployment.
- `api/v1/images.py`'s upload endpoint defaults `user_id=1` as a query/body param rather than deriving it from the authenticated user — auth (`services/auth.get_current_user`) is not yet wired into the image upload flow.

### Frontend (`frontend/src`)

Standard Vite + React 19 SPA: `main.jsx` mounts `App.jsx`, which sets up client-side routing via `react-router-dom` (currently a single `/` route rendering `pages/Home.jsx`). UI dependencies are MUI (`@mui/material`, `@emotion/*`) and `axios` for HTTP calls to the backend. Linting uses `oxlint` (config in `frontend/.oxlintrc.json`) rather than ESLint.
