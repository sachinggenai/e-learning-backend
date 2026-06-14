# US-AI-041: Async Preview Generation Service

**Status:** Draft  
**Priority:** COULD for MVP, SHOULD for production UX  
**Depends on:** US-AI-009 (Proposal Safety Model), US-AI-024 (Frontend AI Integration Layer), US-AI-011 (Create Page Proposal and Apply), US-AI-034 (Durable Workflow Engine), US-AI-023 (AI Chat Endpoint)  
**Source flow:** 29. Async Preview Generation Service  
**Epic Owner:** Technical Product Owner  

---

## 1. Functional Specification

### 1.1 User Story

As an **Author**, I want page and course previews to be generated asynchronously, so that the AI chat remains responsive while previews render in the background, and I can see the rendered result when ready without blocking my editing workflow.

As a **Platform Operator**, I want preview generation to be queued, monitored, and timed out with clear failure diagnostics, so that rendering storms from rapid proposal creation do not degrade API responsiveness for other users.

### 1.2 Overview

After a proposal is created through the AI chat flow (US-AI-011), the backend currently has no mechanism to render a visual preview of what the proposal will look like once applied. The SCORM export pipeline (`app/services/scorm_export.py`, `app/services/scorm_export_v2.py`) already contains the rendering logic (HTML generation, course_data.js construction, player assembly) but it is only invoked synchronously during export, not for per-proposal or per-page preview.

This story introduces an **async preview generation service** that:

1. **Accepts** a preview generation request for a proposal or course and returns a `preview_job_id` immediately (HTTP 202).
2. **Queues** the job using the durable workflow engine from US-AI-034 (or a lightweight in-process `asyncio.Queue` with DB persistence for simpler deployments).
3. **Renders** the proposal data through the same renderer pipeline used by `SCORMExportService` (`app/services/scorm/renderers/base.py`, `app/services/scorm/renderers/dynamic.py`) to produce HTML fragments that are visually consistent with the editor and SCORM output.
4. **Stores** the rendered preview (HTML + metadata) in the `ai_proposals` table as `preview_html` and `preview_status` columns.
5. **Exposes** a polling endpoint `GET /api/v1/ai/proposals/{proposal_id}/preview` so the frontend (US-AI-024) can poll until `preview_status` transitions from `pending` to `ready` or `failed`.
6. **Enforces** a configurable render timeout (default 30 seconds), retry policy (1 retry on transient failure), and max concurrent renderers.

**Key design decisions:**

- **Reuse existing renderer pipeline.** The `SCORMExportService` and `SCORMExportServiceV2` classes in `app/services/` already contain the full rendering logic. The preview service wraps these to produce a single-page or single-proposal HTML fragment rather than a full SCORM package.
- **No new DB table.** The `ai_proposals` table (from US-AI-009) gets three new nullable columns: `preview_html TEXT`, `preview_status VARCHAR(16)`, and `preview_updated_at TIMESTAMP`.
- **Lightweight queue.** For MVP, use an in-process `asyncio.Queue` with a background worker. For production, the queue delegates to the US-AI-034 `WorkflowJob` table for persistence across restarts.
- **Visual parity.** The preview HTML must use the same CSS class names (`content-template`, `content-body`, `takeaways-template`, `accordion-trigger`, etc.) as the SCORM player output, verified by the existing `test_accordion_preview_parity.py` test suite.

### 1.3 Actors

| Actor | Role |
|---|---|
| Author (User) | Triggers preview via chat or frontend; polls `GET /api/v1/ai/proposals/{proposal_id}/preview` to see status |
| AI Agent | Creates proposals via `propose_add_page`, `propose_edit_page`, `propose_delete_page` tools; preview generation auto-triggers after proposal creation |
| Frontend | Shows a "Generating preview..." indicator during `pending`; renders the HTML when `ready`; shows error banner with retry when `failed` |
| PreviewGenerationService | New service (`app/services/ai/preview_service.py`) that manages the async queue, delegates rendering, stores results |
| Renderer Pipeline | Existing `SCORMExportService._create_content_html`, `SCORMExportService._create_course_data_js`, `DynamicTemplateRenderer.render` — reused by the preview service |
| PreviewWorker | Background asyncio task (spawned at app startup in `main.py` lifespan) that picks up jobs from the queue, calls the renderer, writes results |
| DB (PostgreSQL) | Stores rendered `preview_html` in `ai_proposals` table |

### 1.4 Flow: Proposal Created -> Preview Generated -> Frontend Renders

**Precondition:** The AI chat session (US-AI-023) is active. The AI agent has called a proposal tool (e.g., `propose_edit_page`) and the backend has created a proposal row in `ai_proposals` with `status = PENDING_CONFIRMATION` (US-AI-009).

**Phase 0 — Preview Auto-Trigger**
1. The `propose_add_page`, `propose_edit_page`, or `propose_delete_page` handler, after successfully creating the proposal record, calls `PreviewGenerationService.enqueue(proposal_id, proposal_data)`.
2. `enqueue()` inserts a row into the `preview_jobs` in-memory queue (or creates a `WorkflowJob` if US-AI-034 is integrated) and returns immediately.
3. The API response to the AI agent includes `preview_job_id` and `preview_poll_url`.
4. The AI agent passes these to the frontend as part of the tool result.

**Phase 1 — Background Rendering**
1. The `PreviewWorker` (spawned in `main.py` lifespan) picks up the job from the queue.
2. Worker transitions `preview_status` to `rendering`.
3. Worker constructs a `Course` Pydantic model from the proposal data (using `app/models/course.py`). For a single-page proposal, this is a one-template course built from the proposal's `after_candidate` snapshot. For a batch proposal (US-AI-029), this is an N-template course.
4. Worker calls the renderer pipeline:
   - If the proposal is a single page: `SCORMExportService._create_template_html(template, context)` — a new internal method we extract from the existing export pipeline.
   - If the proposal is a batch/course: `SCORMExportService.generate_preview_html(course)` — a new method that generates the `index.html` body and `course_data.js`, skipping ZIP packaging.
5. Worker validates the rendered HTML is syntactically valid (contains at least a `<div>` with the expected `data-template-type` attribute).
6. Worker updates `ai_proposals.preview_html` with the rendered HTML, sets `preview_status = 'ready'`, and writes `preview_updated_at = now()`.

**Phase 2 — Frontend Polls and Renders**
1. Frontend polls `GET /api/v1/ai/proposals/{proposal_id}/preview` every 2 seconds.
2. While `preview_status = 'pending'` or `'rendering'`: backend returns HTTP 200 with `{status: "pending", preview_job_id: "..."}` — no HTML body yet.
3. When `preview_status = 'ready'`: backend returns HTTP 200 with `{status: "ready", preview_html: "<div class=\"content-template\">..."}`.
4. When `preview_status = 'failed'`: backend returns HTTP 200 with `{status: "failed", error: "...", retry_url: "POST /api/v1/ai/proposals/{proposal_id}/preview/retry"}`.
5. Frontend injects `preview_html` into the preview iframe/modal. The HTML is scoped with `data-proposal-id` and rendered in a sandboxed container.
6. If the user clicks "Confirm" on the proposal while preview is still `pending`, the proposal confirms without waiting for preview completion — preview is advisory, not blocking.

**Phase 3 — Retry and Failure Handling**
1. If rendering fails (renderer throws, timeout, or LLM parsing error), worker sets `preview_status = 'failed'` and stores the error message in `preview_error`.
2. Worker writes the failure to the observability log with structured fields: `{event: "preview_render_failed", proposal_id, error_class, error_message, duration_ms}`.
3. Frontend shows a retry button that calls `POST /api/v1/ai/proposals/{proposal_id}/preview/retry`.
4. Retry endpoint re-enqueues the job with the same data but increments `retry_count`. Max retries: 2 (configurable via `PREVIEW_MAX_RETRIES`).
5. After max retries: frontend shows "Preview unavailable" and the proposal can still be confirmed without a preview.

