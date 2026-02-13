"""Add component_types, pages, components, themes, course_scoring tables.

Revision ID: 20250101_0002
Revises: merge_001
Create Date: 2025-01-01 00:01:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20250101_0002"
down_revision: Union[str, None] = "merge_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── component_types ──────────────────────
    op.create_table(
        "component_types",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("type_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("category", sa.String(64), nullable=False, index=True),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.String(64), nullable=True),
        sa.Column("scoring_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("max_score", sa.Integer(), nullable=True),
        sa.Column("scoring_rules", sa.JSON(), nullable=True),
        sa.Column("completion_capabilities", sa.JSON(), nullable=True),
        sa.Column("default_completion_type", sa.String(32), nullable=True),
        sa.Column("audio_support", sa.JSON(), nullable=True),
        sa.Column("schema", sa.JSON(), nullable=True),
        sa.Column("default_data", sa.JSON(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("estimated_duration", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # ── pages ────────────────────────────────
    op.create_table(
        "pages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("page_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.course_id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("layout", sa.JSON(), nullable=True),
        sa.Column("theme_config", sa.JSON(), nullable=True),
        sa.Column("completion_config", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # ── components ───────────────────────────
    op.create_table(
        "components",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("component_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("page_id", sa.String(64), sa.ForeignKey("pages.page_id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("component_type", sa.String(64), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("audio_config", sa.JSON(), nullable=True),
        sa.Column("completion_criteria", sa.JSON(), nullable=True),
        sa.Column("styling", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # ── themes ───────────────────────────────
    op.create_table(
        "themes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("theme_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("is_preset", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("colors", sa.JSON(), nullable=True),
        sa.Column("typography", sa.JSON(), nullable=True),
        sa.Column("component_styles", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # ── course_scoring ───────────────────────
    op.create_table(
        "course_scoring",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scoring_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.course_id", ondelete="CASCADE"), nullable=False, unique=True, index=True),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("component_scores", sa.JSON(), nullable=True),
        sa.Column("scorm_reporting", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("course_scoring")
    op.drop_table("themes")
    op.drop_table("components")
    op.drop_table("pages")
    op.drop_table("component_types")
