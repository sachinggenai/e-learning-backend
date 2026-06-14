# US-AI-031: RLHF Feedback and Provenance Tracking

**Status:** Draft  
**Priority:** SHOULD (Quality) -- MUST for production AI pipeline  
**Depends on:** US-AI-023 (AI Chat Endpoint), US-AI-025 (Prompt Safety Guardrails), US-AI-010 (Apply Safety, Audit, and Outbox)  
**Source flows:** RLHF Feedback Loop, Provenance Trace, Model Improvement Pipeline  
**Epic Owner:** Technical Product Owner  

---

## 1. Functional Specification

### 1.1 User Story

As an **Author**, I want to rate AI-generated content proposals (thumbs up/down, star rating, free-text comment) and see which model, session, turn, and tool call produced each piece of content, so that I can trust the AI output and provide signal that improves future generations.

As a **Platform Operator / ML Engineer**, I want to export structured feedback + full provenance chains (model ID, prompt version, session context, course snapshot) for every AI action, so that I can build reward-model datasets, fine-tune models, and audit AI behavior over time.

### 1.2 Overview

This user story delivers the **RLHF feedback collection system** and the **provenance tracking layer** for every AI-generated mutation in the platform.

**Feedback collection** gives authors a lightweight way to signal quality:
- Thumbs-up / thumbs-down on any AI chat response (session-granularity).
- Star rating (1-5) per turn or per proposal.
- Free-text comment attached to feedback events.
- Feedback is linkable to a specific turn, tool call, proposal, or final LLM output.

**Provenance tracking** records the full ancestry of every AI-authored mutation:
- Which model ID (e.g., `claude-sonnet-4-20250514`) produced the content.
- Which system prompt version was active at the time.
- The session ID, turn ID, and tool call ID that generated the proposal.
- The exact input context (course ID, page count, preceding messages) at generation time.
- The schema signature of course data at mutation time (for exact replay).

**Key design decisions:**

- **Feedback is append-only, never mutable.** Once a user submits feedback, it cannot be edited or deleted (compliance requirement). Corrections are submitted as new feedback records referencing the same target.
- **Provenance is captured at propose-time, not apply-time.** The provenance record is created when the LLM proposes content, not when the user confirms it. This captures the exact generation context before user edits may have been applied.
- **Thumbs-down feedback can optionally trigger a retry.** When `AI_FEEDBACK_RETRY_ENABLED=true`, a thumbs-down with a comment can trigger the LLM to regenerate the proposal in a new turn (via the existing chat orchestrator).
- **Batch export for ML pipelines.** Feedback + provenance can be exported as JSONL or CSV for offline reward-model training, with optional PII redaction.
- **No feedback on server errors or guardrail blocks.** Feedback is only collected on successful AI interactions, not on error or blocked responses.

### 1.3 Actors

| Actor | Role |
|---|---|
| Author (User) | Submits thumbs-up/down, ratings, comments on AI responses and proposals |
| Platform Operator | Views feedback dashboards, configures feedback-to-retry behavior, manages feedback exports |
| ML Engineer | Exports feedback + provenance datasets for model improvement, configures feedback sampling |
| AI Chat Orchestrator | Attaches provenance metadata to every tool call result |
| Feedback API (Server) | Ingests and persists feedback events, validates targets exist |
| Provenance Collector (Server) | Captures generation context at propose-time and stores it in the provenance log |
| Feedback Export Service | Produces structured JSONL/CSV exports with optional PII redaction |
| Proposal System | Links provenance records to proposals, surfaces feedback in proposal status |

### 1.4 Flows

#### Flow 1: Author Submits Feedback on Chat Response

1. Author completes a chat turn. The frontend renders the AI's response and shows a thumbs-up / thumbs-down widget below the response.
2. Author clicks thumbs-down and optionally adds a free-text comment: "This page does not match the course tone. It is too formal."
3. Frontend calls `POST /api/v1/ai/feedback` with:
   ```json
   {
     "target_type": "turn",
     "target_id": "turn_abc123",
     "rating": "thumbs_down",
     "comment": "This page does not match the course tone. It is too formal.",
     "session_id": "sess_xyz"
   }
   ```
4. Backend validates:
   - Session exists and belongs to the authenticated user.
   - Turn exists and belongs to the session.
   - Feedback has not already been submitted for this `(session_id, target_type, target_id)` combination from this user (idempotency by user -- one feedback per target per user). If duplicate, return existing record (idempotent).
   - Rating is one of `["thumbs_up", "thumbs_down", "star_1", "star_2", "star_3", "star_4", "star_5"]`.
5. Backend persists the feedback record and returns HTTP 201 with the feedback ID.
6. If `AI_FEEDBACK_RETRY_ENABLED=true` and rating is `thumbs_down` with a non-empty comment, the backend optionally creates a background task to queue a regeneration request (the frontend polls for the new proposal).
7. Frontend shows a confirmation toast: "Thank you for your feedback."

#### Flow 2: Author Submits Feedback on a Specific Proposal

1. Author reviews an AI proposal (e.g., a proposed new page). The proposal preview includes a feedback widget.
2. Author rates the proposal 4 out of 5 stars and adds a comment.
3. Frontend calls `POST /api/v1/ai/feedback` with:
   ```json
   {
     "target_type": "proposal",
     "target_id": "prop_045",
     "rating": "star_4",
     "comment": "Good structure but the assessment questions are too easy.",
     "session_id": "sess_xyz"
   }
   ```
4. Backend validates the proposal exists, belongs to the session's course, and is in a state that accepts feedback (any state except `EXPIRED`).
5. Backend persists the feedback record. The proposal status changes to include `"hasFeedback": true` and `"feedbackSummary": {"rating": "star_4", "count": 1}`.
6. The frontend refreshes the proposal card to show the feedback was received.

#### Flow 3: Provenance Capture at Proposal Time

1. The AI chat orchestrator processes a turn. The LLM calls `propose_create_page` with the page data.
2. The `ToolExecutor` executes the proposal. After creating the `ai_proposals` record, it calls the `ProvenanceCollector` service.
3. The `ProvenanceCollector` captures:
   - `session_id`, `turn_id`, `tool_call_id` from the current turn context.
   - `model_id` -- the LLM model that generated the content (e.g., `claude-sonnet-4-20250514`).
   - `prompt_version` -- the system prompt version at the time (`AI_SYSTEM_PROMPT_VERSION`).
   - `provider` -- the LLM provider (`anthropic`, `openai`, etc.).
   - `input_context_snapshot` -- JSON snapshot of the course state at generation time (course ID, page count, component count, schema signatures of each page).
   - `proposal_payload_hash` -- SHA-256 of the proposal data (for drift detection at apply time).
   - `schema_signature` -- the schema version of course data at mutation time.
4. The provenance record is linked to the proposal via `proposal_id`.
5. If the same turn produced multiple proposals (e.g., batch create), each proposal gets its own provenance record.

#### Flow 4: Provenance Query and Export

1. Platform Operator navigates to the admin compliance dashboard.
2. They select "AI Provenance" and filter by course, model, date range, or rating.
3. The API returns a list of provenance records with linked feedback.
4. They click "Export as JSONL" and select a date range.
5. The backend generates the export asynchronously (if > 1000 rows) or synchronously. The export includes:
   - Provenance metadata (model, prompt version, timestamps).
   - Linked feedback (rating, comment, timestamp).
   - Proposal payload hash and course snapshot at generation time.
   - PII fields optionally redacted if `AI_EXPORT_REDACT_PII=true`.

### 1.5 Edge Cases and Error Handling

| Scenario | Expected Behavior |
|---|---|
| User submits duplicate feedback for same target | Return existing feedback record (idempotent, HTTP 200) |
| User submits feedback for an expired session | Return 404 SESSION_NOT_FOUND |
| User submits feedback for a non-existent proposal | Return 404 PROPOSAL_NOT_FOUND |
| Feedback comment exceeds 2000 characters | Return 422 with field error at `comment` |
| Rating value is invalid (not in enum) | Return 422 with field error at `rating` |
| Provenance capture fails (DB error) | Non-blocking: log error and continue. Proposal creation is not rolled back |
| Feedback submitted on server-error response | Not allowed; feedback endpoints only accept valid target IDs that exist |
| Export request exceeds 10,000 rows | Async job created, frontend polls for download-ready status |
| Provenance for a turn that had mixed success (some tools succeeded, some failed) | Each successful tool call that produced a proposal gets a provenance record. Failed tool calls leave no provenance |
| Proposal payload hash differs at apply time vs. propose time | Provenance record flagged with `DRIFT_DETECTED` warning, but apply proceeds |

---

## 2. Technical Specification

### 2.1 New Database Tables -- DDL

**Table: `ai_feedback`**

