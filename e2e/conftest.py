"""Pruebas de extremo a extremo con Playwright: SIEMPRE locales o de CI, nunca contra Render.

Levanta todo en la máquina:
- una base temporal en el Postgres de pruebas (tests/pgtest.py), migrada a head;
- el backend en un hilo (uvicorn, puerto 8011) con Storage en memoria (URLs firmadas como data:)
  y el predictor de prueba (sin modelo real);
- el frontend con Vite (puerto 5174) apuntando a ese backend;
- Chromium sin interfaz.

Uso, desde la raíz: `pytest e2e -q` (requiere `pip install -r requirements-e2e.txt` y
`python -m playwright install chromium`). Solo datos sintéticos.
"""

from tests import pgtest  # isort: skip  (fija las variables de entorno de prueba)

import base64  # noqa: E402
import io  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import httpx  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from PIL import Image  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

API_PORT, WEB_PORT = 8011, 5174
API = f"http://127.0.0.1:{API_PORT}/api/v1"
WEB = f"http://localhost:{WEB_PORT}"
FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def _postgres_available() -> bool:
    try:
        with pgtest.admin_engine().connect():
            return True
    except Exception:
        return False


def ultrasound(seed: int = 0) -> bytes:
    rng = np.random.default_rng(seed)
    array = rng.gamma(2.0, 30.0, (360, 480)).clip(0, 255).astype(np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(array, "L").save(buffer, format="PNG")
    return buffer.getvalue()


class Stack:
    def __init__(self, owner, predictor):
        self.owner = owner
        self.predictor = predictor
        self.http = httpx.Client(timeout=60)

    def sql(self, statement: str, **params):
        with self.owner.begin() as conn:
            return conn.execute(text(statement), params)


@pytest.fixture(scope="session")
def stack():
    if not _postgres_available():
        if os.environ.get("REQUIRE_POSTGRES"):
            pytest.fail("Postgres de pruebas no disponible")
        pytest.skip("Postgres de pruebas no disponible (docker compose up -d db)")
    if shutil.which("npm") is None:
        pytest.skip("npm no está instalado")
    os.environ["FRONTEND_ORIGIN"] = WEB
    os.environ["EMAIL_BACKEND"] = "console"

    pgtest.ensure_supabase_api_roles()
    pgtest.create_database(pgtest.TEST_DB_NAME)
    command.upgrade(pgtest.alembic_config(os.environ["DATABASE_URL"]), "head")

    import uvicorn

    from backend.app.api.deps import get_storage
    from backend.app.main import app
    from backend.app.ml.config import ModelCard
    from backend.app.ml.deps import get_inference
    from backend.app.ml.runtime import FakePredictor
    from backend.app.ml.service import InferenceService
    from backend.app.ml.settings import MLSettings
    from tests.conftest import DEMO_CARD, FakeStorage

    class MemoryStorage(FakeStorage):
        def create_signed_url(self, object_name: str, expires_in: int) -> str:
            return "data:image/png;base64," + base64.b64encode(self.objects[object_name]).decode()

    storage = MemoryStorage()
    predictor = FakePredictor(
        ModelCard.from_dict(DEMO_CARD), {"normal": 0.9, "benigno": 0.07, "maligno": 0.03}
    )
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_inference] = lambda: InferenceService(predictor, MLSettings())
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=API_PORT, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.1)

    env = {**os.environ, "VITE_API_URL": f"http://127.0.0.1:{API_PORT}"}
    vite = subprocess.Popen(
        f"npm run dev -- --port {WEB_PORT} --strictPort",
        cwd=FRONTEND,
        env=env,
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    owner = create_engine(os.environ["DATABASE_URL"])
    try:
        for _ in range(240):
            try:
                if httpx.get(WEB, timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.5)
        else:
            pytest.fail("Vite no arrancó")
        yield Stack(owner, predictor)
    finally:
        if sys.platform == "win32":
            subprocess.run(f"taskkill /PID {vite.pid} /T /F", shell=True, capture_output=True)
        else:
            vite.terminate()
        server.should_exit = True
        app.dependency_overrides.clear()
        owner.dispose()
        time.sleep(1)
        pgtest.drop_database(pgtest.TEST_DB_NAME)


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        chromium = playwright.chromium.launch()
        yield chromium
        chromium.close()


@pytest.fixture
def new_page(browser):
    """Cada actor en su propio contexto (sesión aislada), en ancho móvil o de escritorio."""
    contexts = []

    def make(width: int = 1440, height: int = 1000):
        context = browser.new_context(viewport={"width": width, "height": height})
        contexts.append(context)
        page = context.new_page()
        page.set_default_timeout(30_000)
        return page

    yield make
    for context in contexts:
        context.close()
