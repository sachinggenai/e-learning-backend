# US-AI-013: Propose and Confirm Destructive Page Deletes

**Status:** Draft  
**Priority:** MUST (MVP)  
**Depends on:** US-AI-010 (Apply Safety, Audit, and Outbox)  
**Source flows:** Delete Page Proposal and Confirm Flow, Destructive Delete Scenario Flow  
**Epic Owner:** Technical Product Owner  

---

## 1. Functional Specification

### 1.1 User Story

As an Author, I want AI to request explicit confirmation before deleting a page, so that destructive operations cannot happen accidentally.

### 1.2 Overview

The AI agent can propose deleting a page from a course, but it can never delete directly. Every delete request must pass through a two-phase gate: (1) a proposal is created with a dependency impact analysis and a confirmation token, and (2) the user must explicitly confirm the destructive action through the frontend confirmation modal. Only after the user has confirmed does the system execute the database deletion.

The backend enforces that:
- `propose_delete_page` never mutates domain data.
- A valid `confirmation_token` bound to the session, proposal, and page hash is required to execute the delete.
- Dependency checks (branching rules, scoring configs, final assessment references, navigation impact) are surfaced as warnings before the user confirms.
- The full page snapshot is preserved in the audit trail for potential rollback.

### 1.3 Actors

| Actor | Role |
|---|---|
| Author (User) | Initiates delete via chat or UI; confirms or cancels the destructive action |
| AI Agent | Calls `propose_delete_page` tool; never calls deletion APIs directly |
| Backend System | Enforces the two-phase gate; persists proposals; validates tokens; executes transactional delete + audit |
| Frontend | Renders confirmation modal; polls or receives proposal status; refreshes editor state after delete |

### 1.4 Flow: Chat-Driven Delete

**Phase 0 — Intent and Target Resolution**
1. User sends a natural-language request: "Remove the assessment section from Unit 2."
2. The AI chat orchestrator receives the intent, classifies it as a destructive operation, and gates it against the session scope.
3. The agent calls `list_pages(session_id)` to enumerate pages in the session course.
4. The agent calls `fetch_page(session_id, page_id)` on candidates to inspect template/component types.
5. If exactly one target is resolved, the agent proceeds. If zero or multiple targets match, the agent asks for clarification; no proposal is created at this stage.

**Phase 1 — Proposal Creation**
1. The agent calls `propose_delete_page(session_id, page_id)` with the resolved page_id.
2. The backend validates:
   - Session is active, not expired, and within the AI feature flag.
   - Page exists and belongs to the session's course.
   - Proposal with the same `session_id` + `page_id` in `PENDING_CONFIRMATION` state does not already exist (idempotency guard).
3. The backend computes a deterministic page hash from the current `PageRecord.updated_at`, component count, and component updated_ats.
4. The backend performs dependency impact analysis:
   - Checks `branch_rules` table for any rule referencing the page as `source_page_id` or `default_target_page_id`.
   - Checks `course_scoring` for any `component_scores` referencing components on this page.
   - Checks `page_completion` and navigation ordering (deleting the only remaining page, or the final assessment page).
   - Checks if this page's order is referenced in the course navigation settings.
   - Checks export validation (if the page contains unsupported component types that are now being removed, no issue; but if the page is the only assessment page in the course, warn about impact on scoring).
5. Backend generates a `confirmation_token` (cryptographically random string, 64 hex chars), bound to:
   - `session_id`
   - `proposal_id` (generated at proposal creation)
   - `page_id`
   - `page_hash` (computed at proposal creation time)
   - `expires_at` (default: current time + 15 minutes)
6. Backend persists the proposal as a new record in `ai_proposals` with:
   - `status = PENDING_CONFIRMATION`
   - `operation = delete_page`
   - `confirmation_token_sha256 = SHA256(confirmation_token)` (store hash, not plaintext token)
   - `confirmation_token_expires_at`
   - `page_id`, `course_id`, `session_id`
   - `base_hash = page_hash`
   - `before_snapshot = full serialization of the page + components`
7. Backend returns the proposal response to the agent, which passes it to the frontend.

**Phase 2 — Frontend Confirmation**
1. Frontend renders a destructive confirmation modal with:
   - Page title and current order position.
   - Component summary (number and types of components on the page).
   - Dependency warnings from impact analysis (e.g., "This page is referenced by 2 branching rules" or "This page contains the final assessment; deleting it will remove scoring for the course").
   - Irreversible-action notice text.
   - Two explicit buttons: "Confirm Delete" (destructive style, requires typing the word "DELETE" or clicking a secondary confirm checkbox) and "Cancel".
   - The confirmation token is embedded in the frontend's proposal state; it is NOT displayed to the user.
2. User clicks "Confirm Delete" (after optionally typing "DELETE" in a confirmation field).
3. Frontend calls `confirm_delete_page(session_id, proposal_id, user_approved_delete=true)`.

**Phase 3 — Apply Delete**
1. Backend validates the confirmation:
   - Proposal exists, status is `PENDING_CONFIRMATION`, belongs to the session.
   - `confirmation_token` matches the stored SHA256 hash.
   - Token has not expired (check `confirmation_token_expires_at`).
   - `user_approved_delete = true`.
2. Backend re-fetches the page and re-computes the page hash.
3. Backend compares the new hash with `base_hash`:
   - If hash differs (page was modified since proposal), return `409 CONFLICT` with message that the page has changed; the user must re-propose deletion.
   - If the page no longer exists, return `410 GONE` with a message that the page was already deleted (idempotent handling).
4. Backend begins a database transaction:
   a. Update proposal `status = APPLYING`.
   b. Execute the actual page deletion via `PageRepository.delete(page)` — this cascades to all `ComponentRecord` rows via the ORM `cascade="all, delete-orphan"` on `PageRecord.components`.
   c. Post-delete validation: verify the course still has at least one page (if not, flag a warning; do not block).
   d. Reorder remaining pages if needed to close the gap (call `PageRepository.reorder` with the adjusted list).
   e. Write audit entry to `ai_audit_logs` with: `operation=delete_page`, `proposal_id`, `session_id`, `page_id`, `before_snapshot` (full page + components), `confirmation_token_id`, `user_id`, `course_id`, `timestamp`.
   f. Write outbox event to `outbox_events`: `event_type = PageDeletedByAI`, `event_version = 1`, payload with `{proposal_id, page_id, course_id, page_title, before_snapshot_summary}`.
   g. Update proposal `status = APPLIED`, `applied_at = now()`.
5. Commit transaction.
6. Return `{status: "deleted", pageId, pageTitle, updatedCourseState}` to the frontend.

**Phase 4 — Audit and Recovery**
1. Every applied delete is queryable via the audit endpoints (US-AI-020).
2. The `before_snapshot` stored in the audit log enables an admin to generate a rollback proposal (US-AI-040) if needed.
3. The frontend removes the page from the editor page list and refreshes the course state.

### 1.5 Flow: Direct-UI Delete (Future)

For direct UI deletion (not AI-driven), the existing `DELETE /api/v1/courses/{courseId}/pages/{pageId}` already works without the proposal gate. This story does not alter that endpoint. The proposal gate is AI-only. If a future story requires the UI delete to also use the proposal gate, it will be a separate change.

### 1.6 Error Conditions

| Condition | HTTP Status | Error Code | Behavior |
|---|---|---|---|
| Session expired or invalid | 403 | `SESSION_EXPIRED` | Return error; frontend prompts user to restart AI session |
| Page not found | 404 | `PAGE_NOT_FOUND` | Proposal creation fails; agent notifies user |
| Page does not belong to session course | 403 | `PAGE_NOT_IN_SCOPE` | Proposal creation fails |
| Duplicate pending proposal | 409 | `DUPLICATE_PROPOSAL` | Return existing proposal_id; resume confirmation flow |
| Confirmation token expired | 410 | `CONFIRMATION_EXPIRED` | Proposal must be re-created |
| Confirmation token mismatch | 403 | `INVALID_CONFIRMATION_TOKEN` | Possible tampering detected; log security event |
| Page hash changed since proposal | 409 | `PAGE_CHANGED` | User must re-propose deletion with fresh state |
| Page already deleted | 410 | `PAGE_ALREADY_DELETED` | Idempotent response; no error |
| Proposal already applied | 409 | `PROPOSAL_ALREADY_APPLIED` | Idempotent guard |
| User did not approve | 400 | `USER_CONFIRMATION_REQUIRED` | `confirm_delete_page` requires `user_approved_delete=true` |
| AI feature flag disabled | 404 | `FEATURE_NOT_AVAILABLE` | Rate-limited; gracefully disabled |

---

## 2. Technical Specification

### 2.1 New Database Tables — DDL

**Table: `ai_proposals` (extends US-AI-004)**

