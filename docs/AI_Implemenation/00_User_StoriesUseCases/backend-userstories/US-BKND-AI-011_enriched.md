## US-BKND-AI-011: Propose and Apply AI-Created Pages

**Title:** Propose and Apply AI-Created Pages  
**Flow:** 3. Create Page Proposal and Apply Flow  
**Priority:** MUST  
**Depends on:** US-BKND-AI-010 (Generic proposal lifecycle, apply safety, audit, outbox)  
**Dependencies:** US-BKND-AI-006 (AI session creation), US-BKND-AI-007 (List and fetch pages for AI context), US-BKND-AI-008 (Validation pipeline)

---

### 1. FUNCTIONAL SPECIFICATION

#### 1.1 Overview

As an Author, I want the AI agent to propose a new course page using only approved templates and then apply it only after I explicitly approve, so that I can quickly build course content with full control over what gets created.

#### 1.2 Actors and Roles

| Actor | Role |
|---|---|
| Author (User) | Initiates AI session, approves/rejects proposals |
| AI Agent (Claude) | Calls tool endpoints via chat orchestrator |
| Backend System | Validates, persists proposals, applies on confirmation |
| Frontend UI | Renders proposal preview, confirmation controls |

#### 1.3 Functional Requirements

**FR1: Propose Create Page (AI -> Backend)**
- The AI agent calls `propose_create_page(session_id, title, template_type, data, insert_at_index)`.
- The backend validates session is active and course scoping is correct.
- The backend validates the template_type is in the allowed-templates whitelist.
- The backend validates `data` against the template type's JSON schema.
- The backend runs business-rule validation (required fields, field constraints).
- On success: returns `proposal_id`, `preview_page` (simulated page data), `validation_status`, and `validation_messages`.
- On failure: returns structured error(s) with field paths and retryable flags.
- **No mutation occurs at proposal time.** The proposal record stores `before_snapshot` (null for creates), `after_candidate` (full page payload), `base_hash`, `validation_result`, and `expires_at`.

**FR2: Preview Proposal (Frontend)**
- Proposal preview renders the page title, template_type, data payload, and order.
- Validation messages appear per-field with severity color coding (red=error, yellow=warning, gray=info).
- Blocking errors disable the "Apply" button.
- The preview is generated without an additional LLM call -- it uses the `after_candidate` stored in the proposal.

**FR3: Apply Page Proposal (Frontend -> Backend)**
- Author clicks "Apply" in the proposal review UI.
- Frontend calls `apply_page_proposal(session_id, proposal_id, user_confirmed=true)`.
- Backend re-validates: proposal exists, is not expired, belongs to session course, `user_confirmed=true`.
- Backend re-checks that the `base_hash` matches current course state (no concurrent edits).
- Backend creates a `PageRecord` in the `pages` table with the candidate data.
- Backend creates `ComponentRecord` entries for each component in the page data.
- Backend writes the `ai_audit_log` entry with operation type `PageCreatedByAI`, before/after snapshots, proposal ID, session ID, and model metadata.
- Backend writes an `outbox_event` with event_type `PageCreatedByAI`.
- Returns the created `page_id`, `status: "created"`, and refreshed course state.

**FR4: Idempotent Apply**
- Calling `apply_page_proposal` with the same `proposal_id` and `user_confirmed=true` a second time returns the same `page_id` with `status: "created"` -- no duplicate page is created.
- The server checks a `applied_at` timestamp on the proposal record; if non-null, returns success with the original result.

**FR5: Graceful Failures**
- Expired proposals (TTL exceeded): returns `status: "rejected"` with message "Proposal has expired. Please create a new proposal."
- Stale proposals (base_hash mismatch): returns `status: "error"` with code `CONFLICT` and message "Course has been modified since proposal was created. Please re-fetch and propose again."
- Validation failure on re-check: returns `status: "error"` with `validation_messages`.

**FR6: Rejection**
- Author clicks "Reject" or closes the proposal.
- Proposal status transitions to `REJECTED`.
- No page is created.
- Frontend notifies the AI agent of rejection for retry or refinement.

#### 1.4 User Flow (Happy Path)

```
1. Author opens AI chat panel on course editor.
2. Author types: "Add a tabs page comparing Python and JavaScript."
3. AI Agent calls list_pages() to get current course state.
4. AI Agent calls propose_create_page({
       session_id: "abc-123",
       title: "Python vs JavaScript",
       template_type: "tabs",
       data: { tabs: [ ... ] },
       insert_at_index: 2
   })
5. Backend validates: session active, tabs type allowed, data conforms to schema, min 2 tabs satisfied.
6. Backend returns proposal_id: "prop-456", validation_status: "valid", preview_page, validation_messages.
7. AI Agent presents proposal to Author: "Here's a tabs page comparing Python and JavaScript. The tabs cover syntax, typing, and ecosystem."
8. Author reviews preview. Clicks "Apply".
9. Frontend calls apply_page_proposal({ proposal_id: "prop-456", user_confirmed: true }).
10. Backend creates PageRecord + ComponentRecords. Writes audit log + outbox event.
11. Return page_id, status: "created".
12. Frontend adds the new page to the course editor. Author sees it in the page list.
13. AI Agent confirms: "The page has been added. You can now edit it further or continue building."
```

#### 1.5 Template Type Allowlist (MVP)

Only these component types are allowed in `propose_create_page` during MVP:

