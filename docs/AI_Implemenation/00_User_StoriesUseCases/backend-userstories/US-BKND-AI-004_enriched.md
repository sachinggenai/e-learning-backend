# US-BKND-AI-004 -- Add AI Persistence Foundations

**Priority:** MUST  
**Depends on:** US-BKND-AI-003 (Isolated AI API Module)  
**Unlocks:** US-BKND-AI-006 (AI Session Creation), US-BKND-AI-009 (Generic Proposal Lifecycle), US-BKND-AI-010 (Apply Safety, Audit, Outbox), US-BKND-AI-016 (File Upload/Ingestion Job Foundation)  
**Source flows:** 1 (AI Session Creation), 3 (Create Page Proposal and Apply), 4 (Update Page Proposal and Apply), 5 (Delete Page Proposal and Confirm), 8 (File Ingestion/Document Import), 9 (Simple Chat Edit), 10 (Full Course from Uploaded File), 11 (Destructive Delete), 12 (Propose/Validate/Confirm/Apply Safety)  
**Story:** As the System, I need durable records for sessions, proposals, confirmations, audit entries, and outbox events, so that AI workflows are recoverable, traceable, and compliant.

---

## 1. FUNCTIONAL SPECIFICATION

### 1.1 Detailed User Story

The AI authoring system requires its own persistence layer separate from existing course/page/component tables. This foundation stores:

- **AI Sessions** -- scoped to one user, one organization, one course. Sessions have expiry and an immutable course scope. All tool calls and chat turns are associated with a session.
- **AI Proposals** -- every AI mutation (create, update, delete page) creates a proposal record before any database mutation. Proposals have lifecycle states (pending, approved, applied, rejected, expired, failed). A proposal cannot be applied twice. Proposals carry base_hash for staleness detection, before/after snapshots, and validation results.
- **Confirmation Tokens** -- destructive operations (delete page, batch replacement) require a separate confirmation token bound to the proposal, session, and user. Tokens carry their own expiry.
- **Audit Logs** -- every applied AI mutation writes an audit record with user_id, session_id, tool_name, operation, before_state, after_state, diff, result_status, error_code, ip_address, user_agent, and model metadata.
- **Outbox Events** -- every applied mutation also writes an outbox event in the same database transaction for downstream consumers (search indexing, analytics, notification).

### 1.2 Numbered Functional Requirements

1. **FR-001 -- AI Session Persistence:** The system MUST persist AI session records with fields for session_id (UUID), user_id, course_id, organization_id, created_at, expires_at, status (active/expired/revoked), and context_summary (optional JSON). Sessions MUST reject tool calls when expired or if the course_id does not match.

2. **FR-002 -- Session Scope Immutability:** Once created, the session's course_id MUST be immutable. Any tool call attempting to operate on a different course_id MUST be rejected with a PERMISSION_DENIED error.

3. **FR-003 -- Session Expiry Enforcement:** Sessions MUST have a configurable TTL (default 24 hours). Expired sessions MUST reject all tool calls. An expired session MUST NOT be re-activated; users MUST create a new session.

4. **FR-004 -- Proposal Lifecycle Records:** The system MUST persist proposal records with fields for proposal_id (UUID), session_id, operation (create/update/delete), resource_type (page/course/component), resource_id, before_snapshot (JSON), after_candidate (JSON), diff (JSON), validation_result (JSON), status (PENDING_REVIEW/APPROVED/APPLIED/REJECTED/EXPIRED/FAILED), base_hash, applied_at, and expires_at.

5. **FR-005 -- One-Time Apply Enforcement:** A proposal with status APPLIED MUST reject any further apply attempts. A proposal with status REJECTED or EXPIRED MUST reject apply attempts. The system MUST return an error indicating the proposal is no longer usable.

6. **FR-006 -- Staleness Detection via Base Hash:** Proposals MUST store a base_hash computed from the current database state of the resource before the proposal was created. On apply, the system MUST recompute the current hash and compare it to the base_hash. If they differ, the apply MUST fail with a 409 CONFLICT error, indicating the resource was modified by another operation since the proposal was created.

7. **FR-007 -- Confirmation Token Persistence:** The system MUST persist confirmation tokens for destructive operations. Tokens MUST be bound to a proposal_id, session_id, and user_id. Tokens MUST have their own expiry (default 15 minutes). A token can be consumed only once.

8. **FR-008 -- Audit Log Entry Creation:** Every successful or failed apply operation MUST write an audit log entry containing user_id, session_id, proposal_id, tool_name, operation, resource_id, before_state (JSON), after_state (JSON), diff (JSON), result_status, error_code (nullable), model_id, prompt_version, ip_address, user_agent, and created_at.

9. **FR-009 -- Outbox Event Writing:** Every successful mutation apply MUST write an outbox event in the SAME database transaction. The outbox event MUST include event_type, event_version, aggregate_id (the resource ID), payload (JSON), trace_id, occurred_at, and published_at (nullable). Supported event types: PageCreatedByAI, PageUpdatedByAI, PageDeletedByAI, SessionCreated, CourseCreatedFromFile, BatchProposalApplied.

10. **FR-010 -- Transactional Integrity:** The apply flow MUST use a single database transaction that atomically: (a) updates the proposal status to APPLIED, (b) performs the domain mutation (e.g., creates the page), (c) writes the audit log entry, (d) writes the outbox event. If any step fails, the entire transaction MUST roll back.

11. **FR-011 -- Idempotency Support:** The apply endpoint MUST support idempotency keys. If the same idempotency key is presented twice, the system MUST return the result of the first operation without re-executing. Idempotency keys MUST be stored with a TTL of 24 hours.

12. **FR-012 -- Chat Turn Persistence:** Each turn in an AI chat conversation MUST be persisted with fields for turn_id (UUID), session_id, user_prompt, assistant_response, model_used, tool_calls_made (JSON), tool_results_summary (JSON), total_tokens, created_at. This enables audit, debugging, and context window recovery.

### 1.3 Step-by-Step User Flow

#### Happy Path: AI Session Creation and Tool Call

```
1. User opens AI chat panel on course "Introduction to Python" (course_id = C-123)
2. Frontend calls POST /api/v1/ai/sessions with { userId: "U-456", courseId: "C-123", organizationId: "ORG-789" }
3. Backend validates user exists, has access to course C-123, belongs to organization ORG-789
4. Backend creates ai_sessions record:
   - session_id = "SESS-UUID-1"
   - user_id = "U-456"
   - course_id = "C-123"
   - organization_id = "ORG-789"
   - created_at = now
   - expires_at = now + 24 hours
   - status = "active"
5. Backend returns { sessionId, courseId, userId, createdAt, expiresAt }
6. Frontend stores sessionId in sessionStorage
7. User says "Add an intro page about variables"
8. Frontend calls POST /api/v1/ai/tools/propose_create_page with session header + payload
9. Backend validates session is active and not expired
10. Backend creates ai_proposals record:
    - proposal_id = "PROP-UUID-2"
    - session_id = "SESS-UUID-1"
    - operation = "create"
    - resource_type = "page"
    - resource_id = null (not yet created)
    - before_snapshot = null (new resource)
    - after_candidate = { title: "Introduction to Variables", templateType: "text-content", ... }
    - validation_result = { status: "valid", messages: [] }
    - status = "PENDING_REVIEW"
    - base_hash = null (new resource)
    - expires_at = now + 1 hour
11. Backend returns proposalId, preview, validationStatus to frontend
12. User reviews and clicks "Apply"
13. Frontend calls POST /api/v1/ai/tools/apply_page_proposal with { proposalId, userConfirmed: true, idempotencyKey: "IDEM-001" }
14. Backend validates proposal exists, is PENDING_REVIEW, not expired, belongs to session
15. Backend opens database transaction:
    a. Updates proposal status to "APPLIED", sets applied_at = now
    b. Creates page in pages table (via PageRepository)
    c. Writes audit_log entry
    d. Writes outbox event (event_type = "PageCreatedByAI")
16. Transaction commits
17. Backend returns { pageId, status: "created", message: "Success" }
```

#### Alternate Path: Proposal Stale (409 Conflict)