```sql
CREATE TABLE ai_proposals (
    id              SERIAL PRIMARY KEY,
    proposal_id     VARCHAR(64) UNIQUE NOT NULL,
    session_id      VARCHAR(64) NOT NULL REFERENCES ai_sessions(session_id) ON DELETE CASCADE,
    course_id       VARCHAR(64) NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    page_id         VARCHAR(64) REFERENCES pages(page_id) ON DELETE SET NULL,
    
    -- Operation
    operation       VARCHAR(32) NOT NULL CHECK (operation IN (
                        'create_page', 'update_page', 'delete_page',
                        'batch_create', 'batch_update', 'batch_delete'
                    )),
    status          VARCHAR(32) NOT NULL DEFAULT 'PENDING_REVIEW'
                    CHECK (status IN (
                        'PENDING_REVIEW', 'PENDING_CONFIRMATION', 'APPROVED',
                        'APPLYING', 'APPLIED', 'REJECTED', 'EXPIRED', 'FAILED'
                    )),
    
    -- Delete-specific fields
    confirmation_token_sha256   VARCHAR(64),  -- SHA256 of the confirmation token
    confirmation_token_expires_at TIMESTAMPTZ,
    base_hash                   VARCHAR(64),  -- Deterministic hash of page state at proposal time
    before_snapshot             JSONB,        -- Full serialized page + components
    
    -- Generic proposal fields
    after_candidate    JSONB,       -- For create/update proposals; NULL for delete proposals
    validation_result  JSONB,       -- Cached validation errors/warnings
    warning_messages   JSONB,       -- Dependency warnings array
    
    -- Provenance
    tool_schema_version  VARCHAR(32),
    prompt_version       VARCHAR(32),
    model_id             VARCHAR(128),
    
    -- Timestamps
    expires_at      TIMESTAMPTZ NOT NULL,  -- Proposal TTL from creation
    applied_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Idempotency
    idempotency_key VARCHAR(128) UNIQUE
);

CREATE INDEX idx_ai_proposals_session ON ai_proposals(session_id);
CREATE INDEX idx_ai_proposals_status ON ai_proposals(status);
CREATE INDEX idx_ai_proposals_course ON ai_proposals(course_id);
CREATE INDEX idx_ai_proposals_page ON ai_proposals(page_id);
```

**Table: `ai_audit_logs` (extends US-AI-004)**

```sql
CREATE TABLE ai_audit_logs (
    id              SERIAL PRIMARY KEY,
    audit_id        VARCHAR(64) UNIQUE NOT NULL,
    proposal_id     VARCHAR(64) REFERENCES ai_proposals(proposal_id),
    session_id      VARCHAR(64) REFERENCES ai_sessions(session_id),
    course_id       VARCHAR(64) NOT NULL,
    page_id         VARCHAR(64),
    
    -- Operation details
    operation       VARCHAR(32) NOT NULL,
    operation_detail JSONB,  -- {page_title, component_count, component_types[], warnings[]}
    
    -- Before/after snapshots (for rollback)
    before_snapshot JSONB,   -- Full page + components serialization
    after_snapshot  JSONB,   -- NULL for deletes
    
    -- Confirmation token reference (SHA256, not plaintext)
    confirmation_token_sha256 VARCHAR(64),
    
    -- Provenance
    tool_schema_version VARCHAR(32),
    model_id            VARCHAR(128),
    prompt_version      VARCHAR(32),
    
    -- User and session
    user_id         VARCHAR(128),
    user_email      VARCHAR(256),
    
    -- Timestamps
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_proposal ON ai_audit_logs(proposal_id);
CREATE INDEX idx_audit_course ON ai_audit_logs(course_id);
CREATE INDEX idx_audit_operation ON ai_audit_logs(operation);
CREATE INDEX idx_audit_created ON ai_audit_logs(created_at DESC);
```

**Table: `outbox_events` (extends US-AI-004 / US-AI-033)**

```sql
CREATE TABLE outbox_events (
    id              SERIAL PRIMARY KEY,
    event_id        VARCHAR(64) UNIQUE NOT NULL,
    event_type      VARCHAR(64) NOT NULL,  -- 'PageDeletedByAI'
    event_version   INTEGER NOT NULL DEFAULT 1,
    aggregate_id    VARCHAR(64) NOT NULL,  -- proposal_id
    aggregate_type  VARCHAR(32) NOT NULL DEFAULT 'proposal',
    payload         JSONB NOT NULL,
    trace_id        VARCHAR(64),
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at    TIMESTAMPTZ,
    retry_count     INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_outbox_unpublished ON outbox_events(published_at) WHERE published_at IS NULL;
CREATE INDEX idx_outbox_type ON outbox_events(event_type);
CREATE INDEX idx_outbox_aggregate ON outbox_events(aggregate_id);
```

### 2.2 SQLAlchemy ORM Models

**New file: `app/models/ai_proposal.py`**

```python
"""ORM model for AI proposals — two-phase mutation gating."""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import (
    String, DateTime, JSON, Text, Integer, Boolean,
    ForeignKey, TIMESTAMP, BigInteger
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMPTZ

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class AIProposalRecord(Base):
    __tablename__ = "ai_proposals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    proposal_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_sessions.session_id", ondelete="CASCADE"),
        index=True
    )
    course_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("courses.course_id", ondelete="CASCADE"),
        index=True
    )
    page_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("pages.page_id", ondelete="SET NULL"),
        nullable=True, index=True
    )

    operation: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="PENDING_REVIEW")

    # Delete-specific
    confirmation_token_sha256: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    confirmation_token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMPTZ, nullable=True
    )
    base_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    before_snapshot: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True
    )

    # Generic proposal fields
    after_candidate: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    validation_result: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    warning_messages: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    # Provenance
    tool_schema_version: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )
    prompt_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    model_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Timestamps
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)
    applied_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(128), unique=True, nullable=True
    )

    def to_dict(self) -> dict:
        return {
            "proposalId": self.proposal_id,
            "sessionId": self.session_id,
            "courseId": self.course_id,
            "pageId": self.page_id,
            "operation": self.operation,
            "status": self.status,
            "confirmationTokenExpiresAt": (
                self.confirmation_token_expires_at.isoformat()
                if self.confirmation_token_expires_at else None
            ),
            "baseHash": self.base_hash,
            "validationResult": self.validation_result,
            "warningMessages": self.warning_messages,
            "toolSchemaVersion": self.tool_schema_version,
            "promptVersion": self.prompt_version,
            "modelId": self.model_id,
            "expiresAt": self.expires_at.isoformat() if self.expires_at else None,
            "appliedAt": self.applied_at.isoformat() if self.applied_at else None,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }
```

### 2.3 Pydantic Request/Response DTOs

**Location: `app/routers/ai_proposals.py`** (new file — part of `/api/v1/ai/` module)

```python
from __future__ import annotations
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class ProposeDeletePageRequest(BaseModel):
    session_id: str = Field(..., description="Active AI session ID")
    page_id: str = Field(..., description="Page ID to delete")


class DependencyWarning(BaseModel):
    category: str = Field(..., description="e.g., 'branching', 'scoring', 'navigation', 'final_assessment', 'export'")
    severity: str = Field(..., description="'info' | 'warning' | 'error'")
    message: str = Field(..., description="Human-readable warning text")
    affected_ids: list[str] = Field(default_factory=list, description="Related entity IDs")


class ProposeDeletePageResponse(BaseModel):
    proposal_id: str
    page_id: str
    page_title: str
    page_order: int
    component_count: int
    component_types: list[str]
    confirmation_required: bool = Field(default=True, description="Always true for deletes")
    confirmation_token_expires_at: datetime
    warnings: list[DependencyWarning]
    base_hash: str


class ConfirmDeletePageRequest(BaseModel):
    session_id: str
    proposal_id: str
    user_approved_delete: bool = Field(..., description="Must be true to proceed")


class ConfirmDeletePageResponse(BaseModel):
    status: str = Field(..., description="'deleted'")
    page_id: str
    page_title: str
    proposal_id: str
    message: str


class DeletePageErrorResponse(BaseModel):
    code: str
    field: str
    message: str
    details: dict = Field(default_factory=dict)
```

### 2.4 API Contracts

#### POST /api/v1/ai/proposals/delete-page

Proposes deletion of a page. Never mutates domain data.

**Request:**
```json
{
  "session_id": "sess_abc123",
  "page_id": "page_xyz789"
}
```

**Response 200 (Proposal created):**
```json
{
  "proposal_id": "prop_del_001",
  "page_id": "page_xyz789",
  "page_title": "Unit 2 Final Assessment",
  "page_order": 4,
  "component_count": 3,
  "component_types": ["final-assessment", "content-text"],
  "confirmation_required": true,
  "confirmation_token_expires_at": "2026-06-14T11:45:00Z",
  "warnings": [
    {
      "category": "final_assessment",
      "severity": "warning",
      "message": "This page contains the final assessment. Deleting it will remove all scoring and completion configuration for this course.",
      "affected_ids": ["scoring_config_course_001"]
    },
    {
      "category": "branching",
      "severity": "warning",
      "message": "2 branching rules reference this page as a target. Affected rules: 'Remediation Path', 'Advanced Track'.",
      "affected_ids": ["branch_rule_001", "branch_rule_002"]
    }
  ],
  "base_hash": "a1b2c3d4e5f6..."
}
```

