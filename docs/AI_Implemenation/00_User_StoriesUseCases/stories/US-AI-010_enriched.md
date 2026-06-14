# US-AI-010 - Apply Proposals with Idempotency, Audit, and Outbox Events

**Priority:** MUST | **Depends on:** US-AI-009 | **Unlocks:** US-AI-011 (Create), US-AI-012 (Update), US-AI-013 (Delete)

---

## 1. FUNCTIONAL SPECIFICATION

**User Story**

As an Admin, I want applied AI changes to be transactional, auditable, and published to downstream systems, so that AI mutations are safe, traceable, and recoverable in production.

**Problem Statement**

After a proposal is created (US-AI-009), the user reviews it and sends an apply request. Without a rigorous apply layer, double-submits can create duplicate pages, network failures can leave partial writes, there is no record of who changed what, and downstream systems (search index, analytics) have no way to discover AI-authored changes. The apply layer must guarantee exactly-once semantics, full auditability, and event-driven integration.

### 1.1 Numbered Functional Requirements

1. **FR-APPLY-001** — **Transactional Apply**: The apply endpoint must execute proposal status update, domain mutation, audit log write, and outbox event write within a single database transaction. If any step fails, the entire transaction rolls back.

2. **FR-APPLY-002** — **Idempotent Apply by Idempotency Key**: Each apply request must accept an optional `idempotency_key` header/field. When the same key is provided for a subsequent request within the key TTL window (default 24 hours), the server returns the original response without re-executing the mutation. Idempotency keys are generated server-side as part of the proposal record and may also be provided by the frontend for client-side retry safety.

3. **FR-APPLY-003** — **One-Time Proposal Apply**: A proposal must be applied at most once. After a successful apply, the proposal state transitions to `APPLIED` and any further apply attempt with that `proposal_id` returns a 409 Conflict with code `PROPOSAL_ALREADY_APPLIED`.

4. **FR-APPLY-004** — **Proposal State Revalidation on Apply**: Before executing the mutation, the apply service must revalidate: (a) proposal ownership (session, user, course match), (b) proposal TTL expiry, (c) base hash match against current database state (staleness detection), (d) confirmation token validity when `user_confirmed=true`, and (e) idempotency key cache.

5. **FR-APPLY-005** — **Staleness Detection via Base Hash**: When a proposal is created (US-AI-009), the current database state is hashed (e.g., SHA-256 of page `updatedAt` timestamps or a deterministic content hash). On apply, if the current hash differs from the proposal's `base_hash`, the apply is rejected with a 409 Conflict and the server returns the current state so a new proposal can be created.

6. **FR-APPLY-006** — **Post-Apply Validation**: After the mutation executes but before the transaction commits, the apply layer must re-run validation on the changed scope (page/component that was mutated). If validation fails, the transaction is rolled back and the error is returned to the caller.

7. **FR-APPLY-007** — **Audit Log Write**: After a successful mutation and within the same transaction, an audit record must be written containing: `user_id`, `session_id`, `proposal_id`, `operation` (create/update/delete), `resource_type` (page/component/course), `resource_id`, `before_snapshot`, `after_snapshot`, `validation_summary` (errors+warnings from proposal), `confirmation_token`, `idempotency_key`, `model_metadata` (tool schema version, template schema version), `trace_id`, and `timestamp`.

8. **FR-APPLY-008** — **Outbox Event Write**: Within the same transaction as the mutation and audit log, an outbox event must be written with `event_type` (e.g., `PageCreatedByAI`, `PageUpdatedByAI`, `PageDeletedByAI`), `event_version` (integer, starting at 1), `aggregate_id` (page_id or course_id), `payload` (minimal data needed by consumers: resource IDs, changed fields, course context), `trace_id`, and `occurred_at`.

9. **FR-APPLY-009** — **Audit for Read-Only and Failed Operations**: The apply layer must also record audit events for failed apply attempts (with error code and reason) and for read-only proposal lifecycle changes (proposal created, proposal expired, proposal rejected by user). This provides a complete timeline of AI activity.

10. **FR-APPLY-010** — **Cache Invalidation After Apply**: After a successful mutation, any cached course/page data (e.g., in Redis or in-memory) must be invalidated so subsequent reads from the existing editor return fresh state. Invalidation uses the `course_id` as the key scope.

11. **FR-APPLY-011** — **Confirmation Token Enforcement**: For destructive operations (delete) or batch operations, the apply endpoint must validate a `confirmation_token` stored in the proposal record. The token must match, must not be expired (TTL 15 minutes), and must not have been previously used. This prevents replay of confirmations.

12. **FR-APPLY-012** — **Error Catalog**: All apply errors must use the standardized error envelope from `app/utils/error_envelope.py` with specific error codes (see Section 3.3). Error responses include a `retryable` boolean to guide frontend/LLM retry behavior.

### 1.2 User Flow: Happy Path

1. User reviews a proposal in the frontend UI (created by US-AI-009 flow).
2. User clicks "Apply" on a non-destructive proposal (e.g., create page).
3. Frontend calls `POST /api/v1/ai/tools/apply_page_proposal` with `{ session_id, proposal_id, user_confirmed: true }`.
4. Apply service receives request, extracts trace context from headers, resolves session.
5. Service revalidates: session is active, proposal exists and is in PENDING_REVIEW state, proposal TTL has not expired, `user_confirmed` is true, proposal belongs to session's course.
6. Service fetches current course/page state and compares against `base_hash` stored in the proposal. Hash matches -- no staleness conflict.
7. Service begins database transaction.
8. Service executes domain mutation through the appropriate repository (`PageRepository.create` with nested `ComponentRepository` creates for component data).
9. Service re-runs validation on the mutated scope (page/component data). Validation passes.
10. Service updates proposal state to `APPLIED`, sets `applied_at` timestamp.
11. Service writes audit log entry with before/after snapshots.
12. Service writes outbox event.
13. Transaction commits.
14. Stale cache entries for this course_id are invalidated.
15. Service returns success response with `{ page_id, status: "created", message }` and refreshed course state.
16. Frontend re-renders editor with new page visible.

### 1.3 Alternate / Error Paths

**Path A: Stale Base Hash (409 Conflict)**
1. Steps 1-5 proceed as happy path.
2. Step 6: Current state hash differs from `base_hash` stored in proposal.
3. Service returns 409 Conflict with code `STALE_BASE_HASH`, message "Page has been modified since proposal was created.", and the current state in `details.current_state`.
4. Frontend displays conflict warning, fetches the current page state via `GET /api/v1/courses/{courseId}/pages/{pageId}`, and the user must create a new proposal from fresh state.
5. LLM is notified to re-fetch state and create a fresh proposal.

**Path B: Double Submit (409 Conflict)**
1. Frontend sends apply request. Network timeout occurs but server actually committed.
2. Frontend retries the same apply request (same `proposal_id` and `user_confirmed=true`).
3. Apply service detects proposal is already in `APPLIED` state.
4. If idempotency key is present: return cached success response from idempotency store.
5. If no idempotency key: return 409 Conflict with code `PROPOSAL_ALREADY_APPLIED` and the success response body from the original apply.

**Path C: Expired Proposal (410 Gone)**
1. User takes too long to review (proposal TTL of 24 hours elapsed).
2. Apply service checks `expires_at` on proposal, returns 410 Gone with code `PROPOSAL_EXPIRED`.
3. Frontend displays "This proposal has expired. Please ask the AI to create a new proposal."
4. LLM is notified to re-fetch state and create a fresh proposal.

