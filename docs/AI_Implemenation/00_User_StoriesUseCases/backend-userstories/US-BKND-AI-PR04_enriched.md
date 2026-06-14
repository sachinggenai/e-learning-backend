# US-BKND-AI-PR04 — Mock Session Authentication Middleware

**Priority:** MUST (PRE-REQUISITE)
**Story Points:** 3
**Sprint:** 0 (Foundation)
**Depends On:** US-BKND-AI-PR01, US-BKND-AI-PR02, US-BKND-AI-PR03
**Unlocks:** US-AI-006 (AI session creation), US-AI-023 (chat endpoint), all tool-calling stories

---

## 1. Functional Specification

### 1.1 User Story

As a **Backend Engineer building AI features**, I want a mock session authentication middleware that validates the `Authorization: Session {sessionId}` header format and attaches session context to requests, so that AI tool endpoints can enforce session scoping without waiting for a real distributed session store.

### 1.2 Functional Requirements

**FR-1: Session Header Parsing**
The middleware MUST extract `session_id` from `Authorization: Session {sessionId}` headers. Requests without this header on AI routes MUST receive 401.

**FR-2: Session Validation**
Given a `session_id`, the middleware MUST look up the session in an in-memory mock session store and validate it is not expired. Expired sessions receive 440 Session Expired.

**FR-3: Session Context Attachment**
Valid sessions MUST attach a `SessionContext` to `request.state.session` for downstream route handlers.

**FR-4: Course Scope Enforcement**
`validate_session_course_scope(session_id, course_id)` MUST verify the session is scoped to the given course. Cross-course access receives 403.

**FR-5: Mock Session Store**
In-memory dictionary of mock sessions. Sessions expire after `AI_SESSION_TTL_HOURS` (default 24h). `# TODO(SESSION):` markers for Redis-backed store.

**FR-6: Selective Middleware Application**
The middleware MUST only validate sessions on AI routes (`/api/v1/ai/*`). Existing routes (`/api/v1/courses`, etc.) MUST NOT be affected.

---

## 2. Technical Specification

### 2.1 `app/middleware/session_middleware.py`

```python
"""
Session Authentication Middleware

TODO(SESSION): Replace in-memory mock session store with:
1. Redis-backed session store with TTL and auto-expiry
2. Session persistence across server restarts
3. Distributed session validation (multiple API servers)
4. Session activity tracking and idle timeout
5. Session revocation on logout or security events
"""

import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel

class SessionContext(BaseModel):
    """AI authoring session context.

    TODO(SESSION): Add created_at, last_accessed_at, ip_address, user_agent
    for real session management.
    """
    session_id: str
    user_id: str
    organization_id: str
    course_id: str          # Immutable: cannot change course within a session
    created_at: datetime
    expires_at: datetime

    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at

# TODO(SESSION): Replace with Redis client
_MOCK_SESSION_STORE: Dict[str, SessionContext] = {}

def create_mock_session(user_id: str, org_id: str, course_id: str, ttl_hours: int = 24) -> SessionContext:
    """Create a new session in the mock store.

    TODO(SESSION): Persist to Redis with TTL. Generate cryptographically
    secure session tokens.
    """
    session = SessionContext(
        session_id=str(uuid.uuid4()),
        user_id=user_id,
        organization_id=org_id,
        course_id=course_id,
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(hours=ttl_hours),
    )
    _MOCK_SESSION_STORE[session.session_id] = session
    return session

def get_mock_session(session_id: str) -> Optional[SessionContext]:
    """Retrieve and validate a session from the mock store.

    TODO(SESSION): Query Redis with TTL check.
    """
    session = _MOCK_SESSION_STORE.get(session_id)
    if session and session.is_expired():
        del _MOCK_SESSION_STORE[session_id]
        return None
    return session

def validate_session_course_scope(session_id: str, course_id: str) -> bool:
    """Verify session is scoped to the given course.

    TODO(SESSION): Add real course ownership validation against DB.
    """
    session = get_mock_session(session_id)
    return session is not None and session.course_id == course_id
```

---

## 6. Validation & Testing

- TC-PR04-01: Request to `/api/v1/ai/sessions` without `Authorization` header returns 401
- TC-PR04-02: Request with valid `Authorization: Session {id}` header passes middleware
- TC-PR04-03: Expired session returns 440 with "Session expired" body
- TC-PR04-04: Session scoped to course-A cannot access course-B (403)
- TC-PR04-05: Existing routes (`/api/v1/courses`) are NOT affected by session middleware
- TC-PR04-06: `create_mock_session()` returns session with 24h expiry

---

## 7. Definition of Done

- [ ] `SessionContext` model defined
- [ ] Session middleware implemented with header parsing and validation
- [ ] In-memory mock session store with expiry working
- [ ] `validate_session_course_scope()` working
- [ ] Middleware only applied to `/api/v1/ai/*` routes
- [ ] All functions have `# TODO(SESSION):` comments
- [ ] Unit tests pass (6 scenarios)
- [ ] Integration test: AI route with valid session, expired session, wrong course
- [ ] Existing route regression: all pre-AI routes still work
- [ ] Code reviewed

---

## 8. Tasks

| Task ID | Description | Owner | Est. | Depends On |
|---|---|---|---|---|
| PR04-T1 | Create `app/models/session_context.py` with `SessionContext` model | Backend | 0.5h | — |
| PR04-T2 | Create `app/middleware/session_middleware.py` with middleware and mock store | Backend | 2h | PR04-T1 |
| PR04-T3 | Register middleware in `app/main.py` for `/api/v1/ai/*` routes only | Backend | 1h | PR04-T2 |
| PR04-T4 | Write 6 unit tests for session lifecycle and scope enforcement | Backend | 1.5h | PR04-T3 |
| PR04-T5 | Run full existing test suite to verify zero regression on non-AI routes | Backend | 1h | PR04-T3 |
| PR04-T6 | Code review with explicit sign-off on TODO(SESSION) markers | Lead | 0.5h | PR04-T4 |

---

---