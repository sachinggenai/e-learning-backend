"""add templates table

Revision ID: 20251007_0002
Revises: 20251007_0001
Create Date: 2025-10-07
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20251007_0002"
down_revision = "20251007_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "templates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "course_id",
            sa.Integer(),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        sa.Column(
            "template_uid",
            sa.String(length=100),
            index=True,
            nullable=False,
        ),
        sa.Column("template_type", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("json_data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_templates_course_order",
        "templates",
        ["course_id", "order_index"],
    )
    op.create_index(
        "ix_templates_course_templateuid",
        "templates",
        ["course_id", "template_uid"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_templates_course_templateuid", table_name="templates")
    op.drop_index("ix_templates_course_order", table_name="templates")
    op.drop_table("templates")
