# US-AI-034: Durable Workflow Engine for Long-Running AI Jobs

**Status:** Draft  
**Priority:** MUST (MVP)  
**Depends on:** US-AI-002 (Feature Flags), US-AI-003 (Isolated AI Module), US-AI-006 (AI Sessions), US-AI-019 (Course Generation), US-AI-023 (AI Chat Endpoint), US-AI-026 (Observability Foundation)  
**Epic Owner:** Technical Product Owner  

---

## 1. Functional Specification

### 1.1 User Story

As an **Author**, I want to initiate long-running AI operations (course generation, batch content repair, large-course SCORM export) and walk away while the system reliably completes the work, so that I am not blocked by synchronous timeouts and can monitor progress asynchronously.

As a **Platform Operator**, I want a durable workflow engine that survives process restarts, tracks every step with retry logic, emits observability telemetry, and provides manual recovery knobs, so that production AI jobs never silently fail or lose state.

### 1.2 Overview

The e-learning backend currently handles AI operations and SCORM export synchronously inside HTTP request-response cycles. This breaks under real-world conditions: generating a 50-page course with an LLM takes 5–15 minutes; exporting a 200-asset SCORM package can take 2+ minutes. HTTP gateways (Render, Cloudflare, load balancers) timeout after 30–60 seconds, causing mid-job failures with no recovery path.

This user story introduces a **durable workflow engine** — a state-machine-based background worker that:

1. **Accepts** a job request via REST and returns a `job_id` immediately (HTTP 202).
2. **Persists** the full job state (input, step progress, intermediate results, error history) in PostgreSQL.
3. **Executes** steps in a configurable state machine with automatic retries, dead-letter states, and timeout enforcement.
4. **Emits** structured telemetry (logs, metrics, optional OpenTelemetry spans) at every state transition.
5. **Survives** process restarts: on boot, the engine reaps any `running` or `pending` jobs and restarts them from their last checkpoint.
6. **Exposes** poll-and-webhook status so the frontend can show real-time progress bars and detail views.

**Job classes covered by this epic:**

| Job Type | Scope | Typical Duration | LLM Calls |
|---|---|---|---|
| `course_generation` | Generate all pages for a course from an approved page plan | 2–15 min | 1 per page + validation |
| `batch_content_repair` | Repair validation errors across N pages | 30 s – 5 min | 1 per broken page per retry |
| `scorm_export` | Build a SCORM package for a persisted course | 10 s – 3 min | 0 (CPU/IO only) |
| `ai_session_tool_batch` | Execute a batch of AI tool calls (e.g., apply N proposals) | 5 s – 1 min | 0–1 |

**Relation to existing ImportJob:** The existing `ImportJob` model (`app/models/persisted_course.py`) tracks SCORM import progress but lacks a proper state machine, retry logic, checkpointing, and telemetry. The new `WorkflowJob` model replaces it as the canonical durable job record. Import jobs are migrated to the new engine in a follow-up story.

### 1.3 Actors

| Actor | Role |
|---|---|
| Author (User) | Initiates jobs via frontend; polls `GET /api/v1/workflows/{job_id}` for status |
| WorkflowOrchestrator | Background loop that picks up pending jobs, advances state machines, handles retries and timeouts |
| Step Executor (Function) | Individual Python async function (`app/services/workflow/steps/*.py`) that performs one unit of work |
| Frontend | Shows job progress via polling; displays detailed error views; supports manual retry/cancel |
| Platform Operator | Monitors dead-letter queue via admin API; manually retries or terminates stuck jobs |
| DB (PostgreSQL) | Stores all job state, checkpoints, heartbeat timestamps |

### 1.4 Flow: Long-Running Course Generation Job

**Precondition:** User has approved a page plan (US-AI-017). The import job has status `plan_approved` with a `pages[]` array.

**Phase 0 — Initiate Job**
1. Frontend calls `POST /api/v1/workflows` with `{workflow_type: "course_generation", input: {import_job_id, course_id (optional), generation_options}}`.
2. Backend validates the input schema for `course_generation` workflow type.
3. WorkflowOrchestrator creates a `WorkflowJob` row (status: `pending`).
4. Returns HTTP 202 with `{job_id, status: "pending", polling_url: "/api/v1/workflows/{job_id}"}`.
5. Frontend begins polling `GET /api/v1/workflows/{job_id}` every 2 seconds.

**Phase 1 — Orchestrator Loop**
1. WorkflowOrchestrator (running in a background asyncio task, spawned at app startup) picks up the pending job.
2. Locks the job row via `SELECT ... FOR UPDATE SKIP LOCKED` to prevent double-processing.
3. Transitions status to `running`, records `started_at` timestamp.
4. Loads the state machine definition for `course_generation`:

```yaml
states:
  - name: validate_input
    next: generate_pages
    retry_count: 1
    timeout_s: 30
  - name: generate_pages
    next: validate_course
    retry_count: 3
    timeout_s: 600
    on_retry: escalate_error_to_llm
  - name: validate_course
    next: create_batch_proposal
    retry_count: 1
    timeout_s: 60
  - name: create_batch_proposal
    next: complete
    retry_count: 1
    timeout_s: 30
  - name: complete        # terminal
  - name: failed          # terminal (dead-letter)
  - name: cancelled       # terminal
```

5. For each state, the orchestrator:
   a. Loads the step function from the step registry (`app/services/workflow/steps/`).
   b. Calls the step function with `(job_id, checkpoint_data, context_logger)`.
   c. If the step succeeds: stores the step output in `checkpoint_data` (JSON), advances the state machine.
   d. If the step fails: increments retry count, applies `on_retry` strategy (e.g., `escalate_error_to_llm` passes the error back to the LLM), or transitions to `failed`.
   e. If the step exceeds `timeout_s`: cancels the current step execution via `asyncio.wait_for()`, transitions to `failed` with `TIMEOUT` reason.
   f. Writes every state transition to the `workflow_job_events` table for audit.

**Phase 2 — Page Generation (State: generate_pages)**
1. Step function `CourseGenerationStep.execute()` iterates over each page in the approved plan.
2. For page `i` of `N`:
   a. Builds the LLM prompt from the page title, suggested template type, source-material excerpts.
   b. Calls `LLMClient.generate()` with `temperature=0.3`, `max_tokens=4096`, `model=AI_GENERATION_MODEL`.
   c. Parses the response into structured page content (dict matching the component registry schema).
   d. Validates via `CourseValidator.validate_page(page_content)`.
   e. If valid: appends to `checkpoint_data.pages_generated[]`.
   f. If invalid and retries remain: feeds error back to LLM with `"The previous response failed validation: {error}. Please fix."`.
   g. Updates `progress` to `i/N` and writes to DB.
3. On completion, stores all generated pages in `checkpoint_data`.

**Phase 3 — Course Validation (State: validate_course)**
1. Runs `CourseValidator.validate_full_course(pages, course_metadata)`.
2. Checks: schema compliance, navigation completeness, assessment presence if flagged, export readiness.

**Phase 4 — Batch Proposal Creation (State: create_batch_proposal)**
1. Creates batch proposal via US-AI-029 semantics.
2. Stores `batch_proposal_id` in `checkpoint_data`.

**Phase 5 — Completion**
1. Transitions to `complete`, sets `progress=1.0`, `completed_at=now()`.
2. Updates `result` with `{batch_proposal_id, course_preview_url, total_pages, generation_metrics}`.
3. WorkflowOrchestrator releases the row lock.

**Phase 6 — User Notification**
1. Frontend polls and sees `status: "complete"` with `result`.
2. Frontend navigates to the course preview/review screen (return to US-AI-019 flow).
3. If `status: "failed"`, frontend shows error details, retry button.

### 1.5 Flow: Process Recovery on Restart

1. On application startup, the `WorkflowOrchestrator` calls `recover_stale_jobs()`.
2. Queries: `SELECT * FROM workflow_jobs WHERE status IN ('running', 'pending') AND locked_by IS NULL`.
3. For each:
   - If `status = 'running'` AND `heartbeat_at` > 30 seconds ago: restarts from the last checkpoint state.
   - If `status = 'running'` AND `heartbeat_at` <= 30 seconds ago (another worker is active): skips.
   - If `status = 'pending'`: normal pickup.
4. Logs recovery count at startup.

### 1.6 Non-Functional Requirements

| Requirement | Target |
|---|---|
| Max concurrent workers | Configurable via `WORKFLOW_MAX_CONCURRENCY` (default 4) |
| Max job duration | 24 hours (hard limit, enforced at state machine level) |
| Heartbeat interval | Every 5 seconds during step execution |
| Polling interval (frontend) | 2 seconds recommended |
| Step timeout precision | +/- 1 second via `asyncio.wait_for` |
| DB lock timeout | 5 seconds (`lock_timeout` on PG lock queries) |
| Max checkpoint size | 1 MB per job (enforced at write) |
| Recovery time on restart | < 2 seconds for N=100 stale jobs |

---

## 2. API Contract

### 2.1 POST /api/v1/workflows — Submit a New Workflow Job

```
POST /api/v1/workflows
Content-Type: application/json
Accept: application/json
```

**Request Body:**
```json
{
  "workflow_type": "course_generation",
  "input": {
    "import_job_id": "550e8400-e29b-41d4-a716-446655440000",
    "course_id": "course-python-101",
    "generation_options": {
      "model": "claude-sonnet-4-20250514",
      "temperature": 0.3,
      "max_tokens_per_page": 4096,
      "retry_count": 3,
      "language": "en"
    }
  },
  "webhook_url": "https://frontend.example.com/api/v1/workflow-callbacks",
  "priority": 0
}
```

**Validation Rules:**
- `workflow_type` must be a registered workflow type in `WORKFLOW_TYPES` table / enum.
- `input` must pass JSON Schema validation for the specific workflow type (schema stored in `workflow_type_definitions.input_schema`).
- `webhook_url` must be a valid HTTPS URL or null.
- `priority` defaults to 0, range [-10, 10].

**Response (202 Accepted):**
```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "workflow_type": "course_generation",
  "status": "pending",
  "created_at": "2026-06-14T10:30:00Z",
  "polling_url": "/api/v1/workflows/a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "estimated_duration_seconds": 300
}
```

**Error Responses:**
- 400: `{"code": "WORKFLOW_VALIDATION_ERROR", "field": "input.import_job_id", "message": "Import job not found or not in plan_approved status"}`
- 422: `{"code": "WORKFLOW_SCHEMA_ERROR", "field": "workflow_type", "message": "Unregistered workflow type: 'unknown_type'"}`