**Error Responses:**

`403 SESSION_EXPIRED`:
```json
{
  "code": "SESSION_EXPIRED",
  "field": "session_id",
  "message": "AI session has expired. Please start a new session.",
  "details": {}
}
```

`404 PAGE_NOT_FOUND`:
```json
{
  "code": "PAGE_NOT_FOUND",
  "field": "page_id",
  "message": "Page 'page_xyz789' not found in the session course.",
  "details": {}
}
```

`409 DUPLICATE_PROPOSAL`:
```json
{
  "code": "DUPLICATE_PROPOSAL",
  "field": "page_id",
  "message": "A pending delete proposal already exists for this page.",
  "details": {
    "existing_proposal_id": "prop_del_001",
    "existing_proposal_status": "PENDING_CONFIRMATION"
  }
}
```

#### POST /api/v1/ai/proposals/confirm-delete

Confirms and executes a previously proposed page deletion.

**Request:**
```json
{
  "session_id": "sess_abc123",
  "proposal_id": "prop_del_001",
  "user_approved_delete": true
}
```

**Response 200 (Deleted):**
```json
{
  "status": "deleted",
  "page_id": "page_xyz789",
  "page_title": "Unit 2 Final Assessment",
  "proposal_id": "prop_del_001",
  "message": "Page 'Unit 2 Final Assessment' has been deleted."
}
```

**Error Responses:**

`403 INVALID_CONFIRMATION_TOKEN`:
```json
{
  "code": "INVALID_CONFIRMATION_TOKEN",
  "field": "proposal_id",
  "message": "Confirmation token is invalid. The proposal may have been tampered with.",
  "details": {}
}
```

`410 CONFIRMATION_EXPIRED`:
```json
{
  "code": "CONFIRMATION_EXPIRED",
  "field": "proposal_id",
  "message": "The confirmation window has expired (15 minutes). Please create a new delete proposal.",
  "details": {
    "expired_at": "2026-06-14T11:45:00Z"
  }
}
```

`409 PAGE_CHANGED`:
```json
{
  "code": "PAGE_CHANGED",
  "field": "page_id",
  "message": "The page has been modified since the proposal was created. Please review and re-propose deletion.",
  "details": {
    "proposed_hash": "a1b2c3d4e5f6...",
    "current_hash": "f6e5d4c3b2a1..."
  }
}
```

`410 PAGE_ALREADY_DELETED`:
```json
{
  "code": "PAGE_ALREADY_DELETED",
  "field": "page_id",
  "message": "This page was already deleted by a previous confirmation.",
  "details": {}
}
```

`400 USER_CONFIRMATION_REQUIRED`:
```json
{
  "code": "USER_CONFIRMATION_REQUIRED",
  "field": "user_approved_delete",
  "message": "You must set user_approved_delete=true to confirm destructive deletion.",
  "details": {}
}
```

### 2.5 Service Signatures

**New file: `app/services/ai/proposal_orchestrator.py`**

```python
"""Orchestrates the AI proposal lifecycle — create, validate, confirm, apply."""

from __future__ import annotations
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.page_component import PageRecord


class ProposalOrchestrator:
    """Coordinates proposal lifecycle for AI mutations."""

    CONFIRMATION_TOKEN_TTL_MINUTES = 15
    PROPOSAL_TTL_HOURS = 24

    def __init__(self, session: AsyncSession):
        self.session = session

    async def propose_delete_page(
        self,
        session_id: str,
        course_id: str,
        page_id: str,
        user_id: str,
        tool_schema_version: Optional[str] = None,
        prompt_version: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> dict:
        """Create a delete proposal.

        Returns:
            dict with proposal_id, page metadata, warnings, confirmation metadata
        """
        # 1. Validate session is active (delegate to session service)
        # 2. Fetch page and verify it belongs to course_id
        # 3. Compute base_hash from page state
        # 4. Run dependency impact analysis
        # 5. Generate confirmation token
        # 6. Persist AIProposalRecord
        # 7. Return response dict
        raise NotImplementedError

    async def confirm_delete_page(
        self,
        session_id: str,
        proposal_id: str,
        user_approved_delete: bool,
        confirmation_token: str,
    ) -> dict:
        """Confirm and apply a delete proposal.

        Returns:
            dict with status=deleted, page_id, page_title, proposal_id
        """
        # 1. Look up proposal by proposal_id + session_id
        # 2. Verify status == PENDING_CONFIRMATION
        # 3. Verify SHA256(confirmation_token) matches stored hash
        # 4. Verify not expired
        # 5. Verify user_approved_delete == True
        # 6. Re-fetch page and verify base_hash matches
        # 7. Begin transaction
        # 8. Execute PageRepository.delete
        # 9. Post-delete validation and reorder
        # 10. Write audit log entry
        # 11. Write outbox event
        # 12. Update proposal status to APPLIED
        # 13. Commit
        # 14. Return response
        raise NotImplementedError

    async def _compute_page_hash(self, page: PageRecord) -> str:
        """Deterministic hash of a page and its components.

        Hash inputs:
            - page.page_id
            - page.title
            - page.order_index
            - page.updated_at.isoformat()
            - For each component: component_id, component_type, order_index, updated_at
        """
        parts = [
            page.page_id,
            page.title,
            str(page.order_index),
            page.updated_at.isoformat() if page.updated_at else "",
        ]
        for comp in sorted(page.components or [], key=lambda c: c.component_id):
            parts.extend([
                comp.component_id,
                comp.component_type,
                str(comp.order_index),
                comp.updated_at.isoformat() if comp.updated_at else "",
            ])
        raw = "::".join(parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def _generate_confirmation_token(self) -> tuple[str, str]:
        """Generate a random confirmation token and its SHA256 hash.

        Returns:
            (plaintext_token, sha256_hash)
        """
        token = secrets.token_hex(32)  # 64 hex chars
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return token, token_hash

    async def _run_dependency_analysis(
        self, course_id: str, page_id: str
    ) -> list[dict]:
        """Analyze dependencies that would be affected by deleting this page.

        Checks:
            1. Branch rules referencing page as source or target
            2. Course scoring config referencing components on this page
            3. Final assessment on this page
            4. Navigation impact (first/last/only page)
            5. Export readiness impact
        """
        raise NotImplementedError
```

**New file: `app/services/ai/dependency_analyzer.py`**

```python
"""Analyzes dependencies for destructive operations (delete) on courses."""

from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.branching import BranchRule
from app.models.page_component import PageRecord, ComponentRecord


class DependencyAnalyzer:
    """Checks what course features depend on a specific page."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def check_branching_rules(
        self, course_id: str, page_id: str
    ) -> list[dict]:
        """Find branch rules that reference this page."""
        q = select(BranchRule).where(
            BranchRule.course_id == course_id,
            (
                (BranchRule.source_page_id == page_id) |
                (BranchRule.default_target_page_id == page_id)
            )
        )
        result = await self.session.execute(q)
        rules = result.scalars().all()
        warnings = []
        for rule in rules:
            # Check if any condition targets this page
            for cond in (rule.conditions or []):
                if isinstance(cond, dict) and cond.get("targetPageId") == page_id:
                    warnings.append({
                        "category": "branching",
                        "severity": "warning",
                        "message": (
                            f"Branch rule '{rule.title}' has a condition "
                            f"targeting this page."
                        ),
                        "affected_ids": [rule.branch_id],
                    })
                    break
            if rule.default_target_page_id == page_id:
                warnings.append({
                    "category": "branching",
                    "severity": "warning",
                    "message": (
                        f"Branch rule '{rule.title}' uses this page as the "
                        f"default target for unmatched conditions."
                    ),
                    "affected_ids": [rule.branch_id],
                })
            if rule.source_page_id == page_id:
                warnings.append({
                    "category": "branching",
                    "severity": "info",
                    "message": (
                        f"Branch rule '{rule.title}' originates from this page. "
                        f"Deleting the page will remove the rule's source."
                    ),
                    "affected_ids": [rule.branch_id],
                })
        return warnings

    async def check_final_assessment(
        self, page: PageRecord
    ) -> list[dict]:
        """Check if the page contains a final-assessment component."""
        for comp in (page.components or []):
            if comp.component_type == "final-assessment":
                return [{
                    "category": "final_assessment",
                    "severity": "warning",
                    "message": (
                        "This page contains the final assessment. Deleting it "
                        "will remove all scoring and completion configuration "
                        "for this course."
                    ),
                    "affected_ids": [comp.component_id],
                }]
        return []

    async def check_navigation_impact(
        self, course_id: str, page: PageRecord, page_count_in_course: int
    ) -> list[dict]:
        """Check if deleting this page breaks course navigation."""
        warnings = []
        if page_count_in_course <= 1:
            warnings.append({
                "category": "navigation",
                "severity": "error",
                "message": "This is the only page in the course. Deleting it will leave the course empty.",
                "affected_ids": [course_id],
            })
        elif page.order_index == 0:
            warnings.append({
                "category": "navigation",
                "severity": "info",
                "message": (
                    "This is the first page in the course. Deleting it will "
                    "promote the next page to the first position."
                ),
                "affected_ids": [],
            })
        return warnings

    async def check_scoring_references(
        self, course_id: str, page: PageRecord
    ) -> list[dict]:
        """Check if scoring configuration references components on this page."""
        from app.models.scoring import CourseScoringRecord
        q = select(CourseScoringRecord).where(
            CourseScoringRecord.course_id == course_id
        )
        result = await self.session.execute(q)
        scoring = result.scalar_one_or_none()
        if not scoring:
            return []

        warnings = []
        component_ids = {c.component_id for c in (page.components or [])}
        if scoring.component_scores:
            for score_entry in (scoring.component_scores or []):
                comp_id = score_entry.get("componentId")
                if comp_id in component_ids:
                    warnings.append({
                        "category": "scoring",
                        "severity": "warning",
                        "message": (
                            f"Scoring configuration references component "
                            f"'{comp_id}' on this page. Deleting the page "
                            f"will remove this scoring entry."
                        ),
                        "affected_ids": [scoring.scoring_id, comp_id],
                    })
        return warnings

    async def analyze_all(
        self, course_id: str, page: PageRecord, page_count: int
    ) -> list[dict]:
        """Run all dependency checks and return consolidated warnings."""
        warnings = []
        warnings.extend(await self.check_branching_rules(course_id, page.page_id))
        warnings.extend(await self.check_final_assessment(page))
        warnings.extend(await self.check_navigation_impact(course_id, page, page_count))
        warnings.extend(await self.check_scoring_references(course_id, page))
        return warnings
```

