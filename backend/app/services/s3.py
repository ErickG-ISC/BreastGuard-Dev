import boto3
from botocore.exceptions import NoCredentialsError

s3 = boto3.client(
    's3',
    aws_access_key_id='TU_ACCESS_KEY',
    aws_secret_access_key='TU_SECRET_KEY',
    region_name='us-east-1'
)

BUCKET_NAME = "breast-cancer-images-tu-id"

def upload_file_to_s3(file_path, object_name):
    try:
        s3.upload_file(file_path, BUCKET_NAME, object_name)
        return f"https://{BUCKET_NAME}.s3.amazonaws.com/{object_name}"
    except NoCredentialsError:
        return None
