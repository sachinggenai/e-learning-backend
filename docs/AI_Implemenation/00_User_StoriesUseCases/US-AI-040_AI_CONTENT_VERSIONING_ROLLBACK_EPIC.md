# US-AI-040: AI Content Versioning and Rollback

**As an** Admin, **I want** AI-authored changes to be versioned with rollback capability, **so that** problematic AI-generated content can be reverted without manual reconstruction, and full change history is preserved for audit and recovery.

- **Priority:** COULD for MVP, SHOULD for production
- **Depends on:** US-AI-010 (Apply Safety, Audit, and Outbox), US-AI-020 (Admin Audit, Compliance, and Recovery Views)
- **Unlocks:** US-AI-042 (System Prompt Versioning and A/B Testing), point-in-time audit recovery
- **Source flows:** 28. AI Content Versioning and Rollback
- **Epic Owner:** Technical Product Owner
- **Story Points:** 29 SP

---

## 1. Functional Specification

### 1.1 Course Version Snapshots

**Goal:** Every applied AI mutation creates a recoverable version snapshot so the full course state can be reconstructed at any point in time.

**Core Functional Requirements:**

1. **FR-VER-01 (Snapshot on Every Apply):** Every successful AI apply (create/update/delete page, batch apply, course-level operation) captures a full-course snapshot of `PageRecord`, `ComponentRecord`, and `CourseRecord` state into the version store before and after the mutation. This is distinct from (and in addition to) the `before_snapshot`/`after_snapshot` stored in `ai_audit_logs` — version snapshots are full course-level point-in-time captures, not just page-level.

2. **FR-VER-02 (Version Metadata):** Each version records: `version_id`, `course_id`, `version_number` (monotonically increasing per course), `created_at`, `created_by` (user ID), `source` (e.g., `"ai:proposal:<proposal_id>"`, `"manual:save"`, `"rollback:<audit_id>"`), `summary` (human-readable change description), `snapshot_hash` (SHA-256 of the serialized course state for integrity verification), and `parent_version_id` (for linear chain tracking).

3. **FR-VER-03 (Version Listing):** Admins and authors can list all versions for a course in descending chronological order with metadata summary. The list shows `version_number`, `summary`, `created_at`, `created_by`, `source`, and `page_count`.

4. **FR-VER-04 (Version Comparison):** Admins can compare any two versions and receive a structured diff showing: pages added/removed/reordered, per-page component changes, metadata changes, and a summary of what changed (number of pages changed, components changed, fields changed).

5. **FR-VER-05 (Version Labeling):** Authors can assign a human-readable label (e.g., `"v1.0-launch"`, `"pre-review-draft"`) to any version for easy identification. Labels must be unique per course. Maximum label length of 100 characters.

6. **FR-VER-06 (Point-in-Time Restore):** Admins can restore a course to any previous version. Restore creates a new version (the restored state) and follows the standard proposal safety pipeline — the restored-to version becomes the `before_snapshot` target, a restoration proposal is created, validated, and must be explicitly confirmed before apply.

### 1.2 Version Diff and Comparison UI Support

**Goal:** The version diff endpoint returns machine-readable output that the frontend can render as a side-by-side comparison.

**Core Functional Requirements:**

1. **FR-DIFF-01 (Structured Diff Output):** The diff endpoint returns a JSON structure with three top-level sections: `metadata` (course-level field changes), `pages` (added, removed, reordered, changed), and `summary` (aggregate counts).

2. **FR-DIFF-02 (Page-Level Detail):** For each changed page, the diff includes: `page_id`, `page_title` (before and after), `change_type` (`added`/`removed`/`modified`/`reordered`), `order_before`/`order_after`, and `components` (list of component-level changes with `component_id`, `change_type`, and `field_changes` as JSON Patch operations).

3. **FR-DIFF-03 (Component-Level Detail):** For each changed component, the diff includes: `component_id`, `component_type`, `change_type`, and `field_changes` (RFC 6902 JSON Patch array of operations on the component data).

4. **FR-DIFF-04 (Metadata Diff):** Course-level metadata changes (title, description, settings, navigation, theme) are returned as JSON Patch operations in the `metadata` section.

5. **FR-DIFF-05 (Forward and Reverse):** The diff endpoint accepts two version IDs and computes the diff from `version_a` to `version_b`. The frontend can request forward or reverse diffs to support left/right panel comparison.

### 1.3 Rollback via Version Restore (Enhanced over US-AI-020)

**Goal:** Version-based rollback extends the audit-based rollback from US-AI-020 with full-course point-in-time restore, not just page-level before-snapshot restoration.

**Core Functional Requirements:**

1. **FR-RESTORE-01 (Full-Course Restore):** Restoring a version replaces ALL course pages and components with the state from the target version. This is a destructive operation for any changes made since the target version — the system MUST warn the user of exactly what will be lost.

2. **FR-RESTORE-02 (Page-Level Restore):** In addition to full-course restore, admins can restore a single page from a previous version. The page data is extracted from the target version snapshot and proposed as an update to the current version.

3. **FR-RESTORE-03 (Restore Preview):** Before confirming a restore, the system shows a preview of what will change: pages to be added, removed, modified, and a list of pages that will be completely unaffected. This is computed as a diff between the current version and the target version.

4. **FR-RESTORE-04 (Restore Proposal):** Restore follows the standard proposal lifecycle (US-AI-009): a restore proposal is created with the target version state as the `after_candidate`, the current state as `before_snapshot`, and validation is run. Proposal type is `"restore"`. The proposal includes a `restore_type` field (`"full_course"` or `"single_page"`) and a `target_version_id`.

5. **FR-RESTORE-05 (Restore Audit Trail):** Restore operations are recorded in the audit log with `operation="rollback"` and a `rollback_of` field linking to the target version's creating audit entry (if available). The restore also creates a new version snapshot with `source="restore:<proposal_id>"`.

### 1.4 Version Storage Optimization

**Goal:** Version snapshots are stored efficiently to avoid unbounded storage growth.

**Core Functional Requirements:**

1. **FR-STOR-01 (Differential Snapshots):** After the first full snapshot, subsequent snapshots store only the diff (JSON Patch) from the previous version. Full snapshots are taken every N versions (configurable, default 10) or when cumulative diff size exceeds a threshold (configurable, default 5 MB).

2. **FR-STOR-02 (Rehydration):** The system can rehydrate a full course state for any version by applying the chain of diffs from the nearest full snapshot forward. Rehydration must complete in under 3 seconds for courses with up to 500 pages.

3. **FR-STOR-03 (Retention Policy):** Versions older than a configurable retention period (default 90 days) are candidates for archival. Archival moves the snapshot data to a compressed JSONB column or external storage. The version metadata (list entry) is always retained.

4. **FR-STOR-04 (Manual Pruning):** Admins can manually delete specific versions (except the current version). Deletion removes the snapshot data but retains the metadata entry marked as `"pruned"`.

### 1.5 Edge Cases and Error Handling

| Scenario | Expected Behavior |
|---|---|
| Restore target version has been pruned | Restore proposal creation fails with `410 Gone` and a message that the snapshot data has been archived. Admin can restore from archive if configured. |
| Concurrent edit happens between restore preview and confirm | Apply-time conflict detection catches the base hash mismatch. User is shown the conflict and must re-evaluate. Standard proposal staleness handling applies (US-AI-009). |
| Version chain has a gap (pruned intermediate version) | Rehydration skips pruned versions and works from the nearest full snapshot before the gap. If all full snapshots before the target are pruned, restore fails with `422` and suggests manual recovery. |
| Rollback of a restoration | Supported. Full-course restore creates a new version; rolling back that version restores the state before the restore. Each rollback records `rollback_of` linking to the previous mutation. |
| Course has no versions (pre-migration) | The first apply after migration triggers a full initial snapshot. Manual saves via the editor also trigger snapshots if versioning is enabled. |
| Version diff between two snapshots with different schema versions | Diff computation warns about schema version mismatch and performs a best-effort field-level comparison. Incompatible fields are listed as `"schema_changed"` with before/after raw values. |
| Storage quota exceeded | Version creation fails with `507 Insufficient Storage`. Admin must prune old versions or increase storage quota. Current version and the most recent N versions are protected from auto-prune. |

---

## 2. Technical Specification

### 2.1 Database Schema (PostgreSQL DDL)

#### 2.1.1 `ai_version_snapshots` Table

Stores version metadata and the actual course state snapshot.

```sql
CREATE TABLE IF NOT EXISTS ai_version_snapshots (
    id               BIGSERIAL PRIMARY KEY,
    version_id       VARCHAR(64) NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,

    -- Course context
    course_id        VARCHAR(64) NOT NULL,
    version_number   INTEGER NOT NULL,  -- Monotonically increasing per course

    -- Source & authorship
    source           VARCHAR(32) NOT NULL CHECK (source IN (
                         'ai:proposal', 'manual:save', 'rollback',
                         'restore', 'import', 'system:migration'
                     )),
    source_id        VARCHAR(128),  -- proposal_id, audit_id, or import_job_id
    created_by       VARCHAR(128) NOT NULL DEFAULT 'system',
    summary          TEXT NOT NULL DEFAULT '',

    -- Label (optional, user-assignable, unique per course)
    label            VARCHAR(100),

    -- Parent version for chain tracking
    parent_version_id VARCHAR(64),

    -- Snapshot storage strategy
    storage_strategy VARCHAR(16) NOT NULL DEFAULT 'full'
                         CHECK (storage_strategy IN ('full', 'diff')),
    -- 'full'  → snapshot_json contains the complete course state
    -- 'diff'  → snapshot_json contains JSON Patch from parent_version

    -- The actual snapshot data
    snapshot_json    JSONB NOT NULL,  -- Full state or diff depending on strategy

    -- Integrity
    snapshot_hash    VARCHAR(64) NOT NULL,  -- SHA-256 of the reified full state

    -- Schema versioning
    schema_version   VARCHAR(16) NOT NULL DEFAULT '1.0',

    -- Retention
    is_archived      BOOLEAN NOT NULL DEFAULT FALSE,
    archived_at      TIMESTAMPTZ,

    -- Timestamps
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_version_parent FOREIGN KEY (parent_version_id)
        REFERENCES ai_version_snapshots(version_id) ON DELETE SET NULL,
    CONSTRAINT uq_version_course_number UNIQUE (course_id, version_number),
    CONSTRAINT uq_version_course_label UNIQUE (course_id, label)
);

-- Core indexes
CREATE INDEX idx_version_course_id ON ai_version_snapshots(course_id);
CREATE INDEX idx_version_created_at ON ai_version_snapshots(created_at DESC);
CREATE INDEX idx_version_course_number ON ai_version_snapshots(course_id, version_number DESC);
CREATE INDEX idx_version_parent ON ai_version_snapshots(parent_version_id);
CREATE INDEX idx_version_source ON ai_version_snapshots(source);
CREATE INDEX idx_version_archived ON ai_version_snapshots(is_archived) WHERE is_archived = FALSE;

-- GIN index for searching inside snapshot JSONB (e.g., page titles)
CREATE INDEX idx_version_snapshot_gin ON ai_version_snapshots USING GIN (snapshot_json jsonb_path_ops);
```

#### 2.1.2 Storage Quota Tracking Table