### 2.6 API Router

**New file: `app/routers/ai_proposals.py`**

```python
"""AI Proposal routers — propose and confirm page operations.

Endpoints:
  POST /api/v1/ai/proposals/delete-page
  POST /api/v1/ai/proposals/confirm-delete
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.utils.error_envelope import api_http_exception

from app.routers.ai_proposals_dtos import (
    ProposeDeletePageRequest,
    ProposeDeletePageResponse,
    ConfirmDeletePageRequest,
    ConfirmDeletePageResponse,
    DependencyWarning,
)
from app.services.ai.proposal_orchestrator import ProposalOrchestrator

router = APIRouter(prefix="/api/v1/ai/proposals", tags=["AI Proposals"])


@router.post(
    "/delete-page",
    response_model=ProposeDeletePageResponse,
    summary="Propose deletion of a course page (destructive gate)",
    responses={
        403: {"description": "Session expired or page not in scope"},
        404: {"description": "Page not found"},
        409: {"description": "Duplicate pending proposal"},
    },
)
async def propose_delete_page(
    body: ProposeDeletePageRequest,
    session: AsyncSession = Depends(get_session),
):
    """Phase 1 of the two-phase delete gate.

    Creates a PENDING_CONFIRMATION proposal with dependency warnings and
    a confirmation token. The page is NOT deleted at this stage.
    """
    orchestrator = ProposalOrchestrator(session)

    # Resolve session (delegate to US-AI-006 session validation)
    # For now, inline course_id resolution from session_id
    # In production, validate via AISessionRepository

    from app.repositories.page_component_repo import PageRepository

    # 1. Validate session (stub — US-AI-006 provides this)
    # session_record = await ai_session_repo.get_active(body.session_id)
    # if not session_record:
    #     raise api_http_exception(403, "SESSION_EXPIRED", "Session expired")
    # course_id = session_record.course_id

    # TEMP: direct lookup until session service is wired
    page_repo = PageRepository(session)
    page = await page_repo.get(body.page_id)
    if not page:
        raise api_http_exception(
            404, "PAGE_NOT_FOUND", f"Page '{body.page_id}' not found"
        )
    course_id = page.course_id

    # 2. Check for existing pending proposal
    # (delegate to AIProposalRepository)
    # existing = await proposal_repo.get_pending_by_page(session_id, page_id)

    try:
        result = await orchestrator.propose_delete_page(
            session_id=body.session_id,
            course_id=course_id,
            page_id=body.page_id,
            user_id="system",  # TODO: inject from auth
            tool_schema_version="1.0",
            prompt_version="1.0",
            model_id="deepseek-v4-flash",
        )
    except ValueError as exc:
        raise api_http_exception(400, "PROPOSAL_FAILED", str(exc))

    return result


@router.post(
    "/confirm-delete",
    response_model=ConfirmDeletePageResponse,
    summary="Confirm and execute a previously proposed page deletion",
    responses={
        400: {"description": "User confirmation required"},
        403: {"description": "Invalid confirmation token"},
        409: {"description": "Page changed or proposal already applied"},
        410: {"description": "Confirmation expired or page already deleted"},
    },
)
async def confirm_delete_page(
    body: ConfirmDeletePageRequest,
    session: AsyncSession = Depends(get_session),
):
    """Phase 2 of the two-phase delete gate.

    Validates the confirmation token, re-checks page hash, and executes
    the deletion in a single database transaction.
    """
    orchestrator = ProposalOrchestrator(session)

    # In production, retrieve the stored confirmation_token from the
    # frontend's request context or a secure token store.
    # The frontend must send the token with the request.
    confirmation_token = "token-from-request-header-or-body"

    try:
        result = await orchestrator.confirm_delete_page(
            session_id=body.session_id,
            proposal_id=body.proposal_id,
            user_approved_delete=body.user_approved_delete,
            confirmation_token=confirmation_token,
        )
    except ValueError as exc:
        raise api_http_exception(400, "CONFIRMATION_FAILED", str(exc))
    except PermissionError as exc:
        raise api_http_exception(403, "INVALID_CONFIRMATION_TOKEN", str(exc))
    except RuntimeError as exc:
        raise api_http_exception(409, "CONFIRMATION_CONFLICT", str(exc))

    return result
```

### 2.7 AIProposal Repository

**New file: `app/repositories/ai_proposal_repo.py`**

```python
"""Repository for AIProposalRecord persistence."""
from __future__ import annotations
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_proposal import AIProposalRecord


class AIProposalRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_proposal_id(
        self, proposal_id: str
    ) -> Optional[AIProposalRecord]:
        q = select(AIProposalRecord).where(
            AIProposalRecord.proposal_id == proposal_id
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def get_pending_by_page(
        self, session_id: str, page_id: str
    ) -> Optional[AIProposalRecord]:
        """Find a pending delete proposal for a given page in a session."""
        q = select(AIProposalRecord).where(
            and_(
                AIProposalRecord.session_id == session_id,
                AIProposalRecord.page_id == page_id,
                AIProposalRecord.operation == "delete_page",
                AIProposalRecord.status.in_([
                    "PENDING_REVIEW", "PENDING_CONFIRMATION", "APPROVED"
                ]),
            )
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def create(
        self, record: AIProposalRecord
    ) -> AIProposalRecord:
        self.session.add(record)
        await self.session.flush()
        await self.session.refresh(record)
        return record

    async def update(self, record: AIProposalRecord) -> AIProposalRecord:
        await self.session.flush()
        await self.session.refresh(record)
        return record

    async def get_by_session_and_proposal(
        self, session_id: str, proposal_id: str
    ) -> Optional[AIProposalRecord]:
        q = select(AIProposalRecord).where(
            and_(
                AIProposalRecord.session_id == session_id,
                AIProposalRecord.proposal_id == proposal_id,
            )
        )
        return (await self.session.execute(q)).scalar_one_or_none()
```

### 2.8 Alembic Migration

**New file: `alembic/versions/20260614_0001_add_ai_proposals_tables.py`**

