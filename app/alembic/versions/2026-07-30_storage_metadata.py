"""storage metadata for local/S3-compatible attachments

Revision ID: a1b2c3d4e5f6
Revises: f0a1b2c3d4e5
Create Date: 2026-07-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "INV_ADJUNTO",
        sa.Column(
            "ADJ_Storage_Backend",
            sa.String(length=20),
            nullable=False,
            server_default="local",
        ),
    )
    op.add_column(
        "INV_ADJUNTO", sa.Column("ADJ_Bucket", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "INV_ADJUNTO", sa.Column("ADJ_Object_Key", sa.String(length=1024), nullable=True)
    )
    op.add_column(
        "INV_ADJUNTO",
        sa.Column("ADJ_Checksum_SHA256", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("INV_ADJUNTO", "ADJ_Checksum_SHA256")
    op.drop_column("INV_ADJUNTO", "ADJ_Object_Key")
    op.drop_column("INV_ADJUNTO", "ADJ_Bucket")
    op.drop_column("INV_ADJUNTO", "ADJ_Storage_Backend")
