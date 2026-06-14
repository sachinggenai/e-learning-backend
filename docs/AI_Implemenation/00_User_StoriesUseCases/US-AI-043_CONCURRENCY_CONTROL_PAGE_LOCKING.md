# US-AI-043 -- Concurrency Control and Page Locking for AI Sessions

**Priority:** MUST
**Depends on:** US-AI-010
**Status:** Draft
**Target Release:** Phase 2
**Last Updated:** 2026-06-14

---

## 1. FUNCTIONAL SPECIFICATION

### User Story

As an Author using the AI authoring assistant, I want the system to prevent other users or AI sessions from concurrently editing the same course page that I am currently editing, so that my changes are not overwritten silently and I receive clear feedback when a page is locked by another session. As an Admin, I want configurable lock timeouts and the ability to release stale locks, so that accidentally locked pages do not block authors indefinitely.

### Functional Requirements

**FR-001 -- Page Lock Acquisition on Proposal Creation:** When any `propose_*` tool (propose_create_page, propose_update_page, propose_delete_page) is invoked for a specific page, the system MUST acquire an exclusive write lock on that page, scoped to the originating AI session. If the page is already locked by a different session, the proposal MUST be rejected with a `PAGE_LOCKED` error that includes the identity of the lock holder and the estimated remaining lock duration.

**FR-002 -- Lock Types and Hierarchy:** The system MUST support three lock levels: (a) READ lock -- held automatically for the duration of a `fetch_page` or `list_pages` call, allowing multiple concurrent readers; (b) WRITE lock -- held from the first `propose_*` call until the proposal is applied, rejected, or expired, preventing any other session from reading or writing the same page; (c) SESSION lock -- held at the AI session level on the entire course, preventing other AI sessions from starting on the same course while one is active. READ locks never block other READ locks. WRITE locks block both READ and WRITE from other sessions. SESSION locks block session creation entirely for the same course.

**FR-003 -- Lock Expiry and Heartbeat Mechanism:** Every lock MUST have a configurable time-to-live (TTL). The default TTL for a WRITE lock is 15 minutes, refreshed automatically on each tool call from the holding session. A heartbeat endpoint `POST /api/v1/ai/locks/{lock_id}/heartbeat` MUST be available for the frontend to extend the lock TTL by a configurable interval (default 5 minutes). If the TTL expires without a heartbeat, the lock is released automatically and all pending operations for that session on the locked resource fail with a `LOCK_EXPIRED` error.

**FR-004 -- Lock-Conflict Queue with Notification:** When a session attempts to acquire a lock on a page already WRITE-locked by another session, the requesting session SHALL be offered an optional position in a FIFO queue. When the lock is released, the next session in the queue receives a notification (via outbox event or polling endpoint `GET /api/v1/ai/locks/{page_id}/queue`). The queued session may then attempt to acquire the lock again. Queue positions have a configurable max wait time (default 30 minutes), after which the queue entry expires.

**FR-005 -- Admin Lock Management Endpoints:** Admin users SHALL have endpoints to: (a) list all active locks with metadata (lock ID, page ID, session ID, user ID, lock type, acquired at, TTL); (b) forcefully release a lock by lock ID; (c) configure lock TTL defaults per organization. Forceful release requires explicit admin confirmation and logs a security event.

**FR-006 -- Lock Visualization in UI:** The frontend SHALL display lock status indicators: (a) when viewing a page in the editor, a lock icon with the holding user's name if the page is WRITE-locked; (b) when initiating a proposal, an immediate feedback message if the page is locked, showing who holds the lock and how long until auto-release; (c) a lock status panel showing all locks held by the current session.

**FR-007 -- Stale Lock Detection and Recovery:** On application startup and at regular intervals (every 60 seconds), a background task SHALL scan all active locks for expired TTLs and auto-release them. When a lock is released due to expiry, the system SHALL: (a) invalidate any open proposals associated with that session for the locked page; (b) write an audit event with reason `STALE_LOCK_RELEASED`; (c) notify the next session in the conflict queue if any. Sessions whose locks expire while they are still active SHALL receive an error on the next tool call and must re-acquire locks before continuing.

**FR-008 -- Optimistic Concurrency for Read Operations:** For read-only operations (`fetch_page`, `list_pages`), the system SHALL use optimistic concurrency via a `version_hash` or `updated_at` timestamp on the PageRecord. Every `fetch_page` response includes the current version hash. If a later `propose_update_page` provides a stale version hash that does not match the current database value, the proposal is rejected with `STALE_BASE_VERSION` error, forcing the AI agent to re-fetch and re-propose.

### User Flow: Happy Path

1. Author Alice opens AI chat panel for Course C1. The system creates an AI session (S-A) and acquires a SESSION lock on Course C1.
2. Author Bob, on a different machine, attempts to open AI chat for Course C1. The system rejects session creation with error `COURSE_LOCKED`, showing "Alice is currently authoring this course with AI. Try again later or contact your admin."
3. Alice types "Update the introduction page to be more concise." The AI calls `fetch_page(pageId=P42)`, which acquires a transient READ lock (released when the response is sent). The response includes `version_hash="abc123"`.
4. AI calls `propose_update_page(pageId=P42, patch={...})`. The system verifies `version_hash="abc123"` matches the current DB value, then acquires a WRITE lock on page P42 for session S-A and returns a proposal ID.
5. The frontend shows a lock icon on page P42 in the page list, indicating "You are editing this page."
6. Alice approves the proposal. The system applies the change, releases the WRITE lock, and logs the audit event.

### User Flow: Error Path -- Page Locked by Another Session

1. Author Alice holds a WRITE lock on page P42 via session S-A.
2. Author Bob opens AI chat for a different course (Course C2 -- session creation succeeds).
3. Bob navigates to Course C1's page list and clicks "Edit with AI" on page P42.
4. The AI calls `propose_update_page(pageId=P42)`. The system checks locks, finds Alice's WRITE lock, and returns:
   ```json
   {
     "status": "error",
     "code": "PAGE_LOCKED",
     "message": "Page 'Introduction' is locked by Alice (session S-A). Auto-release in ~12 minutes.",
     "details": {
       "pageId": "P42",
       "lockHolderUserId": "user-alice-uuid",
       "lockHolderName": "Alice",
       "lockAcquiredAt": "2026-06-14T10:30:00Z",
       "ttlSecondsRemaining": 720,
       "queueAvailable": true
     },
     "retryable": false
   }
   ```
5. The frontend renders a lock notification: "Page 'Introduction' is being edited by Alice. You can wait in queue or edit another page."
6. Bob clicks "Notify me when available." The system adds Bob's session S-B to a FIFO queue for page P42.
7. When Alice's session releases the lock (apply or timeout), the system pops S-B from the queue, sends an outbox event, and Bob's frontend receives a notification.

### UI/UX Requirements

- **Page List Lock Indicator:** A small lock icon (closed for WRITE-locked, open for READ-locked) next to each page title in the page list view, with a tooltip showing "Editing by {user_name}" when hovered.
- **Proposal Lock Banner:** When a proposal is attempted on a locked page, the chat panel shows a persistent banner at the top: "This page is locked by {user_name}. Changes cannot be proposed until the lock is released." Includes a "Notify me" button.
- **Session Lock Banner:** When an AI session cannot be created because another session holds a SESSION lock on the course, the UI shows: "{user_name} is currently authoring this course. AI authoring is unavailable until they finish."
- **Lock Status Panel:** A collapsible panel in the AI sidebar showing all locks held by the current session: page titles, lock types, time remaining, and a "Release Now" button for each lock.
- **Admin Lock Dashboard:** A dedicated admin view listing all active locks, filterable by user, course, page, and lock type. Each row has a "Force Release" button with a confirmation dialog.
- **Queue Indicator:** When a session is in a lock-conflict queue, show "Position #{n} in queue for page '{title}'" in the chat panel, updated via polling every 30 seconds.