```sql
CREATE TABLE ai_feedback (
    id                  SERIAL PRIMARY KEY,
    feedback_id         VARCHAR(64) UNIQUE NOT NULL,
    session_id          VARCHAR(64) NOT NULL REFERENCES ai_sessions(session_id) ON DELETE CASCADE,
    user_id             VARCHAR(128) NOT NULL,
    
    -- Target polymorphic reference
    target_type         VARCHAR(32) NOT NULL CHECK (target_type IN ('turn', 'proposal', 'tool_call', 'message')),
    target_id           VARCHAR(64) NOT NULL,
    
    -- Rating (closed enum for queryability)
    rating              VARCHAR(16) NOT NULL CHECK (rating IN (
                            'thumbs_up', 'thumbs_down',
                            'star_1', 'star_2', 'star_3', 'star_4', 'star_5'
                        )),
    
    -- Optional free-text
    comment             TEXT,
    
    -- Traceability
    trace_id            VARCHAR(64),
    
    -- Immutable timestamps
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_af_session ON ai_feedback(session_id);
CREATE INDEX idx_af_user ON ai_feedback(user_id);
CREATE INDEX idx_af_target ON ai_feedback(target_type, target_id);
CREATE INDEX idx_af_rating ON ai_feedback(rating);
CREATE INDEX idx_af_created ON ai_feedback(created_at DESC);

-- Enforce one feedback per user per target (idempotency)
CREATE UNIQUE INDEX idx_af_unique_user_target ON ai_feedback(user_id, target_type, target_id);
```

**Table: `ai_provenance`**

```sql
CREATE TABLE ai_provenance (
    id                      SERIAL PRIMARY KEY,
    provenance_id           VARCHAR(64) UNIQUE NOT NULL,
    session_id              VARCHAR(64) NOT NULL REFERENCES ai_sessions(session_id) ON DELETE CASCADE,
    turn_id                 VARCHAR(64) NOT NULL,
    tool_call_id            VARCHAR(64) NOT NULL,
    proposal_id             VARCHAR(64),       -- NULL until proposal-created
    
    -- Model identity
    model_id                VARCHAR(128) NOT NULL,
    provider                VARCHAR(32) NOT NULL DEFAULT 'anthropic',
    prompt_version          VARCHAR(32) NOT NULL DEFAULT '1.0',
    
    -- Generation context (snapshot at propose time)
    course_id               VARCHAR(64) NOT NULL,
    course_snapshot         JSONB NOT NULL DEFAULT '{}',
    -- Contains: pageCount, componentCount, schemaSignatures per page,
    --           courseStatus, hasPendingProposals
    
    -- Content fingerprint
    proposal_payload_hash   VARCHAR(64) NOT NULL,   -- SHA-256 of proposal data JSON
    schema_signature        VARCHAR(64) NOT NULL,   -- Course schema version
    
    -- LLM telemetry at generation time
    input_tokens            INTEGER,
    output_tokens           INTEGER,
    latency_ms              INTEGER,
    
    -- Drift detection
    drift_status            VARCHAR(16) DEFAULT 'clean'
                            CHECK (drift_status IN ('clean', 'drift_detected', 'not_applicable')),
    
    -- Immutable timestamps
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ap_session ON ai_provenance(session_id);
CREATE INDEX idx_ap_turn ON ai_provenance(turn_id);
CREATE INDEX idx_ap_tool_call ON ai_provenance(tool_call_id);
CREATE INDEX idx_ap_proposal ON ai_provenance(proposal_id);
CREATE INDEX idx_ap_course ON ai_provenance(course_id);
CREATE INDEX idx_ap_model ON ai_provenance(model_id);
CREATE INDEX idx_ap_created ON ai_provenance(created_at DESC);
```

**Table: `ai_feedback_tags`** (optional metadata tags for ML pipeline classification)

```sql
CREATE TABLE ai_feedback_tags (
    id                  SERIAL PRIMARY KEY,
    feedback_id         VARCHAR(64) NOT NULL REFERENCES ai_feedback(feedback_id) ON DELETE CASCADE,
    tag                 VARCHAR(64) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE (feedback_id, tag)
);

CREATE INDEX idx_aft_tag ON ai_feedback_tags(tag);
```

### 2.2 SQLAlchemy ORM Models

**New file: `app/models/ai_feedback.py`**

```python
"""ORM models for RLHF feedback and provenance tracking.

Includes: AIFeedbackRecord, AIProvenanceRecord, AIFeedbackTagRecord.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import (
    String, DateTime, JSON, Text, Integer, ForeignKey, BigInteger,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMPTZ

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


_RATING_VALUES = (
    "thumbs_up", "thumbs_down",
    "star_1", "star_2", "star_3", "star_4", "star_5",
)


class AIFeedbackRecord(Base):
    """Immutable feedback record from an author on an AI action."""

    __tablename__ = "ai_feedback"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    feedback_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_sessions.session_id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String(128), index=True)

    target_type: Mapped[str] = mapped_column(
        String(32), default="turn"
    )  # 'turn', 'proposal', 'tool_call', 'message'
    target_id: Mapped[str] = mapped_column(String(64))

    rating: Mapped[str] = mapped_column(String(16))  # validated in DTO
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    trace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, default=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "feedbackId": self.feedback_id,
            "sessionId": self.session_id,
            "userId": self.user_id,
            "targetType": self.target_type,
            "targetId": self.target_id,
            "rating": self.rating,
            "comment": self.comment,
            "traceId": self.trace_id,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class AIProvenanceRecord(Base):
    """Provenance record capturing the full generation context of an AI proposal."""

    __tablename__ = "ai_provenance"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    provenance_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_sessions.session_id", ondelete="CASCADE"),
        index=True,
    )
    turn_id: Mapped[str] = mapped_column(String(64), index=True)
    tool_call_id: Mapped[str] = mapped_column(String(64))
    proposal_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    model_id: Mapped[str] = mapped_column(String(128))
    provider: Mapped[str] = mapped_column(String(32), default="anthropic")
    prompt_version: Mapped[str] = mapped_column(String(32), default="1.0")

    course_id: Mapped[str] = mapped_column(String(64), index=True)
    course_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)

    proposal_payload_hash: Mapped[str] = mapped_column(String(64))
    schema_signature: Mapped[str] = mapped_column(String(64))

    input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    drift_status: Mapped[str] = mapped_column(String(16), default="clean")

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, default=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "provenanceId": self.provenance_id,
            "sessionId": self.session_id,
            "turnId": self.turn_id,
            "toolCallId": self.tool_call_id,
            "proposalId": self.proposal_id,
            "modelId": self.model_id,
            "provider": self.provider,
            "promptVersion": self.prompt_version,
            "courseId": self.course_id,
            "courseSnapshot": self.course_snapshot,
            "proposalPayloadHash": self.proposal_payload_hash,
            "schemaSignature": self.schema_signature,
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "latencyMs": self.latency_ms,
            "driftStatus": self.drift_status,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class AIFeedbackTagRecord(Base):
    """Optional tag on a feedback record for ML pipeline classification."""

    __tablename__ = "ai_feedback_tags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    feedback_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_feedback.feedback_id", ondelete="CASCADE"),
        index=True,
    )
    tag: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, default=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "feedbackId": self.feedback_id,
            "tag": self.tag,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
```

### 2.3 Pydantic DTOs

**New file: `app/routers/ai_feedback_dtos.py`**

```python
"""Pydantic DTOs for the RLHF Feedback and Provenance API."""
from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel, Field


# ── Feedback ──────────────────────────────────────────────────────────────

class FeedbackCreateRequest(BaseModel):
    session_id: str = Field(..., description="Active AI session ID")
    target_type: str = Field(
        ..., pattern=r"^(turn|proposal|tool_call|message)$",
        description="Type of the entity being rated",
    )
    target_id: str = Field(..., min_length=1, description="ID of the entity being rated")
    rating: str = Field(
        ..., pattern=r"^(thumbs_up|thumbs_down|star_1|star_2|star_3|star_4|star_5)$",
        description="Rating value",
    )
    comment: Optional[str] = Field(None, max_length=2000, description="Optional free-text comment")
    trace_id: Optional[str] = Field(None, description="Correlation trace ID for observability")


class FeedbackResponse(BaseModel):
    feedback_id: str
    session_id: str
    user_id: str
    target_type: str
    target_id: str
    rating: str
    comment: Optional[str] = None
    trace_id: Optional[str] = None
    created_at: str


class FeedbackListResponse(BaseModel):
    feedback: List[FeedbackResponse]
    total: int
    has_more: bool


class FeedbackAggregationResponse(BaseModel):
    """Aggregated feedback stats for a target."""
    target_type: str
    target_id: str
    total_feedback: int
    thumbs_up: int
    thumbs_down: int
    star_average: Optional[float] = None  # Average of star ratings (1-5) if any
    star_distribution: dict = Field(default_factory=lambda: {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0})
    recent_comments: List[dict] = Field(default_factory=list)


# ── Provenance ────────────────────────────────────────────────────────────

class ProvenanceResponse(BaseModel):
    provenance_id: str
    session_id: str
    turn_id: str
    tool_call_id: str
    proposal_id: Optional[str] = None
    model_id: str
    provider: str
    prompt_version: str
    course_id: str
    course_snapshot: dict
    proposal_payload_hash: str
    schema_signature: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_ms: Optional[int] = None
    drift_status: str
    created_at: str
    linked_feedback: Optional[List[FeedbackResponse]] = None


class ProvenanceListResponse(BaseModel):
    provenance: List[ProvenanceResponse]
    total: int
    has_more: bool


# ── Export ────────────────────────────────────────────────────────────────

class FeedbackExportRequest(BaseModel):
    start_date: Optional[str] = Field(None, description="ISO 8601 start date")
    end_date: Optional[str] = Field(None, description="ISO 8601 end date")
    course_id: Optional[str] = Field(None, description="Filter by course")
    model_id: Optional[str] = Field(None, description="Filter by model")
    rating: Optional[str] = Field(None, description="Filter by rating")
    format: str = Field("jsonl", pattern=r"^(jsonl|json|csv)$")
    redact_pii: bool = Field(default=False, description="Redact PII from export")
    include_provenance: bool = Field(default=True)


class FeedbackExportStatusResponse(BaseModel):
    job_id: Optional[str] = None  # Non-null if async
    status: str  # 'ready', 'processing', 'completed', 'failed'
    download_url: Optional[str] = None
    record_count: int
    expires_at: Optional[str] = None
```