**Path D: Post-Apply Validation Failure (500 with Rollback)**
1. Steps 1-8 proceed as happy path.
2. Step 9: Post-apply validation fails (e.g., mutated data violates SCORM constraint).
3. Transaction is rolled back entirely.
4. Audit log entry is NOT written (no mutation occurred), but a separate `proposal_failed_apply` event is logged outside the transaction for debugging.
5. Service returns 500 error with code `POST_APPLY_VALIDATION_FAILED` and the validation errors in `details`.
6. Proposal state is set to `FAILED`.
7. Frontend displays "An unexpected validation error occurred. The change was not saved. Please try again."

**Path E: Confirmation Token Mismatch (403 Forbidden)**
1. Steps 1-5 as happy path for a destructive operation.
2. The `confirmation_token` stored in the proposal does not match the one required. Token may be expired (15 min TTL) or was already consumed.
3. Service returns 403 Forbidden with code `CONFIRMATION_TOKEN_INVALID`.
4. Frontend shows "Confirmation timed out. Please reconfirm the deletion."

### 1.4 UI/UX Requirements

- **Apply Button States**: Disabled while proposal is creating; enabled with "Apply" label when proposal is valid; disabled with tooltip "Fix validation errors before applying" when proposal has blocking errors.
- **Loading Indicator**: Indeterminate progress bar/spinner during apply. No timeout bar (apply is fast -- <2s expected).
- **Success Animation**: Brief checkmark or green flash on the affected page/component in the editor pane. The page list updates automatically.
- **Conflict Modal**: For 409 staleness conflicts, show a non-dismissable modal: "This page has been changed since the proposal was created. Close this dialog to see the current state, then ask the AI to retry."
- **Expired Toast**: For 410 expired proposals, show a yellow warning toast: "This proposal expired. Ask the AI to create a new one."
- **Error Recovery**: For 5xx errors, show a red error toast with a "Retry" button that re-sends the exact same apply request.

---

## 2. TECHNICAL SPECIFICATION

### 2.1 API Contracts

#### 2.1.1 Apply Page Proposal

**Endpoint:** `POST /api/v1/ai/tools/apply_page_proposal`

**Headers:**
```
Authorization: Session {session_id}
X-Idempotency-Key: {uuid}        (optional, for client-side retry safety)
X-Trace-Id: {uuid}               (optional, for distributed tracing)
Content-Type: application/json
```

**Request Body:**
```json
{
  "session_id": "uuid-string",
  "proposal_id": "uuid-string",
  "user_confirmed": true
}
```

**Response 200 (Success):**
```json
{
  "status": "created",
  "page_id": "uuid-string",
  "message": "Page created successfully",
  "course_state": {
    "course_id": "uuid-string",
    "title": "Course Title",
    "pages": [
      {
        "page_id": "uuid-string",
        "title": "New Page",
        "order": 3,
        "updated_at": "2026-06-14T12:00:00Z"
      }
    ]
  },
  "audit_entry_id": "uuid-string",
  "trace_id": "uuid-string"
}
```

Possible `status` values: `"created"`, `"updated"`, `"deleted"` (maps to the proposal operation).

**Response 409 (Conflict -- Stale):**
```json
{
  "code": "STALE_BASE_HASH",
  "message": "Page has been modified since proposal was created",
  "details": {
    "proposal_base_hash": "sha256:abcdef...",
    "current_hash": "sha256:ghijkl...",
    "current_state": { "page": { "title": "Current Title", ... } }
  },
  "retryable": true
}
```

**Response 409 (Conflict -- Already Applied):**
```json
{
  "code": "PROPOSAL_ALREADY_APPLIED",
  "message": "This proposal has already been applied",
  "details": {
    "proposal_id": "uuid-string",
    "applied_at": "2026-06-14T11:55:00Z",
    "status": "created"
  },
  "retryable": false
}
```

**Response 410 (Gone -- Expired):**
```json
{
  "code": "PROPOSAL_EXPIRED",
  "message": "Proposal expired at 2026-06-14T11:00:00Z. Create a new proposal.",
  "details": {
    "proposal_id": "uuid-string",
    "expired_at": "2026-06-14T11:00:00Z"
  },
  "retryable": false
}
```

**Response 403 (Forbidden -- Confirmation Invalid):**
```json
{
  "code": "CONFIRMATION_TOKEN_INVALID",
  "message": "Confirmation token is invalid or expired",
  "details": {
    "proposal_id": "uuid-string",
    "reason": "token_expired",
    "expires_at": "2026-06-14T10:15:00Z"
  },
  "retryable": true
}
```

**Response 500 (Post-Apply Validation Failure):**
```json
{
  "code": "POST_APPLY_VALIDATION_FAILED",
  "message": "Validation failed after mutation. Change was rolled back.",
  "details": {
    "validation_errors": [
      { "field": "data.questions", "message": "Assessment requires at least 3 questions", "severity": "error" }
    ]
  },
  "retryable": true
}
```

**HTTP Status Codes:**

| Code | Condition |
|------|-----------|
| 200 | Successful apply (mutation committed) |
| 400 | Missing required field in request body |
| 403 | Confirmation token invalid/expired |
| 409 | Stale base hash or proposal already applied |
| 410 | Proposal expired |
| 422 | `user_confirmed` is false or missing |
| 500 | Post-apply validation failure, database error, internal error |

#### 2.1.2 Generic Tool Apply Endpoint

**Endpoint:** `POST /api/v1/ai/tools/{tool_name}`

Tool names this story provides: `apply_page_proposal`, `apply_update_proposal`, `confirm_delete_page`.

All follow the same pattern as 2.1.1 with tool-specific request/response schemas as defined in `TOOL_SCHEMAS_CLAUDE_NATIVE.md`.

### 2.2 Database Schema DDL

#### 2.2.1 Proposals Table (Part of US-AI-004/US-AI-009 foundations, extended here)

