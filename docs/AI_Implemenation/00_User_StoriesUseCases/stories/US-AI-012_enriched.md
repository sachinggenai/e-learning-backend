## US-AI-012: Propose and Apply AI Updates to Existing Pages

**Priority:** MUST
**Depends on:** US-AI-010 (Apply Safety, Audit, and Outbox)
**Unlocks:** US-AI-014 (Simple Chat Edit Orchestration)
**Source Flow:** 4. Update Page Proposal and Apply Flow
**Story Points:** 13

---

### 1. Current State Assessment

**As-Is Architecture (no AI mutation pathway exists today):**

The codebase at commit `751371b` provides full CRUD over courses/pages/components through direct REST endpoints in `app/routers/courses.py` and `app/routers/page_components.py`, backed by `CourseRepository` and `PageRepository`/`ComponentRepository` respectively.

- `PATCH /courses/{courseId}/pages/{pageId}` in `page_components.py` (line 184-204) accepts a `PageUpdateDTO` with fields `title`, `layout`, `theme`, `pageCompletion` and applies them immediately with no review, no diff, no rollback.
- `PATCH /courses/{courseId}/pages/{pageId}/components/{componentId}` in `page_components.py` (line 284-308) patches `data`, `audioConfig`, `completionCriteria`, and `styling` on a `ComponentRecord` directly.
- There is **no concept of proposals**, no review step, no before-snapshot, no confirmation token, no base-hash staleness check.
- The `courses.py` validation endpoint (`POST /courses/validate`, line 465-751) validates a full course payload but is not integrated into a proposal pipeline.
- No AI sessions, no tool-call adapters, no diff computation exist.
- `DELETE /courses/{courseId}/pages/{pageId}` has no confirmation gating — it deletes immediately.

**Relevant existing tables:**
- `courses` — `CourseRecord` in `app/models/persisted_course.py` (line 24-59)
- `pages` — `PageRecord` in `app/models/page_component.py` (line 20-74)
- `components` — `ComponentRecord` in `app/models/page_component.py` (line 77-128)
- `templates` — `TemplateRecord` in `app/models/persisted_course.py` (line 62-109)
- `template_definitions` — `TemplateDefinition` in `app/models/persisted_course.py` (line 112-145)
- `import_jobs` — `ImportJob` in `app/models/persisted_course.py` (line 148-183)

**No AI-specific tables exist yet** — those will be created by US-AI-004 (ai_sessions, ai_proposals, ai_confirmation_tokens, ai_audit_logs, outbox_events). US-AI-012 consumes the proposal and apply infrastructure from US-AI-009 and US-AI-010.

**Environment config** (`.env.example` line 1-70) has no AI-specific variables. Feature flags, model config, and rate-limit settings do not exist.

---

### 2. Functional Specification

#### 2.1 Overview

As an Author, I want the AI to propose targeted edits to an existing course page and apply them only after I approve a before/after diff. This ensures the AI cannot silently corrupt content and the author retains full control over every mutation.

The flow is:
1. Frontend calls `propose_update_page` AI tool with a session scope, a target `page_id`, and a patch payload.
2. Backend snapshots the current page, applies the patch in memory, validates the result, computes a diff, and stores a `PENDING_REVIEW` proposal.
3. Frontend renders the diff and validation messages for the author.
4. Author approves or rejects. On approval, the frontend calls `apply_update_proposal`.
5. Backend re-checks staleness (base hash), re-validates, applies the mutation transactionally, writes audit + outbox, and returns the updated page.

#### 2.2 `propose_update_page` Tool Contract

**Tool name:** `propose_update_page`

**Input schema (JSON):**
```json
{
  "session_id": "string (uuid, required)",
  "page_id": "string (uuid, required)",
  "base_hash": "string (SHA256 of current page state, required for staleness check)",
  "patch": {
    "title": "string | null (omit if unchanged)",
    "layout": "object | null (omit if unchanged)",
    "pageCompletion": "object | null (omit if unchanged)",
    "theme": "object | null (omit if unchanged)",
    "components": [
      {
        "operation": "string (update | add | delete | reorder)",
        "component_id": "string (uuid, required for update/delete)",
        "component_type": "string (required for add)",
        "data": "object",
        "order": "int (required for add/reorder)",
        "audioConfig": "object | null",
        "completionCriteria": "object | null",
        "styling": "object | null"
      }
    ] | null
  },
  "reason": "string (optional, author's rationale for the edit)"
}
```

**Allowed `patch` fields (any others rejected with 422):**
- `title` — max 200 chars
- `layout` — JSON object (`{preset, grid, placements}`)
- `theme` — JSON object (theme config overrides)
- `pageCompletion` — JSON object (`{criteria, behavior}`)
- `components` — array of component mutations

**Out-of-scope fields (rejected with a structured error):**
- `course_id` — immutable on the page
- `page_id` — cannot be changed
- `created_at`, `updated_at` — server-managed timestamps

**Component patch operations:**
| Operation | Description | Validation |
|---|---|---|
| `update` | Modifies `data`, `audioConfig`, `completionCriteria`, `styling` on an existing component | `component_id` must exist on the page; `component_type` is read-only |
| `add` | Adds a new component at the specified order | `component_type` must be in the supported whitelist; `data` validated against `ComponentType.schema` |
| `delete` | Removes a component | `component_id` must exist; page must retain at least one component unless explicitly allowed |
| `reorder` | Sets new order_index for existing components | All `component_id`s must belong to the page; must be a complete permutation |

**Validation performed during proposal:**
1. Session is valid, active, and scoped to the correct course.
2. Page belongs to session.course_id.
3. `base_hash` matches the computed SHA256 of the current page state (see Section 3.4 for hash algorithm).
4. Patch fields are in the allowed set. Reject `course_id`, `page_id`, `created_at`, `updated_at`.
5. Component operations are internally consistent (no duplicate component_id across operations, no add+update same id).
6. `component_type` (on add) is in the supported whitelist from US-AI-005 tool contract registry.
7. If `components` patch results in zero components, the proposal is allowed but flagged with a warning.
8. The resulting in-memory page passes the validation pipeline (US-AI-008).

