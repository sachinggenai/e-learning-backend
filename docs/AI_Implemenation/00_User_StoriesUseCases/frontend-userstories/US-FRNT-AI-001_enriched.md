# US-FRNT-AI-001 -- Preserve Manual Authoring While Adding AI Entry Points

**Priority:** MUST  
**Depends on:** None  
**Unlocks:** Safe AI rollout (US-BKND-AI-002 Session Management, US-BKND-AI-003 Tool Contracts, US-BKND-AI-004 Validation Pipeline)  
**Epic Owner:** Technical Product Owner / Solutions Architect  
**Story Points:** 13 (Medium-Large)  
**Feature Flag:** `AI_AUTHORING_ENABLED` (boolean, default `false`)

---

## 1. FUNCTIONAL SPECIFICATION

### 1.1 Detailed User Story

**As a** course authoring platform administrator and content creator,
**I want** the AI authoring capability to be introduced as a hidden add-on behind a feature flag that does not alter any existing manual authoring flow,
**so that** the platform can be extended with AI-powered course generation, editing, and file ingestion without risk to the thousands of courses already being authored through the current manual UI and API, and so that the rollout can be gated, tested, and toggled independently.

### 1.2 Numbered Functional Requirements

**FR-1: Feature Flag Gate**
The system MUST provide a server-side feature flag `AI_AUTHORING_ENABLED` (environment variable, default `false`). When `false`, all AI-specific routes (`/api/v1/ai/*`, `/api/v1/files/upload` ingestion path) MUST return HTTP 404 or 403, and no AI UI entry point MAY be rendered in any frontend. When `true`, AI routes become operational and AI UI entry points are visible.

**FR-2: Zero Regression on Existing Routes**
Every existing REST endpoint (courses CRUD, templates CRUD, page_components CRUD, export, import, media, health, themes, branching, scoring, social, analytics, enhanced_templates, component_registry) MUST continue to operate identically regardless of the feature flag state. This MUST be validated by replaying a recorded set of representative API calls before and after flag toggle.

**FR-3: Isolated AI Module Structure**
All new AI code MUST reside in a dedicated `app/ai/` package. New AI-specific routers (e.g., `app/routers/ai_sessions.py`, `app/routers/ai_tools.py`) MUST be added alongside existing routers, not merged into them. No existing file in `app/routers/`, `app/services/`, `app/models/`, or `app/repositories/` MAY be structurally refactored for AI concerns. The only permitted modifications to existing files are (a) adding the conditional route mounting in `app/main.py`, and (b) adding new model tables in `app/models/` (new files only).

**FR-4: Separate AI Database Tables (Optional at Launch)**
AI session state and audit logs MUST be persisted in new database tables (`ai_sessions`, `ai_audit_log`, `ai_proposals`) that are entirely separate from the existing `courses`, `templates`, `pages`, `components` tables. No existing table schema MAY be altered to accommodate AI.

**FR-5: AI Routes Mounted Conditionally**
In `app/main.py`, the AI routers SHALL be imported and mounted only when `AI_AUTHORING_ENABLED=true`. When `false`, the router include calls MUST be skipped entirely. This ensures the AI routes never appear in the OpenAPI schema when the feature is off.

**FR-6: Tool Schema Document as Source of Truth**
The tool schemas defined in `docs/AI_Implemenation/01_SystemArchitecture/TOOL_SCHEMAS_CLAUDE_NATIVE.md` MUST be the authoritative contract between the AI layer and the Claude model. These schemas specify 12 tools covering session management, page operations, course validation, RAG queries, and file ingestion analysis. The implementation MUST expose these as actual REST endpoints under `POST /api/v1/ai/tools/{toolName}`.

**FR-7: AI Configuration Validation on Startup**
When `AI_AUTHORING_ENABLED=true` at startup, the application MUST validate that required configuration variables are present (`ANTHROPIC_API_KEY`, `AI_SESSION_TTL_HOURS`). If missing, the app MUST log a CRITICAL error and continue running with AI features degraded (returning 503 for AI routes with an "AI not configured" message).

**FR-8: Feature Flag Logging and Health Check**
The `/api/v1/health` endpoint MUST expose the current state of `AI_AUTHORING_ENABLED` and `ai_status` (configured/degraded/unavailable) so that monitoring and deployment tooling can verify the feature state.

### 1.3 Step-by-Step User Flow

#### Happy Path: AI Feature Flagging + Entry Point

1. **Operator** sets `AI_AUTHORING_ENABLED=true` in the deployment environment and restarts the backend.
2. **Startup:** `app/main.py` reads the env var. If true, imports and mounts `app.routers.ai_sessions`, `app.routers.ai_tools`, `app.routers.ai_files`. Validates `ANTHROPIC_API_KEY` presence. Logs `INFO: AI authoring enabled`.
3. **Frontend boot:** The React app calls `GET /api/v1/health`. Sees `aiAuthoringEnabled: true`, `aiStatus: "configured"`. Renders an "AI Authoring" button in the course editor toolbar.
4. **User clicks "AI Authoring":** Chat panel slides in. User can now interact with AI-assisted authoring.

#### Alternate Path: Feature Flag Off

1. **Operator** sets `AI_AUTHORING_ENABLED=false` (default) or leaves it unset.
2. **Frontend boot:** Health check returns `aiAuthoringEnabled: false`, `aiStatus: "unavailable"`.
3. **Frontend:** No AI button rendered. Course editor UI is identical to pre-AI baseline.
4. **Direct API call:** Any request to `POST /api/v1/ai/sessions` returns `404 Not Found`.
5. **Existing routes:** `GET /api/v1/courses`, `POST /api/v1/courses/{id}/pages/from-template`, all other routes operate normally.

#### Error Path: Missing API Key

1. Operator sets `AI_AUTHORING_ENABLED=true` but forgets `ANTHROPIC_API_KEY`.
2. **Startup:** `app/main.py` logs `CRITICAL: AI_AUTHORING_ENABLED=true but ANTHROPIC_API_KEY is not set. AI features will be degraded.`
3. **Health check:** Returns `aiAuthoringEnabled: true`, `aiStatus: "degraded"`.
4. **Frontend:** May show an info banner: "AI authoring is misconfigured. Contact your administrator."
5. **AI routes:** Return `HTTP 503` with body `{"detail": "AI service not configured", "code": "AI_NOT_CONFIGURED"}`.