### 2.4 API Contracts

#### POST /api/v1/ai/feedback

Submit feedback on an AI target (turn, proposal, tool call, or message).

**Request:**
```json
{
  "session_id": "sess_abc123",
  "target_type": "turn",
  "target_id": "turn_xyz789",
  "rating": "thumbs_down",
  "comment": "The generated assessment questions did not match the course difficulty level.",
  "trace_id": "trace_001"
}
```

**Response 201 (Created):**
```json
{
  "feedback_id": "fb_001",
  "session_id": "sess_abc123",
  "user_id": "user_42",
  "target_type": "turn",
  "target_id": "turn_xyz789",
  "rating": "thumbs_down",
  "comment": "The generated assessment questions did not match the course difficulty level.",
  "trace_id": "trace_001",
  "created_at": "2026-06-14T10:30:00Z"
}
```

**Response 200 (Duplicate -- same user + target already exists, idempotent):**
```json
{
  "feedback_id": "fb_001",
  "...": "...",
  "created_at": "2026-06-14T10:25:00Z"
}
```

**Error Responses:**

`404 SESSION_NOT_FOUND`:
```json
{
  "code": "SESSION_NOT_FOUND",
  "message": "Session 'sess_abc123' does not exist or has expired."
}
```

`404 TARGET_NOT_FOUND`:
```json
{
  "code": "TARGET_NOT_FOUND",
  "message": "No turn with ID 'turn_xyz789' exists in session 'sess_abc123'."
}
```

`422 VALIDATION_ERROR` (rating not in enum):
```json
{
  "code": "VALIDATION_ERROR",
  "field": "rating",
  "message": "Value 'thumbs_sideways' is not a valid rating. Must be one of: thumbs_up, thumbs_down, star_1, ... star_5."
}
```

#### GET /api/v1/ai/feedback?session_id={sessionId}&target_type={type}&target_id={id}

Query feedback records with filters.

**Response 200:**
```json
{
  "feedback": [
    {
      "feedback_id": "fb_001",
      "session_id": "sess_abc123",
      "user_id": "user_42",
      "target_type": "turn",
      "target_id": "turn_xyz789",
      "rating": "thumbs_down",
      "comment": "The generated assessment questions did not match the course difficulty level.",
      "trace_id": "trace_001",
      "created_at": "2026-06-14T10:30:00Z"
    }
  ],
  "total": 1,
  "has_more": false
}
```

#### GET /api/v1/ai/feedback/stats?target_type=turn&target_id={id}

Aggregated feedback statistics for a given target.

**Response 200:**
```json
{
  "target_type": "turn",
  "target_id": "turn_xyz789",
  "total_feedback": 5,
  "thumbs_up": 3,
  "thumbs_down": 2,
  "star_average": 3.8,
  "star_distribution": {"1": 0, "2": 0, "3": 1, "4": 2, "5": 1},
  "recent_comments": [
    {"feedback_id": "fb_005", "comment": "Great job on the content!", "created_at": "..."},
    {"feedback_id": "fb_002", "comment": "Needs more examples", "created_at": "..."}
  ]
}
```

#### GET /api/v1/ai/provenance?session_id={sessionId}&course_id={courseId}&turn_id={turnId}

Query provenance records.

**Response 200:**
```json
{
  "provenance": [
    {
      "provenance_id": "prov_001",
      "session_id": "sess_abc123",
      "turn_id": "turn_xyz789",
      "tool_call_id": "call_003",
      "proposal_id": "prop_045",
      "model_id": "claude-sonnet-4-20250514",
      "provider": "anthropic",
      "prompt_version": "1.0",
      "course_id": "course_python_101",
      "course_snapshot": {
        "pageCount": 5,
        "componentCount": 23,
        "schemaSignatures": {"page-1": "abc123", "page-2": "def456"},
        "courseStatus": "draft",
        "hasPendingProposals": false
      },
      "proposal_payload_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "schema_signature": "v1.0",
      "input_tokens": 4523,
      "output_tokens": 890,
      "latency_ms": 8430,
      "drift_status": "clean",
      "created_at": "2026-06-14T10:28:00Z"
    }
  ],
  "total": 1,
  "has_more": false
}
```

#### GET /api/v1/ai/provenance/export

Export provenance + feedback as JSONL/CSV. If record count exceeds `AI_EXPORT_ASYNC_THRESHOLD` (default 1000), returns a job ID and the export is generated asynchronously.

**Response 200 (Synchronous, < threshold):**
```
Content-Type: application/x-ndjson
Content-Disposition: attachment; filename="ai-feedback-provenance-2026-06-14.jsonl"

{"provenance_id":"prov_001","model_id":"claude-sonnet-4-20250514",...,"feedback":[...]}
{"provenance_id":"prov_002","model_id":"claude-sonnet-4-20250514",...,"feedback":[...]}
```

**Response 202 (Async, >= threshold):**
```json
{
  "job_id": "export_job_007",
  "status": "processing",
  "record_count": 15230,
  "download_url": null,
  "expires_at": null
}
```

Frontend polls `GET /api/v1/ai/provenance/export/jobs/{job_id}` until status is `"completed"`, then downloads from `download_url`.

### 2.5 Service Signatures

**New file: `app/services/ai/feedback_service.py`**

```python
"""Feedback service for RLHF data ingestion, aggregation, and export.

Handles:
  - Creating feedback records with idempotency (one feedback per user per target).
  - Validating target existence (turn exists in session, proposal exists, etc.).
  - Computing feedback aggregations (stats per target).
  - Exporting feedback + provenance as JSONL/CSV with optional PII redaction.
"""

from __future__ import annotations
import hashlib
import json
import logging
import os
from datetime import datetime
from typing import AsyncGenerator, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class FeedbackError(Exception):
    """Base error for feedback operations."""


class TargetNotFoundError(FeedbackError):
    """The target entity (turn, proposal, etc.) does not exist."""


class FeedbackService:
    """RLHF feedback collection, aggregation, and export."""

    MAX_COMMENT_LENGTH = int(os.getenv("AI_FEEDBACK_MAX_COMMENT_LENGTH", "2000"))
    EXPORT_ASYNC_THRESHOLD = int(os.getenv("AI_EXPORT_ASYNC_THRESHOLD", "1000"))

    def __init__(self, db_session: AsyncSession):
        self.session = db_session

    async def submit_feedback(
        self,
        session_id: str,
        user_id: str,
        target_type: str,
        target_id: str,
        rating: str,
        comment: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> dict:
        """Submit feedback with idempotency.

        Validates the target exists, enforces one-feedback-per-user-per-target,
        and persists the record.

        Returns:
            The feedback record dict (existing if duplicate).

        Raises:
            TargetNotFoundError: If the target entity does not exist.
            FeedbackError: On any other validation failure.
        """
        raise NotImplementedError

    async def _validate_target_exists(
        self,
        session_id: str,
        target_type: str,
        target_id: str,
    ) -> None:
        """Verify the target entity exists and belongs to the session.

        For 'turn' targets: check ai_session_messages for a matching turn_id.
        For 'proposal' targets: check ai_proposals table.
        For 'tool_call' targets: check ai_tool_call_logs.
        For 'message' targets: check ai_session_messages.
        """
        raise NotImplementedError

    async def get_feedback(
        self,
        session_id: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        rating: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Query feedback records with optional filters.

        Returns:
            (list of feedback dicts, total count).
        """
        raise NotImplementedError

    async def get_aggregation(
        self,
        target_type: str,
        target_id: str,
    ) -> dict:
        """Compute aggregate feedback stats for a target.

        Returns dict with total_feedback, thumbs_up/down counts,
        star_average, star_distribution, recent_comments.
        """
        raise NotImplementedError

    async def get_provenance(
        self,
        session_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        course_id: Optional[str] = None,
        model_id: Optional[str] = None,
        proposal_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Query provenance records with optional filters.

        Returns:
            (list of provenance dicts with linked feedback, total count).
        """
        raise NotImplementedError

    async def link_feedback_to_provenance(
        self,
        provenance_records: list[dict],
    ) -> list[dict]:
        """Attach linked feedback to each provenance record.

        For each provenance record, finds feedback records whose
        target_type='proposal' matches the provenance's proposal_id.
        """
        raise NotImplementedError

    async def export_feedback(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        course_id: Optional[str] = None,
        model_id: Optional[str] = None,
        rating: Optional[str] = None,
        format: str = "jsonl",
        redact_pii: bool = False,
        include_provenance: bool = True,
    ) -> AsyncGenerator[str, None]:
        """Stream feedback + provenance export.

        Yields:
            Lines of JSONL or CSV rows.
        """
        raise NotImplementedError

    def _redact_pii(self, record: dict) -> dict:
        """Redact PII fields from a feedback/provenance record.

        Replaces emails, phone numbers, API keys with placeholders.
        Only applied when redact_pii=True.
        """
        raise NotImplementedError

    def _compute_payload_hash(self, payload: dict) -> str:
        """Compute SHA-256 hex digest of canonical JSON payload."""
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
```