**Success response:**
```json
{
  "proposal_id": "uuid",
  "proposal_status": "PENDING_REVIEW",
  "expires_at": "2026-06-15T12:00:00Z",
  "base_hash_used": "sha256hex",
  "diff": {
    "changed_fields": ["title", "components"],
    "before": { "title": "Old Title", "components": [/* brief summary */] },
    "after": { "title": "New Title", "components": [/* brief summary */] },
    "field_diffs": [
      {
        "field": "title",
        "before": "Old Title",
        "after": "New Title",
        "type": "modified"
      },
      {
        "field": "components[0].data.content",
        "before": "<p>old text</p>",
        "after": "<p>new text</p>",
        "component_id": "...",
        "type": "modified"
      }
    ]
  },
  "validation": {
    "valid": true,
    "errors": [],
    "warnings": ["Page has zero components after patch"],
    "timestamp": "2026-06-14T12:00:00Z"
  },
  "trace_id": "uuid"
}
```

**Error responses:**

| Condition | Status | Error code |
|---|---|---|
| Invalid/expired session | 401 | `SESSION_INVALID` |
| Page not found / not in session course | 404 | `PAGE_NOT_FOUND` |
| Stale base_hash | 409 | `STALE_BASE_HASH` |
| Unsupported component_type | 422 | `UNSUPPORTED_COMPONENT_TYPE` |
| Out-of-scope patch field | 422 | `FIELD_OUT_OF_SCOPE` |
| Component operation inconsistency | 422 | `INVALID_COMPONENT_OPERATION` |

#### 2.3 `apply_update_proposal` Tool Contract

**Tool name:** `apply_update_proposal`

**Input schema (JSON):**
```json
{
  "session_id": "string (uuid, required)",
  "proposal_id": "string (uuid, required)",
  "user_confirmed": true,
  "idempotency_key": "string (optional, UUID, for safe retry)"
}
```

**Pre-apply checks (in order, first failure returns immediately):**
1. Proposal exists and status is `PENDING_REVIEW`.
2. Proposal has not expired (`expires_at > now`).
3. Proposal `session_id` matches the calling session.
4. Session is active and scoped to the correct course.
5. Re-fetch page from DB, recompute `page_hash`, compare with `proposal.base_hash`. If mismatch -> 409 `STALE_BASE_HASH`.
6. Re-run validation pipeline on patched page. If blocking errors exist -> 422 with validation details.
7. If `idempotency_key` provided and already recorded -> return original success response without reapplying.

**Apply transaction (all-or-nothing):**
1. BEGIN transaction.
2. Update `proposal.status` from `PENDING_REVIEW` to `APPLYING`.
3. Apply patch to `PageRecord`:
   - If `patch.title` is set -> `page.title = patch.title`
   - If `patch.layout` is set -> `page.layout = patch.layout`
   - If `patch.theme` is set -> `page.theme_config = patch.theme`
   - If `patch.pageCompletion` is set -> `page.completion_config = patch.pageCompletion`
   - If `patch.components` is set -> process component mutations:
     - `update`: update the `ComponentRecord.data`, `audio_config`, `completion_criteria`, `styling`
     - `add`: create new `ComponentRecord(page_id, component_type, order_index, data, ...)`
     - `delete`: delete `ComponentRecord`
     - `reorder`: update `order_index` on affected components
4. Write `ai_audit_logs` record: `{session_id, proposal_id, operation: "PAGE_UPDATED_BY_AI", before_snapshot, after_candidate, user_id, model_metadata}`.
5. Write `outbox_events` record: `{event_type: "PageUpdatedByAI", aggregate_id: page.page_id, payload: {proposal_id, changed_fields, ...}}`.
6. Update `proposal.status` to `APPLIED` and set `applied_at`.
7. COMMIT.

**Success response:**
```json
{
  "proposal_id": "uuid",
  "status": "APPLIED",
  "page": {
    "pageId": "uuid",
    "title": "Updated Title",
    "order": 2,
    "layout": {...},
    "components": [...]
  },
  "changed_fields": ["title", "components"],
  "trace_id": "uuid"
}
```

**Error responses (pre-apply):**

| Condition | Status | Error code |
|---|---|---|
| Proposal not found | 404 | `PROPOSAL_NOT_FOUND` |
| Proposal not PENDING_REVIEW | 409 | `PROPOSAL_NOT_PENDING` |
| Proposal expired | 410 | `PROPOSAL_EXPIRED` |
| Stale base hash (concurrent edit) | 409 | `STALE_BASE_HASH` |
| Validation failure on recheck | 422 | `VALIDATION_FAILED` |
| user_confirmed is false | 400 | `CONFIRMATION_REQUIRED` |

#### 2.4 Page State Hash Algorithm

For staleness detection, compute a SHA256 hash of the deterministic page representation:

```
page_hash = SHA256(JSON.stringify({
  page_id: page.page_id,
  title: page.title,
  layout: page.layout,
  theme_config: page.theme_config,
  completion_config: page.completion_config,
  components: sorted(components.map(c => ({
    component_id: c.component_id,
    component_type: c.component_type,
    order_index: c.order_index,
    data: c.data,
    audio_config: c.audio_config,
    completion_criteria: c.completion_criteria,
    styling: c.styling
  })), by component_id)
}))
```

Keys are sorted, components are sorted by `component_id`, and the output is compact JSON (no whitespace). This ensures deterministic hashing regardless of DB column order.

#### 2.5 Frontend Integration Points

1. **Page fetch tool** (`fetch_page` from US-AI-007) returns `page_hash` in the response metadata.
2. **Proposal preview**: the frontend receives `diff` with `changed_fields`, `field_diffs` array. Each diff entry has `field`, `before`, `after`, `type` (`modified|added|removed`), and optional `component_id`.
3. **Staleness warning**: If the author has made manual changes between proposal creation and review, the frontend should show a "This page has changed since the proposal was created" banner and offer to re-fetch or discard.
4. **Apply UX**: The frontend calls `apply_update_proposal` with `user_confirmed=true`. The apply button is disabled when blocking validation errors exist.

---

### 3. Technical Specification

#### 3.1 New / Modified Files

**New files (under `app/services/ai/`):**
- `page_update_service.py` — Core orchestration: accept session/page/patch, snapshot, diff, create proposal
- `proposal_apply_service.py` — Apply logic with transactional safety (shared with US-AI-011, US-AI-013)
- `diff_computer.py` — Compute field-level diffs between two PageRecord snapshots
- `patch_applicator.py` — Apply a patch to a PageRecord in memory without committing
- `page_hash.py` — SHA256 computation helper for page staleness

**Modified files:**
- `app/repositories/ai_proposal_repo.py` — New repository for `ai_proposals` table (created by US-AI-004, extended here for update-specific queries)
- `app/services/ai/session_service.py` — Add session validation helper (created by US-AI-006, extended here)