```python
"""Add ai_proposals, ai_audit_logs, outbox_events tables.

Revision ID: 20260614_0001
Revises: <previous_revision_id>
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMPTZ

revision = "20260614_0001"
down_revision = "<previous_revision_id>"
branch_labels = None
depends_on = None


def upgrade():
    # ai_proposals
    op.create_table(
        "ai_proposals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("proposal_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("course_id", sa.String(64), nullable=False),
        sa.Column("page_id", sa.String(64), nullable=True),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING_REVIEW"),
        sa.Column("confirmation_token_sha256", sa.String(64), nullable=True),
        sa.Column("confirmation_token_expires_at", TIMESTAMPTZ(), nullable=True),
        sa.Column("base_hash", sa.String(64), nullable=True),
        sa.Column("before_snapshot", JSONB(), nullable=True),
        sa.Column("after_candidate", JSONB(), nullable=True),
        sa.Column("validation_result", JSONB(), nullable=True),
        sa.Column("warning_messages", JSONB(), nullable=True),
        sa.Column("tool_schema_version", sa.String(32), nullable=True),
        sa.Column("prompt_version", sa.String(32), nullable=True),
        sa.Column("model_id", sa.String(128), nullable=True),
        sa.Column("expires_at", TIMESTAMPTZ(), nullable=False),
        sa.Column("applied_at", TIMESTAMPTZ(), nullable=True),
        sa.Column("created_at", TIMESTAMPTZ(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TIMESTAMPTZ(), server_default=sa.func.now(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["ai_sessions.session_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.course_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["page_id"], ["pages.page_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("proposal_id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("idx_ai_proposals_session", "ai_proposals", ["session_id"])
    op.create_index("idx_ai_proposals_status", "ai_proposals", ["status"])
    op.create_index("idx_ai_proposals_course", "ai_proposals", ["course_id"])
    op.create_index("idx_ai_proposals_page", "ai_proposals", ["page_id"])

    # ai_audit_logs
    op.create_table(
        "ai_audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("audit_id", sa.String(64), nullable=False),
        sa.Column("proposal_id", sa.String(64), nullable=True),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("course_id", sa.String(64), nullable=False),
        sa.Column("page_id", sa.String(64), nullable=True),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("operation_detail", JSONB(), nullable=True),
        sa.Column("before_snapshot", JSONB(), nullable=True),
        sa.Column("after_snapshot", JSONB(), nullable=True),
        sa.Column("confirmation_token_sha256", sa.String(64), nullable=True),
        sa.Column("tool_schema_version", sa.String(32), nullable=True),
        sa.Column("model_id", sa.String(128), nullable=True),
        sa.Column("prompt_version", sa.String(32), nullable=True),
        sa.Column("user_id", sa.String(128), nullable=True),
        sa.Column("user_email", sa.String(256), nullable=True),
        sa.Column("created_at", TIMESTAMPTZ(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("audit_id"),
    )
    op.create_index("idx_audit_proposal", "ai_audit_logs", ["proposal_id"])
    op.create_index("idx_audit_course", "ai_audit_logs", ["course_id"])
    op.create_index("idx_audit_operation", "ai_audit_logs", ["operation"])
    op.create_index("idx_audit_created", "ai_audit_logs", [sa.text("created_at DESC")])

    # outbox_events
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("aggregate_id", sa.String(64), nullable=False),
        sa.Column("aggregate_type", sa.String(32), nullable=False, server_default="proposal"),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("occurred_at", TIMESTAMPTZ(), server_default=sa.func.now(), nullable=False),
        sa.Column("published_at", TIMESTAMPTZ(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index(
        "idx_outbox_unpublished", "outbox_events",
        [sa.text("published_at")],
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.create_index("idx_outbox_type", "outbox_events", ["event_type"])
    op.create_index("idx_outbox_aggregate", "outbox_events", ["aggregate_id"])


def downgrade():
    op.drop_table("outbox_events")
    op.drop_table("ai_audit_logs")
    op.drop_table("ai_proposals")
```

### 2.9 Main Application Registration

**In `app/main.py`, add to the router registration:**

```python
from app.routers import ai_proposals  # new import

# In the router registration section:
api_router.include_router(ai_proposals.router)
```

Also add to the `lifespan` startup section:

```python
import app.models.ai_proposal  # noqa: F401 — register ORM model
```

### 2.10 App Initialization Register

In `app/models/__init__.py`, add:

```python
# Future: uncomment when AI models are implemented
# from app.models.ai_proposal import AIProposalRecord
```

### 2.11 Environment Variables

Add to `.env` and `.env.example`:

```ini
# ============================================
# AI Proposal Configuration
# ============================================
AI_PROPOSAL_TTL_HOURS=24
AI_CONFIRMATION_TOKEN_TTL_MINUTES=15
AI_DELETE_CONFIRMATION_REQUIRED=true
```

These are read by the `ProposalOrchestrator`:

```python
import os

CONFIRMATION_TOKEN_TTL_MINUTES = int(
    os.getenv("AI_CONFIRMATION_TOKEN_TTL_MINUTES", "15")
)
PROPOSAL_TTL_HOURS = int(
    os.getenv("AI_PROPOSAL_TTL_HOURS", "24")
)
```

---

## 3. Non-Functional Requirements

### 3.1 Performance

| Requirement | Target | Measurement |
|---|---|---|
| Proposal creation latency | < 500 ms p95 | API response time for `propose_delete_page` |
| Confirmation and apply latency | < 1 s p95 | API response time for `confirm_delete_page` (includes DB transaction + audit write) |
| Dependency analysis latency | < 200 ms p95 | Time to query branching rules, scoring, and navigation checks |
| Concurrent proposals per course | <= 1 pending delete proposal per page per session | Application-level guard |

### 3.2 Security

| Requirement | Implementation |
|---|---|
| Confirmation token entropy | 64 hex chars from `secrets.token_hex(32)` (256 bits) |
| Token storage | Only SHA256 hash stored in DB; plaintext token never persisted |
| Token lifetime | 15 minutes (configurable via `AI_CONFIRMATION_TOKEN_TTL_MINUTES`) |
| Token transport | Must be sent by frontend via HTTPS; never in URL query params |
| Proposal tampering | `session_id` + `proposal_id` scoping; re-validation at confirmation phase |
| Page hash tampering | Re-computed at confirmation time and compared to stored `base_hash` |
| Audit integrity | `confirmation_token_sha256` stored in audit log for non-repudiation |
| Feature gating | All AI proposal endpoints require `AI_AUTHORING_ENABLED=true` feature flag |

### 3.3 Data Integrity

| Requirement | Implementation |
|---|---|
| Atomic delete + audit + outbox | Single database transaction (all-or-nothing) |
| Cascade delete | ORM `cascade="all, delete-orphan"` on `PageRecord.components` |
| Proposal idempotency | `idempotency_key` unique constraint; duplicate keys return existing proposal |
| Page hash consistency | Re-checked at confirmation; `409 CONFLICT` if stale |
| Before-snapshot completeness | Full page + components serialized as JSONB before deletion |

### 3.4 Availability

| Requirement | Implementation |
|---|---|
| Outbox write failure tolerance | Outbox write failures are logged but do not roll back the delete; a background worker retries |
| Proposal expiry | Background cleanup job (or inline check on access) clears expired proposals |
| Feature flag isolation | When `AI_AUTHORING_ENABLED=false`, all proposal endpoints return `404 FEATURE_NOT_AVAILABLE` |

### 3.5 Observability

| Requirement | Implementation |
|---|---|
| Trace ID | Every proposal creation and confirmation logs a `trace_id` correlated across services |
| Metric: proposal_created | Counter incremented on `propose_delete_page` (tagged by `operation=delete_page`) |
| Metric: proposal_confirmed | Counter incremented on `confirm_delete_page` (tagged by `outcome=success|failure`) |
| Metric: proposal_expired | Counter incremented when an expired token is rejected |
| Log: security event | Logged when `INVALID_CONFIRMATION_TOKEN` occurs (possible tampering attempt) |

---

## 4. Current State

### 4.1 What Exists Today

1. **Page/Component CRUD**: The existing `DELETE /api/v1/courses/{courseId}/pages/{pageId}` endpoint at `app/routers/page_components.py:207` performs direct deletion with `PageRepository.delete(page)`, which uses `await self.session.delete(page)` followed by `await self.session.commit()`. Components cascade via ORM. There is no proposal gate, no confirmation token, no audit trail, and no outbox event.

2. **PageRepository**: `app/repositories/page_component_repo.py` provides `delete(self, page: PageRecord)` which does `await self.session.delete(page)` + `commit`. This is the target for the mutation phase of the confirm-delete flow.

3. **PageRecord**: `app/models/page_component.py` — `PageRecord` at line 20 has `page_id`, `course_id`, `title`, `order_index`, `layout`, `theme_config`, `completion_config`, `created_at`, `updated_at`, and a `components` relationship with `cascade="all, delete-orphan"`. `ComponentRecord` at line 77 has `component_id`, `page_id`, `component_type`, `data`, etc.

4. **Branching**: `app/models/branching.py` defines `BranchRule` with `source_page_id`, `default_target_page_id`, and `conditions` (JSON array with `targetPageId` entries). `BranchEvent` records learner decisions. These are checked during dependency analysis.

5. **Scoring**: `app/models/scoring.py` defines `CourseScoringRecord` with `component_scores` JSON field that may reference component IDs on the page being deleted.

6. **No AI Proposals Yet**: There is no `ai_proposals` table, no `ai_audit_logs` table, no `outbox_events` table, and no AI proposal router or service. These must all be created as part of US-AI-004 (persistence foundations) and US-AI-010 (apply safety), which this story depends on.

7. **Error Envelope**: `app/utils/error_envelope.py` provides `build_error()` and `api_http_exception()` for consistent API error responses. The existing validation error handler at `app/main.py:140` returns structured error arrays.

8. **Flow Diagrams**: `docs/AI_Implemenation/01_SystemArchitecture/Delete_Page_Proposal_and_Confirm_Flow.mmd` and `Destructive_Delete_Scenario_Flow.mmd` exist as Mermaid diagrams defining the two-phase delete flow.

9. **User Stories Doc**: `docs/AI_Implemenation/00_User_StoriesUseCases/USER_STORIES.md` contains the high-level definition of US-AI-013 at lines 339-359.

### 4.2 What is Missing

