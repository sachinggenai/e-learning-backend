# US-BKND-AI-003 — Create an Isolated AI API Module

**Priority:** MUST
**Story Points:** 8
**Sprint:** 1 (Foundations)
**Depends On:** US-BKND-AI-002 (feature flags), US-AI-PR01 through US-AI-PR05 (mock auth/authz/tenant/session/user)
**Unlocks:** US-BKND-AI-004 (persistence), US-BKND-AI-005 (tool contracts), all AI route stories

---

## 1. Functional Specification

### 1.1 User Story

As a **Backend Engineer**, I want AI routes and services isolated from existing course APIs in a dedicated module structure, so that the AI feature remains an add-on layer, existing routes stay untouched, and the AI module can be enabled/disabled via feature flag without affecting manual authoring.

### 1.2 Functional Requirements

**FR-1: Dedicated AI Package Structure**
All AI code MUST live under `app/services/ai/` (services), `app/routers/ai_*.py` (routes), and `app/models/ai_*.py` or new model files (persistence). No AI logic in existing routers/services/models.

**FR-2: Separate AI Routers**
AI routes MUST be defined in dedicated router files: `ai_sessions.py`, `ai_tools.py`, `ai_chat.py`, `ai_config.py`, `ai_ingestion.py`, `ai_admin.py`. Each router MUST use prefix `/api/v1/ai/`.

**FR-3: Conditional Router Mounting**
In `app/main.py`, AI routers MUST ONLY be imported and mounted when `AI_AUTHORING_ENABLED=true`. When disabled, AI routes MUST NOT appear in OpenAPI schema and MUST return 404.

**FR-4: Structured Error Envelope**
All AI endpoints MUST return errors in a consistent format: `{"status": "error", "code": "ERROR_CODE", "message": "...", "details": {...}, "retryable": true|false}`. This matches the contract in `TOOL_SCHEMAS_CLAUDE_NATIVE.md`.

**FR-5: Existing Route Non-Regression**
No existing file in `app/routers/`, `app/services/`, `app/models/`, or `app/repositories/` MAY be structurally refactored for AI concerns. The ONLY permitted modifications are adding conditional AI router mounting in `app/main.py`.

**FR-6: AI Service Package**
Services organized as: `app/services/ai/session_service.py`, `app/services/ai/proposal_service.py`, `app/services/ai/chat_orchestrator.py`, `app/services/ai/validation_pipeline.py`, `app/services/ai/model_router.py`, `app/services/ai/ingestion_service.py`, `app/services/ai/rag_service.py`, `app/services/ai/audit_service.py`, `app/services/ai/cost_tracker.py`.

**FR-7: AI Middleware**
AI-specific middleware registered only on AI routes: session validation middleware (US-AI-PR04), rate limiting middleware, and request logging middleware.

**FR-8: Dependency Injection Chain**
All AI routes MUST use FastAPI dependency injection: `Depends(get_current_user)` → `Depends(get_current_organization)` → route handler. Session-scoped routes additionally use session middleware injection.

### 1.3 Module Structure

```
app/
  routers/
    ai_config.py          # Feature status, health
    ai_sessions.py        # Session CRUD
    ai_tools.py            # Tool-calling endpoints (list_pages, fetch_page, propose_*, apply_*, confirm_*)
    ai_chat.py             # Chat orchestration endpoint
    ai_ingestion.py        # File upload and ingestion
    ai_admin.py            # Admin audit, recovery, rollback
  services/
    ai/
      __init__.py
      config.py            # AIConfig singleton
      mock_auth.py         # PR01 - Mock auth (TODO: replace)
      mock_authorization.py # PR02 - Mock authZ (TODO: replace)
      mock_tenancy.py      # PR03 - Mock tenancy (TODO: replace)
      mock_user_org_resolver.py  # PR05 - Mock resolver (TODO: replace)
      session_service.py   # Session lifecycle
      proposal_service.py  # Proposal CRUD + lifecycle
      chat_orchestrator.py # LLM interaction loop
      validation_pipeline.py  # Schema + business + SCORM + accessibility validation
      model_router.py      # Provider routing + fallback
      ingestion_service.py # File upload + extraction
      rag_service.py       # Similar course retrieval
      audit_service.py     # Audit logging
      cost_tracker.py      # Token counting + budget enforcement
  models/
    user_context.py        # PR01 - UserContext
    authorization.py       # PR02 - AuthorizationDecision
    tenant.py              # PR03 - OrganizationContext
    session_context.py     # PR04 - SessionContext
  middleware/
    session_middleware.py  # PR04 - Session auth middleware
  dependencies/
    __init__.py
    auth_dependencies.py   # get_current_user, require_admin exports
```