**New API endpoints (under `/api/v1/ai/`):**
- None directly; the tool-call adapters are invoked via the chat orchestrator (US-AI-023). However, for testing and direct integration, we expose:
  - `POST /api/v1/ai/tools/propose-update-page` (internal, gated by feature flag)
  - `POST /api/v1/ai/tools/apply-update-proposal` (internal, gated by feature flag)

#### 3.2 Database DDL (New AI Tables, from US-AI-004)

These tables are created by US-AI-004 but referenced here. The migration scripts live in `alembic/versions/`. The full DDL is included here for clarity.

**`ai_sessions`** (created by US-AI-004):
```sql
CREATE TABLE ai_sessions (
    id              SERIAL PRIMARY KEY,
    session_id      UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    user_id         VARCHAR(100) NOT NULL,
    organization_id VARCHAR(100) NOT NULL,
    course_id       VARCHAR(64) NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    status          VARCHAR(32) NOT NULL DEFAULT 'active',  -- active | expired | closed
    expires_at      TIMESTAMPTZ NOT NULL,
    context_summary JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_ai_sessions_course ON ai_sessions(course_id);
CREATE INDEX idx_ai_sessions_user ON ai_sessions(user_id);
CREATE INDEX idx_ai_sessions_status ON ai_sessions(status);
```

**`ai_proposals`** (created by US-AI-004, extended by US-AI-012):
```sql
CREATE TABLE ai_proposals (
    id                  SERIAL PRIMARY KEY,
    proposal_id         UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    session_id          UUID NOT NULL REFERENCES ai_sessions(session_id) ON DELETE CASCADE,
    operation           VARCHAR(32) NOT NULL,  -- PAGE_CREATE | PAGE_UPDATE | PAGE_DELETE | BATCH
    status              VARCHAR(32) NOT NULL DEFAULT 'PENDING_REVIEW',
    -- PAGE_UPDATE specific columns
    course_id           VARCHAR(64) NOT NULL,
    page_id             VARCHAR(64) NOT NULL REFERENCES pages(page_id) ON DELETE CASCADE,
    base_hash           VARCHAR(64) NOT NULL,
    before_snapshot     JSONB NOT NULL,
    after_candidate     JSONB NOT NULL,
    patch               JSONB NOT NULL,        -- original patch for audit
    diff                JSONB NOT NULL,         -- computed diff for preview
    validation_result   JSONB,                  -- {valid, errors[], warnings[]}
    expires_at          TIMESTAMPTZ NOT NULL,
    applied_at          TIMESTAMPTZ,
    idempotency_key     UUID UNIQUE,
    provenance          JSONB,                  -- {prompt_version, model_id, provider, generated_at}
    trace_id            UUID NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_ai_proposals_session ON ai_proposals(session_id);
CREATE INDEX idx_ai_proposals_page ON ai_proposals(page_id);
CREATE INDEX idx_ai_proposals_status ON ai_proposals(status);
CREATE INDEX idx_ai_proposals_idempotency ON ai_proposals(idempotency_key);
```

**`ai_audit_logs`** (created by US-AI-004):
```sql
CREATE TABLE ai_audit_logs (
    id              SERIAL PRIMARY KEY,
    audit_id        UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES ai_sessions(session_id),
    proposal_id     UUID NOT NULL REFERENCES ai_proposals(proposal_id),
    operation       VARCHAR(64) NOT NULL,  -- PageUpdatedByAI | PageCreatedByAI | etc.
    aggregate_id    VARCHAR(64) NOT NULL,   -- course_id or page_id
    before_snapshot JSONB NOT NULL,
    after_snapshot  JSONB NOT NULL,
    user_id         VARCHAR(100) NOT NULL,
    organization_id VARCHAR(100),
    provenance      JSONB,
    trace_id        UUID NOT NULL,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_ai_audit_proposal ON ai_audit_logs(proposal_id);
CREATE INDEX idx_ai_audit_aggregate ON ai_audit_logs(aggregate_id);
CREATE INDEX idx_ai_audit_operation ON ai_audit_logs(operation);
```

**`outbox_events`** (created by US-AI-004):
```sql
CREATE TABLE outbox_events (
    id              SERIAL PRIMARY KEY,
    event_type      VARCHAR(64) NOT NULL,
    event_version   INT NOT NULL DEFAULT 1,
    aggregate_id    VARCHAR(64) NOT NULL,
    aggregate_type  VARCHAR(32) NOT NULL,  -- page | course
    payload         JSONB NOT NULL,
    trace_id        UUID NOT NULL,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at    TIMESTAMPTZ
);
CREATE INDEX idx_outbox_unpublished ON outbox_events(published_at) WHERE published_at IS NULL;
```

**Alembic migration revision sequence:**
- `xxxx_ai_sessions.py` (US-AI-004)
- `xxxx_ai_proposals.py` (US-AI-004, extended by US-AI-009)
- `xxxx_ai_update_specific_indices.py` (US-AI-012 adds page_id, base_hash indices)
- `xxxx_ai_audit_logs.py` (US-AI-004)
- `xxxx_outbox_events.py` (US-AI-004)

#### 3.3 Python Service Signatures

**`app/services/ai/page_update_service.py`:**

```python
from __future__ import annotations
from typing import Optional, List
from dataclasses import dataclass

@dataclass
class ComponentPatch:
    operation: str  # "update" | "add" | "delete" | "reorder"
    component_id: Optional[str] = None
    component_type: Optional[str] = None
    data: Optional[dict] = None
    order: Optional[int] = None
    audio_config: Optional[dict] = None
    completion_criteria: Optional[dict] = None
    styling: Optional[dict] = None

@dataclass
class PagePatch:
    title: Optional[str] = None
    layout: Optional[dict] = None
    theme: Optional[dict] = None
    page_completion: Optional[dict] = None
    components: Optional[List[ComponentPatch]] = None

@dataclass
class FieldDiff:
    field: str
    before: object
    after: object
    type: str  # "modified" | "added" | "removed"
    component_id: Optional[str] = None

@dataclass
class ProposalDiff:
    changed_fields: List[str]
    before: dict
    after: dict
    field_diffs: List[FieldDiff]

class PageUpdateService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def propose_update(
        self,
        session_id: str,
        page_id: str,
        base_hash: str,
        patch: PagePatch,
        reason: Optional[str] = None,
        provenance: Optional[dict] = None,
    ) -> ProposalResult:
        """
        1. Validate session (active, scoped to course owning page_id)
        2. Fetch page with components
        3. Compute current page_hash and compare to base_hash
        4. Validate patch fields (allowed set, no out-of-scope)
        5. Apply patch in memory via PatchApplicator
        6. Run validation pipeline on resulting page
        7. Compute diff between before/after
        8. Persist proposal with PENDING_REVIEW status
        9. Return proposal_id, diff, validation
        """
        ...

    async def apply_update(
        self,
        session_id: str,
        proposal_id: str,
        user_confirmed: bool,
        idempotency_key: Optional[str] = None,
    ) -> ApplyResult:
        """
        1. Load proposal, verify PENDING_REVIEW, not expired
        2. Verify session ownership
        3. Re-fetch page, recompute hash, compare to proposal.base_hash
        4. Re-run validation
        5. Begin transaction
        6. Update proposal status -> APPLYING
        7. Apply patch to actual DB records via repositories
        8. Write audit log
        9. Write outbox event
        10. Update proposal status -> APPLIED
        11. Commit
        12. Return updated page
        """
        ...
```

