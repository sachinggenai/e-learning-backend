# US-AI-020: Provide Admin Audit, Compliance, and Recovery Views

**As an** Admin, **I want** to inspect AI operations, filter audit trails, and recover from problematic changes, **so that** AI-assisted authoring meets governance requirements and compliance audits.

- **Priority:** SHOULD for production rollout, MUST for regulated tenants
- **Depends on:** US-AI-010 (Apply Safety, Audit, and Outbox), US-AI-004 (AI Persistence Foundations)
- **Unlocks:** US-AI-022 (E2E Regression Suite), US-AI-040 (AI Content Versioning and Rollback)
- **Source flows:** 3 (Create), 4 (Update), 5 (Delete), 9 (Chat Edit), 10 (Full Course), 11 (Destructive Delete), 12 (Safety)
- **Epic Owner:** Technical Product Owner

---

## 1. Functional Specification

### 1.1 Audit Log API

**Goal:** Every applied AI mutation produces an immutable audit record that can be queried, filtered, and exported.

**Core Functional Requirements:**

1. **FR-AUDIT-01 (Record Every Mutation):** Every successful AI apply (create/update/delete page, batch apply, course-level operation) writes exactly one row to `ai_audit_logs` within the same database transaction.
2. **FR-AUDIT-02 (Read-Only Query):** Admin-facing audit endpoints are read-only. No mutation of audit records through the API.
3. **FR-AUDIT-03 (Filtering):** Admins can filter audit logs by: user ID, course ID, operation type, proposal ID, model ID, outcome (success/failure/rolled-back), date range, and free-text search over `summary`.
4. **FR-AUDIT-04 (Pagination):** All list endpoints support cursor-based pagination with configurable page size (default 50, max 200).
5. **FR-AUDIT-05 (Detail View):** Each audit entry exposes full detail: before-snapshot, after-candidate, validation summary, provenance metadata (model, prompt version, provider), and linked outbox event.
6. **FR-AUDIT-06 (Export):** Admins can export filtered audit results as CSV or JSON with a date range and field selection.

### 1.2 Compliance Dashboard Views

**Goal:** Admins can see aggregate compliance metrics and drill into specific operations.

**Core Functional Requirements:**

1. **FR-COMP-01 (Operations Summary):** Aggregate counts of AI operations over time: total mutations, by operation type, by outcome, by user.
2. **FR-COMP-02 (User Activity Report):** Per-user breakdown of AI operations: proposals created, approved, rejected, expired.
3. **FR-COMP-03 (Model Performance):** Model-level metrics: operations per model, error rate, average latency, rollback rate.
4. **FR-COMP-04 (Course Change History):** Time-ordered change log for a specific course showing every AI mutation with before/after summary.
5. **FR-COMP-05 (PII/Safety Event Log):** Separate queryable log of safety events (prompt injection blocks, PII detection, toxic output blocks) linked to the related audit entry when applicable.

### 1.3 Recovery Operations

**Goal:** Admins can inspect and initiate recovery from problematic AI changes through the standard safety-gated proposal pipeline.

**Core Functional Requirements:**

1. **FR-RECOV-01 (Inspect Before Snapshot):** Admin can view the full before-snapshot of any applied mutation to assess the impact of a potential rollback.
2. **FR-RECOV-02 (Generate Rollback Proposal):** Admin can select an audit entry and request a rollback proposal. The system creates a standard proposal (following the same propose-validate-confirm-apply pipeline) that restores the before-snapshot state.
3. **FR-RECOV-03 (Rollback Chain):** Rollbacks themselves are recorded in the audit log with a `"rolled_back"` outcome and a `rollback_of` field pointing to the original mutation audit entry. A subsequent rollback of a rollback is supported (re-do).
4. **FR-RECOV-04 (Diff View):** For any audit entry, the system can generate a structured diff (JSON Patch or field-level before/after comparison) for human review.
5. **FR-RECOV-05 (Dry-Run Rollback):** Admin can request a dry-run rollback that validates the before-snapshot against the current course state without applying — detecting conflicts (page already edited, page deleted by another user).

### 1.4 Edge Cases and Error Handling

| Scenario | Expected Behavior |
|---|---|
| Audit entry refers to a page that has since been edited manually | Dry-run rollback returns conflict error listing the conflicting fields |
| Audit entry refers to a page that has been deleted | Dry-run rollback returns page-not-found error. Rollback proposal creates the page from before-snapshot |
| Filter date range spans a migration that changed audit schema | API returns audit entries in the format stored at the time of recording (backward-compatible) |
| Audit export exceeds 10,000 rows | API returns a job ID for async export generation. Frontend polls for download readiness |
| Rollback of a rollback | Supported. Each rollback creates a new audit entry with `rollback_of` pointing to its target |

---

## 2. Technical Specification

### 2.1 Database Schema (PostgreSQL DDL)

#### 2.1.1 `ai_audit_logs` Table

```sql
CREATE TABLE IF NOT EXISTS ai_audit_logs (
    id              BIGSERIAL PRIMARY KEY,
    audit_id        VARCHAR(64) NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,
    
    -- Session & User context
    session_id      VARCHAR(64) NOT NULL,
    user_id         VARCHAR(128) NOT NULL DEFAULT 'system',
    organization_id VARCHAR(64) NOT NULL DEFAULT 'default',
    
    -- Operation metadata
    operation       VARCHAR(32) NOT NULL CHECK (operation IN (
                        'page_created', 'page_updated', 'page_deleted',
                        'course_created', 'course_updated', 'course_deleted',
                        'batch_applied', 'rollback', 'proposal_rejected',
                        'proposal_expired', 'component_updated'
                     )),
    outcome         VARCHAR(16) NOT NULL CHECK (outcome IN (
                        'success', 'failure', 'rolled_back', 'conflict'
                     )) DEFAULT 'success',
    
    -- Foreign keys to proposals, sessions, courses
    proposal_id     VARCHAR(64),
    course_id       VARCHAR(64) NOT NULL,
    page_id         VARCHAR(64),
    outbox_event_id VARCHAR(64),
    
    -- Before/After snapshots
    before_snapshot   JSONB,
    after_snapshot    JSONB,
    diff_patch        JSONB,  -- RFC 6902 JSON Patch
    
    -- Validation and provenance
    validation_summary    JSONB,  -- {valid: bool, errors: [...], warnings: [...]}
    provenance           JSONB,  -- {model_id, prompt_version, provider, schema_version, tool_version}
    
    -- Rollback linkage
    rollback_of_audit_id VARCHAR(64),  -- FK to the original mutation if this is a rollback
    
    -- Human-readable summary
    summary            TEXT NOT NULL DEFAULT '',
    
    -- Traceability
    trace_id           VARCHAR(64) NOT NULL,
    idempotency_key    VARCHAR(64),
    
    -- Timestamps
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Indexes
    CONSTRAINT fk_audit_rollback FOREIGN KEY (rollback_of_audit_id)
        REFERENCES ai_audit_logs(audit_id) ON DELETE SET NULL
);

-- Indexes for common query patterns
CREATE INDEX idx_audit_course_id ON ai_audit_logs(course_id);
CREATE INDEX idx_audit_user_id ON ai_audit_logs(user_id);
CREATE INDEX idx_audit_operation ON ai_audit_logs(operation);
CREATE INDEX idx_audit_outcome ON ai_audit_logs(outcome);
CREATE INDEX idx_audit_proposal_id ON ai_audit_logs(proposal_id);
CREATE INDEX idx_audit_session_id ON ai_audit_logs(session_id);
CREATE INDEX idx_audit_trace_id ON ai_audit_logs(trace_id);
CREATE INDEX idx_audit_created_at ON ai_audit_logs(created_at DESC);
CREATE INDEX idx_audit_rollback_of ON ai_audit_logs(rollback_of_audit_id);

-- Composite indexes for common filter combinations
CREATE INDEX idx_audit_course_created ON ai_audit_logs(course_id, created_at DESC);
CREATE INDEX idx_audit_user_operation ON ai_audit_logs(user_id, operation, created_at DESC);
CREATE INDEX idx_audit_org_created ON ai_audit_logs(organization_id, created_at DESC);

-- GIN index for JSONB provenance queries
CREATE INDEX idx_audit_provenance ON ai_audit_logs USING GIN (provenance jsonb_path_ops);
CREATE INDEX idx_audit_validation ON ai_audit_logs USING GIN (validation_summary jsonb_path_ops);
```

#### 2.1.2 `ai_safety_events` Table (Compliance Sub-View)

