# US-AI-050 -- Stale Detection and Merge Resolution for Concurrent AI Edits

**Priority:** SHOULD
**Depends on:** US-AI-010 (Apply Safety, Audit, and Outbox), US-AI-043 (Concurrency Control and Page Locking)
**Status:** Draft
**Target Release:** Phase 3
**Last Updated:** 2026-06-14

---

## 1. FUNCTIONAL SPECIFICATION

### User Story

As an Author using the AI authoring assistant, I want the system to detect when my AI agent is working from stale (outdated) page content and automatically merge my proposed changes with any intervening edits, so that I do not lose my work when another session has modified the page between my fetch and my proposal, and so that I receive clear, structured conflict information when automatic resolution is not possible.

As an Admin, I want configurable merge strategies (auto-merge, abort-on-conflict, or human-review-all) and full audit trails of merge operations, so that I can control the safety/collaboration trade-off for my organization and investigate any data integrity issues.

### Functional Requirements

**FR-001 -- Version Hash Tracking on All Read Operations:** Every page fetch endpoint (`fetch_page`, `list_pages`, `fetch_course_structure`) MUST return a `version_hash` field. This hash is a SHA-256 digest of the page's current `ComponentRecord` and `PageRecord` serialization. The hash is stable and deterministic: identical content always produces an identical hash. The hash is returned in every read response and is required as input in every write-proposal endpoint. The existing `base_version_hash` column on `ai_proposals` (defined in US-AI-043) is the persistence target for this field.

**FR-002 -- Staleness Check at Proposal Creation Time:** When `propose_create_page`, `propose_update_page`, or `propose_delete_page` is invoked, the system MUST compare the caller-supplied `version_hash` against the current computed hash of the target page. If they do not match, the system MUST classify the staleness severity into one of three levels: (a) STALE_NO_CHANGE -- the page metadata (order_index, layout) changed but the content the AI touched is identical; (b) STALE_COMPATIBLE -- the page content changed in non-overlapping fields or components; (c) STALE_CONFLICT -- the page content changed in the same fields or components that the AI proposal targets.

**FR-003 -- Three-Way Auto-Merge on Stale with Non-Conflicting Changes:** When the system detects STALE_NO_CHANGE or STALE_COMPATIBLE staleness, it MUST automatically compute a three-way merge of the page content. The merge uses: (a) BASE = the page state at the time the AI's `version_hash` was current; (b) LOCAL = the current page state at proposal time; (c) REMOTE = the AI's proposed changes. The merge operation applies non-overlapping LOCAL changes to the AI's proposal, producing a new merged proposal. The merge result is transparent to the AI agent: the proposal is created with the merged content, and the response includes a `stale_info` block documenting what changed and that a merge occurred. The `base_version_hash` on the proposal is updated to the hash of the merged page state.

**FR-004 -- Structured Conflict Report on Conflicting Changes:** When the system detects STALE_CONFLICT staleness (the AI proposed changes to the same field or component that was independently modified between BASE and LOCAL), the system MUST NOT auto-merge. Instead, it MUST produce a structured conflict report containing: (a) for each conflicting field, the BASE value, the LOCAL value (current on server), and the REMOTE value (AI's proposal); (b) the conflict locations identified by JSON Pointer (RFC 6901) paths; (c) a `conflict_type` classification (field_level, component_added_removed, schema_mismatch). The proposal MUST NOT be created. The error response MUST include the full conflict report and MUST offer the AI agent a choice to re-fetch the page and retry, or to proceed with a FORCE_OVERWRITE option (if the user confirms they want to replace the current content).

**FR-005 -- Staleness Check at Apply Time (Double-Check):** Before executing any `apply_page_proposal`, `apply_update_proposal`, or `confirm_delete_page`, the system MUST re-verify that the proposal's `base_version_hash` still matches the current page hash. If the page was modified between proposal creation and apply (proposal was not held under a WRITE lock, or lock was released), the system MUST re-run the three-way merge with the current page state. If the re-merge succeeds, the proposal content is transparently updated and applied. If the re-merge fails, the apply is rejected with `APPLY_CONFLICT` error and the conflict report is returned, requiring the AI agent to re-fetch, re-propose, and re-apply.

**FR-006 -- Merge Audit Trail:** Every merge operation (auto or failed) MUST be recorded in the `ai_audit_logs` table with: `operation="merge"`, `merge_type` ("auto_merge", "conflict_detected", "force_overwrite"), `base_version_hash`, `local_version_hash`, `remote_version_hash`, `merged_version_hash`, `conflict_count`, `conflict_fields` (JSON array of field paths), and `result` ("applied", "rejected", "requires_review"). These audit entries are linkable to the parent proposal and the AI session.

**FR-007 -- Force Override with User Confirmation:** When a STALE_CONFLICT is detected, the system MAY accept a `forceOverwrite: true` flag on the proposal request, provided the user has explicitly confirmed the override in the UI. When forceOverwrite is used, the system skips the merge, uses the AI's REMOTE proposal as-is, and logs the operation as `merge_type="force_overwrite"` in the audit log. The previous state is preserved in the version snapshot (US-AI-040), so a rollback is always possible. The frontend MUST show a clear warning: "This will overwrite changes made by {user_name} since you started. Their changes can be recovered via version history."

**FR-008 -- Staleness for Delete and Create Operations:** For `propose_delete_page`, staleness detection checks that the page still exists and that its `version_hash` matches. If the page was already deleted, the proposal is rejected with `PAGE_NOT_FOUND`. If the page was modified since fetch, the conflict report warns that deleting the page will discard the intervening changes. For `propose_create_page`, staleness detection is not applicable (no base page to compare), but the system MUST verify that the page title is still unique within the course (preventing a race where another session created a page with the same title between fetch and propose). If title uniqueness fails, the system returns `TITLE_CONFLICT` with suggested alternative titles.

### User Flow: Happy Path (Auto-Merge)

1. Author Alice opens AI chat for Course C1. The AI calls `fetch_page(pageId=P42)`. The response includes `version_hash="abc123"` and the page content (title: "Introduction", body: "Original text").
2. Meanwhile, Author Bob (via the manual editor, not AI) changes the page's metadata (order from 3 to 4) and saves. The page's version_hash becomes "def456".
3. Alice's AI generates a proposal: "Change the title to 'Getting Started' and update the body to 'New text'." It calls `propose_update_page(pageId=P42, versionHash="abc123", patch={...})`.
4. The system detects staleness: `version_hash` "abc123" does not match current "def456". It computes a three-way merge:
   - BASE (abc123): title="Introduction", order=3, body="Original text"
   - LOCAL (def456): title="Introduction", order=4, body="Original text"
   - REMOTE (patch): title="Getting Started", order=3 (not specified in patch, using BASE), body="New text"
   - The merge detects that LOCAL changed `order` (field not touched by REMOTE) and REMOTE changed `title` and `body` (fields not touched by LOCAL). No conflicts.
5. The system auto-merges: title="Getting Started", order=4, body="New text". It creates the proposal with the merged content, sets `base_version_hash` to "def456", and returns success with a `stale_info` block.
6. Alice sees the proposal in the review panel. A small banner says "Page was modified while AI was working. Changes were automatically merged." Alice reviews and approves.
7. The proposal is applied. The version snapshot is created (US-AI-040). The audit log records a successful auto-merge.

### User Flow: Error Path (Conflicting Changes)

1. Author Alice's AI fetches page P42 with `version_hash="abc123"`. Content: title="Introduction", body="Original text".
2. Author Bob manually edits the body to "Bob's version" and saves. Version hash becomes "def456".
3. Alice's AI calls `propose_update_page(pageId=P42, versionHash="abc123", patch={title: "New Title", body: "AI's version"})`.
4. The system detects staleness: version_hash mismatch. It computes the three-way merge:
   - BASE (abc123): title="Introduction", body="Original text"
   - LOCAL (def456): title="Introduction", body="Bob's version"
   - REMOTE (patch): title="New Title", body="AI's version"
   - Conflict detected: `body` was changed in both LOCAL and REMOTE relative to BASE.
5. The system does NOT create the proposal. Instead, it returns a `STALE_CONFLICT` error with the structured conflict report:

```json
{
  "status": "error",
  "code": "STALE_CONFLICT",
  "message": "The page was modified by another session since your fetch. Conflicting changes detected.",
  "details": {
    "pageId": "P42",
    "versionHashProvided": "abc123",
    "versionHashCurrent": "def456",
    "conflicts": [
      {
        "field": "/body",
        "conflictType": "field_level",
        "baseValue": "Original text",
        "localValue": "Bob's version",
        "remoteValue": "AI's version"
      }
    ],
    "nonConflictingChanges": [
      {
        "field": "/title",
        "baseValue": "Introduction",
        "localValue": "Introduction",
        "remoteValue": "New Title"
      }
    ],
    "forceOverwriteAvailable": true
  },
  "retryable": true
}
```

6. The frontend shows a conflict resolution panel: "AI generated changes conflict with changes made by Bob. Review the differences below." with side-by-side comparison of BASE, LOCAL, and REMOTE.
7. Alice has three options: (a) "Retry" -- the AI re-fetches the page and regenerates the proposal from the current state; (b) "Overwrite" -- Alice confirms, sets `forceOverwrite: true`, and the AI proposal overwrites Bob's changes (with version history preserving Bob's work); (c) "Cancel" -- the proposal is discarded.
8. If Alice chooses "Overwrite," the proposal is created with `force_overwrite=true`, the merged document uses REMOTE values for conflicting fields, and the audit log records `merge_type="force_overwrite"`.

### User Flow: Apply-Time Staleness (Double-Check)

1. Alice's AI holds a WRITE lock on page P42. The lock TTL is set to 15 minutes.
2. The AI creates a proposal and the user approves. However, the network between frontend and backend is slow, and before the apply call reaches the server, the lock expires.
3. Meanwhile, Bob (who was waiting in the queue) acquires the lock and makes changes to the page.
4. Alice's apply call arrives. The system checks `base_version_hash` on the proposal against the current page hash. They don't match.
5. The system re-runs the three-way merge. If successful (no conflicts), the proposal is transparently updated and applied. If conflicts exist, the apply is rejected with `APPLY_CONFLICT` error.
6. The frontend shows: "The page was modified while your proposal was pending. Please review the updated proposal." The AI agent receives the conflict report and can re-fetch and re-propose.

