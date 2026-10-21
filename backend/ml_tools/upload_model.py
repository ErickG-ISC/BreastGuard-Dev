"""Sube un modelo exportado al bucket PRIVADO de modelos (lo crea privado si no existe).

Uso, desde la raíz del repo (lee SUPABASE_URL y SUPABASE_KEY del .env):
    python -m backend.ml_tools.upload_model --model-dir C:/ruta/demo-model
Sube model_card.json y los archivos que lista la ficha bajo {MODEL_BUCKET}/{model_version}/.
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

    card = json.loads((args.model_dir / "model_card.json").read_text(encoding="utf-8"))
    prefix = card["model_version"]
    bucket = client.storage.from_(bucket_name)
    for name in ["model_card.json", *card["files"]]:
        data = (args.model_dir / name).read_bytes()
        bucket.upload(
            f"{prefix}/{name}", data, {"content-type": "application/octet-stream", "upsert": "true"}
        )
        print(f"Subido {prefix}/{name} ({len(data) // 1024} KB)")
    print(f"Listo. En la app: MODEL_BUCKET={bucket_name} MODEL_PREFIX={prefix}")


if __name__ == "__main__":
    main()
