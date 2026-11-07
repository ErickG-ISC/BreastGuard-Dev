"""app_user puede LEER public.alembic_version (solo eso): /health compara la revisión de la base
con la del código y responde 503 si la base está atrasada (migrar antes de desplegar, ADR 0016)

Los roles de la Data API de Supabase siguen sin acceso a esa tabla (revoke_supabase_api_roles).

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-07

"""

from collections.abc import Sequence

from alembic import op

from backend.migrations.rls import app_role, revoke_supabase_api_roles

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(f"GRANT SELECT ON TABLE public.alembic_version TO {app_role()}")
    revoke_supabase_api_roles()


def downgrade() -> None:
    op.execute(f"REVOKE SELECT ON TABLE public.alembic_version FROM {app_role()}")