#### Error Path: API Key Expired or Invalid at Runtime

1. User attempts an AI operation. Backend calls Anthropic API.
2. Anthropic returns 401.
3. Backend catches `AuthenticationError`, logs the incident, updates an in-memory degraded state.
4. Returns `{"status": "error", "code": "AI_PROVIDER_AUTH_FAILED", "retryable": false}`.
5. Frontend shows: "AI service authentication failed. Contact support."

### 1.4 UI/UX Requirements

- **Feature Flag off:** No visual change to the existing editor. All existing buttons, menus, and panels render exactly as before.
- **Feature Flag on:** A single non-intrusive entry point: an "AI Authoring" button (sparkle icon + text) added to the course editor toolbar, positioned after the existing "Save" and "Preview" buttons. The button opens a sliding chat panel on the right side of the editor. The existing manual editor remains fully functional and unchanged.
- **AI panel default state:** Closed. User must explicitly click to open. Panel width is 380px, collapsible.
- **State indicator:** Small badge at the bottom of the AI panel shows connection status: green dot ("AI Ready"), yellow dot ("Degraded"), red dot ("Unavailable").
- **Mobile:** On screens < 768px, the AI panel opens as a full-screen overlay with a close button.

---

## 2. TECHNICAL SPECIFICATION

### 2.1 API Contracts

#### 2.1.1 Health Check Endpoint (Modified)

```
GET /api/v1/health
```

**Response (existing fields omitted, shown for new AI fields):**
```json
{
  "status": "ok",
  "version": "1.5.0",
  "environment": "development",
  "timestamp": "2026-06-14T12:00:00Z",
  "uptime": 3600.0,
  "aiAuthoringEnabled": true,
  "aiStatus": "configured"
}
```

**New Status Codes:** 200 (always, regardless of feature flag)

#### 2.1.2 AI Routes (Only Active When `AI_AUTHORING_ENABLED=true`)

```
POST /api/v1/ai/sessions
```

**Request Headers:**
- `Authorization: Bearer <jwt-or-api-token>` (existing auth mechanism)

**Request Body:**
```json
{
  "course_id": "course-abc-123",
  "organization_id": "org-xyz-789"
}
```

**Response 201:**
```json
{
  "session_id": "ses-uuid-456",
  "course_id": "course-abc-123",
  "user_id": "user-0001",
  "organization_id": "org-xyz-789",
  "created_at": "2026-06-14T12:00:00Z",
  "expires_at": "2026-06-15T12:00:00Z",
  "state": {
    "page_count": 5,
    "pages": []
  }
}
```

**Response 503 (AI degraded):**
```json
{
  "detail": "AI service not configured",
  "code": "AI_NOT_CONFIGURED"
}
```

```
POST /api/v1/ai/tools/{toolName}
```

**Request Headers:**
- `Authorization: Session {session_id}`

**Request Body:** (varies per tool, see `TOOL_SCHEMAS_CLAUDE_NATIVE.md`)

**Response:** (varies per tool, consistent error shape)

```
POST /api/v1/ai/files/upload
```

**Content-Type:** `multipart/form-data`

| Field | Type | Required |
|-------|------|----------|
| file | binary | yes |
| session_id | string | yes |
| course_id | string | yes |
| description | string | no |

**Response 201:**
```json
{
  "upload_id": "upload-uuid-111",
  "filename": "course_outline.pdf",
  "status": "uploaded",
  "file_url": "/api/v1/media/ai-uploads/upload-uuid-111.pdf"
}
```

#### 2.1.3 Error Response Contract (All AI Routes)

```json
{
  "status": "error",
  "code": "VALIDATION_ERROR|PERMISSION_DENIED|NOT_FOUND|TIMEOUT|RATE_LIMIT|SERVER_ERROR|AI_NOT_CONFIGURED|AI_PROVIDER_AUTH_FAILED",
  "message": "Human-readable message",
  "details": {
    "field": "optionalFieldName",
    "reason": "specific_failure_code"
  },
  "retryable": true
}
```

### 2.2 Database Schema DDL

#### New Table: `ai_sessions`

```sql
CREATE TABLE ai_sessions (
    id              SERIAL PRIMARY KEY,
    session_id      VARCHAR(64) UNIQUE NOT NULL,
    user_id         VARCHAR(64) NOT NULL,
    course_id       VARCHAR(64) NOT NULL,
    organization_id VARCHAR(64) NOT NULL,
    state_snapshot  JSONB NOT NULL DEFAULT '{}',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMP WITH TIME ZONE NOT NULL,
    closed_at       TIMESTAMP WITH TIME ZONE,
    CONSTRAINT fk_ai_session_course
        FOREIGN KEY (course_id) REFERENCES courses(course_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_ai_sessions_user ON ai_sessions(user_id);
CREATE INDEX idx_ai_sessions_course ON ai_sessions(course_id);
CREATE INDEX idx_ai_sessions_active ON ai_sessions(is_active) WHERE is_active = TRUE;
```

#### New Table: `ai_proposals`

```sql
CREATE TABLE ai_proposals (
    id              SERIAL PRIMARY KEY,
    proposal_id     VARCHAR(64) UNIQUE NOT NULL,
    session_id      VARCHAR(64) NOT NULL,
    tool_name       VARCHAR(100) NOT NULL,
    proposal_data   JSONB NOT NULL,
    before_snapshot JSONB,
    validation_status VARCHAR(16) NOT NULL DEFAULT 'pending',
        CHECK (validation_status IN ('pending', 'valid', 'warning', 'error')),
    is_applied      BOOLEAN NOT NULL DEFAULT FALSE,
    applied_at      TIMESTAMP WITH TIME ZONE,
    expires_at      TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_ai_proposal_session
        FOREIGN KEY (session_id) REFERENCES ai_sessions(session_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_ai_proposals_session ON ai_proposals(session_id);
CREATE INDEX idx_ai_proposals_applied ON ai_proposals(is_applied) WHERE is_applied = FALSE;
```

#### New Table: `ai_audit_log`