### 2.2 GET /api/v1/workflows/{job_id} — Get Job Status

```
GET /api/v1/workflows/a1b2c3d4-e5f6-7890-abcd-ef1234567890
Accept: application/json
```

**Response (200 OK):**
```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "workflow_type": "course_generation",
  "status": "running",
  "current_state": "generate_pages",
  "progress": 0.45,
  "checkpoint": {
    "pages_total": 20,
    "pages_generated": 9,
    "pages_failed": 0,
    "current_page_index": 9,
    "current_page_title": "Variables and Data Types"
  },
  "result": null,
  "error": null,
  "created_at": "2026-06-14T10:30:00Z",
  "started_at": "2026-06-14T10:30:01Z",
  "updated_at": "2026-06-14T10:33:27Z",
  "completed_at": null,
  "heartbeat_at": "2026-06-14T10:33:26Z",
  "retry_count": 0,
  "estimated_remaining_seconds": 165
}
```

**Error Responses:**
- 404: `{"code": "WORKFLOW_NOT_FOUND", "field": "job_id", "message": "No workflow job found with ID a1b2c3d4-e5f6-7890-abcd-ef1234567890"}`

### 2.3 POST /api/v1/workflows/{job_id}/cancel — Cancel a Job

```
POST /api/v1/workflows/a1b2c3d4-e5f6-7890-abcd-ef1234567890/cancel
Accept: application/json
```

**Response (200 OK):**
```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "cancelled",
  "previous_status": "running",
  "cancelled_at": "2026-06-14T10:35:00Z"
}
```

**Error Responses:**
- 409: `{"code": "WORKFLOW_NOT_RUNNING", "field": "job_id", "message": "Job is already in terminal state: complete"}`

### 2.4 POST /api/v1/workflows/{job_id}/retry — Retry a Failed Job

```
POST /api/v1/workflows/a1b2c3d4-e5f6-7890-abcd-ef1234567890/retry
Accept: application/json
```

**Response (200 OK):**
```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "pending",
  "previous_status": "failed",
  "retry_count": 1,
  "retried_at": "2026-06-14T10:36:00Z"
}
```

### 2.5 GET /api/v1/workflows — List Jobs (Admin)

```
GET /api/v1/workflows?status=failed&workflow_type=course_generation&limit=20&offset=0
Accept: application/json
```

**Response (200 OK):**
```json
{
  "total": 5,
  "limit": 20,
  "offset": 0,
  "items": [
    {
      "job_id": "...",
      "workflow_type": "course_generation",
      "status": "failed",
      "current_state": "generate_pages",
      "progress": 0.1,
      "error": {"code": "LLM_RATE_LIMITED", "message": "Anthropic API rate limit exceeded. Retry in 60 seconds."},
      "created_at": "2026-06-14T10:00:00Z",
      "updated_at": "2026-06-14T10:01:30Z"
    }
  ]
}
```

### 2.6 GET /api/v1/workflows/{job_id}/events — Get Job Event History

```
GET /api/v1/workflows/a1b2c3d4-e5f6-7890-abcd-ef1234567890/events
Accept: application/json
```

**Response (200 OK):**
```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "events": [
    {
      "event_id": 1,
      "state": "validate_input",
      "event_type": "state_entered",
      "timestamp": "2026-06-14T10:30:01Z",
      "payload": null
    },
    {
      "event_id": 2,
      "state": "validate_input",
      "event_type": "step_completed",
      "timestamp": "2026-06-14T10:30:02Z",
      "payload": {"duration_ms": 850}
    },
    {
      "event_id": 3,
      "state": "generate_pages",
      "event_type": "state_entered",
      "timestamp": "2026-06-14T10:30:02Z",
      "payload": null
    },
    {
      "event_id": 4,
      "state": "generate_pages",
      "event_type": "progress_update",
      "timestamp": "2026-06-14T10:33:27Z",
      "payload": {"progress": 0.45, "pages_generated": 9, "current_page_title": "Variables and Data Types"}
    }
  ]
}
```

---

## 3. Database Schema

### 3.1 `workflow_type_definitions` — Registry of Workflow Types

```sql
CREATE TABLE workflow_type_definitions (
    id              INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    workflow_type   VARCHAR(64)   NOT NULL UNIQUE,
    display_name    VARCHAR(200)  NOT NULL,
    description     TEXT          NOT NULL DEFAULT '',
    input_schema    JSONB         NOT NULL,          -- JSON Schema for workflow input validation
    state_machine   JSONB         NOT NULL,          -- State machine definition (states, transitions, retry policies, timeouts)
    output_schema   JSONB         DEFAULT NULL,       -- JSON Schema for the result field (nullable)
    max_duration_seconds INTEGER  NOT NULL DEFAULT 86400,  -- 24h default
    is_active       BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_wf_type_def_active ON workflow_type_definitions (workflow_type) WHERE is_active = TRUE;
```

### 3.2 `workflow_jobs` — The Primary Job Table

```sql
CREATE TABLE workflow_jobs (
    id                  INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    job_id              UUID          NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    workflow_type       VARCHAR(64)   NOT NULL REFERENCES workflow_type_definitions(workflow_type),
    
    -- State machine tracking
    status              VARCHAR(32)   NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'running', 'paused', 'complete', 'failed', 'cancelled')),
    current_state       VARCHAR(128)  NOT NULL DEFAULT 'validate_input',
    previous_state      VARCHAR(128)  DEFAULT NULL,
    
    -- Input / Output
    input               JSONB         NOT NULL,
    result              JSONB         DEFAULT NULL,
    error               JSONB         DEFAULT NULL,   -- {code: string, message: string, details: object}
    
    -- Checkpoint data (step executor writes intermediate state here)
    checkpoint_data     JSONB         NOT NULL DEFAULT '{}'::jsonb,
    
    -- Progress
    progress            REAL          NOT NULL DEFAULT 0.0 CHECK (progress >= 0.0 AND progress <= 1.0),
    
    -- Retry tracking
    retry_count          INTEGER       NOT NULL DEFAULT 0,
    max_retries          INTEGER       NOT NULL DEFAULT 3,
    current_retry_state  VARCHAR(128)  DEFAULT NULL,  -- Which state is being retried
    
    -- Timing
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    started_at          TIMESTAMPTZ   DEFAULT NULL,
    completed_at        TIMESTAMPTZ   DEFAULT NULL,
    updated_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    
    -- Heartbeat & Locking (for concurrency control)
    heartbeat_at        TIMESTAMPTZ   DEFAULT NULL,
    locked_by           VARCHAR(64)   DEFAULT NULL,   -- Worker instance ID
    
    -- Webhook
    webhook_url         VARCHAR(1024) DEFAULT NULL,
    webhook_sent_at     TIMESTAMPTZ   DEFAULT NULL,
    
    -- Priority queue
    priority            INTEGER       NOT NULL DEFAULT 0,
    
    -- User context
    created_by_user_id  VARCHAR(64)   DEFAULT NULL,
    session_id          UUID          DEFAULT NULL REFERENCES ai_sessions(id) ON DELETE SET NULL ON UPDATE CASCADE,
    
    -- Expiry / hard limit
    expires_at          TIMESTAMPTZ   NOT NULL DEFAULT (NOW() + INTERVAL '24 hours')
);

CREATE INDEX idx_wf_jobs_status ON workflow_jobs (status) WHERE status IN ('pending', 'running');
CREATE INDEX idx_wf_jobs_type_status ON workflow_jobs (workflow_type, status);
CREATE INDEX idx_wf_jobs_locked_by ON workflow_jobs (locked_by) WHERE locked_by IS NOT NULL;
CREATE INDEX idx_wf_jobs_heartbeat ON workflow_jobs (heartbeat_at) WHERE status = 'running';
CREATE INDEX idx_wf_jobs_created ON workflow_jobs (created_at DESC);
CREATE INDEX idx_wf_jobs_expires ON workflow_jobs (expires_at) WHERE status NOT IN ('complete', 'cancelled');
```

### 3.3 `workflow_job_events` — Immutable Event Log

```sql
CREATE TABLE workflow_job_events (
    id              BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    job_id          UUID          NOT NULL REFERENCES workflow_jobs(job_id) ON DELETE CASCADE,
    state           VARCHAR(128)  NOT NULL,           -- State name at time of event
    event_type      VARCHAR(64)   NOT NULL,           -- state_entered, step_completed, step_failed, progress_update, error, retry, cancelled, heartbeat
    
    payload         JSONB         DEFAULT NULL,
    timestamp       TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_wf_events_job ON workflow_job_events (job_id, timestamp);
CREATE INDEX idx_wf_events_type ON workflow_job_events (event_type);
```

### 3.4 Migration SQL (Alembic)

This is the Alembic migration (`alembic/versions/20260614_0001_create_workflow_tables.py`):

```python
"""Create workflow engine tables

Revision ID: 20260614_0001
Revises: <previous_revision_id>
Create Date: 2026-06-14 10:00:00.000000
"""
from __future__ import annotations
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "20260614_0001"
down_revision: Union[str, None] = "<previous_revision_id>"  # to be filled
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- workflow_type_definitions --
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
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="TRUE"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_wf_type_def_active", "workflow_type_definitions", ["workflow_type"],
                    postgresql_where=sa.text("is_active = TRUE"))

    # -- workflow_jobs --
    op.create_table(
        "workflow_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", UUID(), nullable=False, unique=True, server_default=sa.text("gen_random_uuid()")),
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
    op.create_index("idx_wf_jobs_status", "workflow_jobs", ["status"],
                    postgresql_where=sa.text("status IN ('pending', 'running')"))
    op.create_index("idx_wf_jobs_type_status", "workflow_jobs", ["workflow_type", "status"])
    op.create_index("idx_wf_jobs_locked_by", "workflow_jobs", ["locked_by"],
                    postgresql_where=sa.text("locked_by IS NOT NULL"))
    op.create_index("idx_wf_jobs_heartbeat", "workflow_jobs", ["heartbeat_at"],
                    postgresql_where=sa.text("status = 'running'"))
    op.create_index("idx_wf_jobs_created", "workflow_jobs", [sa.text("created_at DESC")])
    op.create_index("idx_wf_jobs_expires", "workflow_jobs", ["expires_at"],
                    postgresql_where=sa.text("status NOT IN ('complete', 'cancelled')"))

    # -- workflow_job_events --
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

    # Foreign key for workflow_jobs -> workflow_type_definitions
    op.create_foreign_key(
        "fk_wf_jobs_type", "workflow_jobs", "workflow_type_definitions",
        ["workflow_type"], ["workflow_type"],
    )
    # Foreign key for workflow_job_events -> workflow_jobs
    op.create_foreign_key(
        "fk_wf_events_job", "workflow_job_events", "workflow_jobs",
        ["job_id"], ["job_id"], ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_table("workflow_job_events")
    op.drop_table("workflow_jobs")
    op.drop_table("workflow_type_definitions")
```