**New file: `app/services/ai/provenance_collector.py`**

```python
"""Captures provenance metadata at proposal-creation time.

The ProvenanceCollector is called by the ToolExecutor after a successful
propose_* tool execution. It captures the generation context (model ID,
prompt version, course snapshot, etc.) and persists it to ai_provenance.

Failure to capture provenance is non-blocking: the proposal is not rolled
back, but a warning is logged.
"""

from __future__ import annotations
import hashlib
import json
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ProvenanceCollector:
    """Captures and persists AI generation provenance."""

    def __init__(self, db_session: AsyncSession):
        self.session = db_session

    async def capture(
        self,
        *,
        session_id: str,
        turn_id: str,
        tool_call_id: str,
        proposal_id: str,
        model_id: str,
        provider: str,
        prompt_version: str,
        course_id: str,
        course_snapshot: dict,
        proposal_payload: dict,
        schema_signature: str,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        latency_ms: Optional[int] = None,
    ) -> str:
        """Capture a provenance record.

        Args:
            All provenance fields as documented in the DDL.

        Returns:
            The provenance_id of the created record.

        This method is designed to be called after a proposal is created.
        It should never raise; all exceptions are caught, logged, and
        the proposal creation continues unaffected.
        """
        raise NotImplementedError

    async def _build_course_snapshot(self, course_id: str) -> dict:
        """Build a snapshot dict of the current course state.

        Returns dict with:
          - pageCount, componentCount
          - schemaSignatures: {page_id: sha256_of_page_data}
          - courseStatus
          - hasPendingProposals
        """
        raise NotImplementedError

    async def check_drift(self, proposal_id: str) -> str:
        """Compare the stored proposal payload hash with the current proposal data.

        Returns 'clean' if unchanged, 'drift_detected' if the proposal payload
        has been modified since creation (e.g., by an intervening user edit).
        """
        raise NotImplementedError
```

### 2.6 Repositories

**New file: `app/repositories/ai_feedback_repo.py`**

```python
"""Repository for RLHF feedback and provenance persistence.

Covers: AIFeedbackRecord, AIProvenanceRecord, AIFeedbackTagRecord.
"""

from __future__ import annotations
from typing import Optional, Sequence
from datetime import datetime

from sqlalchemy import select, delete, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_feedback import (
    AIFeedbackRecord,
    AIProvenanceRecord,
    AIFeedbackTagRecord,
)


class FeedbackRepository:
    """DB access for ai_feedback."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self, record: AIFeedbackRecord
    ) -> AIFeedbackRecord:
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def get_by_user_and_target(
        self,
        user_id: str,
        target_type: str,
        target_id: str,
    ) -> Optional[AIFeedbackRecord]:
        q = select(AIFeedbackRecord).where(
            AIFeedbackRecord.user_id == user_id,
            AIFeedbackRecord.target_type == target_type,
            AIFeedbackRecord.target_id == target_id,
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def list(
        self,
        *,
        session_id: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        rating: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[AIFeedbackRecord], int]:
        conditions = []
        if session_id:
            conditions.append(AIFeedbackRecord.session_id == session_id)
        if target_type:
            conditions.append(AIFeedbackRecord.target_type == target_type)
        if target_id:
            conditions.append(AIFeedbackRecord.target_id == target_id)
        if rating:
            conditions.append(AIFeedbackRecord.rating == rating)

        count_q = select(func.count()).select_from(AIFeedbackRecord)
        list_q = select(AIFeedbackRecord)

        if conditions:
            count_q = count_q.where(and_(*conditions))
            list_q = list_q.where(and_(*conditions))

        total = (await self.session.execute(count_q)).scalar() or 0
        rows = (
            await self.session.execute(
                list_q.order_by(AIFeedbackRecord.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
        return rows, total

    async def aggregate_by_target(
        self,
        target_type: str,
        target_id: str,
    ) -> dict:
        """Compute per-rating counts and star average."""
        q = (
            select(
                AIFeedbackRecord.rating,
                func.count().label("count"),
            )
            .where(
                AIFeedbackRecord.target_type == target_type,
                AIFeedbackRecord.target_id == target_id,
            )
            .group_by(AIFeedbackRecord.rating)
        )
        rows = (await self.session.execute(q)).all()

        result = {
            "total_feedback": sum(r[1] for r in rows),
            "thumbs_up": 0,
            "thumbs_down": 0,
            "star_count": 0,
            "star_sum": 0,
            "star_distribution": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0},
        }
        for rating, count in rows:
            if rating == "thumbs_up":
                result["thumbs_up"] = count
            elif rating == "thumbs_down":
                result["thumbs_down"] = count
            elif rating.startswith("star_"):
                star_val = int(rating.split("_")[1])
                result["star_distribution"][str(star_val)] = count
                result["star_count"] += count
                result["star_sum"] += star_val * count

        result["star_average"] = (
            round(result["star_sum"] / result["star_count"], 2)
            if result["star_count"] > 0
            else None
        )
        return result

    async def get_recent_comments(
        self,
        target_type: str,
        target_id: str,
        limit: int = 5,
    ) -> Sequence[AIFeedbackRecord]:
        q = (
            select(AIFeedbackRecord)
            .where(
                AIFeedbackRecord.target_type == target_type,
                AIFeedbackRecord.target_id == target_id,
                AIFeedbackRecord.comment.isnot(None),
                AIFeedbackRecord.comment != "",
            )
            .order_by(AIFeedbackRecord.created_at.desc())
            .limit(limit)
        )
        return (await self.session.execute(q)).scalars().all()


class ProvenanceRepository:
    """DB access for ai_provenance."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self, record: AIProvenanceRecord
    ) -> AIProvenanceRecord:
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def list(
        self,
        *,
        session_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        course_id: Optional[str] = None,
        model_id: Optional[str] = None,
        proposal_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[AIProvenanceRecord], int]:
        conditions = []
        if session_id:
            conditions.append(AIProvenanceRecord.session_id == session_id)
        if turn_id:
            conditions.append(AIProvenanceRecord.turn_id == turn_id)
        if course_id:
            conditions.append(AIProvenanceRecord.course_id == course_id)
        if model_id:
            conditions.append(AIProvenanceRecord.model_id == model_id)
        if proposal_id:
            conditions.append(AIProvenanceRecord.proposal_id == proposal_id)

        count_q = select(func.count()).select_from(AIProvenanceRecord)
        list_q = select(AIProvenanceRecord)

        if conditions:
            count_q = count_q.where(and_(*conditions))
            list_q = list_q.where(and_(*conditions))

        total = (await self.session.execute(count_q)).scalar() or 0
        rows = (
            await self.session.execute(
                list_q.order_by(AIProvenanceRecord.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
        return rows, total

    async def get_by_proposal(
        self, proposal_id: str
    ) -> Optional[AIProvenanceRecord]:
        q = select(AIProvenanceRecord).where(
            AIProvenanceRecord.proposal_id == proposal_id
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def count_by_course_and_model(
        self, course_id: str, model_id: Optional[str] = None
    ) -> int:
        conditions = [AIProvenanceRecord.course_id == course_id]
        if model_id:
            conditions.append(AIProvenanceRecord.model_id == model_id)
        q = (
            select(func.count())
            .select_from(AIProvenanceRecord)
            .where(and_(*conditions))
        )
        return (await self.session.execute(q)).scalar() or 0
```

