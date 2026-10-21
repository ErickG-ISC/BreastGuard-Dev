"""Fixtures de pruebas contra Postgres real (RLS no existe en SQLite). Ver tests/pgtest.py."""

from tests.pgtest import (  # isort: skip  (debe ir antes que la app: fija las variables)
    OWNER_URL,
    TEST_DB_NAME,
    admin_engine,
    alembic_config,
    create_database,
    drop_database,
    ensure_supabase_api_roles,
)

import os  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from backend.app.api.deps import get_storage  # noqa: E402
from backend.app.api.rate_limit import limiter  # noqa: E402
from backend.app.db import get_engine  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.ml.config import ModelCard  # noqa: E402
from backend.app.ml.deps import get_inference  # noqa: E402
from backend.app.ml.runtime import FakePredictor  # noqa: E402
from backend.app.ml.service import InferenceService  # noqa: E402
from backend.app.ml.settings import MLSettings  # noqa: E402
from backend.app.services.storage import StorageError  # noqa: E402
from tests.helpers import TestUser, insert_tenant, insert_user  # noqa: E402


@pytest.fixture(scope="session")
def postgres_available() -> None:
    try:
        engine = admin_engine()
        with engine.connect():
            pass
        engine.dispose()
    except OperationalError:
        message = "Postgres de pruebas no disponible: corre `docker compose up -d db`"
        if os.environ.get("REQUIRE_POSTGRES"):
            pytest.fail(message)
        pytest.skip(message)


@pytest.fixture(scope="session")
def database(postgres_available):
    """Base temporal migrada a head; se borra al terminar la sesión."""
    ensure_supabase_api_roles()
    create_database(TEST_DB_NAME)
    try:
        command.upgrade(alembic_config(os.environ["DATABASE_URL"]), "head")
        yield
    finally:
        get_engine().dispose()
        drop_database(TEST_DB_NAME)


@pytest.fixture(scope="session")
def owner_engine(database):
    """Engine del DUEÑO: solo para preparar y limpiar datos de prueba, nunca para verificar RLS."""
    engine = create_engine(OWNER_URL)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture(autouse=True)
def _clean_tables(request):
    yield
    if "owner_engine" not in request.fixturenames:
        return
    engine = request.getfixturevalue("owner_engine")
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE clinical.audit_log, clinical.questionnaires, clinical.analyses, "
                "clinical.medical_images, "
                "clinical.patients"
            )
        )
        conn.execute(text("DELETE FROM control.subscriptions"))
        conn.execute(text("DELETE FROM control.consents"))
        conn.execute(text("DELETE FROM control.users"))
        conn.execute(text("DELETE FROM control.tenants WHERE slug <> 'b2c'"))
        conn.execute(text("UPDATE control.tenants SET is_active = true WHERE slug = 'b2c'"))


class FakeStorage:
    """Doble de Supabase Storage: guarda en memoria lo que se sube."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.uploaded_from: list[str] = []
        self.signed: list[str] = []
        self.removed: list[str] = []
        self.fail = False
        self.fail_remove = False

    def upload_file(self, file_path: str, object_name: str, content_type: str) -> None:
        self.uploaded_from.append(file_path)
        if self.fail:
            raise StorageError
        with open(file_path, "rb") as f:
            self.objects[object_name] = f.read()

    def upload_bytes(self, object_name: str, data: bytes, content_type: str) -> None:
        if self.fail:
            raise StorageError
        self.objects[object_name] = data

    def remove_objects(self, object_names: list[str]) -> None:
        if self.fail_remove:
            raise StorageError
        for name in object_names:
            self.objects.pop(name, None)
        self.removed.extend(object_names)

    def create_signed_url(self, object_name: str, expires_in: int) -> str:
        self.signed.append(object_name)
        return f"https://storage.test/signed/{object_name}?expires_in={expires_in}"


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


DEMO_CARD = {
    "model_version": "fake-3c-1",
    "is_demo": True,
    "classes": ["normal", "benigno", "maligno"],
    "input_size": [224, 224],
    "color_mode": "rgb",
    "preprocessing": "raw_0_255",
    "files": {},
}


@pytest.fixture
def predictor() -> FakePredictor:
    """Predictor doble; cada prueba puede fijar `predictor.probabilities`."""
    return FakePredictor(
        ModelCard.from_dict(DEMO_CARD), {"normal": 0.9, "benigno": 0.07, "maligno": 0.03}
    )


@pytest.fixture
def inference(predictor) -> InferenceService:
    return InferenceService(predictor, MLSettings())


@pytest.fixture
def client(owner_engine, storage: FakeStorage, inference: InferenceService):
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_inference] = lambda: inference
    # IP de documentación (RFC 5737) para que la auditoría registre una IP válida
    with TestClient(app, client=("198.51.100.7", 50000)) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def b2c_tenant(owner_engine):
    with owner_engine.connect() as conn:
        row = conn.execute(text("SELECT id, slug FROM control.tenants WHERE slug = 'b2c'")).one()
    return row


@pytest.fixture
def tenant_factory(owner_engine):
    def create(slug: str, kind: str = "institucion", active: bool = True):
        return insert_tenant(owner_engine, slug, kind=kind, active=active)

    return create


@pytest.fixture
def user_factory(owner_engine):
    def create(
        tenant=None,
        role: str = "patient",
        email: str | None = None,
        active: bool = True,
    ) -> TestUser:
        return insert_user(owner_engine, tenant, role=role, email=email, active=active)

    return create