---

## 4. Service Signatures and Interfaces

### 4.1 ORM Model: `app/models/workflow.py`

```python
"""Durable workflow engine ORM models."""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import (
    String, Integer, Float, Boolean, Text, DateTime,
    JSON, UniqueConstraint, ForeignKey, Index,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
import uuid as _uuid

from app.models.base import Base


class WorkflowTypeDefinition(Base):
    __tablename__ = "workflow_type_definitions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_type: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    input_schema: Mapped[dict] = mapped_column(JSONB, nullable=False)
    state_machine: Mapped[dict] = mapped_column(JSONB, nullable=False)
    output_schema: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    max_duration_seconds: Mapped[int] = mapped_column(Integer, default=86400)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_wf_type_def_active", "workflow_type", postgresql_where="is_active = TRUE"),
    )


class WorkflowJob(Base):
    __tablename__ = "workflow_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), unique=True, default=_uuid.uuid4, server_default=sa_text("gen_random_uuid()")
    )
    workflow_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    current_state: Mapped[str] = mapped_column(String(128), default="validate_input")
    previous_state: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    input: Mapped[dict] = mapped_column(JSONB, nullable=False)
    result: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    checkpoint_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    current_retry_state: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    webhook_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    webhook_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    session_id: Mapped[Optional[_uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ai_sessions.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("idx_wf_jobs_status", "status", postgresql_where="status IN ('pending', 'running')"),
        Index("idx_wf_jobs_type_status", "workflow_type", "status"),
        Index("idx_wf_jobs_locked_by", "locked_by", postgresql_where="locked_by IS NOT NULL"),
        Index("idx_wf_jobs_heartbeat", "heartbeat_at", postgresql_where="status = 'running'"),
        ForeignKeyConstraint(["workflow_type"], ["workflow_type_definitions.workflow_type"], name="fk_wf_jobs_type"),
    )


class WorkflowJobEvent(Base):
    __tablename__ = "workflow_job_events"

    id: Mapped[int] = mapped_column(sa.BIGINT, primary_key=True, autoincrement=True)
    job_id: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workflow_jobs.job_id", ondelete="CASCADE")
    )
    state: Mapped[str] = mapped_column(String(128))
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        Index("idx_wf_events_job", "job_id", "timestamp"),
    )
```

### 4.2 Repository: `app/repositories/workflow_repository.py`

```python
"""Async repository for workflow jobs and events."""
from __future__ import annotations
import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func, text, and_, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.workflow import WorkflowJob, WorkflowJobEvent, WorkflowTypeDefinition

logger = logging.getLogger(__name__)

LOCK_TIMEOUT_MS = 5000


class WorkflowRepository:
    """Handles durable workflow job persistence and locking."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ── Type Definitions ─────────────────────────────────────────────────

    async def get_type_definition(self, workflow_type: str) -> Optional[WorkflowTypeDefinition]:
        stmt = select(WorkflowTypeDefinition).where(
            WorkflowTypeDefinition.workflow_type == workflow_type,
            WorkflowTypeDefinition.is_active == True,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def register_type_definition(
        self,
        workflow_type: str,
        display_name: str,
        description: str,
        input_schema: Dict[str, Any],
        state_machine: Dict[str, Any],
        output_schema: Optional[Dict[str, Any]] = None,
        max_duration_seconds: int = 86400,
    ) -> WorkflowTypeDefinition:
        stmt = pg_insert(WorkflowTypeDefinition).values(
            workflow_type=workflow_type,
            display_name=display_name,
            description=description,
            input_schema=input_schema,
            state_machine=state_machine,
            output_schema=output_schema or {},
            max_duration_seconds=max_duration_seconds,
        ).on_conflict_do_update(
            index_elements=["workflow_type"],
            set_=dict(
                display_name=display_name,
                description=description,
                input_schema=input_schema,
                state_machine=state_machine,
                output_schema=output_schema or {},
                max_duration_seconds=max_duration_seconds,
                updated_at=datetime.utcnow(),
            ),
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return await self.get_type_definition(workflow_type)

    # ── Job CRUD ─────────────────────────────────────────────────────────

    async def create_job(
        self,
        workflow_type: str,
        input_data: Dict[str, Any],
        webhook_url: Optional[str] = None,
        priority: int = 0,
        created_by_user_id: Optional[str] = None,
        session_id: Optional[uuid.UUID] = None,
        max_retries: int = 3,
        max_duration_seconds: int = 86400,
    ) -> WorkflowJob:
        job = WorkflowJob(
            workflow_type=workflow_type,
            input=input_data,
            status="pending",
            current_state="validate_input",
            checkpoint_data={},
            progress=0.0,
            retry_count=0,
            max_retries=max_retries,
            webhook_url=webhook_url,
            priority=priority,
            created_by_user_id=created_by_user_id,
            session_id=session_id,
            expires_at=datetime.utcnow() + timedelta(seconds=max_duration_seconds),
        )
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        logger.info("Created workflow job %s (type=%s)", job.job_id, workflow_type)
        return job

    async def get_job(self, job_id: uuid.UUID) -> Optional[WorkflowJob]:
        stmt = select(WorkflowJob).where(WorkflowJob.job_id == job_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_jobs(
        self,
        status: Optional[str] = None,
        workflow_type: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[List[WorkflowJob], int]:
        conditions = []
        if status:
            conditions.append(WorkflowJob.status == status)
        if workflow_type:
            conditions.append(WorkflowJob.workflow_type == workflow_type)

        count_stmt = select(func.count(WorkflowJob.id))
        if conditions:
            count_stmt = count_stmt.where(and_(*conditions))
        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar_one()

        stmt = select(WorkflowJob).order_by(WorkflowJob.created_at.desc()).limit(limit).offset(offset)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    # ── Locking & Status Transitions ─────────────────────────────────────

    async def try_lock_pending(self, worker_id: str) -> Optional[WorkflowJob]:
        """Atomically claim the next pending job (priority-ordered)."""
        stmt = text("""
            SET LOCAL lock_timeout = :lock_timeout;
            SELECT job_id, workflow_type, input, checkpoint_data, current_state,
                   retry_count, max_retries, expires_at
            FROM workflow_jobs
            WHERE status = 'pending'
              AND expires_at > NOW()
              AND locked_by IS NULL
            ORDER BY priority DESC, created_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        """).bindparams(lock_timeout=f"{LOCK_TIMEOUT_MS}ms")

        try:
            result = await self.session.execute(stmt)
            row = result.mappings().one_or_none()
        except Exception:
            logger.warning("Lock acquisition timed out or failed for pending job")
            return None

        if not row:
            return None

        job_id = row["job_id"]
        await self.session.execute(
            update(WorkflowJob)
            .where(WorkflowJob.job_id == job_id)
            .values(
                status="running",
                locked_by=worker_id,
                started_at=datetime.utcnow(),
                heartbeat_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        )
        await self.session.commit()
        logger.info("Worker %s locked job %s", worker_id, job_id)

        stmt2 = select(WorkflowJob).where(WorkflowJob.job_id == job_id)
        result2 = await self.session.execute(stmt2)
        return result2.scalar_one_or_none()

    async def heartbeat(self, job_id: uuid.UUID) -> None:
        stmt = (
            update(WorkflowJob)
            .where(WorkflowJob.job_id == job_id)
            .values(heartbeat_at=datetime.utcnow(), updated_at=datetime.utcnow())
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def transition(
        self,
        job_id: uuid.UUID,
        new_status: str,
        new_state: str,
        previous_state: str,
        progress: Optional[float] = None,
        error: Optional[Dict[str, Any]] = None,
        result: Optional[Dict[str, Any]] = None,
        checkpoint_data: Optional[Dict[str, Any]] = None,
        completed_at: Optional[datetime] = None,
    ) -> Optional[WorkflowJob]:
        values = {
            "status": new_status,
            "current_state": new_state,
            "previous_state": previous_state,
            "updated_at": datetime.utcnow(),
        }
        if progress is not None:
            values["progress"] = progress
        if error is not None:
            values["error"] = error
        if result is not None:
            values["result"] = result
        if checkpoint_data is not None:
            values["checkpoint_data"] = checkpoint_data
        if completed_at is not None:
            values["completed_at"] = completed_at
        if new_status in ("complete", "failed", "cancelled"):
            values["locked_by"] = None
            values["completed_at"] = completed_at or datetime.utcnow()

        stmt = (
            update(WorkflowJob)
            .where(WorkflowJob.job_id == job_id)
            .values(**values)
            .returning(WorkflowJob)
        )
        result_set = await self.session.execute(stmt)
        await self.session.commit()
        job = result_set.scalar_one_or_none()
        if job:
            logger.info("Job %s transitioned to %s/%s", job_id, new_status, new_state)
        return job

    # ── Events ───────────────────────────────────────────────────────────

    async def append_event(
        self,
        job_id: uuid.UUID,
        state: str,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> WorkflowJobEvent:
        event = WorkflowJobEvent(
            job_id=job_id,
            state=state,
            event_type=event_type,
            payload=payload or {},
        )
        self.session.add(event)
        await self.session.commit()
        return event

    async def get_events(self, job_id: uuid.UUID, limit: int = 500) -> List[WorkflowJobEvent]:
        stmt = (
            select(WorkflowJobEvent)
            .where(WorkflowJobEvent.job_id == job_id)
            .order_by(WorkflowJobEvent.timestamp.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ── Recovery ─────────────────────────────────────────────────────────

    async def find_stale_running_jobs(self, stale_threshold_seconds: int = 30) -> List[WorkflowJob]:
        """Find jobs stuck in 'running' with no recent heartbeat."""
        cutoff = datetime.utcnow() - timedelta(seconds=stale_threshold_seconds)
        stmt = select(WorkflowJob).where(
            WorkflowJob.status == "running",
            WorkflowJob.locked_by.isnot(None),
            or_(
                WorkflowJob.heartbeat_at.is_(None),
                WorkflowJob.heartbeat_at < cutoff,
            ),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_expired_jobs(self) -> List[WorkflowJob]:
        """Find pending/running jobs past their expiry."""
        stmt = select(WorkflowJob).where(
            WorkflowJob.expires_at < datetime.utcnow(),
            WorkflowJob.status.in_(["pending", "running"]),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def release_lock(self, job_id: uuid.UUID) -> None:
        stmt = (
            update(WorkflowJob)
            .where(WorkflowJob.job_id == job_id)
            .values(locked_by=None, updated_at=datetime.utcnow())
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def increment_retry(self, job_id: uuid.UUID) -> Optional[WorkflowJob]:
        stmt = (
            update(WorkflowJob)
            .where(WorkflowJob.job_id == job_id)
            .values(
                retry_count=WorkflowJob.retry_count + 1,
                current_retry_state=WorkflowJob.current_state,
                status="pending",
                locked_by=None,
                updated_at=datetime.utcnow(),
            )
            .returning(WorkflowJob)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.scalar_one_or_none()
```