---

## 2. TECHNICAL SPECIFICATION

### API Contracts

#### 2.1 Lock Acquisition (Automatic via Tool Calls)

Locks are acquired implicitly when tool endpoints are called. The following endpoints participate in locking:

| Endpoint | Lock Type | Duration |
|---|---|---|
| `POST /api/v1/ai/tools/fetch_page` | READ (transient) | Duration of request |
| `POST /api/v1/ai/tools/list_pages` | None | N/A |
| `POST /api/v1/ai/tools/propose_create_page` | WRITE (on new page ID, if known) | TTL + heartbeat |
| `POST /api/v1/ai/tools/propose_update_page` | WRITE (on target pageId) | TTL + heartbeat |
| `POST /api/v1/ai/tools/propose_delete_page` | WRITE (on target pageId) | TTL + heartbeat |
| `POST /api/v1/ai/tools/apply_page_proposal` | WRITE (held, released after apply) | TTL + heartbeat |
| `POST /api/v1/ai/tools/apply_update_proposal` | WRITE (held, released after apply) | TTL + heartbeat |
| `POST /api/v1/ai/tools/confirm_delete_page` | WRITE (held, released after delete) | TTL + heartbeat |
| `POST /api/v1/ai/sessions` | SESSION (on course) | Session lifetime |

#### 2.2 Lock Management API

**POST /api/v1/ai/locks/{lock_id}/heartbeat**
Extend the TTL of a lock by the configured heartbeat interval.

Request:
```json
{
  "sessionId": "uuid-of-session"
}
```

Response (200):
```json
{
  "lockId": "uuid-of-lock",
  "lockType": "write",
  "resourceType": "page",
  "resourceId": "page-uuid-P42",
  "ttlSecondsRemaining": 300,
  "extendedUntil": "2026-06-14T11:00:00Z"
}
```

Error (403):
```json
{
  "status": "error",
  "code": "LOCK_SESSION_MISMATCH",
  "message": "Lock uuid-of-lock is held by session S-A, not by session S-B.",
  "retryable": false
}
```

Error (404):
```json
{
  "status": "error",
  "code": "LOCK_NOT_FOUND",
  "message": "Lock uuid-of-lock does not exist or has expired.",
  "retryable": false
}
```

**GET /api/v1/ai/locks**
List all active locks for the current organization. Admin-only.

Query parameters: `?resource_type=page&resource_id=P42&lock_type=write&session_id=S-A&user_id=uuid&include_expired=false&limit=50&offset=0`