| Template Type | Category | Min Constraints | Max Constraints |
|---|---|---|---|
| `text-content` (content-text) | presentation | content >= 10 chars | title <= 200 chars |
| `tabs` | navigation | 2 tabs | 6 tabs |
| `accordion` | navigation | 2 panels | 20 panels |
| `click-reveal` | presentation | 2 items | 10 items |
| `final-assessment` | assessment | 3 questions | 50 questions, passingScore 0-100 |

The allowlist is enforced server-side in `app/services/ai/template_allowlist.py`. Expandable via configuration for future template types.

---

### 2. TECHNICAL SPECIFICATION

#### 2.1 New Files

```
app/
  ai/
    __init__.py
    proposal_service.py          # Core proposal lifecycle (create, validate, apply)
    template_allowlist.py         # MVP template whitelist + schema validation
    proposal_validator.py         # Business-rule validation for proposals
  routers/
    ai_tools.py                   # AI tool endpoints (propose_create_page, apply_page_proposal, etc.)
  models/
    ai_proposal.py                # SQLAlchemy ORM model for ai_proposals table
    ai_session.py                 # AI session ORM model
    ai_audit_log.py               # AI audit log ORM model
```

#### 2.2 Database DDL (Alembic Migration)

**ai_sessions table** (US-BKND-AI-004 provides this, listed here for completeness):

```sql
CREATE TABLE ai_sessions (
    id              SERIAL PRIMARY KEY,
    session_id      VARCHAR(64) UNIQUE NOT NULL,
    user_id         VARCHAR(64) NOT NULL,
    course_id       VARCHAR(64) NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    organization_id VARCHAR(64) NOT NULL,
    status          VARCHAR(32) NOT NULL DEFAULT 'active',  -- active, expired, terminated
    expires_at      TIMESTAMP NOT NULL,
    session_metadata JSONB DEFAULT '{}',
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_ai_sessions_course ON ai_sessions(course_id);
CREATE INDEX idx_ai_sessions_user ON ai_sessions(user_id);
CREATE INDEX idx_ai_sessions_status ON ai_sessions(status);
```

**ai_proposals table** (NEW for US-BKND-AI-011):

```sql
CREATE TABLE ai_proposals (
    id                SERIAL PRIMARY KEY,
    proposal_id       VARCHAR(64) UNIQUE NOT NULL,
    session_id        VARCHAR(64) NOT NULL REFERENCES ai_sessions(session_id) ON DELETE CASCADE,
    operation         VARCHAR(32) NOT NULL,  -- 'create_page', 'update_page', 'delete_page'
    status            VARCHAR(32) NOT NULL DEFAULT 'pending',  -- pending, approved, applying, applied, rejected, expired, failed
    template_type     VARCHAR(100),
    title             VARCHAR(200),
    base_hash         VARCHAR(64),             -- SHA256 of course state at proposal time (null for creates)
    before_snapshot   JSONB,                   -- null for create_page proposals
    after_candidate   JSONB NOT NULL,          -- full page payload
    insert_at_index   INTEGER,
    validation_result JSONB,                   -- { status, errors[], warnings[] }
    validation_errors JSONB DEFAULT '[]',
    validation_warnings JSONB DEFAULT '[]',
    confirmation_token VARCHAR(64),            -- generated at proposal time, validated at apply
    applied_at        TIMESTAMP,               -- null until applied; non-null means idempotent-done
    expires_at        TIMESTAMP NOT NULL,      -- default NOW() + 30 minutes
    tool_schema_version VARCHAR(32),
    model_id          VARCHAR(100),
    provenance        JSONB DEFAULT '{}',      -- { prompt_version, model_id, provider, source_doc_hash, rag_chunk_ids }
    created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_ai_proposals_session ON ai_proposals(session_id);
CREATE INDEX idx_ai_proposals_status ON ai_proposals(status);
CREATE INDEX idx_ai_proposals_expires ON ai_proposals(expires_at);
```

**ai_audit_logs table** (US-BKND-AI-010 provides this):

```sql
CREATE TABLE ai_audit_logs (
    id                SERIAL PRIMARY KEY,
    event_id          VARCHAR(64) UNIQUE NOT NULL,
    session_id        VARCHAR(64) NOT NULL,
    proposal_id       VARCHAR(64),
    operation         VARCHAR(64) NOT NULL,    -- 'PageCreatedByAI', 'PageUpdatedByAI', 'PageDeletedByAI'
    user_id           VARCHAR(64) NOT NULL,
    course_id         VARCHAR(64) NOT NULL,
    page_id           VARCHAR(64),
    before_snapshot   JSONB,
    after_snapshot    JSONB,
    metadata          JSONB DEFAULT '{}',      -- model_id, prompt_version, tool_schema_version, trace_id
    created_at        TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_ai_audit_session ON ai_audit_logs(session_id);
CREATE INDEX idx_ai_audit_course ON ai_audit_logs(course_id);
CREATE INDEX idx_ai_audit_operation ON ai_audit_logs(operation);
```

**outbox_events table** (US-BKND-AI-010 provides this):

```sql
CREATE TABLE outbox_events (
    id                SERIAL PRIMARY KEY,
    event_type        VARCHAR(64) NOT NULL,    -- 'PageCreatedByAI'
    event_version     VARCHAR(16) NOT NULL DEFAULT '1.0',
    aggregate_id      VARCHAR(64) NOT NULL,    -- page_id
    payload           JSONB NOT NULL,
    trace_id          VARCHAR(64),
    occurred_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    published_at      TIMESTAMP
);
CREATE INDEX idx_outbox_published ON outbox_events(published_at) WHERE published_at IS NULL;
```

