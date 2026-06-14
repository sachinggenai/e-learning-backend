# US-AI-007 -- List and Fetch Course Pages for AI Context

**Title:** List and Fetch Course Pages for AI Context

**As an** AI Agent (Claude),  
**I want** read-only tools to list and fetch pages from the current course,  
**So that** proposals always use current database state and never rely on stale conversation context.

**Priority:** MUST  
**Depends on:** US-AI-006 (AI Session Creation)  
**Unlocks:** US-AI-008 (Validation Pipeline), US-AI-011 (Create Page Proposal), US-AI-012 (Update Page Proposal), US-AI-014 (Chat Edit)

---

## 1. FUNCTIONAL SPECIFICATION

### 1.1 Detailed User Story

An AI authoring session is created (US-AI-006) and scoped to a single course. The AI agent now needs to understand the current structure of the course before it can propose any changes. The agent calls `list_pages` to get metadata for every page in the course (title, type, order, timestamps). This call is idempotent and returns lightweight metadata only, enabling the agent to navigate the course structure without loading full content. When the agent needs to inspect or modify a specific page, it calls `fetch_page` with the page ID obtained from the listing. That call returns the full page content including all components, layout, theme, and completion configuration. Both tools validate the session, enforce course-scoped permissions, and reject requests for pages outside the session's course scope. The system caches list results briefly to reduce read pressure but always returns fresh data for fetch (because edits must see the latest mutations).

### 1.2 Numbered Functional Requirements

1. **FR-1 -- Session Validation:** Every list_pages and fetch_page call MUST validate that the `session_id` corresponds to an active, non-expired session. Expired or unknown sessions receive a 401/440 error.

2. **FR-2 -- Course Scope Enforcement:** The tool MUST verify that the course associated with the session matches the course context of every returned page. A fetch_page call for a page_id belonging to a different course than the session's course_id MUST be rejected with 403.