### 2.7 API Router

**New file: `app/routers/ai_feedback.py`**

```python
"""RLHF Feedback and Provenance API router.

Endpoints:
  POST   /api/v1/ai/feedback                          — Submit feedback
  GET    /api/v1/ai/feedback                          — Query feedback records
  GET    /api/v1/ai/feedback/stats                    — Aggregated feedback stats
  GET    /api/v1/ai/provenance                        — Query provenance records
  GET    /api/v1/ai/provenance/export                 — Export feedback+provenance
  GET    /api/v1/ai/provenance/export/jobs/{job_id}   — Poll export job status
"""

from __future__ import annotations
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.utils.error_envelope import api_http_exception
from app.utils.feature_flags import require_feature_async

from app.routers.ai_feedback_dtos import (
    FeedbackCreateRequest,
    FeedbackResponse,
    FeedbackListResponse,
    FeedbackAggregationResponse,
    ProvenanceResponse,
    ProvenanceListResponse,
    FeedbackExportRequest,
    FeedbackExportStatusResponse,
)
from app.services.ai.feedback_service import FeedbackService, TargetNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ai", tags=["AI Feedback"])


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit feedback on an AI action",
    responses={
        200: {"description": "Existing feedback returned (idempotent)"},
        404: {"description": "Session or target not found"},
        422: {"description": "Validation error"},
    },
)
async def submit_feedback(
    body: FeedbackCreateRequest,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(require_feature_async("ai_suggestions")),
):
    """Submit thumbs-up/down, star rating, or comment on an AI action.

    One feedback per user per target. Duplicate submissions return the
    existing record (idempotent, HTTP 200).
    """
    try:
        service = FeedbackService(session)
        user_id = "authenticated_user"  # or extract from auth
        result = await service.submit_feedback(
            session_id=body.session_id,
            user_id=user_id,
            target_type=body.target_type,
            target_id=body.target_id,
            rating=body.rating,
            comment=body.comment,
            trace_id=body.trace_id,
        )
        is_new = result.get("_new", True)
        status_code = status.HTTP_201_CREATED if is_new else status.HTTP_200_OK
        return JSONResponse(content=result, status_code=status_code)

    except TargetNotFoundError as exc:
        raise api_http_exception(404, "TARGET_NOT_FOUND", str(exc))
    except Exception as exc:
        logger.exception("Failed to submit feedback")
        raise api_http_exception(
            500, "INTERNAL_ERROR", "An unexpected error occurred."
        )


@router.get(
    "/feedback",
    response_model=FeedbackListResponse,
    summary="Query feedback records with filters",
)
async def list_feedback(
    session_id: Optional[str] = Query(None),
    target_type: Optional[str] = Query(None),
    target_id: Optional[str] = Query(None),
    rating: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db_session: AsyncSession = Depends(get_session),
    _: bool = Depends(require_feature_async("ai_suggestions")),
):
    service = FeedbackService(db_session)
    records, total = await service.get_feedback(
        session_id=session_id,
        target_type=target_type,
        target_id=target_id,
        rating=rating,
        limit=limit,
        offset=offset,
    )
    return {
        "feedback": records,
        "total": total,
        "has_more": (offset + limit) < total,
    }


@router.get(
    "/feedback/stats",
    response_model=FeedbackAggregationResponse,
    summary="Get aggregated feedback stats for a target",
)
async def get_feedback_stats(
    target_type: str = Query(..., pattern=r"^(turn|proposal|tool_call|message)$"),
    target_id: str = Query(..., min_length=1),
    db_session: AsyncSession = Depends(get_session),
    _: bool = Depends(require_feature_async("ai_suggestions")),
):
    service = FeedbackService(db_session)
    return await service.get_aggregation(
        target_type=target_type,
        target_id=target_id,
    )


@router.get(
    "/provenance",
    response_model=ProvenanceListResponse,
    summary="Query provenance records with filters",
)
async def list_provenance(
    session_id: Optional[str] = Query(None),
    turn_id: Optional[str] = Query(None),
    course_id: Optional[str] = Query(None),
    model_id: Optional[str] = Query(None),
    proposal_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db_session: AsyncSession = Depends(get_session),
    _: bool = Depends(require_feature_async("ai_suggestions")),
):
    service = FeedbackService(db_session)
    records, total = await service.get_provenance(
        session_id=session_id,
        turn_id=turn_id,
        course_id=course_id,
        model_id=model_id,
        proposal_id=proposal_id,
        limit=limit,
        offset=offset,
    )
    records = await service.link_feedback_to_provenance(records)
    return {
        "provenance": records,
        "total": total,
        "has_more": (offset + limit) < total,
    }


@router.get(
    "/provenance/export",
    summary="Export feedback + provenance as JSONL or CSV",
    responses={
        200: {"description": "Streaming export (synchronous)"},
        202: {"description": "Async export job created"},
    },
)
async def export_provenance(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    course_id: Optional[str] = Query(None),
    model_id: Optional[str] = Query(None),
    rating: Optional[str] = Query(None),
    format: str = Query("jsonl", pattern=r"^(jsonl|json|csv)$"),
    redact_pii: bool = Query(False),
    include_provenance: bool = Query(True),
    db_session: AsyncSession = Depends(get_session),
    _: bool = Depends(require_feature_async("ai_suggestions")),
):
    service = FeedbackService(db_session)

    # If async threshold is exceeded, return 202 with a job reference.
    # (Simplified: synchronous for now; async path is a future enhancement.)
    content_type = (
        "application/x-ndjson" if format == "jsonl"
        else "application/json" if format == "json"
        else "text/csv"
    )
    filename = (
        f"ai-export-{datetime.utcnow().strftime('%Y%m%d')}.{format.replace('jsonl', 'jsonl')}"
    )

    async def stream():
        async for line in service.export_feedback(
            start_date=start_date,
            end_date=end_date,
            course_id=course_id,
            model_id=model_id,
            rating=rating,
            format=format,
            redact_pii=redact_pii,
            include_provenance=include_provenance,
        ):
            yield line

    return StreamingResponse(
        stream(),
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
```

### 2.8 Integration into ToolExecutor / ChatOrchestrator

Inside `ToolExecutor._execute_propose_create_page()` (and similar `_propose_*` methods), after the `ai_proposals` record is created, call:

```python
from app.services.ai.provenance_collector import ProvenanceCollector

provenance = ProvenanceCollector(self.session)
try:
    await provenance.capture(
        session_id=session_context["session_id"],
        turn_id=session_context["turn_id"],
        tool_call_id=tool_call_id,
        proposal_id=proposal.proposal_id,
        model_id=session_context.get("model_id", "unknown"),
        provider=session_context.get("provider", "anthropic"),
        prompt_version=session_context.get("prompt_version", "1.0"),
        course_id=session_context["course_id"],
        course_snapshot=await provenance._build_course_snapshot(
            session_context["course_id"]
        ),
        proposal_payload=input_args,
        schema_signature=session_context.get("schema_signature", "v1.0"),
        input_tokens=session_context.get("input_tokens"),
        output_tokens=session_context.get("output_tokens"),
        latency_ms=session_context.get("latency_ms"),
    )
except Exception:
    logger.warning("Failed to capture provenance (non-blocking)", exc_info=True)
```

### 2.9 Main Application Registration

**In `app/main.py`, add to imports:**
```python
from app.routers import ai_feedback  # new import
```

**In the router registration section:**
```python
api_router.include_router(ai_feedback.router)
```

**In the `lifespan` startup section, add to the ORM model imports:**
```python
import app.models.ai_feedback  # noqa: F401 -- register ORM model
```

**In `app/models/__init__.py`, add:**
```python
from app.models.ai_feedback import (
    AIFeedbackRecord,
    AIProvenanceRecord,
    AIFeedbackTagRecord,
)
```

### 2.10 Environment Variables

Add to `.env` and `.env.example`:

```ini
# ============================================
# RLHF Feedback and Provenance Tracking
# ============================================

# Feedback limits
AI_FEEDBACK_MAX_COMMENT_LENGTH=2000

# Feedback-to-retry: when enabled, a thumbs_down with comment
# can trigger a background regeneration via the chat orchestrator
AI_FEEDBACK_RETRY_ENABLED=false

# Provenance capture
# When disabled, provenance records are not created (performance trade-off)
AI_PROVENANCE_ENABLED=true

# Export
AI_EXPORT_ASYNC_THRESHOLD=1000
AI_EXPORT_REDACT_PII=false
AI_EXPORT_PII_PATTERNS=email,phone,ssn,credit_card,api_key
```

---

## 3. Non-Functional Requirements

### 3.1 Performance