Response (200):
```json
{
  "locks": [
    {
      "lockId": "uuid-of-lock",
      "lockType": "write",
      "resourceType": "page",
      "resourceId": "page-uuid-P42",
      "resourceName": "Introduction",
      "sessionId": "uuid-session-S-A",
      "userId": "uuid-user-alice",
      "userName": "Alice",
      "courseId": "uuid-course-C1",
      "courseName": "Data Science Fundamentals",
      "acquiredAt": "2026-06-14T10:30:00Z",
      "expiresAt": "2026-06-14T10:45:00Z",
      "ttlSeconds": 900,
      "heartbeatCount": 3,
      "lastHeartbeatAt": "2026-06-14T10:40:00Z"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

**DELETE /api/v1/ai/locks/{lock_id}**
Force-release a lock. Admin-only. Requires `X-Admin-Override: true` header and a reason in the body.

Request:
```json
{
  "reason": "Admin override -- Alice is on PTO and her session is stale.",
  "confirmForceRelease": true
}
```

Response (200):
```json
{
  "lockId": "uuid-of-lock",
  "status": "released",
  "releasedAt": "2026-06-14T11:00:00Z",
  "releasedBy": "admin-user-uuid",
  "reason": "Admin override -- Alice is on PTO and her session is stale.",
  "openProposalsInvalidated": 2,
  "queueNotified": true
}
```

**GET /api/v1/ai/locks/{resource_type}/{resource_id}/queue**
Get the current conflict queue for a resource.

Response (200):
```json
{
  "resourceType": "page",
  "resourceId": "page-uuid-P42",
  "currentLock": {
    "lockId": "uuid-of-lock",
    "heldBy": "Alice",
    "expiresAt": "2026-06-14T10:45:00Z"
  },
  "queue": [
    {
      "position": 1,
      "sessionId": "uuid-session-S-B",
      "userId": "uuid-user-bob",
      "userName": "Bob",
      "enqueuedAt": "2026-06-14T10:32:00Z",
      "expiresAt": "2026-06-14T11:02:00Z"
    }
  ],
  "queueLength": 1
}
```

**POST /api/v1/ai/locks/{resource_type}/{resource_id}/queue**
Join the conflict queue for a resource.

Request:
```json
{
  "sessionId": "uuid-session-S-B"
}
```

Response (201):
```json
{
  "position": 1,
  "queueEntryId": "uuid-queue-entry",
  "estimatedWaitSeconds": 720,
  "queueExpiresAt": "2026-06-14T11:02:00Z"
}
```

**DELETE /api/v1/ai/locks/queue/{queue_entry_id}**
Leave the conflict queue.

Response (200):
```json
{
  "status": "removed",
  "queueEntryId": "uuid-queue-entry"
}
```

#### 2.3 Lock-Enriched Tool Responses

The following are modified API responses for existing tools, now including lock metadata.

**`propose_update_page` response (when page is not locked):**
```json
{
  "proposalId": "uuid-proposal",
  "diff": {
    "before": { ... },
    "after": { ... },
    "changedFields": ["title"]
  },
  "validationStatus": "valid",
  "validationMessages": [],
  "lock": {
    "lockId": "uuid-lock",
    "lockType": "write",
    "acquiredAt": "2026-06-14T10:30:00Z",
    "ttlSeconds": 900,
    "ttlSecondsRemaining": 840
  }
}
```

**`propose_update_page` response (when page IS locked by another session):**
```json
{
  "status": "error",
  "code": "PAGE_LOCKED",
  "message": "This page is currently locked by another session.",
  "details": {
    "pageId": "P42",
    "lockHolderName": "Alice",
    "ttlSecondsRemaining": 720,
    "queueAvailable": true,
    "queueEndpoint": "/api/v1/ai/locks/page/P42/queue"
  },
  "retryable": false
}
```

**`POST /api/v1/ai/sessions` response (when course has SESSION lock):**
```json
{
  "status": "error",
  "code": "COURSE_LOCKED",
  "message": "Course 'Data Science Fundamentals' is currently being authored by Alice via AI session S-A. Only one AI session per course is allowed.",
  "details": {
    "courseId": "C1",
    "lockHolderUserId": "uuid-user-alice",
    "lockHolderName": "Alice",
    "sessionExpiresAt": "2026-06-15T10:30:00Z"
  },
  "retryable": true
}
```

### Database Schema DDL

#### Table: `ai_locks`

```sql
CREATE TABLE ai_locks (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lock_type               VARCHAR(16) NOT NULL CHECK (lock_type IN ('read', 'write', 'session')),
    resource_type           VARCHAR(32) NOT NULL CHECK (resource_type IN ('page', 'course', 'component')),
    resource_id             VARCHAR(255) NOT NULL,
    resource_name           VARCHAR(255),
    session_id              UUID NOT NULL REFERENCES ai_sessions(id) ON DELETE CASCADE,
    user_id                 UUID NOT NULL,
    organization_id         UUID NOT NULL,
    course_id               VARCHAR(64) NOT NULL,
    acquired_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at              TIMESTAMPTZ NOT NULL,
    ttl_seconds             INTEGER NOT NULL DEFAULT 900,
    heartbeat_count         INTEGER NOT NULL DEFAULT 0,
    last_heartbeat_at       TIMESTAMPTZ,
    is_expired              BOOLEAN NOT NULL DEFAULT FALSE,
    released_at             TIMESTAMPTZ,
    released_by             UUID,
    release_reason          VARCHAR(255),
    metadata                JSONB DEFAULT '{}'::jsonb,

    CONSTRAINT uq_lock_resource UNIQUE (resource_type, resource_id, lock_type) DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX idx_ai_locks_session ON ai_locks(session_id);
CREATE INDEX idx_ai_locks_user ON ai_locks(user_id);
CREATE INDEX idx_ai_locks_organization ON ai_locks(organization_id);
CREATE INDEX idx_ai_locks_resource ON ai_locks(resource_type, resource_id);
CREATE INDEX idx_ai_locks_expires ON ai_locks(expires_at) WHERE is_expired = FALSE;
CREATE INDEX idx_ai_locks_course ON ai_locks(course_id);
```

#### Table: `ai_lock_queue`

```sql
CREATE TABLE ai_lock_queue (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resource_type       VARCHAR(32) NOT NULL CHECK (resource_type IN ('page', 'course', 'component')),
    resource_id         VARCHAR(255) NOT NULL,
    session_id          UUID NOT NULL REFERENCES ai_sessions(id) ON DELETE CASCADE,
    user_id             UUID NOT NULL,
    organization_id     UUID NOT NULL,
    course_id           VARCHAR(64) NOT NULL,
    enqueued_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at          TIMESTAMPTZ NOT NULL,
    position            INTEGER NOT NULL,
    notified_at         TIMESTAMPTZ,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,

    CONSTRAINT uq_queue_entry UNIQUE (resource_type, resource_id, session_id)
);

CREATE INDEX idx_ai_lock_queue_resource ON ai_lock_queue(resource_type, resource_id, position) WHERE is_active = TRUE;
CREATE INDEX idx_ai_lock_queue_session ON ai_lock_queue(session_id) WHERE is_active = TRUE;
```

#### Table: `ai_lock_config` (per-organization lock policy)

```sql
CREATE TABLE ai_lock_config (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id             UUID NOT NULL UNIQUE,
    session_lock_enabled        BOOLEAN NOT NULL DEFAULT TRUE,
    write_lock_ttl_seconds      INTEGER NOT NULL DEFAULT 900,
    read_lock_ttl_seconds       INTEGER NOT NULL DEFAULT 30,
    heartbeat_interval_seconds  INTEGER NOT NULL DEFAULT 300,
    queue_max_wait_seconds      INTEGER NOT NULL DEFAULT 1800,
    max_locks_per_session       INTEGER NOT NULL DEFAULT 10,
    stale_lock_scan_interval    INTEGER NOT NULL DEFAULT 60,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### Modifications to `ai_sessions` (from US-AI-004)
Add column for COURSE-level session lock:

```sql
ALTER TABLE ai_sessions ADD COLUMN session_lock_id UUID REFERENCES ai_locks(id);
ALTER TABLE ai_sessions ADD COLUMN course_lock_status VARCHAR(16) DEFAULT 'unlocked'
    CHECK (course_lock_status IN ('unlocked', 'locked', 'released'));
```

#### Modifications to `ai_proposals` (from US-AI-004)
Add column to track associated locks:

```sql
ALTER TABLE ai_proposals ADD COLUMN write_lock_id UUID REFERENCES ai_locks(id);
ALTER TABLE ai_proposals ADD COLUMN base_version_hash VARCHAR(64);
```

### Service / Module Design

#### Module: `app/services/ai/lock_manager.py`

```python
"""
Lock Manager Service

Central authority for all concurrency control in the AI authoring system.
Handles lock acquisition, release, heartbeat, expiry, and conflict queues.
"""
from __future__ import annotations
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import uuid

from sqlalchemy.ext.asyncio import AsyncSession


class LockType(str, Enum):
    READ = "read"
    WRITE = "write"
    SESSION = "session"


class ResourceType(str, Enum):
    PAGE = "page"
    COURSE = "course"
    COMPONENT = "component"


class LockAcquireResult:
    """Result of a lock acquisition attempt."""

    def __init__(
        self,
        acquired: bool,
        lock_id: Optional[str] = None,
        lock: Optional["ActiveLock"] = None,
        conflict: Optional["LockConflict"] = None,
    ):
        self.acquired = acquired
        self.lock_id = lock_id
        self.lock = lock
        self.conflict = conflict


class LockConflict:
    """Details about a lock conflict."""

    def __init__(
        self,
        code: str,
        message: str,
        lock_holder_name: str,
        lock_holder_user_id: str,
        ttl_seconds_remaining: int,
        queue_available: bool,
        queue_endpoint: str,
    ):
        self.code = code
        self.message = message
        self.lock_holder_name = lock_holder_name
        self.lock_holder_user_id = lock_holder_user_id
        self.ttl_seconds_remaining = ttl_seconds_remaining
        self.queue_available = queue_available
        self.queue_endpoint = queue_endpoint


class LockManager:
    """
    LockManager is the central service for concurrency control.

    Responsibilities:
    1. Acquire locks (READ, WRITE, SESSION) with conflict detection.
    2. Release locks on apply, reject, expire, or admin override.
    3. Manage lock heartbeats to extend TTL.
    4. Manage conflict queues (FIFO per resource).
    5. Run stale lock detection and cleanup.
    6. Enforce per-session and per-organization lock limits.
    """

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def acquire_lock(
        self,
        lock_type: LockType,
        resource_type: ResourceType,
        resource_id: str,
        resource_name: Optional[str],
        session_id: str,
        user_id: str,
        organization_id: str,
        course_id: str,
        ttl_seconds: Optional[int] = None,
    ) -> LockAcquireResult:
        """
        Attempt to acquire a lock.

        For WRITE locks: checks if any other active WRITE lock exists on the
        same resource. If so, returns a LockConflict with queue options.
        For READ locks: allows concurrent READs; blocks if WRITE lock held.
        For SESSION locks: checks if any other active SESSION lock exists on
        the same course (only one AI session per course).

        Implementation notes:
        - Uses a database transaction with SELECT FOR UPDATE on the resource
          to prevent race conditions during lock acquisition.
        - Inserts into ai_locks table with the given TTL.
        - Returns the lock_id and lock details on success.
        """
        ...

    async def release_lock(
        self,
        lock_id: str,
        session_id: str,
        reason: Optional[str] = None,
        released_by: Optional[str] = None,
    ) -> bool:
        """
        Release a lock. Validates that the requesting session owns the lock
        (unless admin override, indicated by released_by).

        On release:
        1. Set is_expired = TRUE and released_at = now().
        2. If any proposals reference this lock_id, set their status to
           LOCK_RELEASED.
        3. Notify the next session in the conflict queue (if any).
        4. Write an audit event with lock release details.
        """
        ...

    async def heartbeat(
        self, lock_id: str, session_id: str
    ) -> Optional[dict]:
        """
        Extend the TTL of a lock by heartbeat_interval_seconds.
        Validates session ownership. Updates expires_at and
        increments heartbeat_count.
        """
        ...

    async def get_active_lock(
        self,
        resource_type: ResourceType,
        resource_id: str,
        lock_type: Optional[LockType] = None,
    ) -> Optional["ActiveLock"]:
        """
        Retrieve the current active lock for a resource, if any.
        Returns None if no lock is held or the lock has expired.
        """
        ...

    async def list_active_locks(
        self,
        organization_id: Optional[str] = None,
        resource_type: Optional[ResourceType] = None,
        resource_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        include_expired: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[List["ActiveLock"], int]:
        """
        List active locks with filtering and pagination.
        Used by the admin dashboard and lock status panel.
        """
        ...

    async def enqueue(
        self,
        resource_type: ResourceType,
        resource_id: str,
        session_id: str,
        user_id: str,
        organization_id: str,
        course_id: str,
    ) -> dict:
        """
        Add a session to the FIFO conflict queue for a resource.
        Returns queue position and estimated wait time.
        """
        ...

    async def dequeue(self, queue_entry_id: str, session_id: str) -> bool:
        """
        Remove a session from the conflict queue.
        """
        ...

    async def notify_next_in_queue(
        self, resource_type: ResourceType, resource_id: str
    ) -> Optional[str]:
        """
        Pop the next session from the queue and notify it that the
        lock is available. Returns the notified session_id.
        """
        ...

    async def scan_and_release_stale_locks(self) -> int:
        """
        Background task: scan all non-expired locks where expires_at < now().
        Release each stale lock and notify the next queue entry.
        Returns the count of released locks.
        """
        ...

    async def force_release_by_admin(
        self,
        lock_id: str,
        admin_user_id: str,
        reason: str,
    ) -> dict:
        """
        Admin-only: forcefully release a lock regardless of session ownership.
        Logs an audit event with admin user ID and reason.
        Invalidates any open proposals tied to this lock.
        Notifies the conflict queue.
        """
        ...

    async def get_lock_config(self, organization_id: str) -> "LockConfig":
        """
        Get the lock configuration for an organization, with defaults
        from application configuration if no per-org config exists.
        """
        ...

    async def update_lock_config(
        self, organization_id: str, config: "LockConfig"
    ) -> "LockConfig":
        """
        Update the lock configuration for an organization.
        """
        ...


class ActiveLock:
    """Represents an active lock fetched from the database."""

    def __init__(self, row: dict):
        self.lock_id: str = row["id"]
        self.lock_type: LockType = LockType(row["lock_type"])
        self.resource_type: ResourceType = ResourceType(row["resource_type"])
        self.resource_id: str = row["resource_id"]
        self.resource_name: Optional[str] = row.get("resource_name")
        self.session_id: str = row["session_id"]
        self.user_id: str = row["user_id"]
        self.organization_id: str = row["organization_id"]
        self.course_id: str = row["course_id"]
        self.acquired_at: datetime = row["acquired_at"]
        self.expires_at: datetime = row["expires_at"]
        self.ttl_seconds: int = row["ttl_seconds"]
        self.heartbeat_count: int = row["heartbeat_count"]
        self.last_heartbeat_at: Optional[datetime] = row.get("last_heartbeat_at")
        self.is_expired: bool = row["is_expired"]

    @property
    def ttl_seconds_remaining(self) -> int:
        delta = self.expires_at - datetime.utcnow()
        return max(0, int(delta.total_seconds()))

    @property
    def is_stale(self) -> bool:
        return datetime.utcnow() >= self.expires_at

    def to_dict(self) -> dict:
        return {
            "lockId": self.lock_id,
            "lockType": self.lock_type.value,
            "resourceType": self.resource_type.value,
            "resourceId": self.resource_id,
            "resourceName": self.resource_name,
            "sessionId": self.session_id,
            "userId": self.user_id,
            "courseId": self.course_id,
            "acquiredAt": self.acquired_at.isoformat(),
            "expiresAt": self.expires_at.isoformat(),
            "ttlSeconds": self.ttl_seconds,
            "ttlSecondsRemaining": self.ttl_seconds_remaining,
            "heartbeatCount": self.heartbeat_count,
            "lastHeartbeatAt": self.last_heartbeat_at.isoformat() if self.last_heartbeat_at else None,
        }


@dataclass
class LockConfig:
    """Per-organization lock configuration."""

    session_lock_enabled: bool = True
    write_lock_ttl_seconds: int = 900  # 15 minutes
    read_lock_ttl_seconds: int = 30    # 30 seconds (transient)
    heartbeat_interval_seconds: int = 300  # 5 minutes
    queue_max_wait_seconds: int = 1800  # 30 minutes
    max_locks_per_session: int = 10
    stale_lock_scan_interval: int = 60  # 60 seconds
```

#### Module: `app/services/ai/lock_middleware.py`

```python
"""
Lock Middleware

FastAPI middleware that automatically acquires/releases locks
for AI tool endpoints based on the tool being called.
"""
from __future__ import annotations
from functools import wraps
from typing import Callable, Awaitable

from app.services.ai.lock_manager import LockManager, LockType, ResourceType


def with_write_lock(resource_id_param: str = "pageId"):
    """
    Decorator for tool handler functions that need a WRITE lock.

    Usage:
        @router.post("/ai/tools/propose_update_page")
        @with_write_lock(resource_id_param="pageId")
        async def propose_update_page(...):
            ...

    The decorator:
    1. Extracts the resource_id from the request body using resource_id_param.
    2. Calls lock_manager.acquire_lock(WRITE, ...).
    3. If conflict: returns PAGE_LOCKED error response.
    4. Passes the lock_id to the handler.
    5. On handler success (apply/reject): releases the lock.
    6. On handler error: keeps the lock (for retry) or releases on session error.
    """
    ...


def with_read_lock(resource_id_param: str = "pageId"):
    """
    Decorator for tool handler functions that need a READ lock.
    """
    ...


def with_session_lock():
    """
    Decorator for session creation that acquires a SESSION lock on the course.
    """
    ...
```

#### Module: `app/services/ai/stale_lock_scanner.py`

```python
"""
Stale Lock Scanner

Background task that runs on a configurable interval to detect and
release expired locks. Runs in a separate asyncio task started at
application startup.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime

from app.services.ai.lock_manager import LockManager
from app.db.config import SessionLocal

logger = logging.getLogger(__name__)


class StaleLockScanner:
    """
    Periodically scans ai_locks for expired entries and releases them.

    Runs every `stale_lock_scan_interval` seconds (configurable per org,
    default 60). On each run:
    1. Queries ai_locks WHERE is_expired = FALSE AND expires_at < now().
    2. For each expired lock:
       a. Sets is_expired = TRUE, released_at = now(), release_reason = 'TTL_EXPIRED'.
       b. Invalidates any open proposals referencing the lock.
       c. Notifies the next session in the conflict queue (if any).
       d. Writes an audit event.
    3. Logs count of released locks.
    """

    def __init__(self, interval_seconds: int = 60):
        self.interval = interval_seconds
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        self._task = asyncio.create_task(self._run_loop())
        logger.info("StaleLockScanner started (interval=%ds)", self.interval)

    async def stop(self):
        if self._task:
            self._task.cancel()
            logger.info("StaleLockScanner stopped")

    async def _run_loop(self):
        while True:
            try:
                async with SessionLocal() as session:
                    manager = LockManager(session)
                    released = await manager.scan_and_release_stale_locks()
                    if released > 0:
                        logger.info("Released %d stale lock(s)", released)
            except Exception as e:
                logger.error("Stale lock scan failed: %s", e)
            await asyncio.sleep(self.interval)
```

#### Integration: Proposal Lifecycle Lock Integration (US-AI-010)

The existing `apply_page_proposal` and `apply_update_proposal` handlers in US-AI-010 MUST be modified to:

1. Before executing an apply, verify that the `write_lock_id` on the proposal is still valid (not expired, owned by the same session).
2. If the lock is expired, reject the apply with `LOCK_EXPIRED` error (HTTP 409).
3. On successful apply, call `lock_manager.release_lock()` with reason `PROPOSAL_APPLIED`.
4. On apply failure, keep the lock to allow retry. If the session gives up, the lock TTL handles release.

#### Integration: Session Creation Lock Integration (US-AI-006)

The `POST /api/v1/ai/sessions` handler MUST be modified to:

1. After creating the session record, attempt to acquire a SESSION lock on the course via `lock_manager.acquire_lock(SESSION, COURSE, courseId, ...)`.
2. If the course is already locked by another session, reject session creation with `COURSE_LOCKED` error.
3. Store the `lock_id` on the session record for cleanup during session teardown.

### Configuration Variables

```python
# In app/core/config.py or environment variables:

# Lock defaults
AI_WRITE_LOCK_TTL_SECONDS: int = 900           # 15 minutes
AI_READ_LOCK_TTL_SECONDS: int = 30             # 30 seconds
AI_HEARTBEAT_INTERVAL_SECONDS: int = 300       # 5 minutes
AI_QUEUE_MAX_WAIT_SECONDS: int = 1800          # 30 minutes
AI_MAX_LOCKS_PER_SESSION: int = 10
AI_STALE_LOCK_SCAN_INTERVAL: int = 60          # 60 seconds
AI_SESSION_LOCK_ENABLED: bool = True

# Lock database settings
AI_LOCK_TABLE_PARTITION_ENABLED: bool = False  # Set True for large-scale deployments
AI_LOCK_CLEANUP_BATCH_SIZE: int = 100          # Batch size for stale lock cleanup
```

### Integration Points

| Integration | Description | Status |
|---|---|---|
| US-AI-006 (Session Creation) | Post-session-creation, acquire SESSION lock on course | Modify |
| US-AI-009 (Proposal Lifecycle) | Add `write_lock_id` and `base_version_hash` to proposals; validate lock on apply | Modify |
| US-AI-010 (Apply Safety) | Verify lock ownership before apply; release lock after apply | Modify |
| US-AI-011 (Create Page) | Acquire WRITE lock during propose; release during apply | Modify |
| US-AI-012 (Update Page) | Acquire WRITE lock during propose; release during apply | Modify |
| US-AI-013 (Delete Page) | Acquire WRITE lock during propose; release during apply | Modify |
| US-AI-023 (Chat Orchestrator) | The chat loop must handle `PAGE_LOCKED` errors gracefully and inform the user | Modify |
| US-AI-024 (Frontend AI Layer) | Add lock status polling, lock indicators, queue UI, lock release button | Modify |
| US-AI-033 (Event Outbox) | Emit `LockAcquired`, `LockReleased`, `LockExpired`, `LockForceReleased` events | New |

---

## 3. NON-FUNCTIONAL REQUIREMENTS

### Performance Targets

- Lock acquisition (READ or WRITE) MUST complete in under 50 milliseconds p95 for uncontended resources.
- Lock acquisition for contended resources (conflict check) MUST complete in under 100 milliseconds p95.
- Heartbeat endpoint MUST respond in under 30 milliseconds p95.
- Stale lock scanner MUST complete a full scan of up to 10,000 active locks within 5 seconds.
- Lock conflict queue poll (`GET /api/v1/ai/locks/{id}/queue`) MUST respond in under 20 milliseconds p95.
- The lock management layer MUST NOT add more than 5 milliseconds overhead to any existing tool call that does not require locking (e.g., `query_similar_courses`).

### Security Requirements

- Lock operations MUST authenticate the requesting session via the `Authorization: Session {sessionId}` header.
- Lock release MUST verify that the requesting session owns the lock, except for admin force-release which requires `X-Admin-Override: true` header AND admin role validation.
- Lock metadata (user names, page titles) MUST respect organization-level data isolation: users from Organization A MUST NOT see locks held by users in Organization B.
- Force-release audit events MUST include admin user ID, timestamp, reason, and lock ID for compliance.
- Lock queue positions MUST NOT leak information about other sessions' activity beyond what is necessary for conflict resolution.

### Reliability Requirements

- Lock state MUST survive backend restarts. All lock data is persisted in PostgreSQL.
- If the lock manager service is temporarily unavailable, tool calls that do not require locking MUST continue to function. Tool calls that require locking MUST fail with a `LOCK_SERVICE_UNAVAILABLE` error and a retry suggestion.
- The stale lock scanner MUST detect and release expired locks within 2x the scan interval (default: within 120 seconds of expiry).
- Heartbeat failures (network partition, frontend crash) MUST result in automatic lock release within 1x TTL + 1x scan interval (default: within 15 + 1 = 16 minutes).

### Scalability Requirements

- The lock system MUST support up to 500 concurrent AI sessions across an organization, each holding up to 10 locks (5,000 total concurrent locks).
- The conflict queue MUST support up to 100 waiting sessions per resource.
- Lock queries MUST use database indexes to avoid full table scans, even with 100,000+ historical (expired) lock records.
- For organizations exceeding 500 concurrent sessions, partition the `ai_locks` table by organization_id.

---

## 4. CURRENT STATE ASSESSMENT

### What Exists

1. **US-AI-004 (AI Persistence Foundations):** Defines `ai_sessions`, `ai_proposals`, `ai_audit_logs`, and `outbox_events` tables but does NOT include any lock tables or concurrency mechanisms.

2. **US-AI-010 (Apply Safety, Audit, and Outbox):** Implements the propose-validate-confirm-apply pipeline with transactional safety. However, there is no lock verification before apply -- two sessions can simultaneously call `apply_page_proposal` for the same page. The last writer wins, silently overwriting the other session's changes.

3. **US-AI-006 (Session Creation):** Creates sessions scoped to a single course per session, but does not enforce single-session-per-course at the database level. Two users can create AI sessions for the same course simultaneously.

4. **`app/utils/version_lock.py`:** This file exists but is completely empty (1 blank line). It was likely intended for optimistic concurrency but was never implemented.

5. **Repositories (`CourseRepository`, `PageRepository`):** Current CRUD operations use simple `SELECT`/`INSERT`/`UPDATE`/`DELETE` without any `SELECT ... FOR UPDATE` locking or version hash checks. Optimistic concurrency is not implemented.

### What Must Be Built

1. **Three new database tables:** `ai_locks`, `ai_lock_queue`, `ai_lock_config` (DDL provided in Section 2).
2. **Lock Manager Service** (`app/services/ai/lock_manager.py`): Full implementation with acquire, release, heartbeat, queue management, stale scan, and admin override.
3. **Lock Middleware / Decorators** (`app/services/ai/lock_middleware.py`): Decorators for automatic lock acquisition on tool endpoints.
4. **Stale Lock Scanner** (`app/services/ai/stale_lock_scanner.py`): Background asyncio task for TTL-based lock cleanup.
5. **Admin Lock API routes** (GET/DELETE locks, GET/DELETE queue, GET/PUT lock config).
6. **Frontend lock status polling and visualization** (lock indicators, queue management, lock panel).

### What Must Be Modified

1. **`ai_sessions` table** -- add `session_lock_id` and `course_lock_status` columns.
2. **`ai_proposals` table** -- add `write_lock_id` and `base_version_hash` columns.
3. **Session creation handler** (`POST /api/v1/ai/sessions`) -- acquire SESSION lock after session record creation.
4. **All propose_* tool handlers** -- acquire WRITE locks; return lock metadata in responses; handle `PAGE_LOCKED` errors.
5. **All apply_* tool handlers** -- verify and release WRITE locks during apply.
6. **Frontend AI integration layer** (US-AI-024) -- add lock status indicators and queue UI.
7. **Chat orchestrator** (US-AI-023) -- handle lock conflict errors gracefully.

---

## 5. EXPANSION POINTS

### Technical Expansion Points

**TXP-01 -- Distributed Lock Backend (Redis/etcd):** For deployments scaling beyond 500 concurrent sessions, replace the PostgreSQL-backed locks with a distributed lock service using Redis (via `aioredlock` or `redis-py` locking primitives) or etcd. PostgreSQL locks will remain the default and will be sufficient for the majority of deployments. The `LockManager` should be designed with a `LockBackend` abstract interface so the backend can be swapped without changing business logic.

**TXP-02 -- Lock Analytics and Heatmaps:** Store historical lock acquisition and contention data in a time-series format. Provide dashboards showing: average lock hold times per template type, contention hotspots (which pages/courses see the most lock conflicts), peak concurrency hours, and queue depth distributions. This data can inform course design guidelines (e.g., "avoid editing assessment pages collaboratively").

**TXP-03 -- Automatic Lock Escalation:** Implement a lock escalation strategy where a session that holds READ locks on multiple pages of the same course can request a SESSION-level lock that covers all pages. This reduces the per-page lock overhead for bulk operations (file ingestion, full-course generation) and prevents deadlock scenarios where Session A holds page 1 and waits for page 2 while Session B holds page 2 and waits for page 1.

**TXP-04 -- Deadlock Detection and Resolution:** Implement a deadlock detector that runs periodically (every 30 seconds) and builds a wait-for graph from the lock queue. If a cycle is detected (Session A waits for page held by Session B, Session B waits for page held by Session A), the system selects a victim session (the one with the smallest total locked resources) and force-releases its locks with a `DEADLOCK_RESOLVED` audit event.

### Functional Expansion Points

**FXP-01 -- Collaborative Editing (Google-Docs-style):** Replace exclusive WRITE locks with operational transformation (OT) or Conflict-Free Replicated Data Types (CRDTs) for real-time collaborative AI authoring. Multiple authors could edit the same page simultaneously, with changes merged automatically. This is a major architectural change and is out of scope for the current story.

**FXP-02 -- Granular Component-Level Locking:** Instead of page-level WRITE locks, implement component-level locks so that two authors can edit different components on the same page simultaneously. For example, Author A edits the text content component while Author B edits the assessment component. This requires changes to the proposal system to scope proposals to individual components rather than entire pages.

**FXP-03 -- Scheduled Lock Release Notifications:** Allow users to schedule a lock release at a specific future time (e.g., "Release this lock at 5 PM today whether I'm done or not"). The stale lock scanner would be extended to handle scheduled releases in addition to TTL-based releases.

**FXP-04 -- Read-Only Collaboration Mode:** Allow a user to share a "read-only" view of their locked page with another user, who can see the in-progress changes but cannot edit. This would use the existing READ lock mechanism, granting a READ lock to a collaborator even while the primary author holds a WRITE lock.

---

## 6. VALIDATION AND TESTING

### Unit Tests (5+)

**UT-01 -- Lock Acquisition and Release Cycle:**
Test that a WRITE lock can be acquired on a page, that the lock `is_expired` is FALSE, that `ttl_seconds_remaining` is approximately equal to the configured TTL, and that releasing the lock sets `is_expired = TRUE` and `released_at` is populated.

```python
async def test_lock_acquire_release_cycle(lock_manager: LockManager, db_session):
    result = await lock_manager.acquire_lock(
        lock_type=LockType.WRITE,
        resource_type=ResourceType.PAGE,
        resource_id="page-42",
        resource_name="Introduction",
        session_id="session-alice",
        user_id="user-alice",
        organization_id="org-1",
        course_id="course-C1",
    )
    assert result.acquired is True
    assert result.lock is not None
    assert result.lock.lock_type == LockType.WRITE
    assert result.lock.ttl_seconds_remaining > 800  # Default TTL is 900

    released = await lock_manager.release_lock(
        lock_id=result.lock.lock_id,
        session_id="session-alice",
        reason="PROPOSAL_APPLIED",
    )
    assert released is True

    active = await lock_manager.get_active_lock(
        resource_type=ResourceType.PAGE,
        resource_id="page-42",
    )
    assert active is None  # Lock should be released
```

**UT-02 -- Write Lock Blocks Other Write Locks:**
Test that acquiring a second WRITE lock on the same page returns a `LockConflict`.

```python
async def test_write_lock_conflict(lock_manager: LockManager, db_session):
    # Session A acquires lock
    result_a = await lock_manager.acquire_lock(...)
    assert result_a.acquired is True

    # Session B tries to acquire lock on same page
    result_b = await lock_manager.acquire_lock(...)
    assert result_b.acquired is False
    assert result_b.conflict is not None
    assert result_b.conflict.code == "PAGE_LOCKED"
    assert result_b.conflict.queue_available is True
```

**UT-03 -- Read Locks Do Not Block Other Read Locks:**
Test that multiple READ locks can be held concurrently on the same resource.

```python
async def test_read_lock_concurrent(lock_manager: LockManager, db_session):
    result_a = await lock_manager.acquire_lock(
        lock_type=LockType.READ, resource_type=ResourceType.PAGE, resource_id="page-42", ...
    )
    assert result_a.acquired is True

    result_b = await lock_manager.acquire_lock(
        lock_type=LockType.READ, resource_type=ResourceType.PAGE, resource_id="page-42", ...
    )
    assert result_b.acquired is True  # READ locks don't block
```

**UT-04 -- Write Lock Blocks Read Lock:**
Test that a READ lock acquisition is blocked when a WRITE lock is held.

```python
async def test_write_lock_blocks_read(lock_manager: LockManager, db_session):
    result_w = await lock_manager.acquire_lock(lock_type=LockType.WRITE, ...)
    assert result_w.acquired is True

    result_r = await lock_manager.acquire_lock(lock_type=LockType.READ, ...)
    assert result_r.acquired is False
    assert result_r.conflict.code == "PAGE_LOCKED"
```

**UT-05 -- Heartbeat Extends TTL:**
Test that calling heartbeat on a lock extends its `expires_at` by the heartbeat interval.

```python
async def test_heartbeat_extends_ttl(lock_manager: LockManager, db_session):
    result = await lock_manager.acquire_lock(...)
    original_expires = result.lock.expires_at

    await asyncio.sleep(1)  # Let time pass

    heartbeat = await lock_manager.heartbeat(result.lock.lock_id, "session-alice")
    assert heartbeat is not None
    assert heartbeat["ttlSecondsRemaining"] > 250  # Should have been extended
```

**UT-06 -- Stale Lock Detection:**
Test that a lock with `expires_at` in the past is released by the scanner.

```python
async def test_stale_lock_detection(lock_manager: LockManager, db_session):
    # Acquire lock with 0-second TTL (will be expired immediately)
    result = await lock_manager.acquire_lock(..., ttl_seconds=0)
    assert result.acquired is True

    # Run stale lock scanner
    released_count = await lock_manager.scan_and_release_stale_locks()
    assert released_count == 1

    # Lock should no longer be active
    active = await lock_manager.get_active_lock(...)
    assert active is None
```

### Integration Tests (3+)

**IT-01 -- Full Lock Lifecycle via API:**
Test the full lifecycle through the API: propose_update_page (acquires WRITE lock) -> heartbeat -> apply (releases lock) -> verify lock is released via GET /api/v1/ai/locks.

```python
async def test_lock_lifecycle_via_api(async_client, auth_headers, sample_course):
    # Create session
    session_resp = await async_client.post("/api/v1/ai/sessions", json={
        "userId": "user-alice", "courseId": sample_course.course_id, "organizationId": "org-1"
    })
    session_id = session_resp.json()["sessionId"]

    # Propose update (should acquire WRITE lock automatically)
    propose_resp = await async_client.post(
        "/api/v1/ai/tools/propose_update_page",
        headers={"Authorization": f"Session {session_id}"},
        json={"sessionId": session_id, "input": {"pageId": "page-1", "patch": {"title": "New Title"}}},
    )
    assert propose_resp.status_code == 200
    assert "lock" in propose_resp.json()
    lock_id = propose_resp.json()["lock"]["lockId"]

    # Verify lock appears in active locks list
    locks_resp = await async_client.get("/api/v1/ai/locks", headers=auth_headers)
    lock_ids = [l["lockId"] for l in locks_resp.json()["locks"]]
    assert lock_id in lock_ids

    # Apply update (should release lock)
    apply_resp = await async_client.post(
        "/api/v1/ai/tools/apply_update_proposal",
        headers={"Authorization": f"Session {session_id}"},
        json={"sessionId": session_id, "input": {"proposalId": propose_resp.json()["proposalId"], "userConfirmed": True}},
    )
    assert apply_resp.status_code == 200

    # Lock should be released
    locks_after = await async_client.get("/api/v1/ai/locks", headers=auth_headers)
    assert lock_id not in [l["lockId"] for l in locks_after.json()["locks"]]
```

**IT-02 -- Concurrent Session Rejection on Same Course:**
Test that creating a second AI session for the same course is rejected.

```python
async def test_concurrent_session_rejection(async_client, auth_headers, sample_course):
    # First session
    resp1 = await async_client.post("/api/v1/ai/sessions", json={
        "userId": "user-alice", "courseId": sample_course.course_id, "organizationId": "org-1"
    })
    assert resp1.status_code == 200

    # Second session (same course, same org, different user)
    resp2 = await async_client.post("/api/v1/ai/sessions", json={
        "userId": "user-bob", "courseId": sample_course.course_id, "organizationId": "org-1"
    })
    assert resp2.status_code == 409
    assert resp2.json()["code"] == "COURSE_LOCKED"
    assert resp2.json()["details"]["lockHolderName"] == "Alice"
```

**IT-03 -- Conflict Queue Notification Flow:**
Test that queuing for a locked page results in notification when the lock is released.

```python
async def test_conflict_queue_notification(async_client, auth_headers, sample_course):
    # Session A acquires lock on page
    # Session B joins queue
    # Session A releases lock
    # Session B's queue entry is marked as notified
    ...
```

### End-to-End Tests (2+)

**E2E-01 -- User Sees Lock Indicator and Cannot Propose on Locked Page:**
1. Alice opens AI chat for Course C1, navigates to page "Introduction", starts a proposal.
2. Bob opens AI chat for Course C2 (different course, succeeds).
3. Bob navigates to Course C1 page list, clicks "Edit with AI" on page "Introduction".
4. Bob types "Update this page". The AI calls `propose_update_page`.
5. The chat panel shows a lock banner: "This page is locked by Alice. Changes cannot be proposed until the lock is released."
6. Bob clicks "Notify me" button. The system adds Bob to the queue and shows "Position #1 in queue".
7. Alice applies her proposal. The lock is released.
8. Bob's frontend receives a notification. The banner updates to "The page is now available. You may attempt your changes."
9. Bob retries his proposal. It succeeds.

**E2E-02 -- Admin Force-Releases Stale Lock:**
1. Alice starts an AI session, acquires a WRITE lock on page P42.
2. Alice's browser crashes. The lock TTL begins counting down.
3. Bob reports to Admin that page P42 is locked.
4. Admin opens the Lock Dashboard, sees the lock, clicks "Force Release".
5. Confirmation dialog: "Force-release lock on page 'Introduction' held by Alice? This will invalidate any pending proposals."
6. Admin confirms with reason "Stale session -- user disconnected".
7. System releases the lock, invalidates any open proposals, logs the audit event.
8. Bob receives notification: "The lock on 'Introduction' has been released by an administrator. You may now edit."
9. Bob can now propose changes to page P42.

### Manual QA Steps

1. **Lock Indicator Visibility:** Verify that when a user holds a WRITE lock on a page, the page list shows a closed lock icon next to that page. When the lock is released, the icon disappears within 5 seconds.
2. **Heartbeat from Frontend:** Open browser dev tools. Verify that the frontend sends `POST /api/v1/ai/locks/{lock_id}/heartbeat` every ~4 minutes (before the 5-minute heartbeat interval).
3. **Lock Release on Session End:** Close the browser tab without applying. Wait for the TTL to expire. Verify that the stale lock scanner releases the lock and that another user can edit the page after release.
4. **Admin Lock Dashboard Filters:** As admin, go to the lock dashboard. Verify filters for user name, course ID, page ID, and lock type all work and return correct results. Verify pagination works with 50+ locks.
5. **Cross-Organization Isolation:** As User A in Org 1 holding a lock, verify that User B in Org 2 cannot see any lock information for Org 1 resources via the API.
6. **Queued Notification:** Open two browsers side by side as different users. Lock a page from Browser A. Join the queue from Browser B. Release from Browser A. Verify Browser B receives the notification within 5 seconds.

---

## 7. DEFINITION OF DONE

1. `ai_locks`, `ai_lock_queue`, and `ai_lock_config` tables exist in the database with the correct schema, indexes, and foreign key relationships.
2. All database migrations are created, reviewed, and applied to staging without errors.
3. `LockManager` service is fully implemented with methods: `acquire_lock`, `release_lock`, `heartbeat`, `get_active_lock`, `list_active_locks`, `enqueue`, `dequeue`, `notify_next_in_queue`, `scan_and_release_stale_locks`, `force_release_by_admin`, `get_lock_config`, `update_lock_config`.
4. All 6 unit tests in Section 6 pass with >90% code coverage for the `lock_manager.py` module.
5. All 3 integration tests in Section 6 pass against a real PostgreSQL database.
6. Both E2E tests in Section 6 are passing in the CI environment.
7. The `propose_*` tool endpoints (propose_create_page, propose_update_page, propose_delete_page) acquire WRITE locks and return lock metadata in the response.
8. The `apply_*` tool endpoints verify lock ownership and release the lock on success.
9. Session creation (`POST /api/v1/ai/sessions`) acquires a SESSION lock on the course and rejects concurrent sessions with `COURSE_LOCKED` error.
10. The stale lock scanner background task is running and releases expired locks within the configured interval.
11. Admin lock management API routes (GET/DELETE locks, GET/DELETE queue entries, GET/PUT lock config) are implemented and documented.
12. All lock operations are audited with events written to `ai_audit_logs`.
13. Lock events (`LockAcquired`, `LockReleased`, `LockExpired`, `LockForceReleased`) are emitted to the outbox for downstream consumers.
14. Frontend lock indicators are implemented and tested: lock icon in page list, lock banner in chat panel, lock status panel, admin lock dashboard.
15. Frontend heartbeat polling is implemented: sends heartbeat every 4 minutes for each held lock.
16. Conflict queue UI is implemented: "Notify me" button, queue position indicator, notification when lock is available.
17. All manual QA steps in Section 6 are verified and signed off by QA.
18. Cross-organization isolation is verified: locks from Org A are invisible to users in Org B.
19. No regression in existing tool functionality: all pre-existing US-AI-* tests still pass.
20. Configuration variables documented in deployment guide with recommended values.
21. Load test passed: 500 concurrent sessions with up to 5,000 concurrent locks stable for 10 minutes.
22. Security review completed: session header validation, admin override confirmation, audit logging.

---

## 8. TASKS AND SUB-TASKS

| Task ID | Task Description | Estimated Effort | Dependencies | Assigned To |
|---|---|---|---|---|
| T-043-01 | **Create database tables and migrations** -- Write Alembic migration for `ai_locks`, `ai_lock_queue`, and `ai_lock_config` tables. Add columns `session_lock_id` and `course_lock_status` to `ai_sessions`. Add columns `write_lock_id` and `base_version_hash` to `ai_proposals`. Apply and verify. | 4 hours | US-AI-004 (ai_sessions, ai_proposals tables exist) | Backend Engineer |
| T-043-02 | **Implement LockManager service** -- Write `app/services/ai/lock_manager.py` with all lock acquisition, release, heartbeat, queue management, stale scan, and admin override methods. Include `LockConfig` dataclass, `ActiveLock` model, `LockAcquireResult` and `LockConflict` response types. | 16 hours | T-043-01 | Backend Engineer |
| T-043-03 | **Implement lock middleware/decorators** -- Write `@with_write_lock`, `@with_read_lock`, and `@with_session_lock` decorators in `app/services/ai/lock_middleware.py` for auto-instrumenting tool endpoints. | 4 hours | T-043-02 | Backend Engineer |
| T-043-04 | **Implement stale lock scanner** -- Write `app/services/ai/stale_lock_scanner.py` as an asyncio background task. Integrate into FastAPI lifespan event. Verify auto-release works with expired TTL. | 4 hours | T-043-02 | Backend Engineer |
| T-043-05 | **Integrate locks into session creation** -- Modify `POST /api/v1/ai/sessions` to acquire SESSION lock after session creation. Return `COURSE_LOCKED` on conflict. Store lock_id on session record. | 3 hours | T-043-02, US-AI-006 | Backend Engineer |
| T-043-06 | **Integrate locks into propose_* tool handlers** -- Modify `propose_create_page`, `propose_update_page`, `propose_delete_page` to acquire WRITE locks. Return lock metadata in responses. Handle `PAGE_LOCKED` errors. | 6 hours | T-043-02, T-043-03, US-AI-011, US-AI-012, US-AI-013 | Backend Engineer |
| T-043-07 | **Integrate locks into apply_* tool handlers** -- Modify `apply_page_proposal`, `apply_update_proposal`, `confirm_delete_page` to verify lock ownership and release locks on success. Handle `LOCK_EXPIRED` errors. | 4 hours | T-043-02, T-043-03, US-AI-010 | Backend Engineer |
| T-043-08 | **Implement admin lock API routes** -- Implement GET /api/v1/ai/locks (list with filters), DELETE /api/v1/ai/locks/{lock_id} (force release), GET/POST/DELETE /api/v1/ai/locks/queue endpoints, GET/PUT /api/v1/ai/locks/config. Add admin role validation and audit logging. | 6 hours | T-043-02 | Backend Engineer |
| T-043-09 | **Write unit tests** -- Write 6+ unit tests covering lock acquire/release cycle, conflict detection, concurrent reads, heartbeat, stale detection, and queue management. | 6 hours | T-043-02 | QA Engineer |
| T-043-10 | **Write integration tests** -- Write 3+ integration tests covering full lock lifecycle via API, concurrent session rejection, and conflict queue notification flow. | 6 hours | T-043-05, T-043-06, T-043-07 | QA Engineer |
| T-043-11 | **Write E2E tests** -- Write 2+ E2E tests covering the lock indicator/proposal-blocked flow and the admin force-release flow. | 8 hours | T-043-05 through T-043-08 | QA Engineer |
| T-043-12 | **Implement frontend lock indicators** -- Add lock icon to page list with tooltip. Add lock banner to chat panel. Implement lock status panel in AI sidebar. Add heartbeat polling (every 4 minutes per lock). | 8 hours | T-043-05, T-043-06, T-043-07, US-AI-024 | Frontend Engineer |
| T-043-13 | **Implement frontend conflict queue UI** -- Add "Notify me" button on lock banner. Implement queue position indicator. Handle lock-available notification. Add "Release Now" button on lock panel. | 6 hours | T-043-08, T-043-12 | Frontend Engineer |
| T-043-14 | **Implement admin lock dashboard** -- Build admin view listing all active locks with filters (user, course, page, lock type). Implement force-release with confirmation dialog. Implement lock config editor. | 8 hours | T-043-08 | Frontend Engineer |
| T-043-15 | **Add lock outbox events** -- Emit `LockAcquired`, `LockReleased`, `LockExpired`, `LockForceReleased` outbox events in the lock manager. Ensure events are written in the same transaction as lock mutations. | 3 hours | T-043-02, US-AI-033 | Backend Engineer |
| T-043-16 | **Performance and load testing** -- Run load test with 500 concurrent sessions / 5,000 concurrent locks. Verify p95 latency targets. Test stale lock scanner with 10,000+ expired records. | 6 hours | T-043-02 through T-043-08 | QA Engineer |
| T-043-17 | **Security review and documentation** -- Review all lock endpoints for proper authorization. Verify cross-org isolation. Document lock configuration variables and deployment guide. | 4 hours | All above tasks | Security Engineer |
| T-043-18 | **Regression test suite** -- Run full AI authoring regression suite with lock system enabled. Verify that existing US-AI-001 through US-AI-042 tests still pass. | 4 hours | All above tasks | QA Engineer |
