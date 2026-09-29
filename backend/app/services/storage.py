import os
import shutil

# Backend de almacenamiento de imágenes.
#   STORAGE_BACKEND=local (por defecto) -> guarda en disco local de la EC2, bajo LOCAL_STORAGE_DIR.
#   STORAGE_BACKEND=s3                  -> sube a S3 (requiere credenciales/bucket reales por env vars).
STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "local")
LOCAL_STORAGE_DIR = os.environ.get("LOCAL_STORAGE_DIR", "uploads")
# Base pública desde la que Nginx sirve LOCAL_STORAGE_DIR (ver guía de despliegue), p.ej. "/uploads"
LOCAL_STORAGE_PUBLIC_BASE = os.environ.get("LOCAL_STORAGE_PUBLIC_BASE", "/uploads")


def _store_local(file_path: str, object_name: str) -> str:
    destination = os.path.join(LOCAL_STORAGE_DIR, object_name)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    shutil.copyfile(file_path, destination)
    return f"{LOCAL_STORAGE_PUBLIC_BASE.rstrip('/')}/{object_name}"


def _store_s3(file_path: str, object_name: str) -> str | None:
    import boto3
    from botocore.exceptions import NoCredentialsError

    bucket_name = os.environ["S3_BUCKET_NAME"]
    s3 = boto3.client(
        "s3",
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.environ.get("AWS_SESSION_TOKEN"),  # AWS Academy usa credenciales temporales con token
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
    )
    try:
        s3.upload_file(file_path, bucket_name, object_name)
        return f"https://{bucket_name}.s3.amazonaws.com/{object_name}"
    except NoCredentialsError:
        return None


def store_uploaded_file(file_path: str, object_name: str) -> str | None:
    """Guarda el archivo subido y devuelve la URL/ruta pública para persistir en la DB."""
    if STORAGE_BACKEND == "s3":
        return _store_s3(file_path, object_name)
    return _store_local(file_path, object_name)