```sql
CREATE TABLE ai_audit_log (
    id              BIGSERIAL PRIMARY KEY,
    session_id      VARCHAR(64) NOT NULL,
    user_id         VARCHAR(64) NOT NULL,
    organization_id VARCHAR(64) NOT NULL,
    course_id       VARCHAR(64) NOT NULL,
    tool_name       VARCHAR(100) NOT NULL,
    operation       VARCHAR(32) NOT NULL,
        CHECK (operation IN ('create', 'update', 'delete', 'validate', 'ingest', 'query')),
    resource_type   VARCHAR(32),
    resource_id     VARCHAR(64),
    input_hash      VARCHAR(64),
    result_status   VARCHAR(16) NOT NULL,
        CHECK (result_status IN ('success', 'error', 'rejected')),
    error_code      VARCHAR(64),
    before_state    JSONB,
    after_state     JSONB,
    diff_summary    JSONB,
    ip_address      INET,
    user_agent      VARCHAR(500),
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_ai_audit_session
        FOREIGN KEY (session_id) REFERENCES ai_sessions(session_id)
        ON DELETE SET NULL
);

CREATE INDEX idx_ai_audit_user ON ai_audit_log(user_id);
CREATE INDEX idx_ai_audit_course ON ai_audit_log(course_id);
CREATE INDEX idx_ai_audit_tool ON ai_audit_log(tool_name);
CREATE INDEX idx_ai_audit_created ON ai_audit_log(created_at);
```

### 2.3 Service/Module Design

#### New Package: `app/ai/`

```
app/ai/
  __init__.py
  config.py           -- AI configuration dataclass, loaded from env
  dependencies.py     -- FastAPI dependencies for session auth, feature flag
  feature_flag.py     -- Feature flag singleton + middleware
  exceptions.py       -- AI-specific exception classes

app/routers/
  ai_sessions.py      -- Session lifecycle: POST/DELETE /api/v1/ai/sessions
  ai_tools.py         -- Tool dispatch: POST /api/v1/ai/tools/{toolName}
  ai_files.py         -- File upload for ingestion: POST /api/v1/ai/files/upload
  ai_health.py        -- (optional, merged into existing health router)

app/services/ai/
  __init__.py
  session_service.py      -- Session creation, validation, expiry
  tool_executor.py        -- Tool dispatch + permission scoping + audit logging
  proposal_service.py     -- Proposal lifecycle (create, validate, apply, expire)
  audit_service.py        -- Audit log writer + reader
  rag_service.py          -- (stub) RAG query interface for similar courses
  ingestion_service.py    -- (stub) File extraction + segmentation
  model_router.py         -- (stub) Primary/fallback LLM routing
  validation_service.py   -- (stub) Schema + business rule validation

app/models/ai/
  __init__.py
  session.py          -- SQLAlchemy model for ai_sessions
  proposal.py         -- SQLAlchemy model for ai_proposals
  audit_log.py        -- SQLAlchemy model for ai_audit_log

app/repositories/ai/
  __init__.py
  session_repo.py     -- SessionRepository
  proposal_repo.py    -- ProposalRepository
  audit_repo.py       -- AuditLogRepository
```

#### Key Class Signatures

```python
# app/ai/config.py
@dataclass
class AIConfig:
    enabled: bool = False
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-3-5-sonnet-20241022"
    session_ttl_hours: int = 24
    rate_limit_per_hour: int = 100
    rate_limit_per_day: int = 500

    @classmethod
    def from_env(cls) -> "AIConfig":
        ...

# app/services/ai/session_service.py
class SessionService:
    def __init__(self, session_repo: SessionRepository, db_session: AsyncSession):
        ...

    async def create_session(
        self, user_id: str, course_id: str, organization_id: str
    ) -> SessionRecord:
        ...

    async def get_session(self, session_id: str) -> SessionRecord | None:
        ...

    async def close_session(self, session_id: str) -> None:
        ...

    async def validate_session_scope(
        self, session_id: str, user_id: str, course_id: str
    ) -> SessionRecord:
        ...

# app/services/ai/tool_executor.py
class ToolExecutor:
    def __init__(
        self,
        session_service: SessionService,
        proposal_service: "ProposalService",
        audit_service: AuditService,
        page_repo: PageRepository,
        course_repo: CourseRepository,
    ):
        ...

    async def execute(
        self, session_id: str, tool_name: str, input_data: dict
    ) -> dict:
        # 1. Validate session
        # 2. Permission scope check
        # 3. Rate limit check
        # 4. Execute tool handler
        # 5. Audit log
        ...

# app/services/ai/proposal_service.py
class ProposalService:
    def __init__(self, proposal_repo: ProposalRepository, ...):
        ...

    async def create_proposal(
        self, session_id: str, tool_name: str, proposal_data: dict
    ) -> ProposalRecord:
        ...

    async def apply_proposal(
        self, proposal_id: str, user_confirmed: bool
    ) -> dict:
        ...

    async def expire_stale_proposals(self) -> int:
        ...

# app/services/ai/audit_service.py
class AuditService:
    def __init__(self, audit_repo: AuditLogRepository):
        ...

    async def log(
        self,
        session_id: str, user_id: str, organization_id: str, course_id: str,
        tool_name: str, operation: str, result_status: str,
        before_state: dict | None = None,
        after_state: dict | None = None,
        error_code: str | None = None,
    ) -> None:
        ...

    async def query(
        self, user_id: str | None = None, course_id: str | None = None,
        limit: int = 100, offset: int = 0,
    ) -> list[dict]:
        ...
```

### 2.4 Configuration Variables

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `AI_AUTHORING_ENABLED` | bool | `false` | Master toggle for all AI features |
| `ANTHROPIC_API_KEY` | string | (none) | Anthropic API key for Claude |
| `ANTHROPIC_MODEL` | string | `claude-3-5-sonnet-20241022` | Primary Claude model |
| `ANTHROPIC_FALLBACK_MODEL` | string | `claude-3-5-haiku-20241022` | Fallback model |
| `AI_SESSION_TTL_HOURS` | int | `24` | Session expiry in hours |
| `AI_RATE_LIMIT_PER_HOUR` | int | `100` | Max tool calls per user per hour |
| `AI_RATE_LIMIT_PER_DAY` | int | `500` | Max LLM API calls per user per day |
| `AI_PROPOSAL_TTL_MINUTES` | int | `30` | Proposal expiration in minutes |
| `AI_AUDIT_RETENTION_DAYS` | int | `730` | Audit log retention (2 years) |