```sql
CREATE TABLE IF NOT EXISTS ai_version_quotas (
    id               BIGSERIAL PRIMARY KEY,
    course_id        VARCHAR(64) NOT NULL UNIQUE,

    -- Quota limits
    max_versions     INTEGER NOT NULL DEFAULT 100,
    max_storage_mb   INTEGER NOT NULL DEFAULT 512,

    -- Current usage (updated by trigger or application)
    current_versions  INTEGER NOT NULL DEFAULT 0,
    current_storage_bytes BIGINT NOT NULL DEFAULT 0,

    -- Protected window: keep at least these many recent versions from auto-prune
    protected_count   INTEGER NOT NULL DEFAULT 10,

    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_quota_course ON ai_version_quotas(course_id);
```

#### 2.1.3 Version Rehydration Cache Table (Performance)

```sql
CREATE TABLE IF NOT EXISTS ai_version_rehydration_cache (
    id               BIGSERIAL PRIMARY KEY,
    version_id       VARCHAR(64) NOT NULL UNIQUE,

    -- Fully rehydrated course state (cached after first rehydration)
    reified_json     JSONB NOT NULL,

    -- Cache metadata
    reified_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reification_ms   INTEGER NOT NULL,  -- How long it took to build
    is_stale         BOOLEAN NOT NULL DEFAULT FALSE,

    CONSTRAINT fk_cache_version FOREIGN KEY (version_id)
        REFERENCES ai_version_snapshots(version_id) ON DELETE CASCADE
);

CREATE INDEX idx_cache_version ON ai_version_rehydration_cache(version_id);
CREATE INDEX idx_cache_stale ON ai_version_rehydration_cache(is_stale) WHERE is_stale = FALSE;
```

### 2.2 ORM Models

**File:** `app/models/ai_versioning.py`

```python
"""ORM models for AI content versioning and rollback.

Stores course-level snapshots, differential state, and rehydration cache.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import (
    String, DateTime, JSONB, Text, BigInteger, Integer,
    Boolean, ForeignKey, CheckConstraint, Index, UniqueConstraint, LargeBinary
)

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class AIVersionSnapshot(Base):
    """Immutable version snapshot of a course state.

    Stores either a full copy or a differential patch relative to the
    parent version.  Full snapshots are taken periodically; diffs fill
    the gap versions.
    """

    __tablename__ = "ai_version_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    version_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    course_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="system")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    label: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    parent_version_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    storage_strategy: Mapped[str] = mapped_column(
        String(16), nullable=False, default="full"
    )
    snapshot_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "source IN ('ai:proposal','manual:save','rollback',"
            "'restore','import','system:migration')",
            name="ck_version_source",
        ),
        CheckConstraint(
            "storage_strategy IN ('full', 'diff')",
            name="ck_version_storage_strategy",
        ),
        UniqueConstraint("course_id", "version_number", name="uq_version_course_number"),
        UniqueConstraint("course_id", "label", name="uq_version_course_label"),
        Index("idx_version_course_number", "course_id", "version_number"),
        Index("idx_version_created_at", "created_at"),
        Index("idx_version_archived", "is_archived"),
    )

    def to_dict(self) -> dict:
        return {
            "versionId": self.version_id,
            "courseId": self.course_id,
            "versionNumber": self.version_number,
            "source": self.source,
            "sourceId": self.source_id,
            "createdBy": self.created_by,
            "summary": self.summary,
            "label": self.label,
            "parentVersionId": self.parent_version_id,
            "storageStrategy": self.storage_strategy,
            "snapshotHash": self.snapshot_hash,
            "schemaVersion": self.schema_version,
            "isArchived": self.is_archived,
            "archivedAt": self.archived_at.isoformat() if self.archived_at else None,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class AIVersionQuota(Base):
    """Per-course version storage quota and usage tracking."""

    __tablename__ = "ai_version_quotas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    course_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    max_versions: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    max_storage_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=512)
    current_versions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_storage_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    protected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "courseId": self.course_id,
            "maxVersions": self.max_versions,
            "maxStorageMb": self.max_storage_mb,
            "currentVersions": self.current_versions,
            "currentStorageBytes": self.current_storage_bytes,
            "protectedCount": self.protected_count,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


class AIVersionRehydrationCache(Base):
    """Cached fully-reified course state for a version.

    Populated on first read to avoid re-applying the diff chain on every
    version comparison or restore preview request.  Invalidated when a new
    version is created (the cache entry for the new version is built on
    first access, not eagerly).
    """

    __tablename__ = "ai_version_rehydration_cache"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    version_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    reified_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    reified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    reification_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("idx_cache_version", "version_id"),
        Index("idx_cache_stale", "is_stale"),
    )
```

### 2.3 Pydantic Request/Response Models

**File:** `app/models/ai_versioning_dto.py`

```python
"""Pydantic DTOs for AI versioning and rollback API surfaces."""
from __future__ import annotations
from datetime import datetime
from typing import Optional, List, Literal

from pydantic import BaseModel, Field


# ── Version List / Metadata ─────────────────────────────────────────────────

class VersionOut(BaseModel):
    """Single version entry in list responses (no snapshot data)."""
    versionId: str
    courseId: str
    versionNumber: int
    source: str
    sourceId: Optional[str] = None
    createdBy: str
    summary: str
    label: Optional[str] = None
    parentVersionId: Optional[str] = None
    storageStrategy: str
    snapshotHash: str
    schemaVersion: str
    isArchived: bool
    archivedAt: Optional[str] = None
    createdAt: str

    model_config = {"from_attributes": True}


class VersionListOut(BaseModel):
    """Paginated version list response."""
    items: List[VersionOut]
    total: int
    nextCursor: Optional[str] = None
    hasMore: bool


# ── Version Detail (includes snapshot summary, not full data) ───────────────

class VersionDetailOut(BaseModel):
    """Full version detail with snapshot size info and page count."""
    versionId: str
    courseId: str
    versionNumber: int
    source: str
    sourceId: Optional[str] = None
    createdBy: str
    summary: str
    label: Optional[str] = None
    parentVersionId: Optional[str] = None
    storageStrategy: str
    snapshotHash: str
    schemaVersion: str
    snapshotSizeBytes: int = 0
    reifiedPageCount: int = 0
    reifiedComponentCount: int = 0
    isArchived: bool
    createdAt: str

    model_config = {"from_attributes": True}


# ── Version Labeling ────────────────────────────────────────────────────────

class VersionLabelRequest(BaseModel):
    label: Optional[str] = Field(
        None, max_length=100,
        description="Human-readable label. Set to null to remove."
    )


class VersionLabelOut(BaseModel):
    versionId: str
    label: Optional[str] = None
    updatedAt: str


# ── Version Comparison / Diff ────────────────────────────────────────────────

class DiffFieldChange(BaseModel):
    """A single field-level change within a component."""
    field: str
    changeType: Literal["added", "removed", "modified"]
    before: Optional[object] = None
    after: Optional[object] = None
    jsonPatch: Optional[list] = None  # RFC 6902 operations


class DiffComponent(BaseModel):
    """Component-level change entry."""
    componentId: str
    componentType: str
    changeType: Literal["added", "removed", "modified"]
    before: Optional[dict] = None
    after: Optional[dict] = None
    fieldChanges: List[DiffFieldChange] = Field(default_factory=list)


class DiffPage(BaseModel):
    """Page-level change entry."""
    pageId: str
    titleBefore: Optional[str] = None
    titleAfter: Optional[str] = None
    changeType: Literal["added", "removed", "modified", "reordered"]
    orderBefore: Optional[int] = None
    orderAfter: Optional[int] = None
    components: List[DiffComponent] = Field(default_factory=list)


class DiffMetadata(BaseModel):
    """Course-level metadata changes."""
    titleBefore: Optional[str] = None
    titleAfter: Optional[str] = None
    descriptionBefore: Optional[str] = None
    descriptionAfter: Optional[str] = None
    settingsBefore: Optional[dict] = None
    settingsAfter: Optional[dict] = None
    navigationBefore: Optional[dict] = None
    navigationAfter: Optional[dict] = None
    themeBefore: Optional[dict] = None
    themeAfter: Optional[dict] = None
    jsonPatch: list = Field(default_factory=list)  # RFC 6902 for metadata


class VersionDiffOut(BaseModel):
    """Structured diff between two versions."""
    fromVersionId: str
    toVersionId: str
    metadata: DiffMetadata
    pages: List[DiffPage]
    summary: dict = Field(
        default_factory=lambda: {
            "pagesAdded": 0,
            "pagesRemoved": 0,
            "pagesModified": 0,
            "pagesReordered": 0,
            "componentsChanged": 0,
            "metadataChanged": False,
            "totalChanges": 0,
        }
    )
    schemaVersionBefore: str
    schemaVersionAfter: str
    computedAt: str


# ── Restore Proposals ────────────────────────────────────────────────────────

class RestoreProposalRequest(BaseModel):
    version_id: str = Field(..., description="Target version to restore to")
    restore_type: Literal["full_course", "single_page"] = Field(
        default="full_course"
    )
    page_id: Optional[str] = Field(
        None, description="Required when restore_type=single_page"
    )
    reason: str = Field(
        ..., min_length=10, max_length=2000,
        description="Reason for the restore (recorded in audit)"
    )


class RestorePreviewOut(BaseModel):
    """Preview of what will change during a restore."""
    targetVersionId: str
    targetVersionNumber: int
    currentVersionId: str
    currentVersionNumber: int
    pagesToAdd: List[dict] = Field(
        default_factory=list,
        description="Pages that exist in target but not in current"
    )
    pagesToRemove: List[dict] = Field(
        default_factory=list,
        description="Pages that exist in current but not in target"
    )
    pagesToModify: List[dict] = Field(
        default_factory=list,
        description="Pages that differ between versions"
    )
    unaffectedPageCount: int = 0
    metadataChanged: bool = False
    destructiveWarning: Optional[str] = Field(
        None,
        description="Warning message if restore will remove data"
    )
    estimatedAffectedPages: int = 0


class RestoreProposalOut(BaseModel):
    """Response after creating a restore proposal."""
    proposalId: str
    proposalType: str = Field(default="restore")
    restoreType: str
    targetVersionId: str
    restorePreview: RestorePreviewOut
    summary: str
    expiresAt: str


# ── Storage Quota ────────────────────────────────────────────────────────────

class VersionQuotaOut(BaseModel):
    courseId: str
    maxVersions: int
    maxStorageMb: int
    currentVersions: int
    currentStorageBytes: int
    protectedCount: int
    usagePercent: float  # computed: currentVersions / maxVersions * 100
    storageUsagePercent: float  # computed: currentStorageBytes / (maxStorageMb * 1048576) * 100
    updatedAt: str

    model_config = {"from_attributes": True}


class VersionQuotaUpdateRequest(BaseModel):
    max_versions: Optional[int] = Field(None, ge=10, le=10000)
    max_storage_mb: Optional[int] = Field(None, ge=64, le=10240)
    protected_count: Optional[int] = Field(None, ge=1, le=100)


# ── Manual Pruning ───────────────────────────────────────────────────────────

class VersionPruneRequest(BaseModel):
    version_ids: List[str] = Field(
        ..., min_length=1, max_length=100,
        description="Version IDs to prune (snapshot data removed, metadata retained)"
    )


class VersionPruneOut(BaseModel):
    prunedCount: int
    freedStorageBytes: int
    remainingVersions: int
    message: str


# ── Version Create (internal, used by service layer) ─────────────────────────

class VersionCreateRequest(BaseModel):
    """Internal DTO for creating a new version snapshot.

    Not exposed via API — called by the apply service after mutations.
    """
    course_id: str
    source: str
    source_id: Optional[str] = None
    created_by: str = "system"
    summary: str = ""
    snapshot_json: dict
    snapshot_hash: str
    parent_version_id: Optional[str] = None
    storage_strategy: Literal["full", "diff"] = "full"
    schema_version: str = "1.0"
```