**`app/services/ai/diff_computer.py`:**

```python
from app.models.page_component import PageRecord

class DiffComputer:
    @staticmethod
    def compute_diff(before: PageRecord, after: PageRecord) -> ProposalDiff:
        """
        Compute field-level diff between two PageRecord instances.
        - Top-level fields (title, layout, theme, completion_config)
        - Component-level fields (data, audio_config, styling, completion_criteria)
        - Added/removed components
        - Reordered components
        Returns structured ProposalDiff with per-field before/after.
        """
        ...

    @staticmethod
    def compute_page_hash(page: PageRecord) -> str:
        """
        Deterministic SHA256 of page state per algorithm in Section 2.4.
        """
        ...
```

**`app/services/ai/patch_applicator.py`:**

```python
from app.models.page_component import PageRecord

class PatchApplicator:
    @staticmethod
    def apply_patch(page: PageRecord, patch: PagePatch) -> PageRecord:
        """
        Apply patch to a PageRecord in memory (deep copy input first).
        Returns a new PageRecord with modifications applied.
        Does NOT persist to database.
        Validates:
        - No out-of-scope fields
        - Component operations are consistent
        - component_type (add) is supported
        """
        ...

    @staticmethod
    def validate_patch_fields(patch: PagePatch) -> List[str]:
        """
        Returns list of out-of-scope fields present in the patch.
        Allowed: title, layout, theme, pageCompletion, components
        Rejected: page_id, course_id, created_at, updated_at, and any unknown keys.
        """
        ...
```

**`app/services/ai/proposal_apply_service.py`:**

```python
class ProposalApplyService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def apply(
        self,
        proposal: AiProposalRecord,
        user_confirmed: bool,
        idempotency_key: Optional[str] = None,
    ) -> PageRecord:
        """
        Shared apply logic used by US-AI-011 (create), US-AI-012 (update),
        and US-AI-013 (delete).
        Handles:
        - Idempotency check against ai_proposals.idempotency_key
        - Transactional boundary
        - Audit log write
        - Outbox event write
        - Proposal status transition
        """
        ...

    async def _apply_page_update(
        self, proposal: AiProposalRecord, page: PageRecord
    ) -> PageRecord:
        """
        Apply the stored patch to the actual DB PageRecord.
        Delegates to PageRepository.update, ComponentRepository.create/update/delete.
        """
        ...
```

**`app/repositories/ai_proposal_repo.py`:**

```python
class AiProposalRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, proposal: AiProposalRecord) -> AiProposalRecord: ...
    async def get(self, proposal_id: str) -> AiProposalRecord | None: ...
    async def get_by_idempotency(self, key: str) -> AiProposalRecord | None: ...
    async def update_status(self, proposal_id: str, status: str) -> AiProposalRecord: ...
    async def list_by_session(self, session_id: str) -> List[AiProposalRecord]: ...
    async def list_by_page(self, page_id: str) -> List[AiProposalRecord]: ...
```

#### 3.4 Environment Variables (New, appended to `.env.example`)

```ini
# ============================================
# AI Authoring Configuration
# ============================================

# Master feature flag
AI_AUTHORING_ENABLED=true

# Proposal TTL in seconds (default 24 hours)
AI_PROPOSAL_TTL_SECONDS=86400

# Session TTL in seconds (default 8 hours)
AI_SESSION_TTL_SECONDS=28800

# Max tool-call round trips per chat turn
AI_MAX_TOOL_ROUNDTRIPS=10

# Allowed component types for AI generation (comma-separated)
AI_ALLOWED_COMPONENT_TYPES=content-text,content-video,mcq,tabs,accordion,summary,welcome

# LLM provider configuration
AI_PRIMARY_MODEL=claude-sonnet-4-20250514
AI_FALLBACK_MODEL=claude-haiku-3-20250313
AI_MODEL_PROVIDER=anthropic
AI_MODEL_TIMEOUT_SECONDS=60
AI_MODEL_MAX_RETRIES=3

# Feature sub-flags (all default to enabled when AI_AUTHORING_ENABLED=true)
AI_FEATURE_PAGE_UPDATE=true
AI_FEATURE_PAGE_CREATE=true
AI_FEATURE_PAGE_DELETE=true
AI_FEATURE_CHAT_EDIT=true

# Rate limiting
AI_RATE_LIMIT_REQUESTS_PER_MINUTE=30
AI_RATE_LIMIT_TOKENS_PER_DAY=1000000
```

**Add** `AI_AUTHORING_ENABLED`, `AI_PROPOSAL_TTL_SECONDS`, `AI_FEATURE_PAGE_UPDATE` to `app/db/config.py` or a new `app/services/ai/config.py`:

```python
# app/services/ai/config.py
from __future__ import annotations
import os

class AiConfig:
    authoring_enabled: bool = os.getenv("AI_AUTHORING_ENABLED", "true").lower() == "true"
    proposal_ttl_seconds: int = int(os.getenv("AI_PROPOSAL_TTL_SECONDS", "86400"))
    session_ttl_seconds: int = int(os.getenv("AI_SESSION_TTL_SECONDS", "28800"))
    allowed_component_types: list[str] = os.getenv(
        "AI_ALLOWED_COMPONENT_TYPES",
        "content-text,content-video,mcq,tabs,accordion,summary,welcome"
    ).split(",")
    feature_page_update: bool = os.getenv("AI_FEATURE_PAGE_UPDATE", "true").lower() == "true"
    max_tool_roundtrips: int = int(os.getenv("AI_MAX_TOOL_ROUNDTRIPS", "10"))
```

#### 3.5 Alembic Migration (`alembic/versions/xxxx_ai_proposals.py`)