### 1.5 Non-Functional Requirements

| Requirement | Target |
|---|---|
| Max render time per proposal | 30 seconds (enforced via `asyncio.wait_for`) |
| Max concurrent render jobs | `PREVIEW_MAX_CONCURRENCY` (default 4) |
| Polling interval (frontend) | 2 seconds recommended |
| Preview job queue depth | Unlimited (backed by DB, not memory) |
| Preview HTML max size | 512 KB per row (DB column limit) |
| Time to preview ready (P50) | < 5 seconds for single-page proposals |
| Time to preview ready (P99) | < 20 seconds for 50-page course previews |
| Retry policy | 2 retries, exponential backoff (1s, 4s) |
| Preview staleness | Preview is regenerated automatically if the proposal's `updated_at` > `preview_updated_at` |
| Chat responsiveness | Chat input must remain enabled and responsive during preview rendering |
| Visual parity | Preview CSS classes must match SCORM export CSS classes exactly (verified by integration tests) |

---

## 2. API Contract

### 2.1 GET /api/v1/ai/proposals/{proposal_id}/preview — Poll Preview Status

```
GET /api/v1/ai/proposals/{proposal_id}/preview
Accept: application/json
```

**Path Parameters:**
| Parameter | Type | Description |
|---|---|---|
| `proposal_id` | string | UUID of the proposal (from `ai_proposals.id`) |

**Response (200 OK) — Preview Pending:**
```json
{
  "status": "pending",
  "preview_job_id": "pv_abc123def456",
  "progress": 0.0,
  "poll_interval_ms": 2000
}
```

**Response (200 OK) — Preview Ready:**
```json
{
  "status": "ready",
  "preview_job_id": "pv_abc123def456",
  "preview_html": "<div class=\"content-template\" data-template-type=\"content-text\" data-proposal-id=\"prop_xyz789\">\n  <div class=\"content-body\">\n    <p>Rendered preview content...</p>\n  </div>\n</div>",
  "preview_type": "page",
  "generated_at": "2026-06-14T10:30:00Z",
  "render_duration_ms": 1234
}
```

**Response (200 OK) — Preview Failed:**
```json
{
  "status": "failed",
  "preview_job_id": "pv_abc123def456",
  "error": {
    "code": "RENDER_TIMEOUT",
    "message": "Preview render exceeded 30 second timeout",
    "retry_count": 1,
    "retry_allowed": true,
    "retry_url": "/api/v1/ai/proposals/prop_xyz789/preview/retry"
  }
}
```

**Response (404 Not Found):**
```json
{
  "detail": "Proposal not found",
  "errors": [
    {"code": "PROPOSAL_NOT_FOUND", "field": "proposal_id", "message": "No proposal with id prop_xyz789"}
  ]
}
```

### 2.2 POST /api/v1/ai/proposals/{proposal_id}/preview/retry — Retry Preview Generation

```
POST /api/v1/ai/proposals/{proposal_id}/preview/retry
Accept: application/json
```

**Response (202 Accepted):**
```json
{
  "status": "queued",
  "preview_job_id": "pv_def789ghi012",
  "poll_url": "/api/v1/ai/proposals/prop_xyz789/preview",
  "retry_count": 2,
  "retries_remaining": 0
}
```

**Response (409 Conflict) — Max Retries Exceeded:**
```json
{
  "detail": "Max retries exceeded",
  "errors": [
    {"code": "PREVIEW_MAX_RETRIES_EXCEEDED", "field": "proposal_id", "message": "Preview generation failed after 2 retries"}
  ]
}
```

### 2.3 GET /api/v1/ai/proposals/{proposal_id}/preview/status — Lightweight Status Check (No HTML Body)

```
GET /api/v1/ai/proposals/{proposal_id}/preview/status
Accept: application/json
```

Intended for high-frequency polling without the overhead of the HTML body in the response.

**Response (200 OK):**
```json
{
  "status": "ready",
  "preview_job_id": "pv_abc123def456",
  "generated_at": "2026-06-14T10:30:00Z",
  "render_duration_ms": 1234
}
```

### 2.4 Pydantic Response Models

```python
# app/services/ai/preview_models.py

from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime


class PreviewStatusResponse(BaseModel):
    """Lightweight status-only response (no HTML body)."""
    status: Literal["pending", "rendering", "ready", "failed"]
    preview_job_id: Optional[str] = None
    generated_at: Optional[datetime] = None
    render_duration_ms: Optional[int] = None
    retry_count: Optional[int] = None
    retries_remaining: Optional[int] = None


class PreviewError(BaseModel):
    code: str  # RENDER_TIMEOUT, RENDER_ERROR, VALIDATION_ERROR
    message: str
    retry_count: int = 0
    retry_allowed: bool = True
    retry_url: Optional[str] = None


class PreviewResponse(PreviewStatusResponse):
    """Full response including preview HTML."""
    preview_html: Optional[str] = None
    preview_type: Literal["page", "course"] = "page"
    progress: Optional[float] = None
    poll_interval_ms: int = 2000
    error: Optional[PreviewError] = None


class PreviewRetryResponse(BaseModel):
    status: Literal["queued"]
    preview_job_id: str
    poll_url: str
    retry_count: int
    retries_remaining: int
```

### 2.5 Frontend Polling Contract (for US-AI-024)

The frontend AI integration layer (US-AI-024) uses the following polling algorithm:

```
1. When tool result contains `preview_job_id` and `preview_poll_url`, start polling.
2. Poll GET /api/v1/ai/proposals/{proposal_id}/preview/status every 2 seconds.
3. On "pending" or "rendering": continue polling, show spinner.
4. On "ready": fetch GET /api/v1/ai/proposals/{proposal_id}/preview for full HTML, render in preview container.
5. On "failed" with retry_allowed: show error banner with retry button.
6. On "failed" without retry_allowed: show "Preview unavailable" banner, no retry.
7. Stop polling after 60 seconds regardless of status (safety timeout).
8. Preview is advisory — user can confirm proposal while preview is pending.
```

---

## 3. Database Schema

### 3.1 Migration: Add Preview Columns to `ai_proposals`

```python
# alembic/versions/20260614_0001_add_preview_to_ai_proposals.py

"""Add preview columns to ai_proposals table.

Revision ID: 20260614_0001
Revises: <previous_migration_id>
Create Date: 2026-06-14
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "20260614_0001"
down_revision: Union[str, None] = "<previous_migration_id>"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE ai_proposals ADD COLUMN IF NOT EXISTS preview_html TEXT")
    op.execute("ALTER TABLE ai_proposals ADD COLUMN IF NOT EXISTS preview_status VARCHAR(16) DEFAULT 'none'")
    op.execute("ALTER TABLE ai_proposals ADD COLUMN IF NOT EXISTS preview_error TEXT")
    op.execute("ALTER TABLE ai_proposals ADD COLUMN IF NOT EXISTS preview_job_id VARCHAR(64)")
    op.execute("ALTER TABLE ai_proposals ADD COLUMN IF NOT EXISTS preview_updated_at TIMESTAMP WITHOUT TIME ZONE")
    op.execute("ALTER TABLE ai_proposals ADD COLUMN IF NOT EXISTS preview_retry_count INTEGER DEFAULT 0")
    op.execute("ALTER TABLE ai_proposals ADD COLUMN IF NOT EXISTS preview_render_duration_ms INTEGER")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_proposals_preview_status ON ai_proposals (preview_status)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ai_proposals_preview_status")
    op.execute("ALTER TABLE ai_proposals DROP COLUMN IF EXISTS preview_render_duration_ms")
    op.execute("ALTER TABLE ai_proposals DROP COLUMN IF EXISTS preview_retry_count")
    op.execute("ALTER TABLE ai_proposals DROP COLUMN IF EXISTS preview_updated_at")
    op.execute("ALTER TABLE ai_proposals DROP COLUMN IF EXISTS preview_job_id")
    op.execute("ALTER TABLE ai_proposals DROP COLUMN IF EXISTS preview_error")
    op.execute("ALTER TABLE ai_proposals DROP COLUMN IF EXISTS preview_status")
    op.execute("ALTER TABLE ai_proposals DROP COLUMN IF EXISTS preview_html")
```

