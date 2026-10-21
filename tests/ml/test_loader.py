"""Cargador del modelo: nombres fijos, huellas obligatorias y descarga atómica."""

import hashlib
import json

import pytest

from backend.app.ml import loader
from backend.app.ml.loader import ModelUnavailableError, ensure_model_files
from backend.app.ml.settings import MLSettings

GOOD = {"model.tflite": b"modelo-falso", "head.npz": b"pesos-falsos"}


def card(files: dict[str, bytes] | None = None, listed: dict | None = None) -> bytes:
    files = GOOD if files is None else files
    data = {
        "model_version": "fake",
        "classes": ["normal", "benigno", "maligno"],
        "input_size": [224, 224],
        "preprocessing": "raw_0_255",
        "files": listed
        if listed is not None
        else {name: hashlib.sha256(content).hexdigest() for name, content in files.items()},
    }
    return json.dumps(data).encode()


def write_local(directory, files=GOOD, card_bytes=None):
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (directory / name).write_bytes(content)
    (directory / "model_card.json").write_bytes(card_bytes or card(files))


class FakeBucket:
    def __init__(self, objects: dict[str, bytes], fail_on: str | None = None) -> None:
        self.objects = objects
        self.fail_on = fail_on
        self.requested: list[str] = []

    def download(self, path: str) -> bytes:
        self.requested.append(path)
        if self.fail_on and path.endswith(self.fail_on):
            raise ConnectionError("descarga cortada")
        return self.objects[path]


@pytest.fixture
def bucket(monkeypatch):
    holder = {}

    class Client:
        class storage:  # noqa: N801
            @staticmethod
            def from_(name):
                return holder["bucket"]

    def install(fake: FakeBucket) -> FakeBucket:
        holder["bucket"] = fake
        return fake

    monkeypatch.setattr("backend.app.services.storage._get_client", lambda: Client)
    return install


def remote(card_bytes=None, files=GOOD, prefix="demo-1"):
    objects = {f"{prefix}/{name}": content for name, content in files.items()}
    objects[f"{prefix}/model_card.json"] = card_bytes or card(files)
    return objects


def settings(tmp_path, **kwargs):
    return MLSettings(model_dir=str(tmp_path / "model"), model_prefix="demo-1", **kwargs)


def test_archivos_locales_integros_no_descargan(tmp_path, bucket):
    write_local(tmp_path / "model")
    fake = bucket(FakeBucket({}))
    assert ensure_model_files(settings(tmp_path)) == tmp_path / "model"
    assert fake.requested == []


def test_descarga_verifica_y_deja_los_archivos(tmp_path, bucket):
    fake = bucket(FakeBucket(remote()))
    model_dir = ensure_model_files(settings(tmp_path))
    assert sorted(p.name for p in model_dir.iterdir()) == [
        "head.npz",
        "model.tflite",
        "model_card.json",
    ]
    assert len(fake.requested) == 3


def test_archivo_alterado_en_el_bucket_se_rechaza(tmp_path, bucket):
    tampered = {**GOOD, "model.tflite": b"otro-modelo"}
    bucket(FakeBucket(remote(card_bytes=card(GOOD), files=tampered)))
    with pytest.raises(ModelUnavailableError, match="alterado"):
        ensure_model_files(settings(tmp_path))
    assert not (tmp_path / "model").exists()


@pytest.mark.parametrize(
    "listed",
    [
        {},
        {"model.tflite": hashlib.sha256(GOOD["model.tflite"]).hexdigest()},
        {"../../evil.py": "0" * 64, "model.tflite": "0" * 64, "head.npz": "0" * 64},
        {"/abs/evil": "0" * 64},
    ],
)
def test_ficha_sin_los_archivos_exactos_se_rechaza(tmp_path, bucket, listed):
    bucket(FakeBucket(remote(card_bytes=card(listed=listed))))
    with pytest.raises(ModelUnavailableError):
        ensure_model_files(settings(tmp_path))
    # Nada se escribió fuera de la carpeta del modelo
    assert not (tmp_path / "evil.py").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == []


def test_huella_con_formato_invalido(tmp_path, bucket):
    listed = {"model.tflite": "ABC", "head.npz": "0" * 64}
    bucket(FakeBucket(remote(card_bytes=card(listed=listed))))
    with pytest.raises(ModelUnavailableError):
        ensure_model_files(settings(tmp_path))


def test_descarga_cortada_no_deja_archivos_a_medias(tmp_path, bucket):
    bucket(FakeBucket(remote(), fail_on="head.npz"))
    with pytest.raises(ConnectionError):
        ensure_model_files(settings(tmp_path))
    assert sorted(p.name for p in tmp_path.iterdir()) == []


def test_ficha_fijada_por_variable_de_entorno(tmp_path, bucket, monkeypatch):
    write_local(tmp_path / "model")
    bucket(FakeBucket(remote()))
    monkeypatch.setenv("MODEL_CARD_SHA256", "0" * 64)
    with pytest.raises(ModelUnavailableError, match="MODEL_CARD_SHA256"):
        ensure_model_files(settings(tmp_path))
    good = hashlib.sha256((tmp_path / "model" / "model_card.json").read_bytes()).hexdigest()
    monkeypatch.setenv("MODEL_CARD_SHA256", good)
    assert ensure_model_files(settings(tmp_path)) == tmp_path / "model"


def test_prefijo_invalido(tmp_path, bucket):
    bucket(FakeBucket({}))
    with pytest.raises(ModelUnavailableError, match="MODEL_PREFIX"):
        ensure_model_files(MLSettings(model_dir=str(tmp_path / "m"), model_prefix="../x"))


def test_nombres_fijos():
    assert loader.REQUIRED_FILES == ("model.tflite", "head.npz")
