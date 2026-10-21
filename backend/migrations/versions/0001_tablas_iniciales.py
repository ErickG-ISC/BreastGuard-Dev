"""tablas iniciales: users y medical_images

Refleja el esquema que antes creaba Base.metadata.create_all desde /health. Es idempotente:
en bases donde esas tablas ya existen, no las vuelve a crear (basta con correr upgrade head).

Revision ID: 0001
Revises:
Create Date: 2026-10-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _existing_tables()

    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("email", sa.String(), nullable=True),
            sa.Column("hashed_password", sa.String(), nullable=True),
            sa.Column("full_name", sa.String(), nullable=True),
            sa.Column("is_medical", sa.Boolean(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_users_id", "users", ["id"])
        op.create_index("ix_users_email", "users", ["email"], unique=True)

    if "medical_images" not in tables:
        op.create_table(
            "medical_images",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("image_path", sa.String(), nullable=True),
            sa.Column("image_type", sa.String(), nullable=True),
            sa.Column("prediction", sa.String(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
        )
        op.create_index("ix_medical_images_id", "medical_images", ["id"])


def downgrade() -> None:
    tables = _existing_tables()
    if "medical_images" in tables:
        op.drop_table("medical_images")
    if "users" in tables:
        op.drop_table("users")