```sql
CREATE TABLE ai_proposals (
    id SERIAL PRIMARY KEY,
    proposal_id UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    session_id UUID NOT NULL REFERENCES ai_sessions(session_id) ON DELETE CASCADE,
    course_id VARCHAR(64) NOT NULL,
    operation VARCHAR(32) NOT NULL CHECK (operation IN ('create_page', 'update_page', 'delete_page', 'batch_import', 'update_component')),
    state VARCHAR(32) NOT NULL DEFAULT 'PENDING_REVIEW' CHECK (state IN ('PENDING_REVIEW','APPROVED','APPLYING','APPLIED','REJECTED','EXPIRED','FAILED')),
    target_type VARCHAR(32) DEFAULT NULL CHECK (target_type IN ('page','component','course')),  -- NULL until resolved
    target_id VARCHAR(64) DEFAULT NULL,  -- page_id or component_id, NULL until first apply attempt
    title VARCHAR(200) NOT NULL,
    template_type VARCHAR(100) DEFAULT NULL,
    base_hash VARCHAR(128) NOT NULL,  -- SHA-256 of current state at proposal creation
    before_snapshot JSONB DEFAULT NULL,
    after_candidate JSONB NOT NULL,  -- The proposed new state
    patch JSONB DEFAULT NULL,  -- For update proposals: only the changed fields
    diff JSONB DEFAULT NULL,  -- { changed_fields: [...], before: {...}, after: {...} }
    validation_result JSONB NOT NULL DEFAULT '{}'::jsonb,
    validation_status VARCHAR(16) NOT NULL DEFAULT 'valid' CHECK (validation_status IN ('valid','warning','error')),
    confirmation_required BOOLEAN NOT NULL DEFAULT FALSE,
    confirmation_token VARCHAR(128) DEFAULT NULL,  -- UUID token for destructive ops
    confirmation_token_expires_at TIMESTAMPTZ DEFAULT NULL,  -- 15 min from token issue
    idempotency_key VARCHAR(128) UNIQUE DEFAULT NULL,
    trace_id UUID NOT NULL DEFAULT gen_random_uuid(),
    tool_schema_version VARCHAR(32) NOT NULL DEFAULT '1.0.0',
    template_schema_version VARCHAR(32) DEFAULT NULL,
    model_metadata JSONB DEFAULT '{}'::jsonb,
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '24 hours'),
    applied_at TIMESTAMPTZ DEFAULT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_proposal_session FOREIGN KEY (session_id) REFERENCES ai_sessions(session_id),
    CONSTRAINT fk_proposal_course FOREIGN KEY (course_id) REFERENCES courses(course_id) ON DELETE CASCADE
);

CREATE INDEX idx_proposals_session ON ai_proposals(session_id);
CREATE INDEX idx_proposals_course ON ai_proposals(course_id);
CREATE INDEX idx_proposals_state ON ai_proposals(state);
CREATE INDEX idx_proposals_idempotency ON ai_proposals(idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX idx_proposals_expires ON ai_proposals(expires_at) WHERE state = 'PENDING_REVIEW';
```

#### 2.2.2 Audit Logs Table

```sql
CREATE TABLE ai_audit_logs (
    id SERIAL PRIMARY KEY,
    audit_entry_id UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    session_id UUID NOT NULL REFERENCES ai_sessions(session_id) ON DELETE CASCADE,
    proposal_id UUID REFERENCES ai_proposals(proposal_id) ON DELETE SET NULL,
    user_id VARCHAR(128) NOT NULL,
    organization_id VARCHAR(128) DEFAULT NULL,
    course_id VARCHAR(64) NOT NULL,
    operation VARCHAR(32) NOT NULL CHECK (operation IN ('create','update','delete','batch_apply','propose','reject','expire','fail')),
    resource_type VARCHAR(32) NOT NULL CHECK (resource_type IN ('page','component','course','proposal')),
    resource_id VARCHAR(64) DEFAULT NULL,  -- page_id, component_id, or proposal_id
    before_snapshot JSONB DEFAULT NULL,
    after_snapshot JSONB DEFAULT NULL,
    diff JSONB DEFAULT NULL,  -- For update operations
    validation_summary JSONB DEFAULT '{}'::jsonb,
    confirmation_token_hash VARCHAR(128) DEFAULT NULL,  -- SHA-256 of confirmation token
    idempotency_key VARCHAR(128) DEFAULT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'success' CHECK (status IN ('success','failure','cancelled')),
    error_code VARCHAR(64) DEFAULT NULL,
    error_message TEXT DEFAULT NULL,
    tool_schema_version VARCHAR(32) DEFAULT NULL,
    template_schema_version VARCHAR(32) DEFAULT NULL,
    model_metadata JSONB DEFAULT '{}'::jsonb,
    trace_id UUID NOT NULL,
    ip_address VARCHAR(45) DEFAULT NULL,
    user_agent TEXT DEFAULT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_audit_session FOREIGN KEY (session_id) REFERENCES ai_sessions(session_id),
    CONSTRAINT fk_audit_course FOREIGN KEY (course_id) REFERENCES courses(course_id) ON DELETE CASCADE
);

-- Partition by month for retention management
CREATE INDEX idx_audit_occurred ON ai_audit_logs(occurred_at DESC);
CREATE INDEX idx_audit_user ON ai_audit_logs(user_id);
CREATE INDEX idx_audit_course ON ai_audit_logs(course_id);
CREATE INDEX idx_audit_proposal ON ai_audit_logs(proposal_id);
CREATE INDEX idx_audit_operation ON ai_audit_logs(operation);
CREATE INDEX idx_audit_trace ON ai_audit_logs(trace_id);
CREATE INDEX idx_audit_resource ON ai_audit_logs(resource_type, resource_id);
```

#### 2.2.3 Outbox Events Table

```sql
CREATE TABLE outbox_events (
    id SERIAL PRIMARY KEY,
    event_id UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    event_type VARCHAR(64) NOT NULL CHECK (event_type IN (
        'PageCreatedByAI',
        'PageUpdatedByAI',
        'PageDeletedByAI',
        'ComponentUpdatedByAI',
        'CourseCreatedFromFile',
        'BatchProposalApplied',
        'ProposalCreated',
        'ProposalRejected',
        'ProposalExpired',
        'ProposalFailed'
    )),
    event_version INTEGER NOT NULL DEFAULT 1,
    aggregate_type VARCHAR(32) NOT NULL CHECK (aggregate_type IN ('page','component','course','proposal','batch')),
    aggregate_id VARCHAR(64) NOT NULL,
    payload JSONB NOT NULL,
    trace_id UUID NOT NULL,
    session_id UUID NOT NULL REFERENCES ai_sessions(session_id) ON DELETE CASCADE,
    proposal_id UUID DEFAULT NULL REFERENCES ai_proposals(proposal_id) ON DELETE SET NULL,
    user_id VARCHAR(128) NOT NULL,
    organization_id VARCHAR(128) DEFAULT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ DEFAULT NULL,  -- NULL until consumed by outbox publisher
    publish_attempts INTEGER NOT NULL DEFAULT 0,
    last_publish_error TEXT DEFAULT NULL,

    CONSTRAINT fk_outbox_session FOREIGN KEY (session_id) REFERENCES ai_sessions(session_id)
);

CREATE INDEX idx_outbox_unpublished ON outbox_events(published_at) WHERE published_at IS NULL;
CREATE INDEX idx_outbox_type ON outbox_events(event_type);
CREATE INDEX idx_outbox_aggregate ON outbox_events(aggregate_type, aggregate_id);
CREATE INDEX idx_outbox_occurred ON outbox_events(occurred_at DESC);
CREATE INDEX idx_outbox_trace ON outbox_events(trace_id);
```

#### 2.2.4 Idempotency Cache Table

```sql
CREATE TABLE idempotency_cache (
    id SERIAL PRIMARY KEY,
    idempotency_key VARCHAR(128) NOT NULL UNIQUE,
    request_method VARCHAR(16) NOT NULL,
    request_path VARCHAR(256) NOT NULL,
    request_body_hash VARCHAR(128) NOT NULL,  -- SHA-256 of canonical request body
    response_status INTEGER NOT NULL,
    response_body JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '24 hours'),

    CONSTRAINT unique_idempotency_key UNIQUE (idempotency_key)
);

CREATE INDEX idx_idempotency_expires ON idempotency_cache(expires_at);
```

### 2.3 Service / Module Design

All new files go under `app/services/ai/` per the architecture's AI layer separation principle.

#### 2.3.1 Apply Service

