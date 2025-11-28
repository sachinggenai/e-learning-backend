"""refactor_template_definitions_dynamic_system

Refactors template_definitions table for Dynamic Template Runtime System.
Drops old schema and creates new schema with field_schema, render_config,
sanitize_rules, and scorm_behavior as JSON columns.

Seeds built-in templates: mcq, content-text, content-video, welcome, summary.

Revision ID: 397a10e6a5cb
Revises: b0c884a961c3
Create Date: 2025-11-27 18:11:15.306519

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import func
import json
import hashlib
from datetime import datetime

# revision identifiers, used by Alembic.
revision: str = '397a10e6a5cb'
down_revision: Union[str, Sequence[str], None] = 'b0c884a961c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - drop old table and create new dynamic schema."""
    # Drop old template_definitions table
    op.drop_index('ix_template_definitions_type_id', 'template_definitions')
    op.drop_table('template_definitions')
    
    # Create new template_definitions table with dynamic schema
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
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=func.now(),
            nullable=False
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=func.now(),
            nullable=False
        )
    )
    
    # Create indexes
    op.create_index('idx_type_key', 'template_definitions', ['type_key'])
    op.create_index(
        'idx_schema_sig', 'template_definitions', ['schema_signature']
    )
    op.create_index(
        'idx_type_version',
        'template_definitions',
        ['type_key', 'layout_version']
    )
    
    # Seed built-in template definitions
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__) + '/..')
    from seed_template_definitions import get_all_definitions
    
    definitions = get_all_definitions()
    for definition in definitions:
        op.execute(
            sa.text("""
                INSERT INTO template_definitions (
                    id, type_key, schema_signature,
                    field_schema_json, render_config_json,
                    sanitize_rules_json, scorm_behavior_json,
                    renderer_class, layout_version
                ) VALUES (
                    :id, :type_key, :schema_signature,
                    :field_schema_json, :render_config_json,
                    :sanitize_rules_json, :scorm_behavior_json,
                    :renderer_class, :layout_version
                )
            """).bindparams(
                **definition
            )
        )


def downgrade() -> None:
    """Downgrade schema - revert to old schema."""
    # Drop new table
    op.drop_index('idx_type_version', 'template_definitions')
    op.drop_index('idx_schema_sig', 'template_definitions')
    op.drop_index('idx_type_key', 'template_definitions')
    op.drop_table('template_definitions')
    
    # Recreate old table structure
    op.create_table(
        'template_definitions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('type_id', sa.String(length=50), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('schema_definition', sa.JSON(), nullable=False),
        sa.Column('render_template', sa.Text(), nullable=False),
        sa.Column('default_assets', sa.JSON(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'type_id', 'version', name='uq_template_type_version'
        )
    )
    op.create_index(
        op.f('ix_template_definitions_type_id'),
        'template_definitions',
        ['type_id'],
        unique=False
    )
