# US-AI-009 -- Implement Generic Proposal Lifecycle

**Priority:** MUST
**Depends on:** US-AI-004 (AI Session Management), US-AI-008 (AI Tool Contracts & Registry)
**Unlocks:** Create/update/delete proposals via AI agent
**Story Point Estimate:** 13 points (Engineering)

---

## 1. FUNCTIONAL SPECIFICATION

### 1.1 Detailed User Story

**As** an AI Course Authoring Agent (Claude),  
**I want** a generic proposal lifecycle engine that enforces a propose-validate-confirm-apply gating pattern,  
**So that** every page or course mutation passes through validation, human review, and explicit confirmation before the database is modified, ensuring no unintended mutations occur.

### 1.2 Numbered Functional Requirements

1. **FR001 -- Proposal Creation:** The system MUST accept a proposal payload containing an operation type (`create_page`, `update_page`, `delete_page`, `create_course`, `update_course`) and typed arguments, returning a unique `proposal_id` (UUID v4) and a computed `diff` without mutating any database row.

2. **FR002 -- Proposal Validation Pipeline:** Every proposal MUST pass through three sequential gates before being stored: (a) JSON schema validation against the target template's registered schema, (b) business rules validation (SCORM compliance, WCAG accessibility, required field checks, min/max cardinality), and (c) permission scoping (the targeted resource belongs to the session's course). A proposal that fails any gate MUST be rejected with a structured error response specifying the failing gate, field path, and a human-readable remediation hint.

3. **FR003 -- Proposal Storage:** Validated proposals MUST be persisted in a dedicated `proposals` database table with status `pending`, storing the full before-state snapshot (for updates/deletes), the proposed after-state (for creates/updates), the computed diff, the operation type, the session ID, the user ID, the course ID, and timestamps. Proposal TTL MUST be configurable (default 30 minutes, env var `PROPOSAL_TTL_MINUTES=30`).

4. **FR004 -- Proposal Confirmation (Apply):** Applying a proposal requires a second API call with `proposal_id` and `user_confirmed=true`. The system MUST verify: (a) the proposal exists and status is `pending`, (b) the proposal has not expired (TTL check), (c) the session/user/course context matches the original proposal, (d) the before-state snapshot still matches current DB state (optimistic concurrency check -- if the resource was modified by another actor since the proposal was created, the apply MUST fail with `CONFLICT_DETECTED`). On success, the operation is executed, the proposal status transitions to `applied`, and the after-state is persisted.

5. **FR005 -- Proposal Rejection/Cancellation:** A proposal MAY be explicitly cancelled by calling the reject endpoint. The system MUST transition the proposal status to `cancelled` and return the proposal metadata. Expired proposals MUST be automatically transitioned by a background sweep task (runnable via management command or Celery beat) from `pending` to `expired`. Idempotency: calling apply on an already-applied proposal MUST return success (same result) rather than erroring. Calling apply on a cancelled/expired proposal MUST return a structured `PROPOSAL_STALE` error.

6. **FR006 -- Proposal Diff Computation:** For updates, the system MUST compute a field-level diff between the current DB state and the proposed state, returning a `changed_fields` array and a `before`/`after` snapshot. For creates, the diff SHALL be the full proposed resource. For deletes, the diff SHALL be the full current state of the resource to be deleted. The diff SHALL be stored in the proposal record for auditability.

7. **FR007 -- Batch Proposal Support:** For operations affecting multiple resources (multi-page create, bulk update), the system MUST support a parent batch proposal containing child page-level proposals. The batch SHALL follow all-or-nothing semantics: either all child proposals apply successfully, or the entire batch transitions to `failed` with individual per-child error messages. The batch proposal SHALL have its own `batch_id` and status, and the child proposals SHALL reference it.

8. **FR008 -- Proposal Audit Trail:** Every status transition of a proposal (`created` -> `pending`, `pending` -> `applied`, `pending` -> `cancelled`, `pending` -> `expired`, `pending` -> `failed`) MUST be recorded in an `audit_log` table with the actor (session user ID), the transition timestamp, the previous and new status, and a reason string. This provides full traceability for compliance.

9. **FR009 -- Proposal Query/List:** The system MUST expose endpoints to list proposals filtered by status (`pending`, `applied`, `cancelled`, `expired`), by course ID, by session ID, and by date range, with pagination. This supports the AI chat UI's proposal review panel.

10. **FR010 -- Proposal Expiry Webhook/Callback:** When a proposal expires, the system SHOULD emit an event (in-process event bus) so that the AI session manager can notify the chat UI that a previously proposed change is no longer actionable. This is a soft requirement for MVP (can be a polling fallback).

### 1.3 Step-by-Step User Flow

#### Happy Path: Create Page via AI

```
1. User types in AI chat: "Add a new text-content page about data types"
2. AI Agent calls tool `propose_create_page` via POST /api/v1/ai/tools/propose_create_page
   Body: { sessionId, title: "Data Types Explained", templateType: "text-content", data: { content: "...", key_points: [...] } }
3. Backend ProposalService.create():
   a. Validates session exists & is active (US-AI-004)
   b. Validates template type is in allowed set (US-AI-008)
   c. Runs schema validation against registered text-content template schema
   d. Runs business rules: title length <= 200, content non-empty, key_points max 5
   e. Permissions: verify user owns session.course_id
   f. Computes diff (full proposed resource since this is a create)
   g. Persists proposal with status "pending"
   h. Returns { proposalId, previewPage: {...}, validationStatus: "valid", validationMessages: [] }
4. UI renders proposal preview panel showing the proposed new page
5. User reviews and clicks "Apply" in the UI
6. Frontend calls POST /api/v1/ai/proposals/{proposalId}/apply with body { userConfirmed: true }
7. Backend ProposalService.apply():
   a. Fetches proposal, checks status == "pending"
   b. Checks TTL: created_at + 30min >= now
   c. Optimistic concurrency: no before-state to compare (create)
   d. Executes: creates PageRecord + ComponentRecord in DB via PageRepository
   e. Transitions proposal status to "applied"
   f. Writes audit log entry
   g. Returns { pageId, status: "created" }
8. UI re-renders the course page list with the new page visible
```

#### Alternate Path: Validation Failure

```
1. User: "Add an assessment with 1 question"
2. AI calls propose_create_page with templateType "final-assessment", data with 1 question
3. Backend validates:
   a. Schema: valid JSON structure
   b. Business rules: FAILS -- "final-assessment requires at least 3 questions"
   c. Returns { proposalId, validationStatus: "error", validationMessages: [{ severity: "error", field: "data.questions", message: "Assessment must have at least 3 questions" }] }
4. AI receives error, adjusts data to 3 questions, re-calls propose_create_page
5. This time validation passes -> proposal created
```

#### Error Path: Stale Proposal (Optimistic Concurrency Failure)

```
1. User A proposes updating page X title to "New Title" (before-state: "Old Title")
2. User B (or another session) updates page X title to "Other Title" via manual editor
3. User A clicks "Apply"
4. Backend before-state check: DB current title "Other Title" != proposal before-state "Old Title"
5. Returns HTTP 409 with { code: "CONFLICT_DETECTED", message: "Page was modified since proposal was created. Please re-fetch and propose again." }
6. UI shows "This page has changed since your proposal. Please review current state and try again."
7. AI re-fetches page and creates a new proposal
```

#### Error Path: Expired Proposal

```
1. User creates a proposal (TTL = 30min)
2. User walks away for 45 minutes
3. Background sweep task transitions proposal to "expired"
4. User clicks "Apply"
5. Backend returns HTTP 410 with { code: "PROPOSAL_STALE", message: "Proposal has expired. Please create a new proposal." }
6. UI shows "This proposal is no longer available. Please ask the AI to create a new proposal."
7. AI re-proposes the change
```

### 1.4 UI/UX Requirements

1. **Proposal Preview Panel:** The AI chat UI MUST display a dedicated proposal preview panel (sidebar or modal) showing: operation type (create/update/delete), resource identification, computed diff (before/after or full preview), validation status badge (green=valid, yellow=warning, red=error), and validation messages list.

2. **Confirmation Gate for Destructive Ops:** Delete proposals MUST show a two-step confirmation in the UI: (a) initial preview of what will be deleted, (b) a confirmation modal with red "Confirm Delete" button and "Cancel" button. The apply call is only sent after the user clicks "Confirm Delete."

3. **Batch Proposal UI:** For multi-page operations, the UI MUST show a table with each child proposal's status (valid/error), title, template type, and an expandable diff row. The user sees a single "Apply All" button (disabled if any child is in error state).

4. **Proposal History:** The UI proposal panel MUST include a "History" tab showing previously applied proposals for the session, with expandable details showing the before/after diff. This supports undo awareness (actual undo is a future feature).