```python
"""Add ai_proposals table

Revision ID: xxxx
Revises: <previous_migration_id>
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "xxxx"
down_revision = "<previous>"  # Must point to US-AI-004 migration

def upgrade():
    op.create_table(
        "ai_proposals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), unique=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING_REVIEW"),
        sa.Column("course_id", sa.String(64), nullable=False),
        sa.Column("page_id", sa.String(64), sa.ForeignKey("pages.page_id", ondelete="CASCADE"), nullable=False),
        sa.Column("base_hash", sa.String(64), nullable=False),
        sa.Column("before_snapshot", postgresql.JSONB, nullable=False),
        sa.Column("after_candidate", postgresql.JSONB, nullable=False),
        sa.Column("patch", postgresql.JSONB, nullable=False),
        sa.Column("diff", postgresql.JSONB, nullable=False),
        sa.Column("validation_result", postgresql.JSONB, nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provenance", postgresql.JSONB, nullable=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_ai_proposals_session", "ai_proposals", ["session_id"])
    op.create_index("idx_ai_proposals_page", "ai_proposals", ["page_id"])
    op.create_index("idx_ai_proposals_status", "ai_proposals", ["status"])
    op.create_index("idx_ai_proposals_idempotency", "ai_proposals", ["idempotency_key"], unique=True)

def downgrade():
    op.drop_table("ai_proposals")
```

#### 3.6 OpenAPI Schema Extension

Add these schemas to the FastAPI app by extending the `custom_openapi()` function in `app/main.py` (around line 187):

```python
from app.services.ai.proposal_schemas import (
    ProposeUpdatePageRequest,
    ProposeUpdatePageResponse,
    ApplyUpdateProposalRequest,
    ApplyUpdateProposalResponse,
    ProposalDiffSchema,
    FieldDiffSchema,
)
```

New file `app/services/ai/proposal_schemas.py`:

```python
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class ComponentPatchSchema(BaseModel):
    operation: str = Field(..., pattern=r"^(update|add|delete|reorder)$")
    component_id: Optional[str] = None
    component_type: Optional[str] = None
    data: Optional[dict] = None
    order: Optional[int] = None
    audioConfig: Optional[dict] = None
    completionCriteria: Optional[dict] = None
    styling: Optional[dict] = None

class PagePatchSchema(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    layout: Optional[dict] = None
    theme: Optional[dict] = None
    pageCompletion: Optional[dict] = None
    components: Optional[List[ComponentPatchSchema]] = None

class ProposeUpdatePageRequest(BaseModel):
    session_id: str
    page_id: str
    base_hash: str = Field(..., min_length=64, max_length=64)
    patch: PagePatchSchema
    reason: Optional[str] = Field(None, max_length=500)

class FieldDiffSchema(BaseModel):
    field: str
    before: object
    after: object
    type: str = Field(..., pattern=r"^(modified|added|removed)$")
    component_id: Optional[str] = None

class ProposalDiffSchema(BaseModel):
    changed_fields: List[str]
    before: dict
    after: dict
    field_diffs: List[FieldDiffSchema]

class ProposeUpdatePageResponse(BaseModel):
    proposal_id: str
    proposal_status: str  # PENDING_REVIEW
    expires_at: datetime
    base_hash_used: str
    diff: ProposalDiffSchema
    validation: dict
    trace_id: str

class ApplyUpdateProposalRequest(BaseModel):
    session_id: str
    proposal_id: str
    user_confirmed: bool
    idempotency_key: Optional[str] = None

class ApplyUpdateProposalResponse(BaseModel):
    proposal_id: str
    status: str  # APPLIED
    page: dict
    changed_fields: List[str]
    trace_id: str
```

---

### 4. Definition of Done

#### 4.1 Acceptance Criteria

1. **Proposal creation**: Calling `propose_update_page` with a valid session, page, and patch creates a `PENDING_REVIEW` proposal. No database mutation occurs on `PageRecord` or `ComponentRecord`.

2. **Staleness detection**: If the page has been modified between `fetch_page` and `propose_update_page`, a 409 `STALE_BASE_HASH` is returned with the current `page_hash` so the frontend can re-fetch.

3. **Field gating**: Patch containing `course_id`, `page_id`, `created_at`, or `updated_at` is rejected with 422 `FIELD_OUT_OF_SCOPE` and a descriptive message identifying the offending field.

4. **Component operation consistency**:
   - `update` on a non-existent `component_id` returns 422.
   - `delete` on a non-existent `component_id` returns 422.
   - `add` with an unsupported `component_type` returns 422.
   - `reorder` with a `component_id` not on the page returns 422.
   - Duplicate `component_id` across patch operations returns 422.

5. **Diff computation**: The returned diff correctly identifies changed fields, added/removed components, and nested data changes. Before/after values are exact snapshots from proposal creation time.

6. **Validation integration**: The proposal validates the in-memory patched page through the US-AI-008 validation pipeline. Blocking errors are returned in the proposal preview; apply is blocked if blocking errors remain unresolved.

7. **Apply idempotency**: Calling `apply_update_proposal` twice with the same `idempotency_key` returns the original success response without re-applying. Without an idempotency key, the second call returns 409 `PROPOSAL_NOT_PENDING`.

8. **Apply atomicity**: If the apply transaction fails at any point (DB error, post-apply validation failure), the entire transaction rolls back. No partial update is observable.

9. **Audit trail**: Every successful apply writes an `ai_audit_logs` record with `operation = "PageUpdatedByAI"`, `before_snapshot` (pre-update page), `after_snapshot` (post-update page), `provenance`, `session_id`, `proposal_id`, `user_id`, and `trace_id`.

10. **Outbox event**: Every successful apply writes an `outbox_events` record with `event_type = "PageUpdatedByAI"`, `event_version = 1`, `aggregate_id = page.page_id`, `aggregate_type = "page"`, payload containing `{changed_fields, proposal_id, session_id}`.

11. **Expiry**: Proposals older than `AI_PROPOSAL_TTL_SECONDS` (default 24h) return 410 `PROPOSAL_EXPIRED` on apply attempt.

12. **Feature flag gate**: When `AI_FEATURE_PAGE_UPDATE=false` or `AI_AUTHORING_ENABLED=false`, both endpoints return 503 with `"AI feature disabled"`.

13. **Non-deletion guarantee**: `propose_update_page` never deletes a page or calls `PageRepository.delete`. Only the patch's component delete operations may remove components.

#### 4.2 Rollout Criteria