```python
# app/services/ai/apply_service.py

from typing import Optional, Tuple
from uuid import UUID
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.proposal_repo import AIProposalRepository
from app.services.ai.audit_service import AuditService
from app.services.ai.outbox_service import OutboxService
from app.services.ai.idempotency_service import IdempotencyService
from app.services.ai.validation_adapter import ValidationAdapter
from app.repositories.page_component_repo import PageRepository, ComponentRepository
from app.repositories.course_repo import CourseRepository
from app.utils.cache_manager import CacheManager
from app.utils.trace_context import TraceContext


@dataclass
class ApplyResult:
    status: str  # created | updated | deleted | rejected | error
    resource_id: Optional[str]
    message: str
    course_state: dict
    audit_entry_id: Optional[str]
    trace_id: str


class ApplyService:
    """
    Orchestrates the apply of a validated proposal:
    revalidation -> transaction -> mutation -> audit -> outbox -> cache invalidation.
    """

    def __init__(
        self,
        session: AsyncSession,
        proposal_repo: AIProposalRepository,
        page_repo: PageRepository,
        component_repo: ComponentRepository,
        course_repo: CourseRepository,
        audit_service: AuditService,
        outbox_service: OutboxService,
        idempotency_service: IdempotencyService,
        validation_adapter: ValidationAdapter,
        cache_manager: CacheManager,
        trace_ctx: TraceContext,
    ):
        self.session = session
        self.proposal_repo = proposal_repo
        self.page_repo = page_repo
        self.component_repo = component_repo
        self.course_repo = course_repo
        self.audit_service = audit_service
        self.outbox_service = outbox_service
        self.idempotency_service = idempotency_service
        self.validation_adapter = validation_adapter
        self.cache_manager = cache_manager
        self.trace_ctx = trace_ctx

    async def apply_page_proposal(
        self,
        session_id: UUID,
        proposal_id: UUID,
        user_confirmed: bool,
        idempotency_key: Optional[str] = None,
    ) -> ApplyResult:
        # === Phase 1: Revalidate proposal ===
        # - Check idempotency key cache
        # - Load proposal from DB
        # - Verify ownership (session, course match)
        # - Verify state is PENDING_REVIEW, TTL not expired
        # - Verify user_confirmed is true
        # - Verify confirmation token if destructive
        ...

    async def _execute_mutation(
        self,
        proposal: AIProposalRecord,
        current_hash: str,
    ) -> Tuple[dict, dict]:
        """Execute the domain mutation within an open transaction.
        
        Returns (before_snapshot, after_snapshot).
        """
        ...

    async def _invalidate_caches(self, course_id: str):
        """Invalidate course and page caches after successful apply."""
        ...
```

#### 2.3.2 Audit Service

```python
# app/services/ai/audit_service.py

from uuid import UUID
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class AuditEntry:
    session_id: UUID
    proposal_id: Optional[UUID]
    user_id: str
    organization_id: Optional[str]
    course_id: str
    operation: str
    resource_type: str
    resource_id: Optional[str]
    before_snapshot: Optional[dict]
    after_snapshot: Optional[dict]
    diff: Optional[dict]
    validation_summary: dict
    confirmation_token_hash: Optional[str]
    idempotency_key: Optional[str]
    status: str  # success | failure | cancelled
    error_code: Optional[str]
    error_message: Optional[str]
    tool_schema_version: Optional[str]
    template_schema_version: Optional[str]
    model_metadata: dict
    trace_id: UUID
    ip_address: Optional[str]
    user_agent: Optional[str]


class AuditService:
    """
    Writes audit log entries for all AI operations.
    Always called within the apply transaction.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def write_audit_entry(self, entry: AuditEntry) -> UUID:
        """Persist an audit log row. Returns audit_entry_id."""
        ...

    async def write_failed_apply(
        self,
        session_id: UUID,
        proposal_id: UUID,
        error_code: str,
        error_message: str,
        trace_id: UUID,
    ):
        """Write a failure-only audit entry (outside transaction, after rollback)."""
        ...
```

#### 2.3.3 Outbox Service

```python
# app/services/ai/outbox_service.py

from uuid import UUID
from dataclasses import dataclass
from enum import Enum


class OutboxEventType(str, Enum):
    PAGE_CREATED = "PageCreatedByAI"
    PAGE_UPDATED = "PageUpdatedByAI"
    PAGE_DELETED = "PageDeletedByAI"
    COMPONENT_UPDATED = "ComponentUpdatedByAI"
    COURSE_CREATED_FROM_FILE = "CourseCreatedFromFile"
    BATCH_APPLIED = "BatchProposalApplied"
    PROPOSAL_CREATED = "ProposalCreated"
    PROPOSAL_REJECTED = "ProposalRejected"
    PROPOSAL_EXPIRED = "ProposalExpired"
    PROPOSAL_FAILED = "ProposalFailed"


@dataclass
class OutboxEvent:
    event_type: OutboxEventType
    event_version: int
    aggregate_type: str
    aggregate_id: str
    payload: dict
    trace_id: UUID
    session_id: UUID
    proposal_id: Optional[UUID]
    user_id: str
    organization_id: Optional[str]


class OutboxService:
    """
    Writes outbox events within the apply transaction.
    Events are picked up by the outbox publisher (US-AI-033).
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def write_event(self, event: OutboxEvent) -> UUID:
        """Persist an outbox event row. Returns event_id."""
        ...
```

#### 2.3.4 Idempotency Service

```python
# app/services/ai/idempotency_service.py

from typing import Optional


class IdempotencyService:
    """
    Manages idempotency key cache for deduplication of apply requests.
    Uses the idempotency_cache table.
    """

    def __init__(self, session):
        self.session = session

    async def get_cached_response(
        self, idempotency_key: str
    ) -> Optional[dict]:
        """Return cached response if key exists and is still valid (within TTL)."""
        ...

    async def cache_response(
        self,
        idempotency_key: str,
        request_method: str,
        request_path: str,
        request_body_hash: str,
        response_status: int,
        response_body: dict,
        ttl_seconds: int = 86400,
    ) -> None:
        """Store response for idempotency key."""
        ...

    async def compute_request_hash(self, body: dict) -> str:
        """Deterministic SHA-256 of canonical JSON body (sorted keys)."""
        ...
```

#### 2.3.5 Validation Adapter

```python
# app/services/ai/validation_adapter.py


class ValidationAdapter:
    """
    Adapter over the existing validation pipeline (US-AI-008) for
    post-apply revalidation. Validates only the changed scope.
    """

    async def validate_changed_scope(
        self,
        course_id: str,
        operation: str,
        target_type: str,
        after_state: dict,
    ) -> dict:
        """
        Re-runs validation on the mutated data.
        Returns {"valid": bool, "errors": [...], "warnings": [...]}.
        """
        ...
```

#### 2.3.6 Apply Router

```python
# app/routers/ai_tools.py (new -- part of US-AI-003)

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field


class ApplyProposalRequest(BaseModel):
    session_id: str
    proposal_id: str
    user_confirmed: bool = Field(..., description="Must be true to apply")


class ApplyProposalResponse(BaseModel):
    status: str
    page_id: Optional[str] = None
    message: str
    course_state: Optional[dict] = None
    audit_entry_id: Optional[str] = None
    trace_id: str


router = APIRouter(prefix="/api/v1/ai/tools", tags=["AI Tools"])


@router.post("/apply_page_proposal")
async def apply_page_proposal(
    body: ApplyProposalRequest,
    idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
    trace_id: Optional[str] = Header(None, alias="X-Trace-Id"),
    session: AsyncSession = Depends(get_session),
):
    ...


@router.post("/apply_update_proposal")
async def apply_update_proposal(
    body: ApplyProposalRequest,
    idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
    ...
):
    ...


@router.post("/confirm_delete_page")
async def confirm_delete_page(
    body: ConfirmDeleteRequest,
    ...
):
    ...
```

