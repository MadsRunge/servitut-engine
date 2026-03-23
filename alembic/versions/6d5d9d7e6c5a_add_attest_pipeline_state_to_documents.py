"""add attest pipeline state to documents

Revision ID: 6d5d9d7e6c5a
Revises: acc4f85bdef2
Create Date: 2026-03-23 21:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "6d5d9d7e6c5a"
down_revision: Union[str, Sequence[str], None] = "acc4f85bdef2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "documents",
        sa.Column(
            "attest_pipeline_state",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("documents", "attest_pipeline_state")