#### 2.3 ORM Models

**app/models/ai_session.py (new):**

```python
"""AI Session ORM model."""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, DateTime, JSON, Integer, ForeignKey
from app.models.base import Base

class AiSessionRecord(Base):
    __tablename__ = "ai_sessions"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    course_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("courses.course_id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="active")
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    session_metadata: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

**app/models/ai_proposal.py (new):**

```python
"""AI Proposal ORM model."""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, DateTime, JSON, Integer, Boolean

from app.models.base import Base

class AiProposalRecord(Base):
    __tablename__ = "ai_proposals"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    proposal_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    operation: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    template_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    base_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    before_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    after_candidate: Mapped[dict] = mapped_column(JSON, nullable=False)
    insert_at_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    validation_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    validation_errors: Mapped[list] = mapped_column(JSON, default=list)
    validation_warnings: Mapped[list] = mapped_column(JSON, default=list)
    confirmation_token: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    tool_schema_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    model_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

#### 2.4 API Contracts

**POST /api/v1/ai/tools/propose_create_page**

Request:
```json
{
  "session_id": "uuid-string",
  "title": "string (max 200 chars)",
  "template_type": "string (one of: content-text, tabs, accordion, click-reveal, final-assessment)",
  "data": {
    "content": "string (markdown, for content-text)",
    "tabs": [{"id": "string", "label": "string", "content": "string"}]  // or accordion/final-assessment shape
  },
  "insert_at_index": "integer (optional, default append)"
}
```

Response 200 (success):
```json
{
  "proposal_id": "uuid-string",
  "preview_page": {
    "pageId": "uuid-string (pre-generated, not yet persisted)",
    "title": "string",
    "templateType": "string",
    "data": {},
    "order": 2
  },
  "validation_status": "valid | warning | error",
  "validation_messages": [
    {
      "severity": "error | warning | info",
      "field": "data.questions",
      "message": "Assessment must have at least 3 questions"
    }
  ]
}
```

Response 422 (validation error):
```json
{
  "detail": "Validation failed",
  "errors": [
    {"code": "UNSUPPORTED_TEMPLATE", "field": "template_type", "message": "Template type 'video-slide' is not in the allowed list for AI generation"},
    {"code": "SCHEMA_ERROR", "field": "data.tabs", "message": "Tabs requires at least 2 items"}
  ]
}
```

**POST /api/v1/ai/tools/apply_page_proposal**

Request:
```json
{
  "session_id": "uuid-string",
  "proposal_id": "uuid-string (from propose_create_page)",
  "user_confirmed": true
}
```

Response 200 (success):
```json
{
  "page_id": "uuid-string (the created page's pageId)",
  "page": {
    "pageId": "uuid-string",
    "title": "string",
    "order": 2,
    "components": [
      {
        "componentId": "uuid-string",
        "componentType": "tabs",
        "order": 0,
        "data": {}
      }
    ]
  },
  "status": "created",
  "message": "Page created successfully"
}
```

Response 409 (stale/conflict):
```json
{
  "code": "CONFLICT",
  "message": "Course has been modified since this proposal was created",
  "retryable": true
}
```

Error response schema (all tools):
```json
{
  "status": "error",
  "code": "VALIDATION_ERROR | PERMISSION_DENIED | NOT_FOUND | TIMEOUT | RATE_LIMIT | SERVER_ERROR",
  "message": "Human-readable error message",
  "details": {},
  "retryable": true | false
}
```

#### 2.5 Service Signatures

**app/ai/proposal_service.py:**

```python
from __future__ import annotations
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
import hashlib
import json
import uuid
from datetime import datetime, timedelta

class ProposalService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def propose_create_page(
        self,
        session_id: str,
        title: str,
        template_type: str,
        data: dict,
        insert_at_index: Optional[int] = None,
        provenance: Optional[dict] = None,
    ) -> dict:
        """
        1. Validate session is active and belongs to a course.
        2. Validate template_type is in allowlist (TemplateAllowlist.is_allowed).
        3. Validate data against template JSON schema (TemplateAllowlist.validate_schema).
        4. Run business-rule validation (ProposalValidator.validate_create).
        5. Compute base_hash of current course state (for creates, hash of pages list).
        6. Build after_candidate (full page payload with generated pageId and components).
        7. Persist AiProposalRecord with status='pending', expires_at=now+30min.
        8. Return proposal_id, preview_page, validation_status, validation_messages.
        """
        pass

    async def apply_page_proposal(
        self,
        session_id: str,
        proposal_id: str,
        user_confirmed: bool,
    ) -> dict:
        """
        1. Fetch proposal by proposal_id, verify session_id matches.
        2. Verify status == 'pending' or 'approved', applied_at is null.
        3. Verify expires_at > now. If expired, set status='expired', return error.
        4. Verify user_confirmed == True.
        5. If operation == 'create_page':
           a. Re-check base_hash against current course state.
           b. Create PageRecord with after_candidate data.
           c. Create ComponentRecord entries from components list.
           d. Update proposal: status='applied', applied_at=now.
        6. Write ai_audit_log entry (operation='PageCreatedByAI').
        7. Write outbox_event entry.
        8. Return page_id, status='created'.
        """
        pass

    async def reject_proposal(
        self,
        proposal_id: str,
    ) -> dict:
        """
        1. Set status='rejected'.
        2. Return success.
        """
        pass

    @staticmethod
    def compute_base_hash(pages: list[dict]) -> str:
        """SHA256 of sorted page list JSON for staleness detection."""
        raw = json.dumps(pages, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()
```

