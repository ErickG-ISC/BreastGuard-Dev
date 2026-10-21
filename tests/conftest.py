import os

# Variables ficticias ANTES de importar la app: las pruebas nunca usan .env ni servicios reales.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SECRET_KEY"] = "clave-solo-para-pruebas"
os.environ["SUPABASE_URL"] = "http://localhost:54321"
os.environ["SUPABASE_KEY"] = "clave-falsa"
os.environ["SUPABASE_BUCKET"] = "bucket-de-prueba"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.app.api.deps import get_db, get_storage  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.models.base import Base  # noqa: E402
from backend.app.models.user import User  # noqa: E402
from backend.app.services.auth import get_password_hash  # noqa: E402
from backend.app.services.storage import StorageError  # noqa: E402
from tests.helpers import DEFAULT_PASSWORD  # noqa: E402


class FakeStorage:
    """Doble de Supabase Storage: guarda en memoria lo que se sube."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.uploaded_from: list[str] = []
        self.fail = False

    def upload_file(self, file_path: str, object_name: str, content_type: str) -> str:
        self.uploaded_from.append(file_path)
        if self.fail:
            raise StorageError
        with open(file_path, "rb") as f:
            self.objects[object_name] = f.read()
        return f"https://storage.test/{object_name}"


@pytest.fixture
def db_session():
    # Base SQLite en memoria, nueva y aislada por prueba
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False)
    session = testing_session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def client(db_session: Session, storage: FakeStorage):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_storage] = lambda: storage
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def user_factory(db_session: Session):
    def create(email: str = "paciente@example.com", password: str = DEFAULT_PASSWORD) -> User:
        user = User(
            email=email,
            hashed_password=get_password_hash(password),
            full_name="Paciente de prueba",
            is_medical=False,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user

    return create