1. All AI proposal tables (`ai_proposals`, `ai_audit_logs`, `outbox_events`) and their ORM models.
2. The `ProposalOrchestrator` service class with `propose_delete_page` and `confirm_delete_page` methods.
3. The `DependencyAnalyzer` service class with checks for branching, scoring, final assessment, navigation.
4. The API router (`POST /api/v1/ai/proposals/delete-page` and `POST /api/v1/ai/proposals/confirm-delete`).
5. The AI proposal repository.
6. Confirmation token generation, hashing, and validation logic.
7. Page hash computation at proposal time and re-validation at confirmation time.
8. Transactional integration of delete + audit + outbox.
9. Frontend confirmation modal (epic boundary: this story defines the backend contract; frontend implementation is in US-AI-024).
10. Unit and integration tests for the two-phase gate.

### 4.3 Dependencies on Earlier Stories

| Story | Dependency |
|---|---|
| US-AI-002 | Feature flag for `AI_AUTHORING_ENABLED` |
| US-AI-003 | Isolated AI API module structure |
| US-AI-004 | `ai_proposals`, `ai_audit_logs`, `outbox_events` table designs |
| US-AI-005 | Tool schema for `propose_delete_page` and `confirm_delete_page` tools |
| US-AI-006 | Session validation and course scope resolution |
| US-AI-009 | Generic proposal lifecycle (statuses, TTL, apply guards) |
| US-AI-010 | Apply safety (transactional mutation + audit + outbox) |

---

## 5. Expansion Points

### 5.1 Soft-Delete Retention (Post-MVP)

Instead of hard-deleting the page record, an alternate strategy would mark the page as `is_deleted = TRUE` and retain it for a configurable retention window (e.g., 30 days). The proposal before-snapshot already enables this; the ORM `delete()` call would be replaced with a status update. This would require:
- Adding an `is_deleted` column to `PageRecord`.
- Adding a `deleted_at` column to `PageRecord`.
- Filtering queries to exclude soft-deleted pages.
- A background job to hard-delete expired soft-deleted pages.

### 5.2 Batch Delete Proposal (Post-MVP)

A natural extension is `propose_batch_delete_pages(session_id, page_ids[])` which creates a batch proposal (US-AI-029) for deleting multiple pages atomically. The dependency analysis would be computed across all pages, and the all-or-nothing apply transaction would delete all pages or none.

### 5.3 Automatic Reorder After Delete

Currently the story specifies calling `PageRepository.reorder` after deletion to close the gap. A future improvement could skip reordering by allowing the UI to handle sparse order indices, avoiding unnecessary writes to all subsequent pages on every deletion.

### 5.4 UI-Initiated Delete Proposal (Post-MVP)

Today, the existing `DELETE /api/v1/courses/{courseId}/pages/{pageId}` endpoint remains available for manual authoring. A future story could route all deletes (AI and manual) through the proposal gate by adding an optional `force` parameter or by redirecting the manual delete endpoint through `ProposalOrchestrator`.

### 5.5 Configurable Policy Engine Integration

When US-AI-032 (Policy Engine) is implemented, the confirmation requirement could be downgraded for low-risk pages (e.g., a content-text page with no branching/scoring references deleted by a course admin). The `confirmation_required` field in the response would be set based on policy evaluation rather than hardcoded to `true`.

### 5.6 Preview Before Delete

A future enhancement could generate a preview showing the course state after deletion (simulated, not actually applied) so the user can see the impact before confirming. This is related to US-AI-041 (Async Preview Generation Service).

---

## 6. Validation and Test Scenarios

### 6.1 Unit Tests (Service Layer)

```python
# File: tests/test_ai_proposal_orchestrator.py

class TestProposeDeletePage:
    async def test_propose_delete_happy_path(self, db_session, sample_course_with_pages):
        """A valid page can be proposed for deletion with a confirmation token."""
        pass

    async def test_propose_delete_unknown_page_raises_error(self, db_session):
        """Proposing deletion of a non-existent page returns PAGE_NOT_FOUND."""
        pass

    async def test_propose_delete_page_not_in_session_course_raises_error(self, db_session):
        """A page outside the session's course scope is rejected."""
        pass

    async def test_propose_delete_duplicate_pending_returns_409(self, db_session):
        """A second pending proposal for the same page returns the existing one."""
        pass

    async def test_propose_delete_with_expired_session_returns_session_error(self, db_session):
        """An expired session cannot create proposals."""
        pass

    async def test_propose_delete_dependency_final_assessment_warning(self, db_session):
        """A page with a final-assessment component returns a final_assessment warning."""
        pass

    async def test_propose_delete_dependency_branching_rule_target_warning(self, db_session):
        """A page referenced by branching rules returns branching warnings."""
        pass

    async def test_propose_delete_only_page_navigation_warning(self, db_session):
        """The last/only page in a course generates a navigation error warning."""
        pass

    async def test_propose_delete_dependency_scoring_reference_warning(self, db_session):
        """A page with scoring-referenced components returns scoring warnings."""
        pass

    async def test_propose_delete_generates_confirmation_token(self, db_session):
        """A proposal always generates a confirmation token with SHA256 hash."""
        pass

    async def test_propose_delete_never_mutates_domain_data(self, db_session):
        """After propose_delete, the page still exists unchanged in the DB."""
        pass

    async def test_propose_delete_computes_base_hash(self, db_session):
        """The base_hash is deterministic and unique per page state."""
        pass

    async def test_propose_delete_sets_ttl(self, db_session):
        """The proposal has a TTL of 24 hours (configurable)."""
        pass


class TestConfirmDeletePage:
    async def test_confirm_delete_happy_path(self, db_session, sample_course_with_pages):
        """A valid confirmation token deletes the page and cascades components."""
        pass

    async def test_confirm_delete_without_approval_returns_400(self, db_session):
        """Setting user_approved_delete=false returns USER_CONFIRMATION_REQUIRED."""
        pass

    async def test_confirm_delete_wrong_token_returns_403(self, db_session):
        """An incorrect confirmation token returns INVALID_CONFIRMATION_TOKEN."""
        pass

    async def test_confirm_delete_expired_token_returns_410(self, db_session):
        """A token past its expiry returns CONFIRMATION_EXPIRED."""
        pass

    async def test_confirm_delete_page_changed_returns_409(self, db_session):
        """If the page was modified after proposal, return PAGE_CHANGED conflict."""
        pass

    async def test_confirm_delete_page_already_deleted_returns_410(self, db_session):
        """Calling confirm on an already-deleted page returns PAGE_ALREADY_DELETED."""
        pass

    async def test_confirm_delete_proposal_already_applied_returns_409(self, db_session):
        """A proposal with status APPLIED cannot be applied again."""
        pass

    async def test_confirm_delete_preserves_other_pages(self, db_session):
        """Deleting one page does not affect other pages in the course."""
        pass

    async def test_confirm_delete_components_cascaded(self, db_session):
        """All components on the deleted page are removed from the database."""
        pass

    async def test_confirm_delete_writes_audit_log(self, db_session):
        """A successful delete creates an entry in ai_audit_logs with before_snapshot."""
        pass

    async def test_confirm_delete_writes_outbox_event(self, db_session):
        """A successful delete creates an outbox event of type PageDeletedByAI."""
        pass

    async def test_confirm_delete_atomic_rollback_on_failure(self, db_session, monkeypatch):
        """If audit write fails, the page delete is rolled back."""
        pass

    async def test_confirm_delete_proposal_status_applied(self, db_session):
        """After successful delete, proposal status is APPLIED with applied_at set."""
        pass

    async def test_confirm_delete_reorders_remaining_pages(self, db_session):
        """After deleting page at index 2, pages at indices 3+ shift down by 1."""
        pass


class TestDependencyAnalyzer:
    async def test_check_no_dependencies(self, db_session):
        """A simple content-text page with no relations returns no warnings."""
        pass

    async def test_check_branching_source_and_target(self, db_session):
        """Branch rules referencing the page as source or target are detected."""
        pass

    async def test_check_branching_condition_target(self, db_session):
        """Branch conditions with targetPageId matching the page are detected."""
        pass

    async def test_check_final_assessment_present(self, db_session):
        """A page with a final-assessment component is detected."""
        pass

    async def test_check_final_assessment_absent(self, db_session):
        """A page without final-assessment does not generate that warning."""
        pass

    async def test_check_navigation_only_page(self, db_session):
        """The only page in a course generates a navigation error."""
        pass

    async def test_check_navigation_first_page(self, db_session):
        """The first page generates an info-level navigation note."""
        pass

    async def test_check_scoring_references(self, db_session):
        """Scoring config referencing components on the page is detected."""
        pass

    async def test_check_scoring_no_references(self, db_session):
        """Scoring config without component references generates no warning."""
        pass


class TestPageHash:
    async def test_hash_changes_on_title_update(self, db_session):
        """Updating the page title changes the hash."""
        pass

    async def test_hash_changes_on_component_add(self, db_session):
        """Adding a component to the page changes the hash."""
        pass

    async def test_hash_changes_on_component_update(self, db_session):
        """Updating a component's data changes the hash."""
        pass

    async def test_hash_is_deterministic(self, db_session):
        """Calling _compute_page_hash twice on the same page returns the same hash."""
        pass

    async def test_hash_differs_for_different_pages(self, db_session):
        """Two different pages have different hashes."""
        pass
```