**app/ai/template_allowlist.py:**

```python
"""MVP template allowlist for AI page creation."""

from typing import Optional

# Map of allowed template_type -> (display_name, category, schema_validator_key)
MVP_ALLOWLIST = {
    "content-text": {"display_name": "Text Content", "category": "presentation", "min_items": None, "item_label": None},
    "tabs":         {"display_name": "Tabbed Content", "category": "navigation", "min_items": 2, "item_label": "tabs"},
    "accordion":    {"display_name": "Accordion", "category": "navigation", "min_items": 2, "item_label": "panels"},
    "click-reveal": {"display_name": "Click and Reveal", "category": "presentation", "min_items": 2, "item_label": "items"},
    "final-assessment": {"display_name": "Final Assessment", "category": "assessment", "min_items": 3, "item_label": "questions"},
}

class TemplateAllowlist:
    @staticmethod
    def is_allowed(template_type: str) -> bool:
        return template_type in MVP_ALLOWLIST

    @staticmethod
    def get_allowed_types() -> list[str]:
        return list(MVP_ALLOWLIST.keys())

    @staticmethod
    def validate_schema(template_type: str, data: dict) -> list[dict]:
        """Validate data against component registry schema or built-in rules.
        Returns list of {field, message, severity} dicts.
        """
        errors = []
        if template_type not in MVP_ALLOWLIST:
            errors.append({"field": "template_type", "message": f"Template type '{template_type}' is not allowed", "severity": "error"})
            return errors

        info = MVP_ALLOWLIST[template_type]
        if info["item_label"] and info["min_items"]:
            items = data.get(info["item_label"], [])
            if not isinstance(items, list) or len(items) < info["min_items"]:
                errors.append({
                    "field": f"data.{info['item_label']}",
                    "message": f"{info['display_name']} requires at least {info['min_items']} {info['item_label']}",
                    "severity": "error",
                })

        if template_type == "final-assessment":
            questions = data.get("questions", [])
            for q in questions:
                if q.get("type") in ("mcq", "multiple-select") and not q.get("options"):
                    errors.append({
                        "field": f"data.questions[].options",
                        "message": f"MCQ questions require options",
                        "severity": "error",
                    })
            passing = data.get("passingScore", 80)
            if not (0 <= passing <= 100):
                errors.append({"field": "data.passingScore", "message": "passingScore must be 0-100", "severity": "error"})

        if template_type == "content-text":
            content = data.get("content", "")
            if not content or len(content.strip()) < 10:
                errors.append({"field": "data.content", "message": "Content must be at least 10 characters", "severity": "error"})

        return errors
```

**app/ai/proposal_validator.py:**

```python
"""Business-rule validator for AI proposals. Calls existing validation infrastructure."""
from app.repositories.course_repo import CourseRepository
from app.models.course import Course
from app.services.renderer_manifest import get_renderer_manifest

class ProposalValidator:
    def __init__(self, session):
        self.session = session

    async def validate_create(self, course_id: str, template_type: str, data: dict) -> dict:
        """Run validation across schema, business rules, and export readiness.
        Returns: { status: 'valid'|'warning'|'error', errors: [], warnings: [] }
        """
        errors = []
        warnings = []

        # 1. Schema validation via TemplateAllowlist
        schema_errors = TemplateAllowlist.validate_schema(template_type, data)
        for e in schema_errors:
            (errors if e["severity"] == "error" else warnings).append(e)

        # 2. Export-readiness via RendererManifest
        manifest = get_renderer_manifest()
        if not manifest.is_supported(template_type):
            warnings.append({
                "field": "template_type",
                "message": f"Template '{template_type}' may not be fully exportable in SCORM",
                "severity": "warning",
            })

        # 3. Business rules
        if template_type == "tabs":
            tabs = data.get("tabs", [])
            if len(tabs) > 6:
                errors.append({"field": "data.tabs", "message": "Maximum 6 tabs allowed", "severity": "error"})
            labels = [t.get("label", "") for t in tabs]
            if len(labels) != len(set(labels)):
                errors.append({"field": "data.tabs", "message": "Tab labels must be unique", "severity": "error"})

        if template_type == "final-assessment":
            questions = data.get("questions", [])
            if len(questions) > 50:
                errors.append({"field": "data.questions", "message": "Maximum 50 questions allowed", "severity": "error"})

        if template_type == "accordion":
            panels = data.get("panels", [])
            if len(panels) > 20:
                errors.append({"field": "data.panels", "message": "Maximum 20 accordion panels allowed", "severity": "error"})
            ids = [p.get("id", "") for p in panels]
            if len(ids) != len(set(ids)):
                errors.append({"field": "data.panels", "message": "Panel IDs must be unique", "severity": "error"})

        status = "valid"
        if errors:
            status = "error"
        elif warnings:
            status = "warning"

        return {"status": status, "errors": errors, "warnings": warnings}
```

#### 2.6 Router Implementation

**app/routers/ai_tools.py (new):**

