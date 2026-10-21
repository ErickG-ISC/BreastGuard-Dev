"""Configuración del Postgres de pruebas. Se importa UNA sola vez (antes que la app).

Cada sesión de pytest usa una base temporal en el Postgres de pruebas (`TEST_DATABASE_URL`,
por defecto el de docker-compose): las migraciones corren como dueño y la app se conecta
como el rol de prueba `bg_app_test` (sin superusuario ni BYPASSRLS). Nunca se usa el .env real.
"""

import os
import uuid
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

TEST_DATABASE_DEFAULT = "postgresql://postgres:postgres@localhost:54329/postgres"
TEST_APP_ROLE = "bg_app_test"
TEST_APP_PASSWORD = "bg-app-test-password"  # credencial local de pruebas, no es un secreto

ADMIN_URL = make_url(os.environ.get("TEST_DATABASE_URL", TEST_DATABASE_DEFAULT))
TEST_DB_NAME = f"bg_test_{uuid.uuid4().hex[:10]}"
OWNER_URL = ADMIN_URL.set(database=TEST_DB_NAME)
APP_URL = OWNER_URL.set(username=TEST_APP_ROLE, password=TEST_APP_PASSWORD)

if ADMIN_URL.host not in {"localhost", "127.0.0.1"} and not os.environ.get("ALLOW_REMOTE_TEST_DB"):
    raise RuntimeError("Las pruebas solo corren contra un Postgres local (TEST_DATABASE_URL)")

# Variables ANTES de importar la app; load_dotenv() no sobrescribe las ya definidas.
os.environ["DATABASE_URL"] = OWNER_URL.render_as_string(hide_password=False)
os.environ["APP_DATABASE_URL"] = APP_URL.render_as_string(hide_password=False)
os.environ["APP_DB_USER"] = TEST_APP_ROLE
os.environ["APP_DB_PASSWORD"] = TEST_APP_PASSWORD
os.environ["SECRET_KEY"] = "clave-solo-para-pruebas"
os.environ["SUPABASE_URL"] = "http://localhost:54321"
os.environ["SUPABASE_KEY"] = "clave-falsa"
os.environ["SUPABASE_BUCKET"] = "bucket-de-prueba"

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "backend" / "alembic.ini"


def alembic_config(db_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.attributes["dburl"] = db_url
    return config


def admin_engine():
    return create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")


def create_database(name: str) -> None:
    engine = admin_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        engine.dispose()


def ensure_supabase_api_roles() -> None:
    """Crea anon/authenticated/service_role (como en Supabase) para probar las revocaciones."""
    engine = admin_engine()
    try:
        with engine.connect() as conn:
            for role in ("anon", "authenticated", "service_role"):
                exists = conn.execute(
                    text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}
                ).first()
                if not exists:
                    conn.execute(text(f"CREATE ROLE {role} NOLOGIN"))
    finally:
        engine.dispose()


def drop_database(name: str) -> None:
    engine = admin_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        engine.dispose()
