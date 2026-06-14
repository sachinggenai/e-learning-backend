# US-AI-006 — Create Scoped AI Authoring Sessions

**Priority:** MUST  
**Depends on:** US-AI-004 (AI Persistence Foundations), US-AI-005 (Tool and Template Contract Registry)  
**Unlocks:** US-AI-007 (Page List and Fetch Tools), US-AI-008 (Validation Pipeline), US-AI-009 (Proposal Lifecycle), US-AI-023 (Chat Endpoint), US-AI-024 (Frontend AI Integration)  
**Source Flow:** AI Session Creation Flow  
**Backend Stack:** Python/FastAPI + PostgreSQL + SQLAlchemy Async  
**Estimated Effort:** 3–4 days (backend) + 2–3 days (frontend integration)

---

## 1. FUNCTIONAL SPECIFICATION

### 1.1 Detailed User Story

**As an** Author (Instructor / Course Designer),  
**I want** to start an AI authoring session that is scoped to exactly one course,  
**so that** every subsequent AI operation (list pages, propose changes, apply updates) is automatically restricted to that course, preventing cross-course data leakage and ensuring that permissions and tenant isolation are enforced server-side without the AI model having to reason about scope.

### 1.2 Numbered Functional Requirements

1. **FR-001 — Session Creation:** The system MUST expose a `POST /api/v1/ai/sessions` endpoint that accepts an authenticated user ID, a course ID, and an organization ID, and returns a unique `session_id`, an expiry timestamp (default 24 hours), and a snapshot of the current course state (course title, page count, page metadata list).

2. **FR-002 — Immutable Course Scope:** Once a session is created, the `course_id` MUST be immutable. No tool call within that session can reference a different course. Any attempt to do so MUST be rejected server-side with a `PERMISSION_DENIED` error before the tool logic executes.