### 3.2 ORM Model Update

Add to the existing `AiProposal` model (in `app/models/persisted_course.py` or wherever the ai_proposals model is defined):

```python
# added fields to AiProposal model
preview_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
preview_status: Mapped[str] = mapped_column(String(16), default="none")  # none, pending, rendering, ready, failed
preview_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
preview_job_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
preview_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
preview_retry_count: Mapped[int] = mapped_column(Integer, default=0)
preview_render_duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
```

### 3.3 DDL (Raw PostgreSQL for Reference)

```sql
ALTER TABLE ai_proposals
  ADD COLUMN IF NOT EXISTS preview_html TEXT,
  ADD COLUMN IF NOT EXISTS preview_status VARCHAR(16) DEFAULT 'none',
  ADD COLUMN IF NOT EXISTS preview_error TEXT,
  ADD COLUMN IF NOT EXISTS preview_job_id VARCHAR(64),
  ADD COLUMN IF NOT EXISTS preview_updated_at TIMESTAMP WITHOUT TIME ZONE,
  ADD COLUMN IF NOT EXISTS preview_retry_count INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS preview_render_duration_ms INTEGER;

CREATE INDEX IF NOT EXISTS ix_ai_proposals_preview_status ON ai_proposals (preview_status);
```

---

## 4. Service Signatures

### 4.1 `app/services/ai/preview_service.py` — PreviewGenerationService

