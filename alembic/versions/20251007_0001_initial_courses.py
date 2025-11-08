"""initial courses table

Revision ID: 20251007_0001
Revises:
Create Date: 2025-10-07
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20251007_0001'
down_revision = None
branch_labels = None
depends_on = None

 
def upgrade() -> None:
    op.create_table(
        'courses',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column(
            'course_id', sa.String(length=64), nullable=False, unique=True
        ),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column(
            'status', sa.String(length=32), nullable=False,
            server_default='draft'
        ),
        sa.Column('json_data', sa.JSON(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(),
            server_default=sa.text('CURRENT_TIMESTAMP')
        ),
        sa.Column(
            'updated_at', sa.DateTime(),
            server_default=sa.text('CURRENT_TIMESTAMP')
        ),
    )
    op.create_index(
        'ix_courses_course_id', 'courses', ['course_id'], unique=True
    )

 
def downgrade() -> None:
    op.drop_index('ix_courses_course_id', table_name='courses')
    op.drop_table('courses')