```
1-12: Same as happy path
13. Another user (or same user in another tab) modifies the same page in the manual editor
14. User clicks "Apply" in the AI chat
15. Backend computes current hash of the resource, compares to base_hash
16. base_hash != current_hash --> STALE DETECTED
17. Backend returns HTTP 409 with:
    {
      "code": "STALE_PROPOSAL",
      "message": "The resource has been modified since this proposal was created. Please re-fetch and create a new proposal.",
      "details": { "proposalId": "PROP-UUID-2", "currentHash": "...", "baseHash": "..." }
    }
18. Proposal status remains PENDING_REVIEW (or can be updated to STALE)
19. Frontend shows "Content has changed. Please review and try again."
20. AI must re-fetch current state and create a fresh proposal
```

#### Error Path: Expired Session

```
1. User opens AI chat after 25 hours of inactivity
2. Frontend calls POST /api/v1/ai/tools/list_pages with session header
3. Backend validates session: found but expires_at < now
4. Backend returns HTTP 401 with:
    {
      "code": "SESSION_EXPIRED",
      "message": "AI session has expired. Please create a new session.",
      "details": { "sessionId": "SESS-UUID-1", "expiredAt": "2026-06-15T10:00:00Z" }
    }
5. Frontend clears sessionStorage, shows "Session expired" toast, redirects to re-create session
```

#### Error Path: Proposal Double-Apply

```
1-15: Same as happy path (first apply succeeds)
16. Network retry causes second call with same idempotencyKey
17. Backend finds existing idempotency key record, returns cached response:
    { pageId: "PAGE-UUID-3", status: "created", message: "Already applied (idempotent)" }
18. No duplicate page created
```

#### Error Path: Confirmation Token Required for Delete

```
1. User says "Delete the quiz page"
2. AI calls propose_delete_page(sessionId, pageId)
3. Backend creates proposal with status=PENDING_REVIEW, operation="delete"
4. Backend also creates a confirmation token:
   - token_id = "TOKEN-UUID-4"
   - proposal_id = "PROP-UUID-5"
   - session_id = "SESS-UUID-1"
   - user_id = "U-456"
   - expires_at = now + 15 minutes
   - consumed = false
5. Frontend shows destructive confirmation modal with page title
6. User clicks "Confirm Delete"
7. Frontend calls confirm_delete_page(proposalId, userApprovedDelete: true)
8. Backend: validates token exists, not expired, not consumed
9. Backend marks token as consumed = true
10. Backend proceeds with transactional apply (proposal update + delete + audit + outbox)
```

### 1.4 UI/UX Requirements

- **Session Status Indicator:** Frontend should display a "Session Active" indicator with remaining TTL. When within 30 minutes of expiry, show a warning. When expired, grey out the AI panel.
- **Proposal Review Diff:** Frontend should render proposal diffs showing before/after comparison with highlighted changed fields.
- **Destructive Confirmation Modal:** Must require explicit action (e.g., typing "DELETE" into a text field) for destructive operations. The modal must show the page title, warning icon, and "This action cannot be undone" text.
- **Error Toasts:** Stale proposal errors should show "Content has changed. Refreshing..." with an automatic re-fetch of current state.
- **Expired Session Toast:** Show a non-dismissible toast "Your AI session has expired. Click here to start a new session." with a single-action button.

---

## 2. TECHNICAL SPECIFICATION

### 2.1 API Contracts

All new endpoints are located under `/api/v1/ai/`.

#### 2.1.1 POST /api/v1/ai/sessions -- Create AI Session

**Headers:**
```
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json
```

**Request Body:**
```json
{
  "userId": "string (UUID, required)",
  "courseId": "string (UUID, required)",
  "organizationId": "string (UUID, required)"
}
```

**Response Body (201 Created):**
```json
{
  "sessionId": "string (UUID)",
  "userId": "string (UUID)",
  "courseId": "string (UUID)",
  "organizationId": "string (UUID)",
  "createdAt": "string (ISO-8601 datetime)",
  "expiresAt": "string (ISO-8601 datetime)",
  "status": "active"
}
```

**Response Body (409 Conflict):**
```json
{
  "code": "SESSION_ALREADY_EXISTS",
  "message": "An active session already exists for this user and course.",
  "details": {
    "existingSessionId": "string (UUID)",
    "expiresAt": "string (ISO-8601)"
  }
}
```

**HTTP Status Codes:**
| Code | Condition |
|------|-----------|
| 201 | Session created successfully |
| 400 | Missing required fields, invalid UUID format |
| 401 | Missing or invalid JWT |
| 403 | User does not have access to the specified course/org |
| 404 | Course or organization not found |
| 409 | Active session already exists for this user+course combination |
| 422 | Request body fails validation |
| 500 | Server error |

#### 2.1.2 GET /api/v1/ai/sessions/{sessionId} -- Get Session

**Headers:**
```
Authorization: Bearer <JWT_TOKEN>
```

**Response Body (200):**
```json
{
  "sessionId": "string (UUID)",
  "userId": "string (UUID)",
  "courseId": "string (UUID)",
  "organizationId": "string (UUID)",
  "createdAt": "string (ISO-8601)",
  "expiresAt": "string (ISO-8601)",
  "status": "active|expired|revoked",
  "contextSummary": { "activeProposalIds": ["..."], "lastFocusedPageId": "..." }
}
```

**HTTP Status Codes:**
| Code | Condition |
|------|-----------|
| 200 | Session found and returned |
| 401 | Missing or invalid JWT |
| 404 | Session not found |
| 403 | Session belongs to a different user |

#### 2.1.3 DELETE /api/v1/ai/sessions/{sessionId} -- Revoke Session

**Headers:**
```
Authorization: Bearer <JWT_TOKEN>
```

**Response Body (200):**
```json
{
  "sessionId": "string (UUID)",
  "status": "revoked"
}
```

**HTTP Status Codes:**
| Code | Condition |
|------|-----------|
| 200 | Session revoked successfully |
| 401 | Missing or invalid JWT |
| 403 | Session belongs to a different user |
| 404 | Session not found |

#### 2.1.4 Internal Model: `ai_proposals` table (no direct API -- used by tool endpoints)

The proposal create/read/update flows are achieved through the tool endpoints defined in US-BKND-AI-009. The persistence layer must expose a repository that backing those tools.

#### 2.1.5 Internal Model: `ai_audit_logs` table (read-only query API)

**GET /api/v1/ai/audit-logs?userId=&courseId=&operation=&from=&to=&page=&perPage=**

**Headers:**
```
Authorization: Bearer <JWT_TOKEN>
```

**Response Body (200):**
```json
{
  "items": [
    {
      "auditId": "string (UUID)",
      "userId": "string (UUID)",
      "sessionId": "string (UUID)",
      "proposalId": "string (UUID)",
      "toolName": "string",
      "operation": "create|update|delete",
      "resourceId": "string",
      "resultStatus": "success|error",
      "errorCode": "string|null",
      "modelId": "string",
      "promptVersion": "string",
      "createdAt": "string (ISO-8601)"
    }
  ],
  "total": 123,
  "page": 1,
  "perPage": 50
}
```

Note: `before_state`, `after_state`, and `diff` are excluded from list view. A GET by single audit ID returns the full record including state snapshots.

**HTTP Status Codes:**
| Code | Condition |
|------|-----------|
| 200 | Audit logs returned |
| 401 | Missing or invalid JWT |
| 403 | Non-admin user lacks permission to view audit logs (future: scope to own logs for non-admins) |

### 2.2 Database Schema DDL

All tables follow the existing codebase pattern: auto-increment integer primary key, UUID-based external identifiers, camelCase JSON field mapping, and standard timestamps.

