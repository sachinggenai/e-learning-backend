"""Add import_jobs, template_definitions, global_templates tables and schema_signature to templates

Revision ID: e8a7ce8be9ac
Revises: 397a10e6a5cb
Create Date: 2025-12-04 07:28:19.856646

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e8a7ce8be9ac'
down_revision: Union[str, Sequence[str], None] = '397a10e6a5cb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Drop existing template_definitions table and recreate with new schema
    # (since we're changing the structure significantly for Phase 0)
    op.drop_table('template_definitions')

    # Create new template_definitions table
    op.create_table('template_definitions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('template_type', sa.String(length=100), nullable=False),
        sa.Column('display_name', sa.String(length=200), nullable=False),
        sa.Column('schema_signature', sa.String(length=64), nullable=False),
        sa.Column('render_template_html', sa.Text(), nullable=False),
        sa.Column('schema_json', sa.JSON(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_template_definitions_schema_signature'), 'template_definitions', ['schema_signature'], unique=False)
    op.create_index(op.f('ix_template_definitions_template_type'), 'template_definitions', ['template_type'], unique=True)

    # Create import_jobs table
    op.create_table('import_jobs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('job_id', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('progress', sa.Float(), nullable=False),
        sa.Column('course_id', sa.String(length=64), nullable=True),
        sa.Column('source_file_path', sa.String(length=500), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('result_data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_import_jobs_job_id'), 'import_jobs', ['job_id'], unique=True)

    # Create global_templates table
    op.create_table('global_templates',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('global_template_id', sa.String(length=64), nullable=False),
        sa.Column('template_type', sa.String(length=100), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('json_data', sa.JSON(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('is_published', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_global_templates_global_template_id'), 'global_templates', ['global_template_id'], unique=True)
    op.create_index(op.f('ix_global_templates_template_type'), 'global_templates', ['template_type'], unique=False)

    # Add schema_signature column to templates table
    op.add_column('templates', sa.Column('schema_signature', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_templates_schema_signature'), 'templates', ['schema_signature'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Remove the new tables and column
    op.drop_table('global_templates')
    op.drop_table('import_jobs')
    op.drop_table('template_definitions')

    # Remove schema_signature column from templates
    op.drop_index(op.f('ix_templates_schema_signature'), table_name='templates')
    op.drop_column('templates', 'schema_signature')

    # Recreate the old template_definitions table (from previous migration)
    op.create_table(
        'template_definitions',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('type_key', sa.String(50), unique=True, nullable=False),
        sa.Column('schema_signature', sa.String(64), nullable=False),
        sa.Column('field_schema_json', sa.Text(), nullable=False),
        sa.Column('render_config_json', sa.Text(), nullable=False),
        sa.Column('sanitize_rules_json', sa.Text(), nullable=False),
        sa.Column('scorm_behavior_json', sa.Text(), nullable=False),
        sa.Column('renderer_class', sa.String(200), nullable=False),
        sa.Column('layout_version', sa.Integer(), default=1, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False)
    )
    op.create_index('idx_schema_sig', 'template_definitions', ['schema_signature'], unique=False)
    op.create_index('idx_type_key', 'template_definitions', ['type_key'], unique=False)
    op.create_index('idx_type_version', 'template_definitions', ['type_key', 'layout_version'], unique=False)