### 4.3 Workflow Orchestrator: `app/services/workflow/orchestrator.py`

```python
"""Durable workflow engine orchestrator.

Runs as a background asyncio task. Picks up pending jobs, advances their
state machines, and releases them on completion or failure.
"""
from __future__ import annotations
import asyncio
import logging
import os
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, Callable, Awaitable

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import SessionLocal
from app.repositories.workflow_repository import WorkflowRepository
from app.services.workflow.step_registry import StepRegistry
from app.models.workflow import WorkflowJob

logger = logging.getLogger(__name__)

StepFunc = Callable[
    [
        uuid.UUID,           # job_id
        Dict[str, Any],      # input
        Dict[str, Any],      # checkpoint_data (mutable)
        logging.Logger,      # step-scoped logger
        Dict[str, Any],      # step_config from state machine
    ],
    Awaitable[StepResult],
]


class StepResult:
    """Return value from a step executor."""
    def __init__(
        self,
        success: bool,
        checkpoint_data: Optional[Dict[str, Any]] = None,
        progress: Optional[float] = None,
        error: Optional[Dict[str, Any]] = None,
        output: Optional[Dict[str, Any]] = None,
    ):
        self.success = success
        self.checkpoint_data = checkpoint_data or {}
        self.progress = progress
        self.error = error
        self.output = output


class WorkflowOrchestrator:
    """Background orchestrator that drives workflow jobs to completion."""

    def __init__(
        self,
        worker_id: str = os.getenv("WORKFLOW_WORKER_ID", "worker-1"),
        poll_interval_seconds: float = 1.0,
        heartbeat_interval_seconds: float = 5.0,
        max_concurrency: int = 4,
    ):
        self.worker_id = worker_id
        self.poll_interval = poll_interval_seconds
        self.heartbeat_interval = heartbeat_interval_seconds
        self.max_concurrency = max_concurrency
        self._active_jobs: Dict[uuid.UUID, asyncio.Task] = {}
        self._running = False
        self._step_registry = StepRegistry()

    async def start(self) -> None:
        """Start the orchestrator background loop. Called from app lifespan."""
        self._running = True
        logger.info(
            "WorkflowOrchestrator starting (worker=%s, max_concurrency=%d)",
            self.worker_id, self.max_concurrency,
        )
        # Recover stale jobs before starting the poll loop
        await self._recover_stale_jobs()
        asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """Graceful shutdown: wait for active jobs within their heartbeat window."""
        self._running = False
        logger.info("WorkflowOrchestrator stopping (%d active jobs)", len(self._active_jobs))
        if self._active_jobs:
            wait_for = asyncio.gather(*self._active_jobs.values(), return_exceptions=True)
            try:
                await asyncio.wait_for(wait_for, timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("Timed out waiting for active jobs to finish")

    async def submit_job(
        self,
        workflow_type: str,
        input_data: Dict[str, Any],
        session: AsyncSession,
        webhook_url: Optional[str] = None,
        priority: int = 0,
        created_by_user_id: Optional[str] = None,
    ) -> WorkflowJob:
        repo = WorkflowRepository(session)
        type_def = await repo.get_type_definition(workflow_type)
        if not type_def:
            raise ValueError(f"Unknown workflow type: {workflow_type}")

        job = await repo.create_job(
            workflow_type=workflow_type,
            input_data=input_data,
            webhook_url=webhook_url,
            priority=priority,
            created_by_user_id=created_by_user_id,
            max_retries=type_def.state_machine.get("max_retries", 3),
            max_duration_seconds=type_def.max_duration_seconds,
        )
        return job

    async def cancel_job(self, job_id: uuid.UUID) -> bool:
        """Cancel a running job."""
        async with SessionLocal() as session:
            repo = WorkflowRepository(session)
            job = await repo.get_job(job_id)
            if not job:
                return False
            if job.status not in ("pending", "running"):
                return False

            await repo.transition(
                job_id=job_id,
                new_status="cancelled",
                new_state=job.current_state,
                previous_state=job.current_state,
            )
            await repo.append_event(
                job_id=job_id,
                state=job.current_state,
                event_type="cancelled",
                payload={"cancelled_by": self.worker_id},
            )

            # Cancel the in-memory task if running
            task = self._active_jobs.get(job_id)
            if task and not task.done():
                task.cancel()
                self._active_jobs.pop(job_id, None)

            return True

    # ── Internal ─────────────────────────────────────────────────────────

    async def _recover_stale_jobs(self) -> int:
        """Reclaim jobs orphaned by a previous worker process crash."""
        async with SessionLocal() as session:
            repo = WorkflowRepository(session)
            stale = await repo.find_stale_running_jobs()
            for job in stale:
                # Reset to pending so the next poll cycle picks it up
                await repo.transition(
                    job_id=job.job_id,
                    new_status="pending",
                    new_state=job.current_state,
                    previous_state=job.current_state,
                    error={"code": "WORKER_RECOVERY", "message": "Worker recovered after process restart"},
                )
                await repo.release_lock(job.job_id)

            # Also expire jobs past their TTL
            expired = await repo.find_expired_jobs()
            for job in expired:
                await repo.transition(
                    job_id=job.job_id,
                    new_status="failed",
                    new_state=job.current_state,
                    previous_state=job.current_state,
                    error={"code": "JOB_EXPIRED", "message": f"Job exceeded max duration of {job.expires_at.isoformat()}"},
                )

            logger.info("Recovered %d stale jobs, expired %d jobs", len(stale), len(expired))
            return len(stale) + len(expired)

    async def _poll_loop(self) -> None:
        """Main loop: poll for pending jobs, execute state machines."""
        while self._running:
            try:
                # Enforce concurrency limit
                if len(self._active_jobs) < self.max_concurrency:
                    job = await self._pick_and_lock()
                    if job:
                        task = asyncio.create_task(self._execute_job(job))
                        self._active_jobs[job.job_id] = task
                        task.add_done_callback(
                            lambda t, jid=job.job_id: self._active_jobs.pop(jid, None)
                        )

                # Also health-check active tasks
                stale_tasks = [
                    jid for jid, t in self._active_jobs.items()
                    if t.done() and jid in self._active_jobs
                ]
                for jid in stale_tasks:
                    self._active_jobs.pop(jid, None)

            except Exception:
                logger.exception("Error in orchestration poll loop")

            await asyncio.sleep(self.poll_interval)

    async def _pick_and_lock(self) -> Optional[WorkflowJob]:
        """Atomically claim a pending job from the DB."""
        async with SessionLocal() as session:
            repo = WorkflowRepository(session)
            return await repo.try_lock_pending(self.worker_id)

    async def _execute_job(self, job: WorkflowJob) -> None:
        """Run a single job's state machine to completion."""
        job_logger = logging.getLogger(f"workflow.{job.workflow_type}.{job.job_id}")
        job_logger.info("Starting execution of job %s", job.job_id)

        async with SessionLocal() as session:
            repo = WorkflowRepository(session)
            type_def = await repo.get_type_definition(job.workflow_type)
            if not type_def:
                await repo.transition(
                    job.job_id, "failed", job.current_state, job.current_state,
                    error={"code": "TYPE_NOT_FOUND", "message": f"Workflow type '{job.workflow_type}' not found"},
                    completed_at=datetime.utcnow(),
                )
                return

            state_machine = type_def.state_machine
            checkpoint = dict(job.checkpoint_data or {})

            try:
                await self._run_state_machine(repo, job, state_machine, checkpoint, job_logger)
            except asyncio.CancelledError:
                job_logger.warning("Job %s execution cancelled", job.job_id)
            except Exception as exc:
                job_logger.exception("Unhandled error in job %s state machine", job.job_id)
                await repo.transition(
                    job.job_id, "failed", job.current_state, job.current_state,
                    error={"code": "UNHANDLED_ERROR", "message": str(exc)},
                    checkpoint_data=checkpoint,
                    completed_at=datetime.utcnow(),
                )
                await repo.append_event(job.job_id, job.current_state, "error", {"error": str(exc)})

    async def _run_state_machine(
        self,
        repo: WorkflowRepository,
        job: WorkflowJob,
        state_machine: Dict[str, Any],
        checkpoint: Dict[str, Any],
        job_logger: logging.Logger,
    ) -> None:
        """Advance the job through its state machine states."""
        current_state_name = job.current_state
        states = state_machine.get("states", [])

        # Build a lookup of state configs
        state_configs: Dict[str, Any] = {s["name"]: s for s in states}

        while current_state_name not in ("complete", "failed", "cancelled"):
            state_config = state_configs.get(current_state_name)
            if not state_config:
                raise ValueError(f"Unknown state '{current_state_name}' in state machine")

            timeout_s = state_config.get("timeout_s", 300)
            max_retries_for_state = state_config.get("retry_count", 1)
            next_state_on_success = state_config.get("next", "complete")

            step_func = self._step_registry.get(  # type: ignore[union-attr]
                job.workflow_type, current_state_name
            )
            if not step_func:
                raise ValueError(
                    f"No step registered for {job.workflow_type}.{current_state_name}"
                )

            await repo.append_event(job.job_id, current_state_name, "state_entered")

            # Execute the step with timeout
            try:
                step_result: StepResult = await asyncio.wait_for(
                    step_func(job.job_id, job.input, checkpoint, job_logger, state_config),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                job_logger.error("State '%s' timed out after %ds", current_state_name, timeout_s)
                await repo.append_event(
                    job.job_id, current_state_name, "step_failed",
                    {"error": f"TIMEOUT after {timeout_s}s"},
                )
                # Handle timeout as a failure for retry logic below
                step_result = StepResult(
                    success=False,
                    checkpoint_data=checkpoint,
                    progress=job.progress,
                    error={"code": "STEP_TIMEOUT", "message": f"State '{current_state_name}' timed out after {timeout_s}s"},
                )

            if step_result.success:
                # Merge checkpoint updates
                if step_result.checkpoint_data:
                    checkpoint.update(step_result.checkpoint_data)
                progress = step_result.progress if step_result.progress is not None else job.progress

                await repo.transition(
                    job.job_id,
                    new_status="running",
                    new_state=next_state_on_success,
                    previous_state=current_state_name,
                    progress=progress,
                    checkpoint_data=checkpoint,
                )
                await repo.append_event(
                    job.job_id, current_state_name, "step_completed",
                    {"next_state": next_state_on_success, "duration_ms": 0},
                )

                current_state_name = next_state_on_success
                job.progress = progress

            else:
                # Step failed — decide retry or dead-letter
                attempt = job.retry_count + 1
                max_retries_for_job = job.max_retries

                if attempt < max_retries_for_state and (max_retries_for_job == 0 or attempt <= max_retries_for_job):
                    # Retry: reset to pending, increment retry count
                    job_logger.warning(
                        "State '%s' failed (attempt %d/%d). Retrying.",
                        current_state_name, attempt, max_retries_for_state,
                    )
                    job.retry_count = attempt
                    await repo.increment_retry(job.job_id)
                    await repo.append_event(
                        job.job_id, current_state_name, "retry",
                        {"attempt": attempt, "max_retries": max_retries_for_state,
                         "error": step_result.error},
                    )
                    return  # Exit execution; the poll loop will re-lock on next cycle
                else:
                    # Dead letter
                    job_logger.error(
                        "State '%s' failed permanently after %d attempts.",
                        current_state_name, attempt,
                    )
                    await repo.transition(
                        job.job_id,
                        new_status="failed",
                        new_state=current_state_name,
                        previous_state=current_state_name,
                        error=step_result.error or {"code": "STEP_FAILED", "message": "Step failed"},
                        checkpoint_data=checkpoint,
                        completed_at=datetime.utcnow(),
                    )
                    await repo.append_event(
                        job.job_id, current_state_name, "step_failed",
                        {"error": step_result.error, "final_attempt": attempt},
                    )
                    return

        # Terminal state reached
        if current_state_name == "complete":
            await repo.transition(
                job.job_id,
                new_status="complete",
                new_state="complete",
                previous_state=current_state_name,
                progress=1.0,
                result=checkpoint.get("result"),
                checkpoint_data=checkpoint,
                completed_at=datetime.utcnow(),
            )
            await repo.append_event(job.job_id, "complete", "job_completed")

            # Fire webhook if configured
            if job.webhook_url:
                await self._fire_webhook(job, "complete")

    async def _fire_webhook(self, job: WorkflowJob, status: str) -> None:
        """POST job completion/failure to the configured webhook URL."""
        import httpx
        payload = {
            "job_id": str(job.job_id),
            "workflow_type": job.workflow_type,
            "status": status,
            "result": job.result,
            "error": job.error,
            "completed_at": datetime.utcnow().isoformat(),
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(job.webhook_url, json=payload)
                resp.raise_for_status()
                async with SessionLocal() as session:
                    repo = WorkflowRepository(session)
                    await repo.transition(
                        job.job_id,
                        new_status=job.status,
                        new_state=job.current_state,
                        previous_state=job.previous_state or job.current_state,
                    )
                    # Update webhook_sent_at
                    stmt = update(WorkflowJob).where(
                        WorkflowJob.job_id == job.job_id
                    ).values(webhook_sent_at=datetime.utcnow())
                    await session.execute(stmt)
                    await session.commit()
        except Exception as e:
            logger.warning("Webhook delivery failed for job %s: %s", job.job_id, e)
```