### 2.4 Configuration Variables

| Variable | Type | Default | Description |
|---|---|---|---|
| `AI_PROPOSAL_TTL_HOURS` | int | 24 | Hours before a pending proposal expires |
| `AI_CONFIRMATION_TOKEN_TTL_MINUTES` | int | 15 | Minutes before a confirmation token expires |
| `AI_IDEMPOTENCY_TTL_HOURS` | int | 24 | Hours an idempotency key remains valid |
| `AI_AUDIT_RETENTION_DAYS` | int | 730 | Retention period for audit logs (2 years) |
| `AI_POST_APPLY_VALIDATION_ENABLED` | bool | `true` | Toggle post-apply re-validation |
| `AI_CACHE_BACKEND` | str | `"redis"` | Cache backend: `"redis"` or `"memory"` |
| `AI_CACHE_TTL_SECONDS` | int | 300 | TTL for course/page cache entries |
| `AI_OUTBOX_PUBLISHER_ENABLED` | bool | `true` | Enable outbox event publisher polling |
| `AI_OUTBOX_POLL_INTERVAL_SECONDS` | int | 5 | Polling interval for unpublished outbox events |
| `AI_OUTBOX_BATCH_SIZE` | int | 100 | Max outbox events to publish per poll cycle |

Add to `app/services/ai/config.py` or read from environment via `os.getenv`.

### 2.5 Integration Points

#### 2.5.1 Repositories Used

| Repository | Method | Purpose |
|---|---|---|
| `PageRepository` | `.create()`, `.update()`, `.delete()`, `.get()` | Mutate pages |
| `ComponentRepository` | `.create()`, `.update()`, `.delete()`, `.list_by_page()` | Mutate components |
| `CourseRepository` | `.get_by_course_id()`, `.update_record()` | Update course metadata |
| `AIProposalRepository` (new) | `.get()`, `.update_state()`, `.mark_applied()` | Proposal lifecycle |

#### 2.5.2 Services Used

| Service | Method | Purpose |
|---|---|---|
| `AuditService` (new) | `.write_audit_entry()` | Write audit log |
| `OutboxService` (new) | `.write_event()` | Write outbox event |
| `IdempotencyService` (new) | `.get_cached_response()`, `.cache_response()` | Deduplication |
| `ValidationAdapter` (new) | `.validate_changed_scope()` | Post-apply validation |
| `CacheManager` (new or existing) | `.invalidate_course()`, `.invalidate_page()` | Cache invalidation |

#### 2.5.3 Events Emitted (Outbox)

| Event Type | When | Payload Summary |
|---|---|---|
| `PageCreatedByAI` | Create page applied | `{ page_id, course_id, title, template_type, order }` |
| `PageUpdatedByAI` | Update page applied | `{ page_id, course_id, changed_fields }` |
| `PageDeletedByAI` | Delete page applied | `{ page_id, course_id, title }` |
| `ComponentUpdatedByAI` | Component changed | `{ component_id, page_id, course_id }` |
| `CourseCreatedFromFile` | File import applied | `{ course_id, source_file_hash, page_count }` |
| `BatchProposalApplied` | Batch create/update | `{ course_id, proposal_ids: [...] }` |
| `ProposalRejected` | User rejected proposal | `{ proposal_id, course_id }` |
| `ProposalExpired` | TTL elapsed without action | `{ proposal_id, course_id }` |
| `ProposalFailed` | Post-apply validation failed | `{ proposal_id, errors: [...] }` |

---

## 3. NON-FUNCTIONAL REQUIREMENTS

### 3.1 Performance Targets

| Metric | Target | Measurement |
|---|---|---|
| Apply endpoint p50 latency | < 500ms | From request receipt to response |
| Apply endpoint p95 latency | < 1500ms | Under normal load |
| Apply endpoint p99 latency | < 3000ms | Under peak load |
| Audit log write latency | < 50ms | Within transaction |
| Outbox event write latency | < 50ms | Within transaction |
| Idempotency key lookup | < 10ms | Indexed by key |
| Throughput | > 100 apply ops/second | Single instance |

### 3.2 Security Requirements

**AuthZ Model:**
- Session token validates user identity, session ownership, and course scope.
- `Authorization: Session {session_id}` header is validated on every apply call.
- The session's `user_id` must match the authenticated user context.
- The proposal's `course_id` and `session.course_id` must match.
- Attempted cross-course apply returns 403 PERMISSION_DENIED.

**Validation Rules:**
- `user_confirmed` must be `true` (boolean, not truthy string).
- `proposal_id` must be a valid UUID (v4 or v7) format.
- `session_id` must be a valid UUID format linked to an active session.
- Any unexpected fields in the request body are silently ignored (no injection).
- Request body size is limited to 64KB.

**Tenant Isolation:**
- Session records include `organization_id`. The apply service must validate that the authenticated user belongs to the same organization.
- In a multi-tenant deployment, the organization check must never be bypassed.
- Different tenants' audit logs are partitioned by `organization_id` in the index strategy.

**Secret Redaction:**
- Before writing audit entries, apply the `redact_sensitive_fields()` function from the architecture doc (Section 9.5) to both `before_snapshot` and `after_snapshot`.
- Redact: `password`, `apiKey`, `token`, `authorization`, `studentEmails`, `studentNames` paths.

### 3.3 Reliability

**Error Codes Catalog:**

| Code | HTTP | When | Retryable |
|---|---|---|---|
| `SESSION_INVALID` | 403 | Session expired, not found, or user mismatch | false |
| `PROPOSAL_NOT_FOUND` | 404 | Proposal ID does not exist | false |
| `PROPOSAL_STATE_INVALID` | 409 | Proposal not in PENDING_REVIEW state | false |
| `PROPOSAL_ALREADY_APPLIED` | 409 | Proposal already APPLIED (with cached response) | false |
| `PROPOSAL_EXPIRED` | 410 | Proposal TTL elapsed | false |
| `STALE_BASE_HASH` | 409 | Current state hash differs from proposal hash | true |
| `CONFIRMATION_TOKEN_INVALID` | 403 | Token expired, already used, or doesn't match | false |
| `USER_CONFIRMATION_REQUIRED` | 422 | `user_confirmed` is false or missing | true |
| `POST_APPLY_VALIDATION_FAILED` | 500 | Mutation succeeded but post-apply validation failed (rolled back) | true |
| `IDEMPOTENCY_KEY_MISMATCH` | 409 | Same idempotency key used with different request body | false |
| `MUTATION_FAILED` | 500 | Repository mutation threw unexpected error (rolled back) | true |
| `DATABASE_TIMEOUT` | 503 | Transaction timeout (statement_timeout) | true |
| `CACHE_UNAVAILABLE` | 200 (logged) | Cache invalidation failed but mutation committed | not shown |

