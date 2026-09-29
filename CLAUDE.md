# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

BreastGuard is a multi-tenant SaaS for breast cancer image analysis (ultrasound/BUSI and mammography). It has two independent apps in one repo: a FastAPI backend (`backend/`) and a React + Vite frontend (`frontend/`). `infraestructure/` is currently an empty placeholder for future IaC.

## Commands

### Frontend (`frontend/`)
Run from the `frontend/` directory:
- `npm run dev` — start the Vite dev server
- `npm run build` — production build
- `npm run lint` — lint with oxlint (rules in `.oxlintrc.json`)
- `npm run preview` — preview a production build

There is no test runner configured yet.

### Backend (`backend/`)
There's a `venv/` at the repo root (Windows) with `backend/requirements.txt` installed. No documented entrypoint script yet; run the API from the **repo root** (not from inside `backend/`) so the `backend` package resolves:
```
venv/Scripts/python.exe -m uvicorn backend.app.main:app --reload
```
`backend/` and every subpackage now has an `__init__.py`, so it's an explicit regular package (not relying on implicit namespace packages). There is no test runner configured yet.

Config is read from environment variables via `backend/.env` (loaded with `python-dotenv`; see `backend/.env.example` for the full list — `DATABASE_URL`, `SECRET_KEY`, `ALLOWED_ORIGINS`, `STORAGE_BACKEND` + local/S3 storage vars). `backend/.env` is gitignored; copy the example and fill in real values, it is never committed.

## Architecture

### Backend layers
- `app/main.py` — FastAPI app instance, loads `.env`, adds CORS middleware (origins from `ALLOWED_ORIGINS`), mounts three routers under `/api/v1`: `health`, `/api/v1/auth` (`auth`), `/api/v1/images` (`images`).
- `app/api/v1/` — route handlers only; each defines its own `get_db()` dependency (duplicated per file rather than shared).
- `app/models/database.py` — SQLAlchemy engine/session/`Base`. Connection string comes from `DATABASE_URL` (falls back to a placeholder RDS URL if unset).
- `app/models/user.py`, `app/models/image.py` — SQLAlchemy models. `User` has a one-to-many `images` relationship to `MedicalImage` (via `user_id` FK).
- `app/services/auth.py` — password hashing (passlib/bcrypt) and JWT issuance/validation (python-jose). `SECRET_KEY` comes from the env var of the same name (falls back to a placeholder).
- `app/services/storage.py` — `store_uploaded_file()` saves an uploaded file either to local disk on the server (`STORAGE_BACKEND=local`, default — under `LOCAL_STORAGE_DIR`, meant to be served by Nginx at `LOCAL_STORAGE_PUBLIC_BASE`) or to S3 (`STORAGE_BACKEND=s3`, needs `S3_BUCKET_NAME` + AWS creds; supports `AWS_SESSION_TOKEN` for temporary credentials, e.g. AWS Academy). This replaced the old `services/s3.py` (deleted — it only supported S3 with hardcoded fake credentials).
- `app/services/ml_model.py` — `BreastCancerModel` wraps a Keras model (`models/breast_cancer_model.h5`, resized to 224x224, binary benign/malignant classification). The model file does not exist in the repo, and this class is still **not wired into** `app/api/v1/images.py` — image upload stores the file and a DB row but does not call the model for a prediction yet.

### Image upload flow
`POST /api/v1/images/upload` writes the incoming file to a local `temp/` directory, stores it via `services/storage.py` (local disk or S3 depending on `STORAGE_BACKEND`), persists a `MedicalImage` row with the resulting URL/path, then deletes the temp file. `user_id` is currently a request parameter defaulting to `1` rather than derived from the authenticated user — auth (`get_current_user`) exists in `services/auth.py` but isn't yet enforced on this route.

### Frontend
Standard Vite + React 19 SPA using `react-router-dom` for routing (currently a single `/` route to `Home`, which is just a placeholder heading) and MUI (`@mui/material`) + Emotion for styling. `axios` is a dependency for API calls to the backend but no API client/base URL config exists yet — when wiring real requests, point them at the backend's `ALLOWED_ORIGINS`-matching host and add an env-driven base URL (e.g. Vite's `import.meta.env`).

## Fixed bugs (2026-09-28)
The following were broken/inconsistent and have been fixed — worth knowing since they explain why some code looks slightly different from a "naive" reading of a skeleton FastAPI+SQLAlchemy project: import paths were missing an `.app.` segment across most of `backend/app/` (only `main.py` had it right); `models/database.py` imported a nonexistent `declarative` name instead of `declarative_base`; `models/user.py` was missing `from sqlalchemy.orm import relationship` and used the invalid `Column(..., on_update=...)` kwarg instead of `onupdate=...`; `models/image.py` used `func.now()` without importing `func`. `requirements.txt` also had unpinned/loosely pinned entries and trailing whitespace on some lines (`sqlalchemy` was bumped to `2.0.36` — `2.0.23` crashes on Python 3.13).

## Notes for future work
Remaining hardcoded placeholder values (DB URL fallback, `SECRET_KEY` fallback in `services/auth.py`) are intentional dev-only fallbacks used when the corresponding env var isn't set — always set real env vars via `backend/.env` outside of local dev.
