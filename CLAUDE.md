# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

BreastGuard is an early-stage, multi-tenant SaaS for breast cancer detection from medical images (BUSI ultrasound and mammography). A FastAPI backend accepts image uploads, stores them in Supabase Storage, runs a TensorFlow/Keras classifier (benign/malignant), and persists results in Postgres; a React/Vite frontend consumes the API. The codebase is at "skeleton" stage (see commit `12c04b7`) — several pieces described below are stubbed or not yet wired together.

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
pip install -r requirements.txt
cp .env.example .env           # fill in the values, see "Configuration" below
uvicorn backend.app.main:app --reload
```

`requirements.txt` lives at the repo root (not under `backend/`), so `pip install` must be run from there too.

There is no test suite in the backend yet.

### Configuration

The backend reads all secrets/connection info from environment variables (no more hardcoded credentials) — see `.env.example` at the repo root for the full list (`DATABASE_URL`, `SECRET_KEY`, `SUPABASE_URL`/`SUPABASE_KEY`/`SUPABASE_BUCKET`, `FRONTEND_ORIGIN`, `MODEL_PATH`). `main.py` calls `load_dotenv()` before importing anything else, so a `.env` file at the repo root is picked up automatically for local runs; on Render/Railway/etc. set these directly in the platform's environment settings instead. `frontend/.env.example` documents the one frontend variable (`VITE_API_URL`).

`.python-version` at the repo root pins Python to 3.12 for platforms that read it (e.g. Render) — SQLAlchemy and TensorFlow/`tensorflow-cpu` lag behind the newest CPython releases, so letting a host default to the latest Python (3.13/3.14) breaks the build.

`DATABASE_URL` must point at Supabase's **Session pooler** connection string, not "Direct connection" — Supabase's direct connection host only resolves over IPv6, which Render (and most PaaS providers) can't reach, so it fails with `Network is unreachable`. See the note in `.env.example`.

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

- `main.py` loads `.env` (via `python-dotenv`), creates the `FastAPI()` app, adds `CORSMiddleware` (origins come from `FRONTEND_ORIGIN`, comma-separated), and mounts three routers, all under `/api/v1`: `health`, `auth` (prefixed further with `/auth`), and `images` (prefixed further with `/images`).
- `models/database.py` defines the SQLAlchemy `engine`, `SessionLocal`, and declarative `Base`. `api/v1/health.py`'s `/health` endpoint doubles as the table-creation step (`Base.metadata.create_all`) — there's no separate migration tool (no Alembic).
- `models/user.py` (`User`) and `models/image.py` (`MedicalImage`) are the two SQLAlchemy models, related via `MedicalImage.user_id -> User.id`. Each router (`auth.py`, `images.py`) opens its own DB session with a local `get_db()` dependency rather than a shared one.
- `services/auth.py` handles password hashing (`passlib`/bcrypt) and JWT issuance/verification (`python-jose`) for the `/api/v1/auth` routes (`/register`, `/token`).
- `services/ml_model.py` wraps a Keras model (`BreastCancerModel`) loaded from `MODEL_PATH` (defaults to `models/breast_cancer_model.h5` relative to the working directory); the `.h5` file itself isn't checked into the repo, and this service isn't called from any router yet — image upload does not currently trigger a prediction.
- `services/storage.py` wraps `supabase-py` for uploading images to a Supabase Storage bucket (`SUPABASE_BUCKET`) and is called from `api/v1/images.py`'s `/upload` endpoint, which writes the incoming file to a local `temp/` directory before pushing it to storage and recording the resulting public URL on `MedicalImage.image_path`. No AWS/S3 is used anywhere in the project.

Remaining known gap:
- `api/v1/images.py`'s upload endpoint defaults `user_id=1` as a query/body param rather than deriving it from the authenticated user — auth (`services/auth.get_current_user`) is not yet wired into the image upload flow.

### Frontend (`frontend/src`)

Standard Vite + React 19 SPA: `main.jsx` mounts `App.jsx`, which sets up client-side routing via `react-router-dom` (currently a single `/` route rendering `pages/Home.jsx`). UI dependencies are MUI (`@mui/material`, `@emotion/*`) and `axios` for HTTP calls to the backend. Linting uses `oxlint` (config in `frontend/.oxlintrc.json`) rather than ESLint.