| Requirement | Target | Measurement |
|---|---|---|
| Feedback submission (p95) | < 100 ms | Time to validate + persist |
| Feedback query with filters (p95) | < 200 ms | Time to query and return |
| Provenance capture (p99) | < 50 ms | Non-blocking; must not increase proposal latency by more than 50ms |
| Provenance query with filters (p95) | < 300 ms | Time to query and link feedback |
| Export generation (sync, <1000 rows) | < 3 s | Time to generate full export |
| Concurrent feedback submissions | Unlimited | No locking required (append-only) |

### 3.2 Data Integrity

| Requirement | Implementation |
|---|---|
| Feedback is immutable | Once created, feedback records cannot be updated or deleted. Corrections require a new record. |
| One-feedback-per-user-per-target | Enforced by unique DB index on (user_id, target_type, target_id). Duplicates return existing record. |
| Provenance is non-blocking | Failure to capture provenance never rolls back the proposal. Log and continue. |
| Export consistency | Export uses a snapshot read (REPEATABLE READ isolation or at least a single-query approach) to ensure consistency across feedback + provenance tables. |

### 3.3 Security

| Requirement | Implementation |
|---|---|
| Feedback scoped to user session | Every feedback submission validates the session belongs to the authenticated user. |
| No feedback on non-user-owned targets | Target validation checks that the target belongs to the session's course, and the user owns the session. |
| PII redaction in exports | `AI_EXPORT_REDACT_PII=true` applies regex-based redaction (email, phone, SSN, credit card, API key) before export. |
| Audit trail | All feedback submissions include a `trace_id` that is logged in the server audit trail for correlation. |

### 3.4 Availability

| Requirement | Implementation |
|---|---|
| Provenance capture failure | Non-blocking: proposal creation proceeds even if provenance write fails. Warning logged. |
| Feedback endpoint degradation | If the feedback DB is unavailable, the main chat endpoint is unaffected. Feedback returns 503 independently. |
| Export backpressure | Async export jobs for large datasets prevent memory exhaustion. Export is served from a pre-generated file. |

---

## 4. Current State

### 4.1 What Exists Today

1. **AI Chat Interaction Loop (US-AI-023)**: The `ChatOrchestrator`, `ToolExecutor`, and `LLMClient` services process chat turns, execute tool calls, and persist messages, tool logs, and telemetry. Tool calls currently do NOT capture provenance beyond what is in `ai_tool_call_logs`.

2. **Proposal System (US-AI-007 / US-AI-013)**: The `propose_create_page`, `propose_update_page`, `propose_delete_page` tools create `ai_proposals` records with status `PENDING_REVIEW`. The proposal system has no user feedback mechanism and no provenance linking.

3. **Analytics & Scoring (existing)**: `/api/v1/courses/{courseId}/analytics/summary` and `/api/v1/courses/{courseId}/analytics/manager-view` provide interaction event stats but no AI-specific feedback.

4. **Feature Flags**: `app/utils/feature_flags.py` provides `ai_suggestions` flag that gates AI endpoints. The existing flag is used for guard.

5. **Error Envelope Pattern**: `app/utils/error_envelope.py` defines the normalized error response format used across the project.

6. **Session Management (US-AI-006)**: `ai_sessions` table with session lifecycle, expiry, and scope validation.

### 4.2 What Is Missing

1. `ai_feedback`, `ai_provenance`, `ai_feedback_tags` tables with ORM models and Alembic migration.
2. `FeedbackService` -- feedback submission with target validation and idempotency.
3. `ProvenanceCollector` -- captures generation context at proposal time.
4. `FeedbackRepository` and `ProvenanceRepository` -- DB access for feedback and provenance.
5. Pydantic DTOs for feedback/provenance request/response models.
6. `POST /api/v1/ai/feedback` endpoint for feedback submission.
7. `GET /api/v1/ai/feedback` and `GET /api/v1/ai/feedback/stats` endpoints.
8. `GET /api/v1/ai/provenance` and `GET /api/v1/ai/provenance/export` endpoints.
9. Integration into `ToolExecutor` -- calling `ProvenanceCollector.capture()` after each `propose_*` tool call.
10. Feedback aggregation logic (star average, distribution, comment summaries).
11. Export service streaming feedback + provenance as JSONL/CSV.
12. PII redaction for exports.
13. Registration in `app/main.py` (router + ORM model import).
14. Alembic migration for new tables.
15. Environment variables for feedback and provenance configuration.
16. Unit, integration, and E2E tests.

### 4.3 Dependencies on Earlier Stories

| Story | Dependency |
|---|---|
| US-AI-023 | Chat turn, tool call, and proposal IDs that provenance records reference |
| US-AI-025 | PII redaction patterns for export (reuse `PIIScanner` from guardrails) |
| US-AI-010 | Proposal lifecycle (proposal_id exists at propose time for provenance linking) |
| US-AI-006 | `ai_sessions` table that feedback records FK to |
| US-AI-005 | Tool registry that provenance metadata is attached through |
| US-AI-004 | Persistence foundations (Base, engine, session config) |

---

## 5. Expansion Points

### 5.1 Feedback-Triggered Retry (US-AI-038)

When `AI_FEEDBACK_RETRY_ENABLED=true`, a thumbs-down with a comment should automatically trigger a background retry: the chat orchestrator creates a new turn with the user's comment as a follow-up message, and the LLM regenerates the content. The frontend polls for the new proposal.

### 5.2 Reward Model Data Pipeline (US-AI-039)

The feedback export format can be consumed by a separate ML pipeline that builds preference datasets for RLHF fine-tuning. Future versions should add:
- Preference pair construction: for each context, pair the accepted vs. rejected proposals.
- Sampling strategy: down-sample `thumbs_up` records, up-sample `thumbs_down` records for balanced training data.
- Embedding index: store embedding vectors of proposals + feedback for similarity search across the feedback corpus.

### 5.3 Active Learning Sampling (US-AI-040)

When provenance data shows high uncertainty (low star ratings, high drift, many tool rounds), the system can proactively ask reviewers for feedback on those specific cases. This targets feedback collection on the most informative examples.

### 5.4 Cross-Session Feedback Aggregation

Currently feedback is scoped to individual targets. Future versions should support federated queries: "show me all feedback across all sessions for model X in the last week" with rollups by model, prompt version, and course type.

### 5.5 Feedback-Driven Content Toggle

When a proposal receives multiple thumbs-down with consistent comments ("too verbose", "wrong tone"), the system could auto-adjust the system prompt for that session to nudge the LLM toward the preferred style. This requires integrating feedback into the `ContextBuilder`'s system prompt construction.

---

## 6. Validation and Test Scenarios

### 6.1 Unit Tests (Service Layer)

**File: `tests/test_ai_feedback_service.py`**

```python
class TestFeedbackService:
    async def test_submit_feedback_creates_record(self, db_session, sample_ai_session_with_turn):
        """Happy path: submitting feedback creates a record and returns it."""
        pass

    async def test_submit_feedback_duplicate_is_idempotent(self, db_session, sample_ai_session_with_turn):
        """Same user + target returns existing record instead of creating a duplicate."""
        pass

    async def test_submit_feedback_different_user_allows_separate_feedback(self, db_session, sample_ai_session_with_turn):
        """Different users can each submit feedback on the same target."""
        pass

    async def test_submit_feedback_nonexistent_session_raises_error(self, db_session):
        """Feedback for a non-existent session returns TARGET_NOT_FOUND."""
        pass

    async def test_submit_feedback_nonexistent_turn_raises_error(self, db_session, sample_ai_session):
        """Feedback for a non-existent turn returns TARGET_NOT_FOUND."""
        pass

    async def test_submit_feedback_nonexistent_proposal_raises_error(self, db_session, sample_ai_session):
        """Feedback for a non-existent proposal returns TARGET_NOT_FOUND."""
        pass

    async def test_submit_feedback_comment_exceeds_max_length_raises_error(self, db_session, sample_ai_session_with_turn):
        """A comment exceeding 2000 characters returns a validation error."""
        pass

    async def test_get_feedback_returns_filtered_results(self, db_session, sample_feedback_records):
        """Query with filters returns matching feedback records."""
        pass

    async def test_get_feedback_empty_result(self, db_session):
        """Query with no matches returns empty list with total=0."""
        pass

    async def test_get_aggregation_returns_correct_stats(self, db_session, sample_feedback_records):
        """Aggregation returns correct thumbs count, star average, and distribution."""
        pass

    async def test_get_aggregation_no_feedback_returns_zeros(self, db_session):
        """Aggregation for a target with no feedback returns zeros and None star_average."""
        pass

    async def test_get_provenance_with_linked_feedback(self, db_session, sample_provenance_with_feedback):
        """Provenance records include linked feedback when requested."""
        pass

    async def test_link_feedback_to_provenance_empty_when_no_feedback(self, db_session, sample_provenance_records):
        """Provenance records have empty linked_feedback list when no feedback exists."""
        pass

    async def test_export_provenance_jsonl_format(self, db_session, sample_provenance_with_feedback):
        """Export produces valid JSONL lines."""
        pass

    async def test_export_provenance_csv_format(self, db_session, sample_provenance_with_feedback):
        """Export produces valid CSV with header row."""
        pass

    async def test_export_redact_pii_removes_sensitive_data(self, db_session, sample_provenance_with_pii):
        """When redact_pii=True, emails and phone numbers are replaced with placeholders."""
        pass

    async def test_payload_hash_is_deterministic(self):
        """Computing payload hash of the same dict twice produces the same hash."""
        pass

    async def test_payload_hash_changes_when_data_changes(self):
        """Different payload dicts produce different hashes."""
        pass
```