### 2.5 Integration Points

**Existing repositories that remain unchanged (reused by new AI services):**
- `app/repositories/course_repo.py` -- `CourseRepository.get_by_course_id()` for session scope validation
- `app/repositories/page_component_repo.py` -- `PageRepository.list_by_course()`, `PageRepository.get()` for page operations
- `app/repositories/template_repo.py` -- `TemplateRepository.list()` for listing templates in a course
- `app/repositories/template_definition_repo.py` -- `TemplateDefinitionRepository.get_by_type_key()` for schema retrieval

**Existing services that remain unchanged:**
- `app/utils/validation.py` -- `CourseValidator` for course-level business rule validation (reused by the validation pipeline)
- `app/services/export_validator.py` -- For SCORM compliance checks
- `app/services/scorm_export.py` -- For SCORM export (no changes needed)

**New external integrations:**
- Anthropic API (Claude) via `anthropic` Python SDK -- for LLM calls
- Optional: pgvector or similar for RAG -- future sprint

**Events:**
- None in this story. Future stories will emit domain events (proposal.applied, session.expired) for webhook/analytics consumers.

---

## 3. NON-FUNCTIONAL REQUIREMENTS

### 3.1 Performance Targets

| Metric | Target | Measurement |
|--------|--------|-------------|
| p50 latency (AI session create) | < 200 ms | From request receipt to response |
| p95 latency (AI tool execution) | < 3 s | Includes validation; excludes LLM call time |
| p99 latency (AI tool execution) | < 5 s | |
| AI routes throughput | 50 req/s per instance | Under 10 concurrent sessions |
| Existing routes throughput degradation | < 2% | Measured vs. pre-AI baseline under 100 req/s load |
| Feature flag check overhead | < 1 ms per request | In-memory boolean read |

### 3.2 Security Requirements

- **AuthZ Model:** All AI routes require existing JWT/Bearer token authentication via the middleware already registered in `app/main.py`. Additionally, AI tool calls require a valid `Authorization: Session {session_id}` header. The `SessionService.validate_session_scope()` method enforces that the session's `user_id` matches the authenticated user, and that `course_id` on the request matches the session's `course_id`.
- **Tenant Isolation:** Multi-tenant isolation is enforced by `organization_id` on the session. The `PageRepository.list_by_course()` already filters by `course_id`, which is itself scoped to an org through the existing `courses` table relationship.
- **Validation Rules:** Every incoming tool input is validated against the tool's JSON schema (using `jsonschema` or Pydantic). Malformed input returns `400 VALIDATION_ERROR` before any business logic runs.
- **Secrets:** `ANTHROPIC_API_KEY` MUST NOT be logged, returned in responses, or exposed in any error message. The `AuditService` MUST redact sensitive fields before persistence.
- **Rate Limiting:** Enforced per-user per-hour via an in-memory sliding-window counter (or Redis in production). Exceeded limits return `429 RATE_LIMIT_EXCEEDED`.
- **No Direct DB Access:** Prohibited tools (`execute_sql`, `direct_db_query`) are not defined in the tool schema. The `ToolExecutor` only dispatches to registered, whitelisted handlers.

### 3.3 Reliability

**Error Codes Catalog:**

| Code | HTTP Status | Description | Retryable |
|------|-------------|-------------|-----------|
| `VALIDATION_ERROR` | 400 | Input failed schema or business validation | true |
| `PERMISSION_DENIED` | 403 | Session/course mismatch or expired session | false |
| `NOT_FOUND` | 404 | Session, page, or proposal not found | false |
| `CONFIRMATION_MISMATCH` | 409 | Proposal already applied or expired | false |
| `RATE_LIMIT_EXCEEDED` | 429 | Tool call or LLM call limit hit | true (after `retry_after_seconds`) |
| `AI_NOT_CONFIGURED` | 503 | Feature flag on but missing API key | false |
| `AI_PROVIDER_AUTH_FAILED` | 503 | Anthropic API key invalid/expired | false |
| `AI_PROVIDER_TIMEOUT` | 504 | Anthropic API call timed out | true |
| `SERVER_ERROR` | 500 | Unexpected internal error | true |
| `TOOL_NOT_FOUND` | 404 | Unknown tool name | false |

**Retry Strategy:**
- Idempotent tools (`list_pages`, `fetch_page`, `apply_page_proposal`, `apply_update_proposal`): automatic retry up to 2 times with exponential backoff (1s, 4s) for 5xx responses.
- Non-idempotent tools (`propose_create_page`, `propose_delete_page`): no automatic retry. Return error to LLM for user-facing handling.
- Network/timeout errors to Anthropic API: automatic fallback to secondary model, up to 1 retry.

**Graceful Degradation:**
- If Anthropic API is unreachable, AI tools return `AI_PROVIDER_TIMEOUT`. Existing manual authoring continues unaffected.
- If the database for AI tables is unavailable, AI routes return `SERVER_ERROR`. Existing manual authoring continues unaffected.
- If ANTHROPIC_API_KEY is missing at startup with flag on, AI routes return 503. Health endpoint reports degraded status.

**Idempotency Guarantees:**
- `apply_page_proposal` and `apply_update_proposal` are idempotent via `proposal_id`: applying the same proposal twice returns the same result without creating duplicate records. The `is_applied` flag on the `ai_proposals` row prevents double-application.
- All read-only tools (`list_pages`, `fetch_page`, `validate_course`, `query_similar_courses`) are inherently idempotent.

### 3.4 Scalability

- **Statelessness:** All AI services are stateless with respect to the request-response cycle. Session state is persisted in PostgreSQL (`ai_sessions` table). No in-memory session state across instances.
- **Horizontal Scaling:** Multiple backend instances can be deployed behind a load balancer. Rate limiting requires a shared store (Redis) for accuracy across instances; the initial implementation uses per-instance in-memory counters which is acceptable for single-instance deployments.
- **Connection Pooling:** AI services reuse the existing `AsyncSession` from `app/db/config.py` which uses `pool_size=10`, `max_overflow=20`, `pool_pre_ping=True`. New `ai_sessions`, `ai_proposals`, `ai_audit_log` tables add minimal connection overhead (a few extra rows per AI session).

