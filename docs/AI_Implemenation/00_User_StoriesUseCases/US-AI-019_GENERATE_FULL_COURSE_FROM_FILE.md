# US-AI-019: Generate a Full Course From an Uploaded File

**Status:** Draft  
**Priority:** SHOULD (MVP for file-import MVP, MUST for file-import GA)  
**Depends on:** US-AI-011 (Create Page Proposal and Apply), US-AI-017 (Document Extraction and Page-Plan Review), US-AI-029 (Batch Proposal Operations), US-AI-016 (File Upload and Ingestion Job Foundation)  
**Source flows:** Full Course from Uploaded File Scenario Flow (Flow 10), File Ingestion / Document Import Flow (Flow 8)  
**Epic Owner:** Technical Product Owner  

---

## 1. Functional Specification

### 1.1 User Story

As an Author, I want to turn an approved uploaded-file page plan into a complete course draft, so that I can start from source material (PDF, DOCX, PPTX) and finish in the existing editor without manually building each page.

### 1.2 Overview

This story implements the final assembly step of the file-import pipeline. After US-AI-017 extracts a document and presents a page-plan breakdown for review, and the user approves the plan, US-AI-019 takes over:

1. The backend creates a **course-generation job** tied to the approved page plan and the original import job.
2. A **course generation service** calls the configured LLM with per-page prompts, feeding each approved page's title, suggested template type, and source-material context. The LLM returns structured page content (component data) for each page.
3. The backend validates every generated page against the same validation pipeline used for manual content (schema, business rules, template compatibility, export readiness).
4. A **batch proposal** is created containing all generated pages. The frontend shows a unified course preview with per-page validation status, page ordering, and a content summary.
5. The user reviews the full course preview, makes any last-minute adjustments (reorder, retitle, remove a page), and approves or rejects the batch.
6. On approval, the system applies all pages transactionally to a new `CourseRecord` (or merges into an existing target course), writes the audit trail with file provenance metadata, and returns the created course ready for the existing editor.

**Key principles:**
- All-or-nothing: if any single page fails generation or validation, no pages are applied.
- The LLM generates structured page data, not prose. The backend validates the structure before creating proposals.
- The user always sees a preview before apply. No pages are created in the DB during generation.
- The generated course is fully compatible with the existing editor, SCORM export, and all downstream systems.
- Provenance is tracked end-to-end: source file hash, extraction job ID, prompt versions, model ID, and per-page generation metadata.

### 1.3 Actors

| Actor | Role |
|---|---|
| Author (User) | Uploads source file; reviews and approves page plan; reviews generated course preview; confirms batch apply |
| AI Agent | Called during generation to produce structured page content per the approved plan |
| CourseGenerationService | Orchestrates the generation pipeline: plan iteration, LLM calls, validation, batch proposal creation |
| Backend System | Persists generation jobs, manages batch proposals, enforces all-or-nothing apply, writes audit records |
| Frontend | Shows generation progress, renders course preview with per-page validation status, provides approve/reject UI |

### 1.4 Flow: Full Course Generation from Approved Page Plan

**Precondition:** The user has uploaded a file, extraction completed (US-AI-017), and the page-plan has been approved by the user. The import job has status `plan_approved` and contains the final `pages[]` array with accepted titles, template suggestions, and source-material references.

**Phase 0 — Initiate Course Generation**
1. Frontend calls `POST /api/v1/ai/generate-course` with `{import_job_id, course_id (optional, for merge), generation_options}`.
2. Backend validates the import job exists and is in `plan_approved` status.
3. Backend creates a `CourseGenerationJob` record with status `pending`, links to the import job, and stores the approved page plan.
4. Backend returns `{generation_job_id, status: "pending", total_pages, estimated_templates}`.
5. Frontend transitions to a generation-progress view, polling `GET /api/v1/ai/generate-course/{job_id}` for status updates.