**File: `tests/test_provenance_collector.py`**

```python
class TestProvenanceCollector:
    async def test_capture_creates_provenance_record(self, db_session, sample_ai_session):
        """Happy path: capture creates a record in ai_provenance."""
        pass

    async def test_capture_proposal_id_is_linked(self, db_session, sample_ai_session, sample_proposal):
        """Provenance record has the correct proposal_id."""
        pass

    async def test_capture_failure_is_non_blocking(self, db_session, sample_ai_session, monkeypatch):
        """When capture raises, the error is logged and does not propagate."""
        pass

    async def test_course_snapshot_contains_page_and_component_counts(self, db_session, sample_ai_session_with_pages):
        """Course snapshot includes accurate pageCount and componentCount."""
        pass

    async def test_check_drift_detects_changes(self, db_session, sample_provenance_with_modified_proposal):
        """check_drift returns 'drift_detected' when proposal payload hash differs."""
        pass

    async def test_check_drift_returns_clean_on_unmodified(self, db_session, sample_provenance_with_unmodified_proposal):
        """check_drift returns 'clean' when proposal payload is unchanged."""
        pass
```

### 6.2 Integration Tests (API Layer)

**File: `tests/test_ai_feedback_api.py`**

```python
class TestFeedbackAPI:
    async def test_post_feedback_returns_201(self, async_client, sample_ai_session_with_turn):
        """POST /api/v1/ai/feedback returns 201 with the created feedback."""
        pass

    async def test_post_feedback_duplicate_returns_200(self, async_client, sample_ai_session_with_turn):
        """Duplicate feedback submission returns 200 with existing record."""
        pass

    async def test_post_feedback_invalid_rating_returns_422(self, async_client, sample_ai_session_with_turn):
        """Invalid rating value returns 422."""
        pass

    async def test_post_feedback_nonexistent_session_returns_404(self, async_client):
        """Feedback for non-existent session returns 404."""
        pass

    async def test_get_feedback_returns_list(self, async_client, sample_feedback_records):
        """GET /api/v1/ai/feedback returns paginated feedback list."""
        pass

    async def test_get_feedback_filters_by_target(self, async_client, sample_feedback_records):
        """GET with target_type and target_id filters returns matching records."""
        pass

    async def test_get_feedback_stats_returns_aggregation(self, async_client, sample_feedback_records):
        """GET /api/v1/ai/feedback/stats returns aggregated stats."""
        pass

    async def test_get_feedback_stats_no_data_returns_zeros(self, async_client):
        """GET stats for target with no feedback returns zero counts."""
        pass

    async def test_get_provenance_returns_records(self, async_client, sample_provenance_with_feedback):
        """GET /api/v1/ai/provenance returns provenance list."""
        pass

    async def test_get_provenance_filters_by_model(self, async_client, sample_provenance_with_feedback):
        """GET provenance with model_id filter returns matching records."""
        pass

    async def test_get_provenance_export_returns_jsonl(self, async_client, sample_provenance_with_feedback):
        """GET /api/v1/ai/provenance/export returns application/x-ndjson with Content-Disposition."""
        pass

    async def test_get_provenance_export_empty(self, async_client):
        """Export with no matching records returns an empty file."""
        pass

    async def test_feature_flag_disabled_returns_404(self, async_client, monkeypatch):
        """When ai_suggestions feature flag is disabled, endpoints return 404."""
        pass
```

### 6.3 E2E Scenarios

**Scenario 1: Author rates a chat turn, feedback is saved, stats are queryable**

1. Precondition: AI session exists with completed turn `turn_abc123`.
2. Author calls `POST /api/v1/ai/feedback` with `{session_id, target_type: "turn", target_id: "turn_abc123", rating: "thumbs_up", comment: "Great content!"}`.
3. System returns 201 with feedback_id.
4. Author calls `GET /api/v1/ai/feedback/stats?target_type=turn&target_id=turn_abc123`.
5. Response shows `thumbs_up: 1`, `thumbs_down: 0`, `recent_comments` includes the comment.
6. Author calls the same POST again (duplicate).
7. System returns 200 (idempotent) with the same feedback_id. Stats unchanged.

**Scenario 2: Provenance is captured for a proposal, queried, and exported**

1. Precondition: AI session exists with course `course_python_101`.
2. Chat orchestrator processes a turn. LLM calls `propose_create_page`.
3. ToolExecutor creates the proposal, then calls ProvenanceCollector.capture().
4. Provenance record is created with model_id, prompt_version, course_snapshot, proposal_payload_hash.
5. Operator calls `GET /api/v1/ai/provenance?course_id=course_python_101`.
6. Response includes the provenance record with linked feedback (initially empty).
7. Operator calls `GET /api/v1/ai/provenance/export?format=jsonl&course_id=course_python_101`.
8. Response streams JSONL lines with provenance data.

**Scenario 3: Thumbs-down feedback on a proposal with retry enabled**

1. Precondition: `AI_FEEDBACK_RETRY_ENABLED=true`. Session `sess_xyz` has proposal `prop_045`.
2. Author submits `POST /api/v1/ai/feedback` with `{target_type: "proposal", target_id: "prop_045", rating: "thumbs_down", comment: "Too verbose"}`.
3. System persists feedback. A background task is queued.
4. Background task: creates a new chat turn in session `sess_xyz` with the comment as user message.
5. LLM regenerates relevant content. A new proposal is created.
6. Frontend polls and sees the new proposal. Old proposal is marked as `SUPERSEDED`.

**Scenario 4: Provenance drift detection flags a modified proposal**

1. Precondition: Proposal `prop_045` was created with payload hash `abc123`. Provenance record exists.
2. User manually edits the proposal data via a separate API call (outside the AI flow).
3. `ProvenanceCollector.check_drift(prop_045)` computes the current hash and finds it differs.
4. Provenance record's `drift_status` is updated to `drift_detected`.
5. When queried, the provenance record shows `driftStatus: "drift_detected"`.

---

## 7. Detailed Task Breakdown

### Task 1: Database Migration and ORM Models

**Story points:** 3  
**Files to create/modify:**
- `alembic/versions/20260614_0001_add_feedback_provenance.py` (new migration)
- `app/models/ai_feedback.py` (new file)
- `app/models/__init__.py` (modify)

**Acceptance criteria:**
- Migration creates `ai_feedback`, `ai_provenance`, `ai_feedback_tags` tables.
- Migration includes all indexes and unique constraint on `(user_id, target_type, target_id)`.
- `AIFeedbackRecord`, `AIProvenanceRecord`, `AIFeedbackTagRecord` ORM models match DDL exactly.
- All models export `to_dict()` methods.
- Models are registered in `app/models/__init__.py`.

### Task 2: Repositories

**Story points:** 3  
**Files to create/modify:**
- `app/repositories/ai_feedback_repo.py` (new file)

**Acceptance criteria:**
- `FeedbackRepository` implements: `create()`, `get_by_user_and_target()`, `list()`, `aggregate_by_target()`, `get_recent_comments()`.
- `ProvenanceRepository` implements: `create()`, `list()`, `get_by_proposal()`, `count_by_course_and_model()`.
- All list methods support optional filters with correct `and_()` chaining.
- All methods return ORM objects, not raw rows.
- Repository methods match existing codebase conventions (async, type-annotated).

### Task 3: DTOs

**Story points:** 1  
**Files to create/modify:**
- `app/routers/ai_feedback_dtos.py` (new file)

**Acceptance criteria:**
- `FeedbackCreateRequest` validates session_id, target_type (enum regex), target_id, rating (enum regex), comment (max_length).
- `FeedbackResponse`, `FeedbackListResponse`, `FeedbackAggregationResponse`, `ProvenanceResponse`, `ProvenanceListResponse`, `FeedbackExportRequest`, `FeedbackExportStatusResponse` defined.
- DTOs follow existing project conventions (Pydantic v1/v2 compat where needed).

### Task 4: FeedbackService

**Story points:** 5  
**Files to create/modify:**
- `app/services/ai/feedback_service.py` (new file)