### 4.4 Step Registry: `app/services/workflow/step_registry.py`

```python
"""Central registry mapping (workflow_type, state_name) -> step functions."""
from __future__ import annotations
from typing import Dict, Tuple, Callable

StepKey = Tuple[str, str]


class StepRegistry:
    """Maps (workflow_type, state_name) to step executor functions."""

    def __init__(self):
        self._steps: Dict[StepKey, Callable] = {}

    def register(self, workflow_type: str, state_name: str):
        """Decorator to register a step function."""
        def decorator(func: Callable):
            self._steps[(workflow_type, state_name)] = func
            return func
        return decorator

    def get(self, workflow_type: str, state_name: str) -> Callable | None:
        return self._steps.get((workflow_type, state_name))

    def unregister(self, workflow_type: str, state_name: str) -> None:
        self._steps.pop((workflow_type, state_name), None)
```

### 4.5 Course Generation Step: `app/services/workflow/steps/course_generation.py`

```python
"""Step executors for the 'course_generation' workflow type."""
from __future__ import annotations
import uuid
import logging
from typing import Dict, Any

from app.services.workflow.step_registry import StepRegistry
from app.services.workflow.orchestrator import StepResult

registry = StepRegistry()


@registry.register("course_generation", "validate_input")
async def validate_input_step(
    job_id: uuid.UUID,
    input_data: Dict[str, Any],
    checkpoint: Dict[str, Any],
    logger: logging.Logger,
    step_config: Dict[str, Any],
) -> StepResult:
    """Validate that the input import job exists and is in plan_approved status."""
    import_job_id = input_data.get("import_job_id")
    if not import_job_id:
        return StepResult(False, error={"code": "MISSING_INPUT", "message": "import_job_id is required"})

    # Verify import job exists and is approved
    from app.db.config import SessionLocal
    from app.repositories.import_job_repository import ImportJobRepository

    async with SessionLocal() as session:
        repo = ImportJobRepository(session)
        job = await repo.get_by_id(import_job_id)
        if not job:
            return StepResult(False, error={"code": "IMPORT_JOB_NOT_FOUND", "message": f"No import job with id {import_job_id}"})
        if job.status != "plan_approved":
            return StepResult(False, error={
                "code": "INVALID_IMPORT_STATUS",
                "message": f"Import job status is '{job.status}', expected 'plan_approved'",
            })

        checkpoint["import_job"] = {
            "job_id": import_job_id,
            "course_id": job.course_id,
            "pages": job.result_data.get("pages", []),
            "course_metadata": job.result_data.get("courseMetadata", {}),
        }
        checkpoint["pages_state"] = {
            "total": len(job.result_data.get("pages", [])),
            "generated": 0,
            "failed": 0,
            "results": [],
        }

    return StepResult(True, checkpoint_data=checkpoint, progress=0.05)


@registry.register("course_generation", "generate_pages")
async def generate_pages_step(
    job_id: uuid.UUID,
    input_data: Dict[str, Any],
    checkpoint: Dict[str, Any],
    logger: logging.Logger,
    step_config: Dict[str, Any],
) -> StepResult:
    """Generate page content via LLM for each page in the approved plan."""
    import json
    from app.services.ai.llm_client import LLMClient

    pages = checkpoint.get("import_job", {}).get("pages", [])
    pages_state = checkpoint.get("pages_state", {})
    total = pages_state.get("total", len(pages))
    generation_options = input_data.get("generation_options", {})
    course_metadata = checkpoint.get("import_job", {}).get("course_metadata", {})

    results = pages_state.get("results", [])
    start_index = len(results)

    llm_client = LLMClient(
        model=generation_options.get("model", os.getenv("AI_GENERATION_MODEL", "claude-sonnet-4-20250514")),
        temperature=generation_options.get("temperature", 0.3),
        max_tokens=generation_options.get("max_tokens_per_page", 4096),
    )

    for i in range(start_index, total):
        page = pages[i]
        prompt = _build_generation_prompt(page, course_metadata, generation_options)

        try:
            response = await llm_client.generate(prompt)
            page_content = _parse_llm_response(response)

            # Validate against the component registry
            valid, errors = _validate_page_content(page_content, page.get("template_type"))
            if not valid:
                # Retry with error feedback (the state machine handles retry count)
                return StepResult(False, error={
                    "code": "PAGE_VALIDATION_FAILED",
                    "message": f"Page {i} ('{page.get('title')}') validation failed: {errors}",
                    "page_index": i,
                    "validation_errors": errors,
                }, checkpoint_data=checkpoint, progress=(i / total))

            results.append({
                "page_index": i,
                "title": page.get("title"),
                "template_type": page.get("template_type"),
                "content": page_content,
                "provenance": {
                    "model": generation_options.get("model"),
                    "temperature": generation_options.get("temperature"),
                    "generated_at": __import__("datetime").datetime.utcnow().isoformat(),
                },
            })

            checkpoint["pages_state"] = {
                "total": total,
                "generated": len(results),
                "failed": 0,
                "results": results,
            }

        except Exception as e:
            return StepResult(False, error={
                "code": "LLM_CALL_FAILED",
                "message": str(e),
                "page_index": i,
            }, checkpoint_data=checkpoint, progress=(i / total))

    return StepResult(True, checkpoint_data=checkpoint, progress=0.8)
```

### 4.6 Router: `app/routers/workflows.py`