### 2.4 API Contracts

All routes are under the `/api/v1/ai` prefix. Versioning routes use the `admin` or `courses` sub-prefix depending on access level.

#### `GET /api/v1/ai/admin/courses/{course_id}/versions`

List versions for a course (admin view, includes archived/pruned metadata).

**Query Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `include_archived` | boolean | No | Include archived versions (default false) |
| `label_filter` | string | No | Filter by label prefix |
| `source_filter` | string | No | Filter by source type |
| `date_from` | ISO8601 | No | Start of date range |
| `date_to` | ISO8601 | No | End of date range |
| `limit` | integer | No | Page size (1-200, default 50) |
| `cursor` | string | No | Opaque cursor for pagination |

**Response `200 OK`:**
```json
{
  "items": [
    {
      "versionId": "ver-a1b2c3d4",
      "courseId": "course-alpha",
      "versionNumber": 42,
      "source": "ai:proposal",
      "sourceId": "prop-007",
      "createdBy": "user-42",
      "summary": "AI updated page 'Introduction to Algebra' content",
      "label": "pre-review-draft",
      "parentVersionId": "ver-9z8y7x6w",
      "storageStrategy": "diff",
      "snapshotHash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "schemaVersion": "1.0",
      "isArchived": false,
      "archivedAt": null,
      "createdAt": "2026-06-14T10:30:00+00:00"
    }
  ],
  "total": 42,
  "nextCursor": "eyJ2ZXJzaW9uX251bWJlciI6IDMwfQ==",
  "hasMore": true
}
```

**Error Responses:**
- `404` — Course not found
- `422` — Invalid filter parameter

#### `GET /api/v1/ai/admin/courses/{course_id}/versions/{version_id}`

Get full version detail with snapshot metadata (not the raw snapshot data).

**Response `200 OK`:**
```json
{
  "versionId": "ver-a1b2c3d4",
  "courseId": "course-alpha",
  "versionNumber": 42,
  "source": "ai:proposal",
  "sourceId": "prop-007",
  "createdBy": "user-42",
  "summary": "AI updated page 'Introduction to Algebra' content",
  "label": "pre-review-draft",
  "parentVersionId": "ver-9z8y7x6w",
  "storageStrategy": "diff",
  "snapshotHash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "schemaVersion": "1.0",
  "snapshotSizeBytes": 15234,
  "reifiedPageCount": 12,
  "reifiedComponentCount": 48,
  "isArchived": false,
  "createdAt": "2026-06-14T10:30:00+00:00"
}
```

**Error Responses:**
- `404` — Version not found

#### `GET /api/v1/ai/admin/courses/{course_id}/versions/{version_id}/diff?compare_to={other_version_id}`

Compute a structured diff between two versions. If `compare_to` is omitted, compares with the previous version (version_number - 1).

**Query Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `compare_to` | string | No | Version ID to compare against. Defaults to previous version |

**Response `200 OK`:**
```json
{
  "fromVersionId": "ver-9z8y7x6w",
  "toVersionId": "ver-a1b2c3d4",
  "metadata": {
    "titleBefore": "Algebra Course",
    "titleAfter": "Algebra Course",
    "settingsBefore": {"theme": "default"},
    "settingsAfter": {"theme": "dark"},
    "jsonPatch": [
      {"op": "replace", "path": "/settings/theme", "value": "dark"}
    ]
  },
  "pages": [
    {
      "pageId": "page-005",
      "titleBefore": "Introduction to Algebra",
      "titleAfter": "Introduction to Algebra (Revised)",
      "changeType": "modified",
      "orderBefore": 3,
      "orderAfter": 3,
      "components": [
        {
          "componentId": "comp-001",
          "componentType": "content-text",
          "changeType": "modified",
          "fieldChanges": [
            {
              "field": "data.body",
              "changeType": "modified",
              "before": "<p>Original text</p>",
              "after": "<p>Revised text</p>",
              "jsonPatch": [
                {"op": "replace", "path": "/data/body", "value": "<p>Revised text</p>"}
              ]
            }
          ]
        }
      ]
    },
    {
      "pageId": "page-012",
      "titleBefore": null,
      "titleAfter": "New Quiz Page",
      "changeType": "added",
      "orderBefore": null,
      "orderAfter": 7,
      "components": []
    }
  ],
  "summary": {
    "pagesAdded": 1,
    "pagesRemoved": 0,
    "pagesModified": 1,
    "pagesReordered": 0,
    "componentsChanged": 1,
    "metadataChanged": true,
    "totalChanges": 3
  },
  "schemaVersionBefore": "1.0",
  "schemaVersionAfter": "1.0",
  "computedAt": "2026-06-14T10:35:00+00:00"
}
```

**Error Responses:**
- `404` — Either version not found
- `422` — Versions belong to different courses; version chain gap prevents rehydration

#### `PUT /api/v1/ai/admin/courses/{course_id}/versions/{version_id}/label`

Set or remove a human-readable label on a version.

**Request Body:**
```json
{
  "label": "v1.0-launch-candidate"
}
```

Set to `null` to remove the label.

**Response `200 OK`:**
```json
{
  "versionId": "ver-a1b2c3d4",
  "label": "v1.0-launch-candidate",
  "updatedAt": "2026-06-14T11:00:00+00:00"
}
```

**Error Responses:**
- `404` — Version not found
- `409` — Label already exists for this course

#### `POST /api/v1/ai/admin/courses/{course_id}/restore/preview`

Preview what a restore operation would change. Does not create a proposal.

**Request Body:**
```json
{
  "version_id": "ver-a1b2c3d4",
  "restore_type": "full_course",
  "reason": "Rolling back to before the AI-generated quiz page was added"
}
```

**Response `200 OK`:**
```json
{
  "targetVersionId": "ver-a1b2c3d4",
  "targetVersionNumber": 35,
  "currentVersionId": "ver-x9y8z7w6",
  "currentVersionNumber": 42,
  "pagesToAdd": [
    {"pageId": "page-003", "title": "Original Section 2", "order": 2}
  ],
  "pagesToRemove": [
    {"pageId": "page-012", "title": "New Quiz Page", "order": 7}
  ],
  "pagesToModify": [
    {"pageId": "page-005", "titleBefore": "Introduction (Revised)", "titleAfter": "Introduction"}
  ],
  "unaffectedPageCount": 9,
  "metadataChanged": false,
  "destructiveWarning": "1 page will be removed: 'New Quiz Page'. Any learner progress on this page will be lost.",
  "estimatedAffectedPages": 3
}
```

**Error Responses:**
- `404` — Version not found
- `422` — Restore type `single_page` requires `page_id`; page not found in target version

#### `POST /api/v1/ai/admin/courses/{course_id}/restore/propose`

Create a restore proposal (standard proposal lifecycle entry point). The proposal then follows the standard apply flow from US-AI-010.

**Request Body:**
```json
{
  "version_id": "ver-a1b2c3d4",
  "restore_type": "full_course",
  "reason": "Rolling back to before AI-generated quiz page was added — content was factually incorrect"
}
```

**Response `201 Created`:**
```json
{
  "proposalId": "restore-prop-001",
  "proposalType": "restore",
  "restoreType": "full_course",
  "targetVersionId": "ver-a1b2c3d4",
  "restorePreview": {
    "targetVersionId": "ver-a1b2c3d4",
    "targetVersionNumber": 35,
    "currentVersionId": "ver-x9y8z7w6",
    "currentVersionNumber": 42,
    "pagesToAdd": [],
    "pagesToRemove": [],
    "pagesToModify": [],
    "unaffectedPageCount": 12,
    "metadataChanged": false,
    "destructiveWarning": null,
    "estimatedAffectedPages": 0
  },
  "summary": "Restore course 'Algebra Course' to version 35 (state before AI proposal prop-007)",
  "expiresAt": "2026-06-15T11:00:00+00:00"
}
```

**Error Responses:**
- `404` — Version not found
- `409` — Restore already proposed for this version (existing proposal ID returned)
- `422` — Target version is archived and snapshot data is unavailable; version chain gap prevents rehydration

#### `GET /api/v1/ai/admin/courses/{course_id}/versions/{version_id}/reify`

Force rehydration of a diff-based version and return the reified course state. Useful for debugging and manual inspection. Returns the fully reconstructed course JSON (can be large).

**Query Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `include_snapshots` | boolean | No | Include full snapshot data in response (default false — returns metadata only) |

**Response `200 OK`:**
```json
{
  "versionId": "ver-a1b2c3d4",
  "versionNumber": 42,
  "reifiedAt": "2026-06-14T10:35:00+00:00",
  "reificationMs": 234,
  "courseData": {
    "courseId": "course-alpha",
    "title": "Algebra Course",
    "pages": [...],
    "settings": {...}
  }
}
```

**Error Responses:**
- `404` — Version not found
- `422` — Version chain gap, cannot rehydrate

#### `DELETE /api/v1/ai/admin/courses/{course_id}/versions`

Prune (archive) specific versions. Admin-level operation. Only snapshot data is removed; metadata is retained with `is_archived=true`.

**Request Body:**
```json
{
  "version_ids": ["ver-old-001", "ver-old-002", "ver-old-005"]
}
```

**Response `200 OK`:**
```json
{
  "prunedCount": 3,
  "freedStorageBytes": 152340,
  "remainingVersions": 39,
  "message": "3 versions pruned. Snapshot data removed; metadata retained. 39 versions remain."
}
```

**Error Responses:**
- `422` — Cannot prune the current version or protected versions; version IDs not found

#### `GET /api/v1/ai/admin/courses/{course_id}/versions/quota`

Get version storage quota and current usage for a course.

**Response `200 OK`:**
```json
{
  "courseId": "course-alpha",
  "maxVersions": 100,
  "maxStorageMb": 512,
  "currentVersions": 42,
  "currentStorageBytes": 15234000,
  "protectedCount": 10,
  "usagePercent": 42.0,
  "storageUsagePercent": 2.8,
  "updatedAt": "2026-06-14T10:30:00+00:00"
}
```

#### `PUT /api/v1/ai/admin/courses/{course_id}/versions/quota`

Update version storage quota for a course.

**Request Body:**
```json
{
  "max_versions": 200,
  "max_storage_mb": 1024
}
```

**Response `200 OK`:**
```json
{
  "courseId": "course-alpha",
  "maxVersions": 200,
  "maxStorageMb": 1024,
  "currentVersions": 42,
  "currentStorageBytes": 15234000,
  "protectedCount": 10,
  "usagePercent": 21.0,
  "storageUsagePercent": 1.4,
  "updatedAt": "2026-06-14T10:32:00+00:00"
}
```

**Error Responses:**
- `404` — Quota record not found for course (auto-created on first version)

#### `GET /api/v1/ai/courses/{course_id}/versions` (Author View)

Lightweight version list for authors (excludes archived, excludes snapshot metadata details).

**Response `200 OK`:**
```json
{
  "items": [
    {
      "versionId": "ver-a1b2c3d4",
      "versionNumber": 42,
      "source": "ai:proposal",
      "summary": "AI updated page 'Introduction to Algebra' content",
      "label": "pre-review-draft",
      "createdBy": "user-42",
      "createdAt": "2026-06-14T10:30:00+00:00"
    }
  ],
  "total": 42
}
```

### 2.5 Service Signatures

**File:** `app/services/ai/versioning_service.py`