```python
"""AI Tool endpoints for propose/apply lifecycle."""
from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.ai.proposal_service import ProposalService
from app.ai.template_allowlist import TemplateAllowlist
from app.repositories.course_repo import CourseRepository, CourseNotFoundError

router = APIRouter(prefix="/api/v1/ai/tools", tags=["AI Tools"])

# ── DTOs ──────────────────────────────────────

class ProposeCreatePageRequest(BaseModel):
    session_id: str = Field(..., description="Active AI session ID")
    title: str = Field(..., max_length=200, description="Page title")
    template_type: str = Field(..., description="Template type (must be in allowlist)")
    data: dict = Field(default_factory=dict, description="Template-specific data")
    insert_at_index: Optional[int] = Field(None, ge=0, description="0-based position")

class ApplyPageProposalRequest(BaseModel):
    session_id: str
    proposal_id: str
    user_confirmed: bool = Field(..., description="Must be true to apply")

# ── Endpoints ─────────────────────────────────

@router.post("/propose_create_page")
async def propose_create_page(
    body: ProposeCreatePageRequest,
    session: AsyncSession = Depends(get_session),
    authorization: Optional[str] = Header(None),
) -> dict:
    """AI tool: Propose a new page (no mutation)."""
    # 1. Validate session (via session_service -- simplified here)
    #    TODO: integrate with AiSessionRepository once US-BKND-AI-006 is complete.

    # 2. Validate template is allowed
    if not TemplateAllowlist.is_allowed(body.template_type):
        from app.utils.error_envelope import api_http_exception
        raise api_http_exception(
            422, "UNSUPPORTED_TEMPLATE",
            f"Template type '{body.template_type}' is not in the allowed list",
            field="template_type",
        )

    # 3. Validate data schema
    schema_errors = TemplateAllowlist.validate_schema(body.template_type, body.data)
    if any(e["severity"] == "error" for e in schema_errors):
        from app.utils.error_responses import validation_error
        return validation_error(
            "Schema validation failed",
            [{"field": e["field"], "message": e["message"]} for e in schema_errors],
        )

    # 4. Delegate to ProposalService
    service = ProposalService(session)
    result = await service.propose_create_page(
        session_id=body.session_id,
        title=body.title,
        template_type=body.template_type,
        data=body.data,
        insert_at_index=body.insert_at_index,
    )
    return result


@router.post("/apply_page_proposal")
async def apply_page_proposal(
    body: ApplyPageProposalRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """AI tool: Apply a previously-proposed page creation."""
    if not body.user_confirmed:
        from app.utils.error_envelope import api_http_exception
        raise api_http_exception(400, "USER_CONFIRMATION_REQUIRED", "user_confirmed must be true to apply")

    service = ProposalService(session)
    result = await service.apply_page_proposal(
        session_id=body.session_id,
        proposal_id=body.proposal_id,
        user_confirmed=body.user_confirmed,
    )
    return result


@router.get("/proposals/{proposal_id}")
async def get_proposal(
    proposal_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Fetch proposal details for preview rendering."""
    # TODO: fetch from AiProposalRecord, return shape for frontend preview
    pass


@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(
    proposal_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Reject a proposal without applying it."""
    service = ProposalService(session)
    return await service.reject_proposal(proposal_id)
```

#### 2.7 Integration with Existing Infrastructure

The `propose_create_page` tool reuses these existing components:

| Concern | Existing Component | Usage |
|---|---|---|
| Template type existence | `TemplateTypeRepository.get_by_template_id()` | Validate type exists, not just in allowlist |
| Component type schema | `ComponentType.schema` field (JSON schema) | Validate `data` shape per template_type |
| Renderer support | `RendererManifest.get_supported_types()` | Check is_exportable for warnings |
| Error envelope | `utils/error_envelope.build_error()` | Consistent error shape |
| Course existence | `CourseRepository.get_by_course_id()` | Validate course exists before proposal |
| Page persistence | `PageRepository.create()`, `ComponentRepository.create()` | Used in apply |
| Order management | `PageRepository.count_by_course()`, `PageRepository.reorder()` | Used to compute insert_at_index |

#### 2.8 Environment Variables

```bash
# AI Proposal TTL (default 30 minutes)
AI_PROPOSAL_TTL_MINUTES=30

# AI allowlist control (comma-separated, empty = all enabled types allowed)
AI_TEMPLATE_ALLOWLIST=content-text,tabs,accordion,click-reveal,final-assessment

# Feature flag for AI proposal system
AI_PROPOSALS_ENABLED=true
```

Register these in `app/utils/feature_flags.py`:
```python
'ai_proposals': FeatureFlag(
    name='ai_proposals',
    enabled=False,
    description='Enable AI page proposal and apply system',
    environments=[Environment.DEVELOPMENT, Environment.QA, Environment.STAGING, Environment.PRODUCTION]
),
```

#### 2.9 Router Registration in main.py

```python
# In app/main.py, after existing includes:
from app.routers import ai_tools
api_router.include_router(ai_tools.router)
```

---

### 3. NON-FUNCTIONAL REQUIREMENTS

