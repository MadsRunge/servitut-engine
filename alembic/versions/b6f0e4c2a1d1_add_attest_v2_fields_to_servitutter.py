"""add attest v2 fields to servitutter

Revision ID: b6f0e4c2a1d1
Revises: 6d5d9d7e6c5a
Create Date: 2026-03-24 13:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b6f0e4c2a1d1"
down_revision: Union[str, Sequence[str], None] = "6d5d9d7e6c5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("servitutter", sa.Column("status", sa.String(), nullable=False, server_default="ukendt"))
    op.add_column("servitutter", sa.Column("scope_type", sa.String(), nullable=True))
    op.add_column("servitutter", sa.Column("is_fanout_entry", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("servitutter", sa.Column("declaration_block_id", sa.String(), nullable=True))
    op.alter_column("servitutter", "status", server_default=None)
    op.alter_column("servitutter", "is_fanout_entry", server_default=None)


def downgrade() -> None:
    op.drop_column("servitutter", "declaration_block_id")
    op.drop_column("servitutter", "is_fanout_entry")
    op.drop_column("servitutter", "scope_type")
    op.drop_column("servitutter", "status")