### 6.2 Integration Tests (API Layer)

```python
# File: tests/test_ai_proposals_api.py

class TestProposeDeleteAPI:
    async def test_propose_delete_endpoint_returns_200(self, async_client, sample_ai_session, sample_page):
        """POST /api/v1/ai/proposals/delete-page returns 200 with proposal data."""
        pass

    async def test_propose_delete_endpoint_without_auth_returns_403(self, async_client):
        """Unidentified users are rejected."""
        pass

    async def test_propose_delete_endpoint_unknown_page_returns_404(self, async_client, sample_ai_session):
        """POST with a non-existent page_id returns 404."""
        pass

    async def test_propose_delete_response_shape(self, async_client, sample_ai_session, sample_page):
        """Response includes all required fields: proposal_id, warnings, confirmation_required."""
        pass

    async def test_propose_delete_feature_flag_disabled_returns_404(self, async_client):
        """When AI_AUTHORING_ENABLED=false, endpoint returns 404."""
        pass


class TestConfirmDeleteAPI:
    async def test_confirm_delete_endpoint_returns_200(self, async_client, sample_delete_proposal):
        """POST /api/v1/ai/proposals/confirm-delete returns 200 with status=deleted."""
        pass

    async def test_confirm_delete_without_approval_returns_400(self, async_client, sample_delete_proposal):
        """user_approved_delete=false returns 400."""
        pass

    async def test_confirm_delete_wrong_proposal_returns_404(self, async_client, sample_ai_session):
        """POST with a non-existent proposal_id returns 404."""
        pass

    async def test_confirm_delete_page_verifiable_via_list(self, async_client, sample_delete_proposal):
        """After successful confirm-delete, the page is no longer in the page list."""
        pass
```

### 6.3 E2E Scenarios

**Scenario 1: Chat-driven assessment page deletion (happy path)**
1. User: "Remove the final assessment page from Unit 2."
2. AI agent calls `list_pages` and `fetch_page` to resolve the target.
3. AI agent calls `propose_delete_page`; backend returns warnings about scoring impact.
4. Frontend renders destructive confirmation modal showing assessment warnings.
5. User types "DELETE" and clicks confirm.
6. Frontend calls `confirm_delete_page` with `user_approved_delete=true`.
7. Backend deletes the page, cascades components, writes audit + outbox.
8. Frontend refreshes page list; page is gone.

**Scenario 2: Confirmation token expiry**
1. User proposes deletion of a page.
2. User waits 16 minutes (beyond the 15-minute TTL).
3. User clicks confirm.
4. Backend returns `410 CONFIRMATION_EXPIRED`.
5. Frontend shows message "Confirmation window expired. Please try again."
6. User must re-initiate the delete proposal from the AI.

**Scenario 3: Page modified between proposal and confirm**
1. User proposes deletion of page "Intro".
2. Another user (or same user via manual editor) modifies the page title.
3. User clicks confirm.
4. Backend returns `409 PAGE_CHANGED`.
5. Frontend shows message "Page has changed since the proposal. Please review."
6. Agent re-fetches the page and creates a fresh proposal.

**Scenario 4: Final assessment page with branching dependencies (maximum warnings)**
1. Course has 5 pages. Page 3 is a final assessment with branching rules targeting it.
2. AI proposes deleting page 3.
3. Backend returns warnings: `final_assessment`, `branching` (2 rules), `navigation`.
4. Frontend shows stacked warnings in the confirmation modal.
5. User reviews warnings and decides to proceed ("I have a backup plan").
6. Delete proceeds; all warnings are recorded in the audit trail.

**Scenario 5: User cancels deletion**
1. AI proposes deletion; frontend shows modal.
2. User clicks "Cancel" (or closes the modal).
3. No API call is made to the backend.
4. Proposal remains in `PENDING_CONFIRMATION` state until TTL expiry.
5. Backend cleanup job expires orphaned proposals.

### 6.4 Safety Invariant Tests

These tests verify that the core safety invariants of the two-phase gate hold:

```python
# Invariant: propose_* never mutates domain data
async def test_invariant_propose_does_not_delete(test_client, sample_course_with_pages):
    page_id = sample_course_with_pages["page_id"]
    # Call propose_delete_page
    response = test_client.post("/api/v1/ai/proposals/delete-page", json={
        "session_id": "test_session",
        "page_id": page_id,
    })
    assert response.status_code == 200
    # Verify the page still exists
    get_response = test_client.get(
        f"/api/v1/courses/{sample_course_with_pages['course_id']}/pages/{page_id}"
    )
    assert get_response.status_code == 200

# Invariant: confirm without user_approved_delete=true never deletes
async def test_invariant_no_approval_no_delete(test_client, sample_delete_proposal):
    response = test_client.post("/api/v1/ai/proposals/confirm-delete", json={
        "session_id": sample_delete_proposal["session_id"],
        "proposal_id": sample_delete_proposal["proposal_id"],
        "user_approved_delete": False,
    })
    assert response.status_code == 400
    # Verify page still exists
    ...

# Invariant: expired token never deletes
async def test_invariant_expired_token_no_delete(test_client, sample_expired_proposal):
    response = test_client.post("/api/v1/ai/proposals/confirm-delete", json={
        "session_id": sample_expired_proposal["session_id"],
        "proposal_id": sample_expired_proposal["proposal_id"],
        "user_approved_delete": True,
    })
    assert response.status_code == 410
    ...

# Invariant: page hash mismatch prevents deletion
async def test_invariant_hash_mismatch_no_delete(test_client, sample_modified_page_proposal):
    response = test_client.post("/api/v1/ai/proposals/confirm-delete", json={
        "session_id": sample_modified_page_proposal["session_id"],
        "proposal_id": sample_modified_page_proposal["proposal_id"],
        "user_approved_delete": True,
    })
    assert response.status_code == 409
    ...
```

### 6.5 Concurrency Tests

```python
async def test_concurrent_proposal_same_page(test_client, sample_ai_session, sample_page):
    """Two concurrent propose_delete_page calls for the same page should result in
    one proposal created and the second returning 409 DUPLICATE_PROPOSAL."""
    pass

async def test_confirm_delete_while_manual_edit_in_progress(test_client, sample_delete_proposal):
    """If a manual PATCH to the page happens between proposal and confirm,
    the confirmation detects the hash mismatch and rejects."""
    pass
```

---

## 7. Definition of Done

### 7.1 Code Complete

- [ ] `app/models/ai_proposal.py` — ORM model with all fields as specified in section 2.2.
- [ ] `app/repositories/ai_proposal_repo.py` — Repository with `get_by_proposal_id`, `get_pending_by_page`, `create`, `update`, `get_by_session_and_proposal`.
- [ ] `app/services/ai/proposal_orchestrator.py` — `ProposalOrchestrator` with `propose_delete_page` and `confirm_delete_page` methods.
- [ ] `app/services/ai/dependency_analyzer.py` — `DependencyAnalyzer` with checks for branching, final assessment, navigation, scoring.
- [ ] `app/routers/ai_proposals.py` — Router with `POST /api/v1/ai/proposals/delete-page` and `POST /api/v1/ai/proposals/confirm-delete`.
- [ ] `app/routers/ai_proposals_dtos.py` — All Pydantic request/response models.
- [ ] Alembic migration for `ai_proposals`, `ai_audit_logs`, `outbox_events` tables.
- [ ] Registration in `app/main.py` (router + ORM model import).
- [ ] Environment variables documented in `.env.example`.

### 7.2 Tests Pass

- [ ] All unit tests pass (20+ tests in `test_ai_proposal_orchestrator.py`).
- [ ] All integration tests pass (8+ tests in `test_ai_proposals_api.py`).
- [ ] All safety invariant tests pass (4 tests).
- [ ] All concurrency tests pass (2 tests).
- [ ] Existing page CRUD tests in `test_page_components_api.py` still pass (regression).
- [ ] Coverage >= 90% for new code.

### 7.3 Documentation

- [ ] API contracts documented in `docs/API.md` or OpenAPI spec.
- [ ] Environment variables added to `.env.example`.
- [ ] Flow diagrams in `docs/AI_Implemenation/01_SystemArchitecture/` updated if needed.

### 7.4 Security

- [ ] Confirmation token uses `secrets.token_hex(32)` (256-bit entropy).
- [ ] Only SHA256 hash of token stored in database.
- [ ] Token expiry enforced (15-minute default TTL).
- [ ] Page hash re-validated at confirmation time.
- [ ] Security event logged on token mismatch.

### 7.5 Operational Readiness

- [ ] Feature flag `AI_AUTHORING_ENABLED` gates all proposal endpoints.
- [ ] Metrics counters for proposal created/confirmed/expired events.
- [ ] Audit trail written for every successful deletion.
- [ ] Outbox event written for every successful deletion.