```sql
-- ============================================================
-- Table: ai_sessions
-- ============================================================
CREATE TABLE ai_sessions (
    id              SERIAL PRIMARY KEY,
    session_id      VARCHAR(64) NOT NULL UNIQUE,
    user_id         VARCHAR(64) NOT NULL,
    course_id       VARCHAR(64) NOT NULL,
    organization_id VARCHAR(64) NOT NULL,
    status          VARCHAR(32) NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'expired', 'revoked')),
    context_summary JSONB,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMP WITH TIME ZONE NOT NULL,
    revoked_at      TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_ai_sessions_user_course ON ai_sessions (user_id, course_id)
    WHERE status = 'active';
CREATE INDEX idx_ai_sessions_expires ON ai_sessions (expires_at)
    WHERE status = 'active';
CREATE INDEX idx_ai_sessions_course ON ai_sessions (course_id);
CREATE INDEX idx_ai_sessions_org ON ai_sessions (organization_id);

-- ============================================================
-- Table: ai_proposals
-- ============================================================
CREATE TABLE ai_proposals (
    id                  SERIAL PRIMARY KEY,
    proposal_id         VARCHAR(64) NOT NULL UNIQUE,
    session_id          VARCHAR(64) NOT NULL REFERENCES ai_sessions(session_id)
                            ON DELETE CASCADE,
    operation           VARCHAR(32) NOT NULL
                            CHECK (operation IN ('create', 'update', 'delete', 'batch_import')),
    resource_type       VARCHAR(32) NOT NULL
                            CHECK (resource_type IN ('page', 'course', 'component', 'batch')),
    resource_id         VARCHAR(64),  -- NULL for creates, UUID for updates/deletes
    before_snapshot     JSONB,        -- NULL for creates
    after_candidate     JSONB NOT NULL,
    diff                JSONB,        -- computed diff between before and after
    validation_result   JSONB,        -- { status: "valid"|"warning"|"error", messages: [...] }
    base_hash           VARCHAR(64),  -- SHA256 of resource state before proposal
    status              VARCHAR(32) NOT NULL DEFAULT 'PENDING_REVIEW'
                            CHECK (status IN (
                                'PENDING_REVIEW', 'APPROVED', 'APPLIED',
                                'REJECTED', 'EXPIRED', 'FAILED', 'STALE'
                            )),
    applied_at          TIMESTAMP WITH TIME ZONE,
    expires_at          TIMESTAMP WITH TIME ZONE NOT NULL,
    error_message       TEXT,
    idempotency_key     VARCHAR(255),  -- optional, for dedup
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ai_proposals_session ON ai_proposals (session_id);
CREATE INDEX idx_ai_proposals_status ON ai_proposals (status);
CREATE INDEX idx_ai_proposals_resource ON ai_proposals (resource_type, resource_id);
CREATE UNIQUE INDEX idx_ai_proposals_idempotency ON ai_proposals (idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE INDEX idx_ai_proposals_created ON ai_proposals (created_at DESC);

-- ============================================================
-- Table: ai_confirmation_tokens
-- ============================================================
CREATE TABLE ai_confirmation_tokens (
    id              SERIAL PRIMARY KEY,
    token_id        VARCHAR(64) NOT NULL UNIQUE,
    proposal_id     VARCHAR(64) NOT NULL REFERENCES ai_proposals(proposal_id)
                        ON DELETE CASCADE,
    session_id      VARCHAR(64) NOT NULL REFERENCES ai_sessions(session_id)
                        ON DELETE CASCADE,
    user_id         VARCHAR(64) NOT NULL,
    status          VARCHAR(32) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'consumed', 'expired')),
    consumed_at     TIMESTAMP WITH TIME ZONE,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX idx_ai_confirm_proposal ON ai_confirmation_tokens (proposal_id);
CREATE INDEX idx_ai_confirm_session ON ai_confirmation_tokens (session_id);
CREATE INDEX idx_ai_confirm_status ON ai_confirmation_tokens (status, expires_at);

-- ============================================================
-- Table: ai_audit_logs
-- ============================================================
CREATE TABLE ai_audit_logs (
    id              SERIAL PRIMARY KEY,
    audit_id        VARCHAR(64) NOT NULL UNIQUE,
    user_id         VARCHAR(64) NOT NULL,
    session_id      VARCHAR(64) NOT NULL REFERENCES ai_sessions(session_id)
                        ON DELETE SET NULL,
    proposal_id     VARCHAR(64) REFERENCES ai_proposals(proposal_id)
                        ON DELETE SET NULL,
    tool_name       VARCHAR(100) NOT NULL,
    operation       VARCHAR(32) NOT NULL
                        CHECK (operation IN ('create', 'update', 'delete', 'validate', 'chat', 'import')),
    resource_type   VARCHAR(32),
    resource_id     VARCHAR(64),
    before_state    JSONB,
    after_state     JSONB,
    diff            JSONB,
    result_status   VARCHAR(16) NOT NULL CHECK (result_status IN ('success', 'error')),
    error_code      VARCHAR(64),
    model_id        VARCHAR(100),         -- e.g., "claude-3-5-sonnet-20241022"
    model_provider  VARCHAR(50),          -- e.g., "anthropic"
    prompt_version  VARCHAR(32),          -- version of system prompt used
    tool_schema_version VARCHAR(32),      -- version of tool schemas used
    token_count_input   INTEGER,
    token_count_output  INTEGER,
    ip_address      VARCHAR(45),
    user_agent      VARCHAR(500),
    trace_id        VARCHAR(64),          -- distributed tracing correlation ID
    organization_id VARCHAR(64),
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ai_audit_user ON ai_audit_logs (user_id);
CREATE INDEX idx_ai_audit_session ON ai_audit_logs (session_id);
CREATE INDEX idx_ai_audit_proposal ON ai_audit_logs (proposal_id);
CREATE INDEX idx_ai_audit_course ON ai_audit_logs (resource_id);
CREATE INDEX idx_ai_audit_created ON ai_audit_logs (created_at DESC);
CREATE INDEX idx_ai_audit_operation ON ai_audit_logs (operation);
CREATE INDEX idx_ai_audit_trace ON ai_audit_logs (trace_id);
CREATE INDEX idx_ai_audit_org ON ai_audit_logs (organization_id);

-- Partition hint: For production, partition ai_audit_logs by month on created_at.
-- CREATE TABLE ai_audit_logs (...) PARTITION BY RANGE (created_at);

-- ============================================================
-- Table: ai_outbox_events
-- ============================================================
CREATE TABLE ai_outbox_events (
    id              SERIAL PRIMARY KEY,
    event_id        VARCHAR(64) NOT NULL UNIQUE,
    event_type      VARCHAR(100) NOT NULL,
    event_version   INTEGER NOT NULL DEFAULT 1,
    aggregate_id    VARCHAR(64) NOT NULL,   -- the resource ID (page_id, course_id, etc.)
    aggregate_type  VARCHAR(32),            -- 'page', 'course', 'session'
    payload         JSONB NOT NULL,
    trace_id        VARCHAR(64),
    session_id      VARCHAR(64),
    proposal_id     VARCHAR(64),
    occurred_at     TIMESTAMP WITH TIME ZONE NOT NULL,
    published_at    TIMESTAMP WITH TIME ZONE,  -- NULL = not yet published
    retry_count     INTEGER NOT NULL DEFAULT 0,
    status          VARCHAR(16) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'published', 'failed', 'skipped'))
);

CREATE INDEX idx_ai_outbox_status ON ai_outbox_events (status, retry_count)
    WHERE published_at IS NULL;
CREATE INDEX idx_ai_outbox_event_type ON ai_outbox_events (event_type);
CREATE INDEX idx_ai_outbox_occurred ON ai_outbox_events (occurred_at DESC);
CREATE INDEX idx_ai_outbox_trace ON ai_outbox_events (trace_id);

-- ============================================================
-- Table: ai_chat_turns
-- ============================================================
CREATE TABLE ai_chat_turns (
    id                  SERIAL PRIMARY KEY,
    turn_id             VARCHAR(64) NOT NULL UNIQUE,
    session_id          VARCHAR(64) NOT NULL REFERENCES ai_sessions(session_id)
                            ON DELETE CASCADE,
    user_prompt         TEXT NOT NULL,
    assistant_response  TEXT NOT NULL,
    model_used          VARCHAR(100),
    model_provider      VARCHAR(50),
    tool_calls_made     JSONB,       -- [{ toolName, input, output }]
    tool_results_summary JSONB,      -- [{ toolName, resultStatus, durationMs }]
    total_tokens        INTEGER,
    prompt_version      VARCHAR(32),
    trace_id            VARCHAR(64),
    proposal_ids        JSONB,       -- ["proposal-uuid-1", ...] proposals created in this turn
    feedback_rating     SMALLINT CHECK (feedback_rating BETWEEN -1 AND 1),  -- -1/0/1
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ai_turns_session ON ai_chat_turns (session_id, created_at DESC);
CREATE INDEX idx_ai_turns_created ON ai_chat_turns (created_at DESC);

-- ============================================================
-- Table: ai_idempotency_keys
-- ============================================================
CREATE TABLE ai_idempotency_keys (
    id              SERIAL PRIMARY KEY,
    idempotency_key VARCHAR(255) NOT NULL UNIQUE,
    session_id      VARCHAR(64) NOT NULL,
    response_status INTEGER NOT NULL,
    response_body   JSONB NOT NULL,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX idx_ai_idempotency_expires ON ai_idempotency_keys (expires_at);
```