| ID | Requirement | Target | Measurement |
|---|---|---|---|
| NFR1 | Proposal creation latency | < 500ms p95 (excluding LLM time) | APM tracing |
| NFR2 | Proposal apply latency | < 2s p95 (includes DB writes, audit, outbox) | APM tracing |
| NFR3 | Proposal TTL | 30 minutes default, configurable | Integration test |
| NFR4 | Concurrent proposals per session | Max 5 active proposals | Server-side enforcement |
| NFR5 | Max proposals per course per hour | 50 | Rate limiter |
| NFR6 | Proposal storage retention | 90 days after expiry | Cleanup job |
| NFR7 | Idempotent apply | Same proposal_id -> same result, no duplicate pages | Integration test |
| NFR8 | Audit completeness | Every apply produces audit + outbox record | Transactional test |
| NFR9 | Error response time (validation failures) | < 200ms | APM tracing |
| NFR10 | Proposal payload size limit | 1 MB | Server-side enforcement |
| NFR11 | Concurrent apply operations | 10 per second per tenant | Rate limiter |

---

### 4. CURRENT STATE ANALYSIS

#### 4.1 What Exists Today

- **Page CRUD endpoints** at `/api/v1/courses/{courseId}/pages` (create, read, update, delete, reorder).
- **Component CRUD endpoints** at `/api/v1/courses/{courseId}/pages/{pageId}/components`.
- **Create page from template** endpoint at `POST /api/v1/courses/{courseId}/pages/from-template` (sync, manual-only).
- **Course validation** endpoint at `POST /api/v1/courses/validate` (schema + business rules).
- **Template type registry** with 89 component types across 17 categories.
- **Renderer manifest** covering 84 template types with exportability metadata.
- **Feature flag system** with environment-based gating.
- **Async PostgreSQL** via SQLAlchemy with connection pooling.
- **Error envelope** pattern (`utils/error_envelope.py`).
- **AI architecture** documented with tool schemas, session flows, and validation pipeline in `docs/AI_Implemenation/`.

#### 4.2 What Is Missing (Gaps)

| Gap | Impact | Addressed By |
|---|---|---|
| No `ai_sessions` table or repository | Cannot scope AI tool calls | US-BKND-AI-004, US-BKND-AI-006 |
| No `ai_proposals` table | No proposal lifecycle persistence | This story |
| No `ai_audit_logs` table | No audit trail for AI operations | US-BKND-AI-010 |
| No `outbox_events` table | No downstream event publishing | US-BKND-AI-010 |
| No proposal validation logic | AI could create invalid pages directly | This story |
| No template allowlist enforcement | AI could use unsupported templates | This story |
| No `GET /api/v1/ai/tools/*` endpoints | No AI tool interface | This story |
| No base_hash staleness detection | Risk of concurrent-edit conflicts | This story |
| No confirmation token flow | No double-confirm for creates | This story |
| No feature flag for AI proposals | Cannot disable AI proposal system independently | This story |

#### 4.3 Existing Endpoints That Remain Unchanged

- `POST /api/v1/courses` -- manual course creation
- `POST /api/v1/courses/{courseId}/pages` -- manual page creation
- `PATCH /api/v1/courses/{courseId}/pages/{pageId}` -- manual page update
- `DELETE /api/v1/courses/{courseId}/pages/{pageId}` -- manual page delete
- `POST /api/v1/courses/{courseId}/pages/from-template` -- manual template-picker page creation
- `POST /api/v1/courses/validate` -- validation (called internally by proposal validator)
- All component CRUD endpoints
- All export endpoints
- All template-type/component-type listing endpoints

---

### 5. EXPANSION POINTS

| Expansion | Description | When |
|---|---|---|
| Batch proposal creation | `propose_batch_pages` with all-or-nothing semantics (US-BKND-AI-029) | After MVP |
| Auto-apply for low-risk changes | Policy engine auto-approves content-text proposals for trusted roles (US-BKND-AI-032) | Production hardening |
| Preview HTML generation | Async preview rendering of proposal page (US-BKND-AI-041) | Production UX |
| Component-level proposals | Propose only specific component changes instead of full page | Post-launch |
| Versioned rollback | Rollback applied proposal to before_snapshot (US-BKND-AI-040) | Post-launch |
| Multi-LLM provider routing | Fallback model if primary fails (US-BKND-AI-026) | Production hardening |
| Template harvesting | Promote AI-generated page patterns to template definitions (US-BKND-AI-037) | Post-launch |
| RAG-informed proposals | `query_similar_courses` provides examples for better proposals (US-BKND-AI-015) | Post-launch |
| Allowed template list from DB | Store template allowlist in `template_types.can_be_page` column instead of hardcoded | After MVP |

---

### 6. VALIDATION AND ACCEPTANCE CRITERIA

#### 6.1 Functional Tests (Automated, pytest)

**TC-PROPOSAL-01: Propose valid content-text page**
- Given a valid session, call `propose_create_page` with `template_type="content-text"` and valid `data.content`.
- Expected: returns `proposal_id`, `validation_status="valid"`, no `validation_messages.errors`.

**TC-PROPOSAL-02: Propose valid tabs page**
- Given `template_type="tabs"` with 3 tab items.
- Expected: `validation_status="valid"`.

**TC-PROPOSAL-03: Propose unsupported template type**
- Call with `template_type="video-slide"`.
- Expected: 422 error, code `UNSUPPORTED_TEMPLATE`.

**TC-PROPOSAL-04: Propose tabs with insufficient items**
- Call with `template_type="tabs"` and only 1 tab.
- Expected: `validation_status="error"`, `validation_messages` includes "Tabs requires at least 2 items".