```python
"""Service layer for AI content versioning, diff, and restore operations."""
from __future__ import annotations
from typing import Optional, List, Tuple
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from app.models.persisted_course import CourseRecord
from app.models.page_component import PageRecord, ComponentRecord


class VersioningService:
    """Course version snapshots, diff computation, and restore proposal creation."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ── Snapshot Creation ──────────────────────────────────────────────────────

    async def create_snapshot(
        self,
        *,
        course_id: str,
        source: str,
        source_id: Optional[str] = None,
        created_by: str = "system",
        summary: str = "",
    ) -> dict:
        """Create a new version snapshot after a mutation.

        Steps:
        1. Fetch current full course state (CourseRecord + PageRecord + ComponentRecord)
        2. Serialize to a canonical course JSON structure
        3. Compute SHA-256 hash of the serialized state
        4. Fetch the previous version (if any) and decide storage strategy
           - If previous version exists and diff size < threshold → store as 'diff'
           - Otherwise → store as 'full'
           - Force a 'full' snapshot every 10 versions regardless of diff size
        5. Write the snapshot record
        6. Update the quota tracking record
        7. Invalidate the rehydration cache for the new version
        8. If quota exceeded (versions or storage), trigger prune-oldest policy
           (protected_count most recent are exempt)

        Returns:
            dict with version_id, version_number, storage_strategy, snapshot_hash
        """
        ...

    async def create_initial_snapshot(
        self,
        *,
        course_id: str,
        created_by: str = "system",
    ) -> dict:
        """Create the very first version snapshot for a course.

        Called on the first AI mutation or on manual save after versioning is
        enabled.  Always stores as 'full'.
        """
        ...

    # ── Course State Serialization ─────────────────────────────────────────────

    async def _fetch_course_state(self, course_id: str) -> dict:
        """Fetch full course state as a canonical JSON structure.

        Returns:
            {
                "courseId": str,
                "title": str,
                "description": str,
                "status": str,
                "settings": {...},
                "navigation": {...},
                "pages": [
                    {
                        "pageId": str,
                        "title": str,
                        "orderIndex": int,
                        "layout": {...},
                        "components": [
                            {
                                "componentId": str,
                                "componentType": str,
                                "data": {...}
                            }
                        ]
                    }
                ]
            }
        """
        ...

    @staticmethod
    def _compute_hash(course_state: dict) -> str:
        """Compute SHA-256 hash of the canonical JSON serialization."""
        ...

    @staticmethod
    def _compute_diff(
        before_state: dict,
        after_state: dict,
    ) -> list:
        """Compute JSON Patch (RFC 6902) between two course states.

        Returns a list of patch operations.
        """
        ...

    @staticmethod
    def _apply_diff(state: dict, diff: list) -> dict:
        """Apply a JSON Patch to a course state and return the result."""
        ...

    @staticmethod
    def _decide_storage_strategy(
        diff_size_bytes: int,
        version_number: int,
        config: Optional[dict] = None,
    ) -> str:
        """Decide 'full' or 'diff' based on size and version interval.

        Default: 'full' every 10 versions, 'diff' otherwise if diff < 5 MB.
        """
        ...

    # ── Version Queries ────────────────────────────────────────────────────────

    async def list_versions(
        self,
        *,
        course_id: str,
        include_archived: bool = False,
        label_filter: Optional[str] = None,
        source_filter: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> Tuple[List[dict], int, Optional[str]]:
        """List versions for a course with cursor pagination and filters."""
        ...

    async def list_versions_author(
        self,
        *,
        course_id: str,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> Tuple[List[dict], int, Optional[str]]:
        """Lightweight version list for authors (excludes archived)."""
        ...

    async def get_version_detail(
        self, version_id: str
    ) -> Optional[dict]:
        """Get full version detail with computed metadata (page count, size)."""
        ...

    async def get_version_detail_by_number(
        self, course_id: str, version_number: int
    ) -> Optional[dict]:
        """Get version detail by course_id + version_number."""
        ...

    # ── Version Labeling ───────────────────────────────────────────────────────

    async def set_version_label(
        self, version_id: str, label: Optional[str]
    ) -> dict:
        """Set or remove a human-readable label on a version.

        Raises:
            VersionNotFoundError
            LabelConflictError (if label already exists on another version in course)
        """
        ...

    # ── Rehydration ────────────────────────────────────────────────────────────

    async def rehydrate_version(
        self, version_id: str
    ) -> dict:
        """Rehydrate a version to full course state.

        Steps:
        1. Check rehydration cache → return cached if not stale
        2. Load the version record
        3. If 'full' → decode snapshot_json directly
        4. If 'diff' → walk parent chain to nearest 'full' ancestor,
           then apply each diff forward
        5. Cache the result
        6. Return the full course state dict

        Raises:
            VersionNotFoundError
            RehydrationChainGapError (if a parent version has been pruned)
        """
        ...

    async def _walk_parent_chain(
        self, version_id: str
    ) -> List[dict]:
        """Walk the parent chain from a diff version to the nearest 'full' ancestor.

        Returns ordered list of version records (ancestor first, target last).
        Raises RehydrationChainGapError if any version in the chain is pruned.
        """
        ...

    # ── Diff Computation ──────────────────────────────────────────────────────

    async def compute_diff(
        self,
        from_version_id: str,
        to_version_id: str,
    ) -> dict:
        """Compute a structured diff between two versions.

        Steps:
        1. Rehydrate both versions to full course state
        2. Compute metadata diff (JSON Patch)
        3. Compute page-level diff (added, removed, modified, reordered)
        4. For modified pages, compute component-level diff
        5. Compute summary counts
        6. Return structured DiffOut

        Raises:
            VersionNotFoundError
            DiffCourseMismatchError (versions belong to different courses)
        """
        ...

    # ── Restore Preview & Proposal ─────────────────────────────────────────────

    async def compute_restore_preview(
        self,
        course_id: str,
        target_version_id: str,
        restore_type: str = "full_course",
        page_id: Optional[str] = None,
    ) -> dict:
        """Compute a restore preview without creating a proposal.

        Steps:
        1. Rehydrate the target version
        2. Fetch the current course state
        3. Compute the diff (what changes when going from current → target)
        4. Categorize changes: pages to add, remove, modify
        5. Generate destructive warning if pages will be removed
        6. Return RestorePreviewOut

        Raises:
            VersionNotFoundError
            RehydrationChainGapError
            InvalidRestoreTypeError
        """
        ...

    async def propose_restore(
        self,
        *,
        course_id: str,
        target_version_id: str,
        restore_type: str = "full_course",
        page_id: Optional[str] = None,
        reason: str,
        created_by: str,
        session_id: str,
    ) -> dict:
        """Create a restore proposal.

        Steps:
        1. Compute restore preview
        2. Check if restore already proposed for this version (return 409 if so)
        3. Rehydrate target version to get the full 'after' state
        4. Create a proposal record with:
           - proposal_type = 'restore'
           - after_candidate = rehydrated target state
           - before_snapshot = current course state
           - metadata = { restore_type, target_version_id, preview }
        5. Run validation on the candidate state
        6. Return proposal ID and preview

        Raises:
            VersionNotFoundError
            RestoreAlreadyProposedError
            RehydrationChainGapError
        """
        ...

    # ── Storage Management ────────────────────────────────────────────────────

    async def get_quota(self, course_id: str) -> dict:
        """Get version storage quota for a course."""
        ...

    async def update_quota(
        self,
        course_id: str,
        max_versions: Optional[int] = None,
        max_storage_mb: Optional[int] = None,
        protected_count: Optional[int] = None,
    ) -> dict:
        """Update version storage quota."""
        ...

    async def prune_versions(
        self,
        course_id: str,
        version_ids: List[str],
    ) -> dict:
        """Prune (archive) specific versions.

        Validates:
        - No version in the list is the current version
        - No version in the list is within the protected_count window
        - All version_ids belong to the specified course

        Sets is_archived = True, clears snapshot_json (sets to null),
        updates quota tracking.
        """
        ...

    async def enforce_quota(self, course_id: str) -> bool:
        """Check and enforce quota after a new snapshot.

        If current_versions > max_versions, prunes the oldest unprotected
        versions until under quota.  Returns True if quota was enforced.
        """
        ...

    # ── Integrity ─────────────────────────────────────────────────────────────

    async def verify_snapshot_integrity(
        self, version_id: str
    ) -> dict:
        """Verify snapshot integrity by re-computing the hash.

        Returns: { "verified": bool, "expectedHash": str, "actualHash": str }
        """
        ...
```

### 2.6 Repository

**File:** `app/repositories/ai_version_repo.py`

