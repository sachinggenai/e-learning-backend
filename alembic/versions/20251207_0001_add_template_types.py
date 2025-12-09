"""Add template_types table

Revision ID: 20251207_0001
Revises: 20251007_0002
Create Date: 2025-12-07
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20251207_0001'
down_revision = '20251007_0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create template_types table for builtin template definitions."""
    op.create_table(
        'template_types',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            'template_id',
            sa.String(length=100),
            nullable=False,
            unique=True,
        ),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('category', sa.String(length=100), nullable=False),
        sa.Column('thumbnail', sa.String(length=500), nullable=True),
        sa.Column('estimated_duration', sa.Integer(), nullable=True),
        sa.Column('rating', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column(
            'usage_count',
            sa.Integer(),
            nullable=False,
            server_default='0',
        ),
        sa.Column(
            'can_be_page',
            sa.Boolean(),
            nullable=False,
            server_default='true',
        ),
        sa.Column('fields', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column(
            'is_active',
            sa.Boolean(),
            nullable=False,
            server_default='true',
        ),
        sa.Column(
            'created_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
        ),
    )
    # Create indexes
    op.create_index(
        'ix_template_types_template_id',
        'template_types',
        ['template_id'],
        unique=True,
    )
    op.create_index(
        'ix_template_types_category',
        'template_types',
        ['category'],
    )


def downgrade() -> None:
    """Drop template_types table."""
    op.drop_index('ix_template_types_category', table_name='template_types')
    op.drop_index('ix_template_types_template_id', table_name='template_types')
    op.drop_table('template_types')