---

## 8. Tasks

### Task 1: Create ORM Model and Repository

**Files to create/modify:**
- `app/models/ai_proposal.py` (new)
- `app/models/__init__.py` (add import)
- `app/repositories/ai_proposal_repo.py` (new)

**Acceptance:**
- `AIProposalRecord` has all columns as specified in section 2.2.
- `to_dict()` serializes all fields with correct key naming.
- Repository can create, get, and update proposals.
- Repository can find pending proposals by session+page.

**Effort:** 2 hours  
**Dependencies:** US-AI-004 (table designs)

---

### Task 2: Create Pydantic DTOs

**File to create:**
- `app/routers/ai_proposals_dtos.py` (new)

**Acceptance:**
- `ProposeDeletePageRequest`, `ProposeDeletePageResponse`, `DependencyWarning`, `ConfirmDeletePageRequest`, `ConfirmDeletePageResponse` match the contracts in section 2.3-2.4.
- `DeletePageErrorResponse` matches the error envelope pattern in `app/utils/error_envelope.py`.

**Effort:** 30 minutes  
**Dependencies:** None

---

### Task 3: Implement Page Hash Computation

**File to modify:**
- `app/services/ai/proposal_orchestrator.py` — implement `_compute_page_hash`

**Acceptance:**
- Hash includes `page_id`, `title`, `order_index`, `updated_at`, and all component IDs/types/orders/updated_ats.
- Hash is deterministic: same page state always produces the same hash.
- Hash changes when title, components, or any component data changes.

**Effort:** 1 hour  
**Dependencies:** Task 1 (PageRecord access)

---

### Task 4: Implement Confirmation Token Generation and Validation

**File to modify:**
- `app/services/ai/proposal_orchestrator.py` — implement `_generate_confirmation_token` and token validation in `confirm_delete_page`

**Acceptance:**
- Tokens are 64 hex characters from `secrets.token_hex(32)`.
- SHA256 hash is stored; plaintext token is never persisted.
- Token validation compares SHA256(provided_token) against stored hash.
- Token expiry enforced: expired tokens return 410.

**Effort:** 1 hour  
**Dependencies:** None

---

### Task 5: Implement Dependency Analyzer

**File to create:**
- `app/services/ai/dependency_analyzer.py`

**Acceptance:**
- `check_branching_rules`: detects branch rules where page is `source_page_id`, `default_target_page_id`, or `targetPageId` in conditions.
- `check_final_assessment`: detects `final-assessment` component on the page.
- `check_navigation_impact`: detects if this is the only/first/last page.
- `check_scoring_references`: detects scoring config entries referencing component IDs on the page.
- `analyze_all` aggregates all checks.
- All warnings have correct `category`, `severity`, `message`, and `affected_ids`.

**Effort:** 3 hours  
**Dependencies:** US-AI-008 (validation pipeline), existing BranchRule and CourseScoringRecord models

---

### Task 6: Implement Proposal Orchestrator — propose_delete_page

**File to modify:**
- `app/services/ai/proposal_orchestrator.py` — implement `propose_delete_page`

**Acceptance:**
- Validates session is active (delegates to session service once available; accepts session_id for now).
- Fetches page and verifies it belongs to session's course.
- Checks for existing pending proposal; returns 409 if exists.
- Computes page hash via `_compute_page_hash`.
- Runs dependency analysis via `DependencyAnalyzer.analyze_all`.
- Generates confirmation token via `_generate_confirmation_token`.
- Persists `AIProposalRecord` with status `PENDING_CONFIRMATION`.
- Never mutates any domain data (safety invariant verified by tests).
- Returns proposal_id, page metadata, dependency warnings, confirmation metadata.

**Effort:** 4 hours  
**Dependencies:** Tasks 3, 4, 5

---

### Task 7: Implement Proposal Orchestrator — confirm_delete_page

**File to modify:**
- `app/services/ai/proposal_orchestrator.py` — implement `confirm_delete_page`

**Acceptance:**
- Looks up proposal by proposal_id and session_id.
- Validates proposal status is `PENDING_CONFIRMATION`.
- Validates `user_approved_delete == True`.
- Validates confirmation token (SHA256 hash match).
- Validates token not expired.
- Re-fetches page and validates page hash matches `base_hash`.
- Begins database transaction.
- Updates proposal status to `APPLYING`.
- Calls `PageRepository.delete(page)` — cascade deletes components.
- Reorders remaining pages in the course via `PageRepository.reorder`.
- Writes `ai_audit_logs` entry with before_snapshot.
- Writes `outbox_events` entry with event_type `PageDeletedByAI`.
- Updates proposal status to `APPLIED` with `applied_at`.
- Commits transaction.
- Returns `{status: "deleted", page_id, page_title, proposal_id}`.

**Effort:** 6 hours  
**Dependencies:** Tasks 1, 3, 4, 6 (propose_delete_page must exist first)

---

### Task 8: Create API Router and Wire Endpoints

**File to create/modify:**
- `app/routers/ai_proposals.py` (new)
- `app/main.py` (register router and ORM model import)

**Acceptance:**
- `POST /api/v1/ai/proposals/delete-page` calls `ProposalOrchestrator.propose_delete_page`.
- `POST /api/v1/ai/proposals/confirm-delete` calls `ProposalOrchestrator.confirm_delete_page`.
- Error responses match the error envelope pattern.
- AI feature flag gating is applied via middleware or dependency (US-AI-002).
- Router is registered in `api_router` under `/api/v1` prefix.
- ORM model is imported during startup so `create_all` creates the table.

**Effort:** 2 hours  
**Dependencies:** Tasks 6, 7

---

### Task 9: Create Alembic Migration

**File to create:**
- `alembic/versions/20260614_0001_add_ai_proposals_tables.py`

**Acceptance:**
- Creates `ai_proposals`, `ai_audit_logs`, `outbox_events` tables.
- All indexes as specified in section 2.1.
- Foreign keys with correct ON DELETE behavior.
- `downgrade()` drops all three tables.
- Migration runs cleanly against both SQLite (dev) and PostgreSQL (prod).

**Effort:** 1.5 hours  
**Dependencies:** Task 1 (table column definitions)

---

### Task 10: Write Unit Tests for Service Layer

**File to create:**
- `tests/test_ai_proposal_orchestrator.py`
- `tests/test_dependency_analyzer.py`
- `tests/test_page_hash.py`

**Acceptance:**
- All test scenarios from section 6.1 are covered.
- Safety invariant tests from section 6.4 pass.
- Concurrency tests from section 6.5 pass.
- All tests pass with in-memory SQLite test fixtures.
- Coverage >= 90% for `proposal_orchestrator.py` and `dependency_analyzer.py`.

**Effort:** 6 hours  
**Dependencies:** Tasks 3, 4, 5, 6, 7

---

### Task 11: Write Integration Tests for API Layer

**File to create:**
- `tests/test_ai_proposals_api.py`

**Acceptance:**
- All test scenarios from section 6.2 are covered.
- Tests use `TestClient` and existing `conftest.py` fixtures.
- Existing page CRUD tests in `test_page_components_api.py` still pass.
- Tests cover success, error, and feature-flag-disabled paths.

**Effort:** 3 hours  
**Dependencies:** Task 8

---

### Task 12: Add Environment Variables and Configuration

**File to modify:**
- `.env.example`
- `.env`
- `app/services/ai/proposal_orchestrator.py` (read config from env)

**Acceptance:**
- `AI_PROPOSAL_TTL_HOURS` defaults to 24.
- `AI_CONFIRMATION_TOKEN_TTL_MINUTES` defaults to 15.
- `AI_DELETE_CONFIRMATION_REQUIRED` defaults to true.
- Configuration is read at module level or injected.

**Effort:** 30 minutes  
**Dependencies:** Tasks 6, 7

---

### Task 13: Documentation and Review

**Files to modify:**
- `docs/AI_Implemenation/00_User_StoriesUseCases/USER_STORIES.md` (update status)
- `docs/API.md` or OpenAPI spec (add new endpoints)

**Acceptance:**
- API contracts are documented.
- Environment variables are documented.
- Story is marked complete in the canonical user stories list.

**Effort:** 1 hour  
**Dependencies:** Tasks 8, 10, 11, 12

---

### Task 14: Code Review and Merge

**Acceptance:**
- All CI checks pass.
- Two approvals on the PR.
- No regression in existing tests.
- Feature flag `AI_AUTHORING_ENABLED` defaults to `false` in production.

**Effort:** 2 hours  
**Dependencies:** All prior tasks

---

## Summary

| Metric | Value |
|---|---|
| New files | 8 |
| Modified files | 5 |
| New tables | 3 |
| New API endpoints | 2 |
| New services | 2 (ProposalOrchestrator, DependencyAnalyzer) |
| Total estimated effort | ~33 hours |
| Key safety invariant | `propose_delete_page` never mutates domain data |
| Key risk | Session validation (US-AI-006) is not yet complete; will require adaptation |