```python
"""REST endpoints for the durable workflow engine."""
from __future__ import annotations
import uuid
import logging
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.repositories.workflow_repository import WorkflowRepository
from app.services.workflow.orchestrator import WorkflowOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows", tags=["Workflows"])


# ── Pydantic Schemas ────────────────────────────────────────────────────

class SubmitWorkflowRequest(BaseModel):
    workflow_type: str = Field(..., description="Registered workflow type identifier")
    input: dict = Field(..., description="Workflow-specific input data (validated against input_schema)")
    webhook_url: Optional[str] = Field(None, description="URL to POST on completion/failure")
    priority: int = Field(default=0, ge=-10, le=10, description="Priority (-10=lowest, 10=highest)")


class SubmitWorkflowResponse(BaseModel):
    job_id: str
    workflow_type: str
    status: str
    created_at: str
    polling_url: str
    estimated_duration_seconds: Optional[int] = None


class JobStatusResponse(BaseModel):
    job_id: str
    workflow_type: str
    status: str
    current_state: Optional[str] = None
    progress: float
    checkpoint: Optional[dict] = None
    result: Optional[dict] = None
    error: Optional[dict] = None
    created_at: str
    started_at: Optional[str] = None
    updated_at: str
    completed_at: Optional[str] = None
    heartbeat_at: Optional[str] = None
    retry_count: int


class CancelJobResponse(BaseModel):
    job_id: str
    status: str
    previous_status: str
    cancelled_at: str


class RetryJobResponse(BaseModel):
    job_id: str
    status: str
    previous_status: str
    retry_count: int
    retried_at: str


class JobEventResponse(BaseModel):
    event_id: int
    state: str
    event_type: str
    timestamp: str
    payload: Optional[dict] = None


class JobEventListResponse(BaseModel):
    job_id: str
    events: List[JobEventResponse]


class JobListItem(BaseModel):
    job_id: str
    workflow_type: str
    status: str
    current_state: Optional[str] = None
    progress: float
    error: Optional[dict] = None
    created_at: str
    updated_at: str


class JobListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[JobListItem]


# ── Endpoints ───────────────────────────────────────────────────────────

def _get_orchestrator() -> WorkflowOrchestrator:
    """Retrieve the singleton orchestrator instance from app state."""
    from app.main import app
    orchestrator: WorkflowOrchestrator = app.state.workflow_orchestrator
    return orchestrator


@router.post("", response_model=SubmitWorkflowResponse, status_code=202)
async def submit_workflow(
    request: SubmitWorkflowRequest,
    session: AsyncSession = Depends(get_session),
):
    """Submit a new workflow job for asynchronous execution.

    Returns 202 Accepted with a job_id for status polling.
    """
    orchestrator = _get_orchestrator()

    # Validate workflow type exists
    repo = WorkflowRepository(session)
    type_def = await repo.get_type_definition(request.workflow_type)
    if not type_def:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "WORKFLOW_SCHEMA_ERROR",
                "field": "workflow_type",
                "message": f"Unregistered workflow type: '{request.workflow_type}'",
            },
        )

    # Validate input against the input schema
    import jsonschema
    try:
        jsonschema.validate(request.input, type_def.input_schema)
    except jsonschema.ValidationError as e:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "WORKFLOW_VALIDATION_ERROR",
                "field": f"input.{'.'.join(str(p) for p in e.absolute_path)}",
                "message": e.message,
            },
        )

    # Submit via orchestrator
    job = await orchestrator.submit_job(
        workflow_type=request.workflow_type,
        input_data=request.input,
        session=session,
        webhook_url=request.webhook_url,
        priority=request.priority,
    )

    return SubmitWorkflowResponse(
        job_id=str(job.job_id),
        workflow_type=job.workflow_type,
        status=job.status,
        created_at=job.created_at.isoformat(),
        polling_url=f"/api/v1/workflows/{job.job_id}",
        estimated_duration_seconds=type_def.max_duration_seconds if type_def.max_duration_seconds < 86400 else None,
    )


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_workflow_status(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """Get the current status and progress of a workflow job."""
    repo = WorkflowRepository(session)
    job = await repo.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "WORKFLOW_NOT_FOUND",
                "field": "job_id",
                "message": f"No workflow job found with ID {job_id}",
            },
        )
    return JobStatusResponse(
        job_id=str(job.job_id),
        workflow_type=job.workflow_type,
        status=job.status,
        current_state=job.current_state,
        progress=job.progress,
        checkpoint=_sanitize_checkpoint(job.checkpoint_data),
        result=job.result,
        error=job.error,
        created_at=job.created_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at else None,
        updated_at=job.updated_at.isoformat(),
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        heartbeat_at=job.heartbeat_at.isoformat() if job.heartbeat_at else None,
        retry_count=job.retry_count,
    )


@router.post("/{job_id}/cancel", response_model=CancelJobResponse)
async def cancel_workflow(job_id: uuid.UUID):
    """Cancel a pending or running workflow job."""
    orchestrator = _get_orchestrator()
    job = await _get_job_or_404(job_id)

    if job.status not in ("pending", "running"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "WORKFLOW_NOT_RUNNING",
                "field": "job_id",
                "message": f"Job is already in terminal state: {job.status}",
            },
        )

    success = await orchestrator.cancel_job(job_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to cancel job")

    return CancelJobResponse(
        job_id=str(job_id),
        status="cancelled",
        previous_status=job.status,
        cancelled_at=datetime.utcnow().isoformat(),
    )


@router.post("/{job_id}/retry", response_model=RetryJobResponse)
async def retry_workflow(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """Retry a failed workflow job from its last checkpoint."""
    job = await _get_job_or_404(job_id)

    if job.status != "failed":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "WORKFLOW_NOT_FAILED",
                "field": "job_id",
                "message": f"Job is in '{job.status}' state. Only 'failed' jobs can be retried.",
            },
        )

    repo = WorkflowRepository(session)
    updated = await repo.increment_retry(job_id)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to retry job")

    return RetryJobResponse(
        job_id=str(job_id),
        status=updated.status,
        previous_status="failed",
        retry_count=updated.retry_count,
        retried_at=datetime.utcnow().isoformat(),
    )


@router.get("/{job_id}/events", response_model=JobEventListResponse)
async def get_workflow_events(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """Get the event history for a workflow job."""
    await _get_job_or_404(job_id)  # verify job exists
    repo = WorkflowRepository(session)
    events = await repo.get_events(job_id)
    return JobEventListResponse(
        job_id=str(job_id),
        events=[
            JobEventResponse(
                event_id=e.id,
                state=e.state,
                event_type=e.event_type,
                timestamp=e.timestamp.isoformat(),
                payload=e.payload,
            )
            for e in events
        ],
    )


@router.get("", response_model=JobListResponse)
async def list_workflows(
    status: Optional[str] = Query(None, description="Filter by status"),
    workflow_type: Optional[str] = Query(None, description="Filter by workflow type"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """List workflow jobs with optional filters."""
    repo = WorkflowRepository(session)
    jobs, total = await repo.list_jobs(
        status=status,
        workflow_type=workflow_type,
        limit=limit,
        offset=offset,
    )
    return JobListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[
            JobListItem(
                job_id=str(j.job_id),
                workflow_type=j.workflow_type,
                status=j.status,
                current_state=j.current_state,
                progress=j.progress,
                error=j.error,
                created_at=j.created_at.isoformat(),
                updated_at=j.updated_at.isoformat(),
            )
            for j in jobs
        ],
    )


# ── Helpers ─────────────────────────────────────────────────────────────

async def _get_job_or_404(job_id: uuid.UUID) -> JobStatusResponse:
    """Fetch a job and raise 404 if not found."""
    from app.db.config import SessionLocal
    async with SessionLocal() as session:
        repo = WorkflowRepository(session)
        job = await repo.get_job(job_id)
        if not job:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "WORKFLOW_NOT_FOUND",
                    "field": "job_id",
                    "message": f"No workflow job found with ID {job_id}",
                },
            )
        return job


def _sanitize_checkpoint(checkpoint: dict) -> dict:
    """Strip large page content from checkpoint before returning over the API."""
    sanitized = dict(checkpoint)
    pages_state = sanitized.get("pages_state")
    if pages_state and "results" in pages_state:
        # Return count/metadata only, not full content
        results = pages_state["results"]
        sanitized["pages_state"] = {
            "total": pages_state.get("total", 0),
            "generated": len(results),
            "failed": pages_state.get("failed", 0),
            "current_page_title": results[-1].get("title") if results else None,
            "current_page_index": results[-1].get("page_index") if results else None,
        }
    return sanitized
```

### 4.7 Application Wiring: `app/main.py` Changes

Add to the `lifespan` context manager:

```python
# At top of file
from app.services.workflow.orchestrator import WorkflowOrchestrator
from app.services.workflow import (  # noqa: F401 — import to trigger step registration
    steps.course_generation,
    steps.scorm_export,
)

# Inside lifespan() — startup phase, before yield:
orchestrator = WorkflowOrchestrator(
    worker_id=os.getenv("WORKFLOW_WORKER_ID", f"worker-{os.uname().nodename}"),
    max_concurrency=int(os.getenv("WORKFLOW_MAX_CONCURRENCY", "4")),
)
app.state.workflow_orchestrator = orchestrator
await orchestrator.start()

# After yield — shutdown phase:
await orchestrator.stop()

# Add to router imports and api_router include:
from app.routers import workflows as workflows_router
api_router.include_router(workflows_router)
```

---

## 5. Environment Variables

| Variable | Default | Required | Description |
|---|---|---|---|
| `WORKFLOW_WORKER_ID` | `worker-1` | No | Unique worker instance identifier (used for DB locks) |
| `WORKFLOW_MAX_CONCURRENCY` | `4` | No | Maximum number of jobs processed simultaneously |
| `WORKFLOW_POLL_INTERVAL` | `1.0` | No | Seconds between pending-job poll cycles |
| `WORKFLOW_HEARTBEAT_INTERVAL` | `5.0` | No | Seconds between heartbeat updates for running jobs |
| `WORKFLOW_LOCK_TIMEOUT_MS` | `5000` | No | PG lock_timeout for `SELECT FOR UPDATE` queries |
| `WORKFLOW_STALE_THRESHOLD` | `30` | No | Seconds without heartbeat to consider a job stale |
| `WORKFLOW_ENABLED` | `true` | No | Feature gate; set to `false` to disable background processing |
| `AI_GENERATION_MODEL` | `claude-sonnet-4-20250514` | No | Default LLM model for generation steps |
| `AI_GENERATION_RETRY_COUNT` | `3` | No | Page-level LLM retries on validation failure |
| `AI_GENERATION_TEMPERATURE` | `0.3` | No | LLM temperature for generation steps |
| `AI_GENERATION_MAX_TOKENS` | `4096` | No | Max tokens per page generation |
| `DATABASE_URL` | *(from components)* | Yes | PostgreSQL connection string with asyncpg driver |

**render.yaml additions:**

```yaml
envVars:
  - key: WORKFLOW_ENABLED
    value: true
  - key: WORKFLOW_MAX_CONCURRENCY
    value: 4
  - key: AI_GENERATION_MODEL
    value: claude-sonnet-4-20250514
  - key: AI_GENERATION_TEMPERATURE
    value: 0.3
```

---

## 6. Feature Flags

Defined in `app/utils/feature_flags.py`. Add new flag:

```python
'durable_workflow_engine': FeatureFlag(
    name='durable_workflow_engine',
    enabled=False,
    description='Enable the durable workflow engine for long-running AI jobs',
    environments=[Environment.DEVELOPMENT, Environment.QA, Environment.STAGING, Environment.PRODUCTION]
),
```

Use the decorator on the router endpoints:

```python
from app.utils.feature_flags import require_feature_async
from fastapi import Depends

@router.post("", response_model=SubmitWorkflowResponse, status_code=202)
async def submit_workflow(
    request: SubmitWorkflowRequest,
    _: bool = Depends(require_feature_async("durable_workflow_engine")),
    session: AsyncSession = Depends(get_session),
):
    ...
```