**Phase 1 — Page Content Generation (Server-Side, Async)**
1. A background task (or a durable workflow step) picks up the generation job.
2. The `CourseGenerationService` iterates over each page in the approved plan in sequential order (topological by page order):
   a. Construct a generation prompt containing:
      - System instructions: template schema, field constraints, output format, tone/audience guidelines.
      - Page context: page title, suggested template type, any source-material excerpts (from the import job's extraction results scoped to that page's source references).
      - Course-level context: course title, description, target audience (from the import job's initial upload metadata).
   b. Call the configured LLM provider (primary model from `AI_GENERATION_MODEL` env var) with the prompt.
   c. Receive the LLM response and parse the structured page content.
   d. Validate the generated content against the page's target template schema (via `CourseValidator` + component registry).
   e. If validation passes, append the generated page to the accumulated course data.
   f. If validation fails, retry with the error message as feedback to the LLM (up to `AI_GENERATION_RETRY_COUNT` retries).
   g. If all retries are exhausted, mark the generation job as `failed` with the page index and error details.
3. After all pages are generated successfully, run a full-course validation:
   - Schema validation (Course Pydantic model).
   - Business rule validation (navigation completeness, template ordering, assessment presence if required).
   - Export readiness validation (SCORM compatibility).
4. If full-course validation passes, update the generation job status to `ready_for_review` and store the generated course data.
5. If full-course validation fails, mark the job as `failed` with the aggregated validation errors.

**Phase 2 — Batch Proposal Creation**
1. The `CourseGenerationService` creates a **batch proposal** (leveraging US-AI-029 semantics) containing:
   - `batch_operation = course_create_from_file`
   - `source_import_job_id`
   - `pages[]` — each with `{page_title, template_type, components[], generated_content, validation_status}`
   - `course_metadata` — title, description, suggested settings
   - `provenance` — file hash, extraction job ID, model ID, prompt versions, generation timestamps
2. Each page in the batch gets its own proposal entry linked to the batch ID, following the standard `ai_proposals` status lifecycle (`PENDING_REVIEW`).
3. The batch proposal stores the full generated course data as `after_candidate` (the state to be created if approved).
4. Update the generation job status to `awaiting_confirmation` with the batch proposal ID.

**Phase 3 — User Review**
1. Frontend polls `GET /api/v1/ai/generate-course/{job_id}` and sees `status: "awaiting_confirmation"` with `batch_proposal_id`.
2. Frontend calls `GET /api/v1/ai/batch-proposals/{batch_proposal_id}` to fetch the full preview:
   - Course title, description, page count, estimated duration.
   - Per-page: title, template type (with icon/thumbnail), component count, validation status (pass/warning/error), a brief content summary (first 50 words).
   - Full-course validation summary: errors (blocking), warnings (advisory).
3. Frontend renders a "Course Preview" screen:
   - Left: reorderable page list with validation badges.
   - Right: expanded page detail (title, template, component breakdown, first N chars of content).
   - Bottom: total page count, estimated duration, validation pass/fail banner.
   - Action buttons: "Approve and Create Course" (disabled if blocking errors exist), "Cancel" (returns to import review page), "Edit Page Plan" (returns to US-AI-017 plan review).
4. User can optionally remove individual pages from the batch (remaining pages are still applied) — this is a UI-only removal that triggers a new preview without the removed pages. The backend does not create a new proposal until the user confirms.
5. User clicks "Approve and Create Course".

**Phase 4 — Batch Apply**
1. Frontend calls `POST /api/v1/ai/batch-proposals/{batch_proposal_id}/apply` with `{user_confirmed: true, removed_page_ids: []}`.
2. Backend validates:
   - Batch proposal exists, status is `PENDING_REVIEW`, belongs to user's session.
   - No page IDs in `removed_page_ids` are required for course integrity (at least one page remains).
3. Backend begins a database transaction:
   a. Create a new `CourseRecord` with the generated course data:
      - `course_id`: auto-generated UUID (or the target course_id if merging).
      - `title`, `description`: from the page plan.
      - `json_data`: generated course structure including settings, navigation defaults.
   b. For each generated page (excluding any in `removed_page_ids`):
      - Create a `PageRecord` linked to the new `CourseRecord`.
      - Create `ComponentRecord` entries for each component in the page.
      - Update the batch proposal's per-page status to `APPLIED`.
   c. Write audit log entry (see Section 2.9 for exact schema):
      - `operation = course_create_from_file`
      - `before_snapshot = null` (new course)
      - `after_snapshot` = full course JSON including all pages and components
      - `source_import_job_id`, `file_hash`, `source_type`, `model_id`, `prompt_versions`
   d. Write outbox event `CourseCreatedFromFile` (version 1) with payload containing:
      - `course_id`, `batch_proposal_id`, `import_job_id`, `page_count`, `generation_summary`.
   e. Update batch proposal status to `APPLIED` with `applied_at`.
4. Commit transaction.
5. Update generation job status to `completed` with the new `course_id`.
6. Return response: `{status: "completed", course_id, course_title, page_count, batch_proposal_id}`.

**Phase 5 — Post-Creation Flow**
1. Frontend navigates to the existing course editor with the new `course_id`.
2. The editor loads the generated course in its normal editing mode.
3. All pages and components are editable, repositionable, and exportable.
4. The user can continue editing manually, export to SCORM, or publish.
5. If the original file contained assets (images, media), these are linked via the media service and available in the editor's asset browser.

### 1.5 Error Conditions

| Condition | HTTP Status | Error Code | Behavior |
|---|---|---|---|
| Import job not found | 404 | `IMPORT_JOB_NOT_FOUND` | Course generation cannot start |
| Import job not in plan_approved status | 400 | `INVALID_IMPORT_JOB_STATUS` | Must have `plan_approved` before generation |
| Page plan has no approved pages | 400 | `EMPTY_PAGE_PLAN` | At least one page needed for generation |
| Course title missing | 400 | `MISSING_COURSE_TITLE` | Title required for generation context |
| LLM generation fails for a page (all retries) | 500 | `PAGE_GENERATION_FAILED` | Job marked failed with page index and error |
| LLM provider unavailable | 503 | `LLM_PROVIDER_UNAVAILABLE` | Generation job failed; retry with configuration change |
| Full-course validation fails | 400 | `COURSE_VALIDATION_FAILED` | Job marked failed with validation errors array |
| Batch proposal not found on confirm | 404 | `BATCH_PROPOSAL_NOT_FOUND` | Confirmation rejected |
| Batch proposal status not PENDING_REVIEW | 409 | `BATCH_PROPOSAL_NOT_PENDING` | Already applied or expired |
| All pages removed by user | 400 | `NO_PAGES_REMAINING` | At least one page must remain |
| AI feature flag disabled | 404 | `FEATURE_NOT_AVAILABLE` | Generation endpoints disabled |
| Generation job already completed | 409 | `JOB_ALREADY_COMPLETED` | Idempotent: return existing course_id |
| Course ID conflict on apply | 409 | `COURSE_ID_CONFLICT` | Target course_id already exists (if not merge mode) |

---

## 2. Technical Specification

### 2.1 New Database Tables — DDL

**Table: `course_generation_jobs`**

```sql
CREATE TABLE course_generation_jobs (
    id                  SERIAL PRIMARY KEY,
    job_id              VARCHAR(64) UNIQUE NOT NULL,
    import_job_id       VARCHAR(64) NOT NULL REFERENCES import_jobs(job_id) ON DELETE CASCADE,
    course_id           VARCHAR(64),                          -- populated on successful completion
    batch_proposal_id   VARCHAR(64) REFERENCES ai_proposals(proposal_id),  -- set when proposal created
    
    -- Status tracking
    status              VARCHAR(32) NOT NULL DEFAULT 'pending'
                        CHECK (status IN (
                            'pending', 'generating', 'validating',
                            'ready_for_review', 'awaiting_confirmation',
                            'applying', 'completed', 'failed'
                        )),
    progress            FLOAT NOT NULL DEFAULT 0.0,           -- 0.0 to 1.0
    
    -- Configuration snapshot
    generation_config   JSONB NOT NULL DEFAULT '{}',          -- model, retry count, options
    approved_page_plan  JSONB NOT NULL,                       -- snapshot of the approved pages[]
    
    -- Results
    generated_course    JSONB,                                -- full generated course data (set when ready_for_review)
    validation_result   JSONB,                                -- aggregated validation errors/warnings
    error_message       TEXT,
    failed_page_index   INTEGER,                              -- which page failed generation (if applicable)
    
    -- Provenance
    file_hash           VARCHAR(64),                          -- SHA256 of original uploaded file
    source_type         VARCHAR(32),                          -- 'pdf', 'docx', 'pptx', 'scorm', 'json'
    model_id            VARCHAR(128),                         -- LLM model used for generation
    prompt_versions     JSONB,                                -- {planning: v1, generation: v2, ...}
    
    -- Retry tracking
    generation_attempts INTEGER NOT NULL DEFAULT 0,
    
    -- Timestamps
    expires_at          TIMESTAMPTZ NOT NULL,                 -- job TTL (48h default)
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_cgj_import_job ON course_generation_jobs(import_job_id);
CREATE INDEX idx_cgj_status ON course_generation_jobs(status);
CREATE INDEX idx_cgj_course ON course_generation_jobs(course_id);
CREATE INDEX idx_cgj_created ON course_generation_jobs(created_at DESC);
```

**Table: `generation_page_logs` (per-page generation audit)**

```sql
CREATE TABLE generation_page_logs (
    id                  SERIAL PRIMARY KEY,
    job_id              VARCHAR(64) NOT NULL REFERENCES course_generation_jobs(job_id) ON DELETE CASCADE,
    page_index          INTEGER NOT NULL,                     -- order in the page plan
    page_title          VARCHAR(200) NOT NULL,
    template_type       VARCHAR(100) NOT NULL,
    
    -- Generation metadata
    status              VARCHAR(32) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'generating', 'completed', 'failed')),
    retry_count         INTEGER NOT NULL DEFAULT 0,
    
    -- Prompts and results (for audit and debugging)
    prompt_sent         TEXT,                                  -- the full prompt sent to LLM (may be truncated for storage)
    response_received   JSONB,                                -- the raw LLM response
    generated_data      JSONB,                                -- validated component data
    
    -- Validation
    validation_errors   JSONB,                                -- per-field validation issues
    validation_warnings JSONB,
    
    -- Timing
    llm_latency_ms      INTEGER,                              -- time taken for the LLM call
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_gpl_job ON generation_page_logs(job_id);
CREATE INDEX idx_gpl_page_index ON generation_page_logs(job_id, page_index);
```

### 2.2 SQLAlchemy ORM Models

**New file: `app/models/course_generation.py`**

```python
"""ORM models for course generation jobs and per-page generation logs."""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import (
    String, DateTime, JSON, Text, Integer, Float, ForeignKey,
    TIMESTAMP, BigInteger
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMPTZ

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class CourseGenerationJobRecord(Base):
    __tablename__ = "course_generation_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    import_job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("import_jobs.job_id", ondelete="CASCADE"),
        index=True
    )
    course_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    batch_proposal_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("ai_proposals.proposal_id"), nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(32), default="pending", index=True
    )
    progress: Mapped[float] = mapped_column(Float, default=0.0)

    generation_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    approved_page_plan: Mapped[dict] = mapped_column(JSONB)

    generated_course: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    validation_result: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    failed_page_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    file_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    model_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    prompt_versions: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    generation_attempts: Mapped[int] = mapped_column(Integer, default=0)

    expires_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)
    started_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "jobId": self.job_id,
            "importJobId": self.import_job_id,
            "courseId": self.course_id,
            "batchProposalId": self.batch_proposal_id,
            "status": self.status,
            "progress": self.progress,
            "totalPages": len(
                (self.approved_page_plan or {}).get("pages", [])
            ) if self.approved_page_plan else 0,
            "errorMessage": self.error_message,
            "failedPageIndex": self.failed_page_index,
            "validationResult": self.validation_result,
            "sourceType": self.source_type,
            "modelId": self.model_id,
            "generationAttempts": self.generation_attempts,
            "expiresAt": self.expires_at.isoformat() if self.expires_at else None,
            "startedAt": self.started_at.isoformat() if self.started_at else None,
            "completedAt": self.completed_at.isoformat() if self.completed_at else None,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


class GenerationPageLogRecord(Base):
    __tablename__ = "generation_page_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("course_generation_jobs.job_id", ondelete="CASCADE"),
        index=True
    )
    page_index: Mapped[int] = mapped_column(Integer)
    page_title: Mapped[str] = mapped_column(String(200))
    template_type: Mapped[str] = mapped_column(String(100))

    status: Mapped[str] = mapped_column(String(32), default="pending")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    prompt_sent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response_received: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    generated_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    validation_errors: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    validation_warnings: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    llm_latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, default=datetime.utcnow
    )
```

### 2.3 Pydantic Request/Response DTOs

**Location: `app/routers/ai_course_generation_dtos.py`** (new file)

```python
"""Pydantic DTOs for the course generation API."""
from __future__ import annotations
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class GenerateCourseRequest(BaseModel):
    import_job_id: str = Field(
        ..., description="The import job ID with an approved page plan"
    )
    course_id: Optional[str] = Field(
        None, description="Optional target course ID for merging (creates new if absent)"
    )
    generation_options: dict = Field(
        default_factory=lambda: {
            "model": None,  # use default from env
            "tone": "professional",
            "audience": "general",
            "include_assessment": True,
            "max_pages": 50,
        },
        description="Generation configuration overrides",
    )


class GenerateCourseResponse(BaseModel):
    generation_job_id: str
    status: str
    progress: float
    total_pages: int
    estimated_templates: list[str] = Field(default_factory=list)
    message: str = "Course generation started"


class GenerationJobStatusResponse(BaseModel):
    generation_job_id: str
    import_job_id: str
    course_id: Optional[str] = None
    batch_proposal_id: Optional[str] = None
    status: str
    progress: float
    total_pages: int
    completed_pages: int
    failed_page_index: Optional[int] = None
    error_message: Optional[str] = None
    validation_result: Optional[dict] = None
    source_type: Optional[str] = None
    model_id: Optional[str] = None
    expires_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: str


class GeneratedPageSummary(BaseModel):
    page_index: int
    title: str
    template_type: str
    component_count: int
    validation_status: str  # 'pass' | 'warning' | 'error'
    content_preview: str = Field(
        ..., max_length=200, description="First 200 chars of content"
    )
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class GenerationPreviewResponse(BaseModel):
    course_title: str
    course_description: str
    total_pages: int
    estimated_duration_minutes: Optional[int] = None
    pages: list[GeneratedPageSummary]
    validation_summary: dict = Field(
        default_factory=lambda: {"errors": 0, "warnings": 0, "passed": True}
    )
    source_file_name: str
    source_type: str
    model_used: str
    batch_proposal_id: str


class ConfirmGenerateCourseRequest(BaseModel):
    user_confirmed: bool = Field(
        ..., description="Must be true to proceed with course creation"
    )
    removed_page_indices: list[int] = Field(
        default_factory=list,
        description="Indices of pages to exclude from the generated course",
    )


class ConfirmGenerateCourseResponse(BaseModel):
    status: str = "completed"
    course_id: str
    course_title: str
    page_count: int
    batch_proposal_id: str
    message: str


class GenerationJobError(BaseModel):
    code: str
    field: str
    message: str
    details: dict = Field(default_factory=dict)
```

### 2.4 API Contracts

#### POST /api/v1/ai/generate-course

Initiates course generation from an approved page plan.

**Request:**
```json
{
  "import_job_id": "job_import_abc123",
  "course_id": null,
  "generation_options": {
    "model": null,
    "tone": "professional",
    "audience": "general",
    "include_assessment": true,
    "max_pages": 50
  }
}
```

**Response 202 (Generation started):**
```json
{
  "generation_job_id": "gen_job_xyz789",
  "status": "pending",
  "progress": 0.0,
  "total_pages": 12,
  "estimated_templates": ["welcome", "content-text", "mcq", "tabs", "summary"],
  "message": "Course generation started"
}
```

**Error Responses:**

`404 IMPORT_JOB_NOT_FOUND`:
```json
{
  "code": "IMPORT_JOB_NOT_FOUND",
  "field": "import_job_id",
  "message": "Import job 'job_import_abc123' not found.",
  "details": {}
}
```

`400 INVALID_IMPORT_JOB_STATUS`:
```json
{
  "code": "INVALID_IMPORT_JOB_STATUS",
  "field": "import_job_id",
  "message": "Import job must be in 'plan_approved' status. Current status: 'extracted'.",
  "details": {"current_status": "extracted", "required_status": "plan_approved"}
}
```

`400 EMPTY_PAGE_PLAN`:
```json
{
  "code": "EMPTY_PAGE_PLAN",
  "field": "import_job_id",
  "message": "The approved page plan contains no pages. At least one page is required.",
  "details": {}
}
```

#### GET /api/v1/ai/generate-course/{generation_job_id}

Polls the status of a course generation job.

**Response 200 (In progress):**
```json
{
  "generation_job_id": "gen_job_xyz789",
  "import_job_id": "job_import_abc123",
  "course_id": null,
  "batch_proposal_id": null,
  "status": "generating",
  "progress": 0.42,
  "total_pages": 12,
  "completed_pages": 5,
  "failed_page_index": null,
  "error_message": null,
  "validation_result": null,
  "source_type": "pdf",
  "model_id": "deepseek-v4-flash",
  "expires_at": "2026-06-16T12:00:00Z",
  "started_at": "2026-06-14T12:00:00Z",
  "completed_at": null,
  "created_at": "2026-06-14T11:59:00Z"
}
```

**Response 200 (Ready for review):**
```json
{
  "generation_job_id": "gen_job_xyz789",
  "import_job_id": "job_import_abc123",
  "course_id": null,
  "batch_proposal_id": "batch_prop_001",
  "status": "awaiting_confirmation",
  "progress": 1.0,
  "total_pages": 12,
  "completed_pages": 12,
  "failed_page_index": null,
  "error_message": null,
  "validation_result": {"errors": 0, "warnings": 2, "passed": true},
  "source_type": "pdf",
  "model_id": "deepseek-v4-flash",
  "expires_at": "2026-06-16T12:00:00Z",
  "started_at": "2026-06-14T12:00:00Z",
  "completed_at": null,
  "created_at": "2026-06-14T11:59:00Z"
}
```

**Response 200 (Failed):**
```json
{
  "generation_job_id": "gen_job_xyz789",
  "import_job_id": "job_import_abc123",
  "course_id": null,
  "batch_proposal_id": null,
  "status": "failed",
  "progress": 0.5,
  "total_pages": 12,
  "completed_pages": 6,
  "failed_page_index": 6,
  "error_message": "Failed to generate page 6 'Quiz Section' after 3 retries: Schema validation failed: MCQ must have at least 2 options.",
  "validation_result": null,
  "source_type": "pdf",
  "model_id": "deepseek-v4-flash",
  "expires_at": "2026-06-16T12:00:00Z",
  "started_at": "2026-06-14T12:00:00Z",
  "completed_at": "2026-06-14T12:05:00Z",
  "created_at": "2026-06-14T11:59:00Z"
}
```

#### GET /api/v1/ai/generate-course/{generation_job_id}/preview

Fetches the full course preview for review (only available when status is `awaiting_confirmation` or `completed`).

**Response 200:**
```json
{
  "course_title": "Introduction to Workplace Safety",
  "course_description": "A comprehensive course on workplace safety procedures and best practices.",
  "total_pages": 12,
  "estimated_duration_minutes": 45,
  "pages": [
    {
      "page_index": 0,
      "title": "Welcome to Workplace Safety",
      "template_type": "welcome",
      "component_count": 2,
      "validation_status": "pass",
      "content_preview": "Welcome to this comprehensive course on workplace safety...",
      "warnings": [],
      "errors": []
    },
    {
      "page_index": 5,
      "title": "Knowledge Check",
      "template_type": "mcq",
      "component_count": 3,
      "validation_status": "warning",
      "content_preview": "Test your understanding of the material covered so far...",
      "warnings": ["MCQ page has only 2 options for question 3; recommend 4 for better assessment."],
      "errors": []
    }
  ],
  "validation_summary": {
    "errors": 0,
    "warnings": 2,
    "passed": true
  },
  "source_file_name": "safety_manual_2026.pdf",
  "source_type": "pdf",
  "model_used": "deepseek-v4-flash",
  "batch_proposal_id": "batch_prop_001"
}
```

#### POST /api/v1/ai/generate-course/{generation_job_id}/confirm

Confirms and applies the generated course.

**Response 200 (Course created):**
```json
{
  "status": "completed",
  "course_id": "course_intro_safety_001",
  "course_title": "Introduction to Workplace Safety",
  "page_count": 12,
  "batch_proposal_id": "batch_prop_001",
  "message": "Course 'Introduction to Workplace Safety' created successfully with 12 pages."
}
```

### 2.5 Service Signatures

**New file: `app/services/ai/course_generator.py`**

```python
"""Orchestrates full-course generation from an approved page plan.

Pipeline:
  1. Load approved page plan from import job.
  2. For each page, call LLM with template-specific generation prompt.
  3. Validate generated content per template schema with retry.
  4. Run full-course validation (schema, business rules, export readiness).
  5. Create a batch proposal with all pages.
  6. On user confirmation, apply all pages transactionally.
"""

from __future__ import annotations
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.page_component import PageRecord, ComponentRecord
from app.models.persisted_course import CourseRecord

logger = logging.getLogger(__name__)


class CourseGenerationError(Exception):
    """Base error for course generation failures."""
    pass


class PageGenerationError(CourseGenerationError):
    """Raised when a single page fails generation after all retries."""
    def __init__(self, page_index: int, page_title: str, message: str):
        self.page_index = page_index
        self.page_title = page_title
        super().__init__(f"Page {page_index} '{page_title}': {message}")


class CourseValidationError(CourseGenerationError):
    """Raised when full-course validation fails."""
    def __init__(self, errors: list[dict], warnings: list[dict]):
        self.errors = errors
        self.warnings = warnings
        super().__init__(f"Course validation failed with {len(errors)} error(s)")


class CourseGenerator:
    """Orchestrates the full course generation pipeline."""

    DEFAULT_MODEL = os.getenv("AI_GENERATION_MODEL", "deepseek-v4-flash")
    MAX_RETRIES = int(os.getenv("AI_GENERATION_RETRY_COUNT", "3"))
    JOB_TTL_HOURS = int(os.getenv("AI_GENERATION_JOB_TTL_HOURS", "48"))

    def __init__(
        self,
        db_session: AsyncSession,
        llm_callable: Optional[Callable] = None,
    ):
        """Initialize generator.

        Args:
            db_session: SQLAlchemy async session.
            llm_callable: Async function to call the LLM.
                          Signature: async def(prompt: str, model: str, **kwargs) -> str
                          If None, a default provider client is used.
        """
        self.session = db_session
        self.llm_callable = llm_callable  # injected for testability

    async def start_generation(
        self,
        import_job_id: str,
        course_id: Optional[str] = None,
        generation_options: Optional[dict] = None,
        user_id: str = "system",
    ) -> str:
        """Start a course generation job from an approved page plan.

        Args:
            import_job_id: Import job with plan_approved status.
            course_id: Optional target course for merge.
            generation_options: Overrides for model, tone, audience, etc.
            user_id: Authenticated user ID.

        Returns:
            Generation job ID for polling.

        Raises:
            CourseGenerationError: If the import job is not valid for generation.
        """
        # 1. Validate import job
        # 2. Extract approved page plan
        # 3. Create CourseGenerationJobRecord with status=pending
        # 4. Enqueue background task to run _execute_generation
        # 5. Return job_id
        raise NotImplementedError

    async def _execute_generation(
        self, job: CourseGenerationJobRecord
    ) -> None:
        """Execute the generation pipeline for a job.

        This is the core pipeline:
          1. Update job status to 'generating'.
          2. Iterate pages: build prompt -> call LLM -> validate -> retry on failure.
          3. Validate full course.
          4. Create batch proposal.
          5. Update job status to 'awaiting_confirmation' or 'failed'.
        """
        # Implementation in Task 6
        raise NotImplementedError

    async def _generate_single_page(
        self,
        job_id: str,
        page_plan: dict,
        page_index: int,
        course_context: dict,
    ) -> dict:
        """Generate content for one page by calling the LLM.

        Args:
            job_id: Generation job ID (for logging).
            page_plan: {title, suggested_template, source_references, ...}.
            page_index: Sequential position in the course.
            course_context: {title, description, audience, tone} for prompt construction.

        Returns:
            Validated page data dict with {title, type, data, components[]}.

        Raises:
            PageGenerationError: After exhausting retries.
        """
        # 1. Build generation prompt using template schema + source context
        # 2. Call LLM with retry loop (MAX_RETRIES attempts)
        # 3. Parse structured response
        # 4. Validate against template schema
        # 5. Log to GenerationPageLogRecord
        # 6. Return validated page data
        raise NotImplementedError

    async def _build_prompt_for_page(
        self,
        page_plan: dict,
        course_context: dict,
        template_schema: dict,
    ) -> str:
        """Build a generation prompt for a single page.

        The prompt instructs the LLM to produce structured JSON matching
        the template schema, with source-material context included.
        """
        raise NotImplementedError

    async def _call_llm_with_retry(
        self,
        prompt: str,
        page_plan: dict,
        max_retries: int = 3,
    ) -> str:
        """Call the LLM with automatic retry on failure.

        Uses the injected llm_callable or a default provider client.
        Returns the LLM response text.
        """
        raise NotImplementedError

    async def _validate_generated_page(
        self,
        page_data: dict,
        template_type: str,
    ) -> tuple[list[str], list[str]]:
        """Validate generated page data against the template schema.

        Returns:
            (errors, warnings) — empty errors list means valid.
        """
        raise NotImplementedError

    async def _run_full_course_validation(
        self,
        course_data: dict,
    ) -> dict:
        """Run full-course validation after all pages are generated.

        Checks:
          - Course Pydantic model schema.
          - Business rules (navigation completeness, ordering, assessment).
          - Export readiness (supported template types, scoring config).
          - Component registry compatibility.

        Returns:
            {"passed": bool, "errors": [...], "warnings": [...]}
        """
        raise NotImplementedError

    async def _create_batch_proposal(
        self,
        course_data: dict,
        job: CourseGenerationJobRecord,
        user_id: str,
    ) -> str:
        """Create a batch proposal for the full generated course.

        Uses US-AI-029 batch proposal semantics.
        Returns batch_proposal_id.
        """
        raise NotImplementedError

    async def confirm_and_apply(
        self,
        job_id: str,
        user_id: str,
        user_confirmed: bool,
        removed_page_indices: Optional[list[int]] = None,
    ) -> dict:
        """Confirm generation and apply the course transactionally.

        Args:
            job_id: Generation job ID.
            user_id: Authenticated user ID.
            user_confirmed: Must be True.
            removed_page_indices: Optional pages to exclude from apply.

        Returns:
            {status, course_id, course_title, page_count, batch_proposal_id}.

        Raises:
            CourseGenerationError: If confirmation fails.
        """
        # 1. Load job, verify status == 'awaiting_confirmation'
        # 2. Verify user_confirmed == True
        # 3. Load batch proposal, verify PENDING_REVIEW
        # 4. Begin transaction
        # 5. Create CourseRecord with generated data
        # 6. Create PageRecord + ComponentRecord for each page (skip removed)
        # 7. Write audit log
        # 8. Write outbox event CourseCreatedFromFile
        # 9. Update batch proposal -> APPLIED
        # 10. Update job -> completed
        # 11. Commit
        # 12. Return response
        raise NotImplementedError

    async def _compute_file_hash(self, file_path: str) -> str:
        """Compute SHA256 hash of a file."""
        import hashlib
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
```

**New file: `app/services/ai/prompt_builder.py`**

```python
"""Builds LLM generation prompts for course page generation.

Each prompt is composed from:
  - System instructions (template schema, output format, constraints).
  - Course context (title, description, audience, tone).
  - Page context (title, suggested template, source material excerpts).
"""

from __future__ import annotations
from typing import Optional

# Built-in template type schemas for prompt injection
_TEMPLATE_SCHEMAS = {
    "welcome": {
        "description": "Course welcome/introduction page",
        "fields": {
            "title": "str (required): Page heading",
            "content": "str (required): Welcome message and course overview",
            "subtitle": "Optional[str]: Subtitle or tagline",
            "objectives": "Optional[list[str]]: Learning objectives (3-5 items)",
        },
    },
    "content-text": {
        "description": "Text-heavy content page with optional media",
        "fields": {
            "content": "str (required): Main body text, can include paragraphs",
            "body": "Optional[str]: Rich text body (alternative to content)",
            "subtitle": "Optional[str]: Section subtitle",
        },
    },
    "content-video": {
        "description": "Video-centric content page",
        "fields": {
            "videoUrl": "str (required): HTTPS URL to video",
            "content": "Optional[str]: Video description or transcript excerpt",
            "subtitle": "Optional[str]: Video title/subtitle",
        },
    },
    "mcq": {
        "description": "Multiple choice question page",
        "fields": {
            "content": "str (required): Instructions or context for the questions",
            "questions": "list (required, min 1): Array of question objects",
            "questions[].id": "str: Unique question identifier",
            "questions[].question": "str (required): Question text",
            "questions[].options": "list (required, min 2, max 6): Answer options",
            "questions[].options[].id": "str: Option identifier",
            "questions[].options[].text": "str (required): Option text",
            "questions[].options[].isCorrect": "bool (required): Exactly one per question must be true",
        },
    },
    "tabs": {
        "description": "Tabbed content organization page",
        "fields": {
            "content": "str (required): Tab set title or intro",
            "tabs": "list (required, min 1): Array of tab objects",
            "tabs[].title": "str (required): Tab heading",
            "tabs[].body": "str (required): Tab content body",
        },
    },
    "accordion": {
        "description": "Expandable accordion panels page",
        "fields": {
            "content": "str (required): Accordion section title or intro",
            "panels": "list (required, min 1): Array of panel objects",
            "panels[].title": "str (required): Panel heading",
            "panels[].body": "str (required): Panel content body",
        },
    },
    "summary": {
        "description": "Course section summary / key takeaways page",
        "fields": {
            "content": "str (required): Summary text",
            "subtitle": "Optional[str]: Summary section subtitle",
        },
    },
    "final-assessment": {
        "description": "Final course assessment with mixed question types",
        "fields": {
            "introText": "Optional[str]: Assessment introduction text",
            "passingScore": "int (default 80, range 0-100): Passing score percentage",
            "maxAttempts": "int (default 1): Maximum attempts allowed",
            "shuffleQuestions": "bool (default false): Shuffle question order",
            "shuffleOptions": "bool (default false): Shuffle option order",
            "showCorrectAnswers": "bool (default true): Show correct answers after submit",
            "questions": "list (required, min 1): Array of mixed-type questions",
            "questions[].id": "str: Unique identifier",
            "questions[].type": "Literal['mcq','multiple-select','true-false','fill-in-blank']",
            "questions[].question": "str (required): Question text",
            "questions[].options": "Optional[list]: Options for mcq/multiple-select/true-false",
            "questions[].correctAnswer": "Optional[bool]: For true-false",
            "questions[].correctAnswers": "Optional[list[str]]: For fill-in-blank",
            "questions[].explanation": "Optional[str]: Shown after submit",
            "questions[].points": "float (default 1): Point value",
        },
    },
    "text-with-media": {
        "description": "Text with inline media (image/video) positioned beside text",
        "fields": {
            "body": "str (required): Main text content",
            "mediaUrl": "str (required): URL to media asset",
            "mediaType": "Literal['image','video'] (required): Type of media",
            "mediaPosition": "Literal['left','right','top','bottom'] (default 'right'): Media position relative to text",
            "subtitle": "Optional[str]: Section subtitle",
        },
    },
}


class PromptBuilder:
    """Builds structured generation prompts for LLM page content generation."""

    SYSTEM_PROMPT_VERSION = "1.0"

    @classmethod
    def build_system_prompt(cls) -> str:
        """Build the base system prompt for page content generation."""
        return (
            "You are a course content generator for an e-learning platform. "
            "Your task is to generate structured JSON page data for a course. "
            "Follow these rules:\n"
            "1. Generate ONLY valid JSON — no markdown, no code fences, no extra text.\n"
            "2. Every field must match the specified template schema exactly.\n"
            "3. Content must be professional, clear, and suitable for adult learners.\n"
            "4. For MCQ questions, generate exactly one correct answer per question.\n"
            "5. For assessments, generate 5-10 questions per assessment page.\n"
            "6. Video URLs should use placeholder https://example.com/videos/... format.\n"
            "7. Image/media URLs should use placeholder https://example.com/media/... format.\n"
            "8. Content should be substantial but concise (50-200 words per body section).\n"
            "9. Use the source material context provided for accurate, relevant content.\n"
            "10. Do NOT include fields not listed in the schema.\n"
            f"11. SYSTEM PROMPT VERSION: {cls.SYSTEM_PROMPT_VERSION}\n"
        )

    @classmethod
    def build_page_prompt(
        cls,
        page_title: str,
        template_type: str,
        course_title: str,
        course_description: str,
        page_order: int,
        total_pages: int,
        source_excerpt: Optional[str] = None,
        tone: str = "professional",
        audience: str = "general",
        extra_context: Optional[dict] = None,
    ) -> str:
        """Build a generation prompt for a single page.

        Args:
            page_title: Title of the page to generate.
            template_type: One of the supported template types.
            course_title: Title of the parent course.
            course_description: Course description for context.
            page_order: 0-based order of this page in the course.
            total_pages: Total number of pages in the course.
            source_excerpt: Relevant excerpt from the source document.
            tone: 'professional' | 'conversational' | 'academic' | 'simple'.
            audience: Target audience description.
            extra_context: Additional context key-value pairs.

        Returns:
            A complete prompt string ready to send to the LLM.
        """
        schema = _TEMPLATE_SCHEMAS.get(template_type, {})
        schema_doc = json.dumps(schema, indent=2) if schema else "No specific schema."

        prompt_parts = [
            cls.build_system_prompt(),
            "",
            "--- PAGE GENERATION CONTEXT ---",
            f"Course Title: {course_title}",
            f"Course Description: {course_description}",
            f"Page Title: {page_title}",
            f"Template Type: {template_type}",
            f"Page Order: {page_order + 1} of {total_pages}",
            f"Tone: {tone}",
            f"Target Audience: {audience}",
        ]

        if source_excerpt:
            prompt_parts.extend([
                "",
                "--- SOURCE MATERIAL EXCERPT ---",
                source_excerpt,
            ])

        if extra_context:
            prompt_parts.extend([
                "",
                "--- ADDITIONAL CONTEXT ---",
                json.dumps(extra_context, indent=2),
            ])

        prompt_parts.extend([
            "",
            "--- REQUIRED OUTPUT SCHEMA ---",
            f"You MUST generate a JSON object matching this schema:",
            schema_doc,
            "",
            "--- OUTPUT ---",
            "Generate ONLY the JSON object. No markdown, no code fences, no explanation.",
        ])

        return "\n".join(prompt_parts)

    @classmethod
    def build_retry_prompt(
        cls,
        original_prompt: str,
        previous_response: str,
        validation_errors: list[str],
    ) -> str:
        """Build a retry prompt with error feedback.

        Args:
            original_prompt: The prompt that was sent previously.
            previous_response: The LLM response that failed validation.
            validation_errors: List of error messages from validation.

        Returns:
            A retry prompt that includes the original context plus error feedback.
        """
        return (
            f"{original_prompt}\n\n"
            "--- PREVIOUS RESPONSE (INVALID) ---\n"
            f"{previous_response}\n\n"
            "--- VALIDATION ERRORS ---\n"
            + "\n".join(f"- {err}" for err in validation_errors)
            + "\n\n"
            "--- INSTRUCTION ---\n"
            "The previous response failed schema validation. "
            "Fix ALL errors listed above and generate a corrected JSON object. "
            "ONLY output the JSON object, no explanation."
        )

    @classmethod
    def parse_llm_response(cls, response_text: str) -> dict | None:
        """Parse and extract JSON from an LLM response.

        Handles:
          - Clean JSON objects
          - JSON wrapped in markdown code fences (```json ... ```)
          - JSON preceded/followed by explanatory text
          - Truncated responses (raises ValueError if unparseable)

        Returns:
            Parsed dict, or None if parsing fails.
        """
        import re

        # Try direct parse first
        text = response_text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown code fences
        fence_match = re.search(
            r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL
        )
        if fence_match:
            try:
                return json.loads(fence_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Try finding first { ... } or [ ... ] block
        for delim in ("{", "["):
            start = text.find(delim)
            if start >= 0:
                # Find matching closing delimiter
                depth = 0
                for i in range(start, len(text)):
                    if text[i] in ("{", "["):
                        depth += 1
                    elif text[i] in ("}", "]"):
                        depth -= 1
                        if depth == 0:
                            try:
                                return json.loads(text[start : i + 1])
                            except json.JSONDecodeError:
                                break
        return None
```

### 2.6 CourseGenerationJob Repository

**New file: `app/repositories/course_generation_repo.py`**

```python
"""Repository for CourseGenerationJobRecord and GenerationPageLogRecord persistence."""
from __future__ import annotations
from typing import Optional, Sequence
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course_generation import (
    CourseGenerationJobRecord,
    GenerationPageLogRecord,
)


class CourseGenerationJobNotFoundError(Exception):
    pass


class CourseGenerationJobRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        job_id: str,
        import_job_id: str,
        approved_page_plan: dict,
        generation_config: Optional[dict] = None,
        file_hash: Optional[str] = None,
        source_type: Optional[str] = None,
        model_id: Optional[str] = None,
        prompt_versions: Optional[dict] = None,
        expires_at: Optional[datetime] = None,
    ) -> CourseGenerationJobRecord:
        import uuid
        record = CourseGenerationJobRecord(
            job_id=job_id or str(uuid.uuid4()),
            import_job_id=import_job_id,
            status="pending",
            progress=0.0,
            generation_config=generation_config or {},
            approved_page_plan=approved_page_plan,
            file_hash=file_hash,
            source_type=source_type,
            model_id=model_id,
            prompt_versions=prompt_versions,
            expires_at=expires_at or datetime.utcnow(),
        )
        self.session.add(record)
        await self.session.flush()
        await self.session.refresh(record)
        return record

    async def get_by_job_id(
        self, job_id: str
    ) -> Optional[CourseGenerationJobRecord]:
        q = select(CourseGenerationJobRecord).where(
            CourseGenerationJobRecord.job_id == job_id
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def get_by_import_job_id(
        self, import_job_id: str
    ) -> Sequence[CourseGenerationJobRecord]:
        q = (
            select(CourseGenerationJobRecord)
            .where(CourseGenerationJobRecord.import_job_id == import_job_id)
            .order_by(CourseGenerationJobRecord.created_at.desc())
        )
        return (await self.session.execute(q)).scalars().all()

    async def update_status(
        self,
        job_id: str,
        status: str,
        progress: Optional[float] = None,
        error_message: Optional[str] = None,
        failed_page_index: Optional[int] = None,
        generated_course: Optional[dict] = None,
        validation_result: Optional[dict] = None,
        batch_proposal_id: Optional[str] = None,
        course_id: Optional[str] = None,
        generation_attempts: Optional[int] = None,
    ) -> Optional[CourseGenerationJobRecord]:
        values = {"updated_at": datetime.utcnow()}
        if status is not None:
            values["status"] = status
        if progress is not None:
            values["progress"] = progress
        if error_message is not None:
            values["error_message"] = error_message
        if failed_page_index is not None:
            values["failed_page_index"] = failed_page_index
        if generated_course is not None:
            values["generated_course"] = generated_course
        if validation_result is not None:
            values["validation_result"] = validation_result
        if batch_proposal_id is not None:
            values["batch_proposal_id"] = batch_proposal_id
        if course_id is not None:
            values["course_id"] = course_id
        if generation_attempts is not None:
            values["generation_attempts"] = generation_attempts
        if status == "generating" and not values.get("started_at"):
            values["started_at"] = datetime.utcnow()
        if status in ("completed", "failed") and not values.get("completed_at"):
            values["completed_at"] = datetime.utcnow()

        stmt = (
            update(CourseGenerationJobRecord)
            .where(CourseGenerationJobRecord.job_id == job_id)
            .values(**values)
            .returning(CourseGenerationJobRecord)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.scalar_one_or_none()

    async def create_page_log(
        self,
        job_id: str,
        page_index: int,
        page_title: str,
        template_type: str,
    ) -> GenerationPageLogRecord:
        record = GenerationPageLogRecord(
            job_id=job_id,
            page_index=page_index,
            page_title=page_title,
            template_type=template_type,
            status="pending",
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def update_page_log(
        self,
        log_id: int,
        status: Optional[str] = None,
        prompt_sent: Optional[str] = None,
        response_received: Optional[dict] = None,
        generated_data: Optional[dict] = None,
        validation_errors: Optional[list] = None,
        validation_warnings: Optional[list] = None,
        retry_count: Optional[int] = None,
        llm_latency_ms: Optional[int] = None,
    ) -> Optional[GenerationPageLogRecord]:
        values = {}
        if status is not None:
            values["status"] = status
        if prompt_sent is not None:
            values["prompt_sent"] = prompt_sent
        if response_received is not None:
            values["response_received"] = response_received
        if generated_data is not None:
            values["generated_data"] = generated_data
        if validation_errors is not None:
            values["validation_errors"] = validation_errors
        if validation_warnings is not None:
            values["validation_warnings"] = validation_warnings
        if retry_count is not None:
            values["retry_count"] = retry_count
        if llm_latency_ms is not None:
            values["llm_latency_ms"] = llm_latency_ms
        if status == "generating" and not values.get("started_at"):
            values["started_at"] = datetime.utcnow()
        if status in ("completed", "failed") and not values.get("completed_at"):
            values["completed_at"] = datetime.utcnow()

        stmt = (
            update(GenerationPageLogRecord)
            .where(GenerationPageLogRecord.id == log_id)
            .values(**values)
            .returning(GenerationPageLogRecord)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.scalar_one_or_none()

    async def get_page_logs(
        self, job_id: str
    ) -> Sequence[GenerationPageLogRecord]:
        q = (
            select(GenerationPageLogRecord)
            .where(GenerationPageLogRecord.job_id == job_id)
            .order_by(GenerationPageLogRecord.page_index)
        )
        return (await self.session.execute(q)).scalars().all()
```

### 2.7 API Router

**New file: `app/routers/ai_course_generation.py`**

```python
"""AI Course Generation router.

Endpoints:
  POST   /api/v1/ai/generate-course                                   — Start generation
  GET    /api/v1/ai/generate-course/{generation_job_id}               — Poll status
  GET    /api/v1/ai/generate-course/{generation_job_id}/preview       — Get course preview
  POST   /api/v1/ai/generate-course/{generation_job_id}/confirm       — Confirm & apply
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.utils.error_envelope import api_http_exception
from app.utils.feature_flags import ai_authoring_enabled

from app.routers.ai_course_generation_dtos import (
    GenerateCourseRequest,
    GenerateCourseResponse,
    GenerationJobStatusResponse,
    GenerationPreviewResponse,
    ConfirmGenerateCourseRequest,
    ConfirmGenerateCourseResponse,
    GeneratedPageSummary,
)
from app.services.ai.course_generator import (
    CourseGenerator,
    CourseGenerationError,
    PageGenerationError,
    CourseValidationError,
)

router = APIRouter(prefix="/api/v1/ai", tags=["AI Course Generation"])


@router.post(
    "/generate-course",
    response_model=GenerateCourseResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start course generation from an approved page plan",
    responses={
        400: {"description": "Invalid import job or page plan"},
        404: {"description": "Import job not found"},
        503: {"description": "LLM provider unavailable"},
    },
)
async def start_generation(
    body: GenerateCourseRequest,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(ai_authoring_enabled),
):
    """Start course generation from an approved file-extraction page plan.

    Creates a generation job and begins the LLM-driven content generation
    pipeline. Returns immediately with a job ID for polling.
    """
    try:
        generator = CourseGenerator(session)
        job_id = await generator.start_generation(
            import_job_id=body.import_job_id,
            course_id=body.course_id,
            generation_options=body.generation_options,
            user_id="authenticated_user",  # TODO: inject from auth
        )
        # Load initial status
        job = await generator._repo.get_by_job_id(job_id)  # internal
        total_pages = len(
            (job.approved_page_plan or {}).get("pages", [])
        ) if job.approved_page_plan else 0

        return GenerateCourseResponse(
            generation_job_id=job_id,
            status="pending",
            progress=0.0,
            total_pages=total_pages,
            estimated_templates=list({
                p.get("suggested_template", "content-text")
                for p in (job.approved_page_plan or {}).get("pages", [])
            }),
            message="Course generation started",
        )

    except CourseGenerationError as exc:
        raise api_http_exception(
            status_code=400,
            code="GENERATION_ERROR",
            field="import_job_id",
            message=str(exc),
        )


@router.get(
    "/generate-course/{generation_job_id}",
    response_model=GenerationJobStatusResponse,
    summary="Poll course generation job status",
    responses={
        404: {"description": "Generation job not found"},
    },
)
async def get_generation_status(
    generation_job_id: str,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(ai_authoring_enabled),
):
    """Get the current status and progress of a generation job."""
    from app.repositories.course_generation_repo import (
        CourseGenerationJobRepository,
        CourseGenerationJobNotFoundError,
    )

    repo = CourseGenerationJobRepository(session)
    job = await repo.get_by_job_id(generation_job_id)
    if not job:
        raise api_http_exception(
            status_code=404,
            code="GENERATION_JOB_NOT_FOUND",
            field="generation_job_id",
            message=f"Generation job '{generation_job_id}' not found",
        )

    page_logs = await repo.get_page_logs(generation_job_id)
    completed_pages = sum(1 for p in page_logs if p.status == "completed")
    total_pages = len(
        (job.approved_page_plan or {}).get("pages", [])
    ) if job.approved_page_plan else 0

    return GenerationJobStatusResponse(
        generation_job_id=job.job_id,
        import_job_id=job.import_job_id,
        course_id=job.course_id,
        batch_proposal_id=job.batch_proposal_id,
        status=job.status,
        progress=job.progress,
        total_pages=total_pages,
        completed_pages=completed_pages,
        failed_page_index=job.failed_page_index,
        error_message=job.error_message,
        validation_result=job.validation_result,
        source_type=job.source_type,
        model_id=job.model_id,
        expires_at=job.expires_at.isoformat() if job.expires_at else "",
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        created_at=job.created_at.isoformat() if job.created_at else "",
    )


@router.get(
    "/generate-course/{generation_job_id}/preview",
    response_model=GenerationPreviewResponse,
    summary="Get full course preview for user review",
    responses={
        404: {"description": "Generation job not found"},
        400: {"description": "Job not ready for preview"},
    },
)
async def get_generation_preview(
    generation_job_id: str,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(ai_authoring_enabled),
):
    """Get the full course preview with per-page validation status.

    Only available when the generation job is in 'awaiting_confirmation' status.
    """
    from app.repositories.course_generation_repo import CourseGenerationJobRepository
    from app.services.import_service import ImportService

    repo = CourseGenerationJobRepository(session)
    job = await repo.get_by_job_id(generation_job_id)
    if not job:
        raise api_http_exception(
            status_code=404,
            code="GENERATION_JOB_NOT_FOUND",
            field="generation_job_id",
            message=f"Generation job '{generation_job_id}' not found",
        )

    if job.status not in ("awaiting_confirmation", "completed"):
        raise api_http_exception(
            status_code=400,
            code="JOB_NOT_READY",
            field="generation_job_id",
            message=f"Job is in '{job.status}' status. Preview requires 'awaiting_confirmation' or 'completed'.",
        )

    course_data = job.generated_course
    if not course_data:
        raise api_http_exception(
            status_code=400,
            code="NO_GENERATED_DATA",
            field="generation_job_id",
            message="No generated course data found.",
        )

    page_logs = await repo.get_page_logs(generation_job_id)
    pages_summary = []
    for idx, page in enumerate(course_data.get("templates", [])):
        log_entry = next(
            (pl for pl in page_logs if pl.page_index == idx), None
        )
        errors = list(log_entry.validation_errors or []) if log_entry else []
        warnings = list(log_entry.validation_warnings or []) if log_entry else []
        content_text = str(page.get("data", {}).get("content", "")) or ""
        pages_summary.append(
            GeneratedPageSummary(
                page_index=idx,
                title=page.get("title", f"Page {idx + 1}"),
                template_type=page.get("type", "content-text"),
                component_count=len(page.get("components", [])) or 1,
                validation_status="error" if errors else ("warning" if warnings else "pass"),
                content_preview=content_text[:200],
                warnings=warnings,
                errors=errors,
            )
        )

    validation_result = job.validation_result or {"errors": 0, "warnings": 0, "passed": True}
    return GenerationPreviewResponse(
        course_title=course_data.get("title", "Untitled Course"),
        course_description=course_data.get("description", ""),
        total_pages=len(pages_summary),
        estimated_duration_minutes=course_data.get("settings", {}).get("duration"),
        pages=pages_summary,
        validation_summary=validation_result,
        source_file_name=job.approved_page_plan.get("source_file_name", ""),
        source_type=job.source_type or "unknown",
        model_used=job.model_id or "default",
        batch_proposal_id=job.batch_proposal_id or "",
    )


@router.post(
    "/generate-course/{generation_job_id}/confirm",
    response_model=ConfirmGenerateCourseResponse,
    summary="Confirm and apply the generated course",
    responses={
        400: {"description": "Confirmation failed (user not approved, no pages remaining)"},
        404: {"description": "Generation job not found"},
        409: {"description": "Job already completed or in invalid state"},
    },
)
async def confirm_generation(
    generation_job_id: str,
    body: ConfirmGenerateCourseRequest,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(ai_authoring_enabled),
):
    """Confirm the generated course and apply all pages transactionally.

    Creates a new CourseRecord with all generated pages and components.
    On success, returns the new course ID.
    """
    try:
        generator = CourseGenerator(session)
        result = await generator.confirm_and_apply(
            job_id=generation_job_id,
            user_id="authenticated_user",  # TODO: inject from auth
            user_confirmed=body.user_confirmed,
            removed_page_indices=body.removed_page_indices,
        )
        return ConfirmGenerateCourseResponse(
            status="completed",
            course_id=result["course_id"],
            course_title=result["course_title"],
            page_count=result["page_count"],
            batch_proposal_id=result["batch_proposal_id"],
            message=(
                f"Course '{result['course_title']}' created "
                f"successfully with {result['page_count']} pages."
            ),
        )

    except CourseGenerationError as exc:
        raise api_http_exception(
            status_code=400,
            code="CONFIRMATION_ERROR",
            field="generation_job_id",
            message=str(exc),
        )
```

### 2.8 Main Application Registration

**In `app/main.py`, add to imports:**

```python
from app.routers import ai_course_generation  # new import
```

**In the router registration section:**

```python
api_router.include_router(ai_course_generation.router)
```

**In the `lifespan` startup section, add to the ORM model imports:**

```python
import app.models.course_generation  # noqa: F401 — register ORM model
```

**In `app/models/__init__.py`, add:**

```python
from app.models.course_generation import CourseGenerationJobRecord, GenerationPageLogRecord
```

### 2.9 Audit Log Entry Schema

When a course generation is confirmed and applied, an entry is written to the `ai_audit_logs` table (introduced in US-AI-004/US-AI-013). The exact payload:

```json
{
  "audit_id": "audit_cgf_a1b2c3d4",
  "proposal_id": "batch_prop_001",
  "session_id": "sess_abc123",
  "course_id": "course_intro_safety_001",
  "page_id": null,
  "operation": "course_create_from_file",
  "operation_detail": {
    "page_count": 12,
    "component_count": 36,
    "template_types": ["welcome", "content-text", "mcq", "tabs", "accordion", "summary", "final-assessment"],
    "removed_page_indices": [],
    "generation_job_id": "gen_job_xyz789",
    "import_job_id": "job_import_abc123",
    "source_file_name": "safety_manual_2026.pdf",
    "source_type": "pdf",
    "source_file_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "model_id": "deepseek-v4-flash",
    "system_prompt_version": "1.0",
    "total_llm_calls": 14,
    "total_llm_retries": 2,
    "total_generation_latency_ms": 45320
  },
  "before_snapshot": null,
  "after_snapshot": {
    "courseId": "course_intro_safety_001",
    "title": "Introduction to Workplace Safety",
    "description": "A comprehensive course on workplace safety...",
    "templates": [
      {"id": "page_0", "type": "welcome", "title": "Welcome...", "order": 0, "data": {...}},
      {"id": "page_1", "type": "content-text", "title": "...", "order": 1, "data": {...}}
    ],
    "settings": {"theme": "default", "autoplay": false, "duration": 45},
    "navigation": {"allowSkip": true, "showProgress": true, "linearProgression": false}
  },
  "confirmation_token_sha256": null,
  "tool_schema_version": "1.0",
  "model_id": "deepseek-v4-flash",
  "prompt_version": "1.0",
  "user_id": "user_abc",
  "user_email": "author@example.com",
  "created_at": "2026-06-14T12:05:00Z"
}
```

### 2.10 Outbox Event Schema

When a course is created, an outbox event of type `CourseCreatedFromFile` (version 1) is written:

```json
{
  "event_id": "evt_cgf_a1b2c3d4",
  "event_type": "CourseCreatedFromFile",
  "event_version": 1,
  "aggregate_id": "batch_prop_001",
  "aggregate_type": "batch_proposal",
  "payload": {
    "course_id": "course_intro_safety_001",
    "course_title": "Introduction to Workplace Safety",
    "page_count": 12,
    "import_job_id": "job_import_abc123",
    "generation_job_id": "gen_job_xyz789",
    "batch_proposal_id": "batch_prop_001",
    "source_type": "pdf",
    "source_file_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "model_id": "deepseek-v4-flash",
    "validation_summary": {"errors": 0, "warnings": 2, "passed": true},
    "template_types_used": ["welcome", "content-text", "mcq", "tabs", "accordion", "summary", "final-assessment"]
  },
  "trace_id": "trace_xyz789",
  "occurred_at": "2026-06-14T12:05:00Z",
  "published_at": null,
  "retry_count": 0
}
```

### 2.11 Environment Variables

Add to `.env` and `.env.example`:

```ini
# ============================================
# AI Course Generation Configuration
# ============================================
AI_GENERATION_MODEL=deepseek-v4-flash
AI_GENERATION_RETRY_COUNT=3
AI_GENERATION_JOB_TTL_HOURS=48
AI_GENERATION_MAX_PAGES=50
AI_GENERATION_MAX_CONCURRENT_JOBS=5
AI_GENERATION_TIMEOUT_SECONDS=120
AI_GENERATION_TONE=professional
AI_GENERATION_AUDIENCE=general
AI_GENERATION_INCLUDE_ASSESSMENT=true
```

These are read by `CourseGenerator`:

```python
import os

DEFAULT_MODEL = os.getenv("AI_GENERATION_MODEL", "deepseek-v4-flash")
MAX_RETRIES = int(os.getenv("AI_GENERATION_RETRY_COUNT", "3"))
JOB_TTL_HOURS = int(os.getenv("AI_GENERATION_JOB_TTL_HOURS", "48"))
MAX_PAGES = int(os.getenv("AI_GENERATION_MAX_PAGES", "50"))
TIMEOUT_SECONDS = int(os.getenv("AI_GENERATION_TIMEOUT_SECONDS", "120"))
```

---

## 3. Non-Functional Requirements

### 3.1 Performance

| Requirement | Target | Measurement |
|---|---|---|
| Generation job creation latency | < 200 ms p95 | API response time for `POST /api/v1/ai/generate-course` |
| Per-page LLM generation latency | < 15 s p95 per page | Time from prompt send to validated response |
| Full course generation (12 pages) | < 3 minutes p95 | Total job time from `pending` to `awaiting_confirmation` |
| Preview fetch latency | < 500 ms p95 | API response time for preview endpoint |
| Confirmation and apply latency | < 2 s p95 | API response time for confirm endpoint (includes DB transaction) |
| Concurrent generation jobs | <= 5 per tenant | Application-level guard via `AI_GENERATION_MAX_CONCURRENT_JOBS` |
| LLM timeout per call | 120 seconds | Configurable via `AI_GENERATION_TIMEOUT_SECONDS` |

### 3.2 Security

| Requirement | Implementation |
|---|---|
| File hash integrity | Source file SHA256 hash stored in the generation job and audit trail for non-repudiation |
| Prompt injection resistance | All source material excerpts are truncated (max 2000 chars) and stripped of HTML/script tags before prompt construction |
| LLM output validation | Generated content is validated against server-side template schemas before being accepted; malformed output is rejected for retry, never stored directly |
| Batch proposal gating | No course data is written to the DB until the user explicitly confirms via the confirm-endpoint |
| Feature gating | All generation endpoints require `AI_AUTHORING_ENABLED=true` feature flag |
| Cross-tenant isolation | Generation jobs are scoped to the authenticated user's organization; the import job ownership is verified before generation starts |
| Audit integrity | Full after_snapshot stored; file_hash links back to the original uploaded file |

### 3.3 Data Integrity

| Requirement | Implementation |
|---|---|
| All-or-nothing apply | Single DB transaction: if any page creation fails, the entire course creation is rolled back |
| Generation job idempotency | Duplicate `POST /api/v1/ai/generate-course` for the same import job returns the existing job ID (status check) |
| Confirm idempotency | If confirm is called twice, the second call checks batch proposal status and returns the existing course_id |
| Source material preservation | The original import job's extraction data is preserved; generation does not mutate it |
| Page log completeness | Every LLM call (including retries) is logged in `generation_page_logs` for debugging and quality monitoring |

### 3.4 Availability

| Requirement | Implementation |
|---|---|
| Generation failure recovery | Failed generation jobs (after exhausting retries) preserve partial results and error details for analysis; user can fix and re-initiate |
| LLM provider timeout | Timeout set to `AI_GENERATION_TIMEOUT_SECONDS`; on timeout, retry with backoff (2s, 4s, 8s) |
| Job TTL | Generation jobs expire after `AI_GENERATION_JOB_TTL_HOURS` (default 48h); expired jobs return a clear expiration error |
| Concurrent job limit | `AI_GENERATION_MAX_CONCURRENT_JOBS` limits per-tenant concurrent generations; new jobs are queued |
| Feature flag isolation | When `AI_AUTHORING_ENABLED=false`, all generation endpoints return `404 FEATURE_NOT_AVAILABLE` |

### 3.5 Observability

| Requirement | Implementation |
|---|---|
| Job-level progress | `progress` field (0.0 to 1.0) on the status endpoint reflects pages completed / total pages |
| Per-page latency | `generation_page_logs.llm_latency_ms` captures per-page generation time for performance analysis |
| Metric: generation_started | Counter incremented on `POST /api/v1/ai/generate-course` (tagged by source_type, model_id) |
| Metric: page_generated | Counter incremented per successfully generated page (tagged by template_type, retry_count) |
| Metric: page_generation_retry | Counter incremented per retry attempt (tagged by template_type, error_category) |
| Metric: generation_completed | Counter incremented when a job reaches `awaiting_confirmation` (tagged by source_type, page_count) |
| Metric: generation_confirmed | Counter incremented on successful apply (tagged by source_type, page_count, validation_outcome) |
| Metric: generation_failed | Counter incremented on job failure (tagged by source_type, failure_phase) |
| Log: generation pipeline | Structured log entries at each phase transition (pending -> generating -> ready_for_review -> awaiting_confirmation -> completed/failed) |

---

## 4. Current State

### 4.1 What Exists Today

1. **Import Job Infrastructure**: The existing `ImportService` at `app/services/import_service.py` handles SCORM package analysis and commit. The `ImportJobRepository` at `app/repositories/import_job_repository.py` provides CRUD for import jobs. The `POST /api/v1/imports/analyze` endpoint at `app/routers/imports.py:74` accepts ZIP uploads and creates analysis jobs.

2. **Heuristic Parser & Schema Inference**: `app/services/heuristic_parser.py` extracts JSON payloads from JavaScript. `app/services/schema_inference.py` infers JSON schemas from template data and generates schema signatures. These are used by the import pipeline to understand extracted template structures.

3. **Import Strategies**: `app/services/import_strategies/base.py` defines the `ImportStrategy` protocol. `StrategyRegistry` at `app/services/import_strategies/registry.py` selects the appropriate strategy. Current strategies: `Scorm12Strategy` and `JsonPayloadStrategy`.

4. **Course CRUD**: `app/routers/courses.py` at `app/routers/courses.py` provides full REST CRUD for courses. `CourseRepository` at `app/repositories/course_repo.py` handles `CourseRecord` persistence. The `POST /api/v1/courses` and `PUT /api/v1/courses/{courseId}` endpoints can create new course records.

5. **Page/Component CRUD**: `app/repositories/page_component_repo.py` manages `PageRecord` and `ComponentRecord` persistence. The existing `POST /api/v1/courses/{courseId}/pages/from-template` endpoint at `app/routers/courses.py:345` creates pages from templates with `PageRepository.create`.

6. **Template Repository**: `app/repositories/template_repo.py` provides `TemplateRecord` CRUD with order management and a JSON snapshot sync pattern on `CourseRecord.json_data["templates"]`.

7. **Course Pydantic Models**: `app/models/course.py` defines `Course`, `Template`, `TemplateData`, `MCQData`, `FinalAssessmentData`, `Question`, `QuestionOption` — all the base validation models that any generated course must pass.

8. **Component Registry**: `app/routers/component_registry.py` and `app/services/seed_component_types.py` manage the component type registry. Valid template types include: `welcome`, `content-video`, `mcq`, `content-text`, `summary`, `final-assessment`, `tabs`, `accordion`, `text-with-media` (content-media), and any dynamic types loaded from the DB.

9. **Validation Pipeline**: `app/utils/validation.py` provides `CourseValidator` with business rule validation (mcq, welcome, content-text, summary templates) and the `validate_course_json` dependency for the export route. `app/routers/courses.py:465` has a standalone `POST /api/v1/courses/validate` endpoint.

10. **Export Readiness**: `app/routers/export.py` provides SCORM export for both legacy JSON payloads and persisted courses. The `POST /api/v1/export/scorm/{courseId}` endpoint at line 709 exports persisted courses with theme resolution and component data mapping.

11. **Feature Flags**: `app/utils/feature_flags.py` provides the `ai_authoring_enabled` dependency for gating AI endpoints.

12. **No Multi-Page Batch Generation Yet**: There is no course generation endpoint, no batch proposal system for multi-page creation, and no LLM integration for content generation. The current import pipeline extracts existing content; it does not generate new content.

13. **No AI Proposal Tables Yet** (before US-AI-004): `ai_proposals`, `ai_audit_logs`, and `outbox_events` tables are planned in US-AI-004 and US-AI-013 but do not exist today.

### 4.2 What is Missing

1. `course_generation_jobs` table and `generation_page_logs` table with ORM models.
2. `CourseGenerationJobRepository` for generation job CRUD.
3. `CourseGenerator` service with the full generation pipeline (page iteration, LLM calls, validation, batch proposal creation, transactional apply).
4. `PromptBuilder` service for constructing template-specific generation prompts.
5. DTOs for generation API request/response models.
6. API router with `POST /api/v1/ai/generate-course`, status polling, preview, and confirm endpoints.
7. LLM call integration (the actual provider client that makes HTTP requests to the model API).
8. LLM response parser (`PromptBuilder.parse_llm_response`) that handles code fences, trailing text, and truncation.
9. Retry logic with validation feedback loop (generate -> validate -> retry with error feedback).
10. Batch proposal integration (US-AI-029): creating a batch proposal for all pages, with per-page proposal entries.
11. Full-course validation before batch proposal creation (schema, business rules, export readiness).
12. Transactional apply that creates CourseRecord + PageRecords + ComponentRecords atomically.
13. Audit log and outbox event writing on successful apply.
14. Alembic migration for the new tables.
15. Registration in `app/main.py` (router + ORM model import).
16. Environment variables for generation configuration.
17. Unit, integration, and E2E tests.

### 4.3 Dependencies on Earlier Stories

| Story | Dependency |
|---|---|
| US-AI-002 | Feature flag for `AI_AUTHORING_ENABLED` |
| US-AI-003 | Isolated AI API module structure |
| US-AI-004 | AI persistence foundations (sessions, proposals, audit, outbox) |
| US-AI-005 | Tool schema for `generate_course` tool |
| US-AI-006 | Session validation and course scope resolution |
| US-AI-008 | Course and page validation pipeline (reused for full-course validation) |
| US-AI-010 | Apply safety (transactional mutation + audit + outbox) |
| US-AI-011 | Create page proposal and apply (per-page creation pattern) |
| US-AI-016 | File upload and ingestion job foundation (import_jobs table, file upload) |
| US-AI-017 | Document extraction and page-plan review (import job `plan_approved` status, extraction data) |
| US-AI-029 | Batch proposal operations with all-or-nothing semantics (batch proposal ID, per-page proposal entries) |

---

## 5. Expansion Points

### 5.1 Multi-Format Source Support (Post-MVP)

The current story assumes a single uploaded file as the source. A natural expansion is to support multiple source files (e.g., a PDF + a companion PPTX + reference DOCX) where the page plan is generated from all combined sources. The generation job would receive `import_job_ids[]` and merge the extraction data before generation.

### 5.2 Course Merge Instead of Create-New (Post-MVP)

Currently the flow creates a brand-new `CourseRecord`. Future versions could merge generated pages into an existing course at a specified insertion point (e.g., "add the generated content as a new section after Unit 2"). This requires:
- Accepting a `course_id` + `insert_after_page_index` in the generation request.
- Shifting existing page orders after the insertion point.
- Updating the batch proposal to append to an existing course rather than create new.

### 5.3 Multi-Pass Refinement (Post-MVP)

After the initial generation, if the user is unsatisfied with specific page content, they could request a regeneration of specific pages without regenerating the entire course. This would reuse the generation job ID and create a delta-update batch proposal.

### 5.4 Template-Aware Quality Scoring (Post-MVP)

Each generated page could receive a quality score based on content length, keyword coverage against the source material, reading level match, and diversity of question types. Pages below a threshold would be flagged for the user or automatically regenerated.

### 5.5 Media Asset Sourcing (Post-MVP)

If the source document contains embedded images or media, these could be extracted, uploaded to the media service, and their URLs injected into the generated page data. This requires integrating with `POST /api/v1/media/upload` during the generation pipeline.

### 5.6 Durable Workflow Integration (US-AI-034)

Once US-AI-034's durable workflow engine is available, the generation pipeline should be migrated from a background task to a defined workflow with checkpointing, enabling:
- Resume after server restart.
- Human-in-the-loop at the page-plan level (US-AI-017 already covers the pre-generation plan review).
- Parallel page generation for performance.

### 5.7 Template Harvesting from Generated Content (US-AI-037)

After a successful generation, page patterns that match new template candidates could be automatically harvested into the template registry (US-AI-037), making well-received AI-generated structures available for manual authoring.

---

## 6. Validation and Test Scenarios

### 6.1 Unit Tests (Service Layer)

```python
# File: tests/test_course_generator.py

class TestStartGeneration:
    async def test_start_generation_happy_path(self, db_session, sample_import_job_with_approved_plan):
        """A valid approved page plan starts a generation job in 'pending' status."""
        pass

    async def test_start_generation_import_job_not_found(self, db_session):
        """A non-existent import job ID returns IMPORT_JOB_NOT_FOUND."""
        pass

    async def test_start_generation_wrong_status_raises_error(self, db_session, sample_import_job_in_extracted_status):
        """An import job not in 'plan_approved' status is rejected."""
        pass

    async def test_start_generation_empty_page_plan_raises_error(self, db_session, sample_import_job_approved_empty):
        """An approved plan with zero pages is rejected."""
        pass

    async def test_start_generation_max_pages_exceeded_raises_error(self, db_session, sample_import_job_51_pages):
        """A plan exceeding AI_GENERATION_MAX_PAGES (default 50) is rejected."""
        pass

    async def test_start_generation_creates_job_record(self, db_session, sample_import_job_with_approved_plan):
        """A generation job record is created with correct initial state."""
        pass

    async def test_start_generation_duplicate_import_job_returns_existing(self, db_session, sample_import_job_with_approved_plan):
        """Calling start_generation twice for the same import job returns the existing job ID."""
        pass

    async def test_start_generation_stores_page_plan_snapshot(self, db_session, sample_import_job_with_approved_plan):
        """The approved page plan is snapshot in the generation job."""
        pass


class TestGenerateSinglePage:
    async def test_generate_welcome_page(self, db_session, monkeypatch):
        """A welcome page is generated with title, content, and objectives matching schema."""
        pass

    async def test_generate_mcq_page(self, db_session, monkeypatch):
        """An MCQ page is generated with valid questions and exactly one correct answer per question."""
        pass

    async def test_generate_content_text_page(self, db_session, monkeypatch):
        """A content-text page has non-empty body/content."""
        pass

    async def test_generate_final_assessment(self, db_session, monkeypatch):
        """A final-assessment page has mixed question types with valid options."""
        pass

    async def test_generate_tabs_page(self, db_session, monkeypatch):
        """A tabs page has at least one tab with title and body."""
        pass

    async def test_generate_accordion_page(self, db_session, monkeypatch):
        """An accordion page has at least one panel with title and body."""
        pass

    async def test_llm_response_with_code_fences_parses_correctly(self, db_session, monkeypatch):
        """A valid JSON response inside ```json...``` fences is parsed successfully."""
        pass

    async def test_llm_response_with_trailing_text_parses_correctly(self, db_session, monkeypatch):
        """JSON followed by explanatory text is correctly extracted."""
        pass

    async def test_malformed_llm_response_triggers_retry(self, db_session, monkeypatch):
        """A non-JSON response triggers a retry with the original prompt plus error feedback."""
        pass

    async def test_generation_retry_eventually_succeeds(self, db_session, monkeypatch):
        """After 2 failed retries, the 3rd attempt succeeds."""
        pass

    async def test_generation_retry_exhausted_raises_error(self, db_session, monkeypatch):
        """After MAX_RETRIES failed attempts, PageGenerationError is raised."""
        pass

    async def test_generated_page_is_logged(self, db_session, monkeypatch):
        """Every generation attempt creates or updates a GenerationPageLogRecord."""
        pass

    async def test_prompt_includes_schema_instructions(self, db_session):
        """The built prompt includes the template schema definition."""
        pass

    async def test_prompt_includes_source_excerpt(self, db_session, sample_source_excerpt):
        """If source_excerpt is provided, it appears in the prompt."""
        pass


class TestValidateGeneratedPage:
    async def test_valid_mcq_passes_validation(self, db_session):
        """A well-formed MCQ page passes schema validation."""
        pass

    async def test_mcq_without_questions_fails_validation(self, db_session):
        """An MCQ page with zero questions fails."""
        pass

    async def test_mcq_without_correct_answer_fails_validation(self, db_session):
        """An MCQ page where no option has isCorrect=true fails."""
        pass

    async def test_final_assessment_with_invalid_type_fails_validation(self, db_session):
        """A final-assessment question with an unknown type fails."""
        pass

    async def test_text_with_media_missing_media_url_fails_validation(self, db_session):
        """A text-with-media page without mediaUrl fails."""
        pass

    async def test_welcome_page_without_content_fails_validation(self, db_session):
        """A welcome page without content fails."""
        pass

    async def test_page_with_unknown_template_type_fails_validation(self, db_session):
        """A page with a template type not in the allowed list fails."""
        pass


class TestFullCourseValidation:
    async def test_complete_course_passes_validation(self, db_session, sample_generated_course):
        """A fully generated course with all pages passes schema + business rules."""
        pass

    async def test_course_without_welcome_page_passes_with_warning(self, db_session):
        """A course without a welcome page generates a warning but is not blocked."""
        pass

    async def test_course_without_any_assessment_passes_with_warning(self, db_session):
        """A course without MCQ or final-assessment generates a warning."""
        pass

    async def test_course_with_duplicate_template_orders_fails(self, db_session):
        """Non-sequential template orders in generated data fail validation."""
        pass

    async def test_course_with_too_many_pages_fails(self, db_session):
        """A generated course exceeding the max page count fails."""
        pass


class TestConfirmAndApply:
    async def test_confirm_happy_path_creates_course(self, db_session, sample_completed_generation_job):
        """Confirm with user_confirmed=true creates a CourseRecord with all pages."""
        pass

    async def test_confirm_without_user_approval_returns_error(self, db_session, sample_completed_generation_job):
        """user_confirmed=false returns a confirmation error."""
        pass

    async def test_confirm_removes_specified_pages(self, db_session, sample_completed_generation_job):
        """Pages in removed_page_indices are excluded from the created course."""
        pass

    async def test_confirm_all_pages_removed_returns_error(self, db_session, sample_completed_generation_job):
        """Removing all pages returns NO_PAGES_REMAINING error."""
        pass

    async def test_confirm_creates_course_record(self, db_session, sample_completed_generation_job):
        """A CourseRecord is created with the correct title and description."""
        pass

    async def test_confirm_creates_page_records(self, db_session, sample_completed_generation_job):
        """PageRecord entries are created for each non-removed page."""
        pass

    async def test_confirm_creates_component_records(self, db_session, sample_completed_generation_job):
        """ComponentRecord entries are created for each page's components."""
        pass

    async def test_confirm_writes_audit_log(self, db_session, sample_completed_generation_job):
        """An audit log entry with operation=course_create_from_file is created."""
        pass

    async def test_confirm_writes_outbox_event(self, db_session, sample_completed_generation_job):
        """An outbox event of type CourseCreatedFromFile is created."""
        pass

    async def test_confirm_updates_generation_job_to_completed(self, db_session, sample_completed_generation_job):
        """The generation job status is 'completed' with course_id populated."""
        pass

    async def test_confirm_atomic_rollback_on_failure(self, db_session, sample_completed_generation_job, monkeypatch):
        """If any page creation fails, the entire transaction rolls back."""
        pass

    async def test_confirm_idempotent_second_call_returns_same_course_id(self, db_session, sample_completed_generation_job):
        """Calling confirm twice returns the existing course_id without duplicating."""
        pass

    async def test_confirm_job_not_in_awaiting_confirmation_returns_error(self, db_session, sample_pending_generation_job):
        """A job still in 'generating' status cannot be confirmed."""
        pass


class TestPromptBuilder:
    async def test_build_system_prompt_includes_version(self):
        """The system prompt includes a version identifier."""
        pass

    async def test_build_mcq_prompt_includes_schema(self):
        """The MCQ prompt includes questions array schema with options and isCorrect."""
        pass

    async def test_build_final_assessment_prompt_includes_mixed_types(self):
        """The final-assessment prompt includes mcq, true-false, and fill-in-blank types."""
        pass

    async def test_parse_llm_response_clean_json(self):
        """A clean JSON string parses successfully."""
        pass

    async def test_parse_llm_response_code_fenced_json(self):
        """A ```json ... ``` fenced code block parses successfully."""
        pass

    async def test_parse_llm_response_with_trailing_text(self):
        """JSON with trailing explanatory text extracts the JSON portion."""
        pass

    async def test_parse_llm_response_unparseable_returns_none(self):
        """Completely unparseable text returns None."""
        pass

    async def test_build_retry_prompt_includes_previous_errors(self):
        """The retry prompt includes the validation error messages from the failed attempt."""
        pass
```

### 6.2 Integration Tests (API Layer)

```python
# File: tests/test_ai_course_generation_api.py

class TestGenerateCourseAPI:
    async def test_generate_course_endpoint_returns_202(self, async_client, sample_import_job_with_approved_plan):
        """POST /api/v1/ai/generate-course returns 202 with job ID."""
        pass

    async def test_generate_course_invalid_import_job_returns_404(self, async_client):
        """A non-existent import job returns 404."""
        pass

    async def test_generate_course_feature_flag_disabled_returns_404(self, async_client):
        """When AI_AUTHORING_ENABLED=false, endpoint returns 404."""
        pass

    async def test_generate_course_response_shape(self, async_client, sample_import_job_with_approved_plan):
        """Response includes generation_job_id, status, total_pages, estimated_templates."""
        pass


class TestGenerationJobStatusAPI:
    async def test_status_endpoint_returns_progress(self, async_client, sample_generating_job):
        """GET returns current status and progress."""
        pass

    async def test_status_endpoint_unknown_job_returns_404(self, async_client):
        """A non-existent generation job returns 404."""
        pass

    async def test_status_endpoint_shows_completed_pages(self, async_client, sample_generating_job):
        """The completed_pages count matches the page logs count."""
        pass


class TestGenerationPreviewAPI:
    async def test_preview_endpoint_returns_pages(self, async_client, sample_completed_generation_job):
        """GET preview returns all generated pages with validation status."""
        pass

    async def test_preview_endpoint_not_ready_returns_400(self, async_client, sample_generating_job):
        """A job still generating returns 400 with JOB_NOT_READY."""
        pass

    async def test_preview_endpoint_unknown_job_returns_404(self, async_client):
        """A non-existent generation job returns 404."""
        pass

    async def test_preview_response_shape(self, async_client, sample_completed_generation_job):
        """Response includes course_title, pages[], validation_summary, source info."""
        pass


class TestConfirmGenerationAPI:
    async def test_confirm_endpoint_returns_200_with_course_id(self, async_client, sample_completed_generation_job):
        """POST confirm with user_confirmed=true returns course_id."""
        pass

    async def test_confirm_without_approval_returns_400(self, async_client, sample_completed_generation_job):
        """user_confirmed=false returns 400."""
        pass

    async def test_confirm_unknown_job_returns_404(self, async_client):
        """A non-existent generation job returns 404."""
        pass

    async def test_confirm_course_created_verifiable_via_courses_api(self, async_client, sample_completed_generation_job):
        """After confirm, GET /api/v1/courses/{course_id} returns the new course."""
        pass

    async def test_confirm_pages_verifiable_via_pages_api(self, async_client, sample_completed_generation_job):
        """After confirm, pages exist and are queryable."""
        pass
```

### 6.3 E2E Scenarios

**Scenario 1: Full course generation from PDF (happy path)**
1. User uploads `safety_manual_2026.pdf` via the file upload UI.
2. Backend creates an import job (US-AI-016), status `pending`.
3. Backend extracts the PDF, segments into 12 sections (US-AI-017).
4. Frontend shows the page plan: 12 pages with suggested template types.
5. User reviews, renames page 3, changes page 7 template from `content-text` to `tabs`, approves the plan.
6. Backend updates import job status to `plan_approved`.
7. Frontend calls `POST /api/v1/ai/generate-course` with `import_job_id`.
8. Backend returns `{generation_job_id: "gen_789", status: "pending", total_pages: 12}`.
9. Frontend polls `GET /api/v1/ai/generate-course/gen_789` every 5 seconds.
10. After ~90 seconds, status is `awaiting_confirmation` with `batch_proposal_id`.
11. Frontend calls preview and shows the course: 12 pages, all pass validation, 2 advisory warnings.
12. User clicks "Approve and Create Course".
13. Backend creates `CourseRecord`, 12 `PageRecord`s, ~36 `ComponentRecord`s.
14. Backend returns `{course_id: "course_safety_001", page_count: 12}`.
15. Frontend navigates to the editor with the new course loaded.

**Scenario 2: LLM generation retry and recovery**
1. Page plan has 12 pages. Page 6 is `mcq`.
2. LLM generates pages 0-5 successfully.
3. For page 6, LLM returns invalid JSON (missing a closing brace).
4. Backend detects parse failure, builds a retry prompt with the error, sends to LLM.
5. LLM retry returns valid JSON with 3 questions.
6. Validation detects that question 2 has no correct answer marked.
7. Backend sends a second retry with validation error feedback.
8. LLM third attempt returns valid MCQ with correct structure.
9. All 12 pages generated successfully; course proceeds to review.

**Scenario 3: Page plan with removed pages at confirmation**
1. Generated course has 10 pages.
2. User reviews preview, decides pages 4 and 7 are unnecessary.
3. User clicks "Remove" on pages 4 and 7 in the preview UI.
4. User clicks "Approve" with `removed_page_indices: [4, 7]`.
5. Backend creates the course with 8 pages (original page 5 becomes page 4, etc.).
6. Orders are resequenced to be zero-based contiguous.
7. Audit log records `removed_page_indices: [4, 7]` and original page titles.

**Scenario 4: Full generation failure with exhausted retries**
1. Page plan has 15 pages. Page 8 is `final-assessment`.
2. LLM repeatedly returns invalid content for the final-assessment page across 3 retries: first with missing required field `questions`, second with a question missing `type`, third with unparseable JSON.
3. Backend marks the generation job as `failed` with `failed_page_index: 8`.
4. Frontend shows error message: "Failed to generate page 'Final Knowledge Check' after 3 retries: Schema validation failed: final-assessment questions field is required."
5. User can either retry the entire job (which regenerates all pages) or return to the page plan to adjust the template type suggestion for the failing page.

**Scenario 5: Preview shows validation warnings**
1. Generated course has 10 pages. Page 3 (`mcq`) has only 2 options on question 2 (minimum, triggers a warning). Page 8 (`content-text`) has only 40 characters of body content (very short, triggers a warning).
2. Full-course validation passes with 0 errors and 2 warnings.
3. Preview shows green "Pass" badge with "2 warnings" link.
4. User expands the warning details: "Page 3: MCQ question 2 has only 2 options; consider adding 2 more." and "Page 8: Content page body is very short (40 chars); consider expanding."
5. User can still approve the course (warnings do not block apply).
6. After apply, warnings are recorded in the audit trail for quality tracking.

### 6.4 Safety Invariant Tests

```python
# Invariant: generation never creates course records
async def test_invariant_generation_does_not_create_course(test_client, sample_import_job_with_approved_plan):
    """Calling POST /api/v1/ai/generate-course does not create a CourseRecord."""
    response = await test_client.post("/api/v1/ai/generate-course", json={
        "import_job_id": sample_import_job_with_approved_plan["job_id"],
    })
    assert response.status_code == 202
    # Verify no CourseRecord was created
    courses_response = await test_client.get("/api/v1/courses")
    original_course_ids = {c["courseId"] for c in courses_response.json()}
    # No new course_id from generation
    ...

# Invariant: generation does not mutate the import job
async def test_invariant_generation_does_not_mutate_import_job(test_client, sample_import_job_with_approved_plan):
    """Generation does not change the import job's status or data."""
    pass

# Invariant: confirm without user_confirmed=true never creates a course
async def test_invariant_no_approval_no_course_creation(test_client, sample_completed_generation_job):
    """Calling confirm with user_confirmed=false does not create any records."""
    pass

# Invariant: all generated pages are validated before batch proposal
async def test_invariant_all_pages_validated_before_proposal(test_client, sample_import_job_with_approved_plan, monkeypatch):
    """The batch proposal is only created after all pages pass validation."""
    pass
```

### 6.5 Concurrency Tests

```python
async def test_concurrent_generation_same_import_job(test_client, sample_import_job_with_approved_plan):
    """Two concurrent generate-course calls for the same import job result in
    one job created and the second returning the existing job_id (not a duplicate)."""
    pass

async def test_confirm_while_generation_in_progress(test_client, sample_generating_job):
    """Calling confirm on a job still in 'generating' status returns an error."""
    pass

async def test_max_concurrent_jobs_enforced(test_client):
    """When AI_GENERATION_MAX_CONCURRENT_JOBS (5) is reached, new generation
    requests are rejected with a 429 or queued."""
    pass
```

---

## 7. Definition of Done

### 7.1 Code Complete

- [ ] `app/models/course_generation.py` — ORM models for `CourseGenerationJobRecord` and `GenerationPageLogRecord` with all fields as specified in section 2.2.
- [ ] `app/repositories/course_generation_repo.py` — Repository with `create`, `get_by_job_id`, `get_by_import_job_id`, `update_status`, `create_page_log`, `update_page_log`, `get_page_logs`.
- [ ] `app/services/ai/course_generator.py` — `CourseGenerator` with `start_generation`, `_execute_generation`, `_generate_single_page`, `_validate_generated_page`, `_run_full_course_validation`, `_create_batch_proposal`, `confirm_and_apply`.
- [ ] `app/services/ai/prompt_builder.py` — `PromptBuilder` with `build_system_prompt`, `build_page_prompt`, `build_retry_prompt`, `parse_llm_response`.
- [ ] `app/routers/ai_course_generation.py` — Router with `POST /api/v1/ai/generate-course`, `GET /api/v1/ai/generate-course/{job_id}`, `GET /api/v1/ai/generate-course/{job_id}/preview`, `POST /api/v1/ai/generate-course/{job_id}/confirm`.
- [ ] `app/routers/ai_course_generation_dtos.py` — All Pydantic request/response models.
- [ ] Alembic migration for `course_generation_jobs` and `generation_page_logs` tables.
- [ ] Registration in `app/main.py` (router import + include_router + ORM model import in lifespan).
- [ ] Registration in `app/models/__init__.py`.
- [ ] Environment variables added to `.env` and `.env.example`.

### 7.2 Tests Pass

- [ ] All unit tests pass (30+ tests across `test_course_generator.py` and `test_prompt_builder.py`).
- [ ] All integration tests pass (10+ tests in `test_ai_course_generation_api.py`).
- [ ] All safety invariant tests pass (4 tests).
- [ ] All concurrency tests pass (3 tests).
- [ ] Existing import, course, and page CRUD tests still pass (regression).
- [ ] Coverage >= 90% for new code.

### 7.3 Documentation

- [ ] API contracts documented in `docs/API.md` or OpenAPI spec.
- [ ] Environment variables documented in `.env.example`.
- [ ] Flow diagrams in `docs/AI_Implemenation/01_SystemArchitecture/` updated to include the generation flow.

### 7.4 Security

- [ ] All generation endpoints gated by `AI_AUTHORING_ENABLED=true`.
- [ ] Source material excerpts are truncated and sanitized before prompt construction.
- [ ] LLM responses are validated against server-side schemas; unvalidated content is never stored.
- [ ] User confirmation is required before any data is persisted.
- [ ] Audit trail includes full after_snapshot, file_hash, model_id, and prompt version.

### 7.5 Operational Readiness

- [ ] Feature flag `AI_AUTHORING_ENABLED` gates all generation endpoints.
- [ ] Max concurrent generation jobs per tenant is enforced.
- [ ] Generation job TTL is enforced (48h default).
- [ ] Per-page LLM latency is tracked in `generation_page_logs.llm_latency_ms`.
- [ ] Metrics counters for generation started, page generated, generation completed, generation failed.
- [ ] Failed jobs preserve error context (page index, error message, retry count) for debugging.

---

## 8. Tasks

### Task 1: Create ORM Models and Repository

**Files to create/modify:**
- `app/models/course_generation.py` (new)
- `app/models/__init__.py` (add import)
- `app/repositories/course_generation_repo.py` (new)

**Acceptance:**
- `CourseGenerationJobRecord` has all columns as specified in section 2.2 (job_id, import_job_id, status, progress, generation_config, approved_page_plan, generated_course, validation_result, error_message, failed_page_index, file_hash, source_type, model_id, prompt_versions, generation_attempts, expires_at, timestamps).
- `GenerationPageLogRecord` has all columns as specified in section 2.2 (job_id, page_index, page_title, template_type, status, retry_count, prompt_sent, response_received, generated_data, validation_errors, validation_warnings, llm_latency_ms, timestamps).
- `to_dict()` serializes all fields with correct key naming.
- Repository can create, get, update generation jobs and page logs.
- Repository can list jobs by import job ID and page logs by job ID.

**Effort:** 3 hours
**Dependencies:** US-AI-004 (table designs)

---

### Task 2: Create Pydantic DTOs

**File to create:**
- `app/routers/ai_course_generation_dtos.py` (new)

**Acceptance:**
- `GenerateCourseRequest`, `GenerateCourseResponse`, `GenerationJobStatusResponse`, `GeneratedPageSummary`, `GenerationPreviewResponse`, `ConfirmGenerateCourseRequest`, `ConfirmGenerateCourseResponse`, `GenerationJobError` match the contracts in sections 2.3-2.4.
- All fields use descriptive descriptions for OpenAPI schema generation.
- `GenerationPreviewResponse` correctly nests `GeneratedPageSummary` list.

**Effort:** 1 hour
**Dependencies:** None

---

### Task 3: Implement PromptBuilder

**File to create:**
- `app/services/ai/prompt_builder.py`

**Acceptance:**
- `build_system_prompt()` returns a string with content generation instructions and schema version.
- `build_page_prompt()` constructs a prompt with course context, page context, template schema, and optional source excerpt.
- Template schemas exist for all supported types: welcome, content-text, content-video, mcq, tabs, accordion, summary, final-assessment, text-with-media.
- `build_retry_prompt()` includes the original prompt, the failed response, and the validation errors.
- `parse_llm_response()` handles: clean JSON, code-fenced JSON, JSON with trailing text, unparseable text (returns None).
- `parse_llm_response()` handles truncation: if the JSON is cut off at the end, tries to find the last valid complete object.

**Effort:** 4 hours
**Dependencies:** None

---

### Task 4: Implement Page Content Generator

**File to create:**
- `app/services/ai/page_content_generator.py` (can be a module within `CourseGenerator` or separate)

**Acceptance:**
- `generate_page_content(page_plan, course_context, template_schema) -> dict` calls the LLM, parses the response, validates against schema, and retries on failure.
- On success, returns complete page data dict ready for inclusion in the course structure.
- On failure after MAX_RETRIES, raises `PageGenerationError` with the page index and last error.
- Validation checks cover: required fields present, field types match schema, MCQ has at least one correct answer, assessment questions have valid types, content is non-empty for text templates.
- Every attempt (including retries) is logged to `GenerationPageLogRecord` via the repository.
- LLM call is injected as a callable parameter so tests can mock it without real API calls.

**Effort:** 6 hours
**Dependencies:** Task 3 (PromptBuilder), Task 1 (repository for logging)

---

### Task 5: Implement LLM Provider Client

**File to create:**
- `app/services/ai/llm_client.py` (new)

**Acceptance:**
- `LLMClient.call(prompt: str, model: str, timeout: int) -> str` makes an HTTP request to the configured LLM provider endpoint.
- Reads provider URL and API key from environment variables (`AI_LLM_PROVIDER_URL`, `AI_LLM_API_KEY`).
- Supports configurable model selection (default from `AI_GENERATION_MODEL`).
- Implements timeout via `asyncio.wait_for` with configurable seconds.
- Implements retry with exponential backoff (2s, 4s, 8s) on HTTP 5xx and timeout errors.
- Returns the response text on success.
- Raises `LLMProviderError` with the HTTP status and message on non-retryable errors (4xx).
- Raises `LLMTimeoutError` when the timeout is exceeded.
- All calls are logged with `model`, `prompt_length`, `response_length`, `latency_ms`.

**Effort:** 4 hours
**Dependencies:** None (standalone HTTP client)

---

### Task 6: Implement CourseGenerator — Generation Pipeline

**File to create:**
- `app/services/ai/course_generator.py` — implement `start_generation`, `_execute_generation`, `_generate_single_page`, `_build_prompt_for_page`, `_call_llm_with_retry`, `_validate_generated_page`, `_run_full_course_validation`, `_create_batch_proposal`

**Acceptance:**
- `start_generation`: validates import job exists and has `plan_approved` status, validates page plan has at least one page and does not exceed `AI_GENERATION_MAX_PAGES`, creates `CourseGenerationJobRecord` with status `pending`, enqueues execution (or runs inline in development), returns job_id.
- `_execute_generation`: iterates pages in order, calls `_generate_single_page` for each, updates job progress after each page, runs `_run_full_course_validation` after all pages, creates batch proposal via `_create_batch_proposal`, updates job to `awaiting_confirmation`.
- If any page fails after retries, marks job as `failed` with `failed_page_index` and stops.
- `_validate_generated_page`: validates the generated page data against the template schema. Returns (errors[], warnings[]).
- `_run_full_course_validation`: validates the full course against Course Pydantic model, business rules (navigation completeness, ordering), and export readiness (supported template types). Returns {"passed": bool, "errors": [...], "warnings": [...]}.
- `_create_batch_proposal`: creates a batch proposal (US-AI-029) containing all pages, linked to the generation job and import job. Returns batch_proposal_id.

**Effort:** 10 hours
**Dependencies:** Tasks 1, 3, 4, 5; US-AI-029 (batch proposal semantics)

---

### Task 7: Implement CourseGenerator — Confirm and Apply

**File to modify:**
- `app/services/ai/course_generator.py` — implement `confirm_and_apply`

**Acceptance:**
- Loads the generation job and verifies status is `awaiting_confirmation`.
- Verifies `user_confirmed == True`.
- Loads the batch proposal and verifies status is `PENDING_REVIEW`.
- Excludes any pages in `removed_page_indices` from the apply set.
- Verifies at least one page remains after removal.
- Begins database transaction:
  - Creates `CourseRecord` with `course_id` (auto-generated UUID), title, description, generated course data as `json_data`.
  - Creates `PageRecord` for each page with correct order (resequenced to zero-based contiguous).
  - Creates `ComponentRecord` for each component in each page.
  - Writes audit log entry with `operation=course_create_from_file`, full `after_snapshot`, `source_import_job_id`, `file_hash`, `source_type`, `model_id`, `prompt_versions`.
  - Writes outbox event `CourseCreatedFromFile` version 1.
  - Updates batch proposal status to `APPLIED`.
  - Updates generation job status to `completed` with `course_id`.
- On any error during the transaction, rolls back completely and raises `CourseGenerationError`.
- On success, returns `{course_id, course_title, page_count, batch_proposal_id}`.

**Effort:** 6 hours
**Dependencies:** Task 6, US-AI-010 (audit + outbox patterns), US-AI-029 (batch proposal apply)

---

### Task 8: Create API Router and Wire Endpoints

**File to create/modify:**
- `app/routers/ai_course_generation.py` (new)
- `app/main.py` (register router + ORM model import)
- `app/models/__init__.py` (add import)

**Acceptance:**
- `POST /api/v1/ai/generate-course` calls `CourseGenerator.start_generation`.
- `GET /api/v1/ai/generate-course/{generation_job_id}` returns job status, progress, and metadata.
- `GET /api/v1/ai/generate-course/{generation_job_id}/preview` returns full course preview with per-page validation (only when status is `awaiting_confirmation` or `completed`).
- `POST /api/v1/ai/generate-course/{generation_job_id}/confirm` calls `CourseGenerator.confirm_and_apply`.
- Error responses match the error envelope pattern.
- AI feature flag gating is applied via `ai_authoring_enabled` dependency.
- Router is registered in `api_router` under `/api/v1` prefix.
- ORM model is imported during startup so `create_all` creates the tables.

**Effort:** 3 hours
**Dependencies:** Tasks 6, 7

---

### Task 9: Create Alembic Migration

**File to create:**
- `alembic/versions/20260614_0002_add_course_generation_tables.py`

**Acceptance:**
- Creates `course_generation_jobs` table with all columns as specified in section 2.1.
- Creates `generation_page_logs` table with all columns as specified in section 2.1.
- All indexes as specified: `idx_cgj_import_job`, `idx_cgj_status`, `idx_cgj_course`, `idx_cgj_created`, `idx_gpl_job`, `idx_gpl_page_index`.
- Foreign keys with correct ON DELETE CASCADE behavior.
- `downgrade()` drops both tables.
- Migration runs cleanly against both SQLite (dev) and PostgreSQL (prod).

**Effort:** 1.5 hours
**Dependencies:** Task 1 (table column definitions)

---

### Task 10: Write Unit Tests for Service Layer

**Files to create:**
- `tests/test_course_generator.py`
- `tests/test_prompt_builder.py`

**Acceptance:**
- All test scenarios from section 6.1 are covered.
- Safety invariant tests from section 6.4 pass.
- Concurrency tests from section 6.5 pass.
- Tests use in-memory SQLite test fixtures and mock the LLM callable via `monkeypatch`.
- Coverage >= 90% for `course_generator.py`, `prompt_builder.py`, `llm_client.py`.
- Mock LLM responses cover: valid JSON, malformed JSON, code-fenced JSON, JSON with trailing text, empty responses, timeout errors.

**Effort:** 8 hours
**Dependencies:** Tasks 3, 4, 5, 6, 7

---

### Task 11: Write Integration Tests for API Layer

**File to create:**
- `tests/test_ai_course_generation_api.py`

**Acceptance:**
- All test scenarios from section 6.2 are covered.
- Tests use `TestClient` and existing `conftest.py` fixtures.
- Test fixtures include: `sample_import_job_with_approved_plan`, `sample_generating_job`, `sample_completed_generation_job`.
- Existing import, course, and page CRUD tests still pass.
- Tests cover success, error, and feature-flag-disabled paths.
- Tests verify course creation by querying `/api/v1/courses/{course_id}` after confirm.

**Effort:** 5 hours
**Dependencies:** Task 8

---

### Task 12: Add Environment Variables and Configuration

**Files to modify:**
- `.env.example`
- `.env`
- `app/services/ai/course_generator.py` (read config from env)
- `app/services/ai/llm_client.py` (read provider URL and API key)

**Acceptance:**
- `AI_GENERATION_MODEL` defaults to `deepseek-v4-flash`.
- `AI_GENERATION_RETRY_COUNT` defaults to 3.
- `AI_GENERATION_JOB_TTL_HOURS` defaults to 48.
- `AI_GENERATION_MAX_PAGES` defaults to 50.
- `AI_GENERATION_MAX_CONCURRENT_JOBS` defaults to 5.
- `AI_GENERATION_TIMEOUT_SECONDS` defaults to 120.
- `AI_LLM_PROVIDER_URL` and `AI_LLM_API_KEY` configured for the LLM provider client.
- Configuration is read at module level or injected via constructor.
- Missing optional variables log a warning and use default.

**Effort:** 1 hour
**Dependencies:** Tasks 5, 6

---

### Task 13: Documentation and Review

**Files to modify:**
- `docs/AI_Implemenation/00_User_StoriesUseCases/USER_STORIES.md` (update status)
- `docs/API.md` or OpenAPI spec (add new endpoints)
- `docs/AI_Implemenation/01_SystemArchitecture/` (update flow diagrams if needed)

**Acceptance:**
- API contracts for all 4 endpoints are documented.
- Environment variables are documented in `.env.example` and the story.
- Flow diagrams updated to reflect the generation pipeline.
- Story is marked complete in the canonical user stories list.

**Effort:** 2 hours
**Dependencies:** Tasks 8, 10, 11, 12

---

### Task 14: Code Review and Merge

**Acceptance:**
- All CI checks pass.
- Two approvals on the PR.
- No regression in existing tests (import, course CRUD, page CRUD, export).
- Feature flag `AI_AUTHORING_ENABLED` defaults to `false`.
- LLM provider credentials are not committed; loaded from environment.
- Migration runs without errors on a fresh database.

**Effort:** 2 hours
**Dependencies:** All prior tasks

---

## Summary

| Metric | Value |
|---|---|
| New files | 8 |
| Modified files | 5 |
| New tables | 2 |
| New API endpoints | 4 |
| New services | 3 (CourseGenerator, PromptBuilder, LLMClient) |
| Total estimated effort | ~56.5 hours |
| Key safety invariant | Generation never creates course records without explicit user confirmation |
| Key risk | LLM provider availability and latency during generation; retry logic mitigates transient failures |
