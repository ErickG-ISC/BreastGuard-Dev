from sqlalchemy.orm import declarative_base

# Sin efectos secundarios: importarlo no lee variables de entorno ni crea engines
# (lo usan los modelos y backend/migrations/env.py).
Base = declarative_base()