**Acceptance criteria:**
- `submit_feedback()` validates target exists via `_validate_target_exists()`, enforces idempotency, returns feedback dict with `_new` flag.
- `get_feedback()` and `get_provenance()` support all documented filters with pagination.
- `get_aggregation()` computes thumbs_up/down counts, star_average, star_distribution, recent_comments.
- `link_feedback_to_provenance()` performs efficient batch lookup of feedback for provenance records.
- `export_feedback()` streams JSONL or CSV lines.
- `_redact_pii()` applies regex patterns to redact email, phone, SSN, credit card, API key.
- `_compute_payload_hash()` produces deterministic SHA-256 hash.

### Task 5: ProvenanceCollector

**Story points:** 3  
**Files to create/modify:**
- `app/services/ai/provenance_collector.py` (new file)

**Acceptance criteria:**
- `capture()` creates a `AIProvenanceRecord` with all documented fields.
- `_build_course_snapshot()` returns accurate page/component counts and schema signatures.
- `check_drift()` detects when proposal payload hash differs from stored hash.
- Failure is non-blocking: all exceptions are caught, logged, and never propagate.
- Performance: `capture()` completes in < 50ms p99 (uses at most 2 DB queries).

### Task 6: Integration into ToolExecutor

**Story points:** 2  
**Files to modify:**
- `app/services/ai/tool_executor.py`

**Acceptance criteria:**
- After successful `propose_create_page`, `propose_update_page`, and `propose_delete_page` tool executions, `ProvenanceCollector.capture()` is called.
- `session_context` dict is extended to include `model_id`, `provider`, `prompt_version`, `input_tokens`, `output_tokens`, `latency_ms`.
- Provenance capture failure does not roll back the proposal.
- Drift status is set to `not_applicable` for delete proposals.

### Task 7: API Router

**Story points:** 5  
**Files to create/modify:**
- `app/routers/ai_feedback.py` (new file)
- `app/main.py` (modify)

**Acceptance criteria:**
- `POST /api/v1/ai/feedback` returns 201 on create, 200 on duplicate, 404 on target not found, 422 on validation error.
- `GET /api/v1/ai/feedback` returns paginated results with `has_more` flag.
- `GET /api/v1/ai/feedback/stats` returns aggregated stats.
- `GET /api/v1/ai/provenance` returns paginated provenance with linked feedback.
- `GET /api/v1/ai/provenance/export` streams JSONL/CSV with correct Content-Type and Content-Disposition.
- All endpoints gated behind `ai_suggestions` feature flag.
- Router is registered in `app/main.py` with `api_router.include_router(ai_feedback.router)`.
- ORM model import added to `lifespan` startup section.

### Task 8: Environment Variables

**Story points:** 1  
**Files to modify:**
- `.env.example`
- `.env`

**Acceptance criteria:**
- `AI_FEEDBACK_MAX_COMMENT_LENGTH`, `AI_FEEDBACK_RETRY_ENABLED`, `AI_PROVENANCE_ENABLED`, `AI_EXPORT_ASYNC_THRESHOLD`, `AI_EXPORT_REDACT_PII`, `AI_EXPORT_PII_PATTERNS` documented.
- Each variable has a default value and description.
- Variables are read at service init time with `os.getenv()`.

### Task 9: Tests

**Story points:** 8  
**Files to create/modify:**
- `tests/test_ai_feedback_service.py`
- `tests/test_provenance_collector.py`
- `tests/test_ai_feedback_api.py`
- `tests/conftest.py` (add fixtures)

**Acceptance criteria:**
- All unit tests from Section 6.1 and 6.2 pass.
- `conftest.py` fixtures: `sample_ai_session_with_turn`, `sample_feedback_records`, `sample_provenance_with_feedback`, `sample_provenance_records`, `sample_provenance_with_pii`, `sample_proposal`.
- Test coverage > 90% for all new services, repositories, and routers.
- Integration tests use `async_client` and `db_session` fixtures consistent with existing tests.
- edge cases covered: empty results, duplicate submissions, PII redaction, drift detection.

---

## 8. Rollout and Migration Plan

### 8.1 Schema Migration

The new tables (`ai_feedback`, `ai_provenance`, `ai_feedback_tags`) are additive and backwards-compatible. No existing tables are modified. Migration can be run online without downtime.

**Rollback:** `alembic downgrade -1` drops the three new tables only.

### 8.2 Feature Flag Gating

All new endpoints are gated behind the existing `ai_suggestions` feature flag. Set `FEATURE_AI_SUGGESTIONS=true` in production to enable.

### 8.3 Phased Rollout

1. **Phase 1 (Dev/QA):** Enable feedback submission + query endpoints. Provenance capture is enabled. Exports work synchronously (< 1000 rows).
2. **Phase 2 (Staging):** Enable `AI_FEEDBACK_RETRY_ENABLED` for controlled testing of feedback-triggered regeneration.
3. **Phase 3 (Production):** Full rollout. Export async threshold configured for production data volumes.

### 8.4 Data Retention

- Feedback records: retained indefinitely (compliance requirement for regulated tenants). Subject to data retention policies (configurable via retention job).
- Provenance records: retained for 90 days by default. Configurable via `AI_PROVENANCE_RETENTION_DAYS`.
- Feedback tags: retained alongside parent feedback record.

---
The story is complete and written to file. Here is a summary of what was produced.

**File:** `C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\00_User_StoriesUseCases\US-AI-032_POLICY_ENGINE_AUTO_APPLY.md`

**2,344 lines** across the full 8-section template:

**1. Functional Specification** -- 9 functional requirements (FR-POL-01 through FR-POL-09) covering risk classification, confirmation modes (`auto_apply`/`soft_confirm`/`hard_confirm`/`block`), tenant-scoped configuration, hot-reload, audit logging, admin overrides, and a dry-run evaluation endpoint. An edge-case table covers 8 scenarios including conflicting rules, engine failure, boundary values, and invalid config.

**2. Technical Specification** -- Complete with:
- **3 PostgreSQL DDL tables**: `ai_policy_rules`, `ai_policy_decisions`, `ai_policy_overrides` with check constraints, indexes (including partial indexes on `is_active` and `expires_at`), and seed data (9 system-default rules)
- **3 ORM models** (`PolicyRule`, `PolicyDecision`, `PolicyOverride`) in `app/models/ai_policy.py` following the existing `AIAuditLog` pattern
- **13 Pydantic DTOs** in `app/models/ai_policy_dto.py` covering rule CRUD, evaluation requests/responses, decision audit, override management, and an internal `ProposalRiskContext`
- **7 API endpoint contracts** with exact request/response JSON schemas, query parameters, and error responses: `GET/POST/PUT/DELETE /rules`, `POST /evaluate`, `GET /decisions`, `POST/GET/DELETE /overrides`
- **Full `PolicyEngine` service class** with method signatures for `evaluate()`, `compute_risk_score()`, `match_rule()`, `check_override()`, rule CRUD, decision CRUD, and override management. Includes static weight-mapping methods for operation type, template type, page count, and user role
- **3 repository classes** (`PolicyRuleRepository`, `PolicyDecisionRepository`, `PolicyOverrideRepository`) with all query, filter, and mutation methods
- **Full router** in `app/routers/ai_policy.py` with admin auth dependency, error envelope re-use, and feature flag gating
- **Alembic migration** with seed insert of 9 sensible-default rules (auto-apply for instructor content-text updates, hard-confirm for deletes/assessments/batches, block for anonymous users, fallback default)
- **Integration points** for `app/main.py` (router registration), `alembic/env.py`, `app/models/__init__.py`, and detailed pseudo-code for calling the engine from the proposal service (US-AI-009) and the apply service (US-AI-010)
- **10 environment variables** with descriptions and defaults

**3. Non-Functional Requirements** -- Performance targets (p95 < 50ms cached evaluation), security (admin-only CRUD, fail-safe default, tenant isolation, override auditing), data retention (365 days for decisions, 90 days for expired overrides), availability (99.9%, degraded to `hard_confirm`), and 6 observability metrics.

**4. Current State Assessment** -- 8-section inventory of what exists (no policy tables, no policy service, existing proposal lifecycle with hard-coded confirmation, feature flag infra, error envelope, audit service reference, branching rules pattern, analytics router pattern) and a table of 8 components to build.

**5. Expansion Points** -- 5 phases: time-based policies, ML-enhanced risk scoring, policy-as-code, federated policy.

**6. Validation Strategy** -- 33 unit tests, 26 API integration tests, 5 proposal-flow E2E integration tests, 5 security tests, 3 performance benchmarks -- all with exact test names, scenarios, and expected outcomes.

**7. Definition of Done** -- 13 acceptance criteria, 10 quality gates, 5 signoff checklist items.

**8. Task Breakdown** -- 6 task groups, 15 tasks, 26 total story points with dependencies on US-AI-009, US-AI-010, US-AI-002, US-AI-020, and US-AI-003.

---

---

# Operations & Improvement (US-AI-033 — US-AI-042)