### UI/UX Requirements

- **Staleness Notification Banner (Auto-Merge):** When an auto-merge occurs during proposal creation, the proposal review panel shows a non-intrusive banner: "Page was modified since AI fetched it. Changes were merged automatically. [View details]" The details panel shows which fields changed in the intervening edit and which fields came from the AI.

- **Conflict Resolution Panel (Manual):** When conflicting changes are detected, the proposal review panel transitions to a three-panel view: (a) left panel: "Your AI's changes" (REMOTE), (b) center panel: "Original" (BASE), (c) right panel: "Current on server" (LOCAL). Conflicting fields are highlighted in red. Non-conflicting fields are shown in green. The user can accept individual fields from either side or type a custom value.

- **Force Overwrite Confirmation Dialog:** When the user clicks "Overwrite with my changes," a modal dialog appears: "Warning: {user_name} made changes to this page while you were editing. Overwriting will discard their changes. They can be recovered from version history. [Cancel] [Confirm Overwrite]". The confirmation checkbox "I understand this will overwrite another user's changes" must be checked.

- **Merge Audit Log View (Admin):** The admin audit dashboard (US-AI-020) includes a new filter for `operation="merge"`. Each merge event shows: timestamp, AI session ID, user ID, page ID, merge type (auto_merge/conflict_detected/force_overwrite), conflict count, and a "View Diff" button that shows the three-way diff.

- **Configuration Panel (Admin):** A new section in the admin settings panel for "Merge Behavior": dropdown with three options: "Auto-merge safe changes, warn on conflict" (default), "Always abort on any staleness" (strict mode -- no auto-merge, always reject), "Auto-merge all changes, log conflicts" (permissive mode -- auto-merge even conflicting fields using REMOTE wins). A second toggle: "Require user confirmation for force overwrite" (default: enabled).

---

## 2. TECHNICAL SPECIFICATION

### API Contracts

#### 2.1 Modified Read Endpoints (add version_hash to response)

**GET /api/v1/ai/tools/fetch_page**

Response (200) -- modified to include `version_hash`:

```json
{
  "pageId": "P42",
  "title": "Introduction",
  "versionHash": "abc123def456",
  "order": 3,
  "components": [...],
  "metadata": {...}
}
```

The `version_hash` is computed as:

```
SHA-256(
  page.title || page.order_index || page.layout_json ||
  component_1.component_type || component_1.data_json ||
  component_2.component_type || component_2.data_json ||
  ...
)
```

#### 2.2 Stale-Aware Proposal Endpoints

**POST /api/v1/ai/tools/propose_update_page -- modified request schema (add optional version_hash)**

Request:
```json
{
  "sessionId": "uuid-session",
  "versionHash": "abc123def456",
  "input": {
    "pageId": "P42",
    "patch": {
      "title": "New Title",
      "components": [
        {
          "componentId": "comp-001",
          "data": {"body": "New text"}
        }
      ]
    }
  }
}
```

Note: `versionHash` is optional. When omitted, the system fetches the current version_hash from the database and uses that (bypassing staleness detection -- only recommended for create operations or when the AI has just fetched).

**Response (200) -- auto-merge successful:**

```json
{
  "proposalId": "uuid-proposal",
  "staleInfo": {
    "wasStale": true,
    "mergeType": "auto_merge",
    "versionHashProvided": "abc123def456",
    "versionHashCurrent": "ghi789jkl012",
    "versionHashMerged": "mno345pqr678",
    "mergedChanges": {
      "inheritedFromLocal": [
        {"field": "/orderIndex", "localValue": 4, "remoteValue": 3}
      ],
      "inheritedFromRemote": [
        {"field": "/title", "remoteValue": "New Title", "localValue": "Introduction"}
      ]
    },
    "conflictCount": 0
  },
  "proposal": {
    "proposalType": "update",
    "pageId": "P42",
    "proposedChanges": { ... merged content ... },
    "diff": { ... },
    "validationStatus": "valid"
  },
  "lock": {
    "lockId": "uuid-lock",
    "lockType": "write",
    "ttlSecondsRemaining": 840
  }
}
```

**Response (409) -- conflicting staleness:**

```json
{
  "status": "error",
  "code": "STALE_CONFLICT",
  "message": "The page was modified by another session since your fetch. Conflicting changes detected.",
  "details": {
    "pageId": "P42",
    "versionHashProvided": "abc123def456",
    "versionHashCurrent": "ghi789jkl012",
    "stalenessSeverity": "STALE_CONFLICT",
    "conflicts": [
      {
        "field": "jsonPointer:/components/0/data/body",
        "conflictType": "field_level",
        "baseValue": "Original text",
        "localValue": "Bob's version",
        "remoteValue": "AI's version"
      }
    ],
    "nonConflictingChanges": [
      {
        "field": "jsonPointer:/title",
        "baseValue": "Introduction",
        "localValue": "Introduction",
        "remoteValue": "New Title",
        "autoMergedValue": "New Title"
      }
    ],
    "forceOverwriteAvailable": true,
    "conflictCount": 1,
    "totalFieldChanges": 2
  },
  "retryable": true
}
```

**Response (409) -- force overwrite flag accepted:**

```json
{
  "status": "error",
  "code": "FORCE_OVERWRITE_REQUIRES_CONFIRMATION",
  "message": "forceOverwrite flag requires user confirmation. Set userConfirmed: true to proceed.",
  "retryable": true
}
```

#### 2.3 Apply Endpoints with Double-Check

**POST /api/v1/ai/tools/apply_update_proposal -- response when re-merge succeeds at apply time:**

```json
{
  "status": "applied",
  "applyTimeMerge": {
    "wasStale": true,
    "mergeType": "auto_merge",
    "versionHashAtProposal": "abc123def456",
    "versionHashAtApply": "ghi789jkl012",
    "appliedWithMergedContent": true
  },
  "pageId": "P42",
  "versionHash": "mno345pqr678"
}
```

**Response (409) -- re-merge fails at apply time:**

```json
{
  "status": "error",
  "code": "APPLY_CONFLICT",
  "message": "The page was modified since this proposal was created. Conflicting changes prevent automatic application.",
  "details": {
    "proposalId": "uuid-proposal",
    "pageId": "P42",
    "versionHashAtProposal": "abc123def456",
    "versionHashAtApply": "ghi789jkl012",
    "conflicts": [...],
    "nonConflictingChanges": [...]
  },
  "retryable": true
}
```

#### 2.4 Merge Audit Query Endpoint

**GET /api/v1/ai/admin/merges?course_id=...&page_id=...&merge_type=...&date_from=...&date_to=...&limit=50&offset=0**

Response (200):
```json
{
  "merges": [
    {
      "mergeId": "merge-uuid",
      "proposalId": "prop-uuid",
      "sessionId": "session-uuid",
      "userId": "user-uuid",
      "userName": "Alice",
      "courseId": "course-C1",
      "pageId": "P42",
      "pageTitle": "Introduction",
      "mergeType": "auto_merge",
      "conflictCount": 0,
      "baseVersionHash": "abc123",
      "localVersionHash": "def456",
      "remoteVersionHash": "ghi789",
      "mergedVersionHash": "jkl012",
      "result": "applied",
      "createdAt": "2026-06-14T10:30:00Z"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

#### 2.5 Version Hash Computation Utility

The version hash is a SHA-256 digest of the canonical page state. It is computed by the `PageRepository` whenever a page is read or written.

```python
import hashlib
import json