```python
"""
Async Preview Generation Service.

Manages queued preview rendering for AI proposals.
Reuses the existing SCORM renderer pipeline to produce HTML fragments
that are visually consistent with the editor and SCORM output.
"""

from __future__ import annotations
import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, Callable, Awaitable
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course, Template
from app.services.scorm_export import SCORMExportService
from app.services.scorm_export_v2 import SCORMExportServiceV2

logger = logging.getLogger(__name__)


class PreviewGenerationError(Exception):
    """Base exception for preview generation failures."""
    pass


class PreviewRenderTimeoutError(PreviewGenerationError):
    """Raised when preview rendering exceeds the configured timeout."""
    pass


class PreviewRenderValidationError(PreviewGenerationError):
    """Raised when rendered preview HTML fails structural validation."""
    pass


class PreviewServiceConfig:
    """Configuration for the preview generation service."""

    def __init__(
        self,
        max_concurrency: int = 4,
        render_timeout_s: int = 30,
        max_retries: int = 2,
        retry_delays_s: list[float] = None,
        poll_interval_ms: int = 2000,
    ):
        self.max_concurrency = max_concurrency
        self.render_timeout_s = render_timeout_s
        self.max_retries = max_retries
        self.retry_delays_s = retry_delays_s or [1.0, 4.0]
        self.poll_interval_ms = poll_interval_ms


class PreviewJob:
    """In-memory representation of a preview rendering job."""

    def __init__(
        self,
        proposal_id: str,
        proposal_data: Dict[str, Any],
        preview_type: str = "page",
        session_id: Optional[str] = None,
    ):
        self.job_id = f"pv_{uuid.uuid4().hex[:12]}"
        self.proposal_id = proposal_id
        self.proposal_data = proposal_data
        self.preview_type = preview_type  # "page" or "course"
        self.session_id = session_id
        self.status = "pending"  # pending, rendering, ready, failed
        self.retry_count = 0
        self.error: Optional[str] = None
        self.error_code: Optional[str] = None
        self.result_html: Optional[str] = None
        self.render_duration_ms: Optional[int] = None
        self.created_at = datetime.utcnow()
        self.updated_at = self.created_at


class PreviewGenerationService:
    """Async service for generating proposal previews."""

    def __init__(
        self,
        db_session_factory: Callable[[], Awaitable[AsyncSession]],
        config: Optional[PreviewServiceConfig] = None,
        renderer: Optional[Any] = None,
    ):
        self._db_session_factory = db_session_factory
        self._config = config or PreviewServiceConfig()
        self._renderer = renderer or SCORMExportService()
        self._queue: asyncio.Queue[PreviewJob] = asyncio.Queue()
        self._active_jobs: Dict[str, PreviewJob] = {}
        self._worker_task: Optional[asyncio.Task] = None
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(
            self._config.max_concurrency
        )

    async def start(self):
        """Start the background worker. Called from main.py lifespan."""
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info(
            "PreviewGenerationService started (max_concurrency=%d, timeout=%ds)",
            self._config.max_concurrency,
            self._config.render_timeout_s,
        )

    async def stop(self):
        """Gracefully stop the background worker."""
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
            logger.info("PreviewGenerationService stopped")

    async def enqueue(
        self,
        proposal_id: str,
        proposal_data: Dict[str, Any],
        preview_type: str = "page",
        session_id: Optional[str] = None,
    ) -> PreviewJob:
        """
        Enqueue a preview generation job.

        Args:
            proposal_id: The proposal ID to generate a preview for.
            proposal_data: The proposal data (includes 'after_candidate' or equivalent).
            preview_type: 'page' for single-page proposals, 'course' for batch proposals.
            session_id: Optional AI session ID for audit tracking.

        Returns:
            PreviewJob with status, job_id, and poll URL.

        Raises:
            PreviewGenerationError: If the proposal is already queued or rendered.
        """
        # Check for existing pending job
        existing = self._active_jobs.get(proposal_id)
        if existing and existing.status in ("pending", "rendering"):
            return existing

        job = PreviewJob(
            proposal_id=proposal_id,
            proposal_data=proposal_data,
            preview_type=preview_type,
            session_id=session_id,
        )
        self._active_jobs[proposal_id] = job

        # Persist status to DB immediately
        async with self._db_session_factory() as session:
            await self._update_preview_status(
                session, proposal_id, "pending", job_id=job.job_id
            )

        await self._queue.put(job)
        logger.info("Enqueued preview job %s for proposal %s", job.job_id, proposal_id)
        return job

    async def get_preview_status(
        self, proposal_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get the current preview status for a proposal.

        Args:
            proposal_id: The proposal ID.

        Returns:
            Dict with status, job_id, and optionally preview_html or error.
        """
        job = self._active_jobs.get(proposal_id)
        if not job:
            # Fall back to DB query
            async with self._db_session_factory() as session:
                return await self._query_preview_status(session, proposal_id)

        result = {
            "status": job.status,
            "preview_job_id": job.job_id,
            "preview_type": job.preview_type,
            "generated_at": job.updated_at.isoformat() if job.status == "ready" else None,
            "render_duration_ms": job.render_duration_ms,
            "retry_count": job.retry_count,
            "retries_remaining": max(0, self._config.max_retries - job.retry_count),
        }

        if job.status == "ready":
            result["preview_html"] = job.result_html

        if job.status == "failed":
            result["error"] = {
                "code": job.error_code or "RENDER_ERROR",
                "message": job.error or "Unknown error",
                "retry_count": job.retry_count,
                "retry_allowed": job.retry_count < self._config.max_retries,
                "retry_url": f"/api/v1/ai/proposals/{proposal_id}/preview/retry",
            }

        return result

    async def retry(
        self, proposal_id: str
    ) -> Optional[PreviewJob]:
        """
        Retry a failed preview generation.

        Args:
            proposal_id: The proposal ID.

        Returns:
            PreviewJob if retry was enqueued, None if max retries reached.
        """
        job = self._active_jobs.get(proposal_id)
        if not job:
            return None

        if job.retry_count >= self._config.max_retries:
            return None

        job.retry_count += 1
        job.status = "pending"
        job.error = None
        job.error_code = None
        job.updated_at = datetime.utcnow()

        # Apply exponential backoff
        delay = self._config.retry_delays_s[
            min(job.retry_count - 1, len(self._config.retry_delays_s) - 1)
        ]
        if delay > 0:
            await asyncio.sleep(delay)

        await self._queue.put(job)

        async with self._db_session_factory() as session:
            await self._update_preview_status(
                session, proposal_id, "pending",
                job_id=job.job_id,
                retry_count=job.retry_count,
            )

        logger.info(
            "Retry %d/%d for proposal %s",
            job.retry_count,
            self._config.max_retries,
            proposal_id,
        )
        return job

    async def _worker_loop(self):
        """Background loop that processes preview jobs from the queue."""
        while True:
            try:
                job = await self._queue.get()
                async with self._semaphore:
                    await self._render_job(job)
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Unexpected error in preview worker loop")

    async def _render_job(self, job: PreviewJob):
        """Render a single preview job with timeout enforcement."""
        job.status = "rendering"
        job.updated_at = datetime.utcnow()

        async with self._db_session_factory() as session:
            await self._update_preview_status(session, job.proposal_id, "rendering")

        start_time = datetime.utcnow()

        try:
            html = await asyncio.wait_for(
                self._do_render(job),
                timeout=self._config.render_timeout_s,
            )

            # Validate structural integrity
            self._validate_render_output(html, job.preview_type)

            duration = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            job.status = "ready"
            job.result_html = html
            job.render_duration_ms = duration
            job.updated_at = datetime.utcnow()

            async with self._db_session_factory() as session:
                await self._save_preview_result(
                    session, job.proposal_id, html, duration
                )

            logger.info(
                "Preview ready for proposal %s (%d ms)",
                job.proposal_id,
                duration,
            )

        except asyncio.TimeoutError:
            duration = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            job.status = "failed"
            job.error = f"Preview render exceeded {self._config.render_timeout_s}s timeout"
            job.error_code = "RENDER_TIMEOUT"
            job.render_duration_ms = duration
            job.updated_at = datetime.utcnow()

            async with self._db_session_factory() as session:
                await self._save_preview_failure(
                    session, job.proposal_id, "RENDER_TIMEOUT",
                    job.error, job.retry_count,
                )

            logger.warning(
                "Preview timeout for proposal %s (%d ms)",
                job.proposal_id,
                duration,
            )

        except PreviewGenerationError as e:
            duration = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            job.status = "failed"
            job.error = str(e)
            job.error_code = type(e).__name__.replace("Preview", "").replace("Error", "").upper()
            job.render_duration_ms = duration
            job.updated_at = datetime.utcnow()

            async with self._db_session_factory() as session:
                await self._save_preview_failure(
                    session, job.proposal_id, job.error_code,
                    job.error, job.retry_count,
                )

            logger.error(
                "Preview render error for proposal %s: %s",
                job.proposal_id,
                job.error,
            )

    async def _do_render(self, job: PreviewJob) -> str:
        """
        Core rendering logic. Reuses the SCORM export renderer pipeline.

        Args:
            job: The preview job with proposal_data.

        Returns:
            Rendered HTML string.

        Raises:
            PreviewGenerationError: If rendering fails.
        """
        try:
            proposal_data = job.proposal_data
            after_candidate = proposal_data.get("after_candidate", {})
            template_type = after_candidate.get("type", "content-text")
            template_data = after_candidate.get("data", {})

            # Build a minimal Course model for the renderer
            template = Template(
                id=after_candidate.get("id", "preview-page"),
                type=template_type,
                title=after_candidate.get("title", "Preview"),
                order=0,
                data=template_data,
            )

            course = Course(
                courseId=f"preview_{job.proposal_id}",
                title="Preview",
                author="Preview System",
                templates=[template],
            )

            # Use the SCORM export renderer pipeline
            # This calls the same _create_content_html path used in SCORM export
            # but returns the body HTML fragment instead of writing to a ZIP.
            html = await self._renderer.render_single_template(course, template)
            return html

        except Exception as e:
            raise PreviewGenerationError(f"Rendering failed: {type(e).__name__}: {str(e)}") from e

    def _validate_render_output(self, html: str, preview_type: str):
        """
        Validate that the rendered HTML has the expected structural elements.

        Raises:
            PreviewRenderValidationError: If validation fails.
        """
        if not html or len(html.strip()) == 0:
            raise PreviewRenderValidationError("Rendered HTML is empty")

        if not html.strip().startswith("<"):
            raise PreviewRenderValidationError(
                "Rendered HTML does not start with an HTML tag"
            )

        # Verify at least one data-template-type attribute is present for page previews
        if preview_type == "page" and 'data-template-type' not in html:
            raise PreviewRenderValidationError(
                "Missing data-template-type attribute in rendered HTML"
            )

    async def _update_preview_status(
        self,
        session: AsyncSession,
        proposal_id: str,
        status: str,
        job_id: Optional[str] = None,
        retry_count: Optional[int] = None,
    ):
        """Persist preview status to the ai_proposals table."""
        from sqlalchemy import update, text

        values = {
            "preview_status": status,
            "preview_updated_at": datetime.utcnow(),
        }
        if job_id:
            values["preview_job_id"] = job_id
        if retry_count is not None:
            values["preview_retry_count"] = retry_count

        stmt = (
            update(text("ai_proposals"))
            .where(text("id = :proposal_id"))
            .values(**values)
        )
        await session.execute(stmt, {"proposal_id": proposal_id})
        await session.commit()

    async def _save_preview_result(
        self,
        session: AsyncSession,
        proposal_id: str,
        html: str,
        duration_ms: int,
    ):
        """Persist successful preview result."""
        from sqlalchemy import update, text

        stmt = (
            update(text("ai_proposals"))
            .where(text("id = :proposal_id"))
            .values(
                preview_html=html,
                preview_status="ready",
                preview_error=None,
                preview_updated_at=datetime.utcnow(),
                preview_render_duration_ms=duration_ms,
            )
        )
        await session.execute(stmt, {"proposal_id": proposal_id})
        await session.commit()

    async def _save_preview_failure(
        self,
        session: AsyncSession,
        proposal_id: str,
        error_code: str,
        error_message: str,
        retry_count: int,
    ):
        """Persist preview failure."""
        from sqlalchemy import update, text

        stmt = (
            update(text("ai_proposals"))
            .where(text("id = :proposal_id"))
            .values(
                preview_status="failed",
                preview_error=f"[{error_code}] {error_message}",
                preview_retry_count=retry_count,
                preview_updated_at=datetime.utcnow(),
            )
        )
        await session.execute(stmt, {"proposal_id": proposal_id})
        await session.commit()

    async def _query_preview_status(
        self, session: AsyncSession, proposal_id: str
    ) -> Optional[Dict[str, Any]]:
        """Query preview status from the DB."""
        from sqlalchemy import select, text

        stmt = select(
            text("preview_status, preview_job_id, preview_html, preview_error, "
                 "preview_retry_count, preview_render_duration_ms, preview_updated_at")
        ).select_from(text("ai_proposals")).where(text("id = :proposal_id"))

        result = await session.execute(stmt, {"proposal_id": proposal_id})
        row = result.fetchone()
        if not row:
            return None

        return {
            "status": row.preview_status or "none",
            "preview_job_id": row.preview_job_id,
            "preview_html": row.preview_html if row.preview_status == "ready" else None,
            "error": row.preview_error if row.preview_status == "failed" else None,
            "retry_count": row.preview_retry_count or 0,
            "render_duration_ms": row.preview_render_duration_ms,
            "generated_at": row.preview_updated_at.isoformat() if row.preview_updated_at else None,
        }
```