- Unit tests for all new services pass (coverage > 90% on new code).
- Integration tests passing with in-memory SQLite.
- Migration up/down tested against a PostgreSQL instance.
- Manual smoke test: create a course, add a page, propose an update, verify diff, apply, verify audit/outbox rows, verify page is updated in GET response.
- Feature flag toggled off restores pre-AI behavior.

---

### 5. Non-Functional Requirements

| Category | Requirement | Target |
|---|---|---|
| **Performance** | Proposal creation latency (excluding LLM time) | < 500ms p95 |
| **Performance** | Apply latency | < 200ms p95 |
| **Performance** | Diff computation for a page with 20 components | < 100ms |
| **Scalability** | Concurrent proposals on the same page | First-commit-wins via base_hash; 409 for losers |
| **Scalability** | Max proposals per session | 100 (enforced at proposal creation) |
| **Scalability** | Max patch.component operations per proposal | 50 |
| **Security** | Session authentication | Proposal apply verifies session ownership of the course |
| **Security** | Input validation | All patch fields validated at Pydantic boundary before service layer |
| **Security** | SQL injection | Parameterized queries via SQLAlchemy ORM (existing pattern) |
| **Reliability** | Apply transactionality | All-or-nothing via single DB transaction |
| **Reliability** | Idempotency | Idempotency keys prevent duplicate applies for 24 hours |
| **Observability** | Trace IDs | Every proposal and apply has a trace_id logged across all services |
| **Observability** | Audit completeness | Every apply has before_snapshot and after_snapshot in audit |
| **Resilience** | Empty patch | If patch evaluates to no changes (title same, no component changes), proposal is created with a warning but apply is a no-op on data |

---

### 6. Expansion Points

1. **Partial apply**: Allow applying individual fields of a multi-field proposal (e.g., apply title change but skip component changes). Requires splitting the proposal or adding selective-apply semantics. (COULD, post-MVP)

2. **RLHF feedback integration**: Capture whether the author accepted, modified, or rejected the proposal as implicit feedback for model improvement. See US-AI-031.

3. **Auto-apply for low-risk changes**: Allow the policy engine (US-AI-032) to auto-apply simple content-only patches for trusted roles without manual confirmation.

4. **Multi-page batch update**: Extend the update proposal to accept an array of `{page_id, patch}` for batch updates with all-or-nothing semantics. See US-AI-029.

5. **Preview generation**: Generate an HTML preview of the patched page asynchronously so the author can see the rendered result before approving. See US-AI-041.

6. **Concurrent edit takeover**: If a page is locked by another AI session or manual editor, allow requesting a "force takeover" that creates the proposal but marks it with a concurrency warning. See GAP-1 in the research audit.

7. **Rollback**: Store the `before_snapshot` in a way that enables automatic rollback proposal generation. See US-AI-040.

8. **Versioned page history**: Store all applied updates as versioned snapshots for point-in-time recovery. (COULD, post-MVP)

---

### 7. Validation Strategy (Test Scenarios)

#### 7.1 Unit Tests

**`test_page_hash.py`:**
- `test_deterministic_hash`: Same page data always produces the same hash.
- `test_hash_changes_on_title`: Hash differs when title changes.
- `test_hash_changes_on_component_data`: Hash differs when component data changes.
- `test_hash_order_independent`: Components reordered without data changes produce different hash (since order_index is included).

**`test_patch_applicator.py`:**
- `test_apply_title_patch`: Page title is updated in memory.
- `test_apply_component_update`: Existing component's data is updated.
- `test_apply_component_add`: New component is added at the specified order.
- `test_apply_component_delete`: Component is removed from the in-memory list.
- `test_apply_component_reorder`: Component order indices are updated.
- `test_reject_out_of_scope_field`: `course_id` in patch raises ValueError.
- `test_reject_invalid_operation`: Unknown operation string raises ValueError.
- `test_reject_duplicate_component_id`: Same component_id in update and add raises ValueError.
- `test_empty_patch_is_noop`: Patch with no fields returns identical page.

**`test_diff_computer.py`:**
- `test_identical_pages`: Empty diff with no changed_fields.
- `test_title_change`: Diff contains a modified entry for title.
- `test_component_data_change`: Diff contains a modified entry for components[0].data.content.
- `test_component_added`: Diff contains an added entry with component_id.
- `test_component_deleted`: Diff contains a removed entry with component_id.
- `test_multiple_changes`: Diff lists all changed fields in changed_fields array.

**`test_page_update_service.py`:**
- `test_propose_update_success`: Valid input creates a PENDING_REVIEW proposal with correct diff.
- `test_propose_update_stale_hash`: Returns 409 when base_hash does not match.
- `test_propose_update_page_not_in_session_course`: Returns 404.
- `test_propose_update_invalid_session`: Returns 401.
- `test_apply_update_success`: Apply updates the page in DB and writes audit/outbox.
- `test_apply_update_expired_proposal`: Returns 410.
- `test_apply_update_already_applied`: Returns 409.
- `test_apply_update_idempotency`: Same idempotency_key returns cached success.
- `test_apply_update_concurrent_edit`: Returns 409 when page changed after proposal.
- `test_apply_update_no_confirmation`: Returns 400 when user_confirmed=false.
- `test_feature_flag_disabled`: Returns 503 when AI_FEATURE_PAGE_UPDATE=false.

#### 7.2 Integration Tests

Using the `test_client` fixture from `tests/conftest.py`:

```python
# test_ai_page_update.py (new file in tests/)

async def test_propose_and_apply_update_flow(test_client, sample_session, sample_page):
    """Full happy path: propose -> preview -> apply -> verify."""
    # 1. Fetch page to get base_hash
    fetch_resp = await test_client.get(
        f"/api/v1/courses/{sample_course_id}/pages/{sample_page.page_id}"
    )
    page = fetch_resp.json()
    base_hash = compute_page_hash_from_dict(page)

    # 2. Propose update
    propose_resp = await test_client.post(
        "/api/v1/ai/tools/propose-update-page",
        json={
            "session_id": sample_session.session_id,
            "page_id": page["pageId"],
            "base_hash": base_hash,
            "patch": {"title": "Updated Title"},
        },
    )
    assert propose_resp.status_code == 200
    proposal = propose_resp.json()
    assert proposal["proposal_status"] == "PENDING_REVIEW"
    assert "title" in proposal["diff"]["changed_fields"]

    # 3. Apply
    apply_resp = await test_client.post(
        "/api/v1/ai/tools/apply-update-proposal",
        json={
            "session_id": sample_session.session_id,
            "proposal_id": proposal["proposal_id"],
            "user_confirmed": True,
        },
    )
    assert apply_resp.status_code == 200
    result = apply_resp.json()
    assert result["status"] == "APPLIED"
    assert result["page"]["title"] == "Updated Title"

    # 4. Verify via existing GET endpoint
    get_resp = await test_client.get(
        f"/api/v1/courses/{sample_course_id}/pages/{sample_page.page_id}"
    )
    assert get_resp.json()["title"] == "Updated Title"

    # 5. Verify audit exists
    audit_resp = await test_client.get(f"/api/v1/ai/audit?proposal_id={proposal['proposal_id']}")
    assert audit_resp.status_code == 200
    assert audit_resp.json()["operation"] == "PageUpdatedByAI"

async def test_stale_hash_rejected(test_client, sample_session, sample_page):
    """Proposal with stale base_hash returns 409."""
    # Fetch page
    fetch_resp = await test_client.get(...)
    page = fetch_resp.json()
    base_hash = compute_page_hash_from_dict(page)

    # Someone else edits the page
    await test_client.patch(
        f"/api/v1/courses/{sample_course_id}/pages/{page['pageId']}",
        json={"title": "Interrupted Edit"},
    )

    # Propose with stale hash
    propose_resp = await test_client.post(
        "/api/v1/ai/tools/propose-update-page",
        json={
            "session_id": sample_session.session_id,
            "page_id": page["pageId"],
            "base_hash": base_hash,  # now stale
            "patch": {"title": "AI Update"},
        },
    )
    assert propose_resp.status_code == 409
    assert propose_resp.json()["code"] == "STALE_BASE_HASH"
    assert "current_hash" in propose_resp.json()

async def test_out_of_scope_field_rejected(test_client, sample_session, sample_page):
    """Patch with out-of-scope field returns 422."""
    propose_resp = await test_client.post(
        "/api/v1/ai/tools/propose-update-page",
        json={
            "session_id": sample_session.session_id,
            "page_id": sample_page.page_id,
            "base_hash": "a" * 64,
            "patch": {"course_id": "different-course"},
        },
    )
    assert propose_resp.status_code == 422
    assert propose_resp.json()["code"] == "FIELD_OUT_OF_SCOPE"

async def test_idempotent_apply(test_client, sample_session, sample_page):
    """Same idempotency_key returns cached result."""
    # Propose
    propose_resp = await test_client.post(...)
    proposal_id = propose_resp.json()["proposal_id"]

    # First apply
    first = await test_client.post(
        "/api/v1/ai/tools/apply-update-proposal",
        json={
            "session_id": sample_session.session_id,
            "proposal_id": proposal_id,
            "user_confirmed": True,
            "idempotency_key": "11111111-1111-1111-1111-111111111111",
        },
    )
    assert first.status_code == 200

    # Second apply with same key
    second = await test_client.post(
        "/api/v1/ai/tools/apply-update-proposal",
        json={
            "session_id": sample_session.session_id,
            "proposal_id": proposal_id,
            "user_confirmed": True,
            "idempotency_key": "11111111-1111-1111-1111-111111111111",
        },
    )
    assert second.status_code == 200
    assert second.json() == first.json()
```

#### 7.3 E2E Test

Full end-to-end test in `tests/test_ai_e2e.py` (shared with other AI stories):

- Create course with 3 pages.
- Create AI session for the course.
- List pages (US-AI-007 tool), pick one.
- Fetch page to get base_hash.
- Propose update: change title AND update a component AND add a new component.
- Verify proposal preview shows all three changes in the diff.
- Apply with confirmation.
- Verify via GET /courses/{id}/pages/{id} that all three changes are persisted.
- Verify audit log has one `PageUpdatedByAI` entry with before/after snapshots.
- Verify outbox has one `PageUpdatedByAI` event.
- Verify subsequent propose-update on same page works (fresh hash).

---

### 8. Task Breakdown

#### Chunk 0: Foundation Tasks (Days 1-2)

| Task ID | Description | Owner | Dependencies | Effort |
|---|---|---|---|---|
| US-AI-012-T01 | Create `app/services/ai/page_hash.py` with `compute_page_hash(page: PageRecord) -> str` and `compute_page_hash_from_dict(page: dict) -> str`. Write unit tests. | Backend | None | 3h |
| US-AI-012-T02 | Create `app/services/ai/diff_computer.py` with `DiffComputer.compute_diff(before, after)` and `DiffComputer.compute_page_hash()`. Write unit tests. | Backend | T01 | 4h |
| US-AI-012-T03 | Create `app/services/ai/patch_applicator.py` with `PatchApplicator.apply_patch(page, patch)` and `validate_patch_fields(patch)`. Write unit tests for all component operations. | Backend | None | 5h |
| US-AI-012-T04 | Create `app/services/ai/proposal_schemas.py` with all Pydantic request/response schemas. | Backend | None | 2h |

#### Chunk 1: Core Service Logic (Days 3-5)

| Task ID | Description | Owner | Dependencies | Effort |
|---|---|---|---|---|
| US-AI-012-T05 | Create `app/services/ai/page_update_service.py` with `PageUpdateService.propose_update()` method: session validation, hash check, patch apply in memory, validation pipeline call, diff compute, proposal persistence. Write integration tests. | Backend | T02, T03, T04, US-AI-006 (session validation), US-AI-008 (validation pipeline) | 8h |
| US-AI-012-T06 | Create `app/services/ai/proposal_apply_service.py` with `ProposalApplyService.apply()`: idempotency check, re-validation, transactional apply across PageRepository + ComponentRepository, audit write, outbox write. Write integration tests. | Backend | T05, US-AI-010 (audit/outbox contracts) | 8h |
| US-AI-012-T07 | Create `app/repositories/ai_proposal_repo.py` with CRUD operations for `ai_proposals` table. | Backend | US-AI-004 (ai_proposals model) | 3h |

#### Chunk 2: API Layer + Feature Flags (Days 5-6)

| Task ID | Description | Owner | Dependencies | Effort |
|---|---|---|---|---|
| US-AI-012-T08 | Create tool-call adapter functions in `app/services/ai/tool_adapters.py`: `handle_propose_update_page(params)` and `handle_apply_update_proposal(params)`. These validate input, call the service, and format the response. | Backend | T05, T06, US-AI-005 (tool contract registry) | 4h |
| US-AI-012-T09 | Register `propose_update_page` and `apply_update_proposal` in the AI tool registry (from US-AI-005). Wire up feature flag checks. | Backend | T08, US-AI-005 | 2h |
| US-AI-012-T10 | Create `app/services/ai/config.py` for AI configuration. Add `AI_FEATURE_PAGE_UPDATE` and related env vars to `.env.example`. Update app startup to validate config. | Backend | None | 2h |