**TC-PROPOSAL-05: Propose final-assessment with insufficient questions**
- Call with `template_type="final-assessment"` and 1 question.
- Expected: `validation_status="error"`, message contains "requires at least 3 questions".

**TC-PROPOSAL-06: Propose does not mutate database**
- Call `propose_create_page` with valid data.
- Expected: No `PageRecord` or `ComponentRecord` created. Only `AiProposalRecord` exists.

**TC-PROPOSAL-07: Apply valid proposal**
- Given a previously-created proposal with `validation_status="valid"`.
- Call `apply_page_proposal` with `user_confirmed=true`.
- Expected: status `"created"`, returns `page_id`. `PageRecord` exists. `ComponentRecord` entries exist. `AiProposalRecord.status` is `"applied"`. `AiProposalRecord.applied_at` is non-null.

**TC-PROPOSAL-08: Apply without user_confirmed**
- Call `apply_page_proposal` with `user_confirmed=false`.
- Expected: 400 error, code `USER_CONFIRMATION_REQUIRED`.

**TC-PROPOSAL-09: Idempotent apply**
- Apply same proposal twice.
- Expected: Second call returns same `page_id` and status `"created"`. No duplicate pages. Only 1 `PageRecord` exists.

**TC-PROPOSAL-10: Apply expired proposal**
- Given a proposal with `expires_at` in the past.
- Expected: status `"rejected"`, message "Proposal has expired".

**TC-PROPOSAL-11: Apply with stale base_hash**
- Given a proposal for a create where course state changed after proposal creation.
- Expected: status `"error"`, code `CONFLICT`, message "Course has been modified".

**TC-PROPOSAL-12: Reject proposal**
- Call `POST /proposals/{proposal_id}/reject`.
- Expected: `AiProposalRecord.status` is `"rejected"`. No pages created.

**TC-PROPOSAL-13: Final-assessment passing score validation**
- Propose with `passingScore` = 150.
- Expected: `validation_status="error"`, message "passingScore must be 0-100".

**TC-PROPOSAL-14: Tabs max constraint**
- Propose with 7 tabs.
- Expected: `validation_status="error"`, message "Maximum 6 tabs allowed".

**TC-PROPOSAL-15: Content-text min content**
- Propose with `content=""` (empty string).
- Expected: `validation_status="error"`, message "Content must be at least 10 characters".

**TC-PROPOSAL-16: Audit and outbox on apply**
- After successful apply:
- Expected: `ai_audit_logs` contains entry with `operation="PageCreatedByAI"`, `proposal_id` matches, `page_id` matches.
- Expected: `outbox_events` contains entry with `event_type="PageCreatedByAI"`, `aggregate_id` = page_id.

**TC-PROPOSAL-17: Feature flag blocks proposals**
- Set `AI_PROPOSALS_ENABLED=false`.
- Expected: propose endpoints return 404 with "Feature not available".

#### 6.2 Manual Test Scenarios

**MTC-01: Full AI create page flow**
1. Author opens AI chat on a course with 3 existing pages.
2. AI proposes a new accordion page at index 1.
3. Frontend shows proposal preview with page title, accordion panel data, and validation (valid).
4. Author clicks "Apply".
5. Page appears in the course page list at position 2 (0-based index 1).
6. Author can edit the AI-created page in the existing editor.

**MTC-02: Proposal preview rendering**
1. AI proposes a final-assessment page with 5 questions.
2. Frontend shows preview with all 5 questions rendered.
3. Validation messages for any warnings appear.

**MTC-03: Concurrent edits detection**
1. Author A opens AI session, creates a proposal.
2. Author B manually adds a page to the course (changes base hash).
3. Author A clicks "Apply" on the stale proposal.
4. Backend returns 409 CONFLICT.
5. Frontend shows "Course has changed. Please create a new proposal."

**MTC-04: Expired proposal handling**
1. Create a proposal and wait 31 minutes (or set TTL to 1 minute in test).
2. Click "Apply".
3. Frontend shows "Proposal has expired. Please ask the AI to create a new proposal."

#### 6.3 Non-Functional Tests

**Load test:** 50 concurrent proposal creations, 50 concurrent applies. Target: p95 latency < 2s per operation. No proposal loss. No duplicate pages.

**Security test:** Attempt to apply a proposal from session A using session B's credentials. Expected: 403 Permission denied. Attempt to apply a proposal for course A while scoped to course B. Expected: 403 Permission denied.

---

### 7. DEFINITION OF DONE