5. **Error Handling States:**
   - **Validation Error:** Red badge, list of errors with field paths, "Ask AI to fix" button
   - **Stale/Conflict:** Yellow badge, "Proposal out of date" message, "Re-fetch" button
   - **Expired:** Grey badge, "Proposal expired" message, "Ask AI to re-propose" button
   - **Server Error:** Red error state with retry button

---

## 2. TECHNICAL SPECIFICATION

### 2.1 API Contracts

#### 2.1.1 Create Proposal

```
POST /api/v1/ai/proposals
Headers:
  Authorization: Session {sessionId}
  Content-Type: application/json

Request Body:
{
  "session_id": "uuid-string",
  "operation": "create_page",                    // "create_page" | "update_page" | "delete_page" | "create_course" | "update_course"
  "resource_type": "page",                        // "page" | "course"
  "resource_id": "uuid-string | null",            // null for creates, existing UUID for updates/deletes
  "data": {                                        // operation-specific payload
    "title": "Data Types Explained",
    "template_type": "text-content",
    "data": {
      "content": "## Data Types\n\nIn programming...",
      "key_points": ["Integers", "Strings", "Booleans"]
    },
    "insert_at_index": 3
  },
  "parent_batch_id": "uuid-string | null"         // optional, for batch proposals
}

Response 201 Created:
{
  "proposal_id": "uuid-string",
  "batch_id": "uuid-string | null",
  "operation": "create_page",
  "resource_type": "page",
  "resource_id": "uuid-string | null",
  "status": "pending",
  "validation_status": "valid",                   // "valid" | "warning" | "error"
  "validation_messages": [
    {
      "severity": "error | warning | info",
      "code": "MISSING_REQUIRED_FIELD",
      "field": "data.content",
      "message": "Content field is required for text-content template",
      "hint": "Add non-empty content to the data.content field"
    }
  ],
  "diff": {                                        // operation-specific
    "before": null,                                // null for creates
    "after": {                                     // full proposed state
      "title": "Data Types Explained",
      "template_type": "text-content",
      "data": { "content": "...", "key_points": [...] }
    },
    "changed_fields": ["title", "template_type", "data"]
  },
  "preview": {                                     // human-readable preview
    "summary": "Create new page: 'Data Types Explained' (text-content)",
    "can_undo": true
  },
  "created_at": "2026-06-14T10:00:00Z",
  "expires_at": "2026-06-14T10:30:00Z"
}

Status Codes:
  201: Proposal created (may have validation warnings)
  400: BAD_REQUEST -- invalid payload structure
  401: UNAUTHORIZED -- missing/invalid session token
  403: FORBIDDEN -- resource does not belong to session's course
  422: UNPROCESSABLE_ENTITY -- schema validation failure (validationStatus: "error")
```

#### 2.1.2 Apply Proposal

```
POST /api/v1/ai/proposals/{proposal_id}/apply
Headers:
  Authorization: Session {sessionId}
  Content-Type: application/json

Request Body:
{
  "user_confirmed": true
}

Response 200 OK:
{
  "proposal_id": "uuid-string",
  "status": "applied",
  "result": {
    "resource_id": "uuid-string",
    "operation": "create_page",
    "resource_type": "page",
    "changes_summary": "Page 'Data Types Explained' created",
    "page_id": "uuid-string"                       // set for page operations
  },
  "applied_at": "2026-06-14T10:02:00Z"
}

Status Codes:
  200: Proposal applied successfully
  400: BAD_REQUEST -- user_confirmed is false or missing
  401: UNAUTHORIZED -- session mismatch
  403: FORBIDDEN -- proposal does not belong to session's course
  404: NOT_FOUND -- proposal_id does not exist
  409: CONFLICT_DETECTED -- before-state does not match current DB state
  410: GONE -- proposal is expired or cancelled (PROPOSAL_STALE)
  422: UNPROCESSABLE_ENTITY -- proposal status is not "pending"
```

#### 2.1.3 Cancel Proposal

```
POST /api/v1/ai/proposals/{proposal_id}/cancel
Headers:
  Authorization: Session {sessionId}
Content-Type: application/json

Request Body:
{
  "reason": "User decided not to proceed"
}

Response 200 OK:
{
  "proposal_id": "uuid-string",
  "status": "cancelled",
  "cancelled_at": "2026-06-14T10:05:00Z"
}

Status Codes:
  200: Cancelled
  401: UNAUTHORIZED
  404: NOT_FOUND
  422: Proposal already applied or expired
```

#### 2.1.4 List Proposals

```
GET /api/v1/ai/proposals?status=pending&course_id={courseId}&page=1&page_size=20
Headers:
  Authorization: Session {sessionId}

Response 200 OK:
{
  "items": [
    {
      "proposal_id": "uuid-string",
      "operation": "create_page",
      "resource_type": "page",
      "status": "pending",
      "validation_status": "valid",
      "summary": "Create page: 'Data Types Explained'",
      "created_at": "2026-06-14T10:00:00Z",
      "expires_at": "2026-06-14T10:30:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

#### 2.1.5 Get Proposal Detail

```
GET /api/v1/ai/proposals/{proposal_id}
Headers:
  Authorization: Session {sessionId}

Response 200 OK: (same shape as Create Proposal response)
```

#### 2.1.6 Create Batch Proposal

```
POST /api/v1/ai/proposals/batch
Headers:
  Authorization: Session {sessionId}
Content-Type: application/json

Request Body:
{
  "session_id": "uuid-string",
  "child_proposals": [
    { "operation": "create_page", "resource_type": "page", "data": {...} },
    { "operation": "create_page", "resource_type": "page", "data": {...} },
    { "operation": "update_page", "resource_type": "page", "resource_id": "uuid", "data": {...} }
  ]
}

Response 201 Created:
{
  "batch_id": "uuid-string",
  "status": "pending",
  "child_count": 3,
  "children_valid": 3,                            // count of valid children
  "children_invalid": 0,                          // count of children with errors
  "children": [
    { "proposal_id": "uuid-1", "status": "pending", "validation_status": "valid" },
    { "proposal_id": "uuid-2", "status": "pending", "validation_status": "valid" },
    { "proposal_id": "uuid-3", "status": "pending", "validation_status": "valid" }
  ],
  "created_at": "2026-06-14T10:00:00Z",
  "expires_at": "2026-06-14T10:30:00Z"
}
```

#### 2.1.7 Apply Batch Proposal

```
POST /api/v1/ai/proposals/batch/{batch_id}/apply
Headers:
  Authorization: Session {sessionId}
Content-Type: application/json

Request Body:
{
  "user_confirmed": true
}

Response 200 OK:
{
  "batch_id": "uuid-string",
  "status": "applied",                            // "applied" if all succeeded, "partial" if mixed
  "children": [
    { "proposal_id": "uuid-1", "status": "applied", "result": {...} },
    { "proposal_id": "uuid-2", "status": "applied", "result": {...} },
    { "proposal_id": "uuid-3", "status": "failed", "error": { "code": "CONFLICT_DETECTED", "message": "..." } }
  ],
  "applied_count": 2,
  "failed_count": 1
}
```

### 2.2 Database Schema DDL

```sql
-- ============================================================
-- Table: ai_proposals
-- Core proposal table for the propose-validate-confirm-apply lifecycle
-- ============================================================
CREATE TABLE ai_proposals (
    id                      SERIAL PRIMARY KEY,
    proposal_id             UUID NOT NULL DEFAULT gen_random_uuid(),
    batch_id                UUID,                           -- NULL for standalone, set for batch children
    parent_batch_id         UUID REFERENCES ai_proposals(proposal_id), -- NULL for top-level batch
    session_id              UUID NOT NULL,                  -- FK to ai_sessions
    user_id                 UUID NOT NULL,                  -- User who owns this proposal
    organization_id         UUID NOT NULL,
    course_id               VARCHAR(64) NOT NULL,           -- FK to courses.course_id
    
    -- Operation details
    operation               VARCHAR(32) NOT NULL,           -- 'create_page','update_page','delete_page','create_course','update_course'
    resource_type           VARCHAR(32) NOT NULL,           -- 'page','course'
    resource_id             VARCHAR(64),                    -- NULL for creates
    
    -- Proposal data
    data_before             JSONB,                          -- Full before-state snapshot (NULL for creates)
    data_after              JSONB,                          -- Proposed after-state (NULL for deletes)
    data_patch              JSONB,                          -- Original patch payload (for reference)
    diff                    JSONB NOT NULL,                 -- Computed diff: { before, after, changed_fields }
    
    -- Validation results
    validation_status       VARCHAR(16) NOT NULL DEFAULT 'pending', -- 'pending','valid','warning','error'
    validation_messages     JSONB DEFAULT '[]'::jsonb,
    
    -- Status lifecycle
    status                  VARCHAR(16) NOT NULL DEFAULT 'pending', -- 'pending','applied','cancelled','expired','failed'
    
    -- Timestamps
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at              TIMESTAMPTZ NOT NULL,          -- created_at + PROPOSAL_TTL_MINUTES
    applied_at              TIMESTAMPTZ,
    cancelled_at            TIMESTAMPTZ,
    
    -- Concurrency
    version                 INTEGER NOT NULL DEFAULT 1     -- Optimistic locking for status transitions
);