```sql
CREATE TABLE IF NOT EXISTS ai_safety_events (
    id              BIGSERIAL PRIMARY KEY,
    event_id        VARCHAR(64) NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,
    
    -- Session & User context
    session_id      VARCHAR(64),
    user_id         VARCHAR(128) NOT NULL DEFAULT 'system',
    organization_id VARCHAR(64) NOT NULL DEFAULT 'default',
    
    -- Safety event details
    event_type      VARCHAR(32) NOT NULL CHECK (event_type IN (
                        'prompt_injection_blocked', 'pii_detected_and_redacted',
                        'toxic_output_blocked', 'blocked_term_detected',
                        'rate_limit_exceeded', 'policy_violation'
                     )),
    severity        VARCHAR(16) NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')) DEFAULT 'medium',
    
    -- The sanitized/redacted content (never raw PII)
    input_snippet   TEXT,
    output_snippet  TEXT,
    rule_triggered  VARCHAR(128),
    
    -- Link to audit entry if the safety event was associated with a successful mutation
    audit_id        VARCHAR(64),
    trace_id        VARCHAR(64) NOT NULL,
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    CONSTRAINT fk_safety_audit FOREIGN KEY (audit_id)
        REFERENCES ai_audit_logs(audit_id) ON DELETE SET NULL
);

CREATE INDEX idx_safety_type ON ai_safety_events(event_type);
CREATE INDEX idx_safety_severity ON ai_safety_events(severity);
CREATE INDEX idx_safety_created ON ai_safety_events(created_at DESC);
CREATE INDEX idx_safety_audit_id ON ai_safety_events(audit_id);
CREATE INDEX idx_safety_session_id ON ai_safety_events(session_id);
```

#### 2.1.3 `ai_usage_records` Table (Cost/Budget Tracking for Compliance)

```sql
CREATE TABLE IF NOT EXISTS ai_usage_records (
    id              BIGSERIAL PRIMARY KEY,
    usage_id        VARCHAR(64) NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,
    
    session_id      VARCHAR(64),
    user_id         VARCHAR(128) NOT NULL,
    organization_id VARCHAR(64) NOT NULL DEFAULT 'default',
    
    -- Model usage
    model_id        VARCHAR(128) NOT NULL,
    provider        VARCHAR(64) NOT NULL,
    model_tier      VARCHAR(16) CHECK (model_tier IN ('planner', 'generator', 'repair', 'safety')),
    
    -- Token counts
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    total_tokens    INTEGER GENERATED ALWAYS AS (input_tokens + output_tokens) STORED,
    
    -- Cost (computed from token counts and model pricing)
    cost_usd        NUMERIC(12, 6) NOT NULL DEFAULT 0,
    
    -- Latency
    latency_ms      INTEGER,
    
    -- Context
    trace_id        VARCHAR(64) NOT NULL,
    operation       VARCHAR(32),  -- The AI operation that caused this usage
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
) PARTITION BY RANGE (created_at);

-- Create monthly partitions (PostgreSQL 12+)
CREATE TABLE ai_usage_records_2026_06 PARTITION OF ai_usage_records
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
CREATE TABLE ai_usage_records_2026_07 PARTITION OF ai_usage_records
    FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');

CREATE INDEX idx_usage_session ON ai_usage_records(session_id);
CREATE INDEX idx_usage_user ON ai_usage_records(user_id, created_at DESC);
CREATE INDEX idx_usage_model ON ai_usage_records(model_id);
CREATE INDEX idx_usage_org_created ON ai_usage_records(organization_id, created_at DESC);
```

### 2.2 ORM Models

**File:** `app/models/ai_audit.py`

```python
"""ORM models for AI audit, compliance, and safety events."""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import (
    String, DateTime, JSONB, Text, BigInteger, Integer,
    Numeric, ForeignKey, CheckConstraint, Index
)

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class AIAuditLog(Base):
    """Immutable audit record for every applied AI mutation."""

    __tablename__ = "ai_audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    audit_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, default="system")
    organization_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default"
    )
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="success")
    proposal_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    course_id: Mapped[str] = mapped_column(String(64), nullable=False)
    page_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    outbox_event_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    before_snapshot: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    after_snapshot: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    diff_patch: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    validation_summary: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    provenance: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    rollback_of_audit_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "operation IN ('page_created','page_updated','page_deleted',"
            "'course_created','course_updated','course_deleted',"
            "'batch_applied','rollback','proposal_rejected','proposal_expired','component_updated')",
            name="ck_audit_operation",
        ),
        CheckConstraint(
            "outcome IN ('success','failure','rolled_back','conflict')",
            name="ck_audit_outcome",
        ),
        Index("idx_audit_course_created", "course_id", "created_at"),
        Index("idx_audit_user_operation", "user_id", "operation", "created_at"),
        Index("idx_audit_org_created", "organization_id", "created_at"),
    )

    def to_dict(self) -> dict:
        return {
            "auditId": self.audit_id,
            "sessionId": self.session_id,
            "userId": self.user_id,
            "organizationId": self.organization_id,
            "operation": self.operation,
            "outcome": self.outcome,
            "proposalId": self.proposal_id,
            "courseId": self.course_id,
            "pageId": self.page_id,
            "outboxEventId": self.outbox_event_id,
            "beforeSnapshot": self.before_snapshot,
            "afterSnapshot": self.after_snapshot,
            "diffPatch": self.diff_patch,
            "validationSummary": self.validation_summary,
            "provenance": self.provenance,
            "rollbackOfAuditId": self.rollback_of_audit_id,
            "summary": self.summary,
            "traceId": self.trace_id,
            "createdAt": (
                self.created_at.isoformat() if self.created_at else None
            ),
        }


class AISafetyEvent(Base):
    """Safety event log for compliance monitoring."""

    __tablename__ = "ai_safety_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, default="system")
    organization_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default"
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    input_snippet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_snippet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rule_triggered: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    audit_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('prompt_injection_blocked','pii_detected_and_redacted',"
            "'toxic_output_blocked','blocked_term_detected',"
            "'rate_limit_exceeded','policy_violation')",
            name="ck_safety_event_type",
        ),
        CheckConstraint(
            "severity IN ('low','medium','high','critical')",
            name="ck_safety_severity",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "eventId": self.event_id,
            "sessionId": self.session_id,
            "userId": self.user_id,
            "organizationId": self.organization_id,
            "eventType": self.event_type,
            "severity": self.severity,
            "inputSnippet": self.input_snippet,
            "outputSnippet": self.output_snippet,
            "ruleTriggered": self.rule_triggered,
            "auditId": self.audit_id,
            "traceId": self.trace_id,
            "createdAt": (
                self.created_at.isoformat() if self.created_at else None
            ),
        }
```

### 2.3 Pydantic Request/Response Models

**File:** `app/models/ai_audit_dto.py`

```python
"""Pydantic DTOs for AI audit and compliance API surfaces."""
from __future__ import annotations
from datetime import datetime
from typing import Optional, List, Literal

from pydantic import BaseModel, Field


# ── Audit Query ──────────────────────────────────────────────────────────────

class AuditFilterParams(BaseModel):
    """Query parameters for filtering audit logs."""
    course_id: Optional[str] = Field(None, description="Filter by course ID")
    user_id: Optional[str] = Field(None, description="Filter by user ID")
    operation: Optional[str] = Field(None, description="Filter by operation type")
    outcome: Optional[str] = Field(None, description="Filter by outcome")
    proposal_id: Optional[str] = Field(None, description="Filter by proposal ID")
    model_id: Optional[str] = Field(None, description="Filter by model ID from provenance")
    date_from: Optional[datetime] = Field(None, description="Start of date range")
    date_to: Optional[datetime] = Field(None, description="End of date range")
    search: Optional[str] = Field(
        None, max_length=200, description="Free-text search over summary field"
    )
    limit: int = Field(default=50, ge=1, le=200, description="Page size")
    cursor: Optional[str] = Field(
        None, description="Opaque cursor for cursor-based pagination"
    )


class AuditEntryOut(BaseModel):
    """Single audit log entry in list responses (excludes large payloads)."""
    auditId: str
    sessionId: str
    userId: str
    operation: str
    outcome: str
    proposalId: Optional[str] = None
    courseId: str
    pageId: Optional[str] = None
    outboxEventId: Optional[str] = None
    summary: str
    traceId: str
    rollbackOfAuditId: Optional[str] = None
    createdAt: str

    model_config = {"from_attributes": True}


class AuditDetailOut(BaseModel):
    """Full audit entry including snapshots and provenance."""
    auditId: str
    sessionId: str
    userId: str
    organizationId: str
    operation: str
    outcome: str
    proposalId: Optional[str] = None
    courseId: str
    pageId: Optional[str] = None
    beforeSnapshot: Optional[dict] = None
    afterSnapshot: Optional[dict] = None
    diffPatch: Optional[dict] = None
    validationSummary: Optional[dict] = None
    provenance: Optional[dict] = None
    rollbackOfAuditId: Optional[str] = None
    summary: str
    traceId: str
    idempotencyKey: Optional[str] = None
    createdAt: str

    model_config = {"from_attributes": True}


class AuditListOut(BaseModel):
    """Paginated audit log list response."""
    items: List[AuditEntryOut]
    total: int
    nextCursor: Optional[str] = Field(
        None, description="Opaque cursor for the next page"
    )
    hasMore: bool


# ── Diff / Rollback ──────────────────────────────────────────────────────────

class DiffRequest(BaseModel):
    audit_id: str = Field(..., description="Target audit entry ID")


class DiffOut(BaseModel):
    auditId: str
    beforeSnapshot: Optional[dict] = None
    afterSnapshot: Optional[dict] = None
    diffPatch: Optional[dict] = None
    changedFields: List[str] = Field(default_factory=list)
    pageExists: bool
    courseExists: bool


class RollbackProposalRequest(BaseModel):
    audit_id: str = Field(..., description="Target audit entry ID to roll back")
    reason: str = Field(
        ..., min_length=10, max_length=1000,
        description="Reason for the rollback (recorded in audit)"
    )


class RollbackProposalOut(BaseModel):
    proposalId: str
    operation: str = Field(default="rollback")
    summary: str
    dryRunResult: Optional[dict] = Field(
        None, description="Dry-run validation result before apply"
    )
    expiresAt: str


# ── Compliance Summary ───────────────────────────────────────────────────────

class OperationsSummaryOut(BaseModel):
    totalOperations: int
    byOperation: dict  # {operation: count}
    byOutcome: dict    # {outcome: count}
    dateFrom: str
    dateTo: str


class UserActivityOut(BaseModel):
    userId: str
    proposalsCreated: int
    proposalsApproved: int
    proposalsRejected: int
    proposalsExpired: int
    lastActiveAt: str


class ModelPerformanceOut(BaseModel):
    modelId: str
    operationCount: int
    errorRate: float
    avgLatencyMs: float
    rollbackRate: float
    lastUsedAt: str


class CourseChangeHistoryOut(BaseModel):
    courseId: str
    changes: List[AuditEntryOut]


# ── Safety Events ────────────────────────────────────────────────────────────

class SafetyEventOut(BaseModel):
    eventId: str
    eventType: str
    severity: str
    ruleTriggered: Optional[str] = None
    auditId: Optional[str] = None
    traceId: str
    createdAt: str

    model_config = {"from_attributes": True}


class SafetyEventListOut(BaseModel):
    items: List[SafetyEventOut]
    total: int
    nextCursor: Optional[str] = None
    hasMore: bool


# ── Audit Export ─────────────────────────────────────────────────────────────

class AuditExportRequest(BaseModel):
    format: Literal["csv", "json"] = Field(default="json")
    course_id: Optional[str] = None
    user_id: Optional[str] = None
    operation: Optional[str] = None
    outcome: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    fields: Optional[List[str]] = Field(
        None, description="Subset of fields to include"
    )


class AuditExportOut(BaseModel):
    exportJobId: str
    status: str  # "pending" | "processing" | "completed" | "failed"
    format: str
    estimatedRows: int
    downloadUrl: Optional[str] = None
    expiresAt: Optional[str] = None
```