---

## 2. Technical Specification

### 2.1 Router Registration in `app/main.py`

```python
# In app/main.py — conditional AI router mounting

from app.services.ai.config import get_ai_config, load_ai_config

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing startup code ...
    
    # Initialize AI configuration
    load_ai_config()
    config = get_ai_config()
    if config.ai_authoring_enabled:
        logger.info("AI authoring ENABLED — mounting AI routers")
    else:
        logger.info("AI authoring DISABLED — skipping AI router mount")
    yield

# ... after existing router includes ...

ai_config = get_ai_config()
if ai_config.ai_authoring_enabled:
    # TODO(AUTH): These imports will be updated when mock services are replaced.
    from app.routers import ai_config as ai_config_router
    from app.routers import ai_sessions
    from app.routers import ai_tools
    from app.routers import ai_chat
    
    api_router.include_router(ai_config_router.router)
    api_router.include_router(ai_sessions.router)
    api_router.include_router(ai_tools.router)
    api_router.include_router(ai_chat.router)
    logger.info("AI routers mounted: sessions, tools, chat, config")
```

### 2.2 Common AI Router Pattern

Every AI route file MUST follow this pattern:

```python
"""
AI [Resource] Router

TODO(AUTH): All routes depend on mock auth (US-AI-PR01). When real auth
is implemented, the Depends(get_current_user) import path won't change.
"""

from fastapi import APIRouter, Depends, HTTPException
from app.dependencies.auth_dependencies import get_current_user
from app.models.user_context import UserContext

router = APIRouter(prefix="/api/v1/ai", tags=["AI - [Resource]"])

# Common error response helper
def ai_error(code: str, message: str, status: int = 400, retryable: bool = False, **details):
    return JSONResponse(
        status_code=status,
        content={
            "status": "error",
            "code": code,
            "message": message,
            "details": details,
            "retryable": retryable,
        }
    )

@router.post("/[resource]")
async def create_resource(
    user: UserContext = Depends(get_current_user),
    # ... request body ...
):
    """Create an AI [resource]."""
    # All routes get user context via Depends
    pass
```

### 2.3 Error Code Catalog

All AI routes use these standardized error codes:

| Code | HTTP Status | Retryable | Description |
|---|---|---|---|
| `AI_NOT_CONFIGURED` | 503 | false | AI feature enabled but not configured |
| `SESSION_EXPIRED` | 440 | false | Session token has expired |
| `SESSION_INVALID` | 401 | false | Session token not found or malformed |
| `PERMISSION_DENIED` | 403 | false | User lacks access to requested resource |
| `CROSS_TENANT_DENIED` | 403 | false | Resource belongs to different organization |
| `VALIDATION_ERROR` | 422 | true | Schema or business rule validation failed |
| `PROPOSAL_EXPIRED` | 409 | false | Proposal TTL has elapsed |
| `PROPOSAL_ALREADY_APPLIED` | 409 | false | Proposal has already been applied |
| `STALE_DATA` | 409 | true | Base hash mismatch — re-fetch and retry |
| `CONFIRMATION_REQUIRED` | 400 | false | Destructive operation needs explicit confirmation |
| `RATE_LIMIT_EXCEEDED` | 429 | true | Too many requests; retry after N seconds |
| `TOKEN_BUDGET_EXCEEDED` | 429 | false | Request exceeds token budget |
| `MODEL_UNAVAILABLE` | 503 | true | AI model provider unavailable |
| `NOT_FOUND` | 404 | false | Requested resource not found |
| `INTERNAL_ERROR` | 500 | false | Unexpected server error |

---

## 3. Non-Functional Requirements

### 3.1 Performance
- AI route overhead (auth check + session validation): < 5ms p95
- Conditional router mounting: zero overhead when AI disabled (routers never imported)

### 3.2 Security
- AI routes MUST inherit CORS settings from `app/main.py`
- AI routes MUST NOT be accessible when `AI_AUTHORING_ENABLED=false`
- Error responses MUST NOT leak internal paths, table names, or configuration

### 3.3 Reliability
- Import errors in AI routers MUST NOT prevent app startup (catch and log, degrade AI status)
- All AI dependencies MUST be optional at import time

---

## 4. Current State Assessment

### 4.1 What Exists
- `app/main.py` — router registration pattern with 15 existing routers
- `app/routers/` — 15 router files, none AI-specific
- `app/services/` — existing services (scorm_export, import_service, etc.), no `ai/` subdirectory
- `app/models/` — existing models, no AI-specific models
- `app/utils/feature_flags.py` — existing feature flag system (can gate AI)

