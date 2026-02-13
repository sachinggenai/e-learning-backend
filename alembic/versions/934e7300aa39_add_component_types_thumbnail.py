"""add component_types thumbnail

Revision ID: 934e7300aa39
Revises: 759356cfebd6
Create Date: 2026-02-09 13:05:56.188055

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '934e7300aa39'
down_revision: Union[str, Sequence[str], None] = '759356cfebd6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "component_types",
        sa.Column("thumbnail", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("component_types", "thumbnail")