#### Chunk 3: Alembic Migration (Day 6)

| Task ID | Description | Owner | Dependencies | Effort |
|---|---|---|---|---|
| US-AI-012-T11 | Create Alembic migration for US-AI-004 / US-AI-009 foundational tables (`ai_sessions`, `ai_proposals`, `ai_audit_logs`, `outbox_events`) — shared migration that US-AI-012 builds on. | Backend | US-AI-004 | 3h |
| US-AI-012-T12 | Add indices migration specifically for US-AI-012 query patterns (page_id lookups, idempotency key lookups, status-based queries). | Backend | T11 | 1h |
| US-AI-012-T13 | Verify migration up/down against PostgreSQL. Update `alembic/env.py` if needed to include new models. | Backend | T12 | 2h |

#### Chunk 4: Testing (Days 7-8)

| Task ID | Description | Owner | Dependencies | Effort |
|---|---|---|---|---|
| US-AI-012-T14 | Write unit test suite for `patch_applicator.py` (all operations, edge cases). | Backend | T03 | 3h |
| US-AI-012-T15 | Write unit test suite for `diff_computer.py` (all diff scenarios). | Backend | T02 | 2h |
| US-AI-012-T16 | Write unit test suite for `page_hash.py` (determinism, sensitivity). | Backend | T01 | 1h |
| US-AI-012-T17 | Write integration tests for propose+apply happy path, stale hash, out-of-scope fields, idempotency, expiry, concurrent edit detection. | Backend | T05, T06 | 6h |
| US-AI-012-T18 | Write E2E test: create course -> session -> propose update -> preview -> apply -> verify persistence + audit + outbox. | Backend | T17 | 3h |
| US-AI-012-T19 | Add test for feature-flag-disabled path (503 response). | Backend | T10, T09 | 1h |

#### Chunk 5: Documentation and Sign-Off (Day 8)

| Task ID | Description | Owner | Dependencies | Effort |
|---|---|---|---|---|
| US-AI-012-T20 | Update `TOOL_SCHEMAS_CLAUDE_NATIVE.md` with `propose_update_page` and `apply_update_proposal` tool definitions. | Tech Writer | T08 | 2h |
| US-AI-012-T21 | Update `BACKEND_IMPLEMENTATION_SUMMARY.md` with update proposal flow overview. | Tech Writer | T05, T06 | 1h |
| US-AI-012-T22 | Populate `docs/AI_Implemenation/02DetailedDesign/US-AI-012.md` with the design document. | Architect | All | 2h |
| US-AI-012-T23 | Sign-off: verify all acceptance criteria against integration test results. | PO/QA | T17, T18, T19 | 2h |

**Total estimated effort: 13 story points** (1 SP = 4-6 hours of dev work, roughly 70-78 hours total across all tasks).

---
The complete epic has been written and saved to:

`/c/Users/ADMIN/e-learning-backend/docs/AI_Implemenation/00_User_StoriesUseCases/US-AI-013_DELETE_PAGE_EPIC.md`

**Here is a summary of what the epic covers across all 8 sections:**

**1. Functional Specification** — Describes the full two-phase gate (Phase 0-4), including chat-driven delete flow (intent resolution, proposal, frontend confirmation modal, transactional apply, audit), direct-UI delete exemption, and all error conditions with HTTP status codes and error codes (SESSION_EXPIRED, PAGE_NOT_FOUND, DUPLICATE_PROPOSAL, CONFIRMATION_EXPIRED, INVALID_CONFIRMATION_TOKEN, PAGE_CHANGED, PAGE_ALREADY_DELETED, PROPOSAL_ALREADY_APPLIED).

**2. Technical Specification** — Includes:
- DDL for 3 new tables: `ai_proposals` (with confirmation_token_sha256, base_hash, before_snapshot via JSONB, TTL), `ai_audit_logs`, `outbox_events` — all with proper foreign keys, constraints, and indexes.
- Full SQLAlchemy ORM model (`AIProposalRecord`) in `app/models/ai_proposal.py`.
- 5 Pydantic DTOs: `ProposeDeletePageRequest/Response`, `ConfirmDeletePageRequest/Response`, `DependencyWarning`.
- Exact API contracts (request/response shapes, all error payloads) for `POST /api/v1/ai/proposals/delete-page` and `POST /api/v1/ai/proposals/confirm-delete`.
- Service class signatures for `ProposalOrchestrator` (with `_compute_page_hash` using SHA-256 over page fields + component fields, `_generate_confirmation_token` using `secrets.token_hex(32)`) and `DependencyAnalyzer` (checks branching rules, final assessment components, navigation impact, scoring references).
- API router skeleton, AIProposalRepository, Alembic migration, main.py registration points, and env vars.

**3. NFRs** — Performance targets (< 500 ms proposal, < 1 s confirm, < 200 ms dependency analysis at p95), security (256-bit tokens, SHA256-only storage, 15-min expiry, tamper detection), data integrity (transactional all-or-nothing, cascade delete, idempotency, hash re-validation), availability (outbox failure does not roll back delete), and observability (trace IDs, metric counters for proposal/confirm/expire).

**4. Current State** — References the existing `DELETE /api/v1/courses/{courseId}/pages/{pageId}` at `page_components.py:207`, `PageRepository.delete()` at `page_component_repo.py:62`, `PageRecord` and `ComponentRecord` models, `BranchRule` in `branching.py`, `CourseScoringRecord` in `scoring.py`, existing error envelope utilities, the Mermaid flow diagrams, and the high-level story definition in USER_STORIES.md.

**5. Expansion Points** — Soft-delete retention, batch delete proposals, automatic reorder optimization, UI-initiated delete proposals, policy engine integration (US-AI-032), and preview-before-delete (US-AI-041).

**6. Validation** — 35+ test scenarios organized into: service-layer unit tests (ProposeDeletePage class: 11 tests, ConfirmDeletePage: 12 tests, DependencyAnalyzer: 8 tests, PageHash: 5 tests), API integration tests (7 tests), E2E scenarios (5 scenarios), safety invariant tests (4 tests), and concurrency tests (2 tests).

**7. Definition of Done** — Checklist covering code complete (8 files), tests passing, documentation, security review, and operational readiness.

**8. Tasks** — 14 engineering tasks with per-task: files to create/modify, acceptance criteria, effort estimates (total ~33 hours), and dependency graph. Tasks range from ORM model/repository (2 hrs) through orchestrator implementation (6 hrs for confirm_delete) to code review and merge (2 hrs).

---