### 2.3 Service/Module Design

#### File Structure

```
app/
  models/
    ai_models.py              -- NEW: SQLAlchemy ORM models for all AI tables
  repositories/
    ai_session_repo.py        -- NEW: Session CRUD + expiry check
    ai_proposal_repo.py       -- NEW: Proposal lifecycle + staleness detection
    ai_confirmation_repo.py   -- NEW: Confirmation token management
    ai_audit_repo.py          -- NEW: Audit log writing + querying
    ai_outbox_repo.py         -- NEW: Outbox event writing + publishing
    ai_chat_turn_repo.py      -- NEW: Chat turn persistence
    ai_idempotency_repo.py    -- NEW: Idempotency key storage
  services/
    ai/
      __init__.py             -- NEW
      session_service.py      -- NEW: Business logic for session lifecycle
      proposal_service.py     -- NEW: Business logic for proposal lifecycle
      audit_service.py        -- NEW: Business logic for audit logging
      outbox_service.py       -- NEW: Business logic for outbox event management
```

#### ORM Models (`app/models/ai_models.py`)

```python
"""SQLAlchemy ORM models for AI persistence foundations.

Follows the same patterns as app/models/persisted_course.py and
app/models/page_component.py: auto-increment PKs, UUID external IDs,
JSON/JSONB for flexible data, utcnow timestamps.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional
import uuid

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import (
    String, DateTime, JSON, Text, Integer, Boolean,
    ForeignKey, CheckConstraint, Index,
)

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class AISessionRecord(Base):
    __tablename__ = "ai_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    course_id: Mapped[str] = mapped_column(String(64), index=True)
    organization_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="active")
    context_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at

    def to_dict(self) -> dict:
        return {
            "sessionId": self.session_id,
            "userId": self.user_id,
            "courseId": self.course_id,
            "organizationId": self.organization_id,
            "status": self.status,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "expiresAt": self.expires_at.isoformat() if self.expires_at else None,
            "contextSummary": self.context_summary,
        }


class AIProposalRecord(Base):
    __tablename__ = "ai_proposals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    proposal_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    operation: Mapped[str] = mapped_column(String(32))  # create, update, delete, batch_import
    resource_type: Mapped[str] = mapped_column(String(32))  # page, course, component, batch
    resource_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    before_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    after_candidate: Mapped[dict] = mapped_column(JSON, nullable=False)
    diff: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    validation_result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    base_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING_REVIEW", index=True)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at

    def is_applied(self) -> bool:
        return self.status == "APPLIED"

    def is_usable(self) -> bool:
        return self.status == "PENDING_REVIEW" and not self.is_expired()


class AIConfirmationTokenRecord(Base):
    __tablename__ = "ai_confirmation_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    token_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=_uuid)
    proposal_id: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)

    def is_valid(self) -> bool:
        return (self.status == "pending"
                and datetime.utcnow() <= self.expires_at)


class AIAuditLogRecord(Base):
    __tablename__ = "ai_audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    audit_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    proposal_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(100))
    operation: Mapped[str] = mapped_column(String(32))  # create, update, delete, validate, chat, import
    resource_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    before_state: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    after_state: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    diff: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    result_status: Mapped[str] = mapped_column(String(16))  # success, error
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    model_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model_provider: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    tool_schema_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    token_count_input: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    token_count_output: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    trace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    organization_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AIOutboxEventRecord(Base):
    __tablename__ = "ai_outbox_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=_uuid)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    event_version: Mapped[int] = mapped_column(Integer, default=1)
    aggregate_id: Mapped[str] = mapped_column(String(64))
    aggregate_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    trace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    proposal_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="pending")


class AIChatTurnRecord(Base):
    __tablename__ = "ai_chat_turns"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    turn_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    user_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    assistant_response: Mapped[str] = mapped_column(Text, nullable=False)
    model_used: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model_provider: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tool_calls_made: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    tool_results_summary: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    trace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    proposal_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    feedback_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AIIdempotencyKeyRecord(Base):
    __tablename__ = "ai_idempotency_keys"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    session_id: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
```

#### Repository Signatures (`app/repositories/ai_session_repo.py`)

```python
"""Repository for AI session persistence."""
from __future__ import annotations
from typing import Optional, Sequence
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import datetime

from app.models.ai_models import AISessionRecord


class AISessionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user_id: str, course_id: str,
                     organization_id: str, ttl_hours: int = 24) -> AISessionRecord:
        ...

    async def get_by_session_id(self, session_id: str) -> AISessionRecord:
        ...

    async def find_active_by_user_course(self, user_id: str,
                                         course_id: str) -> Optional[AISessionRecord]:
        """Find non-expired, active session for this user+course pair."""
        ...

    async def expire_old_sessions(self) -> int:
        """Mark sessions as expired where expires_at < now."""
        ...

    async def revoke(self, session_id: str) -> AISessionRecord:
        ...

    async def update_context_summary(self, session_id: str,
                                     summary: dict) -> AISessionRecord:
        ...
```

#### Service Signatures (`app/services/ai/session_service.py`)

```python
"""Business logic for AI session management."""
from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.ai_session_repo import AISessionRepository
from app.repositories.course_repo import CourseRepository


class AISessionService:
    def __init__(self, db_session: AsyncSession):
        self.session_repo = AISessionRepository(db_session)
        self.course_repo = CourseRepository(db_session)

    async def create_session(self, user_id: str, course_id: str,
                             organization_id: str) -> AISessionRecord:
        """Create a new AI session. Validates course exists
        and no duplicate active session exists."""
        ...

    async def validate_session(self, session_id: str) -> AISessionRecord:
        """Check session is active, not expired, return record.
        Raises SessionExpiredError or SessionNotFoundError."""
        ...

    async def revoke_session(self, session_id: str) -> AISessionRecord:
        ...
```

#### Audit Service (`app/services/ai/audit_service.py`)

```python
"""Business logic for audit logging."""
from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.ai_audit_repo import AIAuditRepository


class AuditService:
    def __init__(self, db_session: AsyncSession):
        self.audit_repo = AIAuditRepository(db_session)

    async def log_operation(
        self,
        user_id: str,
        session_id: str,
        proposal_id: str | None,
        tool_name: str,
        operation: str,
        resource_type: str | None,
        resource_id: str | None,
        before_state: dict | None,
        after_state: dict | None,
        diff: dict | None,
        result_status: str,
        error_code: str | None = None,
        model_id: str | None = None,
        model_provider: str | None = None,
        prompt_version: str | None = None,
        token_count_input: int | None = None,
        token_count_output: int | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        trace_id: str | None = None,
        organization_id: str | None = None,
    ) -> AIAuditLogRecord:
        """Write an audit log entry."""
        ...

    async def query_logs(self, filters: dict, page: int = 1,
                         per_page: int = 50) -> tuple[list, int]:
        """Query audit logs with filtering and pagination."""
        ...
```

#### Outbox Service (`app/services/ai/outbox_service.py`)

```python
"""Business logic for outbox event management."""
from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.ai_outbox_repo import AIOutboxRepository


class OutboxService:
    def __init__(self, db_session: AsyncSession):
        self.outbox_repo = AIOutboxRepository(db_session)

    async def write_event(self, event_type: str, aggregate_id: str,
                          aggregate_type: str, payload: dict,
                          trace_id: str | None = None,
                          session_id: str | None = None,
                          proposal_id: str | None = None) -> AIOutboxEventRecord:
        """Write an outbox event in the current transaction."""
        ...

    async def publish_pending(self, batch_size: int = 100) -> int:
        """Publish pending outbox events (called by background worker)."""
        ...

    async def get_unpublished_count(self) -> int:
        ...
```

### 2.4 Configuration Variables

| Variable Name | Type | Default | Description |
|---|---|---|---|
| `AI_SESSION_TTL_HOURS` | int | 24 | Default TTL for AI sessions in hours |
| `AI_PROPOSAL_TTL_MINUTES` | int | 60 | Default TTL for proposals in minutes |
| `AI_CONFIRMATION_TOKEN_TTL_MINUTES` | int | 15 | TTL for confirmation tokens |
| `AI_IDEMPOTENCY_KEY_TTL_HOURS` | int | 24 | TTL for idempotency key storage |
| `AI_OUTBOX_PUBLISH_INTERVAL_SECONDS` | int | 30 | Polling interval for outbox publisher |
| `AI_OUTBOX_BATCH_SIZE` | int | 100 | Max events per publish batch |
| `AI_AUDIT_RETENTION_DAYS` | int | 730 | Audit log retention in days (2 years) |
| `AI_CHAT_TURN_RETENTION_DAYS` | int | 90 | Chat turn retention in days |

