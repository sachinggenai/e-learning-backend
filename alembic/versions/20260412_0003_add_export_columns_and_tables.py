"""Add export persistence columns/tables for courses/templates.

Revision ID: 20260412_0003
Revises: 934e7300aa39
Create Date: 2026-04-12 22:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260412_0003"
down_revision: Union[str, None] = "934e7300aa39"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Courses: export-friendly theme/style persistence.
    op.execute("ALTER TABLE courses ADD COLUMN IF NOT EXISTS theme_json JSONB")
    op.execute("ALTER TABLE courses ADD COLUMN IF NOT EXISTS custom_css TEXT")

    # Templates: page/component style persistence.
    op.execute("ALTER TABLE templates ADD COLUMN IF NOT EXISTS style_json JSONB")
    op.execute("ALTER TABLE templates ADD COLUMN IF NOT EXISTS custom_css TEXT")

    # Component-level style table.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS component_styles (
            id SERIAL PRIMARY KEY,
            template_id INTEGER NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
            component_id VARCHAR(100) NOT NULL,
            style_config JSONB,
            custom_css TEXT,
            export_metadata JSONB,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
            updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_component_styles_template_id ON component_styles (template_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_component_styles_component_id ON component_styles (component_id)"
    )

    # Export asset linkage table.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS export_assets (
            id SERIAL PRIMARY KEY,
            asset_id VARCHAR(100) NOT NULL UNIQUE,
            course_id INTEGER REFERENCES courses(id) ON DELETE CASCADE,
            template_id INTEGER REFERENCES templates(id) ON DELETE CASCADE,
            filename VARCHAR(500) NOT NULL,
            file_path VARCHAR(1000) NOT NULL,
            mime_type VARCHAR(100) NOT NULL,
            file_size INTEGER NOT NULL,
            asset_type VARCHAR(32) NOT NULL,
            file_hash VARCHAR(64),
            export_filename VARCHAR(500),
            is_exported BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
            updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_export_assets_course_id ON export_assets (course_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_export_assets_template_id ON export_assets (template_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_export_assets_asset_id ON export_assets (asset_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_export_assets_file_hash ON export_assets (file_hash)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_export_assets_file_hash")
    op.execute("DROP INDEX IF EXISTS ix_export_assets_asset_id")
    op.execute("DROP INDEX IF EXISTS ix_export_assets_template_id")
    op.execute("DROP INDEX IF EXISTS ix_export_assets_course_id")
    op.execute("DROP TABLE IF EXISTS export_assets")

    op.execute("DROP INDEX IF EXISTS ix_component_styles_component_id")
    op.execute("DROP INDEX IF EXISTS ix_component_styles_template_id")
    op.execute("DROP TABLE IF EXISTS component_styles")

    op.execute("ALTER TABLE templates DROP COLUMN IF EXISTS custom_css")
    op.execute("ALTER TABLE templates DROP COLUMN IF EXISTS style_json")

    op.execute("ALTER TABLE courses DROP COLUMN IF EXISTS custom_css")
    op.execute("ALTER TABLE courses DROP COLUMN IF EXISTS theme_json")
