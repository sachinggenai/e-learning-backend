"""Merge heads e8a7ce8be9ac and 20251207_0001.

Revision ID: merge_001
Revises: e8a7ce8be9ac, 20251207_0001
Create Date: 2025-01-01 00:00:00.000000
"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "merge_001"
down_revision: Union[str, Sequence[str]] = ("e8a7ce8be9ac", "20251207_0001")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
