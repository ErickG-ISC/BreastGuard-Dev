import os

from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "medical-images")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def upload_file_to_storage(file_path, object_name):
    try:
        with open(file_path, "rb") as f:
            supabase.storage.from_(SUPABASE_BUCKET).upload(object_name, f)
    except Exception:
        return None
    return supabase.storage.from_(SUPABASE_BUCKET).get_public_url(object_name)