```python
"""Repository for AI version snapshot CRUD and queries."""
from __future__ import annotations
from typing import Optional, List, Tuple
from datetime import datetime
import base64
import json

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_, desc, update, delete, text

from app.models.ai_versioning import (
    AIVersionSnapshot,
    AIVersionQuota,
    AIVersionRehydrationCache,
)


class VersionRepository:
    """DB access for ai_version_snapshots and related tables."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ── Snapshots ──────────────────────────────────────────────────────────────

    async def list_by_course(
        self,
        *,
        course_id: str,
        include_archived: bool = False,
        label_filter: Optional[str] = None,
        source_filter: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 50,
        cursor_version_number: Optional[int] = None,
    ) -> Tuple[List[AIVersionSnapshot], int]:
        """List versions with cursor pagination (by version_number DESC).

        Uses version_number as the cursor key (monotonically increasing,
        unique per course) for stable pagination.
        """
        q = select(AIVersionSnapshot)

        conditions = [AIVersionSnapshot.course_id == course_id]
        if not include_archived:
            conditions.append(AIVersionSnapshot.is_archived == False)
        if label_filter:
            conditions.append(AIVersionSnapshot.label.ilike(f"{label_filter}%"))
        if source_filter:
            conditions.append(AIVersionSnapshot.source == source_filter)
        if date_from:
            conditions.append(AIVersionSnapshot.created_at >= date_from)
        if date_to:
            conditions.append(AIVersionSnapshot.created_at <= date_to)
        if cursor_version_number is not None:
            conditions.append(
                AIVersionSnapshot.version_number < cursor_version_number
            )

        q = q.where(and_(*conditions))

        # Count total
        count_q = select(func.count()).select_from(q.subquery())
        total = (await self.session.execute(count_q)).scalar() or 0

        q = q.order_by(AIVersionSnapshot.version_number.desc())
        q = q.limit(limit + 1)

        rows = list((await self.session.execute(q)).scalars().all())
        return rows, total

    async def get_by_version_id(
        self, version_id: str
    ) -> Optional[AIVersionSnapshot]:
        q = select(AIVersionSnapshot).where(
            AIVersionSnapshot.version_id == version_id
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def get_by_course_and_number(
        self, course_id: str, version_number: int
    ) -> Optional[AIVersionSnapshot]:
        q = select(AIVersionSnapshot).where(
            and_(
                AIVersionSnapshot.course_id == course_id,
                AIVersionSnapshot.version_number == version_number,
            )
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def get_latest_version(
        self, course_id: str
    ) -> Optional[AIVersionSnapshot]:
        q = (
            select(AIVersionSnapshot)
            .where(AIVersionSnapshot.course_id == course_id)
            .order_by(AIVersionSnapshot.version_number.desc())
            .limit(1)
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def get_full_snapshot_versions(
        self, course_id: str, before_version_number: int
    ) -> List[AIVersionSnapshot]:
        """Get all 'full' strategy versions before a given version number,
        ordered descending. Used for parent chain walking during rehydration.
        """
        q = (
            select(AIVersionSnapshot)
            .where(
                and_(
                    AIVersionSnapshot.course_id == course_id,
                    AIVersionSnapshot.storage_strategy == "full",
                    AIVersionSnapshot.version_number <= before_version_number,
                    AIVersionSnapshot.is_archived == False,
                )
            )
            .order_by(AIVersionSnapshot.version_number.desc())
        )
        rows = (await self.session.execute(q)).scalars().all()
        return list(rows)

    async def get_version_chain(
        self,
        from_version_id: str,
        to_version_id: str,
    ) -> List[AIVersionSnapshot]:
        """Get the ordered chain of versions between two version IDs (inclusive),
        ordered ascending by version_number. Used for diff computation.
        Returns empty list if either end is archived.
        """
        from_v = await self.get_by_version_id(from_version_id)
        to_v = await self.get_by_version_id(to_version_id)
        if not from_v or not to_v:
            return []
        if from_v.course_id != to_v.course_id:
            return []
        min_vn = min(from_v.version_number, to_v.version_number)
        max_vn = max(from_v.version_number, to_v.version_number)
        q = (
            select(AIVersionSnapshot)
            .where(
                and_(
                    AIVersionSnapshot.course_id == from_v.course_id,
                    AIVersionSnapshot.version_number >= min_vn,
                    AIVersionSnapshot.version_number <= max_vn,
                    AIVersionSnapshot.is_archived == False,
                )
            )
            .order_by(AIVersionSnapshot.version_number.asc())
        )
        rows = (await self.session.execute(q)).scalars().all()
        return list(rows)

    async def count_by_course(self, course_id: str) -> int:
        q = select(func.count()).where(
            and_(
                AIVersionSnapshot.course_id == course_id,
                AIVersionSnapshot.is_archived == False,
            )
        )
        return (await self.session.execute(q)).scalar() or 0

    async def create(self, record: AIVersionSnapshot) -> AIVersionSnapshot:
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def get_next_version_number(self, course_id: str) -> int:
        q = (
            select(func.coalesce(
                func.max(AIVersionSnapshot.version_number), 0
            ))
            .where(AIVersionSnapshot.course_id == course_id)
        )
        result = await self.session.execute(q)
        return (result.scalar() or 0) + 1

    async def archive_snapshot(self, version_id: str) -> None:
        """Archive a version by clearing snapshot_json and setting is_archived.
        Retains metadata columns.
        """
        stmt = (
            update(AIVersionSnapshot)
            .where(AIVersionSnapshot.version_id == version_id)
            .values(
                snapshot_json={},  # empty JSONB instead of null for safety
                is_archived=True,
                archived_at=datetime.utcnow(),
            )
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def get_total_storage_bytes(self, course_id: str) -> int:
        """Approximate total storage used by non-archived versions."""
        q = select(
            func.sum(
                func.pg_column_size(AIVersionSnapshot.snapshot_json)
            )
        ).where(
            and_(
                AIVersionSnapshot.course_id == course_id,
                AIVersionSnapshot.is_archived == False,
            )
        )
        result = await self.session.execute(q)
        return result.scalar() or 0

    # ── Quota ──────────────────────────────────────────────────────────────────

    async def get_quota(self, course_id: str) -> Optional[AIVersionQuota]:
        q = select(AIVersionQuota).where(
            AIVersionQuota.course_id == course_id
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def upsert_quota(
        self,
        course_id: str,
        max_versions: Optional[int] = None,
        max_storage_mb: Optional[int] = None,
        protected_count: Optional[int] = None,
    ) -> AIVersionQuota:
        existing = await self.get_quota(course_id)
        if existing:
            if max_versions is not None:
                existing.max_versions = max_versions
            if max_storage_mb is not None:
                existing.max_storage_mb = max_storage_mb
            if protected_count is not None:
                existing.protected_count = protected_count
            existing.current_versions = await self.count_by_course(course_id)
            existing.current_storage_bytes = await self.get_total_storage_bytes(course_id)
            existing.updated_at = datetime.utcnow()
            await self.session.commit()
            await self.session.refresh(existing)
            return existing

        record = AIVersionQuota(
            course_id=course_id,
            max_versions=max_versions or 100,
            max_storage_mb=max_storage_mb or 512,
            protected_count=protected_count or 10,
            current_versions=await self.count_by_course(course_id),
            current_storage_bytes=await self.get_total_storage_bytes(course_id),
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    # ── Rehydration Cache ──────────────────────────────────────────────────────

    async def get_cached_reification(
        self, version_id: str
    ) -> Optional[AIVersionRehydrationCache]:
        q = select(AIVersionRehydrationCache).where(
            and_(
                AIVersionRehydrationCache.version_id == version_id,
                AIVersionRehydrationCache.is_stale == False,
            )
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def set_cached_reification(
        self,
        version_id: str,
        reified_json: dict,
        reification_ms: int,
    ) -> AIVersionRehydrationCache:
        # Remove stale cache entry if exists
        await self.delete_cached_reification(version_id)

        record = AIVersionRehydrationCache(
            version_id=version_id,
            reified_json=reified_json,
            reification_ms=reification_ms,
            is_stale=False,
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def invalidate_reification_cache(self, course_id: str) -> None:
        """Mark all cache entries for a course as stale."""
        stmt = (
            update(AIVersionRehydrationCache)
            .where(
                AIVersionRehydrationCache.version_id.in_(
                    select(AIVersionSnapshot.version_id).where(
                        AIVersionSnapshot.course_id == course_id
                    )
                )
            )
            .values(is_stale=True)
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def delete_cached_reification(self, version_id: str) -> None:
        stmt = delete(AIVersionRehydrationCache).where(
            AIVersionRehydrationCache.version_id == version_id
        )
        await self.session.execute(stmt)
        await self.session.commit()

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def encode_cursor(version_number: int) -> str:
        payload = json.dumps({"version_number": version_number})
        return base64.urlsafe_b64encode(payload.encode()).decode()

    @staticmethod
    def decode_cursor(cursor: str) -> int:
        try:
            payload = json.loads(
                base64.urlsafe_b64decode(cursor.encode()).decode()
            )
            return int(payload["version_number"])
        except (ValueError, KeyError, json.JSONDecodeError):
            raise ValueError("Invalid cursor")
```

### 2.7 Router

**File:** `app/routers/ai_versioning.py`

```python
"""AI content versioning and restore API routes.

All routes are prefixed with /api/v1/ai (admin routes under /ai/admin,
author routes under /ai/courses).
"""
from __future__ import annotations
from typing import Optional
from datetime import datetime, timedelta
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.services.ai.versioning_service import VersioningService
from app.models.ai_versioning_dto import (
    VersionOut,
    VersionListOut,
    VersionDetailOut,
    VersionLabelRequest,
    VersionLabelOut,
    VersionDiffOut,
    RestoreProposalRequest,
    RestoreProposalOut,
    RestorePreviewOut,
    VersionQuotaOut,
    VersionQuotaUpdateRequest,
    VersionPruneRequest,
    VersionPruneOut,
)

logger = logging.getLogger(__name__)

# ── Admin Router ────────────────────────────────────────────────────────────────
admin_router = APIRouter(prefix="/ai/admin", tags=["AI Admin - Versioning"])

# ── Author Router ───────────────────────────────────────────────────────────────
author_router = APIRouter(prefix="/ai", tags=["AI Versioning"])


# ── Shared Dependencies ─────────────────────────────────────────────────────────

async def _require_admin():
    """Placeholder for admin authorization check."""
    return True


async def _require_author():
    """Placeholder for author authorization check (any authenticated user)."""
    return True


async def _get_versioning_service(
    session: AsyncSession = Depends(get_session),
) -> VersioningService:
    return VersioningService(session)


# ── Admin: Version Listing & Detail ────────────────────────────────────────────


@admin_router.get(
    "/courses/{course_id}/versions",
    response_model=VersionListOut,
)
async def list_versions(
    course_id: str,
    include_archived: bool = Query(False),
    label_filter: Optional[str] = Query(None, max_length=100),
    source_filter: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[str] = Query(None),
    admin: bool = Depends(_require_admin),
    service: VersioningService = Depends(_get_versioning_service),
):
    """List versions for a course with filtering and cursor pagination."""
    try:
        items, total, next_cursor = await service.list_versions(
            course_id=course_id,
            include_archived=include_archived,
            label_filter=label_filter,
            source_filter=source_filter,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return VersionListOut(
        items=[VersionOut(**item) for item in items],
        total=total,
        nextCursor=next_cursor,
        hasMore=next_cursor is not None,
    )


@admin_router.get(
    "/courses/{course_id}/versions/{version_id}",
    response_model=VersionDetailOut,
)
async def get_version_detail(
    course_id: str,
    version_id: str,
    admin: bool = Depends(_require_admin),
    service: VersioningService = Depends(_get_versioning_service),
):
    """Get full version detail with computed metadata."""
    detail = await service.get_version_detail(version_id)
    if not detail:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "VERSION_NOT_FOUND",
                "message": f"Version '{version_id}' not found",
            },
        )
    if detail["courseId"] != course_id:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "VERSION_NOT_FOUND",
                "message": f"Version '{version_id}' not found in course '{course_id}'",
            },
        )
    return VersionDetailOut(**detail)


# ── Admin: Version Labeling ────────────────────────────────────────────────────


@admin_router.put(
    "/courses/{course_id}/versions/{version_id}/label",
    response_model=VersionLabelOut,
)
async def set_version_label(
    course_id: str,
    version_id: str,
    body: VersionLabelRequest,
    admin: bool = Depends(_require_admin),
    service: VersioningService = Depends(_get_versioning_service),
):
    """Set or remove a human-readable label on a version."""
    try:
        result = await service.set_version_label(version_id, body.label)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return VersionLabelOut(**result)


# ── Admin: Version Diff ────────────────────────────────────────────────────────


@admin_router.get(
    "/courses/{course_id}/versions/{version_id}/diff",
    response_model=VersionDiffOut,
)
async def compute_version_diff(
    course_id: str,
    version_id: str,
    compare_to: Optional[str] = Query(
        None, description="Version ID to compare against. Defaults to previous version."
    ),
    admin: bool = Depends(_require_admin),
    service: VersioningService = Depends(_get_versioning_service),
):
    """Compute a structured diff between two versions."""
    try:
        diff = await service.compute_diff(
            from_version_id=compare_to,
            to_version_id=version_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return VersionDiffOut(**diff)


# ── Admin: Restore Preview & Proposal ─────────────────────────────────────────


@admin_router.post(
    "/courses/{course_id}/restore/preview",
    response_model=RestorePreviewOut,
)
async def preview_restore(
    course_id: str,
    body: RestoreProposalRequest,
    admin: bool = Depends(_require_admin),
    service: VersioningService = Depends(_get_versioning_service),
):
    """Preview a restore operation without creating a proposal."""
    try:
        preview = await service.compute_restore_preview(
            course_id=course_id,
            target_version_id=body.version_id,
            restore_type=body.restore_type,
            page_id=body.page_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return RestorePreviewOut(**preview)


@admin_router.post(
    "/courses/{course_id}/restore/propose",
    response_model=RestoreProposalOut,
    status_code=201,
)
async def propose_restore(
    course_id: str,
    body: RestoreProposalRequest,
    admin: bool = Depends(_require_admin),
    service: VersioningService = Depends(_get_versioning_service),
):
    """Create a restore proposal (follows standard proposal lifecycle)."""
    try:
        result = await service.propose_restore(
            course_id=course_id,
            target_version_id=body.version_id,
            restore_type=body.restore_type,
            page_id=body.page_id,
            reason=body.reason,
            created_by="admin",  # In production, extract from auth context
            session_id="admin-session",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return RestoreProposalOut(**result)


# ── Admin: Rehydration (Debug) ────────────────────────────────────────────────


@admin_router.get(
    "/courses/{course_id}/versions/{version_id}/reify",
)
async def rehydrate_version(
    course_id: str,
    version_id: str,
    include_snapshots: bool = Query(False),
    admin: bool = Depends(_require_admin),
    service: VersioningService = Depends(_get_versioning_service),
):
    """Force rehydration and return full course state for a version."""
    try:
        result = await service.rehydrate_version(version_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return result


# ── Admin: Storage Management ──────────────────────────────────────────────────


@admin_router.get(
    "/courses/{course_id}/versions/quota",
    response_model=VersionQuotaOut,
)
async def get_version_quota(
    course_id: str,
    admin: bool = Depends(_require_admin),
    service: VersioningService = Depends(_get_versioning_service),
):
    """Get version storage quota and current usage."""
    quota = await service.get_quota(course_id)
    if not quota:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "QUOTA_NOT_FOUND",
                "message": f"No quota record found for course '{course_id}'",
            },
        )
    return VersionQuotaOut(**quota)


@admin_router.put(
    "/courses/{course_id}/versions/quota",
    response_model=VersionQuotaOut,
)
async def update_version_quota(
    course_id: str,
    body: VersionQuotaUpdateRequest,
    admin: bool = Depends(_require_admin),
    service: VersioningService = Depends(_get_versioning_service),
):
    """Update version storage quota."""
    quota = await service.update_quota(
        course_id=course_id,
        max_versions=body.max_versions,
        max_storage_mb=body.max_storage_mb,
        protected_count=body.protected_count,
    )
    return VersionQuotaOut(**quota)


@admin_router.delete(
    "/courses/{course_id}/versions",
    response_model=VersionPruneOut,
)
async def prune_versions(
    course_id: str,
    body: VersionPruneRequest,
    admin: bool = Depends(_require_admin),
    service: VersioningService = Depends(_get_versioning_service),
):
    """Prune (archive) specific versions. Snapshot data removed, metadata retained."""
    try:
        result = await service.prune_versions(
            course_id=course_id,
            version_ids=body.version_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return VersionPruneOut(**result)


# ── Author: Lightweight Version List ───────────────────────────────────────────


@author_router.get(
    "/courses/{course_id}/versions",
    response_model=VersionListOut,
)
async def list_versions_author(
    course_id: str,
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[str] = Query(None),
    auth: bool = Depends(_require_author),
    service: VersioningService = Depends(_get_versioning_service),
):
    """Lightweight version list for authors (excludes archived versions)."""
    items, total, next_cursor = await service.list_versions_author(
        course_id=course_id,
        limit=limit,
        cursor=cursor,
    )
    return VersionListOut(
        items=[VersionOut(**item) for item in items],
        total=total,
        nextCursor=next_cursor,
        hasMore=next_cursor is not None,
    )
```