### 2.4 API Contracts

All routes are under the existing `/api/v1/ai` prefix namespace (see US-AI-003) with an `admin` sub-prefix.

#### `GET /api/v1/ai/admin/audit-logs`

List audit log entries with filtering and cursor-based pagination.

**Query Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `course_id` | string | No | Filter by course ID |
| `user_id` | string | No | Filter by user ID |
| `operation` | string | No | Filter by operation type |
| `outcome` | string | No | Filter by outcome |
| `proposal_id` | string | No | Filter by proposal ID |
| `model_id` | string | No | Filter by model ID (in provenance) |
| `date_from` | ISO8601 datetime | No | Start of date range |
| `date_to` | ISO8601 datetime | No | End of date range |
| `search` | string | No | Free-text search over `summary` |
| `limit` | integer | No | Page size (1-200, default 50) |
| `cursor` | string | No | Opaque cursor from previous response |

**Response `200 OK`:**
```json
{
  "items": [
    {
      "auditId": "a1b2c3d4-...",
      "sessionId": "sess-001",
      "userId": "user-42",
      "operation": "page_created",
      "outcome": "success",
      "proposalId": "prop-007",
      "courseId": "course-alpha",
      "pageId": "page-123",
      "outboxEventId": "evt-8910",
      "summary": "Created page 'Introduction to Algebra' as page 3",
      "traceId": "trace-abc-123",
      "rollbackOfAuditId": null,
      "createdAt": "2026-06-14T10:30:00+00:00"
    }
  ],
  "total": 142,
  "nextCursor": "eyJpZCI6IDE0Mn0=",
  "hasMore": true
}
```

**Error Responses:**
- `422` — Invalid filter parameter (e.g., `operation` not in allowed list)
- `500` — Internal error

#### `GET /api/v1/ai/admin/audit-logs/{audit_id}`

Get full detail for a single audit entry.

**Response `200 OK`:**
```json
{
  "auditId": "a1b2c3d4-...",
  "sessionId": "sess-001",
  "userId": "user-42",
  "organizationId": "org-default",
  "operation": "page_created",
  "outcome": "success",
  "proposalId": "prop-007",
  "courseId": "course-alpha",
  "pageId": "page-123",
  "beforeSnapshot": null,
  "afterSnapshot": {
    "title": "Introduction to Algebra",
    "pageId": "page-123",
    "order": 3,
    "components": [
      {"componentId": "comp-1", "componentType": "content-text", "data": {...}}
    ]
  },
  "diffPatch": {"op": "add", "path": "/pages/3", "value": {...}},
  "validationSummary": {
    "valid": true,
    "errors": [],
    "warnings": ["Image missing alt text"]
  },
  "provenance": {
    "modelId": "claude-sonnet-4",
    "promptVersion": "v2.1",
    "provider": "anthropic",
    "schemaVersion": "1.0",
    "toolVersion": "1.0"
  },
  "rollbackOfAuditId": null,
  "summary": "Created page 'Introduction to Algebra' as page 3",
  "traceId": "trace-abc-123",
  "idempotencyKey": "idem-xyz-789",
  "createdAt": "2026-06-14T10:30:00+00:00"
}
```

**Error Responses:**
- `404` — Audit entry not found

#### `GET /api/v1/ai/admin/audit-logs/{audit_id}/diff`

Get the structured diff for an audit entry.

**Response `200 OK`:**
```json
{
  "auditId": "a1b2c3d4-...",
  "beforeSnapshot": {"title": "Old Title", "components": [...]},
  "afterSnapshot": {"title": "New Title", "components": [...]},
  "diffPatch": [
    {"op": "replace", "path": "/title", "value": "New Title"},
    {"op": "add", "path": "/components/1", "value": {...}}
  ],
  "changedFields": ["title", "components[1]"],
  "pageExists": true,
  "courseExists": true
}
```

**Error Responses:**
- `404` — Audit entry not found
- `200 with pageExists: false` — Referenced page no longer exists (before-snapshot still available)

#### `POST /api/v1/ai/admin/rollback/propose`

Generate a rollback proposal from an audit entry.

**Request Body:**
```json
{
  "audit_id": "a1b2c3d4-...",
  "reason": "Incorrect content generated for the introduction page"
}
```

**Response `200 OK`:**
```json
{
  "proposalId": "rollback-prop-001",
  "operation": "rollback",
  "summary": "Rollback page 'Introduction to Algebra' to state before AI mutation a1b2c3d4",
  "dryRunResult": {
    "valid": true,
    "conflicts": [],
    "changes": [
      {"field": "title", "from": "New Title", "to": "Old Title"},
      {"field": "components[0].data.body", "from": "...", "to": "..."}
    ]
  },
  "expiresAt": "2026-06-15T10:30:00+00:00"
}
```

**Error Responses:**
- `404` — Audit entry not found
- `409` — Rollback already proposed for this audit entry (existing proposal ID returned)
- `422` — Dry-run failed: conflicts detected with current state

**Conflict Example (`422`):**
```json
{
  "detail": {
    "code": "ROLLBACK_CONFLICT",
    "field": "proposal",
    "message": "Cannot rollback: page has been modified since the mutation",
    "details": {
      "conflicts": [
        {
          "field": "title",
          "currentValue": "Different Title",
          "expectedValue": "New Title",
          "resolution": "manual_intervention_required"
        }
      ]
    }
  }
}
```

#### `POST /api/v1/ai/admin/audit-logs/export`

Start an async audit export job.

**Request Body:**
```json
{
  "format": "csv",
  "course_id": "course-alpha",
  "date_from": "2026-06-01T00:00:00Z",
  "date_to": "2026-06-14T23:59:59Z",
  "fields": ["auditId", "operation", "outcome", "summary", "createdAt"]
}
```

**Response `202 Accepted`:**
```json
{
  "exportJobId": "export-job-001",
  "status": "pending",
  "format": "csv",
  "estimatedRows": 85,
  "downloadUrl": null,
  "expiresAt": null
}
```

#### `GET /api/v1/ai/admin/audit-logs/exports/{export_job_id}`

Poll export job status.

**Response `200 OK` (when complete):**
```json
{
  "exportJobId": "export-job-001",
  "status": "completed",
  "format": "csv",
  "estimatedRows": 85,
  "downloadUrl": "/api/v1/ai/admin/audit-logs/exports/export-job-001/download",
  "expiresAt": "2026-06-15T10:30:00+00:00"
}
```

#### `GET /api/v1/ai/admin/safety-events`

List safety events with filtering.

**Query Parameters:** (same pagination/filtering as audit-logs)
| Parameter | Type | Required | Description |
|---|---|---|---|
| `event_type` | string | No | Filter by event type |
| `severity` | string | No | Filter by severity |
| `date_from` | ISO8601 | No | Start of date range |
| `date_to` | ISO8601 | No | End of date range |
| `limit` | integer | No | Page size (1-200, default 50) |
| `cursor` | string | No | Opaque cursor |