3. **FR-003 — Course Existence and Access Validation:** Session creation MUST verify that the course exists (via `CourseRepository.get_by_course_id`) and that the authenticated user has access to it (at minimum, the course exists in the user's organization). If the course does not exist or is not accessible, the endpoint MUST return a 404 or 403 respectively.

4. **FR-004 — Session Expiry:** Every session MUST have an `expires_at` timestamp (default `created_at + 24 hours`). All tool calls against an expired session MUST be rejected with a structured `PERMISSION_DENIED` error and `retryable: true`, indicating the user should create a new session.

5. **FR-005 — Session Retrieval:** The system MUST expose a `GET /api/v1/ai/sessions/{session_id}` endpoint that returns the current session metadata (status, expiry, course ID, user ID) and the current course state summary. This is used for frontend session rehydration on page reload.

6. **FR-006 — Session Deletion:** The system MUST expose a `DELETE /api/v1/ai/sessions/{session_id}` endpoint that invalidates and soft-deletes a session. After deletion, all subsequent tool calls with that session ID are rejected.

7. **FR-007 — Course State Snapshot:** On session creation and retrieval, the response MUST include a `course_state` object containing: `course_id`, `course_title`, `total_pages`, `pages` (list of `{page_id, title, template_type, order}`), and the `organization_id`. This allows the frontend to initialize the AI panel without making additional API calls.

8. **FR-008 — Rate Limit on Session Creation:** The system MUST enforce a maximum number of active sessions per user (configurable, default 5). Creating a new session when the user already has 5 active (non-expired) sessions MUST either reject with `RATE_LIMIT_EXCEEDED` or automatically expire the oldest active session.

9. **FR-009 — Session Audit Trail:** Every session lifecycle event (create, retrieve, delete, expiry) MUST be recorded in the `ai_audit_logs` table with the user ID, session ID, operation name, timestamp, and IP address.

10. **FR-010 — Tenant Isolation:** Sessions from different organizations MUST be fully isolated. A user from Organization A MUST NOT be able to create a session scoped to a course belonging to Organization B, even if they somehow know the course ID.

### 1.3 Step-by-Step User Flow

#### Happy Path

1. **User navigates** to a course in the existing editor UI.
2. **User clicks** the "Build with AI" button (visible only when the `AI_AUTHORING_ENABLED` feature flag is on).
3. **Frontend calls** `POST /api/v1/ai/sessions` with `{user_id, course_id, organization_id}`.
4. **Backend validates:**
   - Feature flag `AI_AUTHORING_ENABLED` is on.
   - User is authenticated (JWT/API key).
   - Course with `course_id` exists via `CourseRepository.get_by_course_id()`.
   - Course belongs to the user's organization (tenant isolation check).
   - User has fewer than `AI_MAX_ACTIVE_SESSIONS` active sessions.
5. **Backend persists** a new session record in `ai_sessions` table with `status = "active"`, `expires_at = now + AI_SESSION_TTL_HOURS`.
6. **Backend returns** `{session_id, course_id, user_id, organization_id, created_at, expires_at, course_state}`.
7. **Frontend stores** `session_id` in `sessionStorage`, initializes the AI chat panel with the `course_state` summary.
8. **User interacts** with the AI agent through the chat panel. Every tool call includes `session_id` in the `Authorization: Session {session_id}` header.
9. **User finishes** AI authoring and closes the AI panel.
10. **Frontend calls** `DELETE /api/v1/ai/sessions/{session_id}` to clean up.
11. **Backend marks** session as `status = "closed"`, logs the deletion in `ai_audit_logs`.

#### Alternate Paths

**Path A: Course does not exist (404)**
1. User clicks "Build with AI" on a deleted course.
2. `POST /api/v1/ai/sessions` returns 404 `{code: "COURSE_NOT_FOUND", message: "Course with ID {course_id} not found."}`.
3. Frontend shows a user-friendly error: "This course could not be found. Please refresh and try again."

**Path B: User lacks access (403)**
1. User attempts to create a session for a course in a different organization.
2. Backend returns 403 `{code: "PERMISSION_DENIED", message: "You do not have access to this course.", retryable: false}`.
3. Frontend shows: "You do not have permission to use AI authoring on this course."

**Path C: Max active sessions exceeded (429)**
1. User already has 5 active sessions.
2. Backend returns 429 `{code: "RATE_LIMIT_EXCEEDED", message: "Maximum active sessions (5) reached. Please close an existing AI session first.", retryable: true}`.
3. Frontend shows the active sessions list and lets the user close one.

**Path D: Feature flag off (404)**
1. `AI_AUTHORING_ENABLED` is `false` for the environment/tenant.
2. The "Build with AI" button is not rendered on the frontend. If the API is called directly, it returns 404 `{code: "FEATURE_DISABLED", message: "AI authoring is not enabled."}`.

**Path E: Session expired mid-use**
1. User leaves the AI panel open overnight (> 24 hours).
2. Next tool call returns 401 `{code: "SESSION_EXPIRED", message: "Your AI session has expired. Please start a new session.", retryable: true}`.
3. Frontend detects this, closes the chat panel, and prompts: "Your session expired. Click 'Build with AI' to start a new one."

### 1.4 UI/UX Requirements

1. The "Build with AI" button should be a secondary/ghost action button placed near the course title area, not disruptive to the existing editor layout.
2. The AI chat panel should not render at all when `AI_AUTHORING_ENABLED` is false.
3. While the session is being created, a subtle loading spinner in the button text ("Starting AI...").
4. On session expiry mid-flow, the frontend should gracefully close the AI panel with a clear informational banner stating the reason and the action required ("Session expired. Click to start a new session.").
5. The frontend must never show raw API error JSON to the user — all errors must be mapped to user-friendly messages.
6. Session ID must be stored in `sessionStorage` (not `localStorage`) so it is cleared when the user closes the tab.

---

## 2. TECHNICAL SPECIFICATION

### 2.1 API Contracts

#### 2.1.1 Create Session

```
POST /api/v1/ai/sessions
```

**Headers:**
```
Authorization: Bearer <jwt-token>
Content-Type: application/json
```

**Request Body:**
```json
{
  "user_id": "string (UUID4, required, the authenticated user)",
  "course_id": "string (course_id string, required, max 64 chars)",
  "organization_id": "string (UUID4, required, for tenant isolation)"
}
```

**Response Body (201 Created):**
```json
{
  "session_id": "string (UUID4)",
  "course_id": "string",
  "user_id": "string",
  "organization_id": "string",
  "created_at": "string (ISO-8601 datetime)",
  "expires_at": "string (ISO-8601 datetime)",
  "status": "active",
  "course_state": {
    "course_id": "string",
    "title": "string",
    "total_pages": "integer",
    "pages": [
      {
        "page_id": "string",
        "title": "string",
        "template_type": "string",
        "order": "integer"
      }
    ]
  }
}
```

**HTTP Status Codes:**

| Code | Condition |
|------|-----------|
| 201 | Session created successfully |
| 400 | Missing required fields (`user_id`, `course_id`, `organization_id`) or invalid UUID format |
| 401 | Missing or invalid Authorization header |
| 403 | User does not have access to the specified course / organization mismatch |
| 404 | Course not found; or AI feature disabled |
| 409 | Course already has an active session for this user (optional strict mode) |
| 422 | Request body fails Pydantic validation (e.g., field type error) |
| 429 | Max active sessions per user exceeded; or rate limit hit |

#### 2.1.2 Get Session

```
GET /api/v1/ai/sessions/{session_id}
```

**Headers:**
```
Authorization: Bearer <jwt-token>
```

**Response Body (200 OK):**
```json
{
  "session_id": "string (UUID4)",
  "course_id": "string",
  "user_id": "string",
  "organization_id": "string",
  "created_at": "string (ISO-8601)",
  "expires_at": "string (ISO-8601)",
  "status": "active | expired | closed",
  "course_state": {
    "course_id": "string",
    "title": "string",
    "total_pages": "integer",
    "pages": [
      {
        "page_id": "string",
        "title": "string",
        "template_type": "string",
        "order": "integer",
        "updated_at": "string (ISO-8601)"
      }
    ]
  }
}
```

**HTTP Status Codes:**

| Code | Condition |
|------|-----------|
| 200 | Session retrieved (even if expired — status field indicates state) |
| 401 | Missing/invalid Authorization |
| 403 | Session's `user_id` does not match the authenticated user |
| 404 | Session not found |

#### 2.1.3 Delete Session (Close)

```
DELETE /api/v1/ai/sessions/{session_id}
```

**Headers:**
```
Authorization: Bearer <jwt-token>
```

**Response Body (200 OK):**
```json
{
  "session_id": "string",
  "status": "closed",
  "deleted_at": "string (ISO-8601)"
}
```

**HTTP Status Codes:**

| Code | Condition |
|------|-----------|
| 200 | Session successfully closed (idempotent — same response on double-delete) |
| 401 | Missing/invalid Authorization |
| 403 | Session's `user_id` does not match the authenticated user |
| 404 | Session not found |

#### 2.1.4 Error Envelope (all endpoints)

All errors follow the existing pattern from `app/utils/error_envelope.py`:

```json
{
  "detail": {
    "code": "ERROR_CODE",
    "field": "field.name",
    "message": "Human-readable description",
    "details": {}
  }
}
```

Error code catalog for this endpoint set:

| Code | Meaning | Retryable |
|------|---------|-----------|
| `SESSION_NOT_FOUND` | Session ID does not exist | false |
| `SESSION_EXPIRED` | Session has passed `expires_at` | true |
| `SESSION_CLOSED` | Session was explicitly deleted | false |
| `COURSE_NOT_FOUND` | Course ID not in database | false |
| `PERMISSION_DENIED` | User does not own session or cannot access course | false |
| `MISSING_FIELD` | Required request field absent | false |
| `RATE_LIMIT_EXCEEDED` | User has max active sessions or hit rate limit | true |
| `FEATURE_DISABLED` | AI authoring not enabled | false |

### 2.2 Database Schema DDL

#### 2.2.1 `ai_sessions` table

```sql
CREATE TABLE ai_sessions (
    -- Primary key
    id              BIGSERIAL PRIMARY KEY,
    
    -- Public identifier exposed via API
    session_id      UUID NOT NULL DEFAULT gen_random_uuid(),
    
    -- Immutable scope
    user_id         UUID NOT NULL,
    course_id       VARCHAR(64) NOT NULL,
    organization_id UUID NOT NULL,
    
    -- Lifecycle
    status          VARCHAR(16) NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'expired', 'closed')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    closed_at       TIMESTAMPTZ,
    
    -- Rate limiting / metadata
    tool_call_count INTEGER NOT NULL DEFAULT 0,
    last_activity_at TIMESTAMPTZ,
    
    -- Constraints
    CONSTRAINT uq_ai_sessions_session_id UNIQUE (session_id),
    CONSTRAINT fk_ai_sessions_course
        FOREIGN KEY (course_id) REFERENCES courses(course_id)
        ON DELETE CASCADE
);

-- Indexes
CREATE INDEX idx_ai_sessions_user_id ON ai_sessions (user_id);
CREATE INDEX idx_ai_sessions_course_id ON ai_sessions (course_id);
CREATE INDEX idx_ai_sessions_status ON ai_sessions (status);
CREATE INDEX idx_ai_sessions_expires_at ON ai_sessions (expires_at)
    WHERE status = 'active';
-- Composite index for the "active session per user" count query
CREATE INDEX idx_ai_sessions_user_active
    ON ai_sessions (user_id, status, expires_at)
    WHERE status = 'active';
```

#### 2.2.2 `ai_audit_logs` (extend from US-AI-004)

```sql
CREATE TABLE ai_audit_logs (
    -- Inherits from US-AI-004 foundation, adding session-specific fields:
    id                  BIGSERIAL PRIMARY KEY,
    session_id          UUID NOT NULL REFERENCES ai_sessions(session_id),
    user_id             UUID NOT NULL,
    organization_id     UUID NOT NULL,
    operation           VARCHAR(32) NOT NULL
                            CHECK (operation IN (
                                'session_create', 'session_get',
                                'session_delete', 'session_expire'
                            )),
    details             JSONB,
    ip_address          INET,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_ai_audit_sessions ON ai_audit_logs (session_id);
CREATE INDEX idx_ai_audit_user_operation ON ai_audit_logs (user_id, operation, created_at);
```

#### 2.2.3 Alembic Migration

Create new migration file: `alembic/versions/20260614_0001_add_ai_sessions.py`

The migration must:
1. Create `ai_sessions` table.
2. Add columns to `ai_audit_logs` if not already present from US-AI-004.
3. Create all indexes listed above.
4. Create the partition for future scaling (optional: use `created_at` monthly range partitioning for audit logs if on PG 12+).

### 2.3 Service/Module Design

#### 2.3.1 New Files

**`app/routers/ai_sessions.py`**

```python
"""
AI Session Lifecycle Router

Endpoints:
- POST   /api/v1/ai/sessions          Create session
- GET    /api/v1/ai/sessions/{id}     Get session with current course state
- DELETE /api/v1/ai/sessions/{id}     Close/delete session
"""
```

Class/method design:

```python
class AISessionRouter:
    """Container for dependency-injected route handlers."""
    
    def __init__(self, session_service: "AISessionService"):
        self.session_service = session_service

    async def create(
        self,
        body: CreateSessionRequest,
        auth_user: AuthenticatedUser = Depends(get_current_user),
        db: AsyncSession = Depends(get_session),
        feature_flags: FeatureFlagService = Depends(get_feature_flags),
    ) -> CreateSessionResponse: ...

    async def get(
        self,
        session_id: str,
        auth_user: AuthenticatedUser = Depends(get_current_user),
        db: AsyncSession = Depends(get_session),
    ) -> GetSessionResponse: ...

    async def delete(
        self,
        session_id: str,
        auth_user: AuthenticatedUser = Depends(get_current_user),
        db: AsyncSession = Depends(get_session),
    ) -> DeleteSessionResponse: ...
```

**`app/services/ai/session_service.py`**

```python
class AISessionService:
    """Core domain logic for AI session lifecycle."""

    def __init__(
        self,
        session_repo: AISessionRepository,
        course_repo: CourseRepository,
        audit_logger: AIAuditLogger,
        feature_flag_svc: FeatureFlagService,
        config: AISessionConfig,
    ):
        self._session_repo = session_repo
        self._course_repo = course_repo
        self._audit_logger = audit_logger
        self._feature_flag_svc = feature_flag_svc
        self._config = config

    async def create_session(
        self,
        user_id: str,
        course_id: str,
        organization_id: str,
        ip_address: str,
    ) -> AISession:
        # 1. Check feature flag
        # 2. Validate course exists and belongs to organization
        # 3. Check active session limit
        # 4. Persist session
        # 5. Build course_state snapshot
        # 6. Audit log
        # 7. Return AISession domain object
        ...

    async def get_session(
        self, session_id: str, requesting_user_id: str
    ) -> AISession:
        # 1. Fetch session record
        # 2. Validate ownership
        # 3. Check expiry
        # 4. Build fresh course_state
        # 5. Return
        ...

    async def close_session(
        self, session_id: str, requesting_user_id: str
    ) -> None:
        # 1. Fetch session
        # 2. Validate ownership
        # 3. Soft-delete (status = 'closed')
        # 4. Audit log
        ...

    async def expire_stale_sessions(self) -> int:
        """Background job: mark all sessions where expires_at < now as expired.
        Returns the count of sessions expired."""
        ...
```

**`app/services/ai/session_repository.py`**

```python
class AISessionRepository:
    """DB access for ai_sessions table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, record: AISessionRecord) -> AISessionRecord: ...
    async def get_by_session_id(self, session_id: str) -> Optional[AISessionRecord]: ...
    async def get_active_sessions_by_user(self, user_id: str) -> Sequence[AISessionRecord]: ...
    async def get_active_sessions_by_course(self, course_id: str, user_id: str) -> Sequence[AISessionRecord]: ...
    async def count_active_by_user(self, user_id: str) -> int: ...
    async def expire_session(self, session_id: str) -> None: ...
    async def close_session(self, session_id: str) -> None: ...
    async def expire_all_stale(self) -> int: ...
    async def touch_activity(self, session_id: str) -> None: ...
```

**`app/services/ai/audit_logger.py`**

```python
class AIAuditLogger:
    """Writes AI audit log entries."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def log(
        self,
        session_id: str,
        user_id: str,
        organization_id: str,
        operation: str,
        details: dict | None = None,
        ip_address: str | None = None,
    ) -> None: ...
```

**`app/services/ai/config.py`**

```python
@dataclass
class AISessionConfig:
    """Configuration loaded from environment variables."""
    ttl_hours: int                      # AI_SESSION_TTL_HOURS
    max_active_sessions_per_user: int   # AI_MAX_ACTIVE_SESSIONS
    enabled: bool                       # AI_AUTHORING_ENABLED
    ...

    @classmethod
    def from_env(cls) -> "AISessionConfig": ...
```

**`app/models/ai_session.py`**

```python
"""SQLAlchemy ORM model for AI sessions."""
from sqlalchemy import ...
from app.models.base import Base

class AISessionRecord(Base):
    __tablename__ = "ai_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, index=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    course_id: Mapped[str] = mapped_column(String(64))
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0)
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

**`app/schemas/ai_session.py`** (Pydantic request/response schemas)

```python
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime

class CreateSessionRequest(BaseModel):
    user_id: UUID = Field(..., description="The authenticated user's UUID")
    course_id: str = Field(..., min_length=1, max_length=64, description="Course ID string")
    organization_id: UUID = Field(..., description="Organization UUID for tenant isolation")

class PageStateDTO(BaseModel):
    page_id: str
    title: str
    template_type: str
    order: int

class CourseStateDTO(BaseModel):
    course_id: str
    title: str
    total_pages: int
    pages: list[PageStateDTO]

class CreateSessionResponse(BaseModel):
    session_id: UUID
    course_id: str
    user_id: UUID
    organization_id: UUID
    created_at: datetime
    expires_at: datetime
    status: str
    course_state: CourseStateDTO

class GetSessionResponse(BaseModel):
    session_id: UUID
    course_id: str
    user_id: UUID
    organization_id: UUID
    created_at: datetime
    expires_at: datetime
    status: str
    course_state: CourseStateDTO

class DeleteSessionResponse(BaseModel):
    session_id: UUID
    status: str
    deleted_at: datetime
```

#### 2.3.2 existing model updates

**`app/main.py`** — Add import and include of the AI sessions router:

```python
from app.routers import ai_sessions
# ...
api_router.include_router(ai_sessions.router, prefix="/ai", tags=["AI Authoring"])
```

### 2.4 Configuration Variables

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `AI_AUTHORING_ENABLED` | `bool` | `false` | Master feature flag for all AI authoring capabilities |
| `AI_SESSION_TTL_HOURS` | `int` | `24` | Session expiry in hours from creation |
| `AI_MAX_ACTIVE_SESSIONS` | `int` | `5` | Max concurrent active sessions per user |
| `AI_SESSION_CLEANUP_INTERVAL_MINUTES` | `int` | `15` | Background job interval for expiring stale sessions |
| `AI_RATE_LIMIT_CREATE_SESSION_PER_HOUR` | `int` | `20` | Max session creation requests per user per hour |
| `FEATURE_AI_SUGGESTIONS` | `bool` | `false` | Legacy feature flag name (mapped to `AI_AUTHORING_ENABLED` for backward compat) |

These should be documented in `.env.example` and loaded at service init:

```python
# app/services/ai/config.py
AI_AUTHORING_ENABLED: bool = os.getenv("AI_AUTHORING_ENABLED", "false").lower() == "true"
AI_SESSION_TTL_HOURS: int = int(os.getenv("AI_SESSION_TTL_HOURS", "24"))
AI_MAX_ACTIVE_SESSIONS: int = int(os.getenv("AI_MAX_ACTIVE_SESSIONS", "5"))
AI_SESSION_CLEANUP_INTERVAL_MINUTES: int = int(os.getenv("AI_SESSION_CLEANUP_INTERVAL_MINUTES", "15"))
AI_RATE_LIMIT_CREATE_SESSION_PER_HOUR: int = int(os.getenv("AI_RATE_LIMIT_CREATE_SESSION_PER_HOUR", "20"))
```

### 2.5 Integration Points

| Integration | Existing Code | How It Is Used |
|-------------|---------------|----------------|
| `CourseRepository.get_by_course_id()` | `app/repositories/course_repo.py` | Validate course exists and fetch course metadata for `course_state` |
| `PageRepository.list_by_course()` | `app/repositories/page_component_repo.py` | Fetch page list for `course_state.pages` in session response |
| `FeatureFlagService.is_enabled()` | `app/utils/feature_flags.py` | Gate the entire session creation behind `AI_AUTHORING_ENABLED` |
| `build_error()` / `api_http_exception()` | `app/utils/error_envelope.py` | Consistent structured error responses |
| `get_session()` dependency | `app/db/config.py` | Inject async DB session into repositories |
| `Base` declarative base | `app/models/base.py` | Register `AISessionRecord` in unified metadata for Alembic |
| `AIAuditLogger` | New in `app/services/ai/audit_logger.py` | Write session lifecycle audit entries into `ai_audit_logs` |
| `BackgroundTasks` / APScheduler | FastAPI built-in / optional | Schedule stale session expiry job |

**External services:** None for this story. Session management is entirely self-contained within the backend PostgreSQL database.

---

## 3. NON-FUNCTIONAL REQUIREMENTS

### 3.1 Performance Targets

| Metric | Target | Measurement Method |
|--------|--------|--------------------|
| `POST /api/v1/ai/sessions` p50 latency | < 200 ms | APM / request logging |
| `POST /api/v1/ai/sessions` p95 latency | < 500 ms | APM / request logging |
| `POST /api/v1/ai/sessions` p99 latency | < 1000 ms | APM / request logging |
| `GET /api/v1/ai/sessions/{id}` p50 latency | < 100 ms | APM / request logging |
| Session creation throughput | > 50 req/s per instance | Load test |
| Course state snapshot generation | < 50 ms overhead beyond DB query | Tracing instrumentation |

### 3.2 Security Requirements

1. **Authentication:** Every session endpoint requires a valid JWT (or equivalent auth mechanism). The `get_current_user` dependency MUST be applied to every route.
2. **Authorization (Ownership):** `GET` and `DELETE` on `/{session_id}` MUST verify that `session.user_id == authenticated_user.id`. A user must never access another user's session.
3. **Authorization (Course Access):** On session creation, the system MUST verify that the course exists AND belongs to the same `organization_id` as the authenticated user. This is tenant isolation.
4. **Input Validation:** All UUID fields (`user_id`, `organization_id`) MUST be validated as proper UUID4 format. `course_id` MUST validate against `CourseRecord.course_id` format (max 64 chars, alphanumeric + hyphens + underscores).
5. **Session ID Unpredictability:** `session_id` is a random UUID v4, generated server-side. It must never be accepted from the client during creation.
6. **No Session ID Enumeration:** `GET /{session_id}` MUST return 404 (not 403) when the session does not exist, to prevent attackers from probing valid session IDs. 403 is only returned when the session exists but belongs to a different user.
7. **Rate Limiting:** Session creation is rate-limited per user to `AI_RATE_LIMIT_CREATE_SESSION_PER_HOUR` (default 20/hour).
8. **Feature Flag Gating:** When `AI_AUTHORING_ENABLED` is `false`, all session endpoints MUST return 404 `FEATURE_DISABLED`.

### 3.3 Reliability

**Error Codes Catalog:**

| Code | HTTP | When | Retry Strategy |
|------|------|------|----------------|
| `COURSE_NOT_FOUND` | 404 | Course does not exist | None (client error) |
| `SESSION_NOT_FOUND` | 404 | Session ID not in DB | None (client error) |
| `SESSION_EXPIRED` | 401 | Session past `expires_at` | Client creates new session |
| `SESSION_CLOSED` | 401 | Session was explicitly closed | Client creates new session |
| `PERMISSION_DENIED` | 403 | User does not own session or course | None (client error) |
| `MISSING_FIELD` | 400 | Required request field absent | Fix request and retry |
| `RATE_LIMIT_EXCEEDED` | 429 | Exceeded max active sessions or creation rate | Retry after `retry_after_seconds` |
| `FEATURE_DISABLED` | 404 | AI authoring flag is off | None until admin enables |
| `INTERNAL_ERROR` | 500 | Unexpected server error | Retry with exponential backoff |

**Graceful Degradation:**
- If the database is unreachable at session creation time, return 503 `SERVICE_UNAVAILABLE` with `retryable: true` and a `retry_after_seconds` hint (default 30).
- If the database is unreachable at session retrieval time, the frontend should display a cached version of the session (from `sessionStorage`) and allow the user to continue, but warn them: "Unable to verify session. Your changes may not be saved."
- If `PageRepository.list_by_course()` fails during course state snapshot generation, return 502 with `COURSE_STATE_UNAVAILABLE` — the session was created (rolled back by transaction), the frontend retries.

**Idempotency Guarantees:**
- `DELETE /sessions/{session_id}` is idempotent: calling it twice returns the same 200 response.
- `POST /sessions` is NOT idempotent (each call creates a new session). The frontend must prevent double-click via button disabling.

**Retry Strategy:**
- All 5xx responses include `retryable: true` and `retry_after_seconds`.
- Frontend should implement exponential backoff for retries: 1s, 2s, 4s, 8s, max 30s.
- Maximum 3 retry attempts before showing a user-facing error.

### 3.4 Scalability

1. **Statelessness:** The AI session router itself is stateless. Session state lives in PostgreSQL. Multiple backend instances can serve session requests concurrently.
2. **Horizontal Scaling:** Session reads (`GET`) are read-heavy compared to writes. The `idx_ai_sessions_user_active` and `idx_ai_sessions_expires_at` indexes ensure queries remain fast even with millions of sessions.
3. **Connection Pooling:** The existing `DB_POOL_SIZE=10`, `DB_MAX_OVERFLOW=20` configuration must be monitored under load. For 50+ concurrent AI session users, increase `DB_POOL_SIZE` to 25-30.
4. **Caching Strategy:** Not required for MVP. Session lookups are single-row primary key lookups (< 5ms). If needed later, cache session records in Redis with TTL = `min(60s, time_to_expiry)`.
5. **Stale Session Cleanup:** A background task runs every `AI_SESSION_CLEANUP_INTERVAL_MINUTES` (default 15) to `UPDATE ai_sessions SET status = 'expired' WHERE expires_at < now() AND status = 'active'`. This prevents the active sessions index from bloating with stale records.

---

## 4. CURRENT STATE ASSESSMENT

### 4.1 Existing Code That Can Be Reused

| Component | File | Usage |
|-----------|------|-------|
| `CourseRepository.get_by_course_id()` | `app/repositories/course_repo.py:67` | Validate course exists, fetch title/status for course_state |
| `PageRepository.list_by_course()` | `app/repositories/page_component_repo.py:18` | Fetch page list for course_state snapshot |
| `CourseRecord` model | `app/models/persisted_course.py:24` | Reference for course existence check and FK reference |
| `PageRecord` model | `app/models/page_component.py:20` | Build page list in course_state; includes `page_id`, `title`, `order_index` |
| `FeatureFlagService` | `app/utils/feature_flags.py:27` | Gate all AI endpoints behind `AI_AUTHORING_ENABLED` |
| `build_error()` / `api_http_exception()` | `app/utils/error_envelope.py:19` | Consistent error response shape |
| `Base` declarative base | `app/models/base.py:8` | New models register via this Base |
| `get_session()` async DB session | `app/db/config.py:70` | FastAPI dependency for injected DB sessions |
| `engine`, `SessionLocal` | `app/db/config.py:61` | Alembic migration uses same engine config |
| `lifespan` startup | `app/main.py:78` | Add `AISessionRecord` import and seed if needed |
| `api_router` pattern | `app/main.py:161` | Register new router with existing prefix |
| `_verify_critical_contracts()` | `app/main.py:34` | Pattern to follow for verifying AI session contracts at startup |
| `Jinja2Templates` / rendering pipeline | `app/services/scorm_export.py` | Not directly used, but the Session service can reuse the same `PageRepository` for state queries |

### 4.2 What Must Be Built Net-New

| Component | File | Reason |
|-----------|------|--------|
| `AISessionRecord` ORM model | `app/models/ai_session.py` | No existing table for AI session data |
| `ai_sessions` table migration | `alembic/versions/20260614_0001_add_ai_sessions.py` | Must be created from scratch |
| `AISessionRepository` | `app/services/ai/session_repository.py` | No existing repository for AI sessions |
| `AISessionService` | `app/services/ai/session_service.py` | Core domain logic class |
| `AIAuditLogger` | `app/services/ai/audit_logger.py` | New audit capabilities (or extend US-AI-004 foundation) |
| `AISessionConfig` | `app/services/ai/config.py` | Configuration data class |
| Pydantic schemas | `app/schemas/ai_session.py` | Request/response DTOs |
| Router module | `app/routers/ai_sessions.py` | Three new API endpoints |
| `app/services/ai/__init__.py` | package init | Package auto-discovery |
| `app/models/ai_audit_log.py` (if not from US-AI-004) | ORM model | Audit persistence |

### 4.3 Existing Code That Must Be Modified (With Non-Regression Constraints)

| File | Change | Non-Regression Constraint |
|------|--------|--------------------------|
| `app/main.py` | (a) Import `ai_sessions` router; (b) Add `api_router.include_router(ai_sessions.router, prefix="/ai", tags=["AI Authoring"])`; (c) Add `import app.models.ai_session` in lifespan for table creation | Existing routers, middleware, and exception handlers must be unchanged. The new router must not affect any existing OpenAPI paths or behavior. |
| `app/models/__init__.py` | Add `AISessionRecord` to module exports | Must not break existing model imports elsewhere |
| `app/db/config.py` (optional) | Validate `AI_AUTHORING_ENABLED` at startup for early error detection | Must not change engine/session factory behavior |

**Critical non-regression constraint:** The `app/routers/courses.py` `POST /api/v1/courses` and `GET /api/v1/courses/{course_id}` endpoints must continue to work identically when `AI_AUTHORING_ENABLED` is `false`. The AI session router must be fully removable by simply removing the import from `main.py`.

---

## 5. EXPANSION POINTS

### 5.1 Technical Expansion (Future Sprints)

1. **Redis Session Cache Layer:** Replace DB-only session lookups with Redis-backed caching. Cache `AISessionRecord` with TTL = `min(60s, expires_at - now)` to reduce DB load. Implement cache-aside pattern: on miss, load from DB and populate cache. On expiry/close, invalidate cache.

2. **Session Replay and Debugging:** Store the full conversation history (all chat turns and tool calls) indexed by `session_id` in a separate `ai_session_turns` table with JSONB columns for `user_message`, `assistant_message`, `tool_calls`, and `tool_results`. Enable admin replay for debugging and compliance auditing.

3. **WebSocket Session Heartbeat:** Replace the HTTP-based session refresh with a lightweight WebSocket connection per session. The frontend sends a heartbeat every 30 seconds; the server extends session TTL by the heartbeat interval (configurable). If the WebSocket disconnects for > 60 seconds, auto-expire the session. This prevents session bloat from abandoned browser tabs.

4. **Session Sharing and Handoff:** Allow an author to transfer their AI session to a different course (scope change) with explicit re-confirmation. This requires adding a new `POST /sessions/{session_id}/rescoop` endpoint that validates the new course, writes an audit event, and updates the immutable `course_id` (technically making it two-phase: close old, create new with same session history reference).

### 5.2 Functional Expansion (Future Sprints)

1. **Multi-Course Sessions (Batch Authoring):** Allow a single AI session to span multiple courses. The `course_id` would become a list (`course_ids[]`) or a folder/group ID. All tool calls validate scope against all listed courses. Requires `create_session` to accept `course_ids: list[str]` and downstream tools to include `course_id` in their input schema.

2. **Persistent Session Recovery Across Logins:** Instead of sessionStorage-only, allow users to optionally "pin" an AI session so it survives tab close and even logout. Sessions would be stored in `localStorage` with an encrypted session token. On re-login, the frontend calls `POST /sessions/{session_id}/recover` which revalidates user identity and reactivates the session.

3. **Session-Based Role Switching:** Allow a single session to temporarily elevate or restrict permissions based on real-time user role changes. For example, a reviewer joining the session halfway through should see only read-only proposals, while the author can still apply. Requires dynamic permission re-evaluation on every tool call, stored as `session_roles` JSONB field.

4. **Collaborative AI Sessions:** Multiple authors work within the same AI session simultaneously. Each tool call is attributed to a specific user, and the course state snapshot reflects the latest state across all participants. Requires conflict resolution: if user A proposes a change while user B applies a different change to the same page, the second proposal's base hash check fails with a 409 conflict.

---

## 6. VALIDATION & TESTING

### 6.1 Unit Test Scenarios (at least 5)

| # | Scenario | Input | Expected Output |
|---|----------|-------|-----------------|
| UC1 | Create session successfully | `user_id=UUID("a"), course_id="course-1", organization_id=UUID("org-a")`; course exists and user has access; user has < 5 active sessions; feature flag on | Returns `CreateSessionResponse` with `session_id`, `expires_at == created_at + 24h`, `course_state` populated with 3 pages |
| UC2 | Create session with non-existent course | Same as UC1 but course does not exist in DB | Raises `HTTPException(404)` with `code = "COURSE_NOT_FOUND"` |
| UC3 | Create session when user has max active sessions | User has 5 active sessions; tries to create 6th | Raises `HTTPException(429)` with `code = "RATE_LIMIT_EXCEEDED"` and message containing "5" |
| UC4 | Create session with feature flag off | `AI_AUTHORING_ENABLED=false` | Raises `HTTPException(404)` with `code = "FEATURE_DISABLED"` |
| UC5 | Get session successfully | Valid `session_id` owned by requesting user; session active | Returns `GetSessionResponse` with matching `session_id`, `status="active"`, `course_state.pages` reflecting current DB state |
| UC6 | Get session that belongs to another user | Valid `session_id` but `session.user_id != requesting_user_id` | Raises `HTTPException(403)` with `code = "PERMISSION_DENIED"` |
| UC7 | Get non-existent session | Random UUID that does not match any session | Raises `HTTPException(404)` with `code = "SESSION_NOT_FOUND"` |
| UC8 | Get expired session | Session with `expires_at` in the past | Returns `GetSessionResponse` with `status="expired"` |
| UC9 | Close session successfully | Valid `session_id` owned by requesting user | Returns `DeleteSessionResponse` with `status="closed"`; subsequent `GET` returns `status="closed"` |
| UC10 | Close session idempotency | Close same session twice | 200 on both calls; only one audit event written; second call returns same response body |

### 6.2 Integration Test Scenarios (at least 3)

| # | Scenario | Steps | Assertions |
|---|----------|-------|------------|
| INT1 | Full session lifecycle (happy path) | 1. `POST /api/v1/ai/sessions` with valid data → get `session_id` <br>2. `GET /api/v1/ai/sessions/{session_id}` → get session state <br>3. `DELETE /api/v1/ai/sessions/{session_id}` → close session <br>4. `GET /api/v1/ai/sessions/{session_id}` → verify status | Step 1: 201, `session_id` not null, `expires_at > created_at` <br>Step 2: 200, `course_state.pages` matches `PageRepository.list_by_course()` <br>Step 3: 200, `status == "closed"` <br>Step 4: 200, `status == "closed"` |
| INT2 | Session isolation between organizations | 1. Create course "A" in org "1" <br>2. User from org "2" tries to `POST /ai/sessions` with course "A" | 403 `PERMISSION_DENIED` |
| INT3 | Create session reflects live DB state | 1. Create course with 2 pages <br>2. Create session → verify `total_pages=2` <br>3. Add a 3rd page via existing `POST /courses/{id}/pages` <br>4. `GET /ai/sessions/{id}` → verify `total_pages=3` | Step 2: `total_pages=2` <br>Step 4: `total_pages=3` (proves snapshot reads live DB, not cached) |
| INT4 | Multiple sessions per user is allowed | 1. Create session S1 for course C1 <br>2. Create session S2 for course C2 <br>3. Both succeed | 201 for both; `S1.session_id != S2.session_id` |

### 6.3 E2E / Acceptance Test Scenarios (at least 2)

| # | Scenario | Steps | Pass Criteria |
|---|----------|-------|---------------|
| E2E1 | Author completes full "Build with AI" flow | 1. User is on course editor page for course "sales-training-101" <br>2. "Build with AI" button is visible <br>3. User clicks it <br>4. AI chat panel opens with "Hello! I'm your AI authoring assistant..." <br>5. Loading spinner appears briefly then transitions to chat mode <br>6. User types "List the pages in this course" <br>7. AI responds with the correct page list from the current course state | Button visible and functional. Chat panel opens. AI has correct context (list_pages tool returns correct data). No errors in browser console. |
| E2E2 | Session expiry handling | 1. Set `AI_SESSION_TTL_HOURS = 0` (or manipulate DB expiry) <br>2. Create session <br>3. Wait for expiry <br>4. Send any tool call <br>5. Frontend shows "Your session has expired" banner <br>6. "Start New Session" button appears <br>7. User clicks it → new session created successfully | Expired session is rejected. Recovery flow works. User can create a new session. No data loss. |

### 6.4 Manual QA Verification Procedure

1. **Prerequisite check:** Confirm `AI_AUTHORING_ENABLED=true` and at least one course exists with pages.
2. **Feature flag off test:** Set `AI_AUTHORING_ENABLED=false`, restart. Verify that the AI chat panel is not rendered in the UI and that `POST /api/v1/ai/sessions` returns 404.
3. **Happy path session creation:** Using Swagger UI or `curl`, send `POST /api/v1/ai/sessions` with a valid `course_id`. Verify 201 response contains all required fields. Verify `expires_at` is 24 hours in the future.
4. **Verify course state accuracy:** Cross-reference the returned `course_state.pages` (titles, order, IDs) with the actual output of `GET /api/v1/courses/{course_id}`. They must match.
5. **Verify course state freshness:** Manually add a page via `POST /api/v1/courses/{course_id}/pages`. Then `GET /api/v1/ai/sessions/{session_id}` and verify `total_pages` has incremented.
6. **Expired session test:** Create a session. Manually run `UPDATE ai_sessions SET expires_at = now() - interval '1 hour' WHERE session_id = '<id>'`. Attempt `GET /ai/sessions/{id}` — verify `status = "expired"`.
7. **Permission test:** Create session as user A. Attempt `GET /ai/sessions/{id}` as user B (different auth). Verify 403.
8. **Max sessions test:** Create 5 sessions. Attempt to create a 6th. Verify 429. Close one session. Verify 6th creation succeeds.
9. **Non-existent course:** Send `POST /ai/sessions` with a random `course_id`. Verify 404 with `COURSE_NOT_FOUND`.
10. **Session deletion:** Create session. Delete it. Verify `GET` returns `status = "closed"`. Verify audit log entry exists with `operation = "session_delete"`.
11. **Alembic rollback:** Run `alembic downgrade -1`. Verify `ai_sessions` table is removed. Run `alembic upgrade head`. Verify table is recreated with correct schema. Verify existing course tests still pass.

---

## 7. DEFINITION OF DONE

Checklist items that ALL must be complete before this story can be marked Done:

- [ ] **DoD-1:** `AISessionRecord` ORM model exists in `app/models/ai_session.py` with all required columns, indexes, and FK constraint to `courses.course_id`.
- [ ] **DoD-2:** Alembic migration `20260614_0001_add_ai_sessions.py` exists, is reviewed, and has been applied to dev database. `alembic downgrade -1` rolls back cleanly.
- [ ] **DoD-3:** `POST /api/v1/ai/sessions`, `GET /api/v1/ai/sessions/{session_id}`, and `DELETE /api/v1/ai/sessions/{session_id}` are implemented and passing all unit tests.
- [ ] **DoD-4:** `POST /api/v1/ai/sessions` validates: (a) feature flag is on -> 404 if off, (b) course exists -> 404 if not, (c) user has < `AI_MAX_ACTIVE_SESSIONS` active sessions -> 429 if exceeded, (d) course belongs to user's organization -> 403 if not.
- [ ] **DoD-5:** `GET /api/v1/ai/sessions/{session_id}` validates ownership (403 if mismatch) and returns fresh `course_state` from `PageRepository.list_by_course()` on every call.
- [ ] **DoD-6:** `DELETE /api/v1/ai/sessions/{session_id}` is idempotent (200 on double-delete) and soft-deletes by setting `status = 'closed'`.
- [ ] **DoD-7:** All new code has at least 90% unit test coverage (sessions router + service + repository). At least 10 unit tests cover the scenarios in section 6.1.
- [ ] **DoD-8:** Integration test INT1 (full lifecycle), INT2 (tenant isolation), and INT3 (live DB state) pass in CI.
- [ ] **DoD-9:** All existing course, page, template, and export tests continue to pass with the new router imported. No existing test is modified.
- [ ] **DoD-10:** The new `ai_sessions` router is registered in `app/main.py` with conditional import logic (can be disabled by removing the import or via feature flag). Removing the import does not break any existing endpoint.
- [ ] **DoD-11:** Audit logging is verified: session create, get (optional), delete, and expiry events are written to `ai_audit_logs` with correct operation types and user IDs.
- [ ] **DoD-12:** Background stale-session cleanup is implemented (APScheduler or FastAPI `BackgroundTasks` on startup). The job marks sessions as `expired` where `expires_at < now()` and `status = 'active'`. Logs the count expired.
- [ ] **DoD-13:** All configuration variables (`AI_AUTHORING_ENABLED`, `AI_SESSION_TTL_HOURS`, `AI_MAX_ACTIVE_SESSIONS`, `AI_SESSION_CLEANUP_INTERVAL_MINUTES`, `AI_RATE_LIMIT_CREATE_SESSION_PER_HOUR`) are documented in `.env.example` and loaded at service startup.
- [ ] **DoD-14:** Manual QA (section 6.4) has been executed and signed off by the QA engineer. All 11 test steps pass.
- [ ] **DoD-15:** OpenAPI spec is regenerated (`app.main.custom_openapi` includes new schema definitions). AI session endpoints appear under a new `AI Authoring` tag.

---

## 8. TASKS & SUB-TASKS

| Task ID | Description | Owner Role | Est. Hours | Dependencies |
|---------|-------------|------------|------------|--------------|
| T-006-01 | **Create `AISessionRecord` ORM model** <br>- Define `app/models/ai_session.py` with all columns, constraints, and indexes <br>- Add `AISessionRecord` to `app/models/__init__.py` exports <br>- Add import in `app/main.py` lifespan <br>- Generate Alembic migration <br>- Run migration on dev DB and verify `CREATE TABLE` output | Backend Engineer (Data) | 2 | US-AI-004 (foundational models base) |
| T-006-02 | **Implement AI session repository** <br>- Create `app/services/ai/session_repository.py` with `AISessionRepository` class <br>- Implement `create`, `get_by_session_id`, `count_active_by_user`, `close_session`, `expire_session`, `expire_all_stale` <br>- Cover with unit tests (mock `AsyncSession`) | Backend Engineer | 3 | T-006-01 |
| T-006-03 | **Implement AI session service** <br>- Create `app/services/ai/session_service.py` with `AISessionService` class <br>- Implement `create_session` with all validations (feature flag, course existence, tenant isolation, rate limit) <br>- Implement `get_session` with ownership check and fresh course state from `PageRepository` <br>- Implement `close_session` with soft delete and audit log <br>- Cover with unit tests | Backend Engineer | 4 | T-006-02 |
| T-006-04 | **Implement Pydantic schemas and router** <br>- Create `app/schemas/ai_session.py` with request/response DTOs <br>- Create `app/routers/ai_sessions.py` with three endpoints <br>- Wire up router in `app/main.py` <br>- Add OpenAPI schema registration <br>- Implement error handling with `error_envelope.py` patterns | Backend Engineer (API) | 3 | T-006-03 |
| T-006-05 | **Implement AI audit logger** <br>- Create `app/services/ai/audit_logger.py` with `AIAuditLogger` class <br>- Extend `ai_audit_logs` table schema if not already from US-AI-004 <br>- Integrate with `AISessionService` for create/get/delete events <br>- Test audit entry creation and querying | Backend Engineer | 2 | T-006-01, US-AI-004 |
| T-006-06 | **Implement stale session cleanup background job** <br>- Create scheduled task (APScheduler or FastAPI lifespan `BackgroundTasks`) <br>- Task marks sessions with `expires_at < now()` and `status = 'active'` -> `'expired'` <br>- Configure `AI_SESSION_CLEANUP_INTERVAL_MINUTES` <br>- Add logging for count expired per run | Backend Engineer | 2 | T-006-02 |
| T-006-07 | **Write integration and E2E tests** <br>- Write integration tests INT1–INT4 (section 6.2) using `httpx.AsyncClient` + test DB <br>- Write E2E test scripts for E2E1–E2E2 (section 6.3) <br>- Verify all unit tests + integration tests in CI pipeline | QA Engineer | 4 | T-006-04 |
| T-006-08 | **Configuration documentation and cleanup** <br>- Add all `AI_*` vars to `.env.example` with descriptions <br>- Update `BACKEND_IMPLEMENTATION_SUMMARY.md` with AI session architecture section <br>- Add OpenAPI tag description for "AI Authoring" <br>- Verify feature flag integration with existing `FeatureFlagService` | Tech Writer / DevOps | 1 | T-006-04 |
| T-006-09 | **Manual QA and sign-off** <br>- Execute all 11 manual QA steps (section 6.4) <br>- Raise and fix any bugs found <br>- Document any known limitations in a README or release notes <br>- Product owner sign-off | QA Engineer / PO | 3 | T-006-07, T-006-08 |

**Total estimated effort: 24 hours (3 engineering days) backend + 4 hours QA = 28 hours total.**

---

## FINAL NOTES

- This story is **self-contained on the backend** — it requires no changes to any existing course, page, template, or export code. The session service depends only on `CourseRepository` and `PageRepository` which already exist.
- The frontend team can begin work on `US-AI-024` (Frontend AI Integration Layer) in parallel, as the API contracts in section 2.1 are the stable boundary.
- The `AISessionService` `expire_stale_sessions()` background job should be extracted as a dependency (`SessionExpiryService`) so it can be tested independently and reused by `US-AI-039` (Session Context Window Recovery).
- All three session endpoints follow the RESTful resource pattern: `POST /sessions` (create), `GET /sessions/{id}` (read), `DELETE /sessions/{id}` (delete). This is intuitive for frontend developers and consistent with the rest of the API.

---