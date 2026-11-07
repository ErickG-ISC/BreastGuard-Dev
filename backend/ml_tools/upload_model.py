"""Sube un modelo exportado al bucket PRIVADO de modelos (lo crea privado si no existe).

Uso, desde la raíz del repo (lee SUPABASE_URL y SUPABASE_KEY del .env):
    python -m backend.ml_tools.upload_model --model-dir C:/ruta/demo-model
Sube model_card.json y los archivos que lista la ficha bajo {MODEL_BUCKET}/{model_version}/.

Antes de subir valida la ficha y los sha256 IGUAL que el servidor (`loader._verify`), y se niega a
sobrescribir una versión que ya está en el bucket: un análisis guardado con esa versión debe
seguir significando el mismo modelo (ADR 0014). Para un modelo distinto, usa otra model_version.
"""

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model-dir", type=Path, required=True)
    args = parser.parse_args()

    from supabase import create_client

    bucket_name = os.environ.get("MODEL_BUCKET", "ml-models")
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    existing = {b.name: b for b in client.storage.list_buckets()}
    if bucket_name not in existing:
        client.storage.create_bucket(bucket_name, options={"public": False})
        print(f"Bucket {bucket_name!r} creado como privado")
    elif existing[bucket_name].public:
        raise SystemExit(f"El bucket {bucket_name!r} es PÚBLICO: hazlo privado antes de subir")

    from backend.app.ml.loader import _verify

    _verify(args.model_dir)  # ficha v2 y sha256; lanza si algo no cuadra
    card = json.loads((args.model_dir / "model_card.json").read_text(encoding="utf-8"))
    prefix = card["model_version"]
    bucket = client.storage.from_(bucket_name)
    if bucket.list(prefix):
        raise SystemExit(
            f"La versión {prefix!r} ya existe en el bucket: no se sobrescribe. "
            "Usa otra model_version para un modelo distinto."
        )
    for name in ["model_card.json", *card["files"]]:
        data = (args.model_dir / name).read_bytes()
        bucket.upload(
            f"{prefix}/{name}",
            data,
            {"content-type": "application/octet-stream", "upsert": "false"},
        )
        print(f"Subido {prefix}/{name} ({len(data) // 1024} KB)")
    print(f"Listo. En la app: MODEL_BUCKET={bucket_name} MODEL_PREFIX={prefix}")


if __name__ == "__main__":
    main()