#### `GET /api/v1/ai/admin/compliance/summary`

Aggregate compliance metrics.

**Query Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `date_from` | ISO8601 | No | Default 30 days ago |
| `date_to` | ISO8601 | No | Default now |
| `organization_id` | string | No | Filter by org |

**Response `200 OK`:**
```json
{
  "totalOperations": 523,
  "byOperation": {
    "page_created": 210,
    "page_updated": 180,
    "page_deleted": 45,
    "batch_applied": 12,
    "rollback": 3,
    "course_created": 73
  },
  "byOutcome": {
    "success": 500,
    "failure": 15,
    "rolled_back": 3,
    "conflict": 5
  },
  "dateFrom": "2026-05-15T00:00:00Z",
  "dateTo": "2026-06-14T23:59:59Z"
}
```

#### `GET /api/v1/ai/admin/compliance/user-activity`

Per-user activity summary.

**Query Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `date_from` | ISO8601 | No | |
| `date_to` | ISO8601 | No | |
| `limit` | integer | No | Default 50 |

**Response `200 OK`:**
```json
{
  "users": [
    {
      "userId": "user-42",
      "proposalsCreated": 98,
      "proposalsApproved": 85,
      "proposalsRejected": 8,
      "proposalsExpired": 5,
      "lastActiveAt": "2026-06-14T10:30:00+00:00"
    }
  ],
  "total": 12
}
```

#### `GET /api/v1/ai/admin/compliance/model-performance`

Model-level performance metrics.

**Response `200 OK`:**
```json
{
  "models": [
    {
      "modelId": "claude-sonnet-4",
      "operationCount": 340,
      "errorRate": 0.029,
      "avgLatencyMs": 1450,
      "rollbackRate": 0.006,
      "lastUsedAt": "2026-06-14T10:30:00+00:00"
    }
  ],
  "total": 2
}
```

#### `GET /api/v1/ai/admin/courses/{courseId}/changes`

Time-ordered change history for a specific course.

**Response `200 OK`:**
```json
{
  "courseId": "course-alpha",
  "changes": [
    {
      "auditId": "a1b2c3d4-...",
      "userId": "user-42",
      "operation": "page_created",
      "outcome": "success",
      "summary": "Created page 'Introduction'",
      "createdAt": "2026-06-14T10:30:00+00:00"
    }
  ],
  "total": 10
}
```

### 2.5 Service Signatures

**File:** `app/services/ai/audit_service.py`

```python
"""Service layer for AI audit, compliance, and recovery operations."""
from __future__ import annotations
from typing import Optional, List, Tuple
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession


class AuditService:
    """Handles audit record queries, rollback proposal generation, and compliance aggregation."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_audit_logs(
        self,
        *,
        course_id: Optional[str] = None,
        user_id: Optional[str] = None,
        operation: Optional[str] = None,
        outcome: Optional[str] = None,
        proposal_id: Optional[str] = None,
        model_id: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        search: Optional[str] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> Tuple[List[dict], int, Optional[str]]:
        """Query audit logs with filters and cursor pagination.
        
        Returns:
            Tuple of (items, total_count, next_cursor)
        """
        ...

    async def get_audit_detail(self, audit_id: str) -> Optional[dict]:
        """Get full audit entry detail including snapshots and provenance."""
        ...

    async def get_audit_diff(self, audit_id: str) -> dict:
        """Compute structured diff from before/after snapshots.
        
        Returns dict with before_snapshot, after_snapshot, diff_patch,
        changed_fields, page_exists, course_exists.
        """
        ...

    async def propose_rollback(
        self,
        audit_id: str,
        reason: str,
        user_id: str,
        session_id: str,
    ) -> dict:
        """Generate a rollback proposal from an audit entry.
        
        Steps:
        1. Load audit entry and verify it exists
        2. Check if rollback already proposed (return existing proposal if so)
        3. Run dry-run validation against current state
        4. Create a proposal record with before-snapshot as target
        5. Return proposal info with dry-run results
        
        Raises:
            AuditEntryNotFoundError
            RollbackConflictError (with conflict details)
        """
        ...

    async def list_safety_events(
        self,
        *,
        event_type: Optional[str] = None,
        severity: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> Tuple[List[dict], int, Optional[str]]:
        """Query safety events with filtering."""
        ...

    async def get_compliance_summary(
        self,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        organization_id: Optional[str] = None,
    ) -> dict:
        """Aggregate operations by type and outcome."""
        ...

    async def get_user_activity(
        self,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 50,
    ) -> List[dict]:
        """Per-user activity breakdown."""
        ...

    async def get_model_performance(
        self,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> List[dict]:
        """Model-level metrics from usage records."""
        ...

    async def get_course_changes(
        self,
        course_id: str,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> Tuple[List[dict], int, Optional[str]]:
        """Time-ordered change history for a course."""
        ...

    async def create_audit_entry(
        self,
        *,
        session_id: str,
        user_id: str,
        organization_id: str,
        operation: str,
        outcome: str,
        course_id: str,
        proposal_id: Optional[str] = None,
        page_id: Optional[str] = None,
        outbox_event_id: Optional[str] = None,
        before_snapshot: Optional[dict] = None,
        after_snapshot: Optional[dict] = None,
        validation_summary: Optional[dict] = None,
        provenance: Optional[dict] = None,
        rollback_of_audit_id: Optional[str] = None,
        summary: str,
        trace_id: str,
        idempotency_key: Optional[str] = None,
    ) -> str:
        """Create a new audit entry (called by apply service).
        
        Returns the audit_id of the created entry.
        """
        ...

    async def create_safety_event(
        self,
        *,
        session_id: Optional[str],
        user_id: str,
        organization_id: str,
        event_type: str,
        severity: str,
        input_snippet: Optional[str] = None,
        output_snippet: Optional[str] = None,
        rule_triggered: Optional[str] = None,
        audit_id: Optional[str] = None,
        trace_id: str,
    ) -> str:
        """Record a safety event (called by guard services)."""
        ...

    async def request_audit_export(
        self,
        *,
        format: str,
        course_id: Optional[str] = None,
        user_id: Optional[str] = None,
        operation: Optional[str] = None,
        outcome: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        fields: Optional[List[str]] = None,
    ) -> dict:
        """Start an async audit export job. Returns job metadata.
        
        For small exports (< 1000 rows), completes synchronously.
        For large exports, creates a background job.
        """
        ...
```

### 2.6 Repository

**File:** `app/repositories/ai_audit_repo.py`

```python
"""Repository for AI audit, safety event, and usage records."""
from __future__ import annotations
from typing import Optional, List, Tuple
from datetime import datetime
import base64
import json

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, text, and_
from sqlalchemy.dialects.postgresql import array

from app.models.ai_audit import AIAuditLog, AISafetyEvent


class AuditRepository:
    """DB access for ai_audit_logs table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_with_filters(
        self,
        *,
        course_id: Optional[str] = None,
        user_id: Optional[str] = None,
        operation: Optional[str] = None,
        outcome: Optional[str] = None,
        proposal_id: Optional[str] = None,
        model_id: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        search: Optional[str] = None,
        limit: int = 50,
        cursor_id: Optional[int] = None,
        cursor_created_at: Optional[datetime] = None,
    ) -> Tuple[List[AIAuditLog], int]:
        """Filtered query with cursor-based pagination.
        
        Uses an opaque cursor encoding (id, created_at) for stable pagination
        across result sets where created_at may have duplicates.
        """
        q = select(AIAuditLog)

        # Apply filters
        conditions = []
        if course_id:
            conditions.append(AIAuditLog.course_id == course_id)
        if user_id:
            conditions.append(AIAuditLog.user_id == user_id)
        if operation:
            conditions.append(AIAuditLog.operation == operation)
        if outcome:
            conditions.append(AIAuditLog.outcome == outcome)
        if proposal_id:
            conditions.append(AIAuditLog.proposal_id == proposal_id)
        if model_id:
            # Query inside provenance JSONB
            conditions.append(
                AIAuditLog.provenance["modelId"].as_string() == model_id
            )
        if date_from:
            conditions.append(AIAuditLog.created_at >= date_from)
        if date_to:
            conditions.append(AIAuditLog.created_at <= date_to)
        if search:
            conditions.append(AIAuditLog.summary.ilike(f"%{search}%"))
        if cursor_id and cursor_created_at:
            # Cursor pagination: fetch rows before (id, created_at)
            conditions.append(
                or_(
                    AIAuditLog.created_at < cursor_created_at,
                    and_(
                        AIAuditLog.created_at == cursor_created_at,
                        AIAuditLog.id < cursor_id,
                    ),
                )
            )

        if conditions:
            q = q.where(and_(*conditions))

        # Count total
        count_q = select(func.count()).select_from(q.subquery())
        total = (await self.session.execute(count_q)).scalar() or 0

        q = q.order_by(AIAuditLog.created_at.desc(), AIAuditLog.id.desc())
        q = q.limit(limit + 1)  # Fetch one extra to determine has_more

        rows = list((await self.session.execute(q)).scalars().all())
        return rows, total

    async def get_by_audit_id(self, audit_id: str) -> Optional[AIAuditLog]:
        q = select(AIAuditLog).where(AIAuditLog.audit_id == audit_id)
        return (await self.session.execute(q)).scalar_one_or_none()

    async def create(self, record: AIAuditLog) -> AIAuditLog:
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def get_usage_stats(
        self,
        date_from: datetime,
        date_to: datetime,
        organization_id: Optional[str] = None,
    ) -> dict:
        """Aggregate operations by type and outcome."""
        # Uses raw SQL for efficient aggregation
        stmt = text("""
            SELECT
                operation,
                outcome,
                COUNT(*) as count
            FROM ai_audit_logs
            WHERE created_at >= :date_from
              AND created_at <= :date_to
              AND (:org_id IS NULL OR organization_id = :org_id)
            GROUP BY operation, outcome
        """)
        result = await self.session.execute(
            stmt,
            {"date_from": date_from, "date_to": date_to, "org_id": organization_id},
        )
        rows = result.all()
        return {"rows": [{"operation": r[0], "outcome": r[1], "count": r[2]} for r in rows]}

    @staticmethod
    def encode_cursor(record_id: int, created_at: datetime) -> str:
        """Encode (id, created_at) into an opaque cursor string."""
        payload = json.dumps({"id": record_id, "created_at": created_at.isoformat()})
        return base64.urlsafe_b64encode(payload.encode()).decode()

    @staticmethod
    def decode_cursor(cursor: str) -> Tuple[int, datetime]:
        """Decode cursor into (id, created_at)."""
        try:
            payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
            return int(payload["id"]), datetime.fromisoformat(payload["created_at"])
        except (ValueError, KeyError, json.JSONDecodeError):
            raise ValueError("Invalid cursor")
```

