"""Create workflow engine tables — US-BKND-AI-034

Revision ID: 20260620_0002
Revises: 20260620_0001
Create Date: 2026-06-20

Creates:
    - workflow_type_definitions
    - workflow_jobs (CHECK constraints, partial indexes, FK to ai_sessions)
    - workflow_job_events (FK CASCADE to workflow_jobs)
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "20260620_0002"
down_revision: Union[str, None] = "20260620_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── workflow_type_definitions ────────────────────────────
    op.create_table(
        "workflow_type_definitions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workflow_type", sa.String(64), nullable=False, unique=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), server_default=""),
        sa.Column("input_schema", JSONB(), nullable=False),
        sa.Column("state_machine", JSONB(), nullable=False),
        sa.Column("output_schema", JSONB(), nullable=True),
        sa.Column("max_duration_seconds", sa.Integer(), nullable=False, server_default="86400"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_wf_type_def_active", "workflow_type_definitions", ["workflow_type"],
                    postgresql_where=sa.text("is_active = TRUE"))

    # ── workflow_jobs ────────────────────────────────────────
    op.create_table(
        "workflow_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", UUID(), nullable=False, unique=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("workflow_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("current_state", sa.String(128), nullable=False, server_default="validate_input"),
        sa.Column("previous_state", sa.String(128), nullable=True),
        sa.Column("input", JSONB(), nullable=False),
        sa.Column("result", JSONB(), nullable=True),
        sa.Column("error", JSONB(), nullable=True),
        sa.Column("checkpoint_data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("progress", sa.REAL(), nullable=False, server_default="0.0"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("current_retry_state", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(64), nullable=True),
        sa.Column("webhook_url", sa.String(1024), nullable=True),
        sa.Column("webhook_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_user_id", sa.String(64), nullable=True),
        sa.Column("session_id", UUID(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True),
                  server_default=sa.text("(NOW() + INTERVAL '24 hours')")),
    )
    # CHECK constraints
    op.create_check_constraint(
        "ck_wf_jobs_status", "workflow_jobs",
        sa.text("status IN ('pending','running','paused','complete','failed','cancelled')")
    )
    op.create_check_constraint(
        "ck_wf_jobs_progress", "workflow_jobs",
        sa.text("progress >= 0.0 AND progress <= 1.0")
    )
    # Partial indexes
    op.create_index("idx_wf_jobs_status", "workflow_jobs", ["status"],
                    postgresql_where=sa.text("status IN ('pending','running')"))
    op.create_index("idx_wf_jobs_type_status", "workflow_jobs", ["workflow_type", "status"])
    op.create_index("idx_wf_jobs_locked_by", "workflow_jobs", ["locked_by"],
                    postgresql_where=sa.text("locked_by IS NOT NULL"))
    op.create_index("idx_wf_jobs_heartbeat", "workflow_jobs", ["heartbeat_at"],
                    postgresql_where=sa.text("status = 'running'"))
    op.create_index("idx_wf_jobs_created", "workflow_jobs",
                    [sa.text("created_at DESC")])
    op.create_index("idx_wf_jobs_expires", "workflow_jobs", ["expires_at"],
                    postgresql_where=sa.text("status NOT IN ('complete','cancelled')"))
    # Foreign keys
    op.create_foreign_key("fk_wf_jobs_type", "workflow_jobs",
                          "workflow_type_definitions", ["workflow_type"], ["workflow_type"])
    # Conditional FK — ai_sessions may not exist yet (created via Base.metadata.create_all)
    conn = op.get_bind()
    ai_sessions_exists = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = 'ai_sessions'")
    ).scalar()
    if ai_sessions_exists:
        op.create_foreign_key("fk_wf_jobs_session", "workflow_jobs",
                              "ai_sessions", ["session_id"], ["id"], ondelete="SET NULL")

    # ── workflow_job_events ──────────────────────────────────
    op.create_table(
        "workflow_job_events",
        sa.Column("id", sa.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column("job_id", UUID(), nullable=False),
        sa.Column("state", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_wf_events_job", "workflow_job_events", ["job_id", "timestamp"])
    op.create_index("idx_wf_events_type", "workflow_job_events", ["event_type"])
    op.create_foreign_key("fk_wf_events_job", "workflow_job_events",
                          "workflow_jobs", ["job_id"], ["job_id"], ondelete="CASCADE")


def downgrade() -> None:
    op.drop_table("workflow_job_events")
    op.drop_table("workflow_jobs")
    op.drop_table("workflow_type_definitions")