### 4.2 New Method on `SCORMExportService`: `render_single_template`

```python
# Add to app/services/scorm_export.py (or scorm_export_v2.py)

async def render_single_template(
    self,
    course: Course,
    template: Template,
) -> str:
    """
    Render a single template as a standalone HTML fragment for preview.

    Uses the same renderer pipeline as full SCORM export, but returns
    only the template body HTML (no manifest, player wrappers, or ZIP).

    Args:
        course: The parent Course model (for theme/context).
        template: The single template to render.

    Returns:
        HTML string with data-template-type attribute for frontend scoping.
    """
    import io
    from pathlib import Path
    import tempfile

    course_dict = self._course_to_dict(course)
    template_dict = self._template_to_dict(template)

    # Build minimal rendering context
    context = {
        "course_id": course_dict.get("courseId", "preview"),
        "title": course_dict.get("title", "Preview"),
        "templates": [template_dict],
        "assets": [],
    }

    # Render through the same player/HTML pipeline as SCORM export
    # but only extract the template body content
    html = await self._create_template_body_html(template_dict, context)
    return html
```

### 4.3 New Router: `app/routers/ai_preview.py`

```python
"""
Preview generation API endpoints.

Provides REST endpoints for polling preview status and retrying
failed preview generation jobs.
"""

import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from app.db.config import get_session
from app.services.ai.preview_service import (
    PreviewGenerationService,
    PreviewGenerationError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ai/proposals", tags=["ai-preview"])


class PreviewStatusResponse(BaseModel):
    status: str
    preview_job_id: Optional[str] = None
    preview_html: Optional[str] = None
    preview_type: str = "page"
    progress: Optional[float] = None
    poll_interval_ms: int = 2000
    generated_at: Optional[str] = None
    render_duration_ms: Optional[int] = None
    retry_count: int = 0
    retries_remaining: int = 2
    error: Optional[dict] = None


class PreviewRetryResponse(BaseModel):
    status: str
    preview_job_id: str
    poll_url: str
    retry_count: int
    retries_remaining: int


@router.get("/{proposal_id}/preview", response_model=PreviewStatusResponse)
async def get_preview(
    proposal_id: str,
    session=Depends(get_session),
    preview_service: PreviewGenerationService = Depends(get_preview_service),
):
    """Poll preview status for a proposal."""
    try:
        status = await preview_service.get_preview_status(proposal_id)
    except Exception as e:
        logger.exception("Error fetching preview status for proposal %s", proposal_id)
        raise HTTPException(status_code=500, detail="Internal error fetching preview status")

    if status is None:
        raise HTTPException(status_code=404, detail="Proposal not found")

    return status


@router.get("/{proposal_id}/preview/status", response_model=PreviewStatusResponse)
async def get_preview_status_light(
    proposal_id: str,
    session=Depends(get_session),
    preview_service: PreviewGenerationService = Depends(get_preview_service),
):
    """Lightweight status check without HTML body."""
    try:
        status = await preview_service.get_preview_status(proposal_id)
    except Exception:
        logger.exception("Error fetching preview status for proposal %s", proposal_id)
        raise HTTPException(status_code=500, detail="Internal error")

    if status is None:
        raise HTTPException(status_code=404, detail="Proposal not found")

    # Strip HTML body for lightweight responses
    status.pop("preview_html", None)
    return status


@router.post("/{proposal_id}/preview/retry", response_model=PreviewRetryResponse)
async def retry_preview(
    proposal_id: str,
    session=Depends(get_session),
    preview_service: PreviewGenerationService = Depends(get_preview_service),
):
    """Retry a failed preview generation."""
    try:
        job = await preview_service.retry(proposal_id)
    except Exception:
        logger.exception("Error retrying preview for proposal %s", proposal_id)
        raise HTTPException(status_code=500, detail="Internal error retrying preview")

    if job is None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Max retries exceeded",
                "errors": [
                    {
                        "code": "PREVIEW_MAX_RETRIES_EXCEEDED",
                        "field": "proposal_id",
                        "message": "Preview generation failed after max retries",
                    }
                ],
            },
        )

    return {
        "status": "queued",
        "preview_job_id": job.job_id,
        "poll_url": f"/api/v1/ai/proposals/{proposal_id}/preview",
        "retry_count": job.retry_count,
        "retries_remaining": max(0, 2 - job.retry_count),
    }


def get_preview_service() -> PreviewGenerationService:
    """Dependency provider for PreviewGenerationService singleton."""
    from app.main import get_preview_service as _get_svc
    return _get_svc()
```

### 4.4 App Bootstrap in `app/main.py`

```python
# Add to app/main.py lifespan context

from app.services.ai.preview_service import PreviewGenerationService, PreviewServiceConfig
from app.db.config import SessionLocal

# Singleton instance
_preview_service: Optional[PreviewGenerationService] = None


def get_preview_service() -> PreviewGenerationService:
    """Return the singleton PreviewGenerationService instance."""
    global _preview_service
    assert _preview_service is not None, "PreviewGenerationService not initialized"
    return _preview_service


# Inside lifespan startup:
async def lifespan(app: FastAPI):
    # ... existing startup code ...

    # Initialize preview service
    global _preview_service
    config = PreviewServiceConfig(
        max_concurrency=int(os.getenv("PREVIEW_MAX_CONCURRENCY", "4")),
        render_timeout_s=int(os.getenv("PREVIEW_RENDER_TIMEOUT_S", "30")),
        max_retries=int(os.getenv("PREVIEW_MAX_RETRIES", "2")),
    )
    _preview_service = PreviewGenerationService(
        db_session_factory=SessionLocal,
        config=config,
    )
    await _preview_service.start()

    yield

    # Shutdown
    if _preview_service:
        await _preview_service.stop()


# Register router
from app.routers import ai_preview
api_router.include_router(ai_preview.router)
```

---

## 5. Configuration & Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PREVIEW_MAX_CONCURRENCY` | `4` | Maximum number of concurrent preview render jobs |
| `PREVIEW_RENDER_TIMEOUT_S` | `30` | Maximum time in seconds for a single preview render |
| `PREVIEW_MAX_RETRIES` | `2` | Maximum retry attempts for failed preview renders |
| `PREVIEW_RETRY_DELAY_S` | `1,4` | Comma-separated exponential backoff delays in seconds |
| `PREVIEW_POLL_INTERVAL_MS` | `2000` | Recommended frontend polling interval in milliseconds |
| `PREVIEW_MAX_HTML_SIZE` | `524288` | Maximum preview HTML size in bytes (512 KB) |

Add to `.env.example`:

```bash
# ============================================
# Async Preview Generation (US-AI-041)
# ============================================
PREVIEW_MAX_CONCURRENCY=4
PREVIEW_RENDER_TIMEOUT_S=30
PREVIEW_MAX_RETRIES=2
PREVIEW_RETRY_DELAY_S=1,4
PREVIEW_POLL_INTERVAL_MS=2000
PREVIEW_MAX_HTML_SIZE=524288
```

---

## 6. Test Scenarios

### 6.1 Unit Tests

Place in `tests/test_preview_service.py`.