### 2.8 Alembic Migration

**File:** `alembic/versions/20260614_0002_add_ai_versioning_tables.py`

```python
"""Add ai_version_snapshots, quotas, and rehydration cache tables.

Revision ID: 20260614_0002
Revises: 20260614_0001
Create Date: 2026-06-14
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260614_0002"
down_revision: Union[str, None] = "20260614_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── ai_version_snapshots ───────────────────────────────────────────────────
    op.create_table(
        "ai_version_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("version_id", sa.String(64), nullable=False),
        sa.Column("course_id", sa.String(64), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(128), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=False, server_default="system"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("parent_version_id", sa.String(64), nullable=True),
        sa.Column("storage_strategy", sa.String(16), nullable=False, server_default="full"),
        sa.Column("snapshot_json", postgresql.JSONB(), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(16), nullable=False, server_default="1.0"),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id"),
        sa.UniqueConstraint(
            "course_id", "version_number", name="uq_version_course_number"
        ),
        sa.UniqueConstraint(
            "course_id", "label", name="uq_version_course_label"
        ),
    )
    op.create_check_constraint(
        "ck_version_source",
        "ai_version_snapshots",
        "source IN ('ai:proposal','manual:save','rollback',"
        "'restore','import','system:migration')",
    )
    op.create_check_constraint(
        "ck_version_storage_strategy",
        "ai_version_snapshots",
        "storage_strategy IN ('full', 'diff')",
    )

    # Indexes
    op.create_index("idx_version_id", "ai_version_snapshots", ["version_id"])
    op.create_index("idx_version_course_id", "ai_version_snapshots", ["course_id"])
    op.create_index(
        "idx_version_course_number",
        "ai_version_snapshots",
        ["course_id", sa.text("version_number DESC")],
    )
    op.create_index(
        "idx_version_created_at",
        "ai_version_snapshots",
        [sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_version_parent", "ai_version_snapshots", ["parent_version_id"]
    )
    op.create_index("idx_version_source", "ai_version_snapshots", ["source"])
    op.create_index(
        "idx_version_archived", "ai_version_snapshots", ["is_archived"],
        postgresql_where=sa.text("is_archived = false"),
    )
    op.create_index(
        "idx_version_snapshot_gin",
        "ai_version_snapshots",
        [postgresql.JSONB("snapshot_json")],
        postgresql_using="gin",
    )

    # ── ai_version_quotas ──────────────────────────────────────────────────────
    op.create_table(
        "ai_version_quotas",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("course_id", sa.String(64), nullable=False),
        sa.Column("max_versions", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("max_storage_mb", sa.Integer(), nullable=False, server_default="512"),
        sa.Column("current_versions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_storage_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("protected_count", sa.Integer(), nullable=False, server_default="10"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id"),
    )
    op.create_index("idx_quota_course", "ai_version_quotas", ["course_id"])

    # ── ai_version_rehydration_cache ───────────────────────────────────────────
    op.create_table(
        "ai_version_rehydration_cache",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("version_id", sa.String(64), nullable=False),
        sa.Column("reified_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "reified_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("reification_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_stale", sa.Boolean(), nullable=False, server_default="false"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id"),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["ai_version_snapshots.version_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("idx_cache_version", "ai_version_rehydration_cache", ["version_id"])
    op.create_index(
        "idx_cache_stale", "ai_version_rehydration_cache", ["is_stale"],
        postgresql_where=sa.text("is_stale = false"),
    )


def downgrade() -> None:
    op.drop_table("ai_version_rehydration_cache")
    op.drop_table("ai_version_quotas")
    op.drop_table("ai_version_snapshots")
```

### 2.9 Integration Points

#### Register the Router in `app/main.py`

```python
# Add to existing imports
from app.routers import ai_versioning  # new

# Add to the api_router include block
api_router.include_router(ai_versioning.admin_router)
api_router.include_router(ai_versioning.author_router)
```

#### Register ORM Models in `alembic/env.py`

```python
# Add to existing model imports
import app.models.ai_versioning  # noqa: F401
```

#### Register in `app/models/__init__.py`

```python
from app.models.ai_versioning import (
    AIVersionSnapshot,
    AIVersionQuota,
    AIVersionRehydrationCache,
)

__all__ += ["AIVersionSnapshot", "AIVersionQuota", "AIVersionRehydrationCache"]
```

#### Hook into Apply Service (US-AI-010)

The apply service in `app/services/ai/apply_service.py` (from US-AI-010) must call `VersioningService.create_snapshot()` inside the same transaction after every successful mutation:

```python
# Inside ApplyService.apply_proposal(), after mutation succeeds:
version = await versioning_service.create_snapshot(
    course_id=proposal.course_id,
    source="ai:proposal",
    source_id=proposal.proposal_id,
    created_by=proposal.created_by,
    summary=proposal.summary or f"Applied proposal {proposal.proposal_id}",
)
```

### 2.10 Environment Variables

```bash
# ── AI Versioning & Rollback Configuration ─────────────────────────────────────

# Enable/disable the versioning system entirely.
# When disabled, no snapshots are taken and version/restore API returns 404.
FEATURE_AI_VERSIONING=true

# Snapshot retention period in days. Versions older than this may be archived.
AI_VERSION_RETENTION_DAYS=90

# Maximum number of versions per course (default quota).
AI_VERSION_MAX_VERSIONS_PER_COURSE=100

# Maximum storage per course in MB (default quota).
AI_VERSION_MAX_STORAGE_MB_PER_COURSE=512

# How many recent versions are protected from auto-prune.
AI_VERSION_PROTECTED_COUNT=10

# Force a 'full' snapshot every N versions. Between fulls, store diffs.
AI_VERSION_FULL_INTERVAL=10

# Maximum diff size (in bytes) before forcing a full snapshot instead.
AI_VERSION_MAX_DIFF_SIZE_BYTES=5242880  # 5 MB

# Rehydration cache TTL in seconds. After this, the cached reified state
# is considered stale and will be recomputed on next access.
AI_VERSION_REHYDRATION_CACHE_TTL_SECONDS=3600

# Enable rehydration caching (recommended for performance).
AI_VERSION_REHYDRATION_CACHE_ENABLED=true
```

---

## 3. Non-Functional Requirements

### 3.1 Performance

| Requirement | Target | Measurement |
|---|---|---|
| Version snapshot creation (diff strategy) p95 | < 500ms for courses up to 500 pages | Application metrics |
| Version snapshot creation (full strategy) p95 | < 3s for courses up to 500 pages | Application metrics |
| Version list query p95 | < 300ms | Application metrics |
| Version diff computation p95 | < 2s for courses up to 500 pages | Application metrics |
| Version rehydration (from cache) p95 | < 200ms | Application metrics |
| Version rehydration (cold, diff chain) p95 | < 3s for courses up to 500 pages, 10-version chain | Application metrics |
| Restore preview computation p95 | < 2s | Application metrics |
| Restore proposal creation p95 | < 3s | Application metrics |
| Version pruning (100 versions) | < 5s | Application metrics |
| Concurrent versioning operations | 20 simultaneous per course | Load test |

### 3.2 Storage

| Item | Estimate | Notes |
|---|---|---|
| Full snapshot, 50-page course | ~500 KB | JSONB with page/component data |
| Diff snapshot, single page edit | ~5-50 KB | JSON Patch of changed fields |
| Full snapshot, 500-page course | ~5 MB | Upper bound for typical courses |
| Storage for 100 versions (mixed full/diff) | ~20-50 MB | Depends on change frequency |
| Rehydration cache, 50-page course | ~500 KB per cached version | Evicted on new snapshot |

### 3.3 Security

| Requirement | Implementation |
|---|---|
| Admin-only for destructive operations | Restore preview, proposal, and prune require admin role |
| Author read-only access | Authors can list versions and view metadata only |
| Course isolation | All queries filter by course_id; cross-course version access returns 404 |
| Snapshot integrity | SHA-256 hash stored with each version; verification endpoint for audit |
| Data retention compliance | Archived versions retain metadata (who, when, source) but clear snapshot data |

### 3.4 Availability

| Requirement | Target |
|---|---|
| Versioning availability | Same as core API (99.9%) |
| Versioning outage behavior | If version store is unreachable, AI mutations proceed WITHOUT version snapshots (fail-open for writes, fail-closed for reads) |
| Data durability | Version snapshots are transactional with the apply mutation |

### 3.5 Observability

- Every snapshot creation emits: `course_id`, `version_number`, `storage_strategy`, `duration_ms`, `snapshot_size_bytes`
- Every rehydration emits: `version_id`, `from_cache`, `chain_length`, `duration_ms`
- Every diff computation emits: `from_version`, `to_version`, `changes_count`, `duration_ms`
- Metrics: `ai.version.snapshot.created`, `ai.version.rehydration.ms`, `ai.version.diff.ms`, `ai.version.restore.proposed`, `ai.version.prune.executed`
- Storage usage metrics per course (gauge): `ai.version.storage.bytes`, `ai.version.count`