These are loaded in `app/services/ai/config.py` using `os.getenv()` with typed fallbacks.

### 2.5 Integration Points

| Integration | Direction | How |
|---|---|---|
| Existing `CourseRepository` | Called by `AISessionService.create_session` | Validate course_id exists before creating session |
| Existing `Base` from `app/models/base.py` | Imported by `ai_models.py` | All new models inherit from same Base |
| Existing `get_session` from `app/db/config.py` | Used by all new repositories | FastAPI dependency injection pattern |
| Alembic migration env | Modified to auto-detect new models | Add `import app.models.ai_models` in `env.py` |
| Existing error envelope (`app/utils/error_envelope.py`) | Used by all new services | Consistent error responses |
| US-BKND-AI-003 router layer | Consumed by | `ai_sessions.py` router calls `AISessionService` |
| US-BKND-AI-009 proposal tools | Consumed by | Proposal tools call `AIProposalRepository` |
| US-BKND-AI-010 apply flow | Writes to | Audit and outbox repositories |
| Background worker (future US-BKND-AI-034) | Reads from | Outbox repository for event publishing |

---

## 3. NON-FUNCTIONAL REQUIREMENTS

### 3.1 Performance Targets

| Metric | Target | Measurement |
|---|---|---|
| Session creation latency p50 | < 100 ms | From request receipt to response |
| Session creation latency p95 | < 250 ms | |
| Session creation latency p99 | < 500 ms | |
| Proposal creation latency p50 | < 150 ms | Includes validation and JSON serialization |
| Proposal creation latency p99 | < 500 ms | |
| Apply (proposal + audit + outbox) p50 | < 200 ms | Single database transaction |
| Apply (proposal + audit + outbox) p99 | < 800 ms | |
| Audit log write latency | < 50 ms | Non-blocking append |
| Audit log query (filtered, paginated) | < 500 ms | With proper indexes |
| Outbox event batch publish (100 events) | < 2 seconds | |
| Concurrent sessions supported | 1000+ | Without degradation |

### 3.2 Security Requirements

**Authorization Model:**
- Session creation requires JWT authentication with valid user identity.
- Session scope enforcement: every tool call validates that the session's `user_id` matches the authenticated user's ID.
- Course access check: `AISessionService.create_session` verifies the user has access to the course via existing course ownership/permission logic.
- Organization/tenant isolation: all AI records include `organization_id`. Queries at the repository level MUST filter by organization_id to prevent cross-tenant data leakage.
- Audit log access: only users with `admin` or `auditor` role can query audit logs. Non-admin users can see only their own audit entries.

**Validation Rules:**
- All UUID fields validated server-side as valid UUID v4 format.
- All string fields have max length limits enforced at the repository layer (mirroring column definitions).
- JSON fields (before_snapshot, after_candidate, payload) are validated to be valid JSON and within size limits (< 1 MB per record).
- `ip_address` validated as valid IPv4 or IPv6 format.
- `user_agent` stripped of control characters before storage.

**Tenant Isolation:**
- Every query on `ai_sessions`, `ai_proposals`, `ai_audit_logs`, and `ai_outbox_events` MUST include an `organization_id` filter.
- Repository methods accept an `organization_id` parameter and include `WHERE organization_id = :org_id` in all queries.

### 3.3 Reliability

**Error Codes Catalog:**

| Code | HTTP Status | Description | Retryable |
|---|---|---|---|
| `SESSION_EXPIRED` | 401 | Session TTL exceeded | No |
| `SESSION_NOT_FOUND` | 404 | Session ID does not exist | No |
| `SESSION_REVOKED` | 403 | Session was explicitly revoked | No |
| `SESSION_USER_MISMATCH` | 403 | Session user != authenticated user | No |
| `PROPOSAL_NOT_FOUND` | 404 | Proposal ID does not exist | No |
| `PROPOSAL_EXPIRED` | 410 | Proposal TTL exceeded | No |
| `PROPOSAL_ALREADY_APPLIED` | 409 | Proposal status is APPLIED | No |
| `PROPOSAL_REJECTED` | 410 | Proposal was rejected by user | No |
| `STALE_PROPOSAL` | 409 | Base hash mismatch (resource changed) | Yes (re-fetch and re-propose) |
| `CONFIRMATION_TOKEN_EXPIRED` | 410 | Token TTL exceeded for destructive op | No (re-create proposal) |
| `CONFIRMATION_TOKEN_CONSUMED` | 409 | Token already used | No |
| `IDEMPOTENCY_MISMATCH` | 422 | Same idempotency key used for different request body | No |
| `VALIDATION_ERROR` | 422 | Proposal data fails validation | Yes (fix and retry) |
| `AUDIT_WRITE_FAILED` | 500 | Cannot write audit log | Yes (DB-level retry) |

**Retry Strategy:**
- Database transaction conflicts: retry up to 3 times with exponential backoff (50ms, 100ms, 200ms).
- Idempotent operations (GET, reads): no retry limit beyond network timeout.
- Non-idempotent writes with idempotency key: safe to retry; response is cached.
- Non-idempotent writes without idempotency key: do NOT retry; return error to caller.
- Outbox publish: retry failed events up to 5 times with exponential backoff (1s, 2s, 4s, 8s, 16s) before marking as `failed`.

**Graceful Degradation:**
- If audit log write fails within the apply transaction, the entire transaction rolls back. The mutation does NOT proceed without an audit trail.
- If outbox event write fails within the transaction, the entire transaction rolls back. No event loss.
- If the background outbox publisher is down, events remain in `pending` status and are published when the publisher recovers.
- If the database connection pool is exhausted, return HTTP 503 with `code: "SERVICE_UNAVAILABLE"` and `retryable: true`.

**Idempotency Guarantees:**
- Same idempotency_key + same request body = same result returned (up to 24h).
- Same idempotency_key + different request body = `IDEMPOTENCY_MISMATCH` error.
- After 24h, the idempotency key expires and a new operation can use the same key.

### 3.4 Scalability

- All AI persistence services are stateless. No in-memory session state. All state lives in PostgreSQL.
- Connection pooling: use existing `DB_POOL_SIZE` (default 10) and `DB_MAX_OVERFLOW` (default 20) from `app/db/config.py`. AI operations may require a dedicated pool configuration if load is high.
- Horizontal scaling: all services can run on any number of backend instances. Session validation is a database read, not an in-memory lookup.
- Read replicas: audit log queries can be routed to read replicas (write queries still go to primary).
- Partitioning: `ai_audit_logs` should be partitioned by month on `created_at` for production deployments with high volume.
- Indexing: all query patterns are covered by the indexes defined in the DDL section.

---

## 4. CURRENT STATE ASSESSMENT

### 4.1 What Exists Today (Reusable)

| File/Module | What It Provides | How to Reuse |
|---|---|---|
| `app/models/base.py` | Declarative Base | Import and inherit for all new AI models |
| `app/models/persisted_course.py` | Existing model patterns (CourseRecord, ImportJob) | Reference for column types, naming conventions, to_dict patterns |
| `app/models/page_component.py` | PageRecord, ComponentRecord with FK patterns | Reference for relationships and UUID generation |
| `app/db/config.py` | Async engine, SessionLocal, get_session dependency | Inject into all new repositories |
| `app/repositories/course_repo.py` | Repository pattern (constructor with AsyncSession, select-based queries, custom exceptions) | Follow exact same pattern for all new AI repositories |
| `app/utils/error_envelope.py` | `build_error()`, `api_http_exception()` | Use for all error responses |
| `app/utils/feature_flags.py` | `FeatureFlagService`, `is_feature_enabled()` | Gate AI routes behind `ai_authoring` flag |
| `app/main.py` | Router registration pattern, startup lifecycle, model imports | Add AI model imports in startup, register AI routers |
| Alembic environment | `alembic/env.py` for auto-migration generation | Add `import app.models.ai_models` so autogenerate detects new tables |
| `alembic/versions/` | Existing migration pattern (20260412_0003_*) | Use as template for new migration that creates all AI tables |