3. **FR-3 -- Page Metadata Listing:** The list_pages tool MUST return an ordered array of page metadata objects, each containing: `page_id`, `title`, `template_type` (from the page's layout or component types), `order`, `created_at`, `updated_at`, and a `page_etag` (computed deterministic hash of the page record for staleness detection).

4. **FR-4 -- Total Count:** The list_pages response MUST include a `total_pages` field indicating the number of pages in the course.

5. **FR-5 -- Full Page Fetch:** The fetch_page tool MUST return the complete page record including: `page_id`, `title`, `order`, `layout` (template_id and customizations), `theme` (page-level theme override), `page_completion`, `components` (full array with componentId, componentType, order, data, audioConfig, completionCriteria, styling, timestamps), `created_at`, `updated_at`, and `page_etag`.

6. **FR-6 -- Staleness Detection:** Every page response (both list and fetch) MUST include a `page_etag` field. This is used by subsequent proposal calls (US-AI-008/009) to detect concurrent modifications. The etag is computed as a SHA-256 hash of the page record's JSON serialization.

7. **FR-7 -- Audit Logging:** Every successful list_pages and fetch_page call MUST be recorded in the AI audit log with: timestamp, session_id, user_id, tool_name, page_id (if applicable), and result status.

8. **FR-8 -- Empty Course Handling:** A course with zero pages MUST return `{"pages": [], "total_pages": 0}` without errors.

9. **FR-9 -- Non-Existent Page:** A fetch_page call for a page_id that does not exist in the course MUST return 404 with a structured error body.

10. **FR-10 -- Idempotent Read Guarantee:** Both list_pages and fetch_page MUST be idempotent -- repeated calls with the same session produce the same data (assuming no intervening writes). They MUST never create, modify, or delete any database record.

### 1.3 Step-by-Step User Flow

#### Happy Path -- List then Fetch

```
Step 1:  AI Agent constructs list_pages call with session_id from US-AI-006.
Step 2:  Backend receives POST /api/v1/ai/tools/list_pages.
Step 3:  Session Manager validates session_id is active, non-expired, belongs to the caller.
Step 4:  Tool Executor looks up session.course_id.
Step 5:  PageRepository.list_by_course(course_id) is called; returns ordered PageRecord list.
Step 6:  Each PageRecord.to_dict() produces metadata; page_etag is computed.
Step 7:  Response built: { "pages": [...], "total_pages": N }.
Step 8:  Audit log entry written.
Step 9:  AI Agent receives page list, identifies the page to edit (e.g., "Introduction").
Step 10: AI Agent constructs fetch_page call with session_id and page_id.
Step 11: Backend receives POST /api/v1/ai/tools/fetch_page.
Step 12: Session validation again (Step 3).
Step 13: PageRepository.get_by_course_and_page(course_id, page_id) called.
Step 14: Cross-check: page.course_id MUST equal session.course_id.
Step 15: Full response built with all components.
Step 16: Audit log entry written.
Step 17: AI Agent receives full page data and can now propose edits.
```

#### Alternate/Error Paths

**Path A -- Expired Session:**
```
Step 3a: Session validation fails because session is expired.
Step 3b: Response: 401/440 with code "SESSION_EXPIRED",
         detail: "Session has expired. Please create a new session.",
         retryable: false.
```

**Path B -- Page Not Found:**
```
Step 13a: PageRepository returns None.
Step 13b: Response: 404 with code "PAGE_NOT_FOUND",
         detail: "Page 'abc-123' not found in course 'course-xyz'.",
         retryable: false.
```

**Path C -- Page Belongs to Different Course:**
```
Step 14a: page.course_id != session.course_id.
Step 14b: Response: 403 with code "PERMISSION_DENIED",
         detail: "Page does not belong to the session's course.",
         retryable: false.
```

**Path D -- Rate Limit Exceeded:**
```
Step 3b (alt): Rate limiter check fails (> 100 calls/hr).
Response: 429 with code "RATE_LIMIT_EXCEEDED",
         detail: "Tool call limit exceeded.",
         retryAfter: 3600,
         retryable: true.
```

**Path E -- Database Error (e.g., connection lost):**
```
Step 5a: Database query raises an exception.
Step 5b: Response: 503 with code "SERVER_ERROR",
         detail: "Temporary database error.",
         retryable: true.
```

### 1.4 UI/UX Requirements

These are backend AI tool endpoints -- there is no direct human UI interaction. However, the frontend AI integration layer (US-AI-024) MUST:

- Display a loading state while pages are being fetched.
- Show an inline error message if list_pages returns an error (e.g., "AI failed to load course pages. Please try again.").
- Notify the user if the session expired and offer to restart.
- Present the page listing visually in the AI chat panel so the user sees which pages the AI is referencing.

---

## 2. TECHNICAL SPECIFICATION

### 2.1 API Contracts

Both tools are exposed as POST endpoints under the AI tools router (`/api/v1/ai/tools`). The request body follows the Claude native tool-calling format but is mapped server-side to a unified tool execution endpoint.

#### Tool: `list_pages`

**Endpoint:** `POST /api/v1/ai/tools/list_pages`

**Headers:**
```
Content-Type: application/json
Authorization: Bearer <session_token>
X-Idempotency-Key: <optional, uuid>
```

**Request Body:**
```json
{
  "session_id": "string (uuid)"
}
```

**Response Body (200 OK):**
```json
{
  "status": "success",
  "data": {
    "pages": [
      {
        "page_id": "uuid-string",
        "title": "Introduction",
        "template_type": "content-text",
        "order": 0,
        "page_etag": "sha256-hex-64-chars",
        "created_at": "2026-06-14T10:00:00Z",
        "updated_at": "2026-06-14T12:00:00Z"
      }
    ],
    "total_pages": 1
  }
}
```

**Status Codes:**
| Code | Condition |
|------|-----------|
| 200  | Success |
| 401  | Missing or invalid session token |
| 440  | Session expired (custom status for session expiry) |
| 429  | Rate limit exceeded |
| 503  | Temporary backend/database error |

#### Tool: `fetch_page`

**Endpoint:** `POST /api/v1/ai/tools/fetch_page`

**Headers:** Same as list_pages.

**Request Body:**
```json
{
  "session_id": "string (uuid)",
  "page_id": "string (uuid)"
}
```

**Response Body (200 OK):**
```json
{
  "status": "success",
  "data": {
    "page_id": "uuid-string",
    "title": "Introduction",
    "order": 0,
    "layout": {
      "template_id": "tmpl-content-text",
      "customizations": {}
    },
    "theme": null,
    "page_completion": {
      "strategy": "all"
    },
    "page_etag": "sha256-hex-64-chars",
    "components": [
      {
        "component_id": "uuid-string",
        "component_type": "content-text",
        "order": 0,
        "data": {"content": "<p>Hello world</p>"},
        "audio_config": null,
        "completion_criteria": null,
        "styling": null,
        "created_at": "2026-06-14T10:00:00Z",
        "updated_at": "2026-06-14T12:00:00Z"
      }
    ],
    "created_at": "2026-06-14T10:00:00Z",
    "updated_at": "2026-06-14T12:00:00Z"
  }
}
```

**Status Codes:**
| Code | Condition |
|------|-----------|
| 200  | Success |
| 401  | Missing or invalid session token |
| 403  | Page does not belong to session's course |
| 404  | Page not found |
| 440  | Session expired |
| 429  | Rate limit exceeded |
| 503  | Temporary backend/database error |

**Error Response Envelope (all error codes):**
```json
{
  "status": "error",
  "code": "PAGE_NOT_FOUND",
  "message": "Page 'abc-123' not found in course 'course-xyz'.",
  "details": {
    "page_id": "abc-123",
    "course_id": "course-xyz"
  },
  "retryable": false
}
```

### 2.2 Database Schema DDL

The existing pages and components tables are reused (no new DDL needed for this story). The session table is defined in US-AI-006. The `page_etag` is computed at the application layer, not stored in the database.

**Existing `pages` table (from `app/models/page_component.py` PageRecord, `__tablename__ = "pages"`):**
```sql
CREATE TABLE pages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id         VARCHAR(64) NOT NULL UNIQUE,
    course_id       VARCHAR(64) NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    title           VARCHAR(200) NOT NULL,
    order_index     INTEGER NOT NULL DEFAULT 0,
    layout          JSON,
    theme_config    JSON,
    completion_config JSON,
    created_at      DATETIME NOT NULL DEFAULT (datetime('now')),
    updated_at      DATETIME NOT NULL DEFAULT (datetime('now')),
    -- Indexes:
    --   idx_pages_page_id UNIQUE on (page_id)
    --   idx_pages_course_id on (course_id)
);
```

**Existing `components` table (from `app/models/page_component.py` ComponentRecord, `__tablename__ = "components"`):**
```sql
CREATE TABLE components (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    component_id        VARCHAR(64) NOT NULL UNIQUE,
    page_id             VARCHAR(64) NOT NULL REFERENCES pages(page_id) ON DELETE CASCADE,
    component_type      VARCHAR(100) NOT NULL,
    order_index         INTEGER NOT NULL DEFAULT 0,
    data                JSON NOT NULL DEFAULT '{}',
    audio_config        JSON,
    completion_criteria JSON,
    styling             JSON,
    created_at          DATETIME NOT NULL DEFAULT (datetime('now')),
    updated_at          DATETIME NOT NULL DEFAULT (datetime('now')),
    -- Indexes:
    --   idx_components_component_id UNIQUE on (component_id)
    --   idx_components_page_id on (page_id)
    --   idx_components_type on (component_type)
);
```

**For PostgreSQL (production), the DDL is equivalent but uses `TIMESTAMP`/`TIMESTAMPTZ`:**
```sql
CREATE TABLE pages (
    id              SERIAL PRIMARY KEY,
    page_id         VARCHAR(64) NOT NULL,
    course_id       VARCHAR(64) NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    title           VARCHAR(200) NOT NULL,
    order_index     INTEGER NOT NULL DEFAULT 0,
    layout          JSONB,
    theme_config    JSONB,
    completion_config JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(page_id)
);
CREATE INDEX idx_pages_course_id ON pages(course_id);

CREATE TABLE components (
    id                  SERIAL PRIMARY KEY,
    component_id        VARCHAR(64) NOT NULL,
    page_id             VARCHAR(64) NOT NULL REFERENCES pages(page_id) ON DELETE CASCADE,
    component_type      VARCHAR(100) NOT NULL,
    order_index         INTEGER NOT NULL DEFAULT 0,
    data                JSONB NOT NULL DEFAULT '{}',
    audio_config        JSONB,
    completion_criteria JSONB,
    styling             JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(component_id)
);
CREATE INDEX idx_components_page_id ON components(page_id);
CREATE INDEX idx_components_type ON components(component_type);
```

**AI Sessions table (defined in US-AI-006, referenced here):**
```sql
CREATE TABLE ai_sessions (
    id              SERIAL PRIMARY KEY,
    session_id      VARCHAR(64) NOT NULL UNIQUE,
    user_id         VARCHAR(64) NOT NULL,
    course_id       VARCHAR(64) NOT NULL,
    organization_id VARCHAR(64),
    status          VARCHAR(32) NOT NULL DEFAULT 'active',
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_ai_sessions_user ON ai_sessions(user_id);
CREATE INDEX idx_ai_sessions_course ON ai_sessions(course_id);
```

**AI Audit Logs table (referenced but not created by this story; created by US-AI-004):**
```sql
CREATE TABLE ai_audit_logs (
    id              SERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id         VARCHAR(64) NOT NULL,
    organization_id VARCHAR(64),
    session_id      VARCHAR(64) NOT NULL,
    tool_name       VARCHAR(64) NOT NULL,
    operation       VARCHAR(32),
    resource_id     VARCHAR(64),
    request_body    JSONB,
    response_status VARCHAR(32),
    error_code      VARCHAR(64),
    ip_address      VARCHAR(45),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_audit_user ON ai_audit_logs(user_id);
CREATE INDEX idx_audit_session ON ai_audit_logs(session_id);
CREATE INDEX idx_audit_tool ON ai_audit_logs(tool_name);
CREATE INDEX idx_audit_timestamp ON ai_audit_logs(timestamp);
```

### 2.3 Service/Module Design

#### New File: `app/services/ai/tool_executor.py`

```python
"""
AI Tool Executor Service

Orchestrates the execution of registered AI tools: input validation, session
checking, permission scoping, rate limiting, repository calls, and audit logging.
"""
from __future__ import annotations
from typing import Any, Dict, Optional
from hashlib import sha256
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.page_component_repo import PageRepository

class ToolExecutor:
    """Stateless executor for AI tool calls."""

    def __init__(
        self,
        session_repo: "AISessionRepository",         # from US-AI-006
        page_repo: PageRepository,
        audit_repo: "AIAuditLogRepository",           # from US-AI-004
        rate_limiter: "RateLimiter",                   # from US-AI-021
    ):
        self.session_repo = session_repo
        self.page_repo = page_repo
        self.audit_repo = audit_repo
        self.rate_limiter = rate_limiter

    async def execute_tool(
        self,
        tool_name: str,
        payload: Dict[str, Any],
        caller_user_id: str,
        ip_address: str = "",
    ) -> Dict[str, Any]:
        """Validate session, check perms, run tool, audit, return result."""
        # 1. Extract and validate session
        session_id = payload.get("session_id")
        if not session_id:
            return self._error("VALIDATION_ERROR", "session_id is required")
        
        session = await self.session_repo.get_active(session_id)
        if not session:
            return self._error("SESSION_INVALID", "Session not found or expired", status=440)
        if session.user_id != caller_user_id:
            return self._error("PERMISSION_DENIED", "Session user mismatch", status=403)
        
        # 2. Rate limit check
        allowed, retry_after = await self.rate_limiter.check(session.user_id, tool_name)
        if not allowed:
            return self._rate_limit_error(retry_after)
        
        # 3. Route to handler
        if tool_name == "list_pages":
            result = await self._handle_list_pages(session.course_id)
        elif tool_name == "fetch_page":
            result = await self._handle_fetch_page(
                session.course_id, payload.get("page_id", "")
            )
        else:
            return self._error("UNKNOWN_TOOL", f"Unknown tool: {tool_name}")
        
        # 4. Audit (async, non-blocking fire-and-forget or enqueue)
        await self.audit_repo.log(
            session_id=session_id,
            user_id=caller_user_id,
            tool_name=tool_name,
            resource_id=payload.get("page_id"),
            request_body=payload,
            response_status="success" if result.get("status") == "success" else "error",
        )
        
        return result

    async def _handle_list_pages(self, course_id: str) -> Dict[str, Any]:
        pages = await self.page_repo.list_by_course(course_id)
        page_list = []
        for p in pages:
            page_list.append({
                "page_id": p.page_id,
                "title": p.title,
                "template_type": self._derive_template_type(p),
                "order": p.order_index,
                "page_etag": self._compute_page_etag(p),
                "created_at": p.created_at.isoformat(),
                "updated_at": p.updated_at.isoformat(),
            })
        return {
            "status": "success",
            "data": {
                "pages": page_list,
                "total_pages": len(page_list),
            },
        }

    async def _handle_fetch_page(self, course_id: str, page_id: str) -> Dict[str, Any]:
        if not page_id:
            return self._error("VALIDATION_ERROR", "page_id is required")
        
        page = await self.page_repo.get_by_course_and_page(course_id, page_id)
        if not page:
            return self._error(
                "PAGE_NOT_FOUND",
                f"Page '{page_id}' not found in course '{course_id}'",
                details={"page_id": page_id, "course_id": course_id},
            )
        
        page_dict = page.to_dict(include_components=True)
        page_dict["page_etag"] = self._compute_page_etag(page)
        return {"status": "success", "data": page_dict}

    def _derive_template_type(self, page: "PageRecord") -> str:
        """Infer the primary template type from page layout or first component."""
        if page.layout and "template_id" in page.layout:
            return page.layout["template_id"]
        if page.components and len(page.components) > 0:
            return page.components[0].component_type
        return "unknown"

    def _compute_page_etag(self, page: "PageRecord") -> str:
        """Deterministic SHA-256 hash of page serialization for staleness."""
        raw = str(sorted(page.to_dict(include_components=True).items()))
        return sha256(raw.encode("utf-8")).hexdigest()

    def _error(self, code: str, msg: str, status: int = 400, details: dict = None, retryable: bool = False) -> Dict:
        return {
            "status": "error",
            "code": code,
            "message": msg,
            "details": details or {},
            "retryable": retryable,
            "_http_status": status,
        }

    def _rate_limit_error(self, retry_after: int) -> Dict:
        return {
            "status": "error",
            "code": "RATE_LIMIT_EXCEEDED",
            "message": "Tool call limit exceeded. Please wait before retrying.",
            "retryAfter": retry_after,
            "retryable": True,
            "_http_status": 429,
        }
```

#### New File: `app/routers/ai_tools.py`

```python
"""AI Tool Router -- Thin HTTP adapter over ToolExecutor."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.config import get_session
from app.services.ai.tool_executor import ToolExecutor

router = APIRouter(prefix="/api/v1/ai/tools", tags=["AI Tools"])

async def _get_executor(session: AsyncSession = Depends(get_session)) -> ToolExecutor:
    from app.repositories.page_component_repo import PageRepository
    # Repositories injected here; session_repo and audit_repo from US-AI-004/US-AI-006
    from app.repositories.ai_session_repo import AISessionRepository
    from app.repositories.ai_audit_repo import AIAuditLogRepository
    from app.services.ai.rate_limiter import RateLimiter
    return ToolExecutor(
        session_repo=AISessionRepository(session),
        page_repo=PageRepository(session),
        audit_repo=AIAuditLogRepository(session),
        rate_limiter=RateLimiter(),
    )

@router.post("/list_pages")
async def list_pages(
    payload: dict,
    request: Request,
    executor: ToolExecutor = Depends(_get_executor),
):
    result = await executor.execute_tool(
        "list_pages", payload,
        caller_user_id=request.headers.get("X-User-Id", ""),
        ip_address=request.client.host if request.client else "",
    )
    status = result.pop("_http_status", 200)
    if status >= 400:
        raise HTTPException(status_code=status, detail=result)
    return result

@router.post("/fetch_page")
async def fetch_page(
    payload: dict,
    request: Request,
    executor: ToolExecutor = Depends(_get_executor),
):
    result = await executor.execute_tool(
        "fetch_page", payload,
        caller_user_id=request.headers.get("X-User-Id", ""),
        ip_address=request.client.host if request.client else "",
    )
    status = result.pop("_http_status", 200)
    if status >= 400:
        raise HTTPException(status_code=status, detail=result)
    return result
```

#### Constructor Dependencies for ToolExecutor:

| Dependency | Source | Purpose |
|---|---|---|
| `AISessionRepository` | US-AI-006 (to be built) | Validate session, look up course_id |
| `PageRepository` | `app/repositories/page_component_repo.py` | List/fetch page records (EXISTS) |
| `AIAuditLogRepository` | US-AI-004 (to be built) | Write audit trail |
| `RateLimiter` | US-AI-021 (to be built) | Enforce per-user/per-hour tool call limits |

### 2.4 Configuration Variables

| Variable | Type | Default | Description |
|---|---|---|---|
| `AI_TOOL_RATE_LIMIT_PER_HOUR` | int | 100 | Max tool calls per user per hour |
| `AI_SESSION_TTL_HOURS` | int | 24 | Session expiry in hours |
| `AI_AUDIT_ENABLED` | bool | true | Enable/disable audit logging |
| `AI_TOOL_PAGE_ETAG_ALGORITHM` | str | "sha256" | Hash algorithm for page etags |

### 2.5 Integration Points

| Integration | What it does | Existing? |
|---|---|---|
| `PageRepository.list_by_course(course_id)` | Returns `List[PageRecord]` with `selectinload(PageRecord.components)` | EXISTS in `app/repositories/page_component_repo.py` line 18 |
| `PageRepository.get_by_course_and_page(course_id, page_id)` | Returns `Optional[PageRecord]` with `selectinload(PageRecord.components)` | EXISTS in `app/repositories/page_component_repo.py` line 35 |
| `AISessionRepository.get_active(session_id)` | Returns active session or None | NEW (US-AI-006) |
| `AIAuditLogRepository.log(...)` | Writes audit entry | NEW (US-AI-004) |
| `RateLimiter.check(user_id, tool_name)` | Returns (allowed, retry_after) | NEW (US-AI-021) |
| `ComponentRepository` | Not directly called; pages include components via `selectinload` | EXISTS but not invoked directly here |

---

## 3. NON-FUNCTIONAL REQUIREMENTS

### 3.1 Performance Targets

| Metric | Target | Measurement |
|---|---|---|
| p50 list_pages latency | < 50 ms | For a course with < 100 pages |
| p95 list_pages latency | < 150 ms | Under normal load |
| p99 list_pages latency | < 500 ms | Under peak load |
| p50 fetch_page latency | < 50 ms | Page with < 20 components |
| p95 fetch_page latency | < 150 ms | Page with < 50 components |
| p99 fetch_page latency | < 500 ms | Worst-case page size |
| Throughput | > 100 req/s per instance | For list_pages + fetch_page |
| Database query count per list_pages | 1 query (with joinedload/selectinload) | No N+1 |
| Database query count per fetch_page | 1 query (with selectinload) | No N+1 |

### 3.2 Security Requirements

**Authorization Model:**
- Session-based: the caller presents a session_id obtained from POST /api/v1/ai/sessions (US-AI-006).
- Tool Executor validates session.user_id against the authenticated caller (X-User-Id header or JWT claim).
- All tool execution is scoped to session.course_id -- a caller can only read pages within their session's course.
- Cross-course reads are rejected with 403.
- No role-based distinctions for read operations within the session scope (any authorized session member can read any page).

**Validation Rules:**
- `session_id` must be a valid UUID v4 string.
- `page_id` must be a valid UUID v4 string (for fetch_page).
- Payload size limit: 8 KB per request.
- Content-Type must be `application/json`.

**Tenant Isolation:**
- Sessions are scoped to `organization_id` at creation time.
- PageRepository queries naturally filter by `course_id`, which is bound to the session.
- If multi-tenant, the `courses` table includes an `organization_id` column; the repository layer must add this to the WHERE clause. This should be done at the repository level (cross-cutting concern), not in the tool executor.

### 3.3 Reliability

**Error Codes Catalog:**

| Code | HTTP Status | Meaning | Retryable |
|---|---|---|---|
| `VALIDATION_ERROR` | 400 | Missing or malformed required field | Yes (fix payload) |
| `SESSION_INVALID` | 401 | Session not found | No |
| `SESSION_EXPIRED` | 440 | Session TTL exceeded | No (create new session) |
| `PERMISSION_DENIED` | 403 | Page not in session's course | No |
| `PAGE_NOT_FOUND` | 404 | Page ID not found in course | No |
| `RATE_LIMIT_EXCEEDED` | 429 | Too many tool calls | Yes (wait and retry) |
| `SERVER_ERROR` | 503 | Unexpected backend error | Yes |
| `UNKNOWN_TOOL` | 400 | Unrecognized tool name | No |

**Retry Strategy:**
- For `RATE_LIMIT_EXCEEDED`: caller MUST honor the `retryAfter` value (in seconds) before retrying. The backend does not auto-retry.
- For `SERVER_ERROR` (503): caller SHOULD retry with exponential backoff (1s, 2s, 4s, max 30s). Max 3 retries.
- For `VALIDATION_ERROR`: caller MAY fix the payload and retry. No automatic retry by the backend.
- All other errors: not retryable.

**Graceful Degradation:**
- If the database is unreachable, return 503 with a clear message. The session validity check reaches the same database, so a 503 from either query is acceptable.
- If audit logging fails, the tool execution should succeed (audit failure should not block reads). Implement audit as a fire-and-forget task with its own error handling.
- If rate limiter storage (Redis) is unavailable, fall back to a conservative in-memory counter per instance (best-effort, not authoritative). Log the fallback.

**Idempotency Guarantees:**
- `list_pages`: fully idempotent. No side effects. Same inputs always return the same data (barring concurrent writes to the course).
- `fetch_page`: fully idempotent. Same inputs always return the same data.

### 3.4 Scalability

- **Statelessness:** ToolExecutor is stateless. All state is in the session repository (database or Redis) and the page repository (database). Multiple instances can run behind a load balancer.
- **Horizontal Scaling:** Since there is no in-memory session affinity requirement, instances can scale horizontally. The rate limiter should use a shared store (Redis) to enforce limits accurately across instances; fallback in-memory is best-effort.
- **Connection Pooling:** The database config at `app/db/config.py` already sets `pool_size=10` and `max_overflow=20` with `pool_pre_ping=True`. This is sufficient for initial deployment. Monitor connection pool utilization under load.
- **Caching (Optional):** A short TTL cache (e.g., 5 seconds) for list_pages responses per course_id can reduce database read pressure. Use Redis with the key pattern `ai:pages:list:{course_id}`. This is a future optimization, not required for MVP.

---

## 4. CURRENT STATE ASSESSMENT

### 4.1 What Exists and Can Be Reused

| File | What Reuses | Specific Lines/Methods |
|---|---|---|
| `app/models/page_component.py` | `PageRecord` ORM model with `to_dict(include_components=True)` | Lines 20-74. The model already has `page_id`, `course_id`, `title`, `order_index`, `layout`, `theme_config`, `completion_config`, `created_at`, `updated_at`, and the `components` relationship with `selectinload` lazy loading. |
| `app/models/page_component.py` | `ComponentRecord` ORM model with `to_dict()` | Lines 77-128. Already has `component_id`, `component_type`, `order_index`, `data`, `audio_config`, `completion_criteria`, `styling`, timestamps. |
| `app/repositories/page_component_repo.py` | `PageRepository.list_by_course(course_id)` | Line 18. Returns `List[PageRecord]` with `selectinload(PageRecord.components)`, ordered by `order_index`. |
| `app/repositories/page_component_repo.py` | `PageRepository.get_by_course_and_page(course_id, page_id)` | Line 35. Returns `Optional[PageRecord]` with `selectinload(PageRecord.components)`. |
| `app/repositories/page_component_repo.py` | `ComponentRepository.list_by_course(course_id)` | Line 135. Already joins pages to get all components per course. Not directly needed but available. |
| `app/models/persisted_course.py` | `CourseRecord` model with `course_id` field | Lines 24-59. The `course_id` field is used for scoping. |
| `app/db/config.py` | `get_session()` FastAPI dependency, async engine, pool settings | Lines 70-78. Already provides `AsyncSession` with proper pooling. |
| `app/main.py` | Router registration, lifespan, CORS | Lines 161-177. The existing pattern for registering routers will be extended to register `ai_tools.router`. |
| `tests/conftest.py` | Test fixtures: `test_client`, `sample_course_data`, `sample_course_json`, in-memory SQLite setup | Lines 28-113. The in-memory SQLite test pattern and the `_override_session` dependency override are reusable for AI tool tests. |
| `tests/test_page_components_api.py` | Test patterns for page CRUD | Lines 1-100. The test approach of creating courses via POST, then pages via POST, then listing/reading is directly applicable. |

### 4.2 What Must Be Built Net-New

| Component | Reason |
|---|---|
| `app/services/ai/tool_executor.py` | The core orchestration service for all AI tools. Does not exist yet. |
| `app/routers/ai_tools.py` | HTTP router for `/api/v1/ai/tools/list_pages` and `fetch_page`. Does not exist. |
| `app/services/ai/__init__.py` | Package init for the AI services package. Does not exist. |
| `app/repositories/ai_session_repo.py` | Session persistence (referenced as dependency, created by US-AI-006). Placeholder or stub needed for testing. |
| `app/repositories/ai_audit_repo.py` | Audit logging (referenced as dependency, created by US-AI-004). Placeholder or stub needed for testing. |
| `app/services/ai/rate_limiter.py` | Rate limiter (referenced as dependency, created by US-AI-021). Simple in-memory stub for MVP. |

### 4.3 What Existing Code Must Be Modified

| File | Change | Non-Regression Constraint |
|---|---|---|
| `app/main.py` | Add `from app.routers import ai_tools` and `api_router.include_router(ai_tools.router)` | Existing route registration is unchanged; disabling AI must still work if the feature flag is off (US-AI-002). The import should be behind a feature flag or conditionally registered. |
| `app/models/page_component.py` | **No change needed.** The existing `PageRecord.to_dict()` and `ComponentRecord.to_dict()` meet all requirements. The `page_etag` is computed externally in ToolExecutor. |
| `app/repositories/page_component_repo.py` | **No change needed.** The existing `PageRepository.list_by_course()` and `get_by_course_and_page()` meet all requirements. |

---

## 5. EXPANSION POINTS

### 5.1 Technical Expansion Points (Future Sprints)

1. **Server-Side Caching:** Add Redis-backed caching for list_pages responses with a 5-second TTL. Cache key: `ai:pages:list:{course_id}`. Invalidate on any page mutation in the course. Reduces DB read pressure for repeated list calls within the same AI conversation turn.

2. **ETag-Based Conditional Reads:** Support `If-None-Match` headers on fetch_page. If the caller sends the last-known etag and the page hasn't changed, return 304 Not Modified with an empty body. This reduces bandwidth for AI agents that poll for changes.

3. **Field-Level Projection:** Allow fetch_page to accept an optional `fields` parameter (e.g., `["title", "components.data"]`) to return only the requested sub-fields. This reduces response size for AI agents that only need specific content (e.g., only component data for editing). Implement via a JSON-path projection utility.

### 5.2 Functional Expansion Points

1. **Search and Filter:** Extend list_pages with optional filters: `search` (text match on title), `template_type` (filter by type), `modified_since` (ISO timestamp). Enables the AI agent to find specific pages more efficiently.

2. **Page Summary in List:** Add a `summary` or `excerpt` field to list_pages response -- a truncated plain-text extraction of the page content (first 200 chars). This helps the AI agent understand page content at a glance without fetching every page individually.

3. **Page Lock/Status Indicators:** Add `lock_status` (locked_by_user_id, locked_at) and `page_status` (draft, published, archived) fields to both list and fetch responses. Enables concurrent edit awareness in future multi-user AI sessions.

---

## 6. VALIDATION AND TESTING

### 6.1 Unit Test Scenarios (at least 5)

**Test 1: list_pages returns empty list for course with no pages**
```
Input: session with course_id = "course-empty", course has 0 pages
Expected Output: { "status": "success", "data": { "pages": [], "total_pages": 0 } }
Assertions:
  - status == "success"
  - data.pages is a list
  - len(data.pages) == 0
  - data.total_pages == 0
  - PageRepository.list_by_course was called exactly once with course_id "course-empty"
```

**Test 2: list_pages returns ordered pages with correct metadata**
```
Input: session with course_id = "course-abc", course has 3 pages ordered 0, 1, 2
Expected Output: pages array length == 3, ordered by order_index ascending
Assertions:
  - pages[0].page_id == page_a.page_id
  - pages[0].title == "Page A"
  - pages[0].order == 0
  - pages[0].template_type is not empty
  - pages[0].page_etag matches sha256 of page_a.to_dict()
  - pages[1].order == 1
  - pages[2].order == 2
```

**Test 3: fetch_page returns full page with components**
```
Input: session with course_id = "course-abc", page_id = "page-42"
        Page has 3 components of type "content-text", "tabs", "mcq"
Expected Output: full page dict with components array
Assertions:
  - data.page_id == "page-42"
  - data.title is present
  - data.page_etag is a 64-char hex string
  - len(data.components) == 3
  - data.components[0].component_type == "content-text"
  - data.components[0].data is a dict
  - data.components[0].component_id is a non-empty string
  - data.layout is present (may be None if not set)
  - data.created_at and data.updated_at are ISO format strings
```

**Test 4: fetch_page returns 404 for non-existent page**
```
Input: session for "course-abc", page_id = "non-existent-id"
Expected Output: error response
Assertions:
  - status == "error"
  - code == "PAGE_NOT_FOUND"
  - message contains "non-existent-id"
  - retryable == false
  - _http_status == 404
```

**Test 5: Expired session returns error for both tools**
```
Input: session_id = "expired-session-1", session is expired (expires_at in past)
Expected Output: error response for both list_pages and fetch_page
Assertions:
  - status == "error"
  - code == "SESSION_EXPIRED"
  - _http_status == 440
  - retryable == false
  - Neither PageRepository method was called
```

### 6.2 Integration Test Scenarios (at least 3)

**Test 1: Full list-then-fetch flow via HTTP**
```
Setup:
  1. Create course via POST /api/v1/courses (201)
  2. Create 2 pages via POST /api/v1/courses/{id}/pages (201 each)
  3. Create a session via POST /api/v1/ai/sessions (mock or real)

Steps:
  1. POST /api/v1/ai/tools/list_pages with { session_id }
  2. Extract first page_id from response
  3. POST /api/v1/ai/tools/fetch_page with { session_id, page_id }

Assertions:
  - list_pages returns 200 with 2 pages
  - pages are in correct order (order_index 0, 1)
  - fetch_page returns 200 with full page data
  - fetch_page response includes components
  - page_etag values are consistent (re-fetch returns same etag if no mutation)
```

**Test 2: Cross-course page fetch is rejected**
```
Setup:
  1. Create course A and course B
  2. Create page P1 in course A, page P2 in course B
  3. Create session for course A

Steps:
  1. POST /api/v1/ai/tools/fetch_page with session_id (course A) and page_id = P2

Assertions:
  - Response status == 403
  - error code == "PERMISSION_DENIED"
  - message indicates page doesn't belong to session's course
```

**Test 3: Database unavailability returns 503**
```
Setup:
  1. Mock/replace PageRepository.list_by_course to raise an exception (e.g., OperationalError)
  2. Create a valid session

Steps:
  1. POST /api/v1/ai/tools/list_pages

Assertions:
  - Response status == 503
  - error code == "SERVER_ERROR"
  - retryable == true
```

### 6.3 E2E/Acceptance Test Scenarios (at least 2)

**Test 1: AI agent can discover and read a newly created page (end-to-end via test client)**
```
Setup:
  1. Create course.
  2. Add page with 2 components via page_components API.
  3. Create AI session scoped to course.
  4. Call list_pages -> receives 1 page in response.
  5. Call fetch_page with the page_id -> receives full page + 2 components.
  6. Verify components match what was created.
  7. Verify page_etag can be used for staleness comparison.
```

**Test 2: Session expiry prevents all read operations**
```
Setup:
  1. Create course with 1 page.
  2. Create AI session with a very short TTL (e.g., 1 second).
  3. Wait for TTL to expire (or mock time).

Steps:
  1. Call list_pages -> 440/SESSION_EXPIRED.
  2. Call fetch_page -> 440/SESSION_EXPIRED.
  3. Verify that no PageRepository method was called (assert via mock).
```

### 6.4 Step-by-Step Manual QA Verification Procedure

```
Prerequisites:
  - Backend running (local dev or test environment)
  - PostgreSQL with seeded data
  - Authentication token available

Step 1: Create a course
  POST /api/v1/courses
  Body: { "courseId": "qa-test-course-1", "title": "QA Test Course" }
  Expected: 201 with course object

Step 2: Add pages to the course
  POST /api/v1/courses/qa-test-course-1/pages
  Body: { "title": "Page 1", "components": [{ "componentType": "content-text", "data": {"content": "Hello"} }] }
  Expected: 201
  
  Repeat to create 3 pages total (Page 1, Page 2, Page 3)

Step 3: Create an AI session
  POST /api/v1/ai/sessions
  Body: { "course_id": "qa-test-course-1", "user_id": "qa-user", "organization_id": "qa-org" }
  Expected: 201 with session_id

Step 4: Test list_pages
  POST /api/v1/ai/tools/list_pages
  Body: { "session_id": "<session_id from Step 3>" }
  Expected: 200, pages array with 3 items in order, total_pages = 3
  Verify: each page has page_id, title, template_type, order, page_etag, timestamps

Step 5: Test fetch_page
  POST /api/v1/ai/tools/fetch_page
  Body: { "session_id": "<session_id>", "page_id": "<page_id of Page 1>" }
  Expected: 200, full page object including components array with 1 component
  Verify: page_etag matches the one from list_pages

Step 6: Test fetch_page with invalid page_id
  POST /api/v1/ai/tools/fetch_page
  Body: { "session_id": "<session_id>", "page_id": "does-not-exist" }
  Expected: 404, error code PAGE_NOT_FOUND

Step 7: Test with expired/invalid session
  POST /api/v1/ai/tools/list_pages
  Body: { "session_id": "00000000-0000-0000-0000-000000000000" }
  Expected: 401 or 440, error code SESSION_INVALID or SESSION_EXPIRED

Step 8: Verify audit trail
  Query ai_audit_logs table (or admin API)
  Expected: 1 record for list_pages, 1 record for successful fetch_page,
            1 record for failed fetch_page (404), 1 record for failed list_pages (expired session)

Step 9: Verify no database mutations
  Check pages, components tables
  Expected: no changes to any existing records. No new rows. No deleted rows.
```

---

## 7. DEFINITION OF DONE

1. **Code complete:** `app/services/ai/tool_executor.py`, `app/routers/ai_tools.py`, and `app/services/ai/__init__.py` are implemented and merged to `demo-course-AI` branch.

2. **Existing routes preserved:** All existing `GET /api/v1/courses/{courseId}/pages` and `GET /api/v1/courses/{courseId}/pages/{pageId}` endpoints continue to work identically (non-regression verified).

3. **Router registration:** `ai_tools.router` is added to `app/main.py` under the `/api/v1/ai/tools` prefix. The registration is conditional via feature flag (US-AI-002) or at minimum wrapped so disabling it leaves the app intact.

4. **Unit tests pass:** At least 5 unit tests from section 6.1 are implemented, covering: empty course listing, ordered listing, full page fetch, 404 for missing page, and expired session rejection. All pass.

5. **Integration tests pass:** At least 3 integration tests from section 6.2 are implemented and pass against the in-memory SQLite test database.

6. **E2E tests pass:** At least 2 end-to-end test scenarios from section 6.3 pass, validating the complete list-then-fetch flow and session expiry behavior.

7. **Manual QA verified:** Section 6.4 manual QA procedure is executed and signed off by QA engineer. All steps produce expected results.

8. **API documentation updated:** OpenAPI specification includes the new `/api/v1/ai/tools/list_pages` and `/api/v1/ai/tools/fetch_page` endpoints with proper request/response schemas.

9. **Tool schema published:** The `TOOL_SCHEMAS_CLAUDE_NATIVE.md` document is updated with the final `list_pages` and `fetch_page` tool definitions reflecting the actual API contract (any drift from the architecture spec corrected).

10. **Audit logging verified:** Audit entries are written for every tool call. Verified by integration test that checks the audit repository mock was called with correct parameters.

11. **Rate limiting enforced:** Verified that exceeding the configured limit returns 429 with correct `retryAfter` value.

12. **Code review completed:** PR is reviewed by at least one other engineer. All review comments are addressed. The PR description references this story (US-AI-007).

---

## 8. TASKS AND SUB-TASKS

| Task ID | Description | Owner Role | Est. Hours | Dependencies |
|---|---|---|---|---|
| T-001 | **Implement ToolExecutor service** -- Create `app/services/ai/tool_executor.py` with `_handle_list_pages`, `_handle_fetch_page`, `_compute_page_etag`, `_derive_template_type`, `_error` helper, session validation (calling AISessionRepository stub), and audit logging stub. | Backend Engineer | 6 | US-AI-006 (AISessionRepository interface) |
| T-002 | **Implement AI tools router** -- Create `app/routers/ai_tools.py` with POST `/list_pages` and `/fetch_page` endpoints. Wire up ToolExecutor via FastAPI dependency injection. Register router in `app/main.py` behind feature flag. | Backend Engineer | 4 | T-001 |
| T-003 | **Write unit tests** -- Implement at least 5 unit tests (section 6.1) using mocked repositories. Test empty course, ordered listing, full fetch, 404, and expired session. Add test fixtures for AI session mock. | Backend Engineer (SDET) | 4 | T-001, T-002 |
| T-004 | **Write integration tests** -- Implement at least 3 integration tests (section 6.2) using the in-memory SQLite test database. Test full list-then-fetch HTTP flow, cross-course rejection, and database error. | Backend Engineer (SDET) | 4 | T-002, T-003 fixtures |
| T-005 | **Write E2E tests and update docs** -- Implement 2 E2E scenarios (section 6.3). Update `TOOL_SCHEMAS_CLAUDE_NATIVE.md` with final API contracts. Run manual QA procedure (section 6.4). Update OpenAPI spec. | QA Engineer / Tech Writer | 4 | T-004 |


---