---

## 4. Current State Assessment

### 4.1 What Exists

1. **No versioning tables exist.** The models in `app/models/` cover courses, pages, components, templates, themes, scoring, interaction events, branching, social features, and the planned AI audit tables (US-AI-020) — but no `ai_version_snapshots`, `ai_version_quotas`, or `ai_version_rehydration_cache` tables.

2. **Audit-based before-snapshots exist (US-AI-020).** The planned `ai_audit_logs.before_snapshot` and `after_snapshot` columns store page-level state at the time of mutation. Versioning extends this to full-course state with differential storage and point-in-time restore.

3. **Existing course state fetching pattern** in `app/repositories/course_repo.py` and `app/repositories/page_component_repo.py` provides the building blocks for the canonical course serialization needed by version snapshots.

4. **Existing cursor pagination pattern** in `app/repositories/ai_audit_repo.py` (from US-AI-020) provides a reference for the version list cursor pagination.

5. **Existing proposal lifecycle** (US-AI-009) in `app/services/ai/proposal_service.py` provides the restore-proposal integration point.

6. **Existing apply service** (US-AI-010) provides the hook for automatic snapshot creation on mutation.

7. **Existing feature flag system** in `app/utils/feature_flags.py` — new flag `FEATURE_AI_VERSIONING` will be added here.

### 4.2 What Needs to Be Built

| Component | Description | Reference Pattern |
|---|---|---|
| `app/models/ai_versioning.py` | ORM models for snapshots, quotas, cache | `app/models/persisted_course.py` |
| `app/models/ai_versioning_dto.py` | Pydantic DTOs for versioning API | `app/models/ai_audit_dto.py` |
| `app/repositories/ai_version_repo.py` | Repository with chain walking, quota, cache | `app/repositories/ai_audit_repo.py` |
| `app/services/ai/versioning_service.py` | Snapshots, diff, rehydration, restore, prune | `app/services/ai/audit_service.py` |
| `app/routers/ai_versioning.py` | Admin and author versioning endpoints | `app/routers/ai_admin.py` |
| Alembic migration | Add `ai_version_snapshots`, `ai_version_quotas`, `ai_version_rehydration_cache` | `alembic/versions/20260614_0002_...` |
| Tests | Unit, integration, and performance tests | `tests/unit/ai/`, `tests/integration/ai/` |
| Apply service hook | Call `VersioningService.create_snapshot()` after mutation | `app/services/ai/apply_service.py` |

### 4.3 Key Assumptions

- The apply service (US-AI-010) exists and provides a hook for post-mutation snapshot creation
- The audit service (US-AI-020) exists and provides the `before_snapshot`/`after_snapshot` data at the page level
- The proposal lifecycle (US-AI-009) exists and supports custom `proposal_type` values
- JSON Patch (RFC 6902) library `jsonpatch` is available or can be added to requirements
- SHA-256 hashing via `hashlib` is built into Python stdlib
- PostgreSQL JSONB type is available for snapshot storage
- PostgreSQL `pg_column_size` function is available for storage tracking

---

## 5. Expansion Points

### 5.1 Phase 2: Enhanced Version Management

- **Version tags and annotations:** Rich annotations per version (author notes, review status, approval workflow)
- **Version branching:** Support for parallel version branches (e.g., experiment branch, review branch) with merge semantics
- **Scheduled snapshots:** Configurable automatic snapshots (every N hours, daily, on export)
- **Bulk version export/import:** Export version history for migration or backup, import into another instance

### 5.2 Phase 3: Point-in-Time Recovery

- **Arbitrary point-in-time restore:** Not just version boundaries, but any timestamp between versions (requires storing operation-level diffs)
- **Warm standby version store:** Replicate version snapshots to a read-replica for query isolation
- **Cold storage archival:** Move old snapshots to S3/GCS with metadata retained in PostgreSQL for queryability

### 5.3 Phase 4: Advanced Diff and Visualization

- **Semantic diff:** Understand when a component type changed (e.g., content-text → mcq) rather than just field-level diff
- **Visual regression diff:** Side-by-side rendered HTML comparison for pages, not just JSON diff
- **Change impact analysis:** Given a version diff, compute impact on SCORM export, learner progress, completion data

---

## 6. Validation Strategy

### 6.1 Unit Tests

**File:** `tests/unit/ai/test_version_repo.py`

| Test | Scenario | Expected |
|---|---|---|
| `test_list_versions_empty` | No versions for course | Returns empty list, total=0 |
| `test_list_versions_paginated` | 25 versions, limit=10 | Returns 10 items, total=25, hasMore=true |
| `test_get_latest_version` | Multiple versions | Returns highest version_number |
| `test_get_by_course_and_number` | Known course+number | Returns matching version |
| `test_get_by_course_and_number_missing` | Unknown number | Returns None |
| `test_get_full_snapshot_versions` | Mix of full/diff | Returns only 'full' type before threshold |
| `test_get_version_chain` | Consecutive versions | Returns ordered list ascending |
| `test_archive_snapshot` | Archive a version | snapshot_json cleared, is_archived=true, archived_at set |
| `test_upsert_quota_create` | No existing quota | Creates new record with defaults |
| `test_upsert_quota_update` | Existing quota | Updates fields, preserves others |
| `test_cursor_encode_decode_roundtrip` | Encode then decode | Returns original version_number |
| `test_cursor_decode_invalid` | Malformed cursor | Raises ValueError |
| `test_cache_operations` | Set, get, invalidate | Cache roundtrips correctly |

**File:** `tests/unit/ai/test_versioning_service.py`

| Test | Scenario | Expected |
|---|---|---|
| `test_create_snapshot_first_version` | No prior versions | Storage=full, version_number=1 |
| `test_create_snapshot_diff_strategy` | Small change from previous | Storage=diff, patch is valid |
| `test_create_snapshot_force_full_interval` | 10th version | Storage=full regardless of diff size |
| `test_create_snapshot_force_full_large_diff` | Diff > 5MB | Storage=full |
| `test_rehydrate_full_version` | Full strategy version | Returns full state directly |
| `test_rehydrate_diff_version` | Diff strategy, parent exists | Applies patch, returns full state |
| `test_rehydrate_chain_gap` | Parent archived | Raises RehydrationChainGapError |
| `test_rehydrate_cache_hit` | Cached version | Returns from cache, fast |
| `test_rehydrate_cache_miss` | Uncached version | Computes, caches, returns |
| `test_compute_diff_same_version` | Version compared to itself | Empty diff, zero changes |
| `test_compute_diff_added_page` | Page added between versions | pagesAdded=1, pagesRemoved=0 |
| `test_compute_diff_removed_page` | Page removed | pagesAdded=0, pagesRemoved=1 |
| `test_compute_diff_metadata_change` | Title changed | metadataChanged=true |
| `test_compute_restore_preview_full` | Full course restore | Lists pages to add/remove/modify |
| `test_compute_restore_preview_noop` | Current = target | Zero affected pages |
| `test_propose_restore_creates_proposal` | Valid params | Returns proposalId |
| `test_propose_restore_already_exists` | Duplicate request | Raises RestoreAlreadyProposedError |
| `test_prune_versions_validation` | Try prune current version | Raises ValueError |
| `test_prune_versions_protected` | Try prune protected version | Raises ValueError |
| `test_verify_integrity_match` | Hash matches | verified=true |
| `test_verify_integrity_mismatch` | Hash doesn't match | verified=false |

### 6.2 API Integration Tests

**File:** `tests/integration/ai/test_versioning_api.py`

| Test | Scenario | HTTP | Expected |
|---|---|---|---|
| `test_list_versions_no_auth` | No auth header | GET | 403 |
| `test_list_versions_empty` | No versions | GET | 200, items=[], total=0 |
| `test_list_versions_populated` | Seed 5 versions | GET | 200, total=5 |
| `test_list_versions_pagination` | Seed 150 versions, page 50 | GET | 200, items=50, hasMore=true |
| `test_get_version_detail` | Known version_id | GET | 200, full detail |
| `test_get_version_detail_not_found` | Unknown version_id | GET | 404 |
| `test_get_version_detail_wrong_course` | Cross-course lookup | GET | 404 |
| `test_set_version_label` | Valid label | PUT | 200, label set |
| `test_set_version_label_duplicate` | Duplicate label | PUT | 409 |
| `test_remove_version_label` | Label=null | PUT | 200, label removed |
| `test_version_diff` | Two versions with changes | GET | 200, diff with changes |
| `test_version_diff_no_changes` | Two identical versions | GET | 200, empty diff |
| `test_version_diff_cross_course` | Versions from different courses | GET | 422 |
| `test_restore_preview_full_course` | Valid version_id | POST | 200, preview with affected pages |
| `test_restore_preview_noop` | Current version | POST | 200, zero affected |
| `test_propose_restore` | Valid request | POST | 201, proposalId returned |
| `test_propose_restore_not_found` | Invalid version_id | POST | 404 |
| `test_propose_restore_duplicate` | Same version asked twice | POST | 409 |
| `test_prune_versions` | 3 version IDs | DELETE | 200, prunedCount=3 |
| `test_prune_current_version` | Try prune current | DELETE | 422 |
| `test_get_quota_default` | First access | GET | 200, default quota values |
| `test_update_quota` | Update limits | PUT | 200, updated values |
| `test_rehydrate_version` | Valid version | GET | 200, course state returned |
| `test_rehydrate_archived_version` | Archived version | GET | 422 |

### 6.3 Security Tests

| Test | Scenario | Expected |
|---|---|---|
| `test_non_admin_cannot_restore` | Author attempts restore | 403 Forbidden |
| `test_non_admin_cannot_prune` | Author attempts prune | 403 Forbidden |
| `test_author_version_list_lightweight` | Author lists versions | 200, lightweight response |
| `test_cross_tenant_version_access` | Tenant A requests tenant B version | 404 |
| `test_version_integrity_check` | Verify hash after create | Hash matches fetched course state |

### 6.4 Performance Tests

| Test | Scenario | Expected |
|---|---|---|
| `test_snapshot_creation_500_pages` | Create full snapshot, 500-page course | p95 < 3s |
| `test_diff_rehydration_chain_10` | Rehydrate 10th version from chain | p95 < 3s |
| `test_diff_large_course` | Diff two versions of 500-page course | p95 < 2s |
| `test_concurrent_version_reads` | 20 concurrent version list queries | No pool exhaustion |
| `test_storage_100_versions` | 100 versions over a 50-page course | Total storage < 100 MB |

---

## 7. Definition of Done

### 7.1 Acceptance Criteria

1. Every applied AI mutation creates a version snapshot (full or diff) in the same transaction
2. Versions are listed in descending chronological order with cursor pagination
3. Version detail includes page count, component count, snapshot hash, and storage strategy
4. Authors can assign/remove human-readable labels on versions (unique per course)
5. Diff between any two versions shows page-level and component-level changes with JSON Patch detail
6. Restore preview shows exact pages to add, remove, and modify without creating a proposal
7. Restore proposal creation follows the standard proposal lifecycle (US-AI-009)
8. Restoration creates a new version snapshot with source="restore"
9. Version pruning (archival) removes snapshot data but retains metadata
10. Quota enforcement prevents unbounded storage growth
11. Differential snapshots are taken between full snapshots; full snapshots are forced every N versions
12. Rehydration cache improves repeated access to diff-based versions
13. Snapshot integrity verification detects data corruption
14. All versioning endpoints return 404 when `FEATURE_AI_VERSIONING=false`
15. Alembic migration is reversible (downgrade drops all three tables)
16. Existing test suite passes with no regressions