### 4.2 What Must Be Built Net-New

| Artifact | Reason |
|---|---|
| `app/models/ai_models.py` | 7 new ORM models not existing anywhere in the codebase |
| `app/repositories/ai_session_repo.py` | No existing session persistence logic |
| `app/repositories/ai_proposal_repo.py` | No existing proposal lifecycle persistence |
| `app/repositories/ai_confirmation_repo.py` | No existing confirmation token persistence |
| `app/repositories/ai_audit_repo.py` | No existing audit logging |
| `app/repositories/ai_outbox_repo.py` | No existing outbox event persistence |
| `app/repositories/ai_chat_turn_repo.py` | No existing chat turn persistence |
| `app/repositories/ai_idempotency_repo.py` | No existing idempotency support |
| `app/services/ai/__init__.py` | New service package |
| `app/services/ai/session_service.py` | Session business logic |
| `app/services/ai/proposal_service.py` | Proposal lifecycle business logic |
| `app/services/ai/audit_service.py` | Audit logging business logic |
| `app/services/ai/outbox_service.py` | Outbox event business logic |
| `app/services/ai/config.py` | AI configuration loading |
| `app/routers/ai_sessions.py` | POST/GET/DELETE session endpoints (from US-BKND-AI-003 scaffold, will wire to services from this story) |
| Alembic migration script | CREATE TABLE statements for all 7 new tables |
| Unit tests for all repositories | Test each CRUD operation, expiry logic, status transitions |
| Unit tests for all services | Test business logic, error conditions, edge cases |
| Integration tests for database | Test transaction atomicity, concurrent access, index performance |

### 4.3 What Existing Code Must Be Modified (with Non-Regression Constraints)

**`app/main.py`** (modify):
- Add `import app.models.ai_models` to the startup lifecycle block (line ~86-93) so Base.metadata includes the new tables for `create_all`.
- Add `import app.routers.ai_sessions` (when US-BKND-AI-003 is complete) to the router imports.
- Add `api_router.include_router(ai_sessions.router)` to the router registration block.
- **Non-regression constraint:** Existing router registration and model imports must remain unchanged and in the same order. The AI router addition must be at the end of the list.

**`app/models/__init__.py`** (modify):
- Add imports for all new AI model classes.
- **Non-regression constraint:** All existing model imports must remain exactly as-is; the new imports are additive.

**Alembic `env.py`** (modify):
- Add `from app.models import ai_models` (or the specific model classes) so autogenerate detects new tables.
- **Non-regression constraint:** The existing `target_metadata = Base.metadata` pattern remains unchanged.

**`app/services/ai/__init__.py`** (create as package):
- Create the file even if empty, establishing the new `app/services/ai/` package structure for future AI services.

**Non-regression constraints (ALL modifications):**
- All existing course CRUD tests must pass without changes.
- All existing import/export tests must pass without changes.
- All existing SCORM export tests must pass without changes.
- The application must start without error when the `ai_authoring` feature flag is disabled.

---

## 5. EXPANSION POINTS

### 5.1 Technical Expansions (Future Sprints)

1. **Audit Log Partitioning:** The `ai_audit_logs` table is defined as a monolithic table. In production with high AI usage, this can grow to millions of rows per month. A future sprint should partition by month on `created_at` using PostgreSQL native partitioning. The DDL includes a commented-out PARTITION BY hint for this purpose.

2. **Outbox Event Stream Processing:** The current outbox stores events for polling-based publishing. A future sprint could add a PostgreSQL LISTEN/NOTIFY trigger on `ai_outbox_events` so that a background worker is notified immediately when a new event appears, reducing publish latency from 30s to < 1s. Further expansion: integrate with Kafka/Pulsar for cross-service event streaming.

3. **Idempotency Key with Redis Caching:** The current idempotency key implementation uses a database table with a TTL. For higher throughput, a future sprint could add a Redis layer for idempotency checks, falling back to the database if Redis is unavailable.

4. **Soft-Delete and Recovery for Audit Logs:** A future sprint could add a `deleted_at` column to `ai_audit_logs` supporting soft-delete instead of hard-delete for compliance purposes, with an admin recovery endpoint.

5. **Session Context Window Recovery Storage:** The `context_summary` JSONB field on `ai_sessions` is a placeholder. A future sprint can populate it with structured summaries (active proposal IDs, last page focused, key decisions) for the context window recovery flow (US-BKND-AI-039).

### 5.2 Functional Expansions (Future Sprints)

1. **Multi-Session per Course:** Currently one active session per user+course. A future sprint could allow multiple concurrent sessions for the same course (e.g., one session for each browser tab), managed via per-session IDs and independent expiry.

2. **Audit-Driven Rollback:** The `before_state` in `ai_audit_logs` enables point-in-time rollback. A future sprint could implement an admin "rollback to this audit entry" feature that creates a reversal proposal, running it through the standard propose-validate-confirm-apply pipeline (US-BKND-AI-040).

3. **Outbox Event Sourcing for Analytics:** The outbox events contain full payload of what changed. A future sprint could consume these events to build an analytics pipeline (course generation metrics, user engagement with AI features, model performance comparison), feeding into dashboards.

4. **Chat Turn Replay for Debugging:** Persisted chat turns with full tool call traces enable debugging and model evaluation. A future sprint could build an admin "replay session" UI that replays all turns of a session for troubleshooting.

5. **Cross-Session Proposal Reuse:** When a proposal is rejected for staleness, a future sprint could automatically create a fresh proposal by re-applying the same after_candidate against the current state, reducing user friction.

---

## 6. VALIDATION & TESTING

### 6.1 Unit Test Scenarios

**Test 1: Session Creation and Expiry**
```
Input:
  - user_id = "U-001", course_id = "C-001", org_id = "ORG-001"
  - Mock system clock at 2026-06-15T10:00:00Z
  - AI_SESSION_TTL_HOURS = 24

Action:
  - Create session via AISessionService.create_session()

Expected Output:
  - session_id is a valid UUID v4 string
  - status = "active"
  - expires_at = 2026-06-16T10:00:00Z
  - is_expired() returns False (if checked at creation time)
  - is_expired() returns True (if clock advances past expires_at)
```

**Test 2: Proposal Status Transitions**
```
Input:
  - Valid session exists
  - Create proposal with status = "PENDING_REVIEW"

Action 1: Apply proposal
  - Set status to "APPLIED", applied_at = now

Expected 1:
  - proposal.is_applied() returns True
  - proposal.is_usable() returns False

Action 2: Attempt apply again
Expected 2:
  - Raises ProposalAlreadyAppliedError with message "Proposal already applied"

Action 3: Test other statuses
  - REJECTED proposal: is_usable() returns False
  - EXPIRED proposal: is_usable() returns False
  - STALE proposal: is_usable() returns False
```

**Test 3: Base Hash Staleness Detection**
```
Input:
  - Proposal with base_hash = "abc123"
  - Resource current_hash = "def456" (different)

Action:
  - Call proposal_service.check_staleness(proposal, current_hash)

Expected Output:
  - Returns STALE_PROPOSAL error
  - error code = "STALE_PROPOSAL"
  - details include baseHash = "abc123" and currentHash = "def456"

Edge case:
  - base_hash is None (new resource): check_staleness returns None (no staleness)
```

**Test 4: Confirmation Token Lifecycle**
```
Input:
  - proposal_id = "PROP-001", session_id = "SESS-001", user_id = "U-001"
  - AI_CONFIRMATION_TOKEN_TTL_MINUTES = 15

Action 1: Create token
Expected 1:
  - token_id is UUID
  - status = "pending"
  - expires_at = now + 15 minutes
  - is_valid() returns True

Action 2: Consume token
Expected 2:
  - status = "consumed"
  - consumed_at is set
  - is_valid() returns False

Action 3: Try to consume again
Expected 3:
  - Raises ConfirmationTokenConsumedError

Action 4: Create token, advance clock past expires_at
Expected 4:
  - is_valid() returns False
```

**Test 5: Idempotency Key Deduplication**
```
Input:
  - idempotency_key = "IDEM-001"
  - Request body A = { proposalId: "P1", userConfirmed: true }

Action 1: First call with IDEM-001, body A
  - Store response { status: "created", pageId: "PAGE-1" }

Expected 1: Returns stored response, does NOT execute the operation again

Action 2: Second call with same IDEM-001, DIFFERENT body B
Expected 2:
  - Raises IdempotencyMismatchError
  - error code = "IDEMPOTENCY_MISMATCH"

Action 3: Call with expired idempotency key (TTL passed)
Expected 3: Treated as a new call
```