**Retry Strategy:**
- Retryable errors: client should retry with exponential backoff (1s, 2s, 4s, max 3 attempts).
- Non-retryable errors: client must notify user and stop retrying.
- Idempotency keys ensure safe retry of any retryable error.

**Graceful Degradation:**
- If the audit log write fails within the transaction, the entire transaction rolls back (no mutation without audit).
- If the outbox event write fails, the transaction rolls back (no mutation without outbox).
- If cache invalidation fails after commit, the mutation is still successful; stale data may be served for up to the cache TTL.
- If the idempotency service is unavailable, proceed without deduplication; the proposal state check provides a secondary guard.

**Idempotency Guarantees:**
- Exactly-once apply semantics when an idempotency key is provided.
- Server generates a unique `idempotency_key` stored on the proposal record at creation time (US-AI-009).
- Client may also provide its own `X-Idempotency-Key` header for additional safety.
- Key collision detection: same key + different request body = 409 IDEMPOTENCY_KEY_MISMATCH.
- Key TTL is configurable via `AI_IDEMPOTENCY_TTL_HOURS` (default 24h).

### 3.4 Scalability

**Statelessness:**
- The apply service is stateless aside from database connections and cache connections.
- Any instance can handle any apply request.
- Session and proposal state is entirely in PostgreSQL (source of truth).

**Horizontal Scaling:**
- Multiple instances of the apply service can run behind a load balancer.
- No instance-local locks or state required.
- The database transaction provides ACID guarantees across instances.
- No distributed lock needed for single-proposal apply (the proposal state check and row-level locking in PostgreSQL prevent double-apply).

**Connection Pooling:**
- Use the existing `DB_POOL_SIZE` (default 10) and `DB_MAX_OVERFLOW` (default 20) from `app/db/config.py`.
- Each apply request uses one connection from the pool for the duration of the transaction.
- Long-running transactions are prevented by a 10-second `statement_timeout` on apply requests.

---

## 4. CURRENT STATE ASSESSMENT

### 4.1 What Exists and Can Be Reused

| File | What It Provides | Reuse In |
|---|---|---|
| `app/main.py` | Router registration pattern, lifespan context | Register `ai_tools.py` router |
| `app/routers/courses.py` | `CourseRepository` usage pattern, `_get_repo` dependency, `CourseOut` model | Reference for response shape |
| `app/routers/page_components.py` | `PageRepository`, `ComponentRepository` usage, `PageRecord`/`ComponentRecord` creation | Direct reuse in mutation step |
| `app/models/persisted_course.py` | `CourseRecord` ORM model, `TemplateRecord`, `ImportJob` | Course mutation |
| `app/models/page_component.py` | `PageRecord`, `ComponentRecord` ORM models | Page/component mutation |
| `app/repositories/course_repo.py` | `CourseRepository` with `get_by_course_id`, `update_record`, `upsert` | Course reading/updating |
| `app/repositories/page_component_repo.py` | `PageRepository`, `ComponentRepository` with full CRUD | Page/component mutation |
| `app/utils/error_envelope.py` | `build_error()`, `api_http_exception()` | Standardized error responses |
| `app/utils/feature_flags.py` | `FeatureFlagService`, `is_feature_enabled()` | Gate AI apply behind `ai_suggestions` flag |
| `app/utils/validation.py` | `CourseValidator`, `validate_course_json` | Reference for validation patterns |
| `app/models/interaction_event.py` | `InteractionEventRecord` pattern for audit-like table | Reference for audit table design |
| `app/db/config.py` | `get_session()`, `engine`, `SessionLocal` | Database session injection |
| `TOOL_SCHEMAS_CLAUDE_NATIVE.md` | Exact `apply_page_proposal`, `apply_update_proposal`, `confirm_delete_page` tool schemas | API contract source of truth |

### 4.2 What Must Be Built Net-New

| Artifact | Description |
|---|---|
| `app/services/ai/apply_service.py` | Core apply orchestration service |
| `app/services/ai/audit_service.py` | Audit log write service |
| `app/services/ai/outbox_service.py` | Outbox event write service |
| `app/services/ai/idempotency_service.py` | Idempotency key cache service |
| `app/services/ai/validation_adapter.py` | Adapter to existing validation pipeline |
| `app/services/ai/proposal_repo.py` | Repository for `ai_proposals` table (shared with US-AI-009) |
| `app/services/ai/__init__.py` | Package init for AI services |
| `app/routers/ai_tools.py` | Router for tool apply endpoints |
| `app/utils/cache_manager.py` | Cache invalidation abstraction |
| `app/utils/trace_context.py` | Trace ID propagation utility |
| Database migration: `ai_proposals` table (if not created by US-AI-009) | See 2.2.1 |
| Database migration: `ai_audit_logs` table | See 2.2.2 |
| Database migration: `outbox_events` table | See 2.2.3 |
| Database migration: `idempotency_cache` table | See 2.2.4 |

### 4.3 What Existing Code Must Be Modified

| File | Modification | Non-Regression Constraint |
|---|---|---|
| `app/main.py` | Add `from app.routers import ai_tools` and `api_router.include_router(ai_tools.router)` | Must not change existing route paths or behavior. AI routes must be additive. |
| `app/main.py` | In `lifespan`, add `import app.services.ai` to trigger model import for `Base.metadata` | Must not break existing startup sequence. Model import errors are caught by the existing `except Exception` block. |
| `app/services/ai/__init__.py` (new, if package already exists) | If package already partially exists from US-AI-003, add new module imports | Must not remove or change existing AI service exports. |

**Non-Regression Constraints:**
- Existing `GET /api/v1/courses/{courseId}/pages` and `POST /api/v1/courses/{courseId}/pages` must remain unchanged.
- Existing `PATCH /api/v1/courses/{courseId}/pages/{pageId}` and `DELETE /api/v1/courses/{courseId}/pages/{pageId}` must remain unchanged.
- Existing `CourseRepository` and `PageRepository` method signatures must not change (type stability).
- Existing error envelope format in `app/utils/error_envelope.py` must remain backward compatible.
- All existing tests for course, page, and component CRUD must continue to pass.

---

## 5. EXPANSION POINTS

### 5.1 Technical Expansions

1. **Outbox Publisher Service (US-AI-033)**: The `outbox_events` table written by this story is consumed by a dedicated outbox publisher. In a future sprint, implement a polling service or PostgreSQL LISTEN/NOTIFY consumer that forwards events to a message broker (RabbitMQ, Kafka) for reliable delivery to search indexing, analytics pipelines, and external webhooks. The table's `published_at` column and `publish_attempts` counter are already designed for this.

2. **Distributed Lock for Concurrent Apply**: If multiple AI sessions or workers could attempt to apply proposals for the same resource simultaneously, add PostgreSQL advisory locks (`pg_advisory_xact_lock`) keyed on `(course_id, target_type, target_id)` to serialize apply attempts per resource. This prevents phantom double-apply in high-concurrency scenarios.

3. **Event Sourcing / Full Audit Replay**: The `ai_audit_logs` table already stores complete before/after snapshots. A future story can implement point-in-time recovery (replay audit events forward/backward) and a read-only audit query API with filtering by user, course, operation, date range, and outcome. The `before_snapshot` and `after_snapshot` JSONB columns enable this without structural changes.

### 5.2 Functional Expansions

