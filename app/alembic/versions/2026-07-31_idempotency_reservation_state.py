"""Add reservation state to idempotency records.

Revision ID: b2c3d4e5f607
Revises: a1b2c3d4e5f6
Create Date: 2026-07-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f607"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "SYS_IDEMPOTENCY_KEY",
        sa.Column(
            "IDK_Estado",
            sa.String(length=16),
            nullable=False,
            server_default="COMPLETED",
        ),
    )


def downgrade() -> None:
    op.drop_column("SYS_IDEMPOTENCY_KEY", "IDK_Estado")