**Test 6: Transactional Rollback on Audit Write Failure**
```
Input:
  - All apply steps succeed except audit log write (simulated failure)

Action:
  - Call apply pipeline

Expected Output:
  - Database transaction rolls back
  - Proposal status remains "PENDING_REVIEW"
  - No page is created
  - No outbox event remains
  - Exception propagated to caller with descriptive message
```

### 6.2 Integration Test Scenarios

**Integration Test 1: End-to-End Session Creation + Proposal + Apply**
```
Setup:
  - Create course C-001 with 0 pages in the database via CourseRepository
  - Initialize an AsyncSession with a test PostgreSQL database

Steps:
  1. Call AISessionService.create_session(user="U-001", course="C-001", org="ORG-001")
     -> Verify session record exists in ai_sessions table
  2. Call proposal_service.create_proposal(session_id, operation="create",
     resource_type="page", after_candidate={...}, base_hash=None)
     -> Verify proposal record exists in ai_proposals table with status "PENDING_REVIEW"
  3. Execute apply pipeline: update proposal + create page + write audit + write outbox
     -> Verify proposal.status = "APPLIED"
     -> Verify page exists in pages table
     -> Verify audit log entry exists in ai_audit_logs
     -> Verify outbox event exists in ai_outbox_events with status "pending"
  4. Query audit logs by session_id
     -> Verify exactly one entry returned with correct operation and result_status
```

**Integration Test 2: Concurrent Proposal Staleness**
```
Setup:
  - Course C-001 with page PAGE-001
  - AISessionRepository.create_session(U-001, C-001, ORG-001)

Steps:
  1. Create proposal P-001 for updating PAGE-001 (base_hash = hash of current page data)
     -> Verify proposal created successfully
  2. Simulate concurrent modification: update PAGE-001 title via PageRepository directly
     (simulating manual editor change)
     -> Verify page updated successfully
  3. Attempt to apply proposal P-001
     -> Verify error: STALE_PROPOSAL (409)
     -> Verify proposal status changed to "STALE" (or remains PENDING_REVIEW per design)
     -> Verify page title is the concurrent modification, NOT the proposal's after_candidate
  4. Create a new proposal P-002 after re-fetching current state
     -> Verify new proposal with updated base_hash
     -> Apply P-002
     -> Verify page title is the new proposed title
```

**Integration Test 3: Outbox Event Persistence and Publishing**
```
Setup:
  - Create session and apply a proposal (creating audit log + outbox event)
  - The event is in ai_outbox_events with status = "pending"

Steps:
  1. Query ai_outbox_events where published_at IS NULL
     -> Verify exactly 1 event returned
     -> Verify event_type = "PageCreatedByAI"
     -> Verify payload contains pageId, proposalId, sessionId, trace_id
  2. Call outbox_service.publish_pending(batch_size=10)
     -> Verify event status changed to "published"
     -> Verify published_at is set (non-null)
  3. Call publish_pending again
     -> Verify no events returned as pending (idempotent publish)
```

### 6.3 E2E / Acceptance Test Scenarios

**E2E Test 1: Full Session Lifecycle with Create and Apply**
```
Preconditions:
  - Feature flag AI_AUTHORING_ENABLED = true
  - User is authenticated with JWT
  - Course with courseId "C-001" exists and user has access

Steps:
  1. POST /api/v1/ai/sessions
     Body: { userId: "U-001", courseId: "C-001", organizationId: "ORG-001" }
     Expected: 201, response includes sessionId, expiresAt = now + 24h
  2. GET /api/v1/ai/sessions/{sessionId}
     Expected: 200, same session data, status = "active"
  3. POST /api/v1/ai/tools/propose_create_page (via tool endpoint, US-BKND-AI-009)
     Expected: proposalId returned, status = "PENDING_REVIEW"
  4. Wait 1 second (simulate user review)
  5. POST /api/v1/ai/tools/apply_page_proposal with proposalId, userConfirmed: true
     Expected: pageId returned, status = "created"
  6. GET /api/v1/courses/C-001/pages
     Expected: new page visible in page list
  7. DELETE /api/v1/ai/sessions/{sessionId}
     Expected: 200, status = "revoked"
  8. GET /api/v1/ai/sessions/{sessionId}
     Expected: status = "revoked"
```

**E2E Test 2: Stale Proposal Rejected**
```
Preconditions:
  - Same as E2E Test 1

Steps:
  1. POST /api/v1/ai/sessions -> get sessionId
  2. POST /api/v1/ai/tools/propose_create_page -> get proposalId
  3. (Simulate race condition) Modify the same course via existing manual API
     POST /api/v1/courses/C-001/pages directly
  4. POST /api/v1/ai/tools/apply_page_proposal with proposalId
     Expected: 409 CONFLICT
     Body includes code: "STALE_PROPOSAL"
  5. GET /api/v1/ai/proposals/{proposalId} (via admin query)
     Expected: status is "STALE" or "PENDING_REVIEW" with staleness flag
  6. Verify no duplicate page was created
  7. No audit log entry for a successful apply (or audit entry with result_status = "error")
```

### 6.4 Manual QA Verification Procedure

```
=== Phase 1: Session Verification ===
[ ] 1. Launch backend with all migrations applied
[ ] 2. Verify ai_sessions, ai_proposals, ai_confirmation_tokens, ai_audit_logs,
        ai_outbox_events, ai_chat_turns, ai_idempotency_keys tables exist
     psql command: \dt ai_*
[ ] 3. Verify each table has the correct columns, types, constraints
     psql command: \d ai_sessions (repeat for each table)
[ ] 4. Verify indexes exist
     psql command: \di idx_ai_*

=== Phase 2: Session Creation ===
[ ] 5. Create a session via API: POST /api/v1/ai/sessions
[ ] 6. Verify response includes sessionId, expiresAt
[ ] 7. Query database: SELECT * FROM ai_sessions WHERE session_id = '<sessionId>'
     Verify: status = 'active', expires_at > now
[ ] 8. Try creating duplicate session for same user+course
     Verify: 409 SESSION_ALREADY_EXISTS

=== Phase 3: Session Validation ===
[ ] 9. GET /api/v1/ai/sessions/{invalidId}
     Verify: 404 SESSION_NOT_FOUND
[ ] 10. Revoke session: DELETE /api/v1/ai/sessions/{sessionId}
     Verify: 200, status = 'revoked'
[ ] 11. GET the revoked session
     Verify: status = 'revoked'
[ ] 12. Create a session, manually set expires_at to past via SQL
     Verify: subsequent tool calls with this session fail with SESSION_EXPIRED

=== Phase 4: Proposal Lifecycle ===
[ ] 13. Create proposal (via service layer call or direct repo):
     Insert into ai_proposals with status = 'PENDING_REVIEW'
[ ] 14. Verify is_usable() logic:
     - APPLIED status -> not usable
     - EXPIRED status -> not usable (expires_at in past)
     - PENDING_REVIEW + future expiry -> usable
[ ] 15. Apply the proposal:
     Update status to 'APPLIED', set applied_at = now
[ ] 16. Attempt to apply again:
     Verify: error -> proposal already applied
[ ] 17. Create proposal, let it expire (set expires_at to past):
     Verify: API returns PROPOSAL_EXPIRED on apply attempt

=== Phase 5: Confirmation Tokens ===
[ ] 18. Create confirmation token for a delete proposal
[ ] 19. Verify token is_valid() returns True
[ ] 20. Consume token
[ ] 21. Verify token is_valid() returns False
[ ] 22. Attempt to consume again -> error
[ ] 23. Create token, let it expire -> is_valid() returns False

=== Phase 6: Audit Logging ===
[ ] 24. Execute apply flow and verify ai_audit_logs entry created
[ ] 25. Query audit logs by session_id, user_id, date range
[ ] 26. Verify before_state and after_state are populated correctly
[ ] 27. Verify trace_id is consistent across session, proposal, audit, outbox

=== Phase 7: Outbox Events ===
[ ] 28. Execute apply flow and verify ai_outbox_events entry created
[ ] 29. Verify event_type, payload, trace_id, session_id, proposal_id are consistent
[ ] 30. Verify status = 'pending', published_at IS NULL
[ ] 31. Trigger outbox publisher: verify status = 'published', published_at set

=== Phase 8: Idempotency ===
[ ] 32. Send apply request with idempotency_key = "TEST-KEY-001"
[ ] 33. Send same request again with same key
     Verify: same response returned, no duplicate mutation
[ ] 34. Send different request with same key
     Verify: 422 IDEMPOTENCY_MISMATCH

=== Phase 9: Transaction Rollback ===
[ ] 35. Simulate a failure mid-transaction (e.g., audit write fails)
     Verify: proposal unchanged, no page created, no outbox event

=== Phase 10: Cleanup ===
[ ] 36. Revoke all test sessions
[ ] 37. Drop test database or truncate all ai_* tables
```