1. **Auto-Apply Policy Engine (US-AI-032)**: Integrate with a policy engine that can auto-apply low-risk proposals (e.g., typo fixes on text-content pages by trusted users) without requiring explicit confirmation. The apply service would check the policy engine as an additional gate before requiring user confirmation, skipping the confirmation step for auto-apply rules.

2. **Rollback Proposals (US-AI-040)**: Use the `before_snapshot` in audit logs to generate rollback proposals. A rollback endpoint would create a new proposal with the before-snapshot as the `after_candidate`, following the same propose -> validate -> confirm -> apply pipeline. The audit log's `before_snapshot` was designed precisely for this.

3. **Batch Proposal Apply (US-AI-029)**: Extend the apply service to handle batch proposals (multiple page creates/updates in one atomic transaction). The current single-proposal apply service would be called for each page in the batch, but wrapped in a parent transaction with all-or-nothing semantics. The `BatchProposalApplied` outbox event type is already defined.

---

## 6. VALIDATION & TESTING

### 6.1 Unit Tests (at least 5)

**Test 1: Happy path apply creates page and writes audit + outbox**
- **Input**: Valid `session_id`, pending `proposal_id` for create_page operation, `user_confirmed=true`, all validations pass, hash matches.
- **Expected Output**: Returns `status: "created"`, `page_id` is non-null UUID. Database has one new row in `pages`, one new row in `ai_audit_logs`, one new row in `outbox_events`. Proposal state is `APPLIED`. `applied_at` is set.

**Test 2: Idempotency key returns cached response on retry**
- **Input**: Same `proposal_id` and `idempotency_key` sent twice. First call succeeds. Second call within TTL window.
- **Expected Output**: Second call returns exactly the same response body and status code as the first call, without executing mutation again. Database has only one page created. Only one audit log entry.

**Test 3: Double submit without idempotency key returns 409**
- **Input**: Same `proposal_id` sent twice without idempotency key. First call succeeds. Second call immediately after.
- **Expected Output**: First call returns 200. Second call returns 409 CONFLICT with code `PROPOSAL_ALREADY_APPLIED` and `status: "created"` in details.

**Test 4: Stale base hash returns 409 with current state**
- **Input**: Valid proposal with `base_hash = "abc123"`. Current database state hash is `"def456"` (changed between proposal creation and apply).
- **Expected Output**: 409 CONFLICT with code `STALE_BASE_HASH`. `details.current_state` contains the current page data. No mutation executed. Proposal state remains `PENDING_REVIEW`.

**Test 5: Expired proposal returns 410**
- **Input**: Proposal where `expires_at` is in the past. `user_confirmed=true`.
- **Expected Output**: 410 GONE with code `PROPOSAL_EXPIRED`. No mutation executed.

**Test 6: Post-apply validation failure rolls back transaction**
- **Input**: Proposal for a page update that would create invalid data (e.g., empty page title). The mutation itself succeeds but post-apply validation fails.
- **Expected Output**: 500 error with code `POST_APPLY_VALIDATION_FAILED`. Database has no new/changed rows in `pages`, no rows in `ai_audit_logs`, no rows in `outbox_events`. Proposal state is `FAILED`.

**Test 7: Confirmation token mismatch blocks destructive apply**
- **Input**: Delete proposal with `confirmation_required=true`. Proposal has a confirmation token `"token-abc"` but request provides `"token-xyz"`.
- **Expected Output**: 403 FORBIDDEN with code `CONFIRMATION_TOKEN_INVALID`. No mutation executed.

### 6.2 Integration Tests (at least 3)

**Test 1: Full create-proposal-then-apply flow**
1. Start an AI session (POST `/api/v1/ai/sessions`).
2. Create a proposal via AI tool flow (propose_create_page).
3. Fetch the proposal, verify it is in `PENDING_REVIEW` state.
4. Call `apply_page_proposal` with `user_confirmed=true`.
5. Verify: (a) response status is 200, (b) new `PageRecord` exists in database with correct data, (c) audit log has one entry with operation `create`, (d) outbox has one `PageCreatedByAI` event, (e) proposal state is `APPLIED`.
6. Call the same apply again without idempotency key. Verify 409 response.
7. Verify database still has exactly one page (no duplicate).

**Test 2: Staleness detection in concurrent-edit scenario**
1. Create a page manually via `POST /api/v1/courses/{courseId}/pages`.
2. Start an AI session for the same course.
3. Create an update proposal for the page using `propose_update_page` with initial state.
4. Before applying, manually edit the page title via `PATCH /api/v1/courses/{courseId}/pages/{pageId}`.
5. Call `apply_update_proposal`. Verify 409 conflict with code `STALE_BASE_HASH`.
6. Verify the page title in database still reflects the manual edit (no overwrite).

**Test 3: Transactional rollback on audit write failure**
1. Mock the `ai_audit_logs` table to simulate a write failure (e.g., raise an exception after mutation but before commit).
2. Send an apply request with valid `proposal_id`.
3. Verify: (a) the entire transaction is rolled back (no page created), (b) the proposal state remains `PENDING_REVIEW`, (c) no outbox events exist for this attempt, (d) an appropriate error is returned to the caller.

### 6.3 E2E / Acceptance Tests (at least 2)

**Test 1: Author creates a page via AI and applies it end-to-end**
1. As an Author, navigate to a course editor.
2. Open AI chat panel.
3. Instruct the AI: "Add an introduction page with text-content template."
4. AI calls `propose_create_page`, returns a proposal preview.
5. Frontend renders the proposal preview. Author clicks "Apply".
6. Frontend calls `POST /api/v1/ai/tools/apply_page_proposal`.
7. Verify: (a) new page appears in the course page list, (b) page content matches the proposal, (c) page is editable in the existing editor, (d) course can be exported without errors.
8. Verify audit trail: admin can query audit logs and see this exact creation event.