-- Indexes
CREATE UNIQUE INDEX idx_ai_proposals_proposal_id ON ai_proposals(proposal_id);
CREATE INDEX idx_ai_proposals_session_id ON ai_proposals(session_id);
CREATE INDEX idx_ai_proposals_course_id ON ai_proposals(course_id);
CREATE INDEX idx_ai_proposals_status ON ai_proposals(status);
CREATE INDEX idx_ai_proposals_expires_at ON ai_proposals(expires_at) WHERE status = 'pending';
CREATE INDEX idx_ai_proposals_batch_id ON ai_proposals(batch_id);
CREATE INDEX idx_ai_proposals_parent_batch_id ON ai_proposals(parent_batch_id);
CREATE INDEX idx_ai_proposals_user_id ON ai_proposals(user_id);
CREATE INDEX idx_ai_proposals_created_at ON ai_proposals(created_at DESC);

-- ============================================================
-- Table: ai_proposal_audit_log
-- Immutable audit trail for every proposal status transition
-- ============================================================
CREATE TABLE ai_proposal_audit_log (
    id                      SERIAL PRIMARY KEY,
    proposal_id             UUID NOT NULL REFERENCES ai_proposals(proposal_id),
    actor_user_id           UUID NOT NULL,
    actor_session_id        UUID,
    from_status             VARCHAR(16) NOT NULL,
    to_status               VARCHAR(16) NOT NULL,
    reason                  TEXT,
    metadata                JSONB DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_proposal_id ON ai_proposal_audit_log(proposal_id);
CREATE INDEX idx_audit_actor ON ai_proposal_audit_log(actor_user_id);
CREATE INDEX idx_audit_created_at ON ai_proposal_audit_log(created_at DESC);

-- ============================================================
-- Table: ai_sessions (reference -- defined in US-AI-004)
-- Included here for context. CREATE TABLE is in US-AI-004.
-- ============================================================
-- CREATE TABLE ai_sessions (
--     session_id          UUID PRIMARY KEY,
--     user_id             UUID NOT NULL,
--     course_id           VARCHAR(64) NOT NULL,
--     organization_id     UUID NOT NULL,
--     status              VARCHAR(16) DEFAULT 'active',  -- active, expired, terminated
--     created_at          TIMESTAMPTZ DEFAULT NOW(),
--     expires_at          TIMESTAMPTZ,
--     metadata            JSONB DEFAULT '{}'
-- );
```

### 2.3 Service/Module Design

Create new file: `app/services/ai/proposal_service.py`

```python
"""
Proposal Service -- orchestration of the propose-validate-confirm-apply lifecycle.

Manages proposal creation, validation, storage, confirmation, expiry, and
audit logging. Stateless service injected with repositories and validators.
"""

from __future__ import annotations
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Any
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.course_repo import CourseRepository, CourseNotFoundError
from app.repositories.page_component_repo import PageRepository
from app.services.ai.validation_pipeline import ValidationPipeline
from app.services.ai.diff_engine import DiffEngine


@dataclass
class ProposalConfig:
    ttl_minutes: int = 30
    max_validation_messages: int = 50
    max_child_proposals_per_batch: int = 50


class ProposalNotFoundError(Exception):
    pass

class ProposalStaleError(Exception):
    pass

class ProposalConflictError(Exception):
    pass

class ProposalValidationError(Exception):
    def __init__(self, messages: list[dict]):
        self.messages = messages
        super().__init__("Proposal validation failed")


class ProposalService:
    """Core service for proposal lifecycle management."""

    def __init__(
        self,
        session: AsyncSession,
        config: Optional[ProposalConfig] = None,
        validation_pipeline: Optional[ValidationPipeline] = None,
        diff_engine: Optional[DiffEngine] = None,
        course_repo: Optional[CourseRepository] = None,
        page_repo: Optional[PageRepository] = None,
    ):
        self.session = session
        self.config = config or ProposalConfig()
        self.validation_pipeline = validation_pipeline or ValidationPipeline()
        self.diff_engine = diff_engine or DiffEngine()
        self.course_repo = course_repo or CourseRepository(session)
        self.page_repo = page_repo or PageRepository(session)

    async def create_proposal(
        self,
        session_id: str,
        user_id: str,
        organization_id: str,
        course_id: str,
        operation: str,
        resource_type: str,
        resource_id: Optional[str],
        data: dict,
        parent_batch_id: Optional[str] = None,
    ) -> dict:
        """Create a proposal: validate -> compute diff -> persist -> return."""
        # 1. Permission: verify resource belongs to course
        await self._verify_resource_scope(course_id, resource_type, resource_id)

        # 2. Fetch before-state if applicable
        before_state = None
        if operation in ("update_page", "delete_page") and resource_id:
            if resource_type == "page":
                page = await self.page_repo.get(resource_id)
                if page:
                    before_state = page.to_dict()

        # 3. Run validation pipeline
        validation_result = await self.validation_pipeline.validate(
            operation=operation,
            resource_type=resource_type,
            data=data,
            course_id=course_id,
        )

        # 4. Compute diff
        diff = self.diff_engine.compute(
            operation=operation,
            before=before_state,
            after=data if operation in ("create_page", "update_page") else None,
        )

        # 5. Build after-state (for creates/updates)
        after_state = None
        if operation in ("create_page", "update_page"):
            if resource_type == "page":
                after_state = {
                    "title": data.get("title", ""),
                    "template_type": data.get("template_type", "text-content"),
                    "data": data.get("data", {}),
                }

        # 6. If validation has errors, still create proposal but mark as error
        proposal_status = "pending"
        has_errors = any(m["severity"] == "error" for m in validation_result.messages)

        # 7. Persist proposal
        now = datetime.now(timezone.utc)
        proposal_id = str(uuid.uuid4())
        proposal_record = await self._insert_proposal(
            proposal_id=proposal_id,
            batch_id=parent_batch_id,
            parent_batch_id=None,
            session_id=session_id,
            user_id=user_id,
            organization_id=organization_id,
            course_id=course_id,
            operation=operation,
            resource_type=resource_type,
            resource_id=resource_id,
            data_before=before_state,
            data_after=after_state,
            data_patch=data,
            diff=diff,
            validation_status="error" if has_errors else validation_result.status,
            validation_messages=validation_result.messages,
            status=proposal_status,
            expires_at=now + timedelta(minutes=self.config.ttl_minutes),
            created_at=now,
        )

        # 8. Audit log: created
        await self._write_audit_log(
            proposal_id=proposal_id,
            actor_user_id=user_id,
            actor_session_id=session_id,
            from_status=None,
            to_status="pending",
            reason="Proposal created",
        )

        return {
            "proposal_id": proposal_id,
            "operation": operation,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "status": proposal_record["status"],
            "validation_status": validation_result.status,
            "validation_messages": validation_result.messages,
            "diff": diff,
            "preview": {
                "summary": self._build_summary(operation, resource_type, data),
                "can_undo": operation != "delete_page",
            },
            "created_at": now.isoformat(),
            "expires_at": proposal_record["expires_at"].isoformat(),
        }

    async def apply_proposal(
        self,
        proposal_id: str,
        user_confirmed: bool,
        session_id: str,
        user_id: str,
    ) -> dict:
        """Apply a pending proposal if user_confirmed is true and state is valid."""
        if not user_confirmed:
            raise ValueError("user_confirmed must be true to apply proposal")

        # 1. Fetch proposal
        proposal = await self._get_proposal(proposal_id)
        if proposal is None:
            raise ProposalNotFoundError(f"Proposal {proposal_id} not found")

        # 2. Permission: verify session matches
        if proposal["session_id"] != session_id or proposal["user_id"] != user_id:
            raise PermissionError("Session does not own this proposal")

        # 3. Status check
        if proposal["status"] != "pending":
            raise ProposalStaleError(
                f"Proposal status is '{proposal['status']}', expected 'pending'"
            )

        # 4. TTL check
        now = datetime.now(timezone.utc)
        if now > proposal["expires_at"]:
            await self._transition_status(
                proposal_id, "pending", "expired", "Proposal expired (TTL reached)"
            )
            raise ProposalStaleError("Proposal has expired")

        # 5. Optimistic concurrency check
        if proposal["resource_id"] and proposal["data_before"]:
            await self._verify_no_conflict(
                proposal["resource_type"],
                proposal["resource_id"],
                proposal["data_before"],
            )

        # 6. Execute operation
        result = await self._execute_operation(
            operation=proposal["operation"],
            resource_type=proposal["resource_type"],
            resource_id=proposal["resource_id"],
            data_after=proposal["data_after"],
            data_before=proposal["data_before"],
            data_patch=proposal["data_patch"],
            course_id=proposal["course_id"],
        )

        # 7. Transition status
        await self._transition_status(
            proposal_id, "pending", "applied", "Applied successfully",
            metadata={"applied_at": now.isoformat(), "result": result},
        )

        # 8. Audit log
        await self._write_audit_log(
            proposal_id=proposal_id,
            actor_user_id=user_id,
            actor_session_id=session_id,
            from_status="pending",
            to_status="applied",
            reason="User confirmed",
        )

        return {
            "proposal_id": proposal_id,
            "status": "applied",
            "result": result,
            "applied_at": now.isoformat(),
        }

    async def cancel_proposal(
        self,
        proposal_id: str,
        reason: str,
        session_id: str,
        user_id: str,
    ) -> dict:
        """Cancel a pending proposal."""
        proposal = await self._get_proposal(proposal_id)
        if proposal is None:
            raise ProposalNotFoundError(f"Proposal {proposal_id} not found")

        if proposal["session_id"] != session_id:
            raise PermissionError("Session does not own this proposal")

        if proposal["status"] != "pending":
            raise ProposalStaleError(
                f"Cannot cancel proposal in status '{proposal['status']}'"
            )

        await self._transition_status(
            proposal_id, "pending", "cancelled", reason
        )
        await self._write_audit_log(
            proposal_id=proposal_id,
            actor_user_id=user_id,
            actor_session_id=session_id,
            from_status="pending",
            to_status="cancelled",
            reason=reason,
        )

        return {
            "proposal_id": proposal_id,
            "status": "cancelled",
            "cancelled_at": datetime.now(timezone.utc).isoformat(),
        }

    async def expire_stale_proposals(self) -> int:
        """Background sweep: transition expired-from-TTL proposals to 'expired'.
        
        Called periodically by a scheduler (Celery beat / cron).
        Returns count of proposals expired in this sweep.
        """
        now = datetime.now(timezone.utc)
        stmt = """
            UPDATE ai_proposals
            SET status = 'expired',
                updated_at = NOW()
            WHERE status = 'pending'
              AND expires_at < $1
            RETURNING proposal_id
        """
        # Execute via raw SQL or via ORM bulk update
        result = await self.session.execute(stmt, [now])
        expired_ids = result.fetchall()
        
        for row in expired_ids:
            await self._write_audit_log(
                proposal_id=row[0],
                actor_user_id="SYSTEM",
                actor_session_id=None,
                from_status="pending",
                to_status="expired",
                reason="Automatic TTL expiry sweep",
            )
        
        return len(expired_ids)

    async def list_proposals(
        self,
        course_id: Optional[str] = None,
        session_id: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """List proposals with filters and pagination."""
        conditions = ["1=1"]
        params = {}
        if course_id:
            conditions.append("course_id = :course_id")
            params["course_id"] = course_id
        if session_id:
            conditions.append("session_id = :session_id")
            params["session_id"] = session_id
        if status:
            conditions.append("status = :status")
            params["status"] = status

        where_clause = " AND ".join(conditions)
        offset = (page - 1) * page_size

        count_sql = f"SELECT COUNT(*) FROM ai_proposals WHERE {where_clause}"
        total = await self.session.execute(count_sql, params)
        
        sql = f"""
            SELECT proposal_id, operation, resource_type, status,
                   validation_status, created_at, expires_at
            FROM ai_proposals
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """
        params["limit"] = page_size
        params["offset"] = offset
        rows = await self.session.execute(sql, params)
        items = [dict(row) for row in rows]

        return {
            "items": items,
            "total": total.scalar(),
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, -(-total // page_size)),  # ceiling div
        }

    # -- Private helpers --------------------------------------------------

    async def _verify_resource_scope(
        self, course_id: str, resource_type: str, resource_id: Optional[str]
    ) -> None:
        """Verify that resource_id belongs to course_id (if resource_id provided)."""
        if not resource_id:
            return
        if resource_type == "page":
            page = await self.page_repo.get_by_course_and_page(course_id, resource_id)
            if not page:
                raise PermissionError(
                    f"Resource {resource_type}/{resource_id} does not belong to course {course_id}"
                )

    async def _verify_no_conflict(
        self, resource_type: str, resource_id: str, expected_before: dict
    ) -> None:
        """Optimistic concurrency: verify current state matches expected_before."""
        if resource_type == "page":
            page = await self.page_repo.get(resource_id)
            if page is None:
                raise ProposalConflictError("Resource no longer exists")
            current = page.to_dict()
            # Compare key fields
            if current.get("title") != expected_before.get("title"):
                raise ProposalConflictError(
                    "Resource was modified since proposal was created. "
                    "Please re-fetch and propose again."
                )

    async def _execute_operation(
        self, operation: str, resource_type: str,
        resource_id: Optional[str], data_after: Optional[dict],
        data_before: Optional[dict], data_patch: Optional[dict],
        course_id: str,
    ) -> dict:
        """Execute the actual database mutation."""
        if operation == "create_page" and resource_type == "page":
            page = await self.page_repo.create(
                PageRecord(
                    course_id=course_id,
                    title=data_after["title"],
                    order_index=data_patch.get("insert_at_index", 9999),
                )
            )
            return {"resource_id": page.page_id, "operation": "create_page",
                    "resource_type": "page", "changes_summary": f"Page '{data_after['title']}' created"}

        elif operation == "update_page" and resource_type == "page":
            page = await self.page_repo.get(resource_id)
            if "title" in data_after:
                page.title = data_after["title"]
            await self.page_repo.update(page)
            return {"resource_id": resource_id, "operation": "update_page",
                    "resource_type": "page", "changes_summary": "Page updated"}

        elif operation == "delete_page" and resource_type == "page":
            page = await self.page_repo.get(resource_id)
            await self.page_repo.delete(page)
            return {"resource_id": resource_id, "operation": "delete_page",
                    "resource_type": "page", "changes_summary": "Page deleted"}

        else:
            raise ValueError(f"Unsupported operation: {operation}/{resource_type}")

    async def _insert_proposal(self, **kwargs) -> dict:
        """Insert a proposal row via raw SQL or ORM."""
        # Implementation uses SQLAlchemy Core insert for performance
        stmt = """
            INSERT INTO ai_proposals
                (proposal_id, batch_id, parent_batch_id, session_id, user_id,
                 organization_id, course_id, operation, resource_type, resource_id,
                 data_before, data_after, data_patch, diff, validation_status,
                 validation_messages, status, expires_at, created_at)
            VALUES
                (:proposal_id, :batch_id, :parent_batch_id, :session_id, :user_id,
                 :organization_id, :course_id, :operation, :resource_type, :resource_id,
                 :data_before, :data_after, :data_patch, :diff, :validation_status,
                 :validation_messages, :status, :expires_at, :created_at)
            RETURNING *
        """
        result = await self.session.execute(stmt, kwargs)
        await self.session.commit()
        return dict(result.fetchone())

    async def _transition_status(
        self, proposal_id: str, from_status: str, to_status: str,
        reason: str, metadata: Optional[dict] = None,
    ) -> None:
        """Atomic status transition with optimistic locking."""
        sql = """
            UPDATE ai_proposals
            SET status = :to_status,
                updated_at = NOW(),
                version = version + 1
            WHERE proposal_id = :proposal_id
              AND status = :from_status
        """
        result = await self.session.execute(sql, {
            "proposal_id": proposal_id,
            "from_status": from_status,
            "to_status": to_status,
        })
        if result.rowcount == 0:
            raise ProposalStaleError(
                f"Could not transition proposal {proposal_id} from {from_status} to {to_status}"
            )
        await self.session.commit()

    async def _write_audit_log(
        self, proposal_id: str, actor_user_id: str,
        actor_session_id: Optional[str], from_status: Optional[str],
        to_status: str, reason: str,
    ) -> None:
        sql = """
            INSERT INTO ai_proposal_audit_log
                (proposal_id, actor_user_id, actor_session_id,
                 from_status, to_status, reason, created_at)
            VALUES
                (:proposal_id, :actor_user_id, :actor_session_id,
                 :from_status, :to_status, :reason, NOW())
        """
        await self.session.execute(sql, {
            "proposal_id": proposal_id,
            "actor_user_id": actor_user_id,
            "actor_session_id": actor_session_id,
            "from_status": from_status,
            "to_status": to_status,
            "reason": reason,
        })
        await self.session.commit()

    async def _get_proposal(self, proposal_id: str) -> Optional[dict]:
        sql = "SELECT * FROM ai_proposals WHERE proposal_id = :proposal_id"
        result = await self.session.execute(sql, {"proposal_id": proposal_id})
        row = result.fetchone()
        return dict(row) if row else None

    def _build_summary(self, operation: str, resource_type: str, data: dict) -> str:
        """Build a human-readable summary string."""
        title = data.get("title", "untitled")
        return f"{operation.replace('_', ' ').title()} {resource_type}: '{title}'"


class ValidationResult:
    """Result from the validation pipeline."""
    def __init__(self, status: str, messages: list[dict]):
        self.status = status  # 'valid', 'warning', 'error'
        self.messages = messages  # list of {severity, code, field, message, hint}
```

Create new file: `app/services/ai/diff_engine.py`

```python
"""Diff engine for computing structural diffs between resource states."""

from typing import Optional


class DiffEngine:
    """Computes field-level diffs for proposal previews."""

    def compute(
        self,
        operation: str,
        before: Optional[dict],
        after: Optional[dict],
    ) -> dict:
        """Compute diff based on operation type."""
        if operation == "create_page":
            return {
                "before": None,
                "after": after,
                "changed_fields": list(after.keys()) if after else [],
            }
        elif operation in ("update_page", "update_course"):
            before_fields = set(before.keys()) if before else set()
            after_fields = set(after.keys()) if after else set()
            changed = list(before_fields.symmetric_difference(after_fields) |
                          {k for k in before_fields & after_fields if before[k] != after[k]})
            return {
                "before": before,
                "after": after,
                "changed_fields": sorted(changed),
            }
        elif operation == "delete_page":
            return {
                "before": before,
                "after": None,
                "changed_fields": list(before.keys()) if before else [],
            }
        return {"before": before, "after": after, "changed_fields": []}
```

Create new file: `app/services/ai/validation_pipeline.py`

```python
"""Validation pipeline: schema -> business rules -> permissions."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ValidationMessage:
    severity: str  # 'error', 'warning', 'info'
    code: str
    field: str
    message: str
    hint: Optional[str] = None


@dataclass
class ValidationResult:
    status: str  # 'valid', 'warning', 'error'
    messages: list[ValidationMessage] = field(default_factory=list)


class ValidationPipeline:
    """Multi-stage validation pipeline."""

    # Template schema definitions (would come from TemplateRegistry in US-AI-008)
    TEMPLATE_SCHEMAS = {
        "text-content": {
            "required": ["content"],
            "max_lengths": {"title": 200},
            "rules": [
                {"field": "key_points", "max_items": 5, "code": "KEY_POINTS_MAX_EXCEEDED"},
            ],
        },
        "tabs": {
            "required": ["tabs"],
            "rules": [
                {"field": "tabs", "min_items": 2, "code": "TABS_MIN_EXCEEDED"},
                {"field": "tabs", "max_items": 6, "code": "TABS_MAX_EXCEEDED"},
            ],
        },
        "accordion": {
            "required": ["items"],
            "rules": [
                {"field": "items", "min_items": 2, "code": "ACCORDION_MIN_EXCEEDED"},
                {"field": "items", "max_items": 20, "code": "ACCORDION_MAX_EXCEEDED"},
            ],
        },
        "click-reveal": {
            "required": ["items"],
            "rules": [
                {"field": "items", "min_items": 2, "code": "CLICK_REVEAL_MIN_EXCEEDED"},
                {"field": "items", "max_items": 10, "code": "CLICK_REVEAL_MAX_EXCEEDED"},
            ],
        },
        "final-assessment": {
            "required": ["questions", "passing_score"],
            "rules": [
                {"field": "questions", "min_items": 3, "code": "ASSESSMENT_MIN_QUESTIONS"},
                {"field": "questions", "max_items": 50, "code": "ASSESSMENT_MAX_QUESTIONS"},
                {"field": "passing_score", "min": 0, "max": 100, "code": "PASSING_SCORE_RANGE"},
            ],
        },
    }

    async def validate(
        self,
        operation: str,
        resource_type: str,
        data: dict,
        course_id: str,
    ) -> ValidationResult:
        """Run the full validation pipeline. Returns validation result."""
        messages = []

        if resource_type == "page":
            template_type = data.get("template_type", "")
            template_data = data.get("data", {})

            # Stage 1: Schema validation (required fields, types)
            schema = self.TEMPLATE_SCHEMAS.get(template_type, {})
            if not schema and template_type:
                messages.append(ValidationMessage(
                    severity="error",
                    code="UNKNOWN_TEMPLATE_TYPE",
                    field="template_type",
                    message=f"Unknown template type: {template_type}",
                    hint="Use one of: text-content, tabs, accordion, click-reveal, final-assessment",
                ))

            if schema:
                for required_field in schema.get("required", []):
                    if required_field not in template_data or template_data[required_field] is None:
                        messages.append(ValidationMessage(
                            severity="error",
                            code="MISSING_REQUIRED_FIELD",
                            field=f"data.{required_field}",
                            message=f"Required field '{required_field}' is missing",
                            hint=f"Add a non-null value for 'data.{required_field}'",
                        ))

                # Title length check
                title = data.get("title", "")
                max_len = schema.get("max_lengths", {}).get("title", 200)
                if len(title) > max_len:
                    messages.append(ValidationMessage(
                        severity="error",
                        code="TITLE_TOO_LONG",
                        field="title",
                        message=f"Title exceeds max length of {max_len} characters",
                        hint=f"Shorten title to {max_len} characters or fewer",
                    ))

                # Business rules
                for rule in schema.get("rules", []):
                    field_name = rule["field"]
                    field_value = template_data.get(field_name)
                    if "min_items" in rule and isinstance(field_value, (list, tuple)):
                        if len(field_value) < rule["min_items"]:
                            messages.append(ValidationMessage(
                                severity="error",
                                code=rule["code"],
                                field=f"data.{field_name}",
                                message=f"'{field_name}' requires at least {rule['min_items']} items (got {len(field_value)})",
                                hint=f"Add more items to 'data.{field_name}'",
                            ))
                    if "max_items" in rule and isinstance(field_value, (list, tuple)):
                        if len(field_value) > rule["max_items"]:
                            messages.append(ValidationMessage(
                                severity="error",
                                code=rule["code"],
                                field=f"data.{field_name}",
                                message=f"'{field_name}' allows at most {rule['max_items']} items (got {len(field_value)})",
                                hint=f"Reduce items in 'data.{field_name}'",
                            ))

        # Determine overall status
        errors = [m for m in messages if m.severity == "error"]
        warnings = [m for m in messages if m.severity == "warning"]

        if errors:
            status = "error"
        elif warnings:
            status = "warning"
        else:
            status = "valid"

        return ValidationResult(
            status=status,
            messages=[m.__dict__ for m in messages],
        )
```

Create new router: `app/routers/ai_proposals.py`

```python
"""AI Proposal Lifecycle Router.

Endpoints:
  POST   /api/v1/ai/proposals              -> Create a new proposal
  GET    /api/v1/ai/proposals              -> List proposals
  GET    /api/v1/ai/proposals/{id}         -> Get proposal detail
  POST   /api/v1/ai/proposals/{id}/apply   -> Apply a proposal
  POST   /api/v1/ai/proposals/{id}/cancel  -> Cancel a proposal
  POST   /api/v1/ai/proposals/batch        -> Create batch proposal
  POST   /api/v1/ai/proposals/batch/{id}/apply -> Apply batch proposal
  POST   /api/v1/ai/proposals/expire-sweep -> Admin: expire stale proposals
"""
```

### 2.4 Configuration Variables

| ENV Variable | Type | Default | Description |
|---|---|---|---|
| `PROPOSAL_TTL_MINUTES` | int | `30` | Minutes before a pending proposal auto-expires |
| `PROPOSAL_MAX_BATCH_CHILDREN` | int | `50` | Max child proposals per batch |
| `PROPOSAL_MAX_VALIDATION_MSGS` | int | `50` | Max validation messages per proposal |
| `PROPOSAL_SWEEP_INTERVAL_MINUTES` | int | `5` | Interval (minutes) for the expiry sweep task |
| `AI_SESSION_HEADER_PREFIX` | string | `Session` | Auth header prefix for session tokens |

### 2.5 Integration Points

| Integration | Direction | Details |
|---|---|---|
| `SessionService` (US-AI-004) | INBOUND | ProposalService calls `session_service.validate_session(session_id)` to verify session is active and owns the course scope |
| `ToolContractRegistry` (US-AI-008) | INBOUND | ValidationPipeline fetches template schemas from `TemplateRegistry.get_schema(template_type)` for schema validation |
| `CourseRepository` | INBOUND | Fetches courses for scope verification |
| `PageRepository` / `ComponentRepository` | INBOUND | Fetches pages for before-state snapshots, applies mutations on confirmation |
| `TemplateTypeRepository` | INBOUND | Validates that `template_type` exists in `template_types` table |
| `AuditLogRepository` (net-new) | INBOUND | Writes audit log entries for proposal lifecycle events |
| `EventBus` (in-process, lightweight) | OUTBOUND | Emits `proposal.applied`, `proposal.expired`, `proposal.failed` events so the AI session manager can push updates to the chat UI |

---

## 3. NON-FUNCTIONAL REQUIREMENTS

### 3.1 Performance Targets

| Metric | Target | Measurement Method |
|---|---|---|
| **Proposal creation p50 latency** | < 200ms | Request-level tracing (OpenTelemetry) |
| **Proposal creation p95 latency** | < 500ms | Request-level tracing (OpenTelemetry) |
| **Proposal creation p99 latency** | < 1500ms | Request-level tracing (OpenTelemetry) |
| **Proposal apply p50 latency** | < 300ms (includes DB write) | Request-level tracing (OpenTelemetry) |
| **Proposal apply p95 latency** | < 800ms | Request-level tracing (OpenTelemetry) |
| **Proposal list (100 items) p50** | < 100ms | Request-level tracing (OpenTelemetry) |
| **Expiry sweep throughput** | 10,000 proposals/minute | Background job metric |
| **Concurrent proposal creations** | 50 req/s per instance | Load test |

### 3.2 Security Requirements

| Requirement | Implementation |
|---|---|
| **Session-bound authorization** | Every endpoint validates `session_id` in the `Authorization: Session {token}` header against the `ai_sessions` table. The session's `user_id` and `course_id` must match the proposal's. |
| **Resource scope enforcement** | Before creating a proposal, the service verifies that `resource_id` (if provided) belongs to `course_id` by querying the pages table. |
| **Input validation** | All input fields are validated via Pydantic schemas at the router layer (type coercion, length limits, allowed enum values for `operation`, `resource_type`, `template_type`). |
| **SQL injection prevention** | All DB queries use parameterized SQL (SQLAlchemy ORM or raw SQL with bound parameters). No string concatenation. |
| **Rate limiting** | Per-session: max 30 proposal creations per minute (configurable via `AI_RATE_LIMIT_PROPOSALS_PER_MIN`). Implemented via middleware or decorator. |
| **Tenant isolation** | `organization_id` is stored on every proposal. Multi-tenant queries always filter by `organization_id` (implicitly via session context). |
| **Audit trail integrity** | The `ai_proposal_audit_log` table is append-only. There is no UPDATE or DELETE path for audit log rows. |
| **TTL enforcement** | Expired proposals cannot be applied, even if the sweep job hasn't run yet (checked inline in `apply_proposal`). |

### 3.3 Reliability

| Aspect | Detail |
|---|---|
| **Error codes catalog** | All errors use a consistent `{ "code": "SNAKE_CASE_CODE", "message": "...", "details": {...} }` envelope. Catalog: `PROPOSAL_NOT_FOUND` (404), `PROPOSAL_STALE` (410), `CONFLICT_DETECTED` (409), `PROPOSAL_VALIDATION_ERROR` (422), `SESSION_INVALID` (401), `PERMISSION_DENIED` (403), `RATE_LIMIT_EXCEEDED` (429), `INTERNAL_ERROR` (500). |
| **Retry strategy** | Idempotent apply: calling `apply_proposal` on an already-applied proposal returns the same successful response (idempotency key). Non-idempotent create: proposal creation is NOT auto-retried -- the client must supply a new payload. |
| **Graceful degradation** | If the validation pipeline's schema registry is unavailable, proposals should still be created with `validation_status: "pending"` and the background validation should be attempted asynchronously (future enhancement). For MVP: fail closed (return error). |
| **Idempotency guarantees** | `apply_proposal` is idempotent -- applying the same proposal multiple times yields the same result. `create_proposal` is NOT idempotent (each call creates a new proposal). |
| **Transaction atomicity** | All operations that mutate multiple tables (e.g., creating a proposal + writing audit log) are wrapped in a single DB transaction. If any step fails, the entire transaction is rolled back. |
| **Deadline propagation** | All async calls within the proposal service use a 10-second timeout for DB operations, propagated via `asyncio.wait_for`. |

### 3.4 Scalability

| Requirement | Implementation |
|---|---|
| **Statelessness** | `ProposalService` is fully stateless -- all state is in PostgreSQL. Any instance can serve any request. No local cache. |
| **Horizontal scaling** | No shared memory or filesystem dependency. The expiry sweep must be run by exactly one instance (use PostgreSQL advisory lock `pg_try_advisory_lock` or a distributed lock). |
| **Connection pooling** | The proposal service uses the existing `AsyncSession` from `app.db.config`, which is backed by SQLAlchemy's connection pool (`pool_size=10`, `max_overflow=20`, `pool_recycle=3600`). No additional pool is created. |
| **Read replicas** | Proposal listing queries (`SELECT` from `ai_proposals` and `ai_proposal_audit_log`) are read-replica safe. Proposal creation and apply (`INSERT`, `UPDATE`) must go to the primary writer. |

---

## 4. CURRENT STATE ASSESSMENT

### 4.1 What Exists That Can Be Reused

| File/Component | Reuse Description |
|---|---|
| `app/repositories/course_repo.py` | `CourseRepository.get_by_course_id()` -- used to verify course exists during proposal scope check |
| `app/repositories/page_component_repo.py` | `PageRepository` -- full CRUD for pages and components. Used during apply to create/update/delete actual rows. `get_by_course_and_page()` for scope verification. |
| `app/repositories/template_type_repo.py` | `TemplateTypeRepository` -- used to verify template types exist during schema validation |
| `app/models/persisted_course.py` | `CourseRecord` -- the target table for course-level proposals |
| `app/models/page_component.py` | `PageRecord`, `ComponentRecord` -- the target tables for page-level proposals |
| `app/db/config.py` | `get_session()` dependency, engine configuration, connection pool settings |
| `app/routers/page_components.py` | Proven patterns for page/component CRUD -- the `apply` step will call the same repository methods |
| `app/main.py` | Router registration pattern (include router with prefix) |
| `docs/AI_Implemenation/01_SystemArchitecture/TOOL_SCHEMAS_CLAUDE_NATIVE.md` | Pre-defined tool schemas for `propose_create_page`, `propose_update_page`, `propose_delete_page`, `apply_page_proposal`, `apply_update_proposal`, `confirm_delete_page` -- these define the exact input/output contracts the proposal service must satisfy |

### 4.2 What Must Be Built Net-New

| Component | Location | Description |
|---|---|---|
| `app/services/ai/proposal_service.py` | New file | Core `ProposalService` class with `create_proposal()`, `apply_proposal()`, `cancel_proposal()`, `list_proposals()`, `expire_stale_proposals()`, and their helper methods |
| `app/services/ai/diff_engine.py` | New file | `DiffEngine.compute()` -- computes structural before/after diffs |
| `app/services/ai/validation_pipeline.py` | New file | `ValidationPipeline.validate()` -- multi-stage validation (schema, business rules) with `ValidationResult` dataclass |
| `app/routers/ai_proposals.py` | New file | FastAPI router with all proposal lifecycle endpoints |
| `app/models/ai_proposal.py` | New file | SQLAlchemy ORM model for `ai_proposals` table |
| `app/models/ai_proposal_audit_log.py` | New file | SQLAlchemy ORM model for `ai_proposal_audit_log` table |
| `app/repositories/ai_proposal_repo.py` | New file | `AIProposalRepository` -- data access for proposals (though ProposalService may use raw SQL for complex queries) |
| `app/repositories/ai_proposal_audit_repo.py` | New file | `AIProposalAuditRepository` -- append-only audit log writes and reads |
| `app/services/ai/__init__.py` | New file | Package init for AI services |
| Alembic migration | New migration | `CREATE TABLE ai_proposals` and `CREATE TABLE ai_proposal_audit_log` |
| Feature flag `AI_PROPOSALS_ENABLED` | Config | Boolean env var to enable/disable proposal endpoints (default: false) |

### 4.3 What Must Be Modified (with Non-Regression Constraints)

| File | Modification | Non-Regression Constraint |
|---|---|---|
| `app/main.py` | Add `from app.routers.ai_proposals import router as ai_proposals_router` and `api_router.include_router(ai_proposals_router)` | Must NOT change existing route order or prefix. Imported models in `lifespan` must still import successfully. Custom OpenAPI function must still work. |
| `app/main.py` (lifespan) | Import `app.models.ai_proposal` and `app.models.ai_proposal_audit_log` so `Base.metadata.create_all` picks up new tables | Must not break existing table creation. Must continue to swallow startup errors gracefully (current `except Exception: continue` behavior). |
| `app/models/persisted_course.py` | No change needed | Existing CourseRecord structure preserved |
| `app/models/page_component.py` | No change needed | Existing PageRecord/ComponentRecord unchanged |
| `app/repositories/course_repo.py` | No change needed | Existing repository contracts preserved |
| `app/repositories/page_component_repo.py` | No change needed | Existing CRUD methods used as-is |

---

## 5. EXPANSION POINTS

### 5.1 Technical Expansions (Future Sprints)

1. **Proposal Comparison/Undo System:** Build a proposal-based undo capability where each `applied` proposal stores enough state to produce an inverse "undo proposal." This gives users one-click undo for AI-driven changes. Requires storing full before-state on every applied proposal (already done for updates/deletes) and an `undo_proposal_id` field.

2. **Async/Human-in-the-Loop Proposals:** For complex operations (like file ingestion proposing 50 pages), make proposal creation fully async. The `create_proposal` endpoint returns immediately with `status: "validating"`, and a background worker runs the validation pipeline. The frontend polls `GET /proposals/{id}` until `validation_status` is no longer `"validating"`. The event bus fires a `proposal.validated` event when done.

3. **Distributed Proposal Expiry Sweep:** Replace the single-instance sweep with a distributed lock (PostgreSQL advisory lock or Redis Redlock) to ensure exactly one instance runs the sweep in a multi-replica deployment. Add OpenTelemetry metrics for sweep duration and count.

4. **Proposal TTL Extension:** Allow the AI session to extend a proposal's TTL (up to a max of 2 hours) if the user is actively reviewing it. Track TTL extension count and total extended time in audit log.

5. **WebSocket-based Proposal Push:** Instead of polling, push proposal status changes (applied, expired, failed) to the chat UI via WebSocket. The event bus emits `proposal.{event}` events that the WebSocket handler forwards.

### 5.2 Functional Expansions (Future Sprints)

1. **Multi-Course Proposals:** Allow proposals that span multiple courses (e.g., copy page from course A to course B). The resource scope check must be relaxed for cross-course operations, and the session must be authorized for both courses.

2. **Scheduled Proposal Apply:** Allow proposals to be created with `scheduled_apply_at` timestamp. The system auto-applies them at the scheduled time via a background job. Useful for "publish this update next Monday at 9 AM."

3. **Collaborative Proposals:** Allow multiple users to review/approve a single proposal. Each user must confirm before the proposal is applied. Track `required_confirmation_count` and `confirmed_by` array. This supports compliance workflows where changes require manager approval.

4. **Proposal Templates:** Pre-defined proposal templates for common operations like "add assessment at end of course" that auto-populate the data payload. The AI agent selects the template and fills in parameters.

5. **Proposal Rollback:** One-click rollback of an applied proposal by executing the inverse operation using the stored `data_before` snapshot. The rollback is itself a proposal that goes through the same lifecycle.

---

## 6. VALIDATION & TESTING

### 6.1 Unit Test Scenarios

| # | Test Name | Input | Expected Output |
|---|---|---|---|
| UT1 | `test_create_proposal_valid_page` | `operation="create_page"`, `resource_type="page"`, `data={"title": "Intro", "template_type": "text-content", "data": {"content": "Hello", "key_points": ["A"]}}` | Returns `proposal_id`, `status="pending"`, `validation_status="valid"`, `diff.after` contains full proposed state, `diff.before` is `null`, `preview.summary` contains "Create Page: 'Intro'" |
| UT2 | `test_create_proposal_validation_error` | `operation="create_page"`, `resource_type="page"`, `data={"title": "Assess", "template_type": "final-assessment", "data": {"questions": [{"q": "only one"}], "passing_score": 70}}` | Returns `proposal_id`, `validation_status="error"`, `validation_messages` contains error with code `ASSESSMENT_MIN_QUESTIONS` and field `data.questions`, message says "requires at least 3 items" |
| UT3 | `test_apply_proposal_success` | Mock a pending proposal in DB. Call `apply_proposal(proposal_id, user_confirmed=True, ...)` | Returns `status="applied"`, `result.resource_id` is set, `result.changes_summary` is non-empty. Proposal DB row has `status="applied"`. Audit log has entry `from_status=null/pending, to_status="applied"`. |
| UT4 | `test_apply_proposal_expired` | Mock a pending proposal with `expires_at` in the past. Call `apply_proposal(...)` | Raises `ProposalStaleError` with message containing "expired". Proposal DB row has `status="expired"` (auto-transitioned during the check). |
| UT5 | `test_apply_proposal_conflict_detected` | Mock a pending proposal with `data_before={"title": "Old"}`. Current DB state has `title: "New"` (modified by another session). Call `apply_proposal(...)` | Raises `ProposalConflictError` with message "Resource was modified since proposal was created". Proposal stays `status="pending"`. |
| UT6 | `test_cancel_proposal` | Create a valid proposal. Call `cancel_proposal(proposal_id, reason="User changed mind", ...)` | Returns `status="cancelled"`. DB row has `status="cancelled"`. Audit log has entry `from_status="pending", to_status="cancelled", reason="User changed mind"`. |
| UT7 | `test_diff_engine_create` | `DiffEngine.compute("create_page", None, {"title": "X", "data": {}})` | Returns `{"before": None, "after": {"title": "X", "data": {}}, "changed_fields": ["title", "data"]}` |
| UT8 | `test_diff_engine_update` | `DiffEngine.compute("update_page", {"title": "A"}, {"title": "B"})` | Returns `{"before": {"title": "A"}, "after": {"title": "B"}, "changed_fields": ["title"]}` |
| UT9 | `test_list_proposals_filters` | Insert 3 proposals: 2 pending, 1 applied. Call `list_proposals(status="pending")` | Returns `items` array with 2 entries, `total=2`. Each entry has `status="pending"`. |
| UT10 | `test_expire_stale_proposals_sweep` | Insert 2 pending proposals: one with `expires_at` in future, one with `expires_at` in past. Call `expire_stale_proposals()` | Returns `expired_count=1`. The stale proposal's DB row has `status="expired"`. The valid proposal is unchanged. |

### 6.2 Integration Test Scenarios

| # | Test Name | Steps | Expected Outcome |
|---|---|---|---|
| IT1 | `test_proposal_to_apply_end_to_end` | 1. Create a course via `POST /api/v1/courses`. 2. Create an AI session via `POST /api/v1/ai/sessions` (US-AI-004). 3. `POST /api/v1/ai/proposals` with `operation="create_page"`. 4. Verify response has `validation_status="valid"` and `status="pending"`. 5. `POST /api/v1/ai/proposals/{id}/apply` with `user_confirmed=true`. 6. `GET /api/v1/courses/{courseId}/pages` | Step 6 returns an array containing 1 page with the proposed title. The page is persisted in `pages` and `components` tables. |
| IT2 | `test_batch_proposal_all_or_nothing` | 1. Create course + session. 2. `POST /api/v1/ai/proposals/batch` with 3 child proposals (2 valid, 1 invalid -- e.g., assessment with 1 question). 3. Verify batch status is `pending`, children_valid=2, children_invalid=1. 4. `POST /api/v1/ai/proposals/batch/{batch_id}/apply` with `user_confirmed=true`. | Returns `status="partial"` or `status="failed"` (depending on MVP choice -- all-or-nothing means failed). No pages are created. The batch child proposals show their individual statuses. |
| IT3 | `test_proposal_permission_scope` | 1. Create course A and course B. 2. Create session for course A. 3. `POST /api/v1/ai/proposals` with `resource_type="page"`, `resource_id`=ID of a page that belongs to course B. | Returns HTTP 403 with `code="PERMISSION_DENIED"`. No proposal is created. |

### 6.3 E2E/Acceptance Test Scenarios

| # | Test Name | Steps | Expected Outcome |
|---|---|---|---|
| E2E1 | `Full AI create-page lifecycle` | 1. Open course in authoring UI. 2. Open AI chat panel. 3. Type "Add a text-content page about networking basics." 4. AI calls `propose_create_page`. 5. UI shows proposal preview panel with green "valid" badge and page preview. 6. User clicks "Apply." 7. Page appears in the page list. 8. User navigates to the new page. 9. Page content matches the AI proposal. | Page count increments by 1. New page has correct title, template type, and content. No unintended side effects on other pages. |
| E2E2 | `AI update-page with conflict` | 1. Start AI session on a course. 2. AI proposes updating page X title. 3. Before user applies, manually edit page X title via the regular editor (simulating another user). 4. User clicks "Apply" on the proposal. | UI shows "This page has changed since your proposal" message with a "Re-fetch" button. Page X title remains as manually set. AI is notified and re-fetches to create a new proposal. |

### 6.4 Manual QA Verification Procedure

1. **Feature Flag Check:** Set `AI_PROPOSALS_ENABLED=false`. Verify that all proposal endpoints return 404 or 403. Verify that existing course CRUD is unaffected.

2. **Proposal Creation (Valid):** Using the API directly (curl or Swagger UI), create a valid proposal for a text-content page. Verify the response structure matches the contract exactly, including `proposal_id`, `diff`, `preview`, `expires_at`.

3. **Proposal Creation (Invalid):** Create a proposal with an assessment template that has only 1 question. Verify the response has `validation_status: "error"` and the validation messages array contains the `ASSESSMENT_MIN_QUESTIONS` error.

4. **Proposal Apply:** Apply a valid proposal. Then `GET /api/v1/courses/{courseId}/pages` and verify the page was created. Then verify the proposal's status is now `applied` by fetching it again.

5. **Idempotent Apply:** Call apply again with the same `proposal_id`. Verify it returns the same successful response (200, not error) -- the proposal stays `applied`.

6. **Proposal Cancel:** Create a proposal. Cancel it. Verify it returns `cancelled`. Call apply on it -- verify it returns 410 `PROPOSAL_STALE`.

7. **Proposal Expiry:** Create a proposal. Wait for TTL + 1 minute (or simulate by running the sweep). Call apply -- verify 410 `PROPOSAL_STALE` with message "expired". Verify the sweep logged the transition.

8. **Stale Concurrency:** Create a proposal updating a page title. Manually update the page title via `PATCH /courses/{courseId}/pages/{pageId}`. Call apply on the proposal -- verify HTTP 409 with `CONFLICT_DETECTED`.

9. **Proposal Listing:** Create multiple proposals with different statuses. Call `GET /api/v1/ai/proposals?status=pending` and verify only pending proposals are returned. Verify pagination works correctly.

10. **Audit Trail:** Create, apply, and cancel proposals. Query the `ai_proposal_audit_log` table directly (or via a future admin endpoint) and verify each status transition is recorded with the correct actor, timestamp, and reason.

---

## 7. DEFINITION OF DONE

1. **[CODE]** `app/services/ai/proposal_service.py` is implemented with all methods described in section 2.3.
2. **[CODE]** `app/services/ai/validation_pipeline.py` is implemented with validation rules for all 5 template types (text-content, tabs, accordion, click-reveal, final-assessment).
3. **[CODE]** `app/services/ai/diff_engine.py` is implemented and produces correct before/after/changed_fields diffs for creates, updates, and deletes.
4. **[CODE]** `app/routers/ai_proposals.py` is implemented with all 7 endpoint handlers, all Pydantic request/response models, proper error handling, and session auth extraction.
5. **[CODE]** `app/models/ai_proposal.py` and `app/models/ai_proposal_audit_log.py` SQLAlchemy ORM models exist and are registered in `Base.metadata`.
6. **[DB]** Alembic migration (or auto-create via `Base.metadata.create_all`) creates the `ai_proposals` and `ai_proposal_audit_log` tables with all indexes. Migration is verified to be idempotent.
7. **[REGISTRATION]** `app/main.py` includes the new router and imports the new models in the lifespan. No existing routes are broken.
8. **[TEST]** At least 10 unit tests covering: proposal creation (valid/invalid), apply (success/expired/conflict), cancel, diff computation, listing, and expiry sweep. All tests pass.
9. **[TEST]** At least 3 integration tests covering: end-to-end proposal-to-apply lifecycle, batch proposal all-or-nothing semantics, and permission scope enforcement.
10. **[DOC]** API contracts are documented (OpenAPI spec updated or inline docs annotated with `description=` and proper response models). The architecture document `PRODUCTION_READY_AI_AUTHORING_ARCHITECTURE.md` is cross-referenced with this story.
11. **[FEATURE FLAG]** The proposal endpoints are toggled by environment variable `AI_PROPOSALS_ENABLED` (default: `false`). When disabled, endpoints return 404.
12. **[QA]** Manual QA verification procedure (section 6.4) passes for all 10 scenarios.
13. **[PERFORMANCE]** Proposal creation p50 latency < 200ms (measured on a development environment with local PostgreSQL).
14. **[SECURITY]** Session auth is enforced on every endpoint. Resource scope is verified before every proposal creation. SQL injection vectors are eliminated (parameterized queries only).

---

## 8. TASKS & SUB-TASKS

| ID | Description | Owner Role | Est. Hours | Dependencies |
|---|---|---|---|---|
| T-001 | **Create database models and migration** -- Implement ORM models for `ai_proposals` and `ai_proposal_audit_log` tables in `app/models/ai_proposal.py` and `app/models/ai_proposal_audit_log.py`. Create Alembic migration. Register models in `app/main.py` lifespan. | Backend Engineer | 4 | US-AI-004, US-AI-008 |
| T-002 | **Implement validation pipeline** -- Implement `app/services/ai/validation_pipeline.py` with `ValidationPipeline.validate()` that runs schema validation, required field checks, min/max cardinality rules for all 5 template types, and permission scoping. Implement `ValidationResult` dataclass. Write unit tests (UT2, related validation scenarios). | Backend Engineer | 6 | US-AI-008 (template schema registry) |
| T-003 | **Implement diff engine** -- Implement `app/services/ai/diff_engine.py` with `DiffEngine.compute()` that handles create (full after-state), update (field-level before/after comparison), and delete (full before-state) diffs. Write unit tests (UT7, UT8). | Backend Engineer | 3 | None |
| T-004 | **Implement core proposal service** -- Implement `app/services/ai/proposal_service.py` with `ProposalService.create_proposal()`, `apply_proposal()`, `cancel_proposal()`, `list_proposals()`, `expire_stale_proposals()`, all private helper methods, error classes (`ProposalNotFoundError`, `ProposalStaleError`, `ProposalConflictError`, `ProposalValidationError`), and `ProposalConfig` dataclass. Write unit tests (UT1, UT3, UT4, UT5, UT6, UT9, UT10). | Backend Engineer | 10 | T-001, T-002, T-003 |
| T-005 | **Implement REST router and integration** -- Implement `app/routers/ai_proposals.py` with all 7 endpoints, Pydantic request/response DTOs (using models from `app/models/course.py` patterns), session auth extraction from `Authorization: Session {token}` header, proper HTTP status codes, error envelope consistency, and feature flag `AI_PROPOSALS_ENABLED`. Register router in `app/main.py`. Write integration tests (IT1, IT2, IT3). | Backend Engineer | 6 | T-004 |
| T-006 | **Write E2E tests and perform QA verification** -- Write automated E2E tests for the two scenarios in section 6.3. Execute manual QA verification from section 6.4 (10 scenarios). Document any issues found. | QA Engineer | 4 | T-005 |
| T-007 | **Performance benchmarking and tuning** -- Measure proposal creation and apply latency against targets (section 3.1). Profile DB query performance. Add missing indexes if needed. Verify connection pool behavior under load. | Backend Engineer | 4 | T-005 |
| T-008 | **Documentation and OpenAPI spec update** -- Update API documentation (inline docstrings, response model annotations). Ensure `openapi.json` includes all new endpoints with correct schemas. Cross-reference this story's contracts in `PRODUCTION_READY_AI_AUTHORING_ARCHITECTURE.md` and `TOOL_SCHEMAS_CLAUDE_NATIVE.md`. | Tech Writer / Engineer | 3 | T-005 |

---

**File paths for implementation:**
- New: `C:\Users\ADMIN\e-learning-backend\app\services\ai\proposal_service.py`
- New: `C:\Users\ADMIN\e-learning-backend\app\services\ai\validation_pipeline.py`
- New: `C:\Users\ADMIN\e-learning-backend\app\services\ai\diff_engine.py`
- New: `C:\Users\ADMIN\e-learning-backend\app\services\ai\__init__.py`
- New: `C:\Users\ADMIN\e-learning-backend\app\routers\ai_proposals.py`
- New: `C:\Users\ADMIN\e-learning-backend\app\models\ai_proposal.py`
- New: `C:\Users\ADMIN\e-learning-backend\app\models\ai_proposal_audit_log.py`
- New: `C:\Users\ADMIN\e-learning-backend\app\repositories\ai_proposal_repo.py`
- New: `C:\Users\ADMIN\e-learning-backend\app\repositories\ai_proposal_audit_repo.py`
- Modified: `C:\Users\ADMIN\e-learning-backend\app\main.py` (register router, import models in lifespan)
- Reference: `C:\Users\ADMIN\e-learning-backend\app\repositories\course_repo.py` (existing, used as-is)
- Reference: `C:\Users\ADMIN\e-learning-backend\app\repositories\page_component_repo.py` (existing, used as-is)
- Reference: `C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\01_SystemArchitecture\TOOL_SCHEMAS_CLAUDE_NATIVE.md` (tool contract specs)

---