---

## 7. DEFINITION OF DONE

The following checklist items must ALL be complete for this story to be considered done:

### Code
- [ ] **DO-D1:** All 7 new SQLAlchemy ORM models exist in `app/models/ai_models.py` with correct column types, constraints, indexes, relationships, and to_dict() methods matching the DDL.
- [ ] **DO-D2:** All 8 new repository classes exist with full CRUD operations, exception handling, and organization_id scoping.
- [ ] **DO-D3:** All 4 new service classes exist (`session_service.py`, `proposal_service.py`, `audit_service.py`, `outbox_service.py`) with complete business logic.
- [ ] **DO-D4:** All new models are imported in `app/models/__init__.py` and registered in `app/main.py` startup lifecycle.
- [ ] **DO-D5:** The `app/services/ai/` package is created with `__init__.py` and `config.py`.

### Tests
- [ ] **DO-D6:** Unit test coverage >= 90% for all repository classes, covering CRUD, expiry logic, status transitions, and error conditions.
- [ ] **DO-D7:** Unit test coverage >= 90% for all service classes, covering happy path, stale detection, confirmation flow, idempotency, and transaction rollback.
- [ ] **DO-D8:** At least 3 integration tests running against a real PostgreSQL database covering end-to-end session+proposal+apply, concurrent staleness, and outbox publishing.

### Database & Migrations
- [ ] **DO-D9:** Alembic migration script is created and verified (applied and rolled back cleanly) that creates all 7 new tables with the exact DDL schema. No data loss on existing tables.

### Feature Flag & Configuration
- [ ] **DO-D10:** The `ai_authoring` feature flag is added to `FeatureFlagService` and gates all AI persistence operations. When disabled, AI endpoints return 404. Configuration env vars are documented in `.env.example`.

### QA & Manual Verification
- [ ] **DO-D11:** All 37 steps of the manual QA verification procedure have been executed and signed off by QA.

### Performance & Security
- [ ] **DO-D12:** Performance targets are verified: session creation < 100ms (p50), proposal apply < 200ms (p50), audit write < 50ms. All queries use proper indexes (verified via EXPLAIN ANALYZE).

### Documentation
- [ ] **DO-D13:** README updates documenting the new AI persistence tables, their purpose, and the session/proposal lifecycle. Architecture diagram updated to include the new tables.
- [ ] **DO-D14:** API documentation (OpenAPI spec) includes the new session create/get/revoke endpoints and audit log query endpoint.

### Coverage Completion
- [ ] **DO-D15:** All code is reviewed and approved by at least one other engineer. No outstanding review comments.

---

## 8. TASKS & SUB-TASKS

| ID | Task Description | Owner Role | Est. Hours | Dependencies |
|---|---|---|---|---|
| T-001 | **Model Layer: SQLAlchemy ORM models** | Backend Engineer | 6 | US-BKND-AI-003 complete |
| T-001.1 | Create `app/models/ai_models.py` with all 7 model classes following existing patterns | | 3 | |
| T-001.2 | Update `app/models/__init__.py` to export new model classes | | 0.5 | T-001.1 |
| T-001.3 | Add model imports to `app/main.py` startup lifecycle | | 0.5 | T-001.1 |
| T-001.4 | Update Alembic `env.py` to detect new models; generate and verify migration | | 2 | T-001.1 |
| T-002 | **Repository Layer: Data access for AI tables** | Backend Engineer | 10 | T-001 |
| T-002.1 | Implement `AISessionRepository` with create, get_by_session_id, find_active_by_user_course, expire_old_sessions, revoke, update_context_summary | | 2 | |
| T-002.2 | Implement `AIProposalRepository` with create, get_by_proposal_id, update_status, find_by_session, find_expired, mark_stale | | 2 | |
| T-002.3 | Implement `AIConfirmationTokenRepository` with create, get_by_token_id, consume, expire_old | | 1.5 | |
| T-002.4 | Implement `AIAuditRepository` with create, query (with filters + pagination), get_by_id | | 1.5 | |
| T-002.5 | Implement `AIOutboxRepository` with create, get_pending, mark_published, increment_retry | | 1 | |
| T-002.6 | Implement `AIChatTurnRepository` with create, list_by_session | | 1 | |
| T-002.7 | Implement `AIIdempotencyRepository` with get_by_key, set, delete_expired | | 1 | |
| T-003 | **Service Layer: Business logic** | Senior Backend Engineer | 8 | T-002 |
| T-003.1 | Create `app/services/ai/__init__.py` and `app/services/ai/config.py` | | 1 | |
| T-003.2 | Implement `AISessionService.create_session` with course existence validation, duplicate active session detection | | 1.5 | T-002.1 |
| T-003.3 | Implement `AISessionService.validate_session` with expiry + user mismatch checks | | 1 | T-002.1 |
| T-003.4 | Implement `ProposalService.create_proposal` with base_hash computation | | 1 | T-002.2 |
| T-003.5 | Implement `ProposalService.apply_proposal` with status transition, stale detection, idempotency check | | 2 | T-002.2, T-002.7 |
| T-003.6 | Implement `AuditService.log_operation` and `AuditService.query_logs` | | 1 | T-002.4 |
| T-003.7 | Implement `OutboxService.write_event`, `publish_pending`, `get_unpublished_count` | | 1.5 | T-002.5 |
| T-004 | **Transactional Apply Pipeline** | Senior Backend Engineer | 4 | T-003 |
| T-004.1 | Implement the single-transaction apply pipeline: (a) proposal state update, (b) domain mutation, (c) audit write, (d) outbox write, with rollback on any failure | | 3 | T-003.5, T-003.6, T-003.7 |
| T-004.2 | Implement idempotency key middleware/decorator for apply endpoint | | 1 | T-002.7 |
| T-005 | **Unit & Integration Tests** | QA Engineer / Backend Engineer | 10 | T-001, T-002, T-003 |
| T-005.1 | Write unit tests for all 7 repositories (CRUD, status transitions, expiration, edge cases) | | 4 | T-002 |
| T-005.2 | Write unit tests for all 4 services (session creation, proposal lifecycle, stale detection, confirmation flow, idempotency) | | 3 | T-003 |
| T-005.3 | Write integration tests for transactional apply, concurrent staleness, outbox publish cycle | | 2 | T-004 |
| T-005.4 | Write integration test for idempotency deduplication (same key, same body vs same key, different body) | | 1 | T-004.2 |
| T-006 | **Documentation & Compliance** | Technical Writer / Backend Engineer | 4 | T-001, T-004 |
| T-006.1 | Update `.env.example` with new AI configuration variables | | 0.5 | T-003.1 |
| T-006.2 | Add OpenAPI spec documentation for session endpoints | | 1 | T-003.2 |
| T-006.3 | Update architecture diagram to include new persistence tables | | 1 | |
| T-006.4 | Write README section on AI persistence design (session lifecycle, proposal lifecycle, audit/outbox) | | 1.5 | |
| T-007 | **Manual QA & Performance Verification** | QA Engineer | 4 | T-004, T-005 |
| T-007.1 | Execute all 37 steps of manual QA verification procedure, document results | | 2 | T-004 |
| T-007.2 | Run performance benchmarks for session creation, proposal apply, audit write at target loads | | 1 | T-004 |
| T-007.3 | Verify EXPLAIN ANALYZE shows index usage on all query patterns | | 0.5 | T-001.4 |
| T-007.4 | Verify non-regression: all existing course, page, import, export tests pass | | 0.5 | |

**Total estimated effort: 46 hours (~6 engineering days for a single developer)**

---

**End of US-BKND-AI-004 -- Add AI Persistence Foundations**

---