### 2.7 Router

**File:** `app/routers/ai_admin.py`

```python
"""Admin audit, compliance, and recovery API routes.

All routes are prefixed with /api/v1/ai/admin and require admin-level
authorization (checked via dependency).
"""
from __future__ import annotations
from typing import Optional
from datetime import datetime, timedelta
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.services.ai.audit_service import AuditService
from app.models.ai_audit_dto import (
    AuditFilterParams,
    AuditEntryOut,
    AuditDetailOut,
    AuditListOut,
    DiffOut,
    RollbackProposalRequest,
    RollbackProposalOut,
    OperationsSummaryOut,
    UserActivityOut,
    ModelPerformanceOut,
    CourseChangeHistoryOut,
    SafetyEventOut,
    SafetyEventListOut,
    AuditExportRequest,
    AuditExportOut,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai/admin", tags=["AI Admin"])


# ── Dependencies ─────────────────────────────────────────────────────────────

async def _require_admin():
    """Placeholder for admin authorization check.
    
    In production, this would verify the user has the 'admin' or 'auditor' role
    and that the tenant is authorized for audit access.
    """
    return True


async def _get_audit_service(
    session: AsyncSession = Depends(get_session),
) -> AuditService:
    return AuditService(session)


# ── Audit Log Routes ─────────────────────────────────────────────────────────

@router.get("/audit-logs", response_model=AuditListOut)
async def list_audit_logs(
    params: AuditFilterParams = Depends(),
    admin: bool = Depends(_require_admin),
    service: AuditService = Depends(_get_audit_service),
):
    """List audit log entries with filtering and cursor pagination."""
    items, total, next_cursor = await service.list_audit_logs(
        course_id=params.course_id,
        user_id=params.user_id,
        operation=params.operation,
        outcome=params.outcome,
        proposal_id=params.proposal_id,
        model_id=params.model_id,
        date_from=params.date_from,
        date_to=params.date_to,
        search=params.search,
        limit=params.limit,
        cursor=params.cursor,
    )
    return AuditListOut(
        items=[AuditEntryOut(**item) for item in items],
        total=total,
        nextCursor=next_cursor,
        hasMore=next_cursor is not None,
    )


@router.get("/audit-logs/{audit_id}", response_model=AuditDetailOut)
async def get_audit_detail(
    audit_id: str,
    admin: bool = Depends(_require_admin),
    service: AuditService = Depends(_get_audit_service),
):
    """Get full audit entry detail."""
    detail = await service.get_audit_detail(audit_id)
    if not detail:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "field": "audit_id", "message": "Audit entry not found"},
        )
    return AuditDetailOut(**detail)


@router.get("/audit-logs/{audit_id}/diff", response_model=DiffOut)
async def get_audit_diff(
    audit_id: str,
    admin: bool = Depends(_require_admin),
    service: AuditService = Depends(_get_audit_service),
):
    """Get structured diff for an audit entry."""
    try:
        diff = await service.get_audit_diff(audit_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return DiffOut(**diff)


@router.post("/audit-logs/export", status_code=202, response_model=AuditExportOut)
async def request_audit_export(
    body: AuditExportRequest,
    admin: bool = Depends(_require_admin),
    service: AuditService = Depends(_get_audit_service),
):
    """Start an async audit export job."""
    job = await service.request_audit_export(
        format=body.format,
        course_id=body.course_id,
        user_id=body.user_id,
        operation=body.operation,
        outcome=body.outcome,
        date_from=body.date_from,
        date_to=body.date_to,
        fields=body.fields,
    )
    return AuditExportOut(**job)


# ── Safety Events ────────────────────────────────────────────────────────────

@router.get("/safety-events", response_model=SafetyEventListOut)
async def list_safety_events(
    event_type: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[str] = Query(None),
    admin: bool = Depends(_require_admin),
    service: AuditService = Depends(_get_audit_service),
):
    """List AI safety events with filtering."""
    items, total, next_cursor = await service.list_safety_events(
        event_type=event_type,
        severity=severity,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        cursor=cursor,
    )
    return SafetyEventListOut(
        items=[SafetyEventOut(**item) for item in items],
        total=total,
        nextCursor=next_cursor,
        hasMore=next_cursor is not None,
    )


# ── Compliance Routes ────────────────────────────────────────────────────────

@router.get("/compliance/summary", response_model=OperationsSummaryOut)
async def get_compliance_summary(
    date_from: Optional[datetime] = Query(
        default=None, description="Default: 30 days ago"
    ),
    date_to: Optional[datetime] = Query(default=None, description="Default: now"),
    admin: bool = Depends(_require_admin),
    service: AuditService = Depends(_get_audit_service),
):
    """Aggregate compliance metrics."""
    if date_from is None:
        date_from = datetime.utcnow() - timedelta(days=30)
    if date_to is None:
        date_to = datetime.utcnow()
    
    summary = await service.get_compliance_summary(
        date_from=date_from, date_to=date_to,
    )
    return OperationsSummaryOut(
        totalOperations=summary["total"],
        byOperation=summary["by_operation"],
        byOutcome=summary["by_outcome"],
        dateFrom=date_from.isoformat(),
        dateTo=date_to.isoformat(),
    )


@router.get("/compliance/user-activity")
async def get_user_activity(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    admin: bool = Depends(_require_admin),
    service: AuditService = Depends(_get_audit_service),
):
    """Per-user activity breakdown."""
    activities = await service.get_user_activity(
        date_from=date_from, date_to=date_to, limit=limit,
    )
    return {"users": [UserActivityOut(**a) for a in activities], "total": len(activities)}


@router.get("/compliance/model-performance")
async def get_model_performance(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    admin: bool = Depends(_require_admin),
    service: AuditService = Depends(_get_audit_service),
):
    """Model-level performance metrics."""
    models = await service.get_model_performance(
        date_from=date_from, date_to=date_to,
    )
    return {"models": [ModelPerformanceOut(**m) for m in models], "total": len(models)}


# ── Course Change History ────────────────────────────────────────────────────

@router.get("/courses/{course_id}/changes", response_model=CourseChangeHistoryOut)
async def get_course_changes(
    course_id: str,
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[str] = Query(None),
    admin: bool = Depends(_require_admin),
    service: AuditService = Depends(_get_audit_service),
):
    """Time-ordered change history for a course."""
    items, total, next_cursor = await service.get_course_changes(
        course_id=course_id, limit=limit, cursor=cursor,
    )
    return CourseChangeHistoryOut(
        courseId=course_id,
        changes=[AuditEntryOut(**item) for item in items],
    )


# ── Rollback Routes ──────────────────────────────────────────────────────────

@router.post("/rollback/propose", response_model=RollbackProposalOut)
async def propose_rollback(
    body: RollbackProposalRequest,
    admin: bool = Depends(_require_admin),
    service: AuditService = Depends(_get_audit_service),
):
    """Generate a rollback proposal from an audit entry."""
    try:
        result = await service.propose_rollback(
            audit_id=body.audit_id,
            reason=body.reason,
            user_id="admin",  # In production, extract from auth context
            session_id="admin-session",  # In production, from request context
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    
    return RollbackProposalOut(**result)
```

### 2.8 Alembic Migration

**File:** `alembic/versions/20260614_0001_add_ai_audit_tables.py`

