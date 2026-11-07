"""clinical.analysis_reviews: quien edita la revisión queda como su autora (CU-09)

La revisión (BI-RADS y recomendación de la médica) es una por análisis. Si otra doctora la
corrige (p. ej. tras un traspaso), `reviewed_by` debe pasar a ella: se concede UPDATE de esa
columna, pero una política RESTRICTIVE exige que el valor final sea la usuaria del contexto.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-06

"""

from collections.abc import Sequence

from alembic import op

from backend.migrations.rls import CURRENT_ROLE, CURRENT_USER, add_role_policy, app_role, grant_app

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    grant_app("analysis_reviews", "UPDATE (reviewed_by)")
    rule = f"{CURRENT_ROLE} = 'doctor' AND reviewed_by = {CURRENT_USER}"
    add_role_policy(
        "analysis_reviews",
        "analysis_reviews_author_on_update",
        f"{CURRENT_ROLE} = 'doctor'",
        command="UPDATE",
        with_check_sql=rule,
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS analysis_reviews_author_on_update ON clinical.analysis_reviews"
    )
    op.execute(f"REVOKE UPDATE (reviewed_by) ON clinical.analysis_reviews FROM {app_role()}")