### 4.2 What Must Be Built (Net-New)
- `app/services/ai/` package with `__init__.py`
- `app/routers/ai_config.py`, `ai_sessions.py`, `ai_tools.py`, `ai_chat.py` (stub versions)
- `app/dependencies/` package with `auth_dependencies.py`
- `app/middleware/session_middleware.py`

### 4.3 What Must Be Modified
- `app/main.py` — Add conditional AI router mounting (detailed in Section 2.1)
- No other existing files modified

---

## 5. Expansion Points

### 5.1 Technical Expansion
1. **API versioning**: Add `/api/v2/ai/` when breaking changes needed
2. **Router auto-discovery**: Scan `app/routers/ai_*.py` and auto-mount instead of explicit imports
3. **GraphQL endpoint**: Add AI operations via GraphQL alongside REST

### 5.2 Functional Expansion
1. **Webhook router**: Add `ai_webhooks.py` for async operation callbacks
2. **Admin dashboard API**: Add `ai_admin.py` for operational metrics
3. **SDK generation**: Auto-generate TypeScript client from OpenAPI schema

---

## 6. Validation & Testing

### 6.1 Unit Tests
- TC-003-01: `AI_AUTHORING_ENABLED=false` → AI routers not imported, no AI routes in OpenAPI schema
- TC-003-02: `AI_AUTHORING_ENABLED=true` → AI routers mounted, AI routes appear in OpenAPI schema
- TC-003-03: Existing routes (`GET /api/v1/courses`) work identically regardless of AI flag
- TC-003-04: AI route error responses use standardized error envelope format
- TC-003-05: Invalid AI route returns 404 with structured error when AI enabled
- TC-003-06: Mock auth dependency injection works on AI route (user context received)

### 6.2 Integration Tests
- TC-003-I1: Full AI route lifecycle: POST /ai/sessions → GET /ai/sessions/{id} → DELETE /ai/sessions/{id}
- TC-003-I2: AI route returns 401 when no auth headers (session middleware)
- TC-003-I3: Cross-AI-route call: session created in ai_sessions is accessible from ai_tools

### 6.3 E2E Tests
- TC-003-E1: Frontend calls feature-status → AI button renders → click → session created
- TC-003-E2: Toggle AI flag off → frontend hides AI button → direct API call returns 404

---

## 7. Definition of Done

- [ ] `app/services/ai/__init__.py` created
- [ ] `app/routers/ai_config.py` implemented with feature-status endpoint
- [ ] `app/routers/ai_sessions.py` created (stub with POST/GET/DELETE)
- [ ] `app/routers/ai_tools.py` created (stub)
- [ ] `app/routers/ai_chat.py` created (stub)
- [ ] `app/dependencies/auth_dependencies.py` created
- [ ] `app/main.py` conditionally mounts AI routers based on feature flag
- [ ] Standardized error envelope used across all AI routes
- [ ] All existing tests pass (zero regression) with flag both on and off
- [ ] OpenAPI schema shows AI routes only when flag enabled
- [ ] Manual QA: toggle flag, verify AI routes appear/disappear from /docs
- [ ] Code reviewed with sign-off on module structure
- [ ] README or CLAUDE.md updated with AI module layout

---

## 8. Tasks & Sub-Tasks

| Task ID | Description | Owner | Est. | Depends On |
|---|---|---|---|---|
| T1 | Create `app/services/ai/__init__.py` | Backend | 0.25h | — |
| T2 | Create `app/dependencies/__init__.py` and `auth_dependencies.py` re-exporting mock auth | Backend | 0.5h | US-AI-PR01 |
| T3 | Create `app/routers/ai_config.py` with feature-status endpoint | Backend | 1h | US-BKND-AI-002 |
| T4 | Create `app/routers/ai_sessions.py` stub with POST/GET/DELETE | Backend | 2h | T2, US-AI-PR04 |
| T5 | Create `app/routers/ai_tools.py` stub | Backend | 1.5h | T2 |
| T6 | Create `app/routers/ai_chat.py` stub | Backend | 1h | T2 |
| T7 | Modify `app/main.py` for conditional AI router mounting | Backend | 2h | T2-T6, US-BKND-AI-002 |
| T8 | Implement standardized error envelope helper | Backend | 1h | T3 |
| T9 | Write 6 unit tests for router mounting and error format | Backend | 2h | T7, T8 |
| T10 | Write 3 integration tests for AI route lifecycle | Backend | 1.5h | T4, T5 |
| T11 | Verify zero regression: run full test suite with flag on and off | Backend | 1h | T7 |
| T12 | Update OpenAPI schema verification | Backend | 0.5h | T7 |
| T13 | Code review and module structure sign-off | Lead | 1h | T9, T10 |