```python
"""Add ai_audit_logs, ai_safety_events, and ai_usage_records tables.

Revision ID: 20260614_0001
Revises: <previous_migration_id>
Create Date: 2026-06-14
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260614_0001"
down_revision: Union[str, None] = "<previous_migration_id>"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ai_audit_logs table
    op.create_table(
        "ai_audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("audit_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=False, server_default="system"),
        sa.Column("organization_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False, server_default="success"),
        sa.Column("proposal_id", sa.String(64), nullable=True),
        sa.Column("course_id", sa.String(64), nullable=False),
        sa.Column("page_id", sa.String(64), nullable=True),
        sa.Column("outbox_event_id", sa.String(64), nullable=True),
        sa.Column("before_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("after_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("diff_patch", postgresql.JSONB(), nullable=True),
        sa.Column("validation_summary", postgresql.JSONB(), nullable=True),
        sa.Column("provenance", postgresql.JSONB(), nullable=True),
        sa.Column("rollback_of_audit_id", sa.String(64), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("audit_id"),
    )
    op.create_check_constraint(
        "ck_audit_operation",
        "ai_audit_logs",
        "operation IN ('page_created','page_updated','page_deleted',"
        "'course_created','course_updated','course_deleted',"
        "'batch_applied','rollback','proposal_rejected','proposal_expired','component_updated')",
    )
    op.create_check_constraint(
        "ck_audit_outcome",
        "ai_audit_logs",
        "outcome IN ('success','failure','rolled_back','conflict')",
    )
    
    # Indexes for ai_audit_logs
    op.create_index("idx_audit_audit_id", "ai_audit_logs", ["audit_id"])
    op.create_index("idx_audit_course_id", "ai_audit_logs", ["course_id"])
    op.create_index("idx_audit_user_id", "ai_audit_logs", ["user_id"])
    op.create_index("idx_audit_operation", "ai_audit_logs", ["operation"])
    op.create_index("idx_audit_outcome", "ai_audit_logs", ["outcome"])
    op.create_index("idx_audit_proposal_id", "ai_audit_logs", ["proposal_id"])
    op.create_index("idx_audit_session_id", "ai_audit_logs", ["session_id"])
    op.create_index("idx_audit_trace_id", "ai_audit_logs", ["trace_id"])
    op.create_index("idx_audit_created_at", "ai_audit_logs", [sa.text("created_at DESC")])
    op.create_index("idx_audit_rollback_of", "ai_audit_logs", ["rollback_of_audit_id"])
    op.create_index("idx_audit_course_created", "ai_audit_logs", ["course_id", sa.text("created_at DESC")])
    op.create_index("idx_audit_user_operation", "ai_audit_logs", ["user_id", "operation", sa.text("created_at DESC")])
    op.create_index("idx_audit_org_created", "ai_audit_logs", ["organization_id", sa.text("created_at DESC")])
    op.create_index("idx_audit_provenance", "ai_audit_logs", [postgresql.JSONB("provenance")], postgresql_using="gin")
    op.create_index("idx_audit_validation", "ai_audit_logs", [postgresql.JSONB("validation_summary")], postgresql_using="gin")

    # ai_safety_events table
    op.create_table(
        "ai_safety_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("user_id", sa.String(128), nullable=False, server_default="system"),
        sa.Column("organization_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("input_snippet", sa.Text(), nullable=True),
        sa.Column("output_snippet", sa.Text(), nullable=True),
        sa.Column("rule_triggered", sa.String(128), nullable=True),
        sa.Column("audit_id", sa.String(64), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_check_constraint(
        "ck_safety_event_type",
        "ai_safety_events",
        "event_type IN ('prompt_injection_blocked','pii_detected_and_redacted',"
        "'toxic_output_blocked','blocked_term_detected',"
        "'rate_limit_exceeded','policy_violation')",
    )
    op.create_check_constraint(
        "ck_safety_severity",
        "ai_safety_events",
        "severity IN ('low','medium','high','critical')",
    )
    op.create_index("idx_safety_event_id", "ai_safety_events", ["event_id"])
    op.create_index("idx_safety_type", "ai_safety_events", ["event_type"])
    op.create_index("idx_safety_severity", "ai_safety_events", ["severity"])
    op.create_index("idx_safety_created", "ai_safety_events", [sa.text("created_at DESC")])
    op.create_index("idx_safety_audit_id", "ai_safety_events", ["audit_id"])
    op.create_index("idx_safety_session_id", "ai_safety_events", ["session_id"])

    # ai_usage_records table (partitioned)
    op.execute("""
        CREATE TABLE ai_usage_records (
            id              BIGSERIAL,
            usage_id        VARCHAR(64) NOT NULL,
            session_id      VARCHAR(64),
            user_id         VARCHAR(128) NOT NULL,
            organization_id VARCHAR(64) NOT NULL DEFAULT 'default',
            model_id        VARCHAR(128) NOT NULL,
            provider        VARCHAR(64) NOT NULL,
            model_tier      VARCHAR(16),
            input_tokens    INTEGER NOT NULL DEFAULT 0,
            output_tokens   INTEGER NOT NULL DEFAULT 0,
            cost_usd        NUMERIC(12,6) NOT NULL DEFAULT 0,
            latency_ms      INTEGER,
            trace_id        VARCHAR(64) NOT NULL,
            operation       VARCHAR(32),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (created_at, id)
        ) PARTITION BY RANGE (created_at)
    """)


def downgrade() -> None:
    op.drop_table("ai_usage_records")
    op.drop_table("ai_safety_events")
    op.drop_table("ai_audit_logs")
```

### 2.9 Integration Points

#### Register the Router in `app/main.py`

```python
# Add to existing imports
from app.routers import ai_admin  # new

# Add to the api_router include block
api_router.include_router(ai_admin.router)
```

#### Register the ORM Models in `alembic/env.py`

```python
# Add to existing model imports near the top
import app.models.ai_audit  # noqa: F401
```

#### Register in `app/models/__init__.py`

```python
# Add to existing imports
from app.models.ai_audit import AIAuditLog, AISafetyEvent

# Add to __all__
__all__ += ["AIAuditLog", "AISafetyEvent"]
```

### 2.10 Environment Variables

```bash
# ── AI Audit & Compliance Configuration ──────────────────────────────────────

# Audit log retention period in days. Records older than this may be archived.
AI_AUDIT_RETENTION_DAYS=365

# Safety event retention period in days.
AI_SAFETY_EVENT_RETENTION_DAYS=730

# Rollback proposal TTL in minutes. Rollback proposals expire after this.
AI_ROLLBACK_PROPOSAL_TTL_MINUTES=1440  # 24 hours

# Admin export directory — where generated audit export files are stored.
# Must be an absolute path readable by the application process.
AI_ADMIN_EXPORT_DIR=/var/data/ai-admin-exports

# Max rows for synchronous audit export. Exports exceeding this use
# background async processing.
AI_AUDIT_EXPORT_SYNC_MAX_ROWS=1000

# Feature flag: enable/disable admin audit and compliance endpoints.
# When disabled, all /api/v1/ai/admin/* routes return 404.
FEATURE_AI_ADMIN_AUDIT=true

# Feature flag: enable/disable rollback capability (separate from read-only audit).
FEATURE_AI_ROLLBACK=true
```

---

## 3. Non-Functional Requirements

### 3.1 Performance

| Requirement | Target | Measurement |
|---|---|---|
| Audit log query p95 latency | < 500ms for filtered queries within 100k rows | Application metrics / Datadog |
| Audit detail fetch p95 latency | < 200ms | Application metrics |
| Rollback proposal dry-run generation p95 | < 2s | Application metrics |
| Compliance summary aggregation p95 | < 3s for 30-day window | Application metrics |
| Audit export (sync) p95 | < 5s for up to 1000 rows | Application metrics |
| Concurrent admin users supported | 10 simultaneous | Load test |

### 3.2 Security

| Requirement | Implementation |
|---|---|
| Admin-only access | All audit/compliance endpoints require admin role authorization |
| PII redaction | `before_snapshot` and `after_snapshot` must be redacted of PII before storage. Safety events store only sanitized snippets |
| Audit immutability | Audit records are INSERT-only. No UPDATE or DELETE on `ai_audit_logs` is permitted at the application level |
| Export access control | Generated export files inherit the admin authorization of the requesting user |
| Data minimization | Audit export `fields` parameter allows selecting only needed columns |

### 3.3 Data Retention

| Data | Retention | Action |
|---|---|---|
| ai_audit_logs | 365 days | Archive to cold storage, then purge |
| ai_safety_events | 730 days | Archive to cold storage, then purge |
| ai_usage_records | 90 days | Drop old partitions |
| Audit export files | 48 hours | Delete after expiry |

### 3.4 Availability

| Requirement | Target |
|---|---|
| Audit query availability | Same as core API (99.9%) |
| Degraded mode | If audit DB is unreachable, core AI operations continue (audit writes are buffered or fail gracefully) |

### 3.5 Observability