Also gate the orchestrator startup:

```python
from app.utils.feature_flags import is_feature_enabled

if is_feature_enabled("durable_workflow_engine"):
    orchestrator = WorkflowOrchestrator(...)
    app.state.workflow_orchestrator = orchestrator
    await orchestrator.start()
```

---

## 7. Test Scenarios

### 7.1 Unit Test: WorkflowJob ORM Model

**Path:** `tests/test_workflow_orm.py`

| ID | Scenario | Given | When | Then |
|---|---|---|---|---|
| WF-ORM-01 | Create workflow job | A valid `WorkflowJob()` is constructed with `workflow_type="course_generation"`, valid `input` JSON, `priority=0` | Call `session.add(job); session.commit()` | Job is persisted with `job_id` UUID, `status="pending"`, `current_state="validate_input"`, `progress=0.0`, `created_at` set |
| WF-ORM-02 | Status constraint | A job is set to `status="invalid_status"` | Attempt to insert | DB raises `CheckViolation` because `"invalid_status"` is not in the CHECK constraint list |
| WF-ORM-03 | Job expiry default | Create a job without specifying `expires_at` | Commit and reload | `expires_at` defaults to `created_at + 24 hours` |
| WF-ORM-04 | Cascade delete events | `WorkflowJob` with 3 `WorkflowJobEvent` rows | Delete the job | Events are auto-deleted via `ON DELETE CASCADE` |

### 7.2 Unit Test: WorkflowRepository

**Path:** `tests/test_workflow_repository.py`

| ID | Scenario | Given | When | Then |
|---|---|---|---|---|
| WF-REPO-01 | Create and retrieve type definition | New `workflow_type="test_flow"` with valid `input_schema` and `state_machine` | `repo.register_type_definition(...)` then `repo.get_type_definition("test_flow")` | Returns the definition; `display_name` matches; `is_active=True` |
| WF-REPO-02 | Update type definition is upsert | Existing `test_flow` definition | `repo.register_type_definition(...)` with new `display_name` | `display_name` is updated; no duplicate key error |
| WF-REPO-03 | try_lock_pending returns highest-priority job | Jobs with priority -5, 0, 10 all in `pending` status | `repo.try_lock_pending("worker-1")` | Returns the job with `priority=10`; job status becomes `running`; `locked_by="worker-1"` |
| WF-REPO-04 | try_lock_pending SKIP LOCKED for locked row | Job already locked by `worker-2` (status=running, locked_by=worker-2) | `repo.try_lock_pending("worker-1")` | Returns `None` (no pending job available) |
| WF-REPO-05 | try_lock_pending ignores expired jobs | Job past `expires_at` with status=`pending` | `repo.try_lock_pending("worker-1")` | Returns `None`; expired job is not picked up |
| WF-REPO-06 | Transition to complete | Job in `status="running"`, `current_state="generate_pages"` | `repo.transition(..., new_status="complete", new_state="complete", progress=1.0)` | `status="complete"`, `locked_by=NULL`, `completed_at` is set, `progress=1.0` |
| WF-REPO-07 | Transition to failed sets error | Job in `status="running"` | `repo.transition(..., new_status="failed", error={"code":"TEST_ERROR"})` | `status="failed"`, `error={"code":"TEST_ERROR"}`, `locked_by=NULL` |
| WF-REPO-08 | Heartbeat updates timestamp | Job in `status="running"` | Call `repo.heartbeat(job_id)` | `heartbeat_at` is updated to near-current time |
| WF-REPO-09 | Append event | Existing running job | `repo.append_event(job_id, "generate_pages", "progress_update", {"progress":0.5})` | Event row is created; `event_type="progress_update"`; `timestamp` is set |
| WF-REPO-10 | Get events returns ordered list | 10 events appended | `repo.get_events(job_id)` | Returns list of 10 events ordered by `timestamp ASC` |
| WF-REPO-11 | find_stale_running_jobs | Job with `status="running"`, `heartbeat_at=NOW()-60s` | `repo.find_stale_running_jobs()` | Returns the job |
| WF-REPO-12 | find_stale_running_jobs skips recent heartbeats | Job with `heartbeat_at=NOW()-5s` | `repo.find_stale_running_jobs(stale_threshold_seconds=30)` | Returns empty list |
| WF-REPO-13 | find_expired_jobs | Job with `expires_at < NOW()`, `status="pending"` | `repo.find_expired_jobs()` | Returns the job |
| WF-REPO-14 | increment_retry resets to pending | Job in `status="failed"` | `repo.increment_retry(job_id)` | `status="pending"`, `retry_count` incremented, `locked_by=NULL` |
| WF-REPO-15 | Create job with max_duration_seconds | `max_duration_seconds=3600` | `repo.create_job(...)` | `expires_at = created_at + 3600s` |

### 7.3 Unit Test: WorkflowOrchestrator

**Path:** `tests/test_workflow_orchestrator.py`

| ID | Scenario | Given | When | Then |
|---|---|---|---|---|
| WF-ORC-01 | State machine advances step-by-step | Job with states [A -> B -> complete]; step A succeeds, step B succeeds | `_execute_job()` runs | Status transitions: running -> running -> complete; events: state_entered(A), step_completed(A), state_entered(B), step_completed(B), job_completed |
| WF-ORC-02 | Step failure triggers retry | Job with `max_retries=3`; step returns `success=False` on attempt 1 | `_execute_job()` runs | `increment_retry` called; job reset to pending; no dead-letter transition |
| WF-ORC-03 | Max retries exceeded moves to failed | `max_retries=3`; all 3 attempts fail | `_execute_job()` runs each retry | After 3rd failure: status=final=`failed`, error populated |
| WF-ORC-04 | Step timeout moves to failed | Step configured with `timeout_s=1`; step function sleeps 10s | `_execute_job()` runs | After ~1s: status=failed, error.code=STEP_TIMEOUT |
| WF-ORC-05 | Unknown state raises ValueError | State machine has no definition for current_state | `_execute_job()` runs | Status becomes `failed` with UNHANDLED_ERROR |
| WF-ORC-06 | Unknown step raises ValueError | No step registered for (type, state) | `_execute_job()` runs | Status becomes `failed` with UNHANDLED_ERROR |
| WF-ORC-07 | Concurrency limit enforced | 10 pending jobs; `max_concurrency=2` | Orchestrator runs 10 poll cycles | At most 2 jobs active simultaneously at any point |
| WF-ORC-08 | Recover stale jobs on start | 3 jobs with `status="running"` and heartbeat 60s stale | `_recover_stale_jobs()` during `start()` | Jobs reset to `status="pending"`, `locked_by=NULL`, `error.code=WORKER_RECOVERY` |
| WF-ORC-09 | Webhook fired on completion | Job with `webbook_url="https://example.com/hook"` | After transition to complete | HTTP POST to webhook with `{job_id, status: "complete", result}` within 1s |
| WF-ORC-10 | Cancel running job | Job in `status="running"`, active task | `cancel_job(job_id)` | status=cancelled, task.cancel() called, event appended |
| WF-ORC-11 | Cancel non-running job returns False | Job in `status="complete"` | `cancel_job(job_id)` | Returns False, no status change |

### 7.4 Integration Test: API Endpoints

**Path:** `tests/test_workflows_api.py`

| ID | Scenario | Given | When | Then |
|---|---|---|---|---|
| WF-API-01 | Submit workflow returns 202 | Valid `SubmitWorkflowRequest` with registered type and valid input | `POST /api/v1/workflows` | Status 202; body contains `job_id`, `status="pending"`, `polling_url` |
| WF-API-02 | Submit unregistered type returns 422 | `workflow_type="nonexistent"` | `POST /api/v1/workflows` | Status 422; `code=WORKFLOW_SCHEMA_ERROR` |
| WF-API-03 | Submit invalid input per schema returns 422 | Workflow type has `input_schema` requiring `{import_job_id: string}`; request omits it | `POST /api/v1/workflows` | Status 422; `code=WORKFLOW_VALIDATION_ERROR` |
| WF-API-04 | Poll status returns current state | Job submitted, orchestrator running | `GET /api/v1/workflows/{job_id}` | Status 200; body matches `JobStatusResponse`; `status != "pending"` after processing |
| WF-API-05 | Poll non-existent job returns 404 | Random UUID | `GET /api/v1/workflows/{uuid}` | Status 404; `code=WORKFLOW_NOT_FOUND` |
| WF-API-06 | Cancel running job | Job currently in `running` status | `POST /api/v1/workflows/{job_id}/cancel` | Status 200; `status="cancelled"` |
| WF-API-07 | Cancel complete job returns 409 | Job in `complete` status | `POST /api/v1/workflows/{job_id}/cancel` | Status 409; `code=WORKFLOW_NOT_RUNNING` |
| WF-API-08 | Retry failed job | Job in `failed` status | `POST /api/v1/workflows/{job_id}/retry` | Status 200; `status="pending"`, `retry_count >= 1` |
| WF-API-09 | Retry non-failed job returns 409 | Job in `complete` status | `POST /api/v1/workflows/{job_id}/retry` | Status 409; `code=WORKFLOW_NOT_FAILED` |
| WF-API-10 | List jobs filters by status | 10 jobs: 5 complete, 3 running, 2 pending | `GET /api/v1/workflows?status=pending` | `total=2`; all items have `status="pending"` |
| WF-API-11 | List jobs limits and offsets | 50 total jobs | `GET /api/v1/workflows?limit=10&offset=10` | 10 items; `total=50`; second page |
| WF-API-12 | Get events returns history | Job with 3 state transitions | `GET /api/v1/workflows/{job_id}/events` | Status 200; `events` array with 3+ entries ordered by timestamp |
| WF-API-13 | Feature flag gates endpoint | `FEATURE_DURABLE_WORKFLOW_ENGINE=false` | `POST /api/v1/workflows` | Status 404 (feature not available) |
| WF-API-14 | Large checkpoint sanitized in response | Job with 20 pages of generated content in checkpoint | `GET /api/v1/workflows/{job_id}` | `checkpoint.pages_state` has count/metadata only; no full page content |

### 7.5 End-to-End Test: Course Generation Workflow

**Path:** `tests/test_workflow_course_generation_e2e.py`