def compute_page_version_hash(page: "PageRecord", components: list["ComponentRecord"]) -> str:
    """Compute a deterministic SHA-256 version hash for a page and its components.
    
    The hash changes whenever any content field of the page or its components
    changes. Ordering matters: components must be sorted by their order_index
    before hashing.
    """
    canonical = {
        "pageId": page.page_id,
        "title": page.title,
        "orderIndex": page.order_index,
        "layout": page.layout_json if hasattr(page, "layout_json") else None,
        "components": sorted(
            [
                {
                    "componentId": c.component_id,
                    "componentType": c.component_type,
                    "data": c.json_data,
                }
                for c in components
            ],
            key=lambda c: (c.get("orderIndex", 0), c["componentId"]),
        ),
    }
    serialized = json.dumps(canonical, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
```

### Database Schema DDL

#### Modifications to `ai_proposals` (from US-AI-043)

The `ai_proposals` table already has `base_version_hash` and `write_lock_id` columns from US-AI-043. Add columns for merge tracking:

```sql
ALTER TABLE ai_proposals ADD COLUMN merged_content JSONB;
ALTER TABLE ai_proposals ADD COLUMN merge_type VARCHAR(32)
    CHECK (merge_type IN ('none', 'auto_merge', 'force_overwrite'));
ALTER TABLE ai_proposals ADD COLUMN merge_metadata JSONB DEFAULT '{}'::jsonb;
ALTER TABLE ai_proposals ADD COLUMN conflict_report JSONB;
ALTER TABLE ai_proposals ADD COLUMN staleness_status VARCHAR(32) DEFAULT 'fresh'
    CHECK (staleness_status IN ('fresh', 'stale_no_change', 'stale_compatible', 'stale_conflict'));
```

#### New Table: `ai_merge_audit`

Stores a detailed record of every merge operation for audit and debugging.

```sql
CREATE TABLE IF NOT EXISTS ai_merge_audit (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merge_id            VARCHAR(64) NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,

    -- Linking
    proposal_id         UUID REFERENCES ai_proposals(id) ON DELETE SET NULL,
    session_id          UUID REFERENCES ai_sessions(id) ON DELETE SET NULL,
    organization_id     UUID NOT NULL,
    course_id           VARCHAR(64) NOT NULL,
    page_id             VARCHAR(64),

    -- Who
    user_id             UUID NOT NULL,
    user_name           VARCHAR(255),

    -- Merge details
    merge_type          VARCHAR(32) NOT NULL
        CHECK (merge_type IN ('auto_merge', 'conflict_detected', 'force_overwrite', 'apply_time_merge')),
    result              VARCHAR(32) NOT NULL
        CHECK (result IN ('proposal_created', 'proposal_rejected', 'applied', 'apply_rejected')),

    -- Version hashes
    base_version_hash   VARCHAR(64) NOT NULL,
    local_version_hash  VARCHAR(64) NOT NULL,
    remote_version_hash VARCHAR(64) NOT NULL,
    merged_version_hash VARCHAR(64),

    -- Conflict data
    conflict_count      INTEGER NOT NULL DEFAULT 0,
    conflict_fields     JSONB DEFAULT '[]'::jsonb,
    non_conflict_fields JSONB DEFAULT '[]'::jsonb,

    -- Force overwrite
    force_overwrite     BOOLEAN NOT NULL DEFAULT FALSE,
    user_confirmed      BOOLEAN NOT NULL DEFAULT FALSE,

    -- Metadata
    staleness_severity  VARCHAR(32)
        CHECK (staleness_severity IN ('STALE_NO_CHANGE', 'STALE_COMPATIBLE', 'STALE_CONFLICT')),
    duration_ms         INTEGER,

    -- Timestamps
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_merge_audit_proposal ON ai_merge_audit(proposal_id);
CREATE INDEX idx_merge_audit_session ON ai_merge_audit(session_id);
CREATE INDEX idx_merge_audit_page ON ai_merge_audit(page_id);
CREATE INDEX idx_merge_audit_org ON ai_merge_audit(organization_id);
CREATE INDEX idx_merge_audit_type ON ai_merge_audit(merge_type);
CREATE INDEX idx_merge_audit_created ON ai_merge_audit(created_at DESC);
```

#### New Table: `ai_merge_config` (per-organization merge policy)

```sql
CREATE TABLE IF NOT EXISTS ai_merge_config (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id                 UUID NOT NULL UNIQUE,

    -- Merge strategy
    merge_strategy                  VARCHAR(32) NOT NULL DEFAULT 'auto_merge_safe'
        CHECK (merge_strategy IN (
            'auto_merge_safe',       -- Auto-merge non-conflicting, warn on conflict
            'strict',                -- Always abort on any staleness
            'permissive'             -- Auto-merge all, REMOTE wins on conflict
        )),

    -- Force overwrite
    require_confirmation_for_overwrite BOOLEAN NOT NULL DEFAULT TRUE,

    -- Staleness detection
    stale_lock_ttl_seconds          INTEGER NOT NULL DEFAULT 300,

    -- Version hash computation
    version_hash_algorithm          VARCHAR(16) NOT NULL DEFAULT 'sha256'
        CHECK (version_hash_algorithm IN ('sha256', 'sha512')),

    -- Timestamps
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_merge_config_org ON ai_merge_config(organization_id);
```

### Service / Module Design

#### Module: `app/services/ai/merge_manager.py`

```python
"""
Merge Manager Service

Three-way merge engine for page content. Determines staleness severity,
performs field-level automatic merging, produces structured conflict reports,
and coordinates with the Lock Manager and Proposal Service.

Supports three merge strategies:
- auto_merge_safe: merge non-conflicting fields, reject on conflict
- strict: reject any staleness, no auto-merge
- permissive: merge all fields, REMOTE wins on conflict
"""
from __future__ import annotations
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
import hashlib
import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class StalenessSeverity(str, Enum):
    FRESH = "fresh"
    STALE_NO_CHANGE = "stale_no_change"
    STALE_COMPATIBLE = "stale_compatible"
    STALE_CONFLICT = "stale_conflict"


class MergeType(str, Enum):
    AUTO_MERGE = "auto_merge"
    CONFLICT_DETECTED = "conflict_detected"
    FORCE_OVERWRITE = "force_overwrite"
    APPLY_TIME_MERGE = "apply_time_merge"


class MergeStrategy(str, Enum):
    AUTO_MERGE_SAFE = "auto_merge_safe"
    STRICT = "strict"
    PERMISSIVE = "permissive"


@dataclass
class FieldConflict:
    """A single field-level conflict."""
    field: str  # JSON Pointer path
    conflict_type: str  # field_level, component_added_removed, schema_mismatch
    base_value: Any = None
    local_value: Any = None
    remote_value: Any = None
    merged_value: Any = None  # Only populated for permissive strategy


@dataclass
class NonConflictingChange:
    """A field that changed in only one direction."""
    field: str
    base_value: Any = None
    local_value: Any = None
    remote_value: Any = None
    source: str = None  # "local" or "remote"
    auto_merged_value: Any = None


@dataclass
class MergeResult:
    """Result of a three-way merge operation."""
    is_merge_possible: bool
    severity: StalenessSeverity
    merge_type: MergeType
    merged_content: Optional[dict] = None
    conflicts: List[FieldConflict] = field(default_factory=list)
    non_conflicting_changes: List[NonConflictingChange] = field(default_factory=list)
    base_version_hash: str = ""
    local_version_hash: str = ""
    remote_version_hash: str = ""
    merged_version_hash: str = ""
    force_overwrite: bool = False
    staleness_message: str = ""


class MergeManager:
    """
    MergeManager handles staleness detection and three-way merge resolution
    for page content in the AI authoring system.

    Responsibilities:
    1. Compute version_hash for a page (deterministic SHA-256).
    2. Detect staleness severity given BASE, LOCAL, and REMOTE states.
    3. Perform field-level three-way merge for non-conflicting changes.
    4. Produce structured conflict reports when merge is not possible.
    5. Apply merge strategy from organization configuration.
    6. Track merge audit events.
    """

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    @staticmethod
    def compute_page_hash(page: Any, components: List[Any]) -> str:
        """
        Compute the deterministic SHA-256 version hash for a page
        and its components. See compute_page_version_hash() above.
        """
        ...

    @staticmethod
    def _serialize_page_canonical(page: Any, components: List[Any]) -> dict:
        """
        Produce a canonical JSON-serializable dict for hashing and comparison.

        Structure:
        {
            "pageId": "...",
            "title": "...",
            "orderIndex": N,
            "layout": {...} or None,
            "components": [
                {
                    "componentId": "...",
                    "componentType": "...",
                    "data": {...},
                    "orderIndex": N
                },
                ...
            ]
        }
        Components are sorted by orderIndex then componentId for stability.
        """
        ...

    async def get_organization_merge_config(
        self, organization_id: str
    ) -> "MergeConfig":
        """Get the merge configuration for an organization."""
        ...

    async def detect_staleness(
        self,
        *,
        page_state_current: dict,
        page_state_base: Optional[dict],
        version_hash_provided: Optional[str],
        version_hash_current: str,
        remote_patch: dict,
    ) -> Tuple[StalenessSeverity, List[FieldConflict], List[NonConflictingChange]]:
        """
        Detect staleness between BASE and LOCAL, and compute field-level
        conflicts with the REMOTE patch.

        Steps:
        1. If no version_hash_provided, return FRESH (no staleness check).
        2. If version_hash_provided == version_hash_current, return FRESH.
        3. Compute the diff between BASE page state and LOCAL page state.
        4. For each field in the REMOTE patch, check if the same field
           was also changed in LOCAL (relative to BASE).
        5. If no overlapping fields: return STALE_NO_CHANGE or STALE_COMPATIBLE
           (depending on whether the LOCAL changes touch content areas
           that are semantically related to the REMOTE changes).
        6. If overlapping fields found: return STALE_CONFLICT with
           the list of conflicting fields.
        """
        ...

    @staticmethod
    def _compute_field_diff(
        base: dict, local: dict, prefix: str = ""
    ) -> List[Tuple[str, Any, Any]]:
        """
        Recursively compute field-level differences between two dicts.

        Returns list of (json_pointer_path, base_value, local_value) tuples
        for every field that differs between base and local.

        Handles:
        - Dict value changes
        - List changes (detected as full replacement at the list path)
        - Nested object changes
        - Field additions and removals
        """
        ...

    async def perform_three_way_merge(
        self,
        *,
        base_state: dict,
        local_state: dict,
        remote_patch: dict,
        merge_strategy: MergeStrategy = MergeStrategy.AUTO_MERGE_SAFE,
        force_overwrite: bool = False,
        user_confirmed: bool = False,
    ) -> MergeResult:
        """
        Perform a three-way merge of page content.

        The merge process:
        1. Compute field-level diff between BASE and LOCAL.
        2. For each field in REMOTE_PATCH:
           a. If the field was NOT changed in LOCAL → auto-apply REMOTE value.
           b. If the field WAS changed in LOCAL:
              - If merge_strategy is STRICT → mark as conflict, do NOT merge.
              - If merge_strategy is AUTO_MERGE_SAFE → mark as conflict, do NOT merge.
              - If merge_strategy is PERMISSIVE → REMOTE wins, auto-merge.
              - If force_overwrite is True → REMOTE wins for ALL fields.
        3. For each field changed in LOCAL but NOT in REMOTE_PATCH:
           - Apply the LOCAL value (it's an unrelated change).
        4. Build the merged_content dict.
        5. Compute merged_version_hash from merged_content.
        6. Return MergeResult with appropriate severity and merge_type.

        Raises:
            MergeConflictError: if conflicts exist and strategy is not permissive
            ForceOverwriteRequiresConfirmationError: if force_overwrite without user_confirmed
        """
        ...

    async def create_merge_audit_entry(
        self,
        *,
        proposal_id: Optional[str],
        session_id: str,
        organization_id: str,
        course_id: str,
        page_id: Optional[str],
        user_id: str,
        user_name: Optional[str],
        merge_type: MergeType,
        result: str,
        base_version_hash: str,
        local_version_hash: str,
        remote_version_hash: str,
        merged_version_hash: Optional[str],
        conflict_count: int,
        conflict_fields: List[dict],
        non_conflict_fields: List[dict],
        force_overwrite: bool,
        user_confirmed: bool,
        staleness_severity: Optional[str],
        duration_ms: int,
    ) -> dict:
        """
        Record a merge audit event in ai_merge_audit table.
        Called after every merge attempt, whether successful or not.
        """
        ...

    async def get_merge_strategy_for_session(
        self, session_id: str, organization_id: str
    ) -> MergeStrategy:
        """
        Determine the merge strategy for a given AI session.

        Priority:
        1. Session-level override (if set in session metadata).
        2. Organization-level config (ai_merge_config table).
        3. Default: AUTO_MERGE_SAFE.
        """
        ...


@dataclass
class MergeConfig:
    """Organization-level merge configuration."""
    merge_strategy: MergeStrategy = MergeStrategy.AUTO_MERGE_SAFE
    require_confirmation_for_overwrite: bool = True
    stale_lock_ttl_seconds: int = 300
    version_hash_algorithm: str = "sha256"


class MergeConflictError(Exception):
    """Raised when a three-way merge discovers unresolvable conflicts."""
    def __init__(self, message: str, merge_result: MergeResult):
        self.merge_result = merge_result
        super().__init__(message)


class ForceOverwriteRequiresConfirmationError(Exception):
    """Raised when forceOverwrite is set but userConfirmed is false."""
    pass
```

#### Module: `app/services/ai/stale_detection_middleware.py`

```python
"""
Stale Detection Middleware

Decorators and middleware to inject staleness checks into proposal and
apply tool handlers. Integrates with the Lock Manager (US-AI-043) for
write-lock acquisition and the proposal lifecycle (US-AI-010) for
version_hash tracking.
"""
from __future__ import annotations
from functools import wraps
from typing import Callable, Optional

from app.services.ai.merge_manager import MergeManager, StalenessSeverity


def with_stale_detection(resource_id_param: str = "pageId", version_hash_param: str = "versionHash"):
    """
    Decorator for proposal creation handlers that adds staleness detection
    and optional three-way merge.

    Placed AFTER the lock acquisition decorator (lock must be acquired
    before staleness check, because the lock prevents the page from
    changing during the merge).

    Behavior by strategy:
    - strict: if stale, return STALE_CONFLICT without attempting merge.
    - auto_merge_safe: attempt merge; return STALE_CONFLICT on conflict.
    - permissive: attempt merge; auto-resolve conflicts with REMOTE wins.

    The decorator:
    1. Before handler: fetches current page state (local) and the base
       state corresponding to versionHash (if available).
    2. Calls MergeManager.detect_staleness().
    3. If fresh: calls the handler normally.
    4. If stale and strategy allows merge: calls MergeManager.perform_three_way_merge().
       - On success: rewrites the handler's input patch with merged content.
       - On failure: returns STALE_CONFLICT error response.
    5. After handler: writes merge audit entry.
    """
    ...


def with_apply_time_stale_check():
    """
    Decorator for apply handlers that re-verifies version_hash before applying.

    This is the "double-check" mechanism. It runs inside the apply
    transaction, after the lock has been verified but before the mutation.

    1. Compares proposal.base_version_hash with current page hash.
    2. If matched: proceeds with apply.
    3. If mismatched: attempts re-merge.
       - On success: updates proposal content transparently, proceeds with apply.
       - On failure: returns APPLY_CONFLICT error.
    4. Writes merge audit entry for apply-time merge.
    """
    ...


def with_fetch_version_hash():
    """
    Decorator for fetch handlers that injects version_hash into the response.

    Computes the hash using MergeManager.compute_page_hash() and adds
    it to the response payload under the "versionHash" key.
    """
    ...
```

#### New Module: `app/services/ai/version_hash_repository.py`

```python
"""
Version Hash Repository

Provides low-level database access for computing and storing version hashes,
and for retrieving the BASE page state for a given version_hash.

The BASE state retrieval is an important function: given a version_hash
that was previously returned, we need to reconstruct the exact page state
that existed at that time. This requires either:
(a) Looking up a version snapshot (US-AI-040) that matches the hash, or
(b) Extracting the state from a recent ai_proposals.merged_content or
    from the current page state if the hash matches the current state.
(c) Falling back to the ai_audit_logs.before_snapshot if available.

For most cases, the version_hash from the immediate previous fetch will
correspond to the current page state (no intervening edits), so (b) is
the common path.
"""
from __future__ import annotations
from typing import Optional
import hashlib
import json

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.page_component import PageRecord, ComponentRecord


class VersionHashRepository:
    """
    Repository for version hash computation and BASE state retrieval.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def compute_page_hash(self, page_id: str) -> Optional[str]:
        """Fetch a page and its components, compute and return the hash,
        or None if the page does not exist."""
        ...

    async def fetch_page_state(self, page_id: str) -> Optional[dict]:
        """Fetch a page and all its components, return as canonical dict
        suitable for merge operations."""
        ...

    async def get_base_state_for_hash(
        self, page_id: str, version_hash: str
    ) -> Optional[dict]:
        """
        Retrieve the page state corresponding to a given version_hash.

        Strategy:
        1. If version_hash matches current page state, return current state.
        2. Check ai_proposals where merged_version_hash = version_hash
           and return the merged content as the base state.
        3. Check ai_version_snapshots (US-AI-040) for a snapshot whose
           page content hash equals version_hash.
        4. Check ai_audit_logs for before_snapshot whose computed hash
           equals version_hash.
        5. If none found, return None (BASE state unavailable).
        """
        ...

    async def store_version_hash_mapping(
        self, page_id: str, version_hash: str, state: dict
    ) -> None:
        """Store a mapping from version_hash to page state for future
        BASE state retrieval. This is called after every proposal creation
        and every apply that produces a new version_hash.

        The mapping is stored in a lightweight lookup table to enable
        fast BASE state reconstruction without requiring full version
        snapshot rehydration."""
        ...
```

#### Integration with Proposal Lifecycle (US-AI-010 / US-AI-043)

The modified proposal creation flow:

```
propose_update_page(pageId, versionHash, patch):
  1. [Lock Manager] Acquire WRITE lock on pageId (from US-AI-043).
  2. [Stale Detection] If versionHash provided:
     a. Compute current page hash.
     b. If versionHash == currentHash → FRESH, proceed normally.
     c. If different:
        i.  Fetch merge strategy for session/organization.
        ii. If strategy == STRICT → return STALE_CONFLICT, no merge.
        iii. Fetch BASE state for versionHash (from VersionHashRepository).
        iv. Compute field diffs between BASE and LOCAL.
        v.  Check for conflicting fields with REMOTE patch.
        vi. If conflicts exist:
            - If strategy == PERMISSIVE → auto-merge with REMOTE wins.
            - If forceOverwrite == true + confirmed → REMOTE wins.
            - Else → return STALE_CONFLICT with conflict report.
        vii. If no conflicts → auto-merge LOCAL non-conflicting changes
             into the proposal.
     d. Update proposal's merged_content, merge_type, base_version_hash.
  3. [Proposal Service] Create proposal record with merged content.
  4. [Audit] Write merge_audit entry.
  5. Return proposal with staleInfo block.
```

The modified apply flow:

```
apply_update_proposal(proposalId):
  1. [Lock Manager] Verify WRITE lock ownership (from US-AI-043).
  2. [Stale Detection Double-Check]
     a. Compute current page hash.
     b. If proposal.base_version_hash == currentHash → proceed.
     c. If different:
        i.  Attempt re-merge using proposal content as REMOTE.
        ii. If re-merge succeeds → update proposal content transparently.
        iii. If re-merge fails → return APPLY_CONFLICT.
  3. [Apply Service] Apply the proposal (from US-AI-010).
  4. [Versioning] Create version snapshot (from US-AI-040).
  5. [Lock Manager] Release WRITE lock.
  6. [Audit] Write merge_audit entry for apply-time merge.
```

### Configuration Variables

```python
# In app/core/config.py or environment variables:

# Merge strategy defaults
AI_MERGE_STRATEGY: str = "auto_merge_safe"   # 'auto_merge_safe', 'strict', 'permissive'
AI_MERGE_REQUIRE_CONFIRMATION_FOR_OVERWRITE: bool = True
AI_MERGE_STALE_LOCK_TTL_SECONDS: int = 300    # 5 minutes

# Version hash computation
AI_VERSION_HASH_ALGORITHM: str = "sha256"     # 'sha256' or 'sha512'

# Merge audit
AI_MERGE_AUDIT_ENABLED: bool = True
AI_MERGE_AUDIT_RETENTION_DAYS: int = 90

# Performance
AI_MERGE_MAX_FIELD_DEPTH: int = 10            # Max recursion depth for field diff
AI_MERGE_TIMEOUT_MS: int = 5000               # Max time for a single merge operation
```

### Integration Points

| Integration | Description | Status |
|---|---|---|
| US-AI-010 (Apply Safety) | After lock verification in apply, add double-check stale detection and re-merge | Modify |
| US-AI-040 (Versioning) | VersionHashRepository can use version snapshots for BASE state retrieval | Modify |
| US-AI-043 (Locking) | Lock must be held during merge to ensure LOCAL state doesn't change mid-merge | Existing dependency |
| US-AI-020 (Audit) | Merge audit events written to ai_merge_audit table; cross-reference with ai_audit_logs | New + Modify |
| US-AI-023 (Chat Orchestrator) | Handle STALE_CONFLICT and APPLY_CONFLICT errors: re-fetch page, re-present to LLM | Modify |
| US-AI-024 (Frontend AI Layer) | Render staleInfo banner, conflict resolution panel, force-overwrite confirmation dialog | Modify |
| US-AI-007 (Page Fetch) | Add version_hash to fetch_page response | Modify |
| US-AI-011 (Create Page) | Add staleness check for title uniqueness | Modify |
| US-AI-012 (Update Page) | Add version_hash input to propose_update_page; integrate merge | Modify |
| US-AI-013 (Delete Page) | Add staleness check verifying page still exists and version matches | Modify |

---

## 3. NON-FUNCTIONAL REQUIREMENTS

### Performance Targets

- Version hash computation MUST complete in under 10 milliseconds p95 for a page with up to 20 components.
- Three-way merge for a page with up to 50 fields MUST complete in under 100 milliseconds p95 for non-conflicting merges.
- Three-way merge for conflicting merges (report generation only, no auto-apply) MUST complete in under 200 milliseconds p95.
- Staleness detection (hash comparison only) MUST complete in under 5 milliseconds p95.
- BASE state retrieval from VersionHashRepository MUST complete in under 50 milliseconds p95 for cached mappings, under 500 milliseconds p95 when falling back to version snapshots.
- The merge audit write MUST add no more than 10 milliseconds overhead to the proposal creation or apply flow.
- The stale detection middleware MUST NOT add more than 3 milliseconds overhead when the version hash matches (FRESH case -- the common path).

### Security Requirements

- Version hash integrity: the hash MUST be computed server-side only. Client-submitted hashes are used only for comparison, never trusted as the source of truth for page state.
- Force overwrite requires confirmed user intent: the `userConfirmed: true` flag MUST only be accepted when the frontend has displayed a specific warning dialog and the user has actively checked a confirmation checkbox. The backend MUST NOT accept `forceOverwrite: true` programmatically from the AI agent without `userConfirmed: true`.
- Merge audit entries are immutable once written: they MAY NOT be deleted or modified by any user, including admins. (Expiry/archival is handled by retention policy, not manual deletion.)
- Cross-organization isolation: merge config and merge audit data MUST be scoped to organization_id. Users from Organization A MUST NOT see merge data from Organization B.
- The BASE state retrieval for a given version_hash MUST verify that the hash belongs to a page and organization that the requesting session has access to.

### Reliability Requirements

- If the merge manager service is temporarily unavailable (database connection failure), proposal creation MUST fall back to the strict mode: reject with STALE_CONFLICT rather than silently creating an un-merged proposal. The system MUST NOT auto-merge when it cannot verify the merge result.
- If BASE state retrieval fails (hash not found in any store), the system MUST fall back to strict mode: treat as STALE_CONFLICT and reject the proposal. The AI agent must re-fetch the page.
- Merge operations MUST be idempotent: given the same BASE, LOCAL, and REMOTE inputs, the merge result MUST always be identical. This ensures replayability for debugging.
- The merge audit write MUST be in the same database transaction as the proposal creation or apply, ensuring that merge records are never orphaned.

### Scalability Requirements

- The VersionHashRepository mapping store MUST support up to 10,000 hash-to-state lookups per second across an organization.
- The merge audit table must support up to 1,000 merge events per minute (peak) without degrading query performance. Indexes on organization_id, page_id, and merge_type support the admin audit queries.
- The canonical serialization and hashing of pages MUST NOT hold database connections longer than 50 milliseconds.
- For the BASE state retrieval fallback using version snapshots (US-AI-040), the version snapshot rehydration must complete within 500 milliseconds (already a requirement in US-AI-040).

---

## 4. CURRENT STATE ASSESSMENT

### What Exists

1. **US-AI-043 (Concurrency Control):** Defines pessimistic locking (WRITE/READ/SESSION locks), lock TTL, heartbeat, conflict queues, and stale lock scanner. Also defines the optimistic concurrency concept in FR-008 via `version_hash` on `ai_proposals`, but the `version_hash` column exists only as a schema addition -- there is no merge resolution logic. The `propose_update_page` handler can reject with `STALE_BASE_VERSION` but only as a simple reject, not a merge.

2. **US-AI-043 Database Schema:** `ai_proposals` table already has `write_lock_id` and `base_version_hash` columns (added by US-AI-043 tasks). No `merged_content`, `merge_type`, `merge_metadata`, or `conflict_report` columns exist yet.

3. **US-AI-040 (Versioning):** Provides `ai_version_snapshots` with full-course state snapshots. Can be used by `VersionHashRepository.get_base_state_for_hash()` as a fallback source of truth for historical page states.

4. **US-AI-010 (Apply Safety):** Provides the transactional apply pipeline. Currently has no stale detection logic at apply time -- it assumes the proposal's content is current.

5. **`app/utils/version_lock.py`:** Empty file (1 blank line). Originally intended for optimistic concurrency handling but never implemented. This file will be replaced/refactored into the new MergeManager service.

6. **PageRepository (`app/repositories/page_component_repo.py`):** Current CRUD operations do not compute or return version hashes. The `fetch_page_by_id` method returns page and component data but without any staleness metadata.

### What Must Be Built

1. **MergeManager Service** (`app/services/ai/merge_manager.py`): Full three-way merge engine with staleness detection, field-level diff computation, conflict classification, auto-merge, and audit entry creation.
2. **VersionHashRepository** (`app/services/ai/version_hash_repository.py`): Hash computation, BASE state retrieval with multi-source fallback, hash-to-state mapping storage.
3. **Stale Detection Middleware** (`app/services/ai/stale_detection_middleware.py`): Decorators for proposal creation handlers (`@with_stale_detection`) and apply handlers (`@with_apply_time_stale_check`), and fetch handlers (`@with_fetch_version_hash`).
4. **New Database Tables and Migrations:** `ai_merge_audit` table, `ai_merge_config` table. ALTER TABLE additions to `ai_proposals` (5 new columns).
5. **Merge Audit Admin Endpoint** (`GET /api/v1/ai/admin/merges`): Query merge events with filters.
6. **Merge Config Admin Endpoint** (`GET/PUT /api/v1/ai/admin/merge-config`): Per-organization merge policy configuration.

### What Must Be Modified

1. **`ai_proposals` table** -- add `merged_content`, `merge_type`, `merge_metadata`, `conflict_report`, `staleness_status` columns.
2. **`fetch_page` handler** -- compute and return `version_hash` in response.
3. **`propose_update_page` handler** -- accept `versionHash` in request; integrate stale detection and merge before proposal creation.
4. **`propose_delete_page` handler** -- add staleness check (page exists, hash matches).
5. **`propose_create_page` handler** -- add title-uniqueness staleness check (race condition prevention).
6. **`apply_update_proposal` and `apply_page_proposal` handlers** -- add apply-time stale double-check with re-merge.
7. **`confirm_delete_page` handler** -- add apply-time staleness verification.
8. **Frontend** -- version_hash returned in fetch responses; staleInfo rendered in proposal review; conflict resolution panel; force-overwrite confirmation dialog.
9. **Chat orchestrator (US-AI-023)** -- handle STALE_CONFLICT, APPLY_CONFLICT, and FORCE_OVERWRITE_REQUIRES_CONFIRMATION errors in the AI loop.

---

## 5. EXPANSION POINTS

### Technical Expansion Points

**TXP-01 -- Semantic Conflict Detection Beyond Field Level:** Replace the simple field-level diff with a semantic diff engine that understands the content model. For example, if the AI changes the question text in an MCQ component and another user changes the answer options, the system should recognize these as semantically related conflicts (the question text change may invalidate the answer options). This would require a component-type-specific conflict detection plugin system where each component type (content-text, mcq, assessment) can register custom conflict detection logic.

**TXP-02 -- Multi-Page Batch Merge:** When an AI session proposes changes across multiple pages (e.g., a full-course generation), the merge system should support batch staleness detection: check all pages at once, report all conflicts in a single response, and allow the user to resolve conflicts across pages in a single review session. This requires aggregating version_hashes for all changed pages and coordinating merge results across multiple proposal records.

**TXP-03 -- CRDT-Based Real-Time Merge:** Replace the snapshot-based three-way merge with Conflict-Free Replicated Data Types (CRDTs) for near-real-time collaborative AI authoring. This would allow multiple AI sessions (or human + AI) to edit the same page simultaneously without lock contention. Each edit produces a CRDT operation that can be merged without conflicts at the data structure level. This is a major architectural change and would replace the pessimistic locking approach for organizations that need real-time collaboration.

**TXP-04 -- Machine-Learned Merge Conflict Resolution:** Train a small ML model (or use the existing LLM) to automatically resolve merge conflicts based on context. When a conflict is detected, the system would present BASE, LOCAL, and REMOTE to an LLM with a prompt asking it to produce a sensible merged result. The LLM's output would be proposed as the merged content, and the human would review it. This could significantly reduce manual conflict resolution effort for organizations with frequent concurrent editing.

### Functional Expansion Points

**FXP-01 -- Component-Level Merge Granularity:** Instead of page-level staleness detection and merge, implement component-level granularity. Two AI sessions working on different components of the same page would never conflict, even without page-level locks. This requires the version_hash to be computed per-component as well as per-page, and the proposal system to support component-scoped proposals (not just full-page patches).

**FXP-02 -- Scheduled Merge Policy Changes:** Allow admins to schedule merge strategy changes (e.g., "switch to strict mode during the final review phase of course production"). The system would automatically adjust merge behavior based on the course's lifecycle stage (drafting, reviewing, approved, published). This integrates with the course workflow/status system.

**FXP-03 -- User Preference for Merge Notification:** Allow individual authors to configure their notification preferences for merge events: "Send me an email when my changes are force-overwritten," "Show a dashboard notification when a merge occurs on my pages," or "Only notify me on conflicting merges." This integrates with the notification system (US-AI-045).

**FXP-04 -- Merge Dry-Run and Preview for Admins:** Provide an admin-only endpoint that performs a dry-run merge between any two version snapshots (US-AI-040) and displays the merge result with conflict highlights. This allows admins to preview what would happen if they merged two parallel versions of a course without actually committing the merge. Useful for course consolidation workflows.

---

## 6. VALIDATION AND TESTING

### Unit Tests (5+)

**UT-01 -- Version Hash Determinism:**

Test that identical page content always produces an identical version_hash, and that changing any single field produces a different hash.

```python
async def test_version_hash_determinism(version_hash_repo, sample_page, sample_components):
    hash1 = await version_hash_repo.compute_page_hash(sample_page.page_id)
    hash2 = await version_hash_repo.compute_page_hash(sample_page.page_id)
    assert hash1 == hash2  # Same content = same hash

    # Change title
    sample_page.title = "Changed Title"
    hash3 = await version_hash_repo.compute_page_hash(sample_page.page_id)
    assert hash3 != hash1  # Different content = different hash

    # Change component data
    sample_components[0].json_data["body"] = "Modified body"
    hash4 = await version_hash_repo.compute_page_hash(sample_page.page_id)
    assert hash4 != hash1  # Component change also changes hash
```

**UT-02 -- Staleness Severity Classification:**

Test that the merge manager correctly classifies staleness as FRESH, STALE_NO_CHANGE, STALE_COMPATIBLE, and STALE_CONFLICT given various combinations of BASE, LOCAL, and REMOTE inputs.

```python
async def test_staleness_severity_classification(merge_manager):
    base = {"title": "Intro", "body": "Text", "order": 3}
    # LOCAL only changes order
    local = {"title": "Intro", "body": "Text", "order": 4}
    # REMOTE only changes title
    remote_patch = {"title": "New Title"}

    severity, conflicts, non_conflicts = await merge_manager.detect_staleness(
        page_state_current=local,
        page_state_base=base,
        version_hash_provided="hash-base",
        version_hash_current="hash-local",
        remote_patch=remote_patch,
    )
    assert severity == StalenessSeverity.STALE_COMPATIBLE
    assert len(conflicts) == 0
    assert len(non_conflicts) == 2  # order changed in local, title in remote

    # Now test with overlapping field
    remote_patch_conflict = {"body": "AI's new body"}
    severity2, conflicts2, non_conflicts2 = await merge_manager.detect_staleness(
        page_state_current={"title": "Intro", "body": "Local's body", "order": 3},
        page_state_base=base,
        version_hash_provided="hash-base",
        version_hash_current="hash-local",
        remote_patch=remote_patch_conflict,
    )
    assert severity2 == StalenessSeverity.STALE_CONFLICT
    assert len(conflicts2) == 1
    assert conflicts2[0].field == "/body"
```

**UT-03 -- Three-Way Auto-Merge (No Conflicts):**

Test that a three-way merge correctly produces merged content when LOCAL and REMOTE touch non-overlapping fields.

```python
async def test_three_way_merge_no_conflicts(merge_manager):
    base = {"title": "Intro", "body": "Original", "order": 3}
    local = {"title": "Intro", "body": "Original", "order": 4}  # order changed
    remote_patch = {"title": "New Title"}  # title changed

    result = await merge_manager.perform_three_way_merge(
        base_state=base,
        local_state=local,
        remote_patch=remote_patch,
        merge_strategy=MergeStrategy.AUTO_MERGE_SAFE,
    )
    assert result.is_merge_possible is True
    assert result.severity == StalenessSeverity.STALE_COMPATIBLE
    assert result.merged_content["title"] == "New Title"  # From remote
    assert result.merged_content["order"] == 4  # From local
    assert result.merged_content["body"] == "Original"  # Unchanged
    assert len(result.conflicts) == 0
    assert len(result.non_conflicting_changes) == 2
```

**UT-04 -- Three-Way Merge Conflict Detection (Auto-Merge-Safe):**

Test that conflicting changes (same field changed in both LOCAL and REMOTE) are correctly detected and the merge is rejected in auto_merge_safe strategy.

```python
async def test_three_way_merge_conflict_detected(merge_manager):
    base = {"title": "Intro", "body": "Original"}
    local = {"title": "Intro", "body": "Bob's version"}
    remote_patch = {"body": "AI's version"}  # Same field as local

    result = await merge_manager.perform_three_way_merge(
        base_state=base,
        local_state=local,
        remote_patch=remote_patch,
        merge_strategy=MergeStrategy.AUTO_MERGE_SAFE,
    )
    assert result.is_merge_possible is False
    assert result.severity == StalenessSeverity.STALE_CONFLICT
    assert len(result.conflicts) == 1
    assert result.conflicts[0].field == "/body"
    assert result.conflicts[0].base_value == "Original"
    assert result.conflicts[0].local_value == "Bob's version"
    assert result.conflicts[0].remote_value == "AI's version"
```

**UT-05 -- Permissive Merge Strategy (Remote Wins):**

Test that the PERMISSIVE strategy auto-merges conflicting fields by accepting the REMOTE value.

```python
async def test_permissive_merge_remote_wins(merge_manager):
    base = {"title": "Intro", "body": "Original"}
    local = {"title": "Intro", "body": "Bob's version"}
    remote_patch = {"title": "AI Title", "body": "AI's version"}  # body conflicts

    result = await merge_manager.perform_three_way_merge(
        base_state=base,
        local_state=local,
        remote_patch=remote_patch,
        merge_strategy=MergeStrategy.PERMISSIVE,
    )
    assert result.is_merge_possible is True
    assert result.severity == StalenessSeverity.STALE_CONFLICT
    assert result.merged_content["body"] == "AI's version"  # Remote wins
    assert result.merged_content["title"] == "AI Title"  # Remote wins
    assert len(result.conflicts) == 1  # body conflict was auto-resolved
```

**UT-06 -- Force Overwrite Requires Confirmation:**

Test that setting `forceOverwrite=True` without `userConfirmed=True` raises an error, and that with confirmation it succeeds.

```python
async def test_force_overwrite_requires_confirmation(merge_manager):
    with pytest.raises(ForceOverwriteRequiresConfirmationError):
        await merge_manager.perform_three_way_merge(
            base_state={"title": "Intro"},
            local_state={"title": "Bob's Title"},
            remote_patch={"title": "AI's Title"},
            merge_strategy=MergeStrategy.AUTO_MERGE_SAFE,
            force_overwrite=True,
            user_confirmed=False,
        )

    result = await merge_manager.perform_three_way_merge(
        base_state={"title": "Intro"},
        local_state={"title": "Bob's Title"},
        remote_patch={"title": "AI's Title"},
        merge_strategy=MergeStrategy.AUTO_MERGE_SAFE,
        force_overwrite=True,
        user_confirmed=True,
    )
    assert result.is_merge_possible is True
    assert result.force_overwrite is True
    assert result.merged_content["title"] == "AI's Title"
```

### Integration Tests (3+)

**IT-01 -- Full Auto-Merge Lifecycle via API:**

Test the end-to-end flow: fetch page with version_hash -> another session edits page -> propose with stale hash -> auto-merge occurs -> proposal is created with merged content.

```python
async def test_auto_merge_lifecycle_via_api(
    async_client, auth_headers, sample_course, sample_page
):
    # 1. Fetch page to get version hash
    fetch_resp = await async_client.post(
        "/api/v1/ai/tools/fetch_page",
        headers=auth_headers,
        json={"pageId": sample_page.page_id},
    )
    assert fetch_resp.status_code == 200
    original_hash = fetch_resp.json()["versionHash"]

    # 2. Simulate another session editing the page (modify order_index)
    edit_resp = await async_client.put(
        f"/api/v1/pages/{sample_page.page_id}",
        headers=auth_headers,
        json={"orderIndex": 99},
    )
    assert edit_resp.status_code == 200

    # 3. Propose update using stale hash -- should trigger auto-merge
    propose_resp = await async_client.post(
        "/api/v1/ai/tools/propose_update_page",
        headers=auth_headers,
        json={
            "sessionId": "test-session",
            "versionHash": original_hash,
            "input": {
                "pageId": sample_page.page_id,
                "patch": {
                    "title": "Auto-Merged Title",
                    "components": [],
                },
            },
        },
    )
    assert propose_resp.status_code == 200
    data = propose_resp.json()
    assert data["staleInfo"]["wasStale"] is True
    assert data["staleInfo"]["mergeType"] == "auto_merge"
    assert data["staleInfo"]["conflictCount"] == 0
    assert data["staleInfo"]["versionHashProvided"] == original_hash
    assert data["staleInfo"]["versionHashCurrent"] != original_hash
    assert "proposalId" in data

    # 4. Verify merge audit entry was created
    merge_audit_resp = await async_client.get(
        f"/api/v1/ai/admin/merges?page_id={sample_page.page_id}",
        headers=auth_headers,
    )
    assert merge_audit_resp.status_code == 200
    assert len(merge_audit_resp.json()["merges"]) == 1
    assert merge_audit_resp.json()["merges"][0]["mergeType"] == "auto_merge"
```

**IT-02 -- Conflicting Staleness Rejects Proposal via API:**

Test that when a field is changed in both LOCAL and REMOTE, the proposal is rejected with a structured conflict report.

```python
async def test_conflicting_staleness_rejection(
    async_client, auth_headers, sample_course, sample_page
):
    # 1. Fetch page
    fetch_resp = await async_client.post(
        "/api/v1/ai/tools/fetch_page",
        headers=auth_headers,
        json={"pageId": sample_page.page_id},
    )
    original_hash = fetch_resp.json()["versionHash"]
    page_data = fetch_resp.json()

    # 2. Another session modifies the body component (the same field AI will target)
    # This directly updates the component data via the API
    component_id = page_data["components"][0]["componentId"]
    await async_client.put(
        f"/api/v1/pages/{sample_page.page_id}/components/{component_id}",
        headers=auth_headers,
        json={"data": {"body": "Intervening edit by Bob"}},
    )

    # 3. Propose update with stale hash targeting the same body field
    propose_resp = await async_client.post(
        "/api/v1/ai/tools/propose_update_page",
        headers=auth_headers,
        json={
            "sessionId": "test-session",
            "versionHash": original_hash,
            "input": {
                "pageId": sample_page.page_id,
                "patch": {
                    "components": [
                        {"componentId": component_id, "data": {"body": "AI's proposed body"}}
                    ]
                },
            },
        },
    )
    assert propose_resp.status_code == 409
    error = propose_resp.json()
    assert error["code"] == "STALE_CONFLICT"
    assert len(error["details"]["conflicts"]) >= 1
    assert error["details"]["conflictCount"] >= 1
    assert error["retryable"] is True
    assert error["details"]["forceOverwriteAvailable"] is True

    # 4. Verify merge audit entry was created with conflict_detected type
    merge_audit_resp = await async_client.get(
        f"/api/v1/ai/admin/merges?page_id={sample_page.page_id}",
        headers=auth_headers,
    )
    audits = merge_audit_resp.json()["merges"]
    conflict_audits = [a for a in audits if a["mergeType"] == "conflict_detected"]
    assert len(conflict_audits) >= 1
    assert conflict_audits[0]["conflictCount"] >= 1
```

**IT-03 -- Force Overwrite with User Confirmation:**

Test that a conflicting proposal with `forceOverwrite: true` and `userConfirmed: true` creates the proposal using REMOTE values.

```python
async def test_force_overwrite_with_confirmation(
    async_client, auth_headers, sample_course, sample_page
):
    # 1. Fetch page
    fetch_resp = await async_client.post(
        "/api/v1/ai/tools/fetch_page",
        headers=auth_headers,
        json={"pageId": sample_page.page_id},
    )
    original_hash = fetch_resp.json()["versionHash"]
    component_id = fetch_resp.json()["components"][0]["componentId"]

    # 2. Intervening edit
    await async_client.put(
        f"/api/v1/pages/{sample_page.page_id}/components/{component_id}",
        headers=auth_headers,
        json={"data": {"body": "Bob's intervening edit"}},
    )

    # 3. Force overwrite proposal
    propose_resp = await async_client.post(
        "/api/v1/ai/tools/propose_update_page",
        headers=auth_headers,
        json={
            "sessionId": "test-session",
            "versionHash": original_hash,
            "input": {
                "pageId": sample_page.page_id,
                "patch": {
                    "components": [
                        {"componentId": component_id, "data": {"body": "AI's forced body"}}
                    ]
                },
            },
            "forceOverwrite": True,
            "userConfirmed": True,
        },
    )
    assert propose_resp.status_code == 200
    data = propose_resp.json()
    assert data["staleInfo"]["mergeType"] == "force_overwrite"
    assert data["staleInfo"]["conflictCount"] >= 1
```

**IT-04 -- Apply-Time Double-Check Detects Staleness:**

Test that when a page is modified between proposal creation and apply, the system re-checks staleness and either re-merges or rejects.

```python
async def test_apply_time_staleness_detection(
    async_client, auth_headers, sample_course, sample_page
):
    # 1. Create a proposal (fresh, no staleness)
    fetch_resp = await async_client.post(
        "/api/v1/ai/tools/fetch_page",
        headers=auth_headers,
        json={"pageId": sample_page.page_id},
    )
    current_hash = fetch_resp.json()["versionHash"]

    propose_resp = await async_client.post(
        "/api/v1/ai/tools/propose_update_page",
        headers=auth_headers,
        json={
            "sessionId": "test-session",
            "versionHash": current_hash,
            "input": {
                "pageId": sample_page.page_id,
                "patch": {"title": "Apply-Time Test Title"},
            },
        },
    )
    assert propose_resp.status_code == 200
    proposal_id = propose_resp.json()["proposalId"]
    lock_id = propose_resp.json()["lock"]["lockId"]

    # 2. Release the lock and simulate another session editing
    # Release the WRITE lock to allow the double-check to trigger
    release_resp = await async_client.delete(
        f"/api/v1/ai/locks/{lock_id}",
        headers={**auth_headers, "X-Admin-Override": "true"},
        json={"reason": "Test release", "confirmForceRelease": True},
    )
    # Note: In production, the lock would NOT be explicitly released this way.
    # This is a test shortcut. In reality, the lock expires or is released
    # by the session. The apply-time check runs regardless of lock state.

    # 3. Intervening edit by another session
    await async_client.put(
        f"/api/v1/pages/{sample_page.page_id}",
        headers=auth_headers,
        json={"title": "Intervening Title"},
    )

    # 4. Try to apply the proposal -- should trigger double-check
    apply_resp = await async_client.post(
        "/api/v1/ai/tools/apply_update_proposal",
        headers=auth_headers,
        json={
            "sessionId": "test-session",
            "input": {"proposalId": proposal_id, "userConfirmed": True},
        },
    )

    # The apply may succeed (if re-merge works) or fail (if conflicts)
    # Both are valid outcomes. What matters is the merge audit entry.
    assert apply_resp.status_code in (200, 409)
    if apply_resp.status_code == 200:
        assert apply_resp.json().get("applyTimeMerge", {}).get("wasStale") is True
```

### End-to-End Tests (2+)

**E2E-01 -- User Experiences Auto-Merge with Banner:**

1. Alice opens AI chat for Course C1. The AI fetches page "Introduction" (P42). Version hash "abc123" is returned.
2. Bob (via manual editor) changes the page's order_index from 3 to 4 and saves.
3. Alice types "Update the title to 'Getting Started'." The AI generates a proposal with `versionHash="abc123"` and patch updating title.
4. The backend detects staleness (hash mismatch), computes the three-way merge (order_index changed in LOCAL, title changed in REMOTE -- no conflict), auto-merges, and creates the proposal with merged content.
5. The frontend proposal review panel shows a green banner: "Page was modified while AI was working. Changes were automatically merged." Clicking "View details" shows a popup: "Order index changed by Bob. Title changed by AI. No conflicts."
6. Alice reviews the merged proposal and approves. The page is updated with title "Getting Started" and order_index 4.
7. Alice checks the version history. The version snapshot reflects the merged state.

**E2E-02 -- User Resolves a Staleness Conflict:**

1. Alice opens AI chat for Course C1. The AI fetches page "Quiz" (P123). Version hash "xyz789" is returned. The page has a text component with body "Original question text."
2. Bob (via manual editor) changes the body to "Bob's revised question." Hash becomes "abc000".
3. Alice types "Make the question more challenging." The AI generates a proposal with `versionHash="xyz789"` and patch updating the body to "AI's challenging question."
4. The backend detects a STALE_CONFLICT on field `/components/0/data/body`. It returns a 409 with the structured conflict report.
5. The frontend transitions to the conflict resolution panel showing three columns: "Your AI's changes" (AI's challenging question), "Original" (Original question text), "Current on server" (Bob's revised question). The body field is highlighted in red.
6. The panel shows three action buttons: "Retry" (re-fetch page, AI regenerates), "Overwrite with AI changes" (force overwrite with confirmation dialog), "Cancel" (discard proposal).
7. Alice clicks "Overwrite with AI changes." A confirmation dialog appears: "Warning: Bob made changes to this page while you were editing. Overwriting will discard their changes. They can be recovered from version history. [I understand, overwrite] [Cancel]"
8. Alice checks "I understand" and confirms. The proposal is created with `forceOverwrite: true` and `userConfirmed: true`.
9. The frontend shows the proposal with the overwritten content. Alice approves.
10. Bob navigates to the page and sees Alice's changes. He checks the version history, restores his version from the snapshot, and contacts Alice about the conflict.

### Manual QA Steps

1. **Version Hash Visibility:** Open the browser dev tools. Fetch any page via the AI chat. Verify the response contains a `versionHash` field. Verify the hash is a 64-character hex string (SHA-256).
2. **Staleness Banner Appearance:** In two browser windows as the same user, fetch a page in Window A. Make an edit to the same page in Window B (manual editor). In Window A, propose a change that does NOT touch the fields changed in Window B. Verify the green staleness banner appears with "Changes were merged automatically."
3. **Conflict Panel Layout:** Repeat the above but propose a change that DOES touch the same field. Verify the conflict resolution panel appears with three columns and red highlighting on the conflicting field.
4. **Force Overwrite Confirmation:** In the conflict panel, click "Overwrite with AI changes." Verify the confirmation dialog appears with the correct warning text and that the "I understand" checkbox must be checked before the "Confirm" button is enabled.
5. **Merge Audit in Admin Dashboard:** As admin, navigate to the admin audit dashboard. Filter by operation="merge". Verify merge events appear with correct merge_type, conflict_count, and version hash fields. Click "View Diff" on a conflict_detected entry and verify the three-way diff shows BASE, LOCAL, REMOTE.
6. **Strict Mode Behavior:** As admin, change the merge strategy to "strict." Create a new AI session and attempt to propose on a page that was modified between fetch and propose. Verify the proposal is rejected immediately with STALE_CONFLICT, no merge attempt, and no conflict panel (just a "page was modified, please retry" message).
7. **Apply-Time Staleness:** Create a proposal, then before applying, release the lock (or wait for TTL expiry) and make an intervening edit. Attempt to apply. Verify the system detects the staleness and either auto-re-merges or shows an APPLY_CONFLICT error.
8. **Cross-Organization Isolation:** As Org A admin, attempt to query merge audits for Org B via the API. Verify 404 or empty results.

---

## 7. DEFINITION OF DONE

1. `ai_merge_audit` and `ai_merge_config` tables exist in the database with the correct schema, indexes, and foreign key relationships. All columns on `ai_proposals` (merged_content, merge_type, merge_metadata, conflict_report, staleness_status) are added via Alembic migration.
2. All database migrations are created, reviewed, and applied to staging without errors. Downgrade scripts cleanly revert all changes.
3. `MergeManager` service is fully implemented with methods: `compute_page_hash`, `detect_staleness`, `perform_three_way_merge`, `create_merge_audit_entry`, `get_organization_merge_config`, and `get_merge_strategy_for_session`.
4. `VersionHashRepository` is fully implemented with methods: `compute_page_hash`, `fetch_page_state`, `get_base_state_for_hash`, and `store_version_hash_mapping`. The BASE state retrieval supports multi-source fallback (current state, proposal merged content, version snapshots, audit before-snapshots).
5. `StaleDetectionMiddleware` decorators are implemented: `@with_stale_detection`, `@with_apply_time_stale_check`, and `@with_fetch_version_hash`.
6. All 6 unit tests in Section 6 pass with >90% code coverage for the `merge_manager.py` module.
7. All 4 integration tests in Section 6 pass against a real PostgreSQL database.
8. Both E2E tests in Section 6 are passing in the CI environment.
9. The `fetch_page` endpoint returns `versionHash` in its response. The `propose_update_page` endpoint accepts `versionHash` in its request and performs staleness detection.
10. Auto-merge (STALE_NO_CHANGE and STALE_COMPATIBLE) successfully creates proposals with merged content and returns `staleInfo` in the response.
11. Conflicting staleness (STALE_CONFLICT) is rejected with a structured `STALE_CONFLICT` error response containing field-level conflict details.
12. Force overwrite with `forceOverwrite: true` and `userConfirmed: true` creates proposals even on conflicting staleness, using REMOTE values. Without `userConfirmed: true`, force overwrite is rejected.
13. Apply-time double-check detects staleness between proposal creation and apply. It re-attempts merge and either succeeds transparently or returns `APPLY_CONFLICT`.
14. Merge audit entries are written for every merge operation (auto-merge, conflict detected, force overwrite, apply-time merge). Audit entries are immutable and linked to the proposal and session.
15. Admin merge audit query endpoint (`GET /api/v1/ai/admin/merges`) is implemented with filtering by course, page, merge type, and date range. Pagination is supported.
16. Admin merge config endpoint (`GET/PUT /api/v1/ai/admin/merge-config`) is implemented with per-organization merge strategy configuration.
17. The three merge strategies (auto_merge_safe, strict, permissive) are all implemented and switchable per organization.
18. Frontend staleInfo banner is implemented: shows merge summary on auto-merge, links to merge details.
19. Frontend conflict resolution panel is implemented: three-column view with BASE, LOCAL, REMOTE, highlighted conflicts, and action buttons (Retry, Overwrite, Cancel).
20. Frontend force-overwrite confirmation dialog is implemented with checkbox requirement.
21. Cross-organization isolation is verified: merge data from Org A is invisible to users in Org B.
22. Chat orchestrator (US-AI-023) handles STALE_CONFLICT and APPLY_CONFLICT errors: the AI re-fetches the page and regenerates the proposal when these errors occur.
23. No regression in existing tool functionality: all pre-existing US-AI-* tests still pass.
24. Configuration variables documented in deployment guide with recommended values.
25. Security review completed: version hash trust model (server-authoritative), force-overwrite confirmation enforcement, merge audit immutability, cross-org data isolation.

---

## 8. TASKS AND SUB-TASKS

| Task ID | Task Description | Estimated Effort | Dependencies | Assigned To |
|---|---|---|---|---|
| T-050-01 | **Create database tables, columns, and migration** -- Write Alembic migration for `ai_merge_audit` and `ai_merge_config` tables. ALTER `ai_proposals` to add `merged_content` (JSONB), `merge_type` (VARCHAR 32), `merge_metadata` (JSONB), `conflict_report` (JSONB), `staleness_status` (VARCHAR 32) columns. Apply and verify upgrade/downgrade. | 4 hours | US-AI-043 (ai_proposals and ai_locks tables exist), US-AI-010 (proposal lifecycle patterns) | Backend Engineer |
| T-050-02 | **Implement VersionHashRepository** -- Write `app/services/ai/version_hash_repository.py` with deterministic hash computation, canonical page state serialization, BASE state retrieval with multi-source fallback (current state -> proposal merged content -> version snapshots -> audit before-snapshots), and hash-to-state mapping storage. Include error handling for hash not found scenarios. | 8 hours | T-050-01, US-AI-040 (version snapshots for BASE retrieval) | Backend Engineer |
| T-050-03 | **Implement MergeManager service (core engine)** -- Write `app/services/ai/merge_manager.py` with three-way merge engine. Implement field-level diff computation (recursive dict comparison producing JSON Pointer paths), staleness severity classification (FRESH, STALE_NO_CHANGE, STALE_COMPATIBLE, STALE_CONFLICT), auto-merge for non-conflicting changes, structured conflict report generation, permissive merge (REMOTE wins), force-overwrite logic, merge audit entry creation, and organization merge strategy resolution. All three strategies (auto_merge_safe, strict, permissive) must be fully implemented. | 16 hours | T-050-02 | Backend Engineer |
| T-050-04 | **Implement stale detection middleware/decorators** -- Write `app/services/ai/stale_detection_middleware.py` with three decorators: `@with_stale_detection` (for propose_* handlers -- integrates with lock acquisition, calls MergeManager, rewrites input patch on auto-merge), `@with_apply_time_stale_check` (for apply handlers -- re-verifies hash, re-merges if needed), and `@with_fetch_version_hash` (for fetch handlers -- computes and injects version_hash into response). Ensure proper integration ordering: lock first, then stale check. | 6 hours | T-050-03, US-AI-043 (lock middleware/decorators) | Backend Engineer |
| T-050-05 | **Integrate stale detection into propose_* handlers** -- Modify `propose_update_page` to accept `versionHash` in request, apply `@with_stale_detection` decorator, return `staleInfo` block in success responses, return `STALE_CONFLICT` error with conflict report on conflicts. Modify `propose_delete_page` to verify page still exists and hash matches. Modify `propose_create_page` to add title-uniqueness staleness check. Return `FORCE_OVERWRITE_REQUIRES_CONFIRMATION` error when forceOverwrite is sent without userConfirmed. | 8 hours | T-050-04, US-AI-012, US-AI-013 | Backend Engineer |
| T-050-06 | **Integrate apply-time double-check into apply handlers** -- Modify `apply_update_proposal`, `apply_page_proposal`, and `confirm_delete_page` to apply `@with_apply_time_stale_check` decorator. The double-check re-verifies `base_version_hash` against current page hash. On mismatch, it re-attempts the three-way merge. On success, it transparently updates proposal content and proceeds. On failure, it returns `APPLY_CONFLICT` error with conflict report. | 6 hours | T-050-04, US-AI-010 (apply safety pipeline) | Backend Engineer |
| T-050-07 | **Modify fetch_page to return version_hash** -- Modify `fetch_page` handler to compute and return `versionHash` in the response using `@with_fetch_version_hash`. The hash is computed server-side from the current page and component data. Also update `list_pages` and `fetch_course_structure` to include version_hash for each page if feasible (or at minimum the course-level hash). | 3 hours | T-050-02, US-AI-007 (page fetch tools) | Backend Engineer |
| T-050-08 | **Implement admin merge audit and config API routes** -- Implement `GET /api/v1/ai/admin/merges` with filtering (course_id, page_id, merge_type, date_from, date_to) and cursor pagination. Implement `GET /api/v1/ai/admin/merge-config` and `PUT /api/v1/ai/admin/merge-config` for per-organization merge strategy configuration. Add admin role validation and audit logging for config changes. | 6 hours | T-050-01, T-050-03 | Backend Engineer |
| T-050-09 | **Implement merge audit event outbox** -- Emit merge-related events (`MergeAutoApplied`, `MergeConflictDetected`, `MergeForceOverwritten`, `ApplyTimeMergeApplied`) to the event outbox (US-AI-033) for downstream consumers (notifications, analytics, webhooks). Ensure events are written in the same database transaction as the merge audit entry. | 3 hours | T-050-03, US-AI-033 (event outbox) | Backend Engineer |
| T-050-10 | **Write unit tests** -- Write 8+ unit tests covering: version hash determinism (UT-01), staleness severity classification (UT-02), auto-merge no conflicts (UT-03), conflict detection and rejection (UT-04), permissive strategy remote-wins (UT-05), force overwrite confirmation requirement (UT-06), nested object field diff computation, edge cases (empty page, null fields, deeply nested structures, very large component lists), BASE state retrieval fallback behavior, and merge strategy resolution for different organization configs. | 8 hours | T-050-03, T-050-04 | QA Engineer |
| T-050-11 | **Write integration tests** -- Write 5+ integration tests covering: full auto-merge lifecycle via API (IT-01), conflicting staleness rejection (IT-02), force overwrite with confirmation (IT-03), apply-time staleness detection (IT-04), merge audit endpoint querying and filtering, strict mode rejection, and merge config CRUD. Tests must run against a real PostgreSQL database with seeded test data. | 8 hours | T-050-05 through T-050-08 | QA Engineer |
| T-050-12 | **Write E2E tests** -- Write 2+ E2E tests covering: user experiences auto-merge with banner (E2E-01), user resolves staleness conflict via conflict panel (E2E-02). Tests use a browser automation framework (Playwright or Cypress) and verify both UI behavior and API responses. | 8 hours | T-050-05 through T-050-08, frontend implementation | QA Engineer |
| T-050-13 | **Implement frontend stale detection UI components** -- Implement staleInfo banner component (displays merge summary, "View details" link, green/yellow/red color coding for merge type). Implement merge details popover (shows which fields came from local vs remote). Wire version_hash into the frontend page store and pass it to proposal requests. | 8 hours | T-050-05, US-AI-024 (frontend AI integration layer) | Frontend Engineer |
| T-050-14 | **Implement frontend conflict resolution panel** -- Build three-column conflict resolution view: left panel (REMOTE / AI's changes), center panel (BASE / original), right panel (LOCAL / current on server). Implement field-level highlighting: red for conflicting fields, green for non-conflicting auto-merged fields. Implement action buttons: "Retry" (re-fetch, re-propose), "Overwrite with AI changes" (with confirmation dialog), "Cancel" (discard). Implement confirmation dialog with checkbox requirement for force overwrite. | 12 hours | T-050-13 | Frontend Engineer |
| T-050-15 | **Integrate STALE_CONFLICT handling into chat orchestrator** -- Modify the AI chat loop (US-AI-023) to handle STALE_CONFLICT and APPLY_CONFLICT errors: when these errors are received, the orchestrator automatically calls `fetch_page` to get the current state, presents the state diff to the LLM, and allows the LLM to regenerate the proposal incorporating the current state. This ensures the AI can self-correct without manual retry in most cases. | 6 hours | T-050-05, T-050-06, US-AI-023 (chat orchestrator) | Backend Engineer |
| T-050-16 | **Performance and load testing** -- Run load test with 100 concurrent AI sessions, each performing fetch-propose-apply cycles that trigger staleness detection (50% fresh, 30% auto-merge, 20% conflict). Measure p50/p95/p99 latency for: version hash computation, staleness detection (hash compare), auto-merge (non-conflicting), conflict report generation (conflicting). Verify that version hash computation stays under 10ms p95. Verify that the merge path does not degrade non-stale path performance. | 6 hours | T-050-03 through T-050-06 | QA Engineer |
| T-050-17 | **Security review and documentation** -- Review version hash trust model (confirm server-authoritative hash computation). Verify force-overwrite confirmation enforcement cannot be bypassed by API calls without frontend interaction. Verify cross-org isolation on merge audit and merge config endpoints. Document merge configuration variables in deployment guide. Document the three merge strategies with use-case guidance. Document the merge conflict resolution flow for end-users. | 4 hours | All above tasks | Security Engineer |
| T-050-18 | **Regression test suite** -- Run full AI authoring regression suite with merge system enabled. Verify that existing US-AI-001 through US-AI-049 tests still pass. Pay special attention to: apply service flow (staleness check should not affect fresh proposals), lock manager flow (staleness check should not interfere with lock acquisition/release), version snapshot creation (merge should not change snapshot behavior), and session lifecycle (staleness events should not affect session teardown). | 4 hours | All above tasks | QA Engineer |