---

## 4. CURRENT STATE ASSESSMENT

### 4.1 What Exists in the Codebase That Can Be Reused

| File | What It Provides | How It Is Reused |
|------|------------------|------------------|
| `app/main.py` | FastAPI app setup, CORS, lifespan, router mounting | Modified to conditionally mount AI routers |
| `app/db/config.py` | AsyncSession, engine, `get_session()` dependency | Directly reused by AI repositories and services |
| `app/models/base.py` | Declarative Base for ORM | New AI models inherit from this Base |
| `app/models/persisted_course.py` | `CourseRecord`, `TemplateRecord`, `TemplateDefinition` | Reused for course/page lookups in tool execution |
| `app/models/page_component.py` | `PageRecord`, `ComponentRecord` | Reused by `fetch_page`, `list_pages` tool handlers |
| `app/models/course.py` | Pydantic `Course`, `Template`, `FinalAssessmentData`, etc. | Reused for validation + schema |
| `app/repositories/course_repo.py` | `CourseRepository.get_by_course_id()` | Reused for session scope validation |
| `app/repositories/page_component_repo.py` | `PageRepository.list_by_course()`, `get()` | Reused by tool handlers |
| `app/repositories/template_repo.py` | `TemplateRepository.list()` | Reused by `list_pages` tool |
| `app/repositories/template_definition_repo.py` | `TemplateDefinitionRepository.get_by_type_key()` | Reused for schema retrieval during validation |
| `app/utils/validation.py` | `CourseValidator`, `validate_course_json` | Reused by the validation pipeline tool |
| `app/routers/health.py` | Health check endpoint | Extended to report AI status |
| `app/routers/courses.py` | Course CRUD | Unchanged; AI tools call these via repository, not routes |
| `app/services/export_validator.py` | SCORM validation rules | Reused by `validate_course` tool |

### 4.2 What Must Be Built Net-New

| Component | Description |
|-----------|-------------|
| `app/ai/` package | All AI module scaffolding |
| `app/ai/config.py` | `AIConfig` dataclass with `from_env()` factory |
| `app/ai/feature_flag.py` | Singleton flag reader, middleware, FastAPI dependency |
| `app/ai/exceptions.py` | `AIServiceUnavailable`, `AIPermissionDenied`, `AIRateLimitExceeded`, etc. |
| `app/ai/dependencies.py` | `require_ai_enabled()`, `require_session()` FastAPI dependencies |
| `app/routers/ai_sessions.py` | Session lifecycle routes |
| `app/routers/ai_tools.py` | Tool dispatch endpoint |
| `app/routers/ai_files.py` | File upload endpoint |
| `app/services/ai/session_service.py` | Session creation, validation, expiry |
| `app/services/ai/tool_executor.py` | Tool dispatch, permission scoping, audit |
| `app/services/ai/proposal_service.py` | Proposal CRUD, apply, expiry |
| `app/services/ai/audit_service.py` | Audit log writing and querying |
| `app/models/ai/` package with 3 ORM models | `SessionRecord`, `ProposalRecord`, `AuditLogRecord` |
| `app/repositories/ai/` package with 3 repos | `SessionRepository`, `ProposalRepository`, `AuditLogRepository` |
| Alembic migration | Create `ai_sessions`, `ai_proposals`, `ai_audit_log` tables |

### 4.3 What Existing Code Must Be Modified (With Non-Regression Constraints)

**`app/main.py`**
- Add conditional import and mounting of AI routers inside the application setup, gated by `AI_AUTHORING_ENABLED`.
- Add `app.models.ai.session`, `app.models.ai.proposal`, `app.models.ai.audit_log` to the `lifespan` startup imports so their tables get created by `Base.metadata.create_all`.
- Non-regression constraint: The order of existing router mounting MUST NOT change. The `custom_openapi()` function MUST remain untouched (only appends Pydantic models, which is unrelated).

**`app/routers/health.py`**
- Add a new field `ai_authoring_enabled` (boolean) and `ai_status` (string: "configured" | "degraded" | "unavailable") to the health response.
- Non-regression constraint: All existing health response fields MUST remain, their formats unchanged. The new fields MUST be optional, defaulting to `false` / `"unavailable"`, so old clients that parse the health response do not break.

**`app/main.py` `lifespan()` function**
- After the existing startup block, conditionally validate AI config.
- Non-regression constraint: The `except Exception` catch-all currently prevents startup failures from crashing the app. The AI config validation MUST also be wrapped in a try/except that logs the error but does not crash.

---

## 5. EXPANSION POINTS

### 5.1 Technical Expansion in Future Sprints

**T1: Rate Limiting with Redis**
Replace in-memory per-instance counters with a Redis-backed sliding-window rate limiter for accurate enforcement across multiple backend instances. Add `REDIS_URL` config variable.

**T2: Proposal Garbage Collection**
Create a background scheduled job (APScheduler or Celery beat) that runs every 5 minutes to delete expired unapplied proposals from `ai_proposals` and closed sessions older than 7 days from `ai_sessions`.

**T3: Observability and Tracing**
Add OpenTelemetry instrumentation to all AI services. Export trace spans for each tool execution to capture LLM call duration, validation pipeline latency, and database query times. Add Prometheus metrics: `ai_tool_calls_total`, `ai_tool_latency_seconds`, `ai_session_count`.

**T4: Full RAG Implementation**
Replace the `rag_service.py` stub with a real pgvector-based similarity search. Add a background indexer that embeds course pages on create/update and stores embeddings in a `course_embeddings` table.

### 5.2 Functional Capability Growth

**F1: Multi-Page Batch Operations**
Extend the proposal system to support `propose_batch_create` and `propose_batch_update` operations that handle multiple pages atomically (all-or-nothing). This unlocks the full file ingestion pipeline.

**F2: AI Refine Mode with Diff Preview**
Add a `mode: "refine"` parameter to the chat session that enables the AI to propose targeted edits to existing pages with a visual diff preview in the UI (showing before/after per changed field).

**F3: Course-Level AI Operations**
Beyond single-page edits, support AI operations at the course level: reorder all pages, bulk-update metadata, generate a course summary, or produce a SCORM manifest compliance report.