| ID | Scenario | Given | When | Then |
|---|---|---|---|---|
| WF-E2E-01 | Full course generation lifecycle | Approved import job with 3-page plan; LLM mocked to return valid content for each page | Submit workflow; poll until complete | Status becomes `complete`; `result.batch_proposal_id` is set; `checkpoint.pages_state.generated=3` |
| WF-E2E-02 | Page validation failure triggers LLM retry | LLM returns invalid content on 1st attempt for page 2; returns valid content on 2nd attempt | Submit workflow; poll until complete | Status becomes `complete`; `retry_count=1`; all 3 pages generated |
| WF-E2E-03 | LLM failure exhausts retries | LLM returns invalid content for page 1 on all 3 retries | Submit workflow; poll until terminal | Status becomes `failed`; `error.code` includes page index 0 and validation errors |
| WF-E2E-04 | LLM API timeout | LLM client hangs for 120s; step timeout is 30s | Submit workflow; wait 35s | Status becomes `failed`; `error.code=STEP_TIMEOUT` |
| WF-E2E-05 | Progress updates visible | 10-page generation; LLM mock returns immediately per page | Poll every 0.5s during execution | Progress values: 0.05, 0.1, 0.2, ..., 1.0; each page increment visible |
| WF-E2E-06 | Process restart recovery | Job in `running` state, `heartbeat_at` is 60s old | Start new orchestrator; poll job | Status becomes `pending` then `running`; continues from last checkpoint |
| WF-E2E-07 | Cancel while pages being generated | Job in `generate_pages` state, 4 of 10 pages done | POST cancel | Status becomes `cancelled`; no batch proposal created |

### 7.6 Integration Test: Export + Workflow Handoff

**Path:** `tests/test_export_workflow_integration.py`

| ID | Scenario | Given | When | Then |
|---|---|---|---|---|
| WF-EXP-01 | Large course auto-routes through workflow | Course with 80 pages, 150 assets triggers export workflow | Submit SCORM export request | System creates `WorkflowJob` with `workflow_type="scorm_export"`; returns 202 not 200 |
| WF-EXP-02 | Small course exports synchronously | Course with 3 pages, 0 assets | Submit SCORM export request | Returns 200 with ZIP stream as today (no workflow) |

---

## 8. Task Breakdown

### Task 8.1 — DB Schema & Alembic Migration (3 SP)

**Files to create/modify:**
- `app/models/workflow.py` (new)
- `alembic/versions/20260614_0001_create_workflow_tables.py` (new)

**Acceptance Criteria:**
- `WorkflowJob` ORM model with all columns matching spec section 3.
- `WorkflowTypeDefinition` ORM model with JSONB columns for schemas and state machine.
- `WorkflowJobEvent` ORM model with indexes.
- Alembic migration creates all three tables with CHECK constraints, foreign keys, partial indexes.
- Down-migration drops all three tables.
- `Base.metadata.create_all` (dev path) also creates the tables.
- All models importable from `app.models`.

### Task 8.2 — WorkflowRepository (3 SP)

**File:** `app/repositories/workflow_repository.py` (new)

**Acceptance Criteria:**
- All 15+ repository methods implemented as async functions.
- `try_lock_pending` uses raw SQL with `SELECT ... FOR UPDATE SKIP LOCKED` and `SET LOCAL lock_timeout`.
- `transition` uses UPDATE ... RETURNING for atomic status change.
- `append_event` creates immutable event rows.
- `find_stale_running_jobs` uses heartbeat timestamp threshold.
- `find_expired_jobs` uses `expires_at` boundary.
- All methods properly commit and handle rollback on error.
- Unit tests pass (WF-REPO-01 through WF-REPO-15).

### Task 8.3 — WorkflowOrchestrator (5 SP)

**File:** `app/services/workflow/orchestrator.py` (new)

**Acceptance Criteria:**
- `start()` spawns `_poll_loop()` as asyncio task.
- `_poll_loop()` respects `max_concurrency` (tracks active tasks in `_active_jobs` dict).
- `_execute_job()` loads state machine from type definition, iterates states until terminal.
- Step timeout enforced via `asyncio.wait_for()`.
- Retry logic: on step failure, increments retry count, resets to pending; on exhaustion, transitions to failed.
- `_recover_stale_jobs()` runs on start, resets stale running jobs to pending with recovery error.
- `_expire_jobs()` marks past-expiry jobs as failed.
- Webhook delivery for complete/failed terminal states.
- `stop()` cancels active tasks gracefully with 10s timeout.
- Orchestrator instantiated in `app.main.py` lifespan; starts on boot, stops on shutdown.
- Unit tests pass (WF-ORC-01 through WF-ORC-11).

### Task 8.4 — Step Registry & Course Generation Steps (3 SP)

**Files:**
- `app/services/workflow/__init__.py` (new)
- `app/services/workflow/step_registry.py` (new)
- `app/services/workflow/steps/__init__.py` (new)
- `app/services/workflow/steps/course_generation.py` (new)
- `app/services/workflow/steps/scorm_export.py` (new)

**Acceptance Criteria:**
- `StepRegistry` supports `register` decorator and `get` lookup by (workflow_type, state_name).
- `course_generation` steps registered: `validate_input`, `generate_pages`, `validate_course`, `create_batch_proposal`.
- `generate_pages` step iterates per-page, calls LLM, validates output, updates checkpoint after each page.
- Step functions return `StepResult(success=True/False, checkpoint_data, progress, error)`.
- All step files auto-imported at app startup (via `__init__.py` or `app/main.py` imports) so decorators fire.

### Task 8.5 — REST Router & Pydantic Schemas (3 SP)

**File:** `app/routers/workflows.py` (new)

**Acceptance Criteria:**
- `POST /api/v1/workflows` accepts JSON body; validates workflow_type against DB; validates input against `input_schema` via `jsonschema.validate()`; returns HTTP 202.
- `GET /api/v1/workflows/{job_id}` returns full `JobStatusResponse` with sanitized checkpoint.
- `POST /api/v1/workflows/{job_id}/cancel` transitions to `cancelled` state.
- `POST /api/v1/workflows/{job_id}/retry` resets failed job to pending.
- `GET /api/v1/workflows/{job_id}/events` returns ordered event log.
- `GET /api/v1/workflows` lists jobs with optional filters, pagination.
- All endpoints gated by `require_feature_async("durable_workflow_engine")`.
- Error responses match existing `error_envelope.py` conventions.
- All Pydantic `BaseModel` request/response schemas defined in the same file.
- Router included in `api_router` in `app/main.py`.
- Integration tests pass (WF-API-01 through WF-API-14).

### Task 8.6 — Feature Flag & Env Config (1 SP)

**Files modified:**
- `app/utils/feature_flags.py` (add `durable_workflow_engine` flag)
- `render.yaml` (add workflow env vars)

**Acceptance Criteria:**
- Flag `durable_workflow_engine` explicitly registered in `_initialize_flags()`.
- Flag enabled for all environments (gated by env var `FEATURE_DURABLE_WORKFLOW_ENGINE`).
- `WORKFLOW_ENABLED` env var controls whether orchestrator starts at all (app-level kill switch).
- Orchestrator wires into lifespan conditionally via `is_feature_enabled(...)`.
- All env vars documented with defaults.

### Task 8.7 — SCORM Export Workflow Step (2 SP)

**File:** `app/services/workflow/steps/scorm_export.py` (new)

**Acceptance Criteria:**
- Registers `scorm_export` workflow with states: `validate_course`, `generate_manifest`, `package_assets`, `create_zip`, `complete`.
- `validate_course` step runs the same `_validate_course_for_export` logic from `app/routers/export.py`.
- `package_assets` step uses `AssetPackager` to collect and hash assets.
- `create_zip` step builds the ZIP in a temp directory and uploads to persistent storage; stores the download URL in checkpoint.
- Large courses (>80 pages, >100 assets) auto-route to workflow; small courses stay synchronous (determined by input validation step which raises a special signal for direct return).
- Webhook payload includes `download_url` for completed exports.

### Task 8.8 — Observability & Telemetry (2 SP)

**Files modified:**
- `app/services/workflow/orchestrator.py` (add OpenTelemetry spans)
- Logging configuration

**Acceptance Criteria:**
- Every state transition emits a structured log line with: `job_id`, `workflow_type`, `state`, `event_type`, `duration_ms` (since last state entered).
- `workflow_job_events` table captures all transitions for audit.
- Heartbeat loop logs a debug-line every beat.
- Optionally: OpenTelemetry span for each state execution (parent span = job execution, child span = step function).
- Error telemetry: failed transitions log at ERROR level with full stack trace in `error.details`.

### Task 8.9 — Unit & Integration Tests (5 SP)

**Files:**
- `tests/test_workflow_orm.py`
- `tests/test_workflow_repository.py`
- `tests/test_workflow_orchestrator.py`
- `tests/test_workflows_api.py`
- `tests/test_workflow_course_generation_e2e.py`
- `tests/test_export_workflow_integration.py`

**Acceptance Criteria:**
- All test scenarios from section 7 pass.
- ORM tests use the existing `conftest.py` SQLite override.
- Repository tests use `AsyncSession` with a fresh transaction per test, rolled back after.
- Orchestrator tests use mocked `StepRegistry` and a lightweight in-memory DB.
- API tests use `TestClient` with dependency overrides.
- E2E tests mock `LLMClient` at the class level.
- Test coverage > 90% for all new code (measured via `pytest-cov`).

### Task 8.10 — Frontend Polling Integration (2 SP)

**Files (frontend — repo assumed at `../frontend`):**

**Acceptance Criteria:**
- Frontend workflow component calls `POST /api/v1/workflows` to initiate jobs.
- Displays progress bar and current state text by polling `GET /api/v1/workflows/{job_id}` every 2s.
- Shows error state with retry button when `status=failed`.
- Shows cancel button when `status=running`.
- Emits telemetry events for job lifecycle (submitted, progress, completed, failed, cancelled).
- Integrates with existing import/export UI: export screen uses workflow for large courses, course generation screen uses workflow by default.
- Handles 202 response correctly (some paths return 202, some return direct result for small jobs).

---

## References

- **ImportJob model** (`app/models/persisted_course.py:148-183`) — existing job pattern to migrate from
- **ImportJobRepository** (`app/repositories/import_job_repository.py`) — existing CRUD pattern to replicate
- **Feature flags** (`app/utils/feature_flags.py`) — gating infrastructure
- **Error envelope** (`app/utils/error_envelope.py`) — response shape convention
- **DB config** (`app/db/config.py`) — async session factory
- **conftest.py** (`tests/conftest.py`) — test DB override pattern
- **US-AI-019** — course generation flow that uses this workflow engine
- **US-AI-023** — AI chat endpoint that may submit workflow jobs for long-running tool batches
- **US-AI-026** — observability foundation for telemetry