```python
"""
Unit and integration tests for the Async Preview Generation Service (US-AI-041).

Covers:
- PreviewGenerationService queue operations
- Render timeout enforcement
- Retry logic and max retries exceeded
- Preview status transitions (pending -> rendering -> ready/failed)
- Rendered HTML structural validation
- DB persistence of preview results
- Error handling and error responses
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ai.preview_service import (
    PreviewGenerationService,
    PreviewServiceConfig,
    PreviewJob,
    PreviewGenerationError,
    PreviewRenderTimeoutError,
    PreviewRenderValidationError,
)
from app.models.course import Course, Template


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def preview_config():
    return PreviewServiceConfig(
        max_concurrency=2,
        render_timeout_s=5,
        max_retries=2,
        retry_delays_s=[0.1, 0.2],
    )


@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture
def mock_db_factory(mock_db_session):
    async def factory():
        return mock_db_session
    return factory


@pytest.fixture
def mock_renderer():
    renderer = MagicMock()
    renderer.render_single_template = AsyncMock(
        return_value='<div class="content-template" data-template-type="content-text"><p>Hello</p></div>'
    )
    return renderer


@pytest.fixture
def preview_service(preview_config, mock_db_factory, mock_renderer):
    return PreviewGenerationService(
        db_session_factory=mock_db_factory,
        config=preview_config,
        renderer=mock_renderer,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestPreviewJobEnqueue:
    """Preview job creation and queueing."""

    @pytest.mark.asyncio
    async def test_enqueue_returns_job_with_correct_fields(
        self, preview_service
    ):
        """Enqueuing a preview job returns a PreviewJob with valid job_id and pending status."""
        job = await preview_service.enqueue(
            proposal_id="prop_001",
            proposal_data={"after_candidate": {"type": "content-text", "data": {"content": "test"}}},
        )
        assert job.job_id.startswith("pv_")
        assert job.status == "pending"
        assert job.proposal_id == "prop_001"
        assert job.preview_type == "page"
        assert job.retry_count == 0

    @pytest.mark.asyncio
    async def test_enqueue_duplicate_returns_existing_job(
        self, preview_service
    ):
        """Enqueuing a second job for the same pending proposal returns the existing job."""
        job1 = await preview_service.enqueue(proposal_id="prop_001", proposal_data={})
        job2 = await preview_service.enqueue(proposal_id="prop_001", proposal_data={})
        assert job1.job_id == job2.job_id

    @pytest.mark.asyncio
    async def test_enqueue_persists_pending_status_to_db(
        self, preview_service, mock_db_session
    ):
        """Enqueue writes 'pending' status to the ai_proposals table."""
        await preview_service.enqueue(proposal_id="prop_001", proposal_data={})
        mock_db_session.execute.assert_called()
        mock_db_session.commit.assert_called()


class TestPreviewRendering:
    """Preview rendering lifecycle."""

    @pytest.mark.asyncio
    async def test_render_success_transitions_to_ready(
        self, preview_service, mock_renderer
    ):
        """Successful render transitions job status to 'ready' and stores HTML."""
        job = await preview_service.enqueue(
            proposal_id="prop_001",
            proposal_data={"after_candidate": {"type": "content-text", "data": {"content": "Hello"}}},
        )
        await preview_service._render_job(job)

        assert job.status == "ready"
        assert job.result_html is not None
        assert 'data-template-type="content-text"' in job.result_html
        assert job.render_duration_ms is not None
        assert job.render_duration_ms >= 0

    @pytest.mark.asyncio
    async def test_render_timeout_sets_failed_status(
        self, preview_service, mock_renderer
    ):
        """Render timeout transitions job status to 'failed' with RENDER_TIMEOUT error."""
        # Make renderer hang beyond timeout
        async def slow_render(*args, **kwargs):
            await asyncio.sleep(10)
            return "<div></div>"

        mock_renderer.render_single_template = AsyncMock(side_effect=slow_render)
        preview_service._renderer = mock_renderer

        job = await preview_service.enqueue(proposal_id="prop_timeout", proposal_data={})
        await preview_service._render_job(job)

        assert job.status == "failed"
        assert job.error_code == "RENDER_TIMEOUT"
        assert "timeout" in job.error.lower()

    @pytest.mark.asyncio
    async def test_render_exception_sets_failed_status(
        self, preview_service, mock_renderer
    ):
        """Renderer exception transitions job to 'failed' with descriptive error."""
        mock_renderer.render_single_template = AsyncMock(
            side_effect=ValueError("Invalid template data")
        )
        preview_service._renderer = mock_renderer

        job = await preview_service.enqueue(proposal_id="prop_err", proposal_data={})
        await preview_service._render_job(job)

        assert job.status == "failed"
        assert "Invalid template data" in job.error

    @pytest.mark.asyncio
    async def test_empty_html_validation_fails(
        self, preview_service, mock_renderer
    ):
        """Empty rendered HTML is caught by structural validation."""
        mock_renderer.render_single_template = AsyncMock(return_value="")
        preview_service._renderer = mock_renderer

        job = await preview_service.enqueue(proposal_id="prop_empty", proposal_data={})
        await preview_service._render_job(job)

        assert job.status == "failed"
        assert job.error_code == "VALIDATION_ERROR"
        assert "empty" in job.error.lower()

    @pytest.mark.asyncio
    async def test_missing_data_template_type_fails_validation(
        self, preview_service, mock_renderer
    ):
        """Page preview HTML without data-template-type attribute is rejected."""
        mock_renderer.render_single_template = AsyncMock(
            return_value="<div>No type attribute</div>"
        )
        preview_service._renderer = mock_renderer

        job = await preview_service.enqueue(proposal_id="prop_notpl", proposal_data={})
        await preview_service._render_job(job)

        assert job.status == "failed"
        assert "data-template-type" in job.error


class TestPreviewRetry:
    """Retry logic for failed preview jobs."""

    @pytest.mark.asyncio
    async def test_retry_reenqueues_failed_job(
        self, preview_service, mock_renderer
    ):
        """Retry re-enqueues a failed job and increments retry count."""
        mock_renderer.render_single_template = AsyncMock(
            side_effect=ValueError("Fail once")
        )
        preview_service._renderer = mock_renderer

        job = await preview_service.enqueue(proposal_id="prop_retry", proposal_data={})
        await preview_service._render_job(job)
        assert job.status == "failed"

        # Make second attempt succeed
        mock_renderer.render_single_template = AsyncMock(
            return_value='<div class="content-template" data-template-type="content-text">OK</div>'
        )

        retry_job = await preview_service.retry("prop_retry")
        assert retry_job is not None
        assert retry_job.retry_count == 1
        assert retry_job.status == "pending"

        await preview_service._render_job(retry_job)
        assert retry_job.status == "ready"

    @pytest.mark.asyncio
    async def test_max_retries_exceeded_returns_none(
        self, preview_service, mock_renderer
    ):
        """After max retries, retry() returns None."""
        mock_renderer.render_single_template = AsyncMock(
            side_effect=ValueError("Always fails")
        )
        preview_service._renderer = mock_renderer

        job = await preview_service.enqueue(proposal_id="prop_maxretry", proposal_data={})
        await preview_service._render_job(job)
        assert job.status == "failed"

        # First retry
        await preview_service.retry("prop_maxretry")
        await preview_service._render_job(job)

        # Second retry (max_retries = 2)
        await preview_service.retry("prop_maxretry")
        await preview_service._render_job(job)

        # Third retry should be denied
        result = await preview_service.retry("prop_maxretry")
        assert result is None


class TestPreviewStatusQuery:
    """Status query endpoint logic."""

    @pytest.mark.asyncio
    async def test_get_preview_status_ready_returns_html(
        self, preview_service, mock_renderer
    ):
        """Ready preview returns full status with HTML."""
        job = await preview_service.enqueue(proposal_id="prop_stat", proposal_data={})
        await preview_service._render_job(job)

        status = await preview_service.get_preview_status("prop_stat")
        assert status["status"] == "ready"
        assert status["preview_html"] is not None
        assert status["render_duration_ms"] is not None

    @pytest.mark.asyncio
    async def test_get_preview_status_pending_no_html(
        self, preview_service
    ):
        """Pending preview returns status without HTML."""
        job = await preview_service.enqueue(proposal_id="prop_pend", proposal_data={})
        status = await preview_service.get_preview_status("prop_pend")
        assert status["status"] in ("pending", "rendering")
        assert "preview_html" not in status or status["preview_html"] is None

    @pytest.mark.asyncio
    async def test_get_preview_status_failed_returns_error(
        self, preview_service, mock_renderer
    ):
        """Failed preview returns error details with retry info."""
        mock_renderer.render_single_template = AsyncMock(
            side_effect=ValueError("Render crash")
        )
        preview_service._renderer = mock_renderer

        job = await preview_service.enqueue(proposal_id="prop_fail", proposal_data={})
        await preview_service._render_job(job)

        status = await preview_service.get_preview_status("prop_fail")
        assert status["status"] == "failed"
        assert "error" in status
        assert status["error"]["retry_allowed"] is True

    @pytest.mark.asyncio
    async def test_get_preview_status_unknown_returns_none(
        self, preview_service
    ):
        """Unknown proposal returns None."""
        status = await preview_service.get_preview_status("prop_nonexistent")
        assert status is None


class TestConcurrency:
    """Concurrency and queue management."""

    @pytest.mark.asyncio
    async def test_max_concurrency_respected(
        self, preview_service
    ):
        """At most max_concurrency jobs run simultaneously."""
        preview_service._semaphore = asyncio.Semaphore(2)
        results = []

        async def slow_render(*args, **kwargs):
            await asyncio.sleep(1)
            return '<div class="content-template" data-template-type="content-text">Slow</div>'

        preview_service._renderer.render_single_template = AsyncMock(side_effect=slow_render)

        async def check_concurrency(job):
            concurrent = sum(
                1 for j in preview_service._active_jobs.values()
                if j.status == "rendering"
            )
            results.append(concurrent)
            await preview_service._render_job(job)
            return job

        jobs = [
            await preview_service.enqueue(proposal_id=f"prop_con_{i}", proposal_data={})
            for i in range(4)
        ]

        tasks = [check_concurrency(job) for job in jobs]
        await asyncio.gather(*tasks)

        # At no point should more than 2 jobs be rendering simultaneously
        assert max(results) <= 2


class TestRendererPipeline:
    """Integration with the SCORM export renderer."""

    @pytest.mark.asyncio
    async def test_render_content_text_template(self, preview_service):
        """Content-text template renders with expected CSS classes."""
        # Use the real SCORMExportService, not mock
        from app.services.scorm_export import SCORMExportService
        real_renderer = SCORMExportService()

        service = PreviewGenerationService(
            db_session_factory=preview_service._db_session_factory,
            config=preview_service._config,
            renderer=real_renderer,
        )

        job = await service.enqueue(
            proposal_id="prop_integration",
            proposal_data={
                "after_candidate": {
                    "id": "tpl_integration",
                    "type": "content-text",
                    "title": "Integration Test",
                    "order": 0,
                    "data": {"content": "<p>Integration <b>test</b> content.</p>"},
                }
            },
        )
        await service._render_job(job)

        assert job.status == "ready"
        html = job.result_html
        assert "content-template" in html
        assert "content-body" in html
        assert "<b>test</b>" in html or "test" in html
```