### 7.2 Quality Gates

- [ ] All unit tests pass (coverage > 85% for new code)
- [ ] All API integration tests pass
- [ ] `FEATURE_AI_VERSIONING=false` hides all versioning routes
- [ ] OpenAPI spec renders correctly with new route tags "AI Admin - Versioning" and "AI Versioning"
- [ ] Flake8/Pylint passes with no new issues
- [ ] Type annotations present on all new function signatures
- [ ] Migration tested both `upgrade()` and `downgrade()`
- [ ] Performance benchmark meets p95 targets
- [ ] Storage optimization: diff snapshots < full snapshots for single-page changes
- [ ] Integrity verification: snapshot_hash matches re-computed hash

### 7.3 Signoff Checklist

| Role | Signoff Criteria |
|---|---|
| Product Owner | Acceptance criteria met, demo shows all FRs working |
| Security Lead | Course isolation verified, admin access control enforced |
| QA Lead | All test levels pass, performance benchmarks met |
| Operations | Migration script tested, env vars documented, storage monitoring configured |
| Tech Lead | Code review clean, diff/rehydration performance acceptable |

---

## 8. Task Breakdown

### Task Group A: Foundation (6 SP)

**A-1: Create ORM Models and Alembic Migration** (2 SP)
- Files: `app/models/ai_versioning.py`, `alembic/versions/20260614_0002_add_ai_versioning_tables.py`
- Details:
  - Implement `AIVersionSnapshot` model with all columns, constraints, and indexes
  - Implement `AIVersionQuota` model for per-course storage tracking
  - Implement `AIVersionRehydrationCache` model
  - Register models in `app/models/__init__.py`
  - Register model import in `alembic/env.py`
  - Generate and test the Alembic migration (both upgrade and downgrade)
  - Verify `Base.metadata.create_all` picks up the new tables

**A-2: Create Pydantic DTOs** (1 SP)
- File: `app/models/ai_versioning_dto.py`
- Details:
  - Implement all request/response DTOs from section 2.3
  - Validate field constraints, descriptions, and type annotations
  - Ensure `model_config = {"from_attributes": True}` on response models

**A-3: Create Version Repository** (3 SP)
- File: `app/repositories/ai_version_repo.py`
- Details:
  - Implement `list_by_course()` with cursor pagination
  - Implement `get_by_version_id()`, `get_by_course_and_number()`, `get_latest_version()`
  - Implement `get_full_snapshot_versions()`, `get_version_chain()` for rehydration
  - Implement `create()` with `get_next_version_number()`
  - Implement quota operations: `get_quota()`, `upsert_quota()`, `get_total_storage_bytes()`
  - Implement cache operations: `get_cached_reification()`, `set_cached_reification()`, `invalidate_reification_cache()`
  - Implement `archive_snapshot()` for pruning
  - Implement cursor encode/decode helpers
  - Unit test: all repo methods with mocked session

### Task Group B: Versioning Service Core (8 SP)

**B-1: Course State Serialization and Hashing** (2 SP)
- File: `app/services/ai/versioning_service.py`
- Details:
  - Implement `_fetch_course_state()`: fetch `CourseRecord` + all `PageRecord`s + all `ComponentRecord`s for a course and serialize to canonical JSON structure
  - Implement `_compute_hash()`: deterministic SHA-256 over the canonical JSON
  - Implement `_compute_diff()`: RFC 6902 JSON Patch between two course states using the `jsonpatch` library
  - Implement `_apply_diff()`: apply a JSON Patch to a course state
  - Handle edge cases: empty course, course with no pages, pages with no components
  - Unit test: serialization fidelity, hash determinism, patch roundtrip

**B-2: Snapshot Creation with Storage Strategy** (3 SP)
- File: `app/services/ai/versioning_service.py`
- Details:
  - Implement `create_snapshot()`: full lifecycle including:
    - Fetch current state
    - Check previous version → decide full vs diff
    - Enforce full interval (every N versions)
    - Enforce max diff size threshold
    - Compute hash
    - Write snapshot record
    - Update quota
    - Invalidate rehydration cache
    - Enforce quota (prune oldest if over limit)
  - Implement `create_initial_snapshot()` for first-time setup
  - Implement `_decide_storage_strategy()` based on configurable rules
  - Edge cases: concurrent snapshot creation (use DB sequence for version_number)
  - Unit test: full/diff decision logic, quota enforcement, concurrent safety

**B-3: Version Rehydration** (2 SP)
- File: `app/services/ai/versioning_service.py`
- Details:
  - Implement `rehydrate_version()`: cache-first then chain-walk
  - Implement `_walk_parent_chain()`: traverse from diff version to nearest full ancestor
  - Handle cache hit (return fast), cache miss (compute and store)
  - Handle chain gap: detect pruned intermediate versions → raise `RehydrationChainGapError`
  - Cache invalidation on new snapshot
  - Unit test: full rehydration, diff chain rehydration, cache hit, chain gap error

**B-4: Version Diff Computation** (1 SP)
- File: `app/services/ai/versioning_service.py`
- Details:
  - Implement `compute_diff()`:
    - Rehydrate both versions
    - Compute metadata-level diff
    - Compute page-level diff (detect added, removed, modified, reordered pages)
    - Compute component-level diff for modified pages
    - Compute aggregate summary
  - Handle same-version diff (empty result)
  - Handle cross-course version comparison (error)
  - Unit test: all page change types, metadata changes, empty diff

### Task Group C: Restore and Storage Management (5 SP)

**C-1: Restore Preview and Proposal** (3 SP)
- File: `app/services/ai/versioning_service.py`
- Details:
  - Implement `compute_restore_preview()`: diff current → target, categorize changes
  - Implement `propose_restore()`:
    - Verify source (audit entry or version ID)
    - Rehydrate target version
    - Create proposal with type='restore'
    - Run validation on candidate state
    - Check for existing pending restore proposal (return 409)
  - Implement full-course restore and single-page restore variants
  - Handle deleted pages, modified pages, metadata conflicts
  - Unit test: all restore scenarios, duplicate detection, conflict detection

**C-2: Storage Quota and Pruning** (2 SP)
- File: `app/services/ai/versioning_service.py`
- Details:
  - Implement `get_quota()` / `update_quota()` with defaults
  - Implement `prune_versions()`: validate constraints, archive snapshots
  - Implement `enforce_quota()`: auto-prune oldest unprotected versions when over limit
  - Implement `verify_snapshot_integrity()`: re-compute hash, compare to stored
  - Edge cases: prune current version (rejected), prune protected window (rejected), concurrent prune and snapshot
  - Unit test: quota enforcement, prune validation, integrity check

### Task Group D: Router and Integration (4 SP)

**D-1: Create Versioning Router** (2 SP)
- File: `app/routers/ai_versioning.py`
- Details:
  - Implement admin router: all version list, detail, diff, label, reify, quota, prune endpoints
  - Implement author router: lightweight version list
  - Add admin/author authorization dependency injection
  - Register both routers in `app/main.py`
  - Add feature flag gating for versioning (`FEATURE_AI_VERSIONING`)
  - Structured error responses matching existing patterns
  - Integration test: all endpoints with seeded data

**D-2: Integrate Snapshot Creation into Apply Service** (1 SP)
- File: `app/services/ai/apply_service.py` (requires coordination with US-AI-010)
- Details:
  - Add `VersioningService.create_snapshot()` call inside the apply transaction
  - Capture source, source_id, created_by, summary from the proposal context
  - Ensure the snapshot write is in the same DB transaction as the mutation
  - Handle versioning service failure gracefully (log warning, don't block apply)

**D-3: Feature Flags and Configuration** (1 SP)
- Files: `app/utils/feature_flags.py`, `.env.example`
- Details:
  - Add `FEATURE_AI_VERSIONING` flag
  - Add env vars from section 2.10 to `.env.example`
  - Wire feature flag into router registration
  - Add configuration defaults for all versioning settings

### Task Group E: Testing (6 SP)

**E-1: Unit Tests** (2 SP)
- Files: `tests/unit/ai/test_version_repo.py`, `tests/unit/ai/test_versioning_service.py`
- Details:
  - Mock SQLAlchemy session for repository tests
  - Test all filter combinations, pagination, cursor operations
  - Test snapshot creation with full/diff strategy decisions
  - Test rehydration with chain walking and caching
  - Test diff computation with all change types
  - Test restore preview and proposal creation
  - Test quota enforcement and pruning logic
  - Test edge cases: empty course, missing pages, chain gaps

**E-2: Integration Tests** (2 SP)
- File: `tests/integration/ai/test_versioning_api.py`
- Details:
  - Seed test database with courses, pages, components, and version snapshots
  - Test all endpoints with real HTTP client
  - Test pagination across result pages
  - Test diff computation end-to-end
  - Test restore preview, proposal, and validation chain
  - Test feature flag gating
  - Test authorization enforcement (admin vs author)
  - Test quota and pruning workflows

**E-3: Performance and Storage Benchmark** (2 SP)
- File: `tests/performance/test_versioning_perf.py`
- Details:
  - Create a 50-page course and generate 100 version snapshots
  - Measure: per-snapshot creation latency, storage per snapshot, total storage
  - Measure: rehydration latency (cold chain of 10 diffs vs cached)
  - Measure: diff computation latency between distant versions
  - Measure: restore preview computation latency
  - Verify: full snapshots every 10 versions, diff size thresholds met
  - Report: p50/p95/p99 latencies, total storage used, compression ratio (full vs diff)

### Task Group F: Documentation and Operations (2 SP)

**F-1: API Documentation** (1 SP)
- Details:
  - Verify OpenAPI spec renders all new routes with correct schemas
  - Add route summaries and descriptions matching section 2.4
  - Document admin vs author access levels
  - Document pagination and cursor usage

**F-2: Operations Runbook** (1 SP)
- Details:
  - Document versioning configuration (retention, quotas, thresholds)
  - Document restore procedure with step-by-step instructions
  - Document storage monitoring and alerting
  - Document manual pruning and quota management
  - Document troubleshooting: chain gaps, rehydration failures, integrity checks

---

### Summary: Total Effort Estimate

| Task Group | Story Points | Dependencies |
|---|---|---|
| A: Foundation (Models, Repo, Migration) | 6 | US-AI-004 (DB patterns), US-AI-020 (audit patterns) |
| B: Versioning Service Core | 8 | A completed |
| C: Restore and Storage Management | 5 | B completed |
| D: Router and Integration | 4 | B, C completed, US-AI-010 (apply hook), US-AI-009 (proposal lifecycle) |
| E: Testing | 6 | A-D completed |
| F: Documentation | 2 | E completed |
| **Total** | **31 SP** | |

### Dependencies on Other Stories

| Story | Dependency | Notes |
|---|---|---|
| US-AI-004 | Required | DB patterns, `ai_proposals` table for restore proposals |
| US-AI-009 | Required | Proposal lifecycle states for restore-proposal flow |
| US-AI-010 | Required | Apply service hook for snapshot creation on mutation |
| US-AI-020 | Required | `ai_audit_logs.before_snapshot` for linking versions to audit entries |
| US-AI-002 | Required | Feature flags infra for `FEATURE_AI_VERSIONING` |
| US-AI-030 | Related | Course assembly ensures editor reads version-restored content correctly |
| US-AI-042 | Related | System prompt versioning can use similar storage patterns |
