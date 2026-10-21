import os

# Variables ficticias ANTES de importar la app: las pruebas nunca usan .env ni servicios reales.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SECRET_KEY"] = "clave-solo-para-pruebas"
os.environ["SUPABASE_URL"] = "http://localhost:54321"
os.environ["SUPABASE_KEY"] = "clave-falsa"
os.environ["SUPABASE_BUCKET"] = "bucket-de-prueba"