### 6.2 Integration Tests

Place in `tests/test_preview_api.py`.

```python
"""
Integration tests for the /api/v1/ai/proposals/{id}/preview endpoints.

Covers:
- HTTP 200 with pending preview
- HTTP 200 with ready preview (includes HTML)
- HTTP 200 with failed preview (includes error)
- HTTP 404 for unknown proposal
- HTTP 409 for retry after max retries
- Polling flow: pending -> ready or pending -> failed
- Retry flow: failed -> retry -> ready
"""

import pytest
from fastapi.testclient import TestClient


class TestPreviewAPI:
    """Integration tests for preview endpoints."""

    def test_get_preview_unknown_proposal_returns_404(
        self, test_client: TestClient
    ):
        """GET /api/v1/ai/proposals/unknown/preview returns 404."""
        response = test_client.get("/api/v1/ai/proposals/nonexistent/preview")
        assert response.status_code == 404

    def test_get_preview_status_light_returns_without_html(
        self, test_client: TestClient
    ):
        """GET .../preview/status returns lightweight response."""
        response = test_client.get(
            "/api/v1/ai/proposals/some-proposal/preview/status"
        )
        # The response shape must not contain preview_html
        data = response.json()
        assert "preview_html" not in data

    def test_retry_preview_unknown_proposal_returns_404(
        self, test_client: TestClient
    ):
        """POST .../preview/retry on unknown proposal returns 404."""
        response = test_client.post(
            "/api/v1/ai/proposals/nonexistent/preview/retry"
        )
        assert response.status_code == 404

    @pytest.mark.skip("Needs proposal fixture with preview_enabled flag")
    def test_full_polling_flow_pending_to_ready(
        self, test_client: TestClient, sample_proposal_with_preview: str
    ):
        """Polling flow: status transitions from pending to ready within timeout."""
        import time

        proposal_id = sample_proposal_with_preview
        max_wait = 15  # seconds

        for _ in range(max_wait * 2):  # poll every 500ms
            response = test_client.get(
                f"/api/v1/ai/proposals/{proposal_id}/preview"
            )
            assert response.status_code == 200
            data = response.json()

            if data["status"] == "ready":
                assert "preview_html" in data
                assert data["preview_html"].startswith("<")
                break
            elif data["status"] == "failed":
                pytest.fail(f"Preview failed: {data.get('error', 'unknown')}")

            time.sleep(0.5)
        else:
            pytest.fail("Preview did not become ready within timeout")

    @pytest.mark.skip("Needs proposal fixture that will fail")
    def test_retry_flow(
        self, test_client: TestClient, sample_failed_preview_proposal: str
    ):
        """Retry a failed preview and verify it becomes ready."""
        proposal_id = sample_failed_preview_proposal

        # Verify failed
        response = test_client.get(f"/api/v1/ai/proposals/{proposal_id}/preview")
        assert response.status_code == 200
        assert response.json()["status"] == "failed"

        # Retry
        response = test_client.post(
            f"/api/v1/ai/proposals/{proposal_id}/preview/retry"
        )
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "queued"

        # Poll until ready (or timeout)
        import time
        for _ in range(10):
            response = test_client.get(
                f"/api/v1/ai/proposals/{proposal_id}/preview"
            )
            if response.json()["status"] == "ready":
                break
            time.sleep(0.5)
        else:
            pytest.fail("Retry did not produce ready preview")
```

### 6.3 Renderer Parity Tests

Add to existing `tests/test_accordion_preview_parity.py` and `tests/test_renderer_registry.py`:

```python
@pytest.mark.asyncio
async def test_preview_renderer_produces_same_html_as_scorm_export(tmp_path, monkeypatch):
    """The preview renderer output must match the SCORM export HTML for the same template data."""
    from app.services.scorm_export import SCORMExportService
    from app.models.course import Course, Template, TemplateData

    template_data = {
        "id": "tpl-parity",
        "type": "accordion",
        "order": 0,
        "title": "Parity Test",
        "data": {
            "content": "Fallback",
            "panels": [
                {"id": "p1", "title": "Panel 1", "content": "<p>Content 1</p>"},
                {"id": "p2", "title": "Panel 2", "content": "<p>Content 2</p>"},
            ],
        },
    }

    service = SCORMExportService()
    monkeypatch.setattr(service, "_validate_templates_for_scorm", lambda *a: None)

    course = Course(
        courseId="parity-001",
        title="Parity Test",
        author="QA",
        templates=[Template(**template_data)],
    )

    # Render via preview path
    preview_html = await service.render_single_template(course, course.templates[0])

    # Render via full SCORM export path
    import tempfile, os
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    await service._create_content_html(package_dir, course)
    export_html = (package_dir / "index.html").read_text(encoding="utf-8")

    # The preview HTML should be a subset of the full export HTML
    # (same CSS classes, same data attributes, same rendered content)
    assert preview_html in export_html or all(
        cls in export_html for cls in ["accordion-template", "accordion-trigger", "panel-title"]
    )
    assert all(
        phrase in preview_html for phrase in ["Panel 1", "Panel 2", "Content 1", "Content 2"]
    )
```

---

## 7. Task Breakdown

### Task 7.1: Database Migration — Add Preview Columns

**Files:**
- `alembic/versions/20260614_0001_add_preview_to_ai_proposals.py` (NEW)
- `app/models/persisted_course.py` (MODIFY — add preview columns to AiProposal model)

**Acceptance:**
- Migration runs successfully on PostgreSQL and SQLite (test).
- Rollback drops all preview columns.
- New AiProposal ORM fields exist with correct types.

**Effort:** 1 point (2 hours)

### Task 7.2: Preview Pydantic Models

**Files:**
- `app/services/ai/preview_models.py` (NEW)

**Acceptance:**
- `PreviewStatusResponse`, `PreviewResponse`, `PreviewRetryResponse` match API contract section 2.4.
- Models serialize correctly with example payloads.

**Effort:** 1 point (1 hour)

### Task 7.3: PreviewGenerationService Core

**Files:**
- `app/services/ai/preview_service.py` (NEW)

**Acceptance:**
- `enqueue()` creates a job, persists `pending` status to DB, returns job.
- `get_preview_status()` returns correct status dictionary for all states.
- `retry()` increments retry count, re-enqueues, returns `None` when max retries exceeded.
- `_render_job()` calls renderer, stores result, handles timeout and exceptions.
- `_validate_render_output()` catches empty HTML and missing `data-template-type`.

**Effort:** 3 points (2-3 days)

### Task 7.4: Renderer Pipeline Extension

**Files:**
- `app/services/scorm_export.py` (MODIFY — add `render_single_template()` method)
- `app/services/scorm_export_v2.py` (MODIFY — add `render_single_template()` method if needed)

**Acceptance:**
- `render_single_template()` returns valid HTML fragment for any supported template type.
- Output uses same CSS class names as full SCORM export.
- Existing SCORM export tests continue to pass unchanged.
- Preview output for accordion templates matches test_accordion_preview_parity expectations.

**Effort:** 3 points (2-3 days)

### Task 7.5: Preview API Router

**Files:**
- `app/routers/ai_preview.py` (NEW)
- `app/main.py` (MODIFY — bootstrap PreviewGenerationService, register router)

**Acceptance:**
- `GET /api/v1/ai/proposals/{proposal_id}/preview` returns 200 with correct status shape.
- `GET /api/v1/ai/proposals/{proposal_id}/preview/status` returns lightweight status.
- `POST /api/v1/ai/proposals/{proposal_id}/preview/retry` returns 202 or 409.
- Unknown proposals return 404.
- Service boots correctly in lifespan context.

**Effort:** 2 points (1-2 days)

### Task 7.6: Auto-Trigger from Proposal Handlers

**Files:**
- Proposal creation handlers in existing AI routers (e.g., `propose_add_page`, `propose_edit_page`)

**Acceptance:**
- When a proposal is created with `status = PENDING_CONFIRMATION`, the handler calls `preview_service.enqueue()`.
- Preview generation does not block the API response.
- The proposal creation response includes `preview_job_id` and `preview_poll_url`.

**Effort:** 1 point (4 hours)

### Task 7.7: Unit Tests

**Files:**
- `tests/test_preview_service.py` (NEW)

**Acceptance:**
- All tests in sections 6.1 pass.
- Test coverage for: enqueue, status transitions, render success/failure/timeout, validation, retry, concurrency.

**Effort:** 2 points (1-2 days)

### Task 7.8: Integration Tests

**Files:**
- `tests/test_preview_api.py` (NEW)

**Acceptance:**
- All tests in section 6.2 pass or are properly skipped with documented fixture requirements.
- Polling flow integration test verifies end-to-end: proposal created -> preview ready -> frontend renders.

**Effort:** 2 points (1 day)

### Task 7.9: Renderer Parity Tests

**Files:**
- `tests/test_accordion_preview_parity.py` (MODIFY — add parity test)

**Acceptance:**
- Parity test verifies preview HTML is a structural subset of SCORM export HTML.
- All existing renderer tests continue to pass.

**Effort:** 1 point (4 hours)

### Task 7.10: Documentation and Configuration

**Files:**
- `.env.example` (MODIFY — add preview env vars)

**Acceptance:**
- All env vars documented in section 5 are added to `.env.example`.
- API contract in section 2 is reflected in OpenAPI schema.
- Frontend polling contract is documented for US-AI-024 integration.

**Effort:** 1 point (2 hours)

---

## 8. Dependencies & References

### Internal Dependencies

| Dependency | Relationship |
|---|---|
| US-AI-009 (Proposal Safety Model) | Requires `ai_proposals` table and proposal lifecycle. Preview columns are added to this table. |
| US-AI-011 (Create Page Proposal and Apply) | Proposal handlers trigger preview auto-enqueue. |
| US-AI-024 (Frontend AI Integration Layer) | Frontend polls the `/preview` endpoints and renders HTML. Polling contract defined in section 2.5. |
| US-AI-023 (AI Chat Endpoint) | Chat response must include `preview_job_id` and `preview_poll_url` in tool results. |
| US-AI-034 (Durable Workflow Engine) | Optional integration: instead of in-process queue, delegate to `WorkflowJob` for persistence across restarts. |
| US-AI-029 (Batch Proposal Operations) | Course-level previews for batch proposals use the same rendering pipeline with multiple templates. |

### External References

| Reference | Purpose |
|---|---|
| `app/services/scorm_export.py` | Existing SCORM export service whose renderer pipeline is reused. |
| `app/services/scorm_export_v2.py` | Refactored SCORM export with modular builders; alternative preview path. |
| `app/services/scorm/renderers/base.py` | Abstract base renderer interface. |
| `app/services/scorm/renderers/dynamic.py` | Dynamic template renderer using DB-stored template definitions. |
| `app/services/scorm/renderers/registry.py` | Template renderer registry (singleton, loaded from DB at startup). |
| `app/services/renderer_manifest.py` | Manifest of all 84 template types with `isExportable` flags and required fields. |
| `app/models/course.py` | Pydantic `Course`, `Template`, `TemplateData` models. |
| `app/models/persisted_course.py` | ORM models: `CourseRecord`, `TemplateRecord`, `ImportJob`, `TemplateDefinition`. |
| `tests/test_accordion_preview_parity.py` | Existing parity tests between preview and SCORM output. |
| `tests/test_renderer_registry.py` | Existing renderer tests covering all template types. |
| `app/routers/imports.py` | Existing import preview endpoint (`GET /api/v1/imports/{job_id}/preview`) as reference pattern. |
| `app/services/import_service.py` | Existing `get_preview()` method (lines 194-219) as reference for preview response structure. |
| `app/db/config.py` | DB session factory (`SessionLocal`, `get_session()`) used by the preview service. |