**Test 2: Double-click apply does not duplicate content**
1. Using browser DevTools, network throttle to simulate slow connection.
2. Click "Apply" on a proposal.
3. Before the response arrives, click "Apply" again (or use the browser's network replay).
4. Server processes first request successfully.
5. Server processes second request. Verify 409 conflict.
6. Verify: (a) only one page exists in the course, (b) audit has exactly one success entry and one failure entry for the conflict.

### 6.4 Manual QA Verification Procedure

1. **Verify Happy Path**: Create a course manually. Open AI session. Propose a new page. Click Apply. Verify page appears in the editor with correct data. Verify database has one row in `ai_proposals` with state `APPLIED`, one row in `ai_audit_logs`, one row in `outbox_events`.

2. **Verify Double-Click Safety**: In a slow network simulation, double-click Apply. Verify the second request returns 409. Verify database has exactly one new page.

3. **Verify Staleness Conflict**: Create an AI proposal. Before applying, use the regular editor to change the page. Then apply the proposal. Verify 409 conflict modal appears. Verify the editor page state is unchanged.

4. **Verify Expired Proposal**: Create an AI proposal. Set `AI_PROPOSAL_TTL_HOURS` to 0 (or mock `expires_at`). Wait or trigger TTL check. Try to apply. Verify 410 error with clear message.

5. **Verify Audit Query**: After applying several mutations, query `ai_audit_logs` table. Verify each mutation is recorded with correct `operation`, `resource_type`, `resource_id`, `before_snapshot`, `after_snapshot`, `trace_id`.

6. **Verify Outbox Events**: After each apply, query `outbox_events` table where `published_at IS NULL`. Verify exactly one event per apply with correct `event_type`, `aggregate_id`, and `payload`.

7. **Verify Cache Invalidation**: After applying a page creation, use the existing `GET /api/v1/courses/{courseId}/pages` endpoint. Verify the new page appears in the response immediately (cache was invalidated). If a Redis cache is configured, verify the cache key for this course is evicted.

8. **Verify Error Screen**: Send an apply request with `user_confirmed: false`. Verify 422 error with code `USER_CONFIRMATION_REQUIRED` and a clear error message.

9. **Verify Tenant Isolation**: Create two courses in different organizations. Create a proposal in org A's session. Try to apply it with org B's session. Verify 403 PERMISSION_DENIED.

---

## 7. DEFINITION OF DONE

1. [ ] **Code**: `app/services/ai/apply_service.py` is implemented with full apply orchestration (revalidation, mutation, audit, outbox, cache invalidation).
2. [ ] **Code**: `app/services/ai/audit_service.py` writes `ai_audit_logs` entries for successful and failed apply attempts.
3. [ ] **Code**: `app/services/ai/outbox_service.py` writes `outbox_events` entries for all event types in Section 2.5.3.
4. [ ] **Code**: `app/services/ai/idempotency_service.py` provides idempotency key deduplication with TTL enforcement.
5. [ ] **Code**: `app/services/ai/validation_adapter.py` reuses the existing validation pipeline for post-apply checks.
6. [ ] **Code**: `app/routers/ai_tools.py` exposes `apply_page_proposal`, `apply_update_proposal`, and `confirm_delete_page` endpoints with documented OpenAPI schemas.
7. [ ] **Code**: `app/utils/cache_manager.py` invalidates course-level caches after successful mutations.
8. [ ] **Migrations**: Four Alembic migration files exist and are idempotent (can run up/down): `ai_proposals` (or extended from US-AI-004), `ai_audit_logs`, `outbox_events`, `idempotency_cache`.
9. [ ] **Tests**: At least 7 unit tests (Section 6.1) pass with >85% code coverage on the new service modules.
10. [ ] **Tests**: At least 3 integration tests (Section 6.2) pass against a test PostgreSQL database.
11. [ ] **Tests**: At least 2 E2E tests (Section 6.3) pass, verifying end-to-end proposal-to-apply flow.
12. [ ] **Feature Flag**: All apply endpoints are gated behind the `ai_suggestions` feature flag. When disabled, the router returns 404.
13. [ ] **QA**: All 9 manual QA verification steps (Section 6.4) have been executed and signed off.
14. [ ] **Performance**: Apply endpoint p95 latency is under 1500ms under load of 50 concurrent requests (verified via locust or similar).
15. [ ] **Security**: Cross-tenant isolation verified (org A session cannot apply to org B course). Confirmation token replay tested.
16. [ ] **Non-Regression**: All existing `courses`, `page_components`, and `export` router tests pass unchanged.
17. [ ] **Audit**: A `SELECT * FROM ai_audit_logs` after a full test run shows correct entries for create, update, delete, and failure operations.
18. [ ] **Documentation**: OpenAPI spec is regenerated and includes the new tool endpoints with request/response schemas.

---

## 8. TASKS & SUB-TASKS

| ID | Task Description | Owner Role | Est. Hours | Dependencies |
|---|---|---|---|---|
| T1 | **Create database migration files for AI apply tables** | Backend Engineer (DB focused) | 4 | US-AI-004 (ai_proposals table schema) |
| T1.1 | Create `ai_audit_logs` table migration with all columns, constraints, indices, partitioning strategy | | 2 | T1 |
| T1.2 | Create `outbox_events` table migration with event type enum, payload, publish tracking | | 1 | T1 |
| T1.3 | Create `idempotency_cache` table migration with TTL index | | 0.5 | T1 |
| T1.4 | Create or extend `ai_proposals` table migration with `confirmation_token`, `idempotency_key`, `applied_at` columns | | 0.5 | US-AI-004 |
| T2 | **Implement core apply service** | Backend Engineer (senior) | 12 | T1 |
| T2.1 | Implement `IdempotencyService` with cache lookup, response caching, request hash computation | | 2 | T1.3 |
| T2.2 | Implement `ApplyService._revalidate_proposal()` with session, proposal, owner, TTL, confirmation_token checks | | 3 | T1.4 |
| T2.3 | Implement `ApplyService._execute_mutation()` dispatching to PageRepository/ComponentRepository | | 3 | Existing repositories |
| T2.4 | Implement `ApplyService._invalidate_caches()` for course-level cache eviction | | 1 | T5 |
| T2.5 | Implement `ApplyService.apply_page_proposal()` orchestrating the full flow (revalidate, hash check, transaction, mutate, post-validate, audit, outbox, cache, respond) | | 3 | T2.1-T2.4 |
| T3 | **Implement audit and outbox services** | Backend Engineer | 4 | T1.1, T1.2 |
| T3.1 | Implement `AuditService.write_audit_entry()` with full schema, secret redaction, failure logging | | 2 | T1.1 |
| T3.2 | Implement `OutboxService.write_event()` with event type mapping and payload assembly | | 1 | T1.2 |
| T3.3 | Implement `AuditService.write_failed_apply()` for out-of-transaction failure recording | | 1 | T3.1 |
| T4 | **Implement validation adapter and router** | Backend Engineer | 4 | T2, US-AI-008 |
| T4.1 | Implement `ValidationAdapter.validate_changed_scope()` calling existing validation pipeline | | 2 | US-AI-008 |
| T4.2 | Implement `ai_tools.py` router with `apply_page_proposal`, `apply_update_proposal`, `confirm_delete_page` endpoints | | 1.5 | T2, T3 |
| T4.3 | Register router in `main.py`, wire dependencies, feature flag gating | | 0.5 | T4.2 |
| T5 | **Implement cache manager utility** | Backend Engineer | 2 | None |
| T5.1 | Implement `CacheManager` with Redis backend (primary) and in-memory fallback | | 1.5 | None |
| T5.2 | Add cache key naming convention (`ai:course:{course_id}:pages`, `ai:page:{page_id}`) | | 0.5 | T5.1 |
| T6 | **Write unit and integration tests** | Backend Engineer (QA) | 8 | T2-T5 |
| T6.1 | Write 7 unit tests covering happy path, idempotency, double-submit, staleness, expiry, post-apply failure, confirmation mismatch | | 4 | T2, T3 |
| T6.2 | Write 3 integration tests covering full proposal-to-apply flow, concurrent edit staleness, transactional rollback | | 3 | T1, T2 |
| T6.3 | Run all existing CRUD tests to confirm non-regression | | 1 | T6.2 |
| T7 | **Manual QA and performance verification** | QA Engineer | 4 | T6 |
| T7.1 | Execute all 9 manual QA steps from Section 6.4 | | 2 | T6 |
| T7.2 | Run load test (50 concurrent apply requests, measure p95 latency) | | 1 | T2 |
| T7.3 | Run cross-tenant isolation security test | | 0.5 | T2 |
| T7.4 | Sign off Definition of Done checklist | | 0.5 | T7.1-T7.3 |

**Total estimated effort: 38 hours**

---

---

# Core Flows (US-AI-011 — US-AI-022)