- Every audit query logs its filter parameters, result count, and latency
- Export job progress emits events for monitoring
- Rollback proposal creation logs the audit ID, conflict details, and outcome
- All admin endpoints emit metrics: `ai_admin.audit.query.count`, `ai_admin.rollback.proposed`, `ai_admin.export.started`

---

## 4. Current State Assessment

### 4.1 What Exists

The codebase at `C:\Users\ADMIN\e-learning-backend` currently has:

1. **No AI audit tables exist.** The models in `app/models/` cover courses, pages, components, templates, themes, scoring, interaction events, branching, and social features — but no `ai_audit_logs`, `ai_safety_events`, or `ai_usage_records` tables.

2. **No AI admin routes exist.** The routers in `app/routers/` include `analytics.py` (learner-facing reporting), `courses.py`, `export.py`, and others — but no `ai_admin.py`.

3. **Existing analytics pattern** in `app/routers/analytics.py` provides a reference for read-only reporting endpoints using `Depends(get_session)` and `GET` routes. The audit service will follow a similar pattern.

4. **Existing error envelope** in `app/utils/error_envelope.py` defines `build_error()` and `api_http_exception()` — the audit router will reuse these.

5. **Existing feature flag system** in `app/utils/feature_flags.py` — new flags `FEATURE_AI_ADMIN_AUDIT` and `FEATURE_AI_ROLLBACK` will be added here.

6. **Structured error responses** in `app/utils/error_responses.py` define the `validation_error()` helper — the audit router will use the same shape.

7. **The analytics router** at `app/routers/analytics.py` has the closest pattern to what audit needs:
   - Uses repository pattern via `PageRepository`, `ScoringRepository`, `InteractionEventRepository`
   - Returns structured responses with `generatedAt` timestamps
   - Filters by `courseId` and `learnerId`
   - Handles `courseId` not found with 404

### 4.2 What Needs to Be Built

| Component | Description | Reference Pattern |
|---|---|---|
| `app/models/ai_audit.py` | ORM models for audit, safety, usage tables | `app/models/interaction_event.py` |
| `app/models/ai_audit_dto.py` | Pydantic DTOs for all admin API surfaces | `app/models/course.py` for DTO patterns |
| `app/repositories/ai_audit_repo.py` | Repository with filtered queries, cursor pagination | `app/repositories/interaction_event_repo.py` |
| `app/services/ai/audit_service.py` | Business logic: queries, rollback proposal, compliance aggregation | `app/services/export_data_builder.py` |
| `app/routers/ai_admin.py` | REST API for audit, compliance, recovery | `app/routers/analytics.py` |
| Alembic migration | Add `ai_audit_logs`, `ai_safety_events`, `ai_usage_records` | `alembic/versions/20260412_0003_add_export_columns_and_tables.py` |
| Tests | API tests, repository tests, service unit tests | `tests/test_analytics.py`, `tests/test_export.py` |

### 4.3 Key Assumptions

- The `ai_audit_logs` table is written by the apply safety service (US-AI-010) — US-AI-020 only provides read/query/recovery on top of it
- Admin authorization middleware exists or will be created as a shared dependency
- The existing Postgres JSONB type is used for flexible snapshot storage
- Cursor-based pagination follows the `(id, created_at)` composite key pattern for stability

---

## 5. Expansion Points

### 5.1 Phase 2: Enhanced Compliance

- **Audit log archiving to S3/GCS** for retention beyond 365 days with queryable manifests
- **Audit log signing** with SHA-256 hash chains for legal admissibility (immutable audit trail)
- **GDPR data subject access request (DSAR)** endpoint: export all audit entries for a given user ID
- **Compliance rule engine**: custom rules (e.g., "warn when any admin performs more than 10 rollbacks/day")

### 5.2 Phase 3: Automated Recovery

- **Scheduled rollback windows**: configure auto-rollback for failed batch operations within a time window
- **Point-in-time course restore**: restore a course to its state at any past timestamp using audit snapshots
- **Change impact analysis**: given an audit entry, analyze what downstream effects (export, SCORM) the change had

### 5.3 Phase 4: Federated Audit

- **Multi-region audit aggregation**: aggregate audit logs across regional deployments
- **SIEM integration**: forward audit and safety events to Splunk, Datadog, or Elastic via structured webhooks
- **Audit event schema registry**: versioned Avro/Protobuf schemas for audit events published to Kafka

---

## 6. Validation Strategy

### 6.1 Unit Tests

**File:** `tests/unit/ai/test_audit_repo.py`

| Test | Scenario | Expected |
|---|---|---|
| `test_list_empty` | No audit entries match filters | Returns empty list, total=0 |
| `test_list_single_filter` | Filter by course_id | Returns only matching entries |
| `test_list_multi_filter` | Filter by course_id AND operation | Returns intersection |
| `test_list_cursor_pagination` | First page with 5 items, cursor for next page | Returns 5 items, hasMore=true, nextCursor non-null |
| `test_list_last_page` | Cursor from last page | Returns fewer than limit, hasMore=false, nextCursor=null |
| `test_list_search_summary` | Search term matches summary substring | Returns matching entries |
| `test_cursor_encode_decode_roundtrip` | Encode then decode | Returns original (id, created_at) |
| `test_cursor_decode_invalid` | Malformed cursor string | Raises ValueError |
| `test_create_audit_entry` | Create a valid audit record | Returns audit_id, fields match input |
| `test_get_by_audit_id_exists` | Existing audit_id | Returns record |
| `test_get_by_audit_id_missing` | Non-existent audit_id | Returns None |

**File:** `tests/unit/ai/test_audit_service.py`

| Test | Scenario | Expected |
|---|---|---|
| `test_propose_rollback_success` | Valid audit entry, no conflicts | Returns proposal with dryRunResult.valid=true |
| `test_propose_rollback_not_found` | Invalid audit_id | Raises AuditEntryNotFoundError |
| `test_propose_rollback_already_proposed` | Rollback already exists for this entry | Raises RuntimeError with existing proposal ID |
| `test_propose_rollback_conflict` | Page modified since mutation | Raises RollbackConflictError with details |
| `test_get_audit_diff_deleted_page` | Page was deleted after mutation | Returns diff with pageExists=false, beforeSnapshot still present |
| `test_get_compliance_summary_empty` | No operations in date range | Returns zeros for all metrics |
| `test_get_user_activity_ordering` | Multiple users | Sorted by proposal count descending |
| `test_create_safety_event` | Valid safety event params | Returns event_id, all fields preserved |

### 6.2 API Integration Tests

**File:** `tests/integration/ai/test_admin_audit_api.py`

| Test | Scenario | HTTP | Expected |
|---|---|---|---|
| `test_list_audit_logs_no_auth` | No admin auth header | GET | 403 or empty response |
| `test_list_audit_logs_empty` | No filters, no audit entries | GET | 200, items=[], total=0 |
| `test_list_audit_logs_with_data` | Seed 5 entries, list all | GET | 200, total=5 |
| `test_list_audit_logs_filter_course` | Filter by course_id | GET | 200, results limited to course |
| `test_list_audit_logs_pagination` | Seed 150 entries, page size 50 | GET | 200, items=50, hasMore=true on page 1, hasMore=false on page 3 |
| `test_get_audit_detail` | Known audit_id | GET | 200, full detail with snapshots |
| `test_get_audit_detail_not_found` | Non-existent audit_id | GET | 404 |
| `test_get_audit_diff` | Known audit_id | GET | 200, diff fields populated |
| `test_propose_rollback` | Valid audit entry | POST | 200, proposalId returned |
| `test_propose_rollback_not_found` | Invalid audit_id | POST | 404 |
| `test_compliance_summary` | No filters | GET | 200, aggregated metrics |
| `test_safety_events_list` | Seed 3 safety events | GET | 200, total=3 |
| `test_audit_export_sync` | < 1000 rows, JSON format | POST | 202, job status=completed |
| `test_admin_routes_disabled_no_flag` | FEATURE_AI_ADMIN_AUDIT=false | GET | 404 |

### 6.3 Security Tests

| Test | Scenario | Expected |
|---|---|---|
| `test_non_admin_cannot_query_audit` | Regular user (no admin role) | 403 Forbidden |
| `test_audit_logs_no_pii_in_response` | Verify response JSON has no PII patterns | No emails, phones, credentials in output |
| `test_rollback_cannot_target_other_tenant` | Org A admin tries to rollback Org B audit entry | 404 or 403 |
| `test_export_download_auth_required` | Export download URL accessed without auth | 403 |

### 6.4 Performance Tests

| Test | Scenario | Expected |
|---|---|---|
| `test_audit_query_100k_rows` | Query across 100k audit entries with filter | p95 < 500ms |
| `test_compliance_aggregation_large` | Aggregate 30 days of data with 50k entries | p95 < 3s |
| `test_concurrent_admin_queries` | 10 simultaneous admin queries | No connection pool exhaustion |

---

## 7. Definition of Done

### 7.1 Acceptance Criteria

1. Every applied AI mutation produces a queryable audit record within the same transaction
2. Audit logs can be filtered by: course, user, operation, outcome, proposal, model, date range, and free-text search
3. Cursor-based pagination works correctly across all list endpoints
4. Admin can view full detail (before/after snapshots, provenance, diff) for any audit entry
5. Admin can request a rollback proposal from any audit entry; rollback follows standard proposal lifecycle
6. Dry-run rollback detects and reports conflicts with current state
7. Compliance summary aggregates operations by type and outcome over a configurable date range
8. Safety events are queryable separately with type and severity filters
9. Audit export (CSV/JSON) supports field selection and async generation for large result sets
10. All admin endpoints return 404 when `FEATURE_AI_ADMIN_AUDIT=false`
11. Rollback endpoints return 404 when `FEATURE_AI_ROLLBACK=false`
12. Non-admin users receive 403 on all admin endpoints
13. Alembic migration is reversible (`downgrade` drops all three tables)
14. Existing test suite passes with no regressions

### 7.2 Quality Gates

- [ ] All unit tests pass (coverage > 85% for new code)
- [ ] All API integration tests pass
- [ ] `FEATURE_AI_ADMIN_AUDIT=false` hides all admin routes
- [ ] `FEATURE_AI_ROLLBACK=false` hides rollback-specific routes
- [ ] OpenAPI spec renders correctly with new route tags "AI Admin"
- [ ] Flake8/Pylint passes with no new issues
- [ ] Type annotations present on all new function signatures
- [ ] Migration tested both `upgrade()` and `downgrade()`
- [ ] Performance benchmark meets p95 targets
- [ ] Security review: no PII exposure in audit responses

### 7.3 Signoff Checklist

| Role | Signoff Criteria |
|---|---|
| Product Owner | Acceptance criteria met, demo shows all FRs working |
| Security Lead | No PII exposure, admin access control verified |
| QA Lead | All test levels pass, performance benchmarks met |
| Operations | Migration script tested, env vars documented |
| Tech Lead | Code review clean, architecture documented |

---

## 8. Task Breakdown

### Task Group A: Foundation (5 SP)

**A-1: Create ORM Models and Alembic Migration** (2 SP)
- Files: `app/models/ai_audit.py`, `alembic/versions/20260614_0001_add_ai_audit_tables.py`
- Details:
  - Implement `AIAuditLog` model with all columns from section 2.1.1
  - Implement `AISafetyEvent` model with all columns from section 2.1.2
  - Register models in `app/models/__init__.py`
  - Register model import in `alembic/env.py`
  - Generate and test the Alembic migration (both upgrade and downgrade)
  - Verify `Base.metadata.create_all` picks up the new tables

**A-2: Create Pydantic DTOs** (1 SP)
- File: `app/models/ai_audit_dto.py`
- Details:
  - Implement all request/response DTOs from section 2.3
  - Validate field constraints, descriptions, and type annotations

**A-3: Create Audit Repository** (2 SP)
- File: `app/repositories/ai_audit_repo.py`
- Details:
  - Implement `list_with_filters()` with cursor pagination
  - Implement `get_by_audit_id()`
  - Implement `create()` for audit rows
  - Implement `encode_cursor()` / `decode_cursor()` static methods
  - Implement `get_usage_stats()` for aggregation
  - Unit test: all repo methods with mocked session

### Task Group B: Audit Read API (5 SP)

**B-1: Create Audit Service** (3 SP)
- File: `app/services/ai/audit_service.py`
- Details:
  - Implement `list_audit_logs()` with all filter parameters
  - Implement `get_audit_detail()` 
  - Implement `get_audit_diff()` with JSON Patch generation
  - Implement `create_audit_entry()` 
  - Implement `create_safety_event()`
  - Implement `get_compliance_summary()` with aggregation
  - Implement `get_user_activity()` with per-user breakdown
  - Implement `get_model_performance()` from usage records
  - Implement `get_course_changes()` filtered by course
  - Implement `list_safety_events()`
  - Implement `request_audit_export()` with sync/async split

**B-2: Create Admin Router** (2 SP)
- File: `app/routers/ai_admin.py`
- Details:
  - Implement all audit log endpoints (list, detail, diff)
  - Implement safety events list endpoint
  - Implement compliance summary, user activity, model performance
  - Implement course change history endpoint
  - Add admin authorization dependency injection
  - Register router in `app/main.py`
  - Add feature flag gating
  - Integration test: all endpoints with seeded data

### Task Group C: Recovery and Rollback (5 SP)

**C-1: Implement Rollback Proposal Service** (3 SP)
- Update: `app/services/ai/audit_service.py`
- Details:
  - Implement `propose_rollback()` with conflict detection
  - Implement dry-run validation against current course/page state
  - Integrate with existing `ai_proposals` table (from US-AI-004)
  - Handle rollback chain: rollback of a rollback
  - Handle edge cases: deleted page, modified page, missing course

**C-2: Implement Rollback Router Endpoints** (1 SP)
- Update: `app/routers/ai_admin.py`
- Details:
  - Implement `POST /rollback/propose`
  - Feature flag gating for rollback
  - Error responses: 404 (not found), 409 (already proposed), 422 (conflict)

**C-3: Implement Audit Export** (1 SP)
- Update: `app/services/ai/audit_service.py` + `app/routers/ai_admin.py`
- Details:
  - Implement async export job creation endpoint
  - Implement export job poll endpoint
  - Implement export file download endpoint with expiry
  - CSV and JSON serialization with field selection

### Task Group D: Configuration and Integration (3 SP)

**D-1: Feature Flags and Configuration** (1 SP)
- Files: `app/utils/feature_flags.py`, `.env.example`
- Details:
  - Add `FEATURE_AI_ADMIN_AUDIT` flag
  - Add `FEATURE_AI_ROLLBACK` flag
  - Add env vars from section 2.10 to `.env.example`
  - Wire feature flags into router registration

**D-2: Admin Authorization Dependency** (1 SP)
- File: `app/services/ai/admin_auth.py` (new)
- Details:
  - Implement `require_admin_role()` dependency
  - Extract user ID, organization ID from request context
  - For MVP: check against a configured admin user list or role header
  - For production: integrate with identity provider (JWT claims)

**D-3: Integrate Audit Writing into Apply Service** (1 SP)
- Requires coordination with US-AI-010
- Details:
  - Add `AuditService.create_audit_entry()` call inside the apply transaction
  - Ensure before_snapshot is captured before mutation
  - Ensure after_snapshot is captured after mutation
  - Ensure the audit write is in the same DB transaction as the mutation
  - Add `trace_id` propagation from chat/session through to audit

### Task Group E: Testing (5 SP)

**E-1: Unit Tests** (2 SP)
- Files: `tests/unit/ai/test_audit_repo.py`, `tests/unit/ai/test_audit_service.py`
- Details:
  - Mock SQLAlchemy session for repository tests
  - Test all filter combinations, pagination, edge cases
  - Test rollback proposal service with mocked data
  - Test compliance aggregation logic

**E-2: Integration Tests** (2 SP)
- File: `tests/integration/ai/test_admin_audit_api.py`
- Details:
  - Seed test database with audit entries, safety events, usage records
  - Test all endpoints with real HTTP client
  - Test pagination across result pages
  - Test rollback proposal generation and conflict detection
  - Test feature flag gating
  - Test authorization enforcement

**E-3: Performance Benchmark** (1 SP)
- File: `tests/performance/test_audit_query_perf.py`
- Details:
  - Seed 100k audit entries across various courses, users, operations
  - Run filtered queries and measure p50/p95/p99 latency
  - Run compliance aggregation and measure latency
  - Verify index usage (EXPLAIN ANALYZE)

### Task Group F: Documentation (2 SP)

**F-1: API Documentation** (1 SP)
- Details:
  - Verify OpenAPI spec renders all new routes with correct schemas
  - Add route summaries and descriptions matching section 2.4
  - Document admin authorization requirements

**F-2: Operations Runbook** (1 SP)
- Details:
  - Document retention configuration
  - Document manual export process
  - Document rollback procedure with screenshots
  - Document troubleshooting: missing audit entries, export failures
  - Document monitoring and alerting for audit system health

---

### Summary: Total Effort Estimate

| Task Group | Story Points | Dependencies |
|---|---|---|
| A: Foundation | 5 | US-AI-004 (tables exist for sessions/proposals) |
| B: Audit Read API | 5 | A completed |
| C: Recovery & Rollback | 5 | B completed, US-AI-009 (proposal lifecycle) |
| D: Configuration | 3 | US-AI-002 (feature flags) |
| E: Testing | 5 | A-D completed |
| F: Documentation | 2 | E completed |
| **Total** | **25 SP** | |

### Dependencies on Other Stories

| Story | Dependency | Notes |
|---|---|---|
| US-AI-004 | Required | `ai_proposals` table must exist for rollback proposals |
| US-AI-010 | Required | Audit writing hook integrated into apply transaction |
| US-AI-009 | Required | Proposal lifecycle states (pending/expired/applied) for rollback |
| US-AI-002 | Required | Feature flags infra for `FEATURE_AI_ADMIN_AUDIT` |
| US-AI-025 | Required | `ai_safety_events` populated by guard services |
| US-AI-031 | Optional | Provenance metadata enriches audit records |
| US-AI-040 | Related | Rollback is the first step toward full versioning |