**F4: AI Template Suggestions**
Based on existing courses in the same organization, the AI can suggest optimal template types for new pages ("this content looks like it would work better as tabs rather than text-content").

---

## 6. VALIDATION & TESTING

### 6.1 Unit Test Scenarios (At Least 5)

**UT-1: Feature flag blocks AI routes when disabled**
- **Setup:** `AIConfig(enabled=False)` created from env with `AI_AUTHORING_ENABLED=false`.
- **Input:** Call `require_ai_enabled()` FastAPI dependency.
- **Expected:** Raises `HTTPException(status_code=404)` (route not found). Existing health endpoint returns `aiAuthoringEnabled: false`.

**UT-2: Feature flag allows AI routes when enabled**
- **Setup:** `AIConfig(enabled=True, anthropic_api_key="sk-test")`.
- **Input:** Call `require_ai_enabled()` dependency.
- **Expected:** Passes without exception.

**UT-3: Session creation validates course existence**
- **Setup:** Mock `CourseRepository.get_by_course_id()` to raise `CourseNotFoundError`.
- **Input:** `SessionService.create_session(user_id="u1", course_id="nonexistent", organization_id="org1")`.
- **Expected:** Raises `HTTPException(status_code=404, detail="Course not found")`.

**UT-4: Tool executor rejects cross-course page access**
- **Setup:** Session with `course_id="course-A"`. `PageRepository.get()` returns a page with `course_id="course-B"`.
- **Input:** `ToolExecutor.execute(session_id="s1", tool_name="fetch_page", input={"page_id": "p1"})`.
- **Expected:** Returns `{"status": "error", "code": "PERMISSION_DENIED", "retryable": false}`.

**UT-5: Proposal apply is idempotent**
- **Setup:** `ProposalRecord` with `is_applied=True`.
- **Input:** `ProposalService.apply_proposal(proposal_id="p1", user_confirmed=True)`.
- **Expected:** Returns `{"status": "rejected", "message": "Proposal already applied"}`. No duplicate page created.

**UT-6: Audit log redacts sensitive fields**
- **Setup:** Input dict containing `{"apiKey": "secret123", "title": "safe"}`.
- **Input:** `AuditService._redact(input_data)`.
- **Expected:** Returns `{"apiKey": "[REDACTED]", "title": "safe"}`.

**UT-7: Session expiry check**
- **Setup:** `SessionRecord` with `expires_at = now - 1 hour`.
- **Input:** `SessionService.validate_session_scope(session_id="s1", user_id="u1", course_id="c1")`.
- **Expected:** Raises `HTTPException(status_code=403, detail="Session expired")`.

### 6.2 Integration Test Scenarios (At Least 3)

**IT-1: Full propose-create-apply flow**
- **Setup:** Start test app with `AI_AUTHORING_ENABLED=true`. Create a course via existing `POST /api/v1/courses`. Create an AI session.
- **Steps:**
  1. Call `POST /api/v1/ai/tools/propose_create_page` with valid `text-content` data.
  2. Assert response has `proposal_id`, `validation_status: "valid"`.
  3. Assert page count in course is unchanged.
  4. Call `POST /api/v1/ai/tools/apply_page_proposal` with `proposal_id` and `user_confirmed: true`.
  5. Assert response has `status: "created"`.
  6. Assert `GET /api/v1/courses/{id}` now returns 1 additional page.

**IT-2: Feature flag toggle does not affect existing routes**
- **Setup:** Seed database with 3 courses.
- **Steps with flag off:**
  1. `GET /api/v1/courses` returns 3 courses (assert 200).
  2. `POST /api/v1/ai/sessions` returns 404.
- **Toggle flag on:**
  3. `GET /api/v1/courses` still returns 3 courses (assert 200, same response body).
  4. `POST /api/v1/ai/sessions` returns 201.
- **Toggle flag off again:**
  5. `GET /api/v1/courses` returns 3 courses (assert 200).
  6. `POST /api/v1/ai/sessions` returns 404.

**IT-3: Missing API key degrades AI routes**
- **Setup:** Start app with `AI_AUTHORING_ENABLED=true`, no `ANTHROPIC_API_KEY`.
- **Steps:**
  1. `GET /api/v1/health` returns `aiStatus: "degraded"`.
  2. `POST /api/v1/ai/sessions` returns 503 with `code: "AI_NOT_CONFIGURED"`.
  3. Existing route `GET /api/v1/courses` returns 200 successfully.

### 6.3 E2E/Acceptance Test Scenarios (At Least 2)

**E2E-1: Manual authoring workflow is completely unaffected by AI presence**
- **Precondition:** Application running with `AI_AUTHORING_ENABLED=true`.
- **Steps:**
  1. Create a new course via `POST /api/v1/courses` (payload: valid `CourseCreate`).
  2. Add 3 pages via `POST /api/v1/courses/{id}/pages/from-template` (mixed templates: text-content, tabs, final-assessment).
  3. Update a page title via `PATCH /api/v1/courses/{id}/pages/{page_id}`.
  4. List pages via `GET /api/v1/courses/{id}/pages`.
  5. Delete a page via `DELETE /api/v1/courses/{id}/pages/{page_id}`.
  6. Export the course via `POST /api/v1/export/scorm`.
- **Expected:** All 6 operations succeed. SCORM export produces a valid zip. No AI data appears in any response. The `ai_sessions` table remains empty.

**E2E-2: AI session lifecycle with concurrent manual editing**
- **Precondition:** Application with AI enabled. Course "C1" with 2 pages exists.
- **Steps:**
  1. User A opens AI session on course C1.
  2. User B (concurrently) manually updates page 1's title via `PATCH /api/v1/courses/{c1}/pages/{p1}`.
  3. User A calls `POST /api/v1/ai/tools/fetch_page` with `page_id=p1`.
  4. The response contains User B's updated title (proving DB is source of truth, not cached session state).
  5. User A calls `propose_update_page` to change page 2's data.
  6. `propose_update_page` response shows `validation_status: "valid"`.
  7. User A calls `apply_update_proposal` with confirmation.
  8. Page 2 is updated. Audit log contains entries for both user A and user B operations.

### 6.4 Manual QA Verification Procedure

