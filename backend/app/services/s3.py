import os

import boto3
from botocore.exceptions import NoCredentialsError

s3 = boto3.client(
    's3',
    aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    region_name=os.environ.get("AWS_REGION", "us-east-1"),
)

BUCKET_NAME = os.environ["S3_BUCKET_NAME"]

def upload_file_to_s3(file_path, object_name):
    try:
        s3.upload_file(file_path, BUCKET_NAME, object_name)
        return f"https://{BUCKET_NAME}.s3.amazonaws.com/{object_name}"
    except NoCredentialsError:
        return None