- [ ] `ai_proposals` table created via Alembic migration, rollback-tested.
- [ ] `AiProposalRecord` ORM model defined and importable.
- [ ] `app/ai/proposal_service.py` implemented with `propose_create_page`, `apply_page_proposal`, `reject_proposal` methods.
- [ ] `app/ai/template_allowlist.py` implemented with MVP allowlist and schema validation.
- [ ] `app/ai/proposal_validator.py` implemented with business-rule validation.
- [ ] `app/routers/ai_tools.py` implemented with `POST /api/v1/ai/tools/propose_create_page`, `POST /api/v1/ai/tools/apply_page_proposal`, `GET /api/v1/ai/tools/proposals/{proposal_id}`, `POST /api/v1/ai/tools/proposals/{proposal_id}/reject` endpoints.
- [ ] Router registered in `app/main.py`.
- [ ] `ai_proposals` feature flag added to `app/utils/feature_flags.py`.
- [ ] Proposal TTL env var `AI_PROPOSAL_TTL_MINUTES` documented and wired.
- [ ] Template allowlist config env var `AI_TEMPLATE_ALLOWLIST` documented and wired.
- [ ] All 17 automated test scenarios pass (TC-PROPOSAL-01 through TC-PROPOSAL-17).
- [ ] All 4 manual test scenarios documented and verified (MTC-01 through MTC-04).
- [ ] Audit log written for every successful apply.
- [ ] Outbox event written for every successful apply.
- [ ] Idempotent apply verified: double-submit creates no duplicate pages.
- [ ] Apply with `user_confirmed=false` is rejected with clear error.
- [ ] Expired proposals are rejected with clear error (set TTL to 1 minute, wait, verify).
- [ ] Stale base_hash returns 409 conflict.
- [ ] Existing manual page CRUD tests still pass (no regression).
- [ ] Existing course validation tests still pass (no regression).
- [ ] API docs show new AI tool endpoints under "AI Tools" tag.
- [ ] Code reviewed and merged to `demo-course-AI` branch.
- [ ] Feature flag `ai_proposals` defaults to `False`; set to `True` in dev environment for testing.

---

### 8. TASK BREAKDOWN

#### Task 1: Alembic Migration for ai_proposals table
**Files:** `alembic/versions/20260614_0001_add_ai_proposals.py`, `app/models/ai_proposal.py`
**Acceptance:** Migration creates `ai_proposals` table with all columns, indexes, and foreign key. Rollback drops the table. `AiProposalRecord.to_dict()` returns the expected shape.

#### Task 2: Template Allowlist Module
**Files:** `app/ai/__init__.py`, `app/ai/template_allowlist.py`
**Acceptance:** `TemplateAllowlist.is_allowed("tabs")` returns True. `TemplateAllowlist.is_allowed("video-slide")` returns False. `validate_schema("tabs", {"tabs": [{"id": "a", "label": "A", "content": "body"}]})` returns empty errors. `validate_schema("tabs", {"tabs": []})` returns error. All 5 MVP template types covered.

#### Task 3: Proposal Validator
**Files:** `app/ai/proposal_validator.py`
**Acceptance:** Calls `TemplateAllowlist.validate_schema` and adds business rules: tab unique labels, accordion unique IDs, final-assessment question count cap (50), passingScore range (0-100), content-text min length (10). Integrates with `RendererManifest.is_supported`.

#### Task 4: Proposal Service (Core Logic)
**Files:** `app/ai/proposal_service.py`
**Acceptance:** `propose_create_page` validates session, validates template, validates data, computes base_hash, stores `AiProposalRecord` with `status="pending"`, returns proposal_id and preview. `apply_page_proposal` re-validates expiry, base_hash, user_confirmed; creates PageRecord + ComponentRecord entries; updates proposal to `applied`; writes audit + outbox. `reject_proposal` sets status to `rejected`.

#### Task 5: AI Tools Router
**Files:** `app/routers/ai_tools.py`
**Acceptance:** `POST /api/v1/ai/tools/propose_create_page` receives request body, delegates to ProposalService, returns proposal. `POST /api/v1/ai/tools/apply_page_proposal` delegates to service, returns result. `GET /api/v1/ai/tools/proposals/{proposal_id}` returns proposal details. `POST reject` rejects proposal. Error responses use `utils/error_envelope` shape. Router registered in `app/main.py`.

#### Task 6: Feature Flag and Configuration
**Files:** `app/utils/feature_flags.py`, `app/main.py`
**Acceptance:** `ai_proposals` flag added, defaults to `False`. Environment variables `AI_PROPOSAL_TTL_MINUTES`, `AI_TEMPLATE_ALLOWLIST` parsed at startup. When flag is off, AI tool endpoints return 404. When flag is on, endpoints operate normally.

#### Task 7: Automated Tests
**Files:** `tests/test_ai_proposals.py`
**Acceptance:** All 17 TC-PROPOSAL-* tests implemented as pytest async tests. Mock the database session and session service. Test each validation rule, each apply success/failure path, idempotency, expiry, audit, outbox, and feature flag gating. Existing regression tests (`test_courses_api.py`, `test_page_components_api.py`, `test_course_validate_api.py`) still pass.

#### Task 8: Manual Test Scenarios and Documentation
**Files:** `docs/AI_Implemenation/00_User_StoriesUseCases/US-BKND-AI-011_TEST_PLAN.md` (new)
**Acceptance:** MTC-01 through MTC-04 documented with step-by-step instructions. Expected results and pass/fail criteria documented. All 4 scenarios pass when executed manually against a development server.

#### Task 9: Integration Wiring
**Files:** `app/routers/ai_tools.py` (session validation integration)
**Acceptance:** After US-BKND-AI-006 is complete, integrate `AiSessionRepository` into the proposal endpoints to validate that the session is active, not expired, and scoped to the correct course. Wire `organization_id` scoping via session.

---

### Implementation Order

```
Task 2 (Allowlist)       ─┐
Task 3 (Validator)       ─┤
                         ├─→ Task 4 (Service) ─→ Task 5 (Router) ─→ Task 6 (Flags)
Task 1 (Migration)       ─┘
                                               ↓
                                          Task 7 (Tests)
                                               ↓
                                          Task 8 (Docs)
                                               ↓
                                          Task 9 (Integration)
```

---