**Step-by-step manual test for feature flag + regression:**

1. **Setup:** Deploy backend with `AI_AUTHORING_ENABLED=false`. Ensure frontend is pointed at this backend.
2. **Verify baseline UI:** Open course editor. Confirm no "AI Authoring" button appears. All tabs, buttons, and panels render correctly.
3. **Verify baseline API:** Using Postman/curl, execute 10 representative API calls covering course CRUD, page CRUD, template operations, export, and import. Record response bodies.
4. **Enable AI:** Set `AI_AUTHORING_ENABLED=true`, `ANTHROPIC_API_KEY=sk-test`. Restart backend.
5. **Verify regression (UI):** Open editor again. Confirm "AI Authoring" button appears BUT all existing UI elements remain in their original positions and behave identically.
6. **Verify regression (API):** Replay the same 10 API calls from step 3. Assert identical response bodies (ignoring `updatedAt` timestamps).
7. **Verify AI entry point:** Click "AI Authoring" button. Confirm slide-out panel appears. Confirm status indicator shows green.
8. **Verify AI session creation:** In the panel, confirm a session is created (check `ai_sessions` table for new row).
9. **Verify degraded mode:** Remove `ANTHROPIC_API_KEY` env var, restart. Confirm health endpoint shows `aiStatus: "degraded"`. Confirm AI panel shows yellow indicator with "AI service not configured" message. Confirm existing course editor remains fully functional.
10. **Verify toggle off:** Set `AI_AUTHORING_ENABLED=false`, restart. Confirm AI button is gone. Confirm all 10 baseline API calls still work. Confirm `ai_sessions` table unchanged (no data loss).

---

## 7. DEFINITION OF DONE

**Code:**
- [ ] 1. `app/ai/` package created with `__init__.py`, `config.py`, `feature_flag.py`, `exceptions.py`, `dependencies.py`.
- [ ] 2. AI ORM models created in `app/models/ai/` (`session.py`, `proposal.py`, `audit_log.py`).
- [ ] 3. AI repositories created in `app/repositories/ai/` (`session_repo.py`, `proposal_repo.py`, `audit_repo.py`).
- [ ] 4. AI services created in `app/services/ai/` (`session_service.py`, `tool_executor.py`, `proposal_service.py`, `audit_service.py`).
- [ ] 5. AI routers created: `app/routers/ai_sessions.py`, `app/routers/ai_tools.py`, `app/routers/ai_files.py`.
- [ ] 6. `app/main.py` modified to conditionally mount AI routers and import AI models in lifespan.
- [ ] 7. `app/routers/health.py` extended with `aiAuthoringEnabled` and `aiStatus` fields.
- [ ] 8. All new routes use the `require_ai_enabled()` dependency to return 404 when flag is off / 503 when degraded.
- [ ] 9. `POST /api/v1/ai/tools/{toolName}` dispatches to correct handler based on tool name.
- [ ] 10. `ToolExecutor` validates session scope and permission for every call.
- [ ] 11. `ProposalService.apply_proposal()` is idempotent (checks `is_applied` flag).
- [ ] 12. `AuditService` redacts sensitive fields before persistence.

**Tests:**
- [ ] 13. All 7 unit tests pass (UT-1 through UT-7).
- [ ] 14. All 3 integration tests pass (IT-1 through IT-3).
- [ ] 15. All 2 E2E tests pass (E2E-1, E2E-2).
- [ ] 16. Existing test suite passes with zero regressions (run `pytest` on entire project).

**Docs & Migrations:**
- [ ] 17. Alembic migration script generated for `ai_sessions`, `ai_proposals`, `ai_audit_log` tables (or inline `create_all` for MVP).
- [ ] 18. `docs/AI_Implemenation/01_SystemArchitecture/PRODUCTION_READY_AI_AUTHORING_ARCHITECTURE.md` updated to reflect the actual file/module structure implemented.

**Feature Flag & Configuration:**
- [ ] 19. `AI_AUTHORING_ENABLED` documented in `app/ai/config.py` and `.env.example`.
- [ ] 20. `ANTHROPIC_API_KEY`, `AI_SESSION_TTL_HOURS`, `AI_RATE_LIMIT_PER_HOUR` documented in `.env.example`.

**QA & Performance:**
- [ ] 21. Manual QA verification procedure executed and signed off by QA engineer.
- [ ] 22. Load test with 50 concurrent API calls to existing routes shows < 5% performance degradation compared to pre-AI baseline.

**Security:**
- [ ] 23. `ANTHROPIC_API_KEY` never appears in logs, error messages, or API responses (verified by grep and manual test).
- [ ] 24. Rate limiting enforced: calling AI tools more than `AI_RATE_LIMIT_PER_HOUR` times in one hour returns `429 RATE_LIMIT_EXCEEDED`.

---

## 8. TASKS & SUB-TASKS

| ID | Task Description | Owner Role | Est. (h) | Dependencies |
|----|------------------|-----------|----------|--------------|
| T-001 | **Create AI module scaffolding** -- Create `app/ai/` package with `config.py`, `feature_flag.py`, `exceptions.py`, `dependencies.py`. Implement `AIConfig.from_env()` and `require_ai_enabled()` FastAPI dependency. | Backend Developer | 4 | None |
| T-002 | **Create AI database models and migrations** -- Create `app/models/ai/` package with `SessionRecord`, `ProposalRecord`, `AuditLogRecord` ORM models. Generate Alembic migration. Import models in `app/main.py` lifespan. | Backend Developer | 3 | T-001 |
| T-003 | **Create AI repositories** -- Create `app/repositories/ai/` package with `SessionRepository`, `ProposalRepository`, `AuditLogRepository`. Implement CRUD and query methods. | Backend Developer | 3 | T-002 |
| T-004 | **Implement SessionService** -- Create `app/services/ai/session_service.py` with `create_session()`, `get_session()`, `close_session()`, `validate_session_scope()`. Session TTL enforcement. | Backend Developer | 4 | T-003 |
| T-005 | **Implement ProposalService** -- Create `app/services/ai/proposal_service.py` with `create_proposal()`, `apply_proposal()` (with idempotency), `expire_stale_proposals()`. | Backend Developer | 5 | T-003 |
| T-006 | **Implement ToolExecutor + AuditService** -- Create `app/services/ai/tool_executor.py` with dispatch, permission scoping, rate limiting. Create `app/services/ai/audit_service.py` with `log()`, `query()`, `_redact()`. | Backend Developer | 6 | T-003, T-005 |
| T-007 | **Create AI routers** -- Create `app/routers/ai_sessions.py`, `app/routers/ai_tools.py`, `app/routers/ai_files.py`. Implement route handlers with proper status codes. Wire up dependencies. | Backend Developer | 5 | T-001, T-004, T-006 |
| T-008 | **Modify main.py and health router** -- Add conditional AI router mounting in `app/main.py`. Extend `app/routers/health.py` with `aiAuthoringEnabled` and `aiStatus`. Add AI model imports to lifespan. | Backend Developer | 3 | T-001, T-002, T-007 |
| T-009 | **Write unit tests (UT-1 through UT-7)** -- Mock all dependencies. Test feature flag behavior, session validation, tool permission scoping, proposal idempotency, audit redaction, session expiry. | Backend Developer | 4 | T-001..T-008 |
| T-010 | **Write integration tests (IT-1 through IT-3)** -- Use test database with migrations. Test full propose-apply flow, flag toggle regression, degraded mode. | Backend Developer | 4 | T-009 |
| T-011 | **Write E2E tests (E2E-1, E2E-2)** -- Use test client or docker-compose. Test complete manual authoring regression and concurrent AI/manual editing. | QA Engineer | 4 | T-010 |
| T-012 | **Manual QA and sign-off** -- Execute manual verification procedure. Document results. Verify `.env.example` updates. Perform security review (API key exposure, rate limiting). | QA Engineer + Security Engineer | 4 | T-011 |
| T-013 | **Documentation update** -- Update `PRODUCTION_READY_AI_AUTHORING_ARCHITECTURE.md` with final module layout. Update `.env.example`. Update OpenAPI spec with AI routes. | Technical Writer | 3 | T-008 |

**Total Estimated Hours:** 52 hours (approximately 6.5 developer-days with 2 developers)

---
The enriched epic for US-BKND-AI-002 has been written above in full. It covers all eight sections of the prescribed template:

1. **FUNCTIONAL SPECIFICATION** -- 10 numbered functional requirements (FR-001 through FR-010), four detailed user flows (happy path, alternate/fallback, both models fail, invalid config, disabled), and UI/UX guidance for admin and non-admin experiences.

2. **TECHNICAL SPECIFICATION** -- Exact API contracts for `GET /health/ai-configuration` and all AI error responses (503/403/400) with JSON schemas; full `CREATE TABLE ai_settings` DDL with seed data; complete class designs for `AIConfigurationManager`, `ModelRouter`, `CircuitBreakerState`, and `ModelCallResult` with all method signatures; a 14-row env variable table; and a 7-row integration points matrix.

3. **NON-FUNCTIONAL REQUIREMENTS** -- Performance targets at p50/p95/p99; a 6-code error catalog with retry semantics; security requirements covering three-layer authZ, secret redaction, model ID validation, and tenant isolation; retry strategy with exponential backoff; graceful degradation rules; and statelessness/scalability guarantees.

4. **CURRENT STATE ASSESSMENT** -- Nine specific existing assets to reuse (environment variable pattern from `app/db/config.py`, health endpoint from `app/routers/health.py`, startup lifecycle from `app/main.py` lifespan, etc.); 10 net-new files listed with full paths; three files to modify (`app/main.py`, `app/routers/health.py`, `app/models/__init__.py`) with explicit non-regression constraints.

5. **EXPANSION POINTS** -- Three technical expansions (distributed circuit breaker via Redis, centralized feature flag service, provider SDK abstraction) and three functional expansions (per-user model overrides, usage-based cost-optimized routing, automated model canary deployments).

6. **VALIDATION & TESTING** -- 8 specific unit test scenarios with input/expected-output/mock strategy; 3 integration test scenarios with setup/exercise/verify/teardown; 2 E2E acceptance tests; and a 6-step manual QA verification procedure.

7. **DEFINITION OF DONE** -- 19 checklist items covering code (6), tests (3), docs (1), migrations (2), feature flags (3), QA (1), performance (1), and security (2).

8. **TASKS & SUB-TASKS** -- 6 parent tasks (T-001 through T-006) with 22 sub-tasks, each with owner role, hourly estimate, and dependencies. Total estimated effort: 32 hours (4 engineer-days).

---
The complete enriched story for US-BKND-AI-003 has been written above in full. Key files referenced in the analysis:

- **Existing code to reuse:** `C:\Users\ADMIN\e-learning-backend\app\main.py` (conditional router registration), `C:\Users\ADMIN\e-learning-backend\app\utils\feature_flags.py` (feature gating), `C:\Users\ADMIN\e-learning-backend\app\utils\error_envelope.py` (error formatting), `C:\Users\ADMIN\e-learning-backend\app\db\config.py` (existing DB session), `C:\Users\ADMIN\e-learning-backend\app\models\base.py` (declarative base), `C:\Users\ADMIN\e-learning-backend\app\models\persisted_course.py` (extend for AI tables), `C:\Users\ADMIN\e-learning-backend\app\routers\health.py` (extend for AI health block), `C:\Users\ADMIN\e-learning-backend\tests\conftest.py` (reusable test fixtures)

- **Net-new files to create:** `app/ai/__init__.py`, `app/ai/router.py`, `app/ai/dependencies.py`, `app/ai/config.py`, `app/ai/exceptions.py`, `app/ai/schemas/__init__.py`, `app/services/ai/__init__.py`, `app/services/ai/config_service.py`, `app/services/ai/contract_verifier.py`, Alembic migration `20260614_0001_add_ai_tables.py`, test files

- **Architecture references:** `C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\01_SystemArchitecture\PRODUCTION_READY_AI_AUTHORING_ARCHITECTURE.md` (Section 3.1.1 AI Layer Separation, page 2-3), `C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\01_SystemArchitecture\TOOL_SCHEMAS_CLAUDE_NATIVE.md` (all 12 tool schemas), `C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\01_SystemArchitecture\DEVELOPER_ONBOARDING_GUIDE.md` (module structure on page 6)

---