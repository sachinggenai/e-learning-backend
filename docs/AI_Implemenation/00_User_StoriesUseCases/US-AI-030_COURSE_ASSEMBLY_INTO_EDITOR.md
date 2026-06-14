# US-AI-030: Course Assembly into Existing Editor

**Status:** Draft
**Priority:** MUST (MVP)
**Depends on:** US-AI-009 (Generic Proposal Lifecycle), US-AI-011 (Create Page Proposal), US-AI-012 (Update Page Proposal), US-AI-013 (Delete Page Proposal), US-AI-023 (AI Chat Endpoint), US-AI-024 (Frontend AI Integration Layer)
**Source flow:** 18. Course Assembly into Existing Editor
**Epic Owner:** Technical Product Owner

---

## 1. Functional Specification

### 1.1 User Story

As an **Author**, I want AI-generated courses and pages to load into the existing course editor seamlessly, so that I can continue editing manually after AI generation completes without disruption, data loss, or format mismatches.

As a **Frontend Engineer**, I want a deterministic assembly contract that transforms AI proposal outputs into the editor's native page/component state tree, so that the existing editor components render AI-generated and manually-authored content identically without requiring editor rewrites.

As a **Backend Engineer**, I want a centralized `CourseAssembler` service that owns the proposal-to-editor-state transformation pipeline, so that all AI mutation pathways (single page, batch, file-ingestion) converge on a single assembly code path.

### 1.2 Overview

This user story delivers the **assembly layer** that bridges AI-generated content proposals and the existing manual course editor. It is the final integration step that makes AI output "real" inside the editor.

The architecture follows a **transform → map → refresh** pattern:

1. **Transform**: A proposal (create/update/delete) produces a set of changes targeting `PageRecord` and `ComponentRecord` entities.
2. **Map**: The `CourseAssembler` maps proposal data fields to the editor's expected state shape, including layout config, component types, data payloads, completion criteria, and theme overrides.
3. **Refresh**: The editor state is refreshed from the database via existing `GET /api/v1/courses/{courseId}` which returns the composite course + pages + components response, ensuring the editor sees the identical data shape as manual authoring.

**Key design decisions:**

- **No dual-write problem**: AI proposals write to the same `pages` and `components` tables as manual authoring. There is no separate "AI content" storage.
- **Proposal-to-assembly is a one-way map**: The `CourseAssembler` reads proposal data and writes `PageRecord`/`ComponentRecord` rows. It never reads back and re-transforms.
- **Editor remains unchanged**: The existing editor components consume `GET /api/v1/courses/{courseId}` which already returns the composite `pages[]` with nested `components[]`. No new editor endpoints are needed for assembly.
- **Component type compatibility is enforced at assembly time**: The assembler validates that every component type in proposal data exists in the `ComponentType` registry before writing. Unknown types are rejected with a specific error code.
- **Assembly is idempotent**: Applying the same proposal twice produces the same final state (proposal lifecycle prevents double-apply via `PROPOSAL_ALREADY_APPLIED` check).

### 1.3 Actors

| Actor | Role |
|---|---|
| Author (User) | Proposes AI changes via chat (US-AI-023); reviews proposals (US-AI-024); confirms apply |
| AI Agent (LLM) | Generates proposal payloads with page title, component types, component data |
| CourseAssembler (Server) | Transforms proposal data into PageRecord/ComponentRecord rows; validates component type compatibility; refreshes editor state |
| ProposalApplier (Server) | Reads proposal payload, calls CourseAssembler, commits the transaction, returns the assembled state |
| Editor State Provider (Server) | Existing `GET /api/v1/courses/{courseId}` endpoint that returns course + pages + components composite |
| Frontend Editor | Existing editor components that render pages and components from the state tree |

### 1.4 Flow: Course Assembly After Proposal Apply

**Precondition:** An AI proposal exists with status `PENDING_REVIEW` (US-AI-009). The proposal payload contains the full page/component specification.

**Phase 0 — User Confirms Proposal**
1. User reviews the proposal card in the AI panel (US-AI-024).
2. User clicks "Apply" (for create/update) or types "DELETE" and clicks confirm (for delete).
3. Frontend calls `POST /api/v1/ai/proposals/{proposalId}/apply` with `{ sessionId, userConfirmed: true }`.

**Phase 1 — Server Validates and Assembles**
1. Server verifies the proposal exists, belongs to the session's course, and is in `PENDING_REVIEW` status.
2. Server calls `CourseAssembler.assemble(session, proposal)` which:
   a. Reads the proposal payload (`operation`, `pageSpec`, `components[]`).
   b. Validates the operation type: `CREATE_PAGE`, `UPDATE_PAGE`, `DELETE_PAGE`.
   c. Calls `_validate_component_types(components)` against the `ComponentType` registry.
   d. Calls the specific assembly method:
      - `_assemble_create_page(payload)` — creates `PageRecord` + `ComponentRecord[]` rows.
      - `_assemble_update_page(payload)` — updates `PageRecord` fields, replaces `ComponentRecord[]` rows.
      - `_assemble_delete_page(payload)` — deletes `PageRecord` (cascades to components).
   e. Returns an `AssemblyResult` with the new/updated/deleted page IDs and a state refresh token.

**Phase 2 — Commit and Refresh**
1. The transaction is committed. Proposal status transitions to `APPLIED`.
2. Server returns the assembly result including `pageId`, `operation`, and `courseId`.
3. Frontend receives the successful response.
4. Frontend calls `GET /api/v1/courses/{courseId}` to refresh the full course state.
5. Editor re-renders with the new/updated/deleted pages, showing AI-generated content identically to manual content.

**Phase 3 — Post-Assembly Editor Interaction**
1. The AI-generated page appears in the page list with the correct title, order, and metadata.
2. Clicking the page opens it in the existing page editor.
3. All page fields (title, layout, theme, completion config) are editable.
4. All components are displayed in the component list with the correct types and data.
5. Components can be reordered, edited, or deleted using existing editor controls.
6. Preview renders the page identically to a manually-authored page with the same data.

### 1.5 Data Transformation Mapping

The core of the assembly layer is the **proposal-to-editor-state transformation map**. This maps each field in the AI proposal payload to the corresponding `PageRecord`/`ComponentRecord` column.

#### Create Page Mapping

| Proposal Field | Target Entity | Target Column | Transformation |
|---|---|---|---|
| `pageSpec.title` | `PageRecord` | `title` | Direct copy; truncated to 200 chars |
| `pageSpec.layout.templateId` | `PageRecord` | `layout` -> `{"template_id": ...}` | Wrapped into layout dict |
| `pageSpec.layout.customizations` | `PageRecord` | `layout` -> `{"customizations": ...}` | Merged into layout dict |
| `pageSpec.theme` | `PageRecord` | `theme_config` | Direct copy; validated against ThemeType |
| `pageSpec.completionConfig` | `PageRecord` | `completion_config` | Direct copy; validated schema |
| `components[].componentType` | `ComponentRecord` | `component_type` | Validated against ComponentType registry; mapped to DB value |
| `components[].data` | `ComponentRecord` | `data` | Direct copy; validated against ComponentType.schema |
| `components[].order` | `ComponentRecord` | `order_index` | Assigned sequentially if missing |
| `components[].audioConfig` | `ComponentRecord` | `audio_config` | Direct copy (nullable) |
| `components[].completionCriteria` | `ComponentRecord` | `completion_criteria` | Direct copy (nullable) |
| `components[].styling` | `ComponentRecord` | `styling` | Direct copy (nullable) |

#### Update Page Mapping

| Proposal Field | Target Entity | Target Column | Transformation |
|---|---|---|---|
| `pageSpec.title` | (existing) `PageRecord` | `title` | Direct update |
| `pageSpec.layout` | (existing) `PageRecord` | `layout` | Full replace |
| `pageSpec.theme` | (existing) `PageRecord` | `theme_config` | Full replace (null = clear) |
| `pageSpec.completionConfig` | (existing) `PageRecord` | `completion_config` | Full replace (null = clear) |
| `components[]` | (existing) `ComponentRecord[]` | All columns | **Full replacement**: all existing components are deleted, then new ones are created (enables reordering and type changes) |

#### Delete Page Mapping

| Proposal Field | Target Entity | Action |
|---|---|---|
| `pageId` | `PageRecord` | DELETE CASCADE (all `ComponentRecord` rows for this page are auto-deleted) |
| `pageId` | `PageRecord` | `order_index` of subsequent pages decremented by 1 |

### 1.6 Component Type Compatibility Matrix

The following component types are compatible between AI proposals and the existing editor. Any type not in this matrix is rejected at assembly time with `UNSUPPORTED_COMPONENT_TYPE`.

| Component Type Key | Editor Support | SCORM Exportable | AI Proposable | Notes |
|---|---|---|---|---|
| `text-content` | Full | Yes | Yes | Pydantic `TemplateData.content` |
| `content-text` | Full | Yes | Yes | Alias for text-content |
| `welcome` | Full | Yes | Yes | Pydantic `TemplateData.content` + `subtitle` |
| `content-video` | Full | Yes | Yes | Requires `videoUrl` field |
| `video` | Full | Yes | Yes | Alias for content-video |
| `mcq` | Full | Yes | Yes | Pydantic `MCQData`; requires `questions` array |
| `quiz` | Full | Yes | Yes | Alias for mcq |
| `tabs` | Full | Yes | Yes | Requires `tabs` array with `title` + `content` |
| `accordion` | Full | Yes | Yes | Requires `panels` array with `title` + `content` |
| `final-assessment` | Full | Yes | Yes | Pydantic `FinalAssessmentData`; >= 1 question |
| `summary` | Full | Yes | Yes | Deprecated; mapped to text-content |
| `click-reveal` | Limited | Yes | Post-MVP | Requires new ComponentType registration |
| `flashcard` | Limited | Yes | Post-MVP | Requires new ComponentType registration |
| `hotspot` | Limited | Yes | Post-MVP | Requires new ComponentType registration |
| `scenario` | Limited | Yes | Post-MVP | Requires new ComponentType registration |
| `drag-drop` | Limited | Yes | Post-MVP | Requires new ComponentType registration |
| `timeline` | Limited | Yes | Post-MVP | Requires new ComponentType registration |
| `sorting` | Limited | Yes | Post-MVP | Requires new ComponentType registration |

**MVP-compatible types** (full support in Phase 1): `text-content`, `welcome`, `content-video`, `mcq`, `tabs`, `accordion`, `final-assessment`.

### 1.7 Editor State Refresh Contract

After assembly completes, the frontend must refresh course state from the existing endpoint:

**GET /api/v1/courses/{courseId}**

Response shape (existing — unchanged):

```json
{
  "id": 1,
  "courseId": "course_abc123",
  "title": "Introduction to Python",
  "status": "draft",
  "description": "A comprehensive Python course",
  "createdAt": "2026-06-14T10:00:00Z",
  "updatedAt": "2026-06-14T11:30:00Z",
  "data": { "author": "...", "language": "en", "version": "1.0.0" },
  "author": "...",
  "language": "en",
  "version": "1.0.0",
  "navigation": { "allowSkip": true, "showProgress": true },
  "settings": { "theme": "default", "autoplay": false },
  "pages": [
    {
      "pageId": "page_abc123",
      "title": "Welcome to Python",
      "order": 0,
      "layout": { "template_id": "welcome", "customizations": {} },
      "theme": null,
      "pageCompletion": null,
      "createdAt": "2026-06-14T11:30:00Z",
      "updatedAt": "2026-06-14T11:30:00Z",
      "components": [
        {
          "componentId": "comp_xyz789",
          "componentType": "text-content",
          "order": 0,
          "data": { "content": "Python is a versatile programming language..." },
          "audioConfig": null,
          "completionCriteria": null,
          "styling": null,
          "createdAt": "2026-06-14T11:30:00Z",
          "updatedAt": "2026-06-14T11:30:00Z"
        }
      ]
    }
  ]
}
```

### 1.8 Error Conditions

| Condition | HTTP Status | Error Code | Behavior |
|---|---|---|---|
| Proposal not found | 404 | `PROPOSAL_NOT_FOUND` | Apply rejected; proposal may have expired |
| Proposal already applied | 409 | `PROPOSAL_ALREADY_APPLIED` | Idempotent: return existing assembly result |
| Proposal not in PENDING_REVIEW | 409 | `PROPOSAL_INVALID_STATUS` | Proposal in EXPIRED/REJECTED state |
| Unsupported component type | 422 | `UNSUPPORTED_COMPONENT_TYPE` | Component type not in compatibility matrix |
| Component data fails schema validation | 422 | `COMPONENT_DATA_INVALID` | Data does not match ComponentType schema |
| Page title exceeds max length | 422 | `PAGE_TITLE_TOO_LONG` | Title > 200 chars |
| Course not found | 404 | `COURSE_NOT_FOUND` | The course referenced by the proposal was deleted |
| Session user mismatch | 403 | `SESSION_USER_MISMATCH` | Apply attempted by different user |
| Database constraint violation | 500 | `ASSEMBLY_FAILED` | Unexpected DB error during assembly |
| Concurrent modification detected | 409 | `PAGE_CONCURRENTLY_MODIFIED` | Page hash changed since proposal creation (optimistic lock) |

---

## 2. Technical Specification

### 2.1 New Database Tables — DDL

**Table: `component_type_compatibility`**

Tracks which component types are compatible with AI proposals and the editor.

```sql
CREATE TABLE component_type_compatibility (
    id                      SERIAL PRIMARY KEY,
    component_type          VARCHAR(100) UNIQUE NOT NULL,
    display_name            VARCHAR(200) NOT NULL,
    editor_support          VARCHAR(16) NOT NULL DEFAULT 'full'
                            CHECK (editor_support IN ('full', 'limited', 'none')),
    ai_proposable           BOOLEAN NOT NULL DEFAULT true,
    scorm_exportable        BOOLEAN NOT NULL DEFAULT true,
    schema_signature        VARCHAR(64),                           -- FK to template_definitions
    min_components          INTEGER NOT NULL DEFAULT 0,
    max_components          INTEGER,                                -- NULL = unlimited
    requires_fields         JSONB DEFAULT '[]',                     -- Required field names
    incompatible_with       JSONB DEFAULT '[]',                     -- Incompatible component types
    notes                   TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ccc_ai_proposable ON component_type_compatibility(ai_proposable);
CREATE INDEX idx_ccc_editor ON component_type_compatibility(editor_support);
```

**Seed data:**

```sql
INSERT INTO component_type_compatibility (component_type, display_name, editor_support, ai_proposable, scorm_exportable, min_components, requires_fields) VALUES
    ('text-content',    'Text Content',       'full', true,  true, 1, '["content"]'),
    ('welcome',         'Welcome Page',       'full', true,  true, 1, '["content"]'),
    ('content-video',   'Video Content',      'full', true,  true, 1, '["videoUrl"]'),
    ('mcq',             'Multiple Choice',    'full', true,  true, 1, '["questions"]'),
    ('tabs',            'Tabs',               'full', true,  true, 1, '["tabs"]'),
    ('accordion',       'Accordion',          'full', true,  true, 1, '["panels"]'),
    ('final-assessment','Final Assessment',   'full', true,  true, 1, '["questions"]'),
    ('summary',         'Summary',            'full', false, true, 1, '["content"]'),       -- Deprecated
    ('click-reveal',    'Click to Reveal',    'limited', false, true, 1, '["items"]'),
    ('flashcard',       'Flashcard',          'limited', false, true, 1, '["cards"]'),
    ('scenario',        'Scenario',           'limited', false, true, 1, '["stages"]');
```

### 2.2 SQLAlchemy ORM Model

**Add to existing file: `app/models/component_type.py`** (or create new if not exists)

```python
"""ORM model for component type compatibility matrix."""
from __future__ import annotations
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, DateTime, JSON, Text, Boolean, Integer, CheckConstraint
from sqlalchemy.dialects.postgresql import TIMESTAMPTZ

from app.models.base import Base


class ComponentTypeCompatibilityRecord(Base):
    """Compatibility metadata for component types across AI, editor, and export."""

    __tablename__ = "component_type_compatibility"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    component_type: Mapped[str] = mapped_column(
        String(100), unique=True, index=True
    )
    display_name: Mapped[str] = mapped_column(String(200))
    editor_support: Mapped[str] = mapped_column(
        String(16), default="full"
    )  # 'full', 'limited', 'none'
    ai_proposable: Mapped[bool] = mapped_column(Boolean, default=True)
    scorm_exportable: Mapped[bool] = mapped_column(Boolean, default=True)
    schema_signature: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    min_components: Mapped[int] = mapped_column(Integer, default=0)
    max_components: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    requires_fields: Mapped[list] = mapped_column(JSON, default=list)
    incompatible_with: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "componentType": self.component_type,
            "displayName": self.display_name,
            "editorSupport": self.editor_support,
            "aiProposable": self.ai_proposable,
            "scormExportable": self.scorm_exportable,
            "schemaSignature": self.schema_signature,
            "minComponents": self.min_components,
            "maxComponents": self.max_components,
            "requiresFields": self.requires_fields,
            "incompatibleWith": self.incompatible_with,
            "notes": self.notes,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }
```

### 2.3 Pydantic DTOs

**New file: `app/routers/assembly_dtos.py`**

```python
"""Pydantic DTOs for the course assembly API."""
from __future__ import annotations
from typing import Optional, Any, Literal
from pydantic import BaseModel, Field


class AssemblyResult(BaseModel):
    """Result of a course assembly operation."""
    proposal_id: str
    session_id: str
    course_id: str
    operation: Literal["create_page", "update_page", "delete_page"]
    page_id: Optional[str] = Field(None, description="Affected page ID (null for batch)")
    page_title: Optional[str] = None
    page_order: Optional[int] = None
    component_count: int = 0
    applied_at: str = ""  # ISO-8601 timestamp
    state_refresh_token: Optional[str] = Field(
        None,
        description="Token to pass to GET /courses/{courseId} for cache-busting"
    )


class AssemblyError(BaseModel):
    """An error during assembly, returned inline."""
    code: str
    message: str
    field: Optional[str] = None
    component_index: Optional[int] = None
    retryable: bool = False


class AssemblyValidationResult(BaseModel):
    """Pre-flight validation result before assembly."""
    valid: bool
    errors: list[AssemblyError] = Field(default_factory=list)
    warnings: list[AssemblyError] = Field(default_factory=list)
    component_count: int = 0
    page_title: str = ""
    page_order: int = 0


class StateRefreshResponse(BaseModel):
    """Response from course state refresh."""
    course_id: str
    course_title: str
    page_count: int
    total_components: int
    updated_at: str


class AssemblyBatchResult(BaseModel):
    """Result of assembling multiple proposals in a batch."""
    batch_id: str
    results: list[AssemblyResult] = Field(default_factory=list)
    errors: list[AssemblyError] = Field(default_factory=list)
    all_succeeded: bool = False
```

### 2.4 Service Signatures

**New file: `app/services/ai/course_assembler.py`**

```python
"""Course Assembler — transforms AI proposal output into editor state.

The CourseAssembler is the single entry point for converting AI proposals
into persisted PageRecord and ComponentRecord rows that the existing editor
can consume. It enforces the component type compatibility matrix and validates
data shapes before writing.

All mutation pathways converge here:
  - Single page create (US-AI-011)
  - Single page update (US-AI-012)
  - Single page delete (US-AI-013)
  - Batch page operations (US-AI-029)
  - File ingestion apply (US-AI-019)

Usage:
    assembler = CourseAssembler(db_session)
    result = await assembler.assemble(session_context, proposal_payload)
"""

from __future__ import annotations
import logging
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.repositories.page_component_repo import PageRepository, ComponentRepository
from app.repositories.course_repo import CourseRepository, CourseNotFoundError

logger = logging.getLogger(__name__)


class ComponentTypeValidationError(ValueError):
    """Raised when a component type is not in the compatibility matrix."""
    def __init__(self, component_type: str, message: str):
        self.component_type = component_type
        super().__init__(message)


class AssemblyPermissionError(PermissionError):
    """Raised when assembly violates ownership or scope."""
    pass


class AssemblyConflictError(RuntimeError):
    """Raised on concurrent modification or proposal-already-applied."""
    pass


class AssemblyResult:
    """Structured result returned by every assembly method."""
    def __init__(
        self,
        proposal_id: str,
        operation: str,
        course_id: str,
        page_id: Optional[str] = None,
        page_title: Optional[str] = None,
        page_order: Optional[int] = None,
        component_count: int = 0,
        applied_at: Optional[str] = None,
    ):
        self.proposal_id = proposal_id
        self.operation = operation
        self.course_id = course_id
        self.page_id = page_id
        self.page_title = page_title
        self.page_order = page_order
        self.component_count = component_count
        self.applied_at = applied_at or datetime.utcnow().isoformat()


class CourseAssembler:
    """Transforms AI proposals into persisted editor state.

    The assembler is stateless — all state is in the passed session_context.
    It performs writes via PageRepository and ComponentRepository.
    """

    MAX_PAGE_TITLE_LENGTH = 200
    MVP_COMPATIBLE_TYPES = frozenset({
        "text-content", "welcome", "content-video", "mcq",
        "tabs", "accordion", "final-assessment", "content-text",
        "video", "quiz",
    })

    def __init__(self, db_session: AsyncSession):
        self.session = db_session
        self.page_repo = PageRepository(db_session)
        self.component_repo = ComponentRepository(db_session)
        self.course_repo = CourseRepository(db_session)

    async def assemble(
        self,
        session_context: dict,
        proposal_payload: dict,
    ) -> AssemblyResult:
        """Main assembly entry point — route to the correct method by operation.

        Args:
            session_context: Dict with keys:
                - session_id: str
                - course_id: str
                - user_id: str
                - proposal_id: str
            proposal_payload: Dict with keys:
                - operation: 'create_page' | 'update_page' | 'delete_page'
                - pageSpec: dict (title, layout, theme, completionConfig)
                - components: list[dict] (for create/update)
                - pageId: str (for update/delete)
                - baseHash: str | None (optimistic lock hash)

        Returns:
            AssemblyResult with outcome details.

        Raises:
            ComponentTypeValidationError: On unsupported component type.
            AssemblyPermissionError: On scope violation.
            AssemblyConflictError: On concurrent modification.
            CourseNotFoundError: On missing course.
        """
        operation = proposal_payload.get("operation")
        if operation == "create_page":
            return await self._assemble_create(session_context, proposal_payload)
        elif operation == "update_page":
            return await self._assemble_update(session_context, proposal_payload)
        elif operation == "delete_page":
            return await self._assemble_delete(session_context, proposal_payload)
        else:
            raise ValueError(f"Unknown assembly operation: {operation}")

    async def validate_payload(
        self,
        proposal_payload: dict,
    ) -> dict:
        """Pre-flight validation of a proposal payload without writing.

        Returns a dict with:
            valid: bool
            errors: list[dict] — blocking issues
            warnings: list[dict] — non-blocking advisories
            component_count: int
        """
        errors = []
        warnings = []
        operation = proposal_payload.get("operation")
        page_spec = proposal_payload.get("pageSpec", {})
        components = proposal_payload.get("components", [])
        page_id = proposal_payload.get("pageId")

        # Operation validation
        if operation not in ("create_page", "update_page", "delete_page"):
            errors.append({
                "code": "INVALID_OPERATION",
                "message": f"Unknown operation '{operation}'",
                "field": "operation",
            })

        # Title validation
        title = page_spec.get("title", "")
        if operation in ("create_page", "update_page"):
            if not title:
                errors.append({
                    "code": "MISSING_PAGE_TITLE",
                    "message": "Page title is required",
                    "field": "pageSpec.title",
                })
            elif len(title) > self.MAX_PAGE_TITLE_LENGTH:
                errors.append({
                    "code": "PAGE_TITLE_TOO_LONG",
                    "message": f"Page title exceeds {self.MAX_PAGE_TITLE_LENGTH} characters",
                    "field": "pageSpec.title",
                })

        # Component type validation
        if operation in ("create_page", "update_page"):
            for idx, comp in enumerate(components):
                comp_type = comp.get("componentType", "")
                if comp_type and comp_type not in self.MVP_COMPATIBLE_TYPES:
                    errors.append({
                        "code": "UNSUPPORTED_COMPONENT_TYPE",
                        "message": f"Component type '{comp_type}' is not supported in the editor",
                        "field": f"components[{idx}].componentType",
                        "componentIndex": idx,
                    })
                if not comp_type:
                    errors.append({
                        "code": "MISSING_COMPONENT_TYPE",
                        "message": f"Component at index {idx} is missing componentType",
                        "field": f"components[{idx}].componentType",
                        "componentIndex": idx,
                    })

            # Required field validation per type
            for idx, comp in enumerate(components):
                comp_type = comp.get("componentType", "")
                required = self._get_required_fields(comp_type)
                data = comp.get("data", {})
                for field_name in required:
                    if field_name not in data or data[field_name] is None:
                        errors.append({
                            "code": "MISSING_REQUIRED_FIELD",
                            "message": f"Component '{comp_type}' requires field '{field_name}'",
                            "field": f"components[{idx}].data.{field_name}",
                            "componentIndex": idx,
                        })

        # Page ID required for update/delete
        if operation in ("update_page", "delete_page") and not page_id:
            errors.append({
                "code": "MISSING_PAGE_ID",
                "message": "pageId is required for update/delete operations",
                "field": "pageId",
            })

        # Warning for empty components
        if operation in ("create_page", "update_page") and not components:
            warnings.append({
                "code": "NO_COMPONENTS",
                "message": "Page has no components; editor will show an empty page",
                "field": "components",
            })

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "component_count": len(components),
            "page_title": title,
            "page_order": page_spec.get("pageOrder", 0),
        }

    # ── Private: Assembly Methods ─────────────────────────────────

    async def _assemble_create(
        self,
        context: dict,
        payload: dict,
    ) -> AssemblyResult:
        """Create a new page from proposal data."""
        course_id = context["course_id"]
        page_spec = payload.get("pageSpec", {})
        components = payload.get("components", [])

        # Verify course exists
        try:
            await self.course_repo.get_by_course_id(course_id)
        except CourseNotFoundError:
            raise CourseNotFoundError(f"Course '{course_id}' not found")

        # Determine page order
        page_count = await self.page_repo.count_by_course(course_id)
        page_order = page_spec.get("pageOrder", page_count)

        # Build layout config
        layout = None
        template_id = page_spec.get("layout", {}).get("templateId")
        customizations = page_spec.get("layout", {}).get("customizations")
        if template_id or customizations:
            layout = {}
            if template_id:
                layout["template_id"] = template_id
            if customizations:
                layout["customizations"] = customizations

        # Create PageRecord
        from app.models.page_component import PageRecord

        page = PageRecord(
            course_id=course_id,
            title=page_spec["title"][:self.MAX_PAGE_TITLE_LENGTH],
            order_index=page_order,
            layout=layout,
            theme_config=page_spec.get("theme"),
            completion_config=page_spec.get("completionConfig"),
        )
        self.session.add(page)
        await self.session.flush()  # Get page_id

        # Create ComponentRecord rows
        await self._create_components(page.page_id, components)

        await self.session.commit()
        await self.session.refresh(page)

        return AssemblyResult(
            proposal_id=context["proposal_id"],
            operation="create_page",
            course_id=course_id,
            page_id=page.page_id,
            page_title=page.title,
            page_order=page.order_index,
            component_count=len(components),
        )

    async def _assemble_update(
        self,
        context: dict,
        payload: dict,
    ) -> AssemblyResult:
        """Update an existing page — replace fields and components."""
        course_id = context["course_id"]
        page_id = payload["pageId"]
        page_spec = payload.get("pageSpec", {})
        components = payload.get("components", [])

        # Fetch existing page
        page = await self.page_repo.get_by_course_and_page(course_id, page_id)
        if not page:
            raise ValueError(f"Page '{page_id}' not found in course '{course_id}'")

        # Check concurrent modification (optimistic lock)
        base_hash = payload.get("baseHash")
        if base_hash and self._compute_page_hash(page) != base_hash:
            raise AssemblyConflictError(
                f"Page '{page_id}' was modified since the proposal was created"
            )

        # Update PageRecord fields
        if "title" in page_spec:
            page.title = page_spec["title"][:self.MAX_PAGE_TITLE_LENGTH]
        if "layout" in page_spec:
            page.layout = page_spec["layout"]
        if "theme" in page_spec:
            page.theme_config = page_spec["theme"]
        if "completionConfig" in page_spec:
            page.completion_config = page_spec["completionConfig"]

        # Full replacement of components
        # Delete all existing components for this page
        from sqlalchemy import delete as sa_delete
        from app.models.page_component import ComponentRecord

        await self.session.execute(
            sa_delete(ComponentRecord).where(
                ComponentRecord.page_id == page.page_id
            )
        )

        # Create new components
        await self._create_components(page.page_id, components)

        await self.session.commit()
        await self.session.refresh(page)

        return AssemblyResult(
            proposal_id=context["proposal_id"],
            operation="update_page",
            course_id=course_id,
            page_id=page.page_id,
            page_title=page.title,
            page_order=page.order_index,
            component_count=len(components),
        )

    async def _assemble_delete(
        self,
        context: dict,
        payload: dict,
    ) -> AssemblyResult:
        """Delete a page (cascades to components)."""
        course_id = context["course_id"]
        page_id = payload["pageId"]

        page = await self.page_repo.get_by_course_and_page(course_id, page_id)
        if not page:
            raise ValueError(f"Page '{page_id}' not found in course '{course_id}'")

        page_title = page.title
        page_order = page.order_index
        component_count = len(page.components or [])

        await self.page_repo.delete(page)

        # Re-index remaining pages to close the gap
        remaining = await self.page_repo.list_by_course(course_id)
        for idx, p in enumerate(remaining):
            if p.order_index != idx:
                p.order_index = idx
        await self.session.commit()

        return AssemblyResult(
            proposal_id=context["proposal_id"],
            operation="delete_page",
            course_id=course_id,
            page_id=page_id,
            page_title=page_title,
            page_order=page_order,
            component_count=component_count,
        )

    # ── Private: Helpers ──────────────────────────────────────────

    async def _create_components(
        self,
        page_id: str,
        components: list[dict],
    ) -> None:
        """Create ComponentRecord rows for a page."""
        from app.models.page_component import ComponentRecord

        for idx, comp_data in enumerate(components):
            comp_type = comp_data.get("componentType", "")
            if comp_type not in self.MVP_COMPATIBLE_TYPES:
                raise ComponentTypeValidationError(
                    comp_type,
                    f"Component type '{comp_type}' is not in the MVP compatibility set"
                )

            comp = ComponentRecord(
                page_id=page_id,
                component_type=comp_type,
                order_index=comp_data.get("order", idx),
                data=comp_data.get("data", {}),
                audio_config=comp_data.get("audioConfig"),
                completion_criteria=comp_data.get("completionCriteria"),
                styling=comp_data.get("styling"),
            )
            self.session.add(comp)

    def _get_required_fields(self, component_type: str) -> list[str]:
        """Get the required field names for a component type."""
        mapping = {
            "text-content": ["content"],
            "content-text": ["content"],
            "welcome": ["content"],
            "content-video": ["videoUrl"],
            "video": ["videoUrl"],
            "mcq": ["questions"],
            "quiz": ["questions"],
            "tabs": ["tabs"],
            "accordion": ["panels"],
            "final-assessment": ["questions"],
        }
        return mapping.get(component_type, [])

    def _compute_page_hash(self, page) -> str:
        """Compute a deterministic hash of page state for optimistic locking."""
        import hashlib
        raw = f"{page.page_id}:{page.title}:{page.order_index}:{page.updated_at.isoformat() if page.updated_at else ''}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
```

**New file: `app/services/ai/component_type_resolver.py`**

```python
"""Resolves component type compatibility for AI proposals against the editor.

Queries the component_type_compatibility table and provides lookup methods
for validating AI proposal data against the editor's supported types.
"""

from __future__ import annotations
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.component_type import ComponentTypeCompatibilityRecord

logger = logging.getLogger(__name__)


class ComponentTypeNotRegisteredError(ValueError):
    """Raised when a component type is not found in the compatibility registry."""


class ComponentTypeResolver:
    """Resolves component type compatibility metadata."""

    def __init__(self, db_session: AsyncSession):
        self.session = db_session

    async def is_compatible(self, component_type: str) -> bool:
        """Check if a component type is compatible with the editor and AI proposable."""
        record = await self._get(component_type)
        if not record:
            return False
        return record.editor_support in ("full", "limited") and record.ai_proposable

    async def get_supported_types(self) -> list[dict]:
        """Return all editor-compatible, AI-proposable component types."""
        q = (
            select(ComponentTypeCompatibilityRecord)
            .where(
                ComponentTypeCompatibilityRecord.editor_support.in_(["full", "limited"]),
                ComponentTypeCompatibilityRecord.ai_proposable == True,
            )
            .order_by(ComponentTypeCompatibilityRecord.display_name)
        )
        rows = (await self.session.execute(q)).scalars().all()
        return [r.to_dict() for r in rows]

    async def validate_component(
        self,
        component_type: str,
        data: dict,
    ) -> list[str]:
        """Validate a component's data against its registered requirements.

        Returns a list of validation error messages (empty = valid).
        """
        record = await self._get(component_type)
        if not record:
            return [f"Component type '{component_type}' is not registered"]

        errors = []
        requires_fields = record.requires_fields or []
        for field_name in requires_fields:
            if field_name not in data or data.get(field_name) is None:
                errors.append(f"'{component_type}' requires field '{field_name}'")
        return errors

    async def _get(
        self,
        component_type: str,
    ) -> Optional[ComponentTypeCompatibilityRecord]:
        q = select(ComponentTypeCompatibilityRecord).where(
            ComponentTypeCompatibilityRecord.component_type == component_type
        )
        return (await self.session.execute(q)).scalar_one_or_none()
```

### 2.5 API Contracts

#### POST /api/v1/ai/proposals/{proposalId}/apply — Apply Proposal (Enhanced for Assembly)

This endpoint already exists from US-AI-011/012/013. This epic enhances it to use the `CourseAssembler` service internally and return assembly metadata.

**Request:**
```json
{
  "sessionId": "sess_abc123",
  "userConfirmed": true
}
```

**Response 200 (Create Page):**
```json
{
  "status": "created",
  "proposalId": "prop_001",
  "sessionId": "sess_abc123",
  "courseId": "course_abc123",
  "pageId": "page_new_001",
  "pageTitle": "Understanding Data Types",
  "pageOrder": 3,
  "componentCount": 2,
  "message": "Page 'Understanding Data Types' has been created.",
  "appliedAt": "2026-06-14T10:01:00Z",
  "stateRefreshToken": "abc123def456"
}
```

**Response 200 (Update Page):**
```json
{
  "status": "updated",
  "proposalId": "prop_002",
  "sessionId": "sess_abc123",
  "courseId": "course_abc123",
  "pageId": "page_002",
  "pageTitle": "Introduction to Variables",
  "pageOrder": 1,
  "componentCount": 3,
  "message": "Page 'Introduction to Variables' has been updated.",
  "appliedAt": "2026-06-14T10:02:00Z",
  "stateRefreshToken": "def789ghi012"
}
```

**Response 200 (Delete Page):**
```json
{
  "status": "deleted",
  "proposalId": "prop_003",
  "sessionId": "sess_abc123",
  "courseId": "course_abc123",
  "pageId": "page_003",
  "pageTitle": "Outdated Module",
  "pageOrder": 2,
  "componentCount": 4,
  "message": "Page 'Outdated Module' has been deleted.",
  "appliedAt": "2026-06-14T10:03:00Z"
}
```

**Error Response 422 (Unsupported Component Type):**
```json
{
  "code": "UNSUPPORTED_COMPONENT_TYPE",
  "message": "Component type 'flashcard' is not supported in the editor",
  "field": "components[0].componentType",
  "componentIndex": 0,
  "retryable": true,
  "proposalId": "prop_001"
}
```

#### GET /api/v1/ai/component-types — Get Compatible Component Types

Returns the component type compatibility matrix for the frontend editor.

**Response 200:**
```json
{
  "componentTypes": [
    {
      "componentType": "text-content",
      "displayName": "Text Content",
      "editorSupport": "full",
      "aiProposable": true,
      "scormExportable": true,
      "requiresFields": ["content"],
      "schemaSignature": "a1b2c3d4..."
    }
  ],
  "mvpTypes": ["text-content", "welcome", "content-video", "mcq", "tabs", "accordion", "final-assessment"],
  "total": 7
}
```

#### GET /api/v1/ai/proposals/{proposalId}/validate-assembly — Pre-flight Validation

Validates proposal data against the assembly compatibility matrix without writing.

**Response 200 (Valid):**
```json
{
  "valid": true,
  "errors": [],
  "warnings": [],
  "componentCount": 2,
  "pageTitle": "Understanding Data Types",
  "pageOrder": 3
}
```

**Response 200 (Invalid):**
```json
{
  "valid": false,
  "errors": [
    {
      "code": "UNSUPPORTED_COMPONENT_TYPE",
      "message": "Component type 'flashcard' is not supported in the editor",
      "field": "components[0].componentType",
      "componentIndex": 0
    }
  ],
  "warnings": [
    {
      "code": "NO_COMPONENTS",
      "message": "Page has no components; editor will show an empty page",
      "field": "components"
    }
  ],
  "componentCount": 0,
  "pageTitle": "My Page",
  "pageOrder": 0
}
```

### 2.6 Assembly Repository

**New file: `app/repositories/assembly_repo.py`**

```python
"""Repository for assembly-related operations.

Provides transaction-scoped helpers for the CourseAssembler, keeping
the assembler focused on transformation logic rather than SQL.
"""

from __future__ import annotations
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.page_component import PageRecord, ComponentRecord


class AssemblyRepository:
    """Low-level DB access for assembly operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_max_page_order(self, course_id: str) -> int:
        """Get the highest order_index for pages in a course."""
        q = select(func.coalesce(func.max(PageRecord.order_index), -1)).where(
            PageRecord.course_id == course_id
        )
        return (await self.session.execute(q)).scalar() or 0

    async def get_component_count_for_page(self, page_id: str) -> int:
        """Count components on a page."""
        q = select(func.count()).select_from(ComponentRecord).where(
            ComponentRecord.page_id == page_id
        )
        return (await self.session.execute(q)).scalar() or 0

    async def delete_all_components_for_page(self, page_id: str) -> int:
        """Delete all components for a page (used during update)."""
        from sqlalchemy import delete
        q = delete(ComponentRecord).where(
            ComponentRecord.page_id == page_id
        )
        result = await self.session.execute(q)
        return result.rowcount

    async def get_next_available_order(
        self,
        course_id: str,
        preferred_order: int,
    ) -> int:
        """Get the next available order, preferring the requested position."""
        max_order = await self.get_max_page_order(course_id)
        if preferred_order < 0 or preferred_order > max_order + 1:
            return max_order + 1
        return preferred_order

    async def shift_page_orders(
        self,
        course_id: str,
        from_order: int,
        direction: str = "decrement",
    ) -> None:
        """Shift page order_index values up or down to fill gaps.

        Used after page deletion to close the gap in ordering.
        """
        pages = (
            await self.session.execute(
                select(PageRecord)
                .where(PageRecord.course_id == course_id)
                .order_by(PageRecord.order_index)
            )
        ).scalars().all()

        for idx, page in enumerate(pages):
            page.order_index = idx
```

### 2.7 API Router Changes

**Modify existing file: `app/routers/page_components.py`**

Add a new endpoint for assembly validation. The existing apply endpoint logic is updated in US-AI-011/012/013 to invoke `CourseAssembler`; this epic adds the validation endpoint and the component types listing.

```python
# Add to existing file: app/routers/page_components.py

from app.services.ai.course_assembler import CourseAssembler
from app.services.ai.component_type_resolver import ComponentTypeResolver


@router.get(
    "/ai/component-types",
    summary="Get component types compatible with the editor",
    tags=["AI Assembly"],
)
async def get_ai_compatible_component_types(
    session: AsyncSession = Depends(get_session),
):
    """Return the component type compatibility matrix for AI proposals.

    This endpoint tells the frontend which component types the AI can
    propose and the editor can render. Any type not in this list will
    be rejected at assembly time.
    """
    resolver = ComponentTypeResolver(session)
    types = await resolver.get_supported_types()
    return {
        "componentTypes": types,
        "mvpTypes": sorted(CourseAssembler.MVP_COMPATIBLE_TYPES),
        "total": len(types),
    }


@router.post(
    "/ai/proposals/{proposalId}/validate-assembly",
    summary="Pre-flight validation of a proposal against assembly rules",
    tags=["AI Assembly"],
)
async def validate_proposal_assembly(
    proposalId: str,
    session: AsyncSession = Depends(get_session),
):
    """Validate a proposal's data against the assembly compatibility matrix.

    This is a read-only check. It does not write any data. It validates:
      - Component types exist in the compatibility matrix.
      - Required fields are present for each component type.
      - Page title constraints.

    Returns validation errors and warnings without applying the proposal.
    """
    # Fetch proposal payload from ai_proposals table (US-AI-009)
    from app.repositories.ai_proposal_repo import AIProposalRepository

    proposal_repo = AIProposalRepository(session)
    proposal = await proposal_repo.get(proposalId)
    if not proposal:
        raise HTTPException(status_code=404, detail=f"Proposal '{proposalId}' not found")

    assembler = CourseAssembler(session)
    result = await assembler.validate_payload(proposal.payload)
    return result
```

**Modify existing file: `app/main.py`**

No changes needed — the existing router setup already covers `/ai/component-types` and `/ai/proposals/{proposalId}/validate-assembly` if added to existing routers.

### 2.8 Environment Variables

Add to `.env` and `.env.example`:

```ini
# ===========================================
# Course Assembly Configuration
# ===========================================

# Maximum page title length enforced during assembly
ASSEMBLY_MAX_PAGE_TITLE_LENGTH=200

# Enable assembly validation logging (debug)
ASSEMBLY_VALIDATION_LOG_ENABLED=false

# Default page order when no position is specified
ASSEMBLY_DEFAULT_INSERT_POSITION=end

# Validate component data against schema during assembly (strict mode)
ASSEMBLY_STRICT_SCHEMA_VALIDATION=true
```

---

## 3. Non-Functional Requirements

### 3.1 Performance

| Requirement | Target | Measurement |
|---|---|---|
| Assembly of a single page with 3 components | < 200 ms p95 | End-to-end from DB read to commit |
| Assembly validation (pre-flight, no write) | < 50 ms p95 | Read proposal + validate schema |
| Assembly of a batch of 10 pages | < 1.5 s p95 | Transactional batch |
| Component type compatibility lookup | < 10 ms p95 | Single DB query |
| Deletion + re-index of 50 pages | < 500 ms p95 | Delete + update order_index |
| State refresh via GET /courses/{id} | < 100 ms p95 after assembly | Composite query |

### 3.2 Security

| Requirement | Implementation |
|---|---|
| Proposal-ownership scoping | Assembly verifies `session_context.course_id` matches proposal's course |
| User-ownership scoping | Assembly verifies `session_context.user_id` matches session's owner |
| Optimistic lock on update | Assembly computes page hash and compares to `baseHash` from proposal |
| No SQL injection | All assembly writes go through SQLAlchemy ORM, not raw SQL |
| Component type whitelist | Only types in `MVP_COMPATIBLE_TYPES` are accepted for assembly |
| Delete cascading | `PageRecord` delete cascades to `ComponentRecord` via FK constraint |
| Assembly idempotency | `PROPOSAL_ALREADY_APPLIED` check prevents double-assembly |
| Transaction isolation | Assembly uses a single DB transaction; rollback on any error |

### 3.3 Data Integrity

| Requirement | Implementation |
|---|---|
| Ordered page indices | `order_index` is sequential starting from 0 after every deletion/reorder |
| Component order within page | `order_index` is sequential starting from 0 after every assembly |
| Cascade on page delete | FK `ON DELETE CASCADE` removes all components |
| No orphan components | Components are always created within a page FK scope |
| Title truncation safety | Page title truncated to 200 chars at assembly time, not at DB level |
| Timestamp accuracy | `updated_at` is set to `datetime.utcnow()` on every assembly write |
| Rollback on partial failure | If any component create fails, the entire assembly transaction rolls back |

### 3.4 Availability

| Requirement | Implementation |
|---|---|
| Assembly failure does not corrupt course | Single transaction; rollback on error preserves previous state |
| Concurrent proposal applies are serialized | DB row-level locking on the proposal prevents concurrent apply |
| Component type registry cached | In-memory cache of compatibility matrix with 5-minute TTL |
| Editor unaffected by assembly failure | Assembly errors return a 422/409; editor state is unchanged |
| Graceful degradation for unknown types | Unknown component types produce a clear validation error, not a 500 |

### 3.5 Observability

| Metric | Type | Tags |
|---|---|---|
| `assembly_operations_total` | Counter | operation, status (success/error) |
| `assembly_duration_seconds` | Histogram | operation, component_count |
| `assembly_component_types_total` | Counter | component_type, operation |
| `assembly_validation_errors_total` | Counter | error_code |
| `assembly_optimistic_lock_conflicts_total` | Counter | page_id |
| `assembly_component_count_per_page` | Histogram | operation |
| `assembly_batch_size` | Histogram | operation |

---

## 4. Current State

### 4.1 What Exists Today

1. **PageRecord and ComponentRecord ORM models**: `app/models/page_component.py` with full CRUD via `PageRepository` and `ComponentRepository` in `app/repositories/page_component_repo.py`. These are the target entities for assembly writes.

2. **Course endpoint**: `GET /api/v1/courses/{courseId}` in `app/routers/courses.py` returns composite course + pages + components. This is the state refresh endpoint the frontend calls after assembly.

3. **Proposal framework (US-AI-009)**: The `ai_proposals` table design in US-AI-009 provides the proposal storage that the assembler reads as input. Proposal payload contains the `operation`, `pageSpec`, and `components[]` fields.

4. **Proposal lifecycle (US-AI-011/012/013)**: Create, update, and delete proposal endpoints exist with status management (`PENDING_REVIEW`, `APPLIED`, etc.).

5. **Frontend AI integration (US-AI-024)**: `ProposalCard` component renders proposals with Apply/Reject buttons. On apply success, it refreshes course state via `GET /api/v1/courses/{courseId}`.

6. **Component Type registry**: `app/models/component_type.py` defines the `ComponentType` ORM model with schema validation.

7. **Course validation endpoint**: `POST /api/v1/courses/validate` in `app/routers/courses.py` validates page structure. The assembler should produce data that passes this validation.

8. **Existing page editor**: Frontend has an existing course editor that consumes the `GET /api/v1/courses/{courseId}` response shape and renders pages/components for editing.

### 4.2 What Is Missing

1. `app/services/ai/course_assembler.py` — the main assembly service with `assemble()` and `validate_payload()` methods.
2. `app/services/ai/component_type_resolver.py` — resolves component type compatibility against the registry.
3. `component_type_compatibility` table with ORM model and Alembic migration — stores the compatibility matrix.
4. `app/repositories/assembly_repo.py` — repository helpers for assembly operations (max order, shift orders, etc.).
5. `app/routers/assembly_dtos.py` — Pydantic DTOs for assembly result, errors, and batch results.
6. `GET /api/v1/ai/component-types` endpoint — returns compatible component types for the frontend.
7. `POST /api/v1/ai/proposals/{proposalId}/validate-assembly` endpoint — pre-flight validation.
8. Enhanced proposal apply endpoint logic (in US-AI-011/012/013) to call `CourseAssembler.assemble()`.
9. Component type seed data in `component_type_compatibility` table for all MVP types.
10. Unit tests for `CourseAssembler` (all three operations, all validation paths, error cases).
11. Integration tests for assembly endpoints with mocked proposal data.
12. E2E test verifying assembly -> state refresh -> editor renders correctly.
13. Alembic migration for `component_type_compatibility` table.

### 4.3 Dependencies on Earlier Stories

| Story | Dependency |
|---|---|
| US-AI-004 | AI persistence (courses, pages, components tables exist) |
| US-AI-009 | Proposal payload structure (the input to CourseAssembler) |
| US-AI-011 | Create page proposal endpoint (calls CourseAssembler on apply) |
| US-AI-012 | Update page proposal endpoint (calls CourseAssembler on apply) |
| US-AI-013 | Delete page proposal endpoint (calls CourseAssembler on apply) |
| US-AI-023 | Chat endpoint generates proposals that this assembler processes |
| US-AI-024 | Frontend proposal card calls apply; on success, refreshes course state |
| US-AI-029 | Batch proposal operations require batch assembly pathway |

---

## 5. Expansion Points

### 5.1 Batch Assembly (US-AI-029)

The current `CourseAssembler.assemble()` operates on a single proposal. For batch operations (file ingestion, multi-page chat edits), a `batch_assemble()` method should be added that:
1. Reads all proposals in the batch.
2. Pre-validates every proposal via `validate_payload()`.
3. Opens a single transaction.
4. Calls `_assemble_*` for each proposal.
5. If any fails, rolls back the entire batch.
6. Returns `AssemblyBatchResult` with per-proposal results.

### 5.2 Concurrent Edit Conflict Resolution (Post-MVP)

When two users (or an AI + a user) edit the same page concurrently, the current optimistic lock (`baseHash`) detects the conflict but does not resolve it. Post-MVP:
- Store the previous page state as a JSON snapshot before assembly.
- On conflict, return a three-way diff (current, proposed, previous).
- Allow the LLM to re-propose with the conflicts resolved.

### 5.3 Undo/Redo for Assembly (Post-MVP)

Each assembly creates a reversal proposal that can be applied to undo:
- `create_page` reversal: `delete_page` with the created pageId.
- `update_page` reversal: `update_page` with the previous component state.
- `delete_page` reversal: `create_page` with the deleted page's data.

This requires storing the previous state snapshot in the assembly result (expansion tracked in US-AI-040).

### 5.4 Component Type Dynamic Resolution (Post-MVP)

Currently the compatibility matrix is seeded with known types and enforced server-side. Post-MVP, when new template types are registered in the `template_definitions` table, they should automatically reflect in the compatibility matrix if they meet minimum criteria (has `render_config`, has `field_schema`). This enables AI to propose content using dynamically registered templates.

### 5.5 Assembly Dry-Run with Preview (Post-MVP)

Instead of validating and committing in separate steps, a dry-run assembly would:
1. Perform the full assembly in a savepoint (nested transaction).
2. Return the resulting page data (as if it were persisted).
3. Generate a visual preview URL for the assembled page.
4. Roll back the savepoint.
5. On user confirmation, replay the assembly without validation.

This provides a "preview before apply" experience for AI-generated pages.

### 5.6 Page Order Auto-Shift on Batch Insert (Post-MVP)

When inserting multiple pages at a specific position, the order indices of existing pages should shift to accommodate the new pages without gaps. This requires an `insert_at_position` parameter in the assembly payload and a batch reindex operation.

---

## 6. Validation and Test Scenarios

### 6.1 Unit Tests (CourseAssembler Service)

```python
# File: tests/test_course_assembler.py

class TestAssembleCreatePage:
    async def test_create_page_with_components_happy_path(
        self, db_session, sample_course, sample_session_context
    ):
        """A create_page assembly creates a PageRecord with ComponentRecord rows."""
        assembler = CourseAssembler(db_session)
        payload = {
            "operation": "create_page",
            "pageSpec": {
                "title": "Understanding Data Types",
                "layout": {"templateId": "text-content", "customizations": {}},
                "theme": None,
                "completionConfig": None,
            },
            "components": [
                {
                    "componentType": "text-content",
                    "data": {"content": "Data types define the kind of values..."},
                    "order": 0,
                },
            ],
        }
        result = await assembler.assemble(sample_session_context, payload)
        assert result.operation == "create_page"
        assert result.page_id is not None
        assert result.component_count == 1
        # Verify in DB
        page = await PageRepository(db_session).get(result.page_id)
        assert page is not None
        assert page.title == "Understanding Data Types"
        assert len(page.components) == 1

    async def test_create_page_with_multiple_components(
        self, db_session, sample_course, sample_session_context
    ):
        """A page with 3 components creates 3 ComponentRecord rows with correct order."""
        assembler = CourseAssembler(db_session)
        payload = {
            "operation": "create_page",
            "pageSpec": {"title": "Mixed Content Page"},
            "components": [
                {"componentType": "text-content", "data": {"content": "Intro"}},
                {"componentType": "tabs", "data": {"tabs": [{"title": "Tab 1", "content": "..."}]}},
                {"componentType": "accordion", "data": {"panels": [{"title": "Panel 1", "content": "..."}]}},
            ],
        }
        result = await assembler.assemble(sample_session_context, payload)
        page = await PageRepository(db_session).get(result.page_id)
        assert len(page.components) == 3
        # Verify order
        for i, comp in enumerate(page.components):
            assert comp.order_index == i

    async def test_create_page_rejects_unsupported_component_type(
        self, db_session, sample_course, sample_session_context
    ):
        """Flashcard type raises ComponentTypeValidationError."""
        assembler = CourseAssembler(db_session)
        payload = {
            "operation": "create_page",
            "pageSpec": {"title": "Flashcard Page"},
            "components": [
                {"componentType": "flashcard", "data": {"cards": []}},
            ],
        }
        with pytest.raises(ComponentTypeValidationError) as exc:
            await assembler.assemble(sample_session_context, payload)
        assert "flashcard" in str(exc.value)

    async def test_create_page_auto_assigns_page_order(
        self, db_session, sample_course_with_pages, sample_session_context
    ):
        """If no pageOrder specified, new page goes at the end."""
        assembler = CourseAssembler(db_session)
        payload = {
            "operation": "create_page",
            "pageSpec": {"title": "New Last Page"},
            "components": [{"componentType": "text-content", "data": {"content": "..."}}],
        }
        result = await assembler.assemble(sample_session_context, payload)
        assert result.page_order == 2  # Assuming 2 existing pages

    async def test_create_page_title_truncated_at_200_chars(
        self, db_session, sample_course, sample_session_context
    ):
        """A title exceeding 200 chars is truncated, not rejected."""
        assembler = CourseAssembler(db_session)
        long_title = "A" * 300
        payload = {
            "operation": "create_page",
            "pageSpec": {"title": long_title},
            "components": [{"componentType": "text-content", "data": {"content": "..."}}],
        }
        result = await assembler.assemble(sample_session_context, payload)
        page = await PageRepository(db_session).get(result.page_id)
        assert len(page.title) == 200


class TestAssembleUpdatePage:
    async def test_update_page_replaces_components(
        self, db_session, sample_course_with_pages, sample_session_context
    ):
        """update_page replaces all components with the new set."""
        existing_pages = await PageRepository(db_session).list_by_course(sample_session_context["course_id"])
        page_id = existing_pages[0].page_id
        old_component_count = len(existing_pages[0].components or [])

        assembler = CourseAssembler(db_session)
        payload = {
            "operation": "update_page",
            "pageId": page_id,
            "pageSpec": {"title": "Updated Title"},
            "components": [
                {"componentType": "text-content", "data": {"content": "New content"}},
            ],
        }
        result = await assembler.assemble(sample_session_context, payload)
        assert result.component_count == 1
        page = await PageRepository(db_session).get(page_id)
        assert page.title == "Updated Title"
        assert len(page.components) == 1
        assert page.components[0].component_type == "text-content"

    async def test_update_page_optimistic_lock_conflict(
        self, db_session, sample_course_with_pages, sample_session_context
    ):
        """When baseHash does not match current state, AssemblyConflictError is raised."""
        existing_pages = await PageRepository(db_session).list_by_course(sample_session_context["course_id"])
        page_id = existing_pages[0].page_id

        assembler = CourseAssembler(db_session)
        payload = {
            "operation": "update_page",
            "pageId": page_id,
            "pageSpec": {"title": "Conflicting Update"},
            "components": [{"componentType": "text-content", "data": {"content": "..."}}],
            "baseHash": "wrong_hash_value",
        }
        with pytest.raises(AssemblyConflictError):
            await assembler.assemble(sample_session_context, payload)

    async def test_update_page_nonexistent_page_raises_error(
        self, db_session, sample_course, sample_session_context
    ):
        """Updating a page that does not exist raises ValueError."""
        assembler = CourseAssembler(db_session)
        payload = {
            "operation": "update_page",
            "pageId": "nonexistent_page_id",
            "pageSpec": {"title": "Ghost Page"},
            "components": [{"componentType": "text-content", "data": {"content": "..."}}],
        }
        with pytest.raises(ValueError):
            await assembler.assemble(sample_session_context, payload)


class TestAssembleDeletePage:
    async def test_delete_page_cascades_to_components(
        self, db_session, sample_course_with_pages, sample_session_context
    ):
        """Deleting a page removes its components (verified by FK cascade)."""
        existing_pages = await PageRepository(db_session).list_by_course(sample_session_context["course_id"])
        page_id = existing_pages[0].page_id

        assembler = CourseAssembler(db_session)
        payload = {
            "operation": "delete_page",
            "pageId": page_id,
        }
        result = await assembler.assemble(sample_session_context, payload)
        assert result.operation == "delete_page"
        # Verify deletion
        page = await PageRepository(db_session).get(page_id)
        assert page is None

    async def test_delete_page_reindexes_remaining_pages(
        self, db_session, sample_course_with_pages, sample_session_context
    ):
        """After deletion, remaining pages have sequential order_index starting from 0."""
        course_id = sample_session_context["course_id"]
        repo = PageRepository(db_session)
        all_pages = await repo.list_by_course(course_id)
        page_count = len(all_pages)

        assembler = CourseAssembler(db_session)
        payload = {"operation": "delete_page", "pageId": all_pages[0].page_id}
        await assembler.assemble(sample_session_context, payload)

        remaining = await repo.list_by_course(course_id)
        assert len(remaining) == page_count - 1
        for i, page in enumerate(remaining):
            assert page.order_index == i

    async def test_delete_last_page_returns_empty_course(
        self, db_session, sample_course_with_one_page, sample_session_context
    ):
        """Deleting the last page in a course leaves the course empty but valid."""
        existing = await PageRepository(db_session).list_by_course(
            sample_session_context["course_id"]
        )
        assembler = CourseAssembler(db_session)
        payload = {"operation": "delete_page", "pageId": existing[0].page_id}
        result = await assembler.assemble(sample_session_context, payload)
        remaining = await PageRepository(db_session).list_by_course(
            sample_session_context["course_id"]
        )
        assert len(remaining) == 0


class TestValidatePayload:
    async def test_valid_payload_returns_no_errors(self):
        """A payload with valid types and fields passes validation."""
        assembler = CourseAssembler(None)  # No DB needed for schema-only checks
        payload = {
            "operation": "create_page",
            "pageSpec": {"title": "Valid Page"},
            "components": [{"componentType": "text-content", "data": {"content": "Hello"}}],
        }
        result = await assembler.validate_payload(payload)
        assert result["valid"] is True
        assert len(result["errors"]) == 0

    async def test_unsupported_component_type_returns_error(self):
        """Flashcard is rejected by validation."""
        assembler = CourseAssembler(None)
        payload = {
            "operation": "create_page",
            "pageSpec": {"title": "Bad Component"},
            "components": [{"componentType": "flashcard", "data": {"cards": []}}],
        }
        result = await assembler.validate_payload(payload)
        assert result["valid"] is False
        assert any(e["code"] == "UNSUPPORTED_COMPONENT_TYPE" for e in result["errors"])

    async def test_missing_required_field_returns_error(self):
        """Text-content without 'content' field is rejected."""
        assembler = CourseAssembler(None)
        payload = {
            "operation": "create_page",
            "pageSpec": {"title": "Missing Data"},
            "components": [{"componentType": "text-content", "data": {}}],
        }
        result = await assembler.validate_payload(payload)
        assert result["valid"] is False
        assert any(e["code"] == "MISSING_REQUIRED_FIELD" for e in result["errors"])

    async def test_empty_components_triggers_warning(self):
        """A page with no components produces a warning, not an error."""
        assembler = CourseAssembler(None)
        payload = {
            "operation": "create_page",
            "pageSpec": {"title": "Empty Page"},
            "components": [],
        }
        result = await assembler.validate_payload(payload)
        assert result["valid"] is True  # Empty is valid but warned
        assert any(w["code"] == "NO_COMPONENTS" for w in result["warnings"])

    async def test_delete_operation_requires_page_id(self):
        """Delete operation without pageId fails validation."""
        assembler = CourseAssembler(None)
        payload = {"operation": "delete_page"}
        result = await assembler.validate_payload(payload)
        assert result["valid"] is False
        assert any(e["code"] == "MISSING_PAGE_ID" for e in result["errors"])

    async def test_page_title_too_long_returns_error(self):
        """A title exceeding the max length is rejected."""
        assembler = CourseAssembler(None)
        payload = {
            "operation": "create_page",
            "pageSpec": {"title": "A" * 201},
            "components": [{"componentType": "text-content", "data": {"content": "..."}}],
        }
        result = await assembler.validate_payload(payload)
        assert result["valid"] is False
        assert any(e["code"] == "PAGE_TITLE_TOO_LONG" for e in result["errors"])


class TestComponentTypeResolver:
    async def test_is_compatible_returns_true_for_mvp_type(
        self, db_session, seeded_compatibility_types
    ):
        """Text-content is recognized as compatible."""
        resolver = ComponentTypeResolver(db_session)
        assert await resolver.is_compatible("text-content") is True

    async def test_is_compatible_returns_false_for_unsupported_type(
        self, db_session, seeded_compatibility_types
    ):
        """Flashcard is not compatible."""
        resolver = ComponentTypeResolver(db_session)
        assert await resolver.is_compatible("flashcard") is False

    async def test_get_supported_types_returns_mvp_types(
        self, db_session, seeded_compatibility_types
    ):
        """get_supported_types returns the expected MVP subset."""
        resolver = ComponentTypeResolver(db_session)
        types = await resolver.get_supported_types()
        type_keys = {t["componentType"] for t in types}
        assert "text-content" in type_keys
        assert "welcome" in type_keys
        assert "mcq" in type_keys
        assert "flashcard" not in type_keys

    async def test_validate_component_valid_data(self, db_session, seeded_compatibility_types):
        """Valid component data returns no errors."""
        resolver = ComponentTypeResolver(db_session)
        errors = await resolver.validate_component("text-content", {"content": "Hello"})
        assert len(errors) == 0

    async def test_validate_component_missing_required_field(
        self, db_session, seeded_compatibility_types
    ):
        """Missing required field returns an error."""
        resolver = ComponentTypeResolver(db_session)
        errors = await resolver.validate_component("text-content", {})
        assert len(errors) == 1
        assert "content" in errors[0]
```

### 6.2 Integration Tests (API Layer)

```python
# File: tests/test_course_assembly_api.py

class TestAssemblyAPI:
    async def test_validate_assembly_valid_proposal(
        self, async_client, sample_ai_session, sample_valid_proposal, monkeypatch
    ):
        """POST /ai/proposals/{proposalId}/validate-assembly returns valid=True."""
        # Arrange: create a proposal with valid data
        response = await async_client.post(
            f"/api/v1/ai/proposals/{sample_valid_proposal.proposal_id}/validate-assembly"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert len(data["errors"]) == 0

    async def test_validate_assembly_invalid_proposal_returns_errors(
        self, async_client, sample_ai_session, sample_invalid_proposal, monkeypatch
    ):
        """A proposal with unsupported type returns UNSUPPORTED_COMPONENT_TYPE."""
        response = await async_client.post(
            f"/api/v1/ai/proposals/{sample_invalid_proposal.proposal_id}/validate-assembly"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        error_codes = [e["code"] for e in data["errors"]]
        assert "UNSUPPORTED_COMPONENT_TYPE" in error_codes

    async def test_validate_assembly_nonexistent_proposal_returns_404(
        self, async_client
    ):
        """A non-existent proposal ID returns 404."""
        response = await async_client.post(
            "/api/v1/ai/proposals/nonexistent_id/validate-assembly"
        )
        assert response.status_code == 404

    async def test_component_types_endpoint_returns_list(
        self, async_client, seeded_compatibility_types
    ):
        """GET /ai/component-types returns the compatibility matrix."""
        response = await async_client.get("/api/v1/ai/component-types")
        assert response.status_code == 200
        data = response.json()
        assert "componentTypes" in data
        assert "mvpTypes" in data
        assert data["total"] >= 7
        assert data["mvpTypes"] == sorted(CourseAssembler.MVP_COMPATIBLE_TYPES)

    async def test_assembly_apply_creates_page_in_db(
        self, async_client, sample_ai_session, sample_apply_request, monkeypatch
    ):
        """Applying a create_page proposal results in a new PageRecord."""
        response = await async_client.post(
            f"/api/v1/ai/proposals/prop_001/apply",
            json=sample_apply_request,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "created"
        assert data["pageId"] is not None
        assert data["componentCount"] > 0

    async def test_assembly_state_refresh_returns_updated_data(
        self, async_client, sample_ai_session_with_applied_proposal
    ):
        """After assembly, GET /courses/{courseId} includes the new page."""
        course_id = sample_ai_session_with_applied_proposal["course_id"]
        response = await async_client.get(f"/api/v1/courses/{course_id}")
        assert response.status_code == 200
        data = response.json()
        assert "pages" in data
        assert len(data["pages"]) > 0

    async def test_already_applied_proposal_returns_409(
        self, async_client, sample_ai_session_with_applied_proposal
    ):
        """Applying an already-applied proposal returns 409."""
        proposal_id = sample_ai_session_with_applied_proposal["applied_proposal_id"]
        response = await async_client.post(
            f"/api/v1/ai/proposals/{proposal_id}/apply",
            json={"sessionId": "sess_abc", "userConfirmed": True},
        )
        assert response.status_code == 409

    async def test_assembly_with_unsupported_type_returns_422(
        self, async_client, sample_ai_session, sample_unsupported_proposal, monkeypatch
    ):
        """Applying a proposal with unsupported component type returns 422."""
        response = await async_client.post(
            f"/api/v1/ai/proposals/{sample_unsupported_proposal.proposal_id}/apply",
            json={"sessionId": "sess_abc", "userConfirmed": True},
        )
        assert response.status_code == 422
        data = response.json()
        assert data["code"] == "UNSUPPORTED_COMPONENT_TYPE"
```

### 6.3 E2E Scenarios

**Scenario 1: AI creates a page -> proposal -> apply -> editor refreshes**
1. AI session is active. User types: "Create a welcome page called 'Getting Started'."
2. Chat endpoint returns a create_page proposal with `pageSpec.title = "Getting Started"`, `componentType = "welcome"`, `data.content = "..."`.
3. Frontend renders ProposalCard with Apply button.
4. User clicks Apply. Frontend calls `POST /api/v1/ai/proposals/{id}/apply`.
5. Server runs `CourseAssembler.assemble()`:
   - Creates `PageRecord` with title "Getting Started", order = latest + 1.
   - Creates `ComponentRecord` with `component_type = "welcome"`, `data = {"content": "..."}`.
   - Commits transaction. Proposal status = `APPLIED`.
6. Response returns `{status: "created", pageId: "page_new_001", componentCount: 1}`.
7. Frontend calls `GET /api/v1/courses/{courseId}` to refresh state.
8. Course response includes the new page in `pages[]` with nested components.
9. Editor re-renders page list showing "Getting Started" at the end.
10. User clicks the new page. Editor opens it with the welcome content displayed.
11. User can edit the title, add components, reorder — all existing editor controls work.

**Scenario 2: AI updates an existing page -> proposal -> apply -> editor refreshes**
1. User types: "Update the 'Introduction' page to use a tabs layout with 3 tabs."
2. Chat endpoint returns an update_page proposal with `pageId = "page_002"`, `pageSpec.title = "Introduction"`, 3 tab components.
3. User applies. Server assembles: deletes existing components, creates 3 new `ComponentRecord` rows with type "tabs".
4. Editor refreshes. The 'Introduction' page now shows 3 tabs.
5. User can edit individual tab content in the editor.

**Scenario 3: AI deletes a page -> proposal with confirmation -> confirm -> editor refreshes**
1. User types: "Delete the 'Outdated Module' page."
2. Chat returns a delete_page proposal. ProposalCard shows "Review & Confirm" button.
3. User clicks "Review & Confirm". ConfirmationModal opens.
4. User types "DELETE", clicks confirm. Frontend calls confirmation endpoint.
5. Server runs `CourseAssembler._assemble_delete()`:
   - Deletes `PageRecord` (cascades to components).
   - Re-indexes remaining pages.
   - Commits transaction.
6. Editor refreshes. "Outdated Module" is gone from page list.
7. Remaining pages have sequential order (0, 1, 2, ...).

**Scenario 4: AI proposes unsupported component type -> validation error -> re-propose**
1. User types: "Add a flashcard page."
2. Chat returns a proposal with `componentType = "flashcard"`.
3. Frontend calls `POST /api/v1/ai/proposals/{id}/validate-assembly`.
4. Response: `{valid: false, errors: [{code: "UNSUPPORTED_COMPONENT_TYPE", ...}]}`.
5. ProposalCard shows red error badge. Apply button is disabled.
6. User types: "Use a text-content page instead."
7. New proposal created with `componentType = "text-content"`. Validation passes. Apply enabled.

**Scenario 5: Concurrent edit conflict during assembly**
1. User A creates a proposal to update page "Introduction".
2. Meanwhile, User B manually edits the same page via the editor.
3. User A clicks Apply. Server detects `baseHash` mismatch during assembly.
4. Assembly returns 409 with `code = "PAGE_CONCURRENTLY_MODIFIED"`.
5. Frontend shows inline error: "This page was modified since the proposal. Please re-propose."
6. User A can trigger AI to re-propose with updated context.

**Scenario 6: Batch assembly from file ingestion**
1. User uploads a PDF. File ingestion creates 5 page proposals as a batch.
2. User reviews the page breakdown, clicks "Confirm & Create".
3. Server calls batch assembly:
   - Validates all 5 proposals. One has an unsupported component type.
   - Returns error for the failing page; 4 pages pass.
4. User removes the failing page, confirms remaining 4.
5. Batch assembly creates 4 pages in a single transaction.
6. Editor refreshes with 4 new pages at the end of the course.

---

## 7. Definition of Done

### 7.1 Code Complete

- [ ] `app/services/ai/course_assembler.py` — `CourseAssembler` class with `assemble()`, `validate_payload()`, and private `_assemble_*` methods.
- [ ] `app/services/ai/component_type_resolver.py` — `ComponentTypeResolver` class with `is_compatible()`, `get_supported_types()`, `validate_component()`.
- [ ] `app/models/component_type.py` — `ComponentTypeCompatibilityRecord` ORM model.
- [ ] Alembic migration script creating `component_type_compatibility` table.
- [ ] Seed data for `component_type_compatibility` table (all MVP types).
- [ ] `app/repositories/assembly_repo.py` — `AssemblyRepository` with order management and component count helpers.
- [ ] `app/routers/assembly_dtos.py` — `AssemblyResult`, `AssemblyError`, `AssemblyValidationResult`, `AssemblyBatchResult`, `StateRefreshResponse` DTOs.
- [ ] `GET /api/v1/ai/component-types` endpoint in appropriate router.
- [ ] `POST /api/v1/ai/proposals/{proposalId}/validate-assembly` endpoint.
- [ ] Enhance `POST /api/v1/ai/proposals/{proposalId}/apply` to call `CourseAssembler.assemble()` (in US-AI-011/012/013).
- [ ] Registration of `component_type_compatibility` table in `app/models/__init__.py`.
- [ ] No changes to existing editor components or routes (non-regression verified).
- [ ] Environment variables documented in `.env.example`.

### 7.2 Tests Pass

- [ ] All `CourseAssembler` unit tests pass (create, update, delete, validation — 18+ tests).
- [ ] All `ComponentTypeResolver` unit tests pass (compatibility checks — 5+ tests).
- [ ] All integration tests for assembly validation endpoint pass (3+ tests).
- [ ] All integration tests for component types endpoint pass (1+ tests).
- [ ] All existing course CRUD tests pass (regression: assembly does not break manual authoring).
- [ ] All existing page/component API tests pass (regression).
- [ ] Test coverage >= 85% for `app/services/ai/course_assembler.py`.
- [ ] Test coverage >= 80% for `app/services/ai/component_type_resolver.py`.

### 7.3 Manual Authoring Preservation

- [ ] Creating a page manually (via `POST /courses/{courseId}/pages`) still works unchanged.
- [ ] Editing a page manually (via `PATCH /courses/{courseId}/pages/{pageId}`) still works unchanged.
- [ ] Deleting a page manually (via `DELETE /courses/{courseId}/pages/{pageId}`) still works unchanged.
- [ ] Reordering pages manually still works unchanged.
- [ ] Component CRUD (create/edit/delete/reorder) still works unchanged.
- [ ] Course export still works unchanged.
- [ ] Course preview still works unchanged.
- [ ] On `GET /api/v1/courses/{courseId}`, AI-assembled pages are indistinguishable from manual pages.

### 7.4 Security

- [ ] Assembly verifies proposal belongs to session's course (permission check).
- [ ] Assembly verifies session belongs to the authenticated user.
- [ ] Optimistic lock hash prevents overwriting concurrent manual edits.
- [ ] Component type whitelist prevents unknown type injection.
- [ ] Page title truncated to 200 chars (no DB-level overflow).
- [ ] Transaction rolls back on any assembly error (no partial writes).
- [ ] Proposal status changes to `APPLIED` only after successful assembly commit.

### 7.5 Operational Readiness

- [ ] Assembly validation can be used as a standalone pre-flight check (no side effects).
- [ ] Assembly errors are logged with structured context (proposalId, operation, pageId).
- [ ] Component type compatibility matrix is seeded via Alembic migration (not manual).
- [ ] Assembly performance meets targets (< 200 ms for single page, < 1.5 s for batch of 10).
- [ ] Failed assembly leaves the course in its previous state (transaction rollback).
- [ ] Concurrent assembly attempts on the same proposal are serialized by DB row lock.

### 7.6 Documentation

- [ ] Data transformation mapping documented in section 1.5 (proposal field -> editor state).
- [ ] Component type compatibility matrix documented in section 1.6.
- [ ] Error codes and conditions documented in section 1.8.
- [ ] `app/services/ai/course_assembler.py` has module-level docstring with usage example.
- [ ] `app/services/ai/component_type_resolver.py` has module-level docstring.
- [ ] Environment variables documented in `docs/DEPLOYMENT.md` or `.env.example`.

---

## 8. Tasks

### Task 1: Create Alembic Migration for Component Type Compatibility Table

**Files to create:**
- `alembic/versions/20260615_0001_add_component_type_compatibility.py`

**Acceptance:**
- Migration creates `component_type_compatibility` table with all columns and constraints.
- Migration seeds initial data for all MVP component types (text-content, welcome, content-video, mcq, tabs, accordion, final-assessment).
- Migration is reversible (downgrade drops the table).
- Run `alembic upgrade head` succeeds without errors.

**Effort:** 1 hour
**Dependencies:** None (standalone table)

---

### Task 2: Implement ComponentTypeCompatibilityRecord ORM Model

**Files to create/modify:**
- `app/models/component_type.py` (modify if exists, or create)
- `app/models/__init__.py` (add import)

**Acceptance:**
- ORM model maps to `component_type_compatibility` table.
- All fields match DDL: `component_type`, `display_name`, `editor_support`, `ai_proposable`, `scorm_exportable`, `schema_signature`, `min_components`, `max_components`, `requires_fields`, `incompatible_with`, `notes`, `created_at`, `updated_at`.
- `to_dict()` method returns all fields in snake_case.
- Model is registered in `app/models/__init__.py`.

**Effort:** 1 hour
**Dependencies:** Task 1 (migration)

---

### Task 3: Implement ComponentTypeResolver Service

**File to create:**
- `app/services/ai/component_type_resolver.py`

**Acceptance:**
- `is_compatible(component_type) -> bool` returns True if editor_support in ("full", "limited") and ai_proposable is True.
- `get_supported_types() -> list[dict]` returns all compatible types ordered by display_name.
- `validate_component(component_type, data) -> list[str]` validates data fields against `requires_fields`.
- All methods handle non-existent component types gracefully (return False / empty list).
- Unit tests cover all methods with seeded data.

**Effort:** 2 hours
**Dependencies:** Task 2 (ORM model)

---

### Task 4: Implement CourseAssembler Service

**File to create:**
- `app/services/ai/course_assembler.py`

**Acceptance:**
- `assemble(session_context, proposal_payload) -> AssemblyResult`:
  - Create: creates PageRecord + ComponentRecord rows with correct order, layout, theme, completion config.
  - Update: updates PageRecord fields, replaces all components, checks optimistic lock hash.
  - Delete: deletes PageRecord, re-indexes remaining pages.
  - Unknown operation raises ValueError.
- `validate_payload(proposal_payload) -> dict`:
  - Checks operation type.
  - Validates title length and presence.
  - Validates component types against MVP_COMPATIBLE_TYPES.
  - Validates required data fields per type.
  - Returns errors and warnings separately.
- ComponentTypeValidationError raised for unsupported types during assembly.
- AssemblyConflictError raised on optimistic lock mismatch.
- Page title truncated to 200 chars.
- All operations are idempotent at the DB level (same data written twice = same state).
- Full unit test coverage (create, update, delete, validation, error cases).

**Effort:** 6 hours
**Dependencies:** Task 3 (ComponentTypeResolver), Task 5 (AssemblyRepository)

---

### Task 5: Implement AssemblyRepository

**File to create:**
- `app/repositories/assembly_repo.py`

**Acceptance:**
- `get_max_page_order(course_id) -> int` returns highest order_index.
- `get_component_count_for_page(page_id) -> int` returns component count.
- `delete_all_components_for_page(page_id) -> int` bulk-deletes components.
- `shift_page_orders(course_id)` re-indexes pages to sequential order starting from 0.
- All methods use async SQLAlchemy, no raw SQL.

**Effort:** 1.5 hours
**Dependencies:** Task 1 (table exists), existing `PageRepository`/`ComponentRepository`

---

### Task 6: Create Pydantic DTOs for Assembly

**File to create:**
- `app/routers/assembly_dtos.py`

**Acceptance:**
- `AssemblyResult` with `proposal_id`, `session_id`, `course_id`, `operation`, `page_id`, `page_title`, `page_order`, `component_count`, `applied_at`, `state_refresh_token`.
- `AssemblyError` with `code`, `message`, `field`, `component_index`, `retryable`.
- `AssemblyValidationResult` with `valid`, `errors`, `warnings`, `component_count`, `page_title`, `page_order`.
- `AssemblyBatchResult` with `batch_id`, `results`, `errors`, `all_succeeded`.
- All DTOs have `model_config = {"from_attributes": True}` for ORM compatibility if needed.

**Effort:** 45 minutes
**Dependencies:** None

---

### Task 7: Implement Component Types Endpoint

**Files to modify:**
- `app/routers/page_components.py` or `app/routers/courses.py`

**Acceptance:**
- `GET /api/v1/ai/component-types` returns:
  - `componentTypes`: full list from ComponentTypeResolver.
  - `mvpTypes`: sorted list from CourseAssembler.MVP_COMPATIBLE_TYPES.
  - `total`: count.
- Endpoint is gated by `ai_authoring_enabled` feature flag.
- Response time < 50 ms.

**Effort:** 1 hour
**Dependencies:** Task 3 (ComponentTypeResolver)

---

### Task 8: Implement Assembly Validation Endpoint

**Files to modify:**
- `app/routers/page_components.py` or `app/routers/courses.py`

**Acceptance:**
- `POST /api/v1/ai/proposals/{proposalId}/validate-assembly`:
  - Fetches proposal payload from `ai_proposals` table.
  - Calls `CourseAssembler.validate_payload()`.
  - Returns validation result (valid, errors, warnings).
  - Does NOT write any data.
- Returns 404 for non-existent proposal.
- Endpoint is gated by `ai_authoring_enabled` feature flag.
- Integration test covers valid, invalid, and not-found cases.

**Effort:** 1.5 hours
**Dependencies:** Task 4 (CourseAssembler), Task 6 (DTOs), US-AI-009 (proposal table)

---

### Task 9: Integrate CourseAssembler into Proposal Apply Endpoint

**Files to modify:**
- `app/routers/proposals.py` or equivalent (from US-AI-011/012/013)

**Acceptance:**
- When a proposal with operation `create_page`, `update_page`, or `delete_page` is applied:
  1. Validate the proposal is in `PENDING_REVIEW` status.
  2. Call `CourseAssembler.assemble()` with session context and proposal payload.
  3. On success: update proposal status to `APPLIED`, return assembly result.
  4. On `ComponentTypeValidationError`: return 422 with error details.
  5. On `AssemblyConflictError`: return 409 with conflict details.
  6. On any other error: rollback transaction, return 500.
- The existing apply endpoint for non-page proposals (e.g., batch, file-ingestion) is unchanged.
- Unit tests cover all integration paths between apply endpoint and assembler.

**Effort:** 3 hours
**Dependencies:** Task 4 (CourseAssembler), US-AI-011/012/013

---

### Task 10: Create Component Type Seed Migration

**File to create/modify:**
- `alembic/versions/20260615_0002_seed_component_type_compatibility.py`

**Acceptance:**
- Seed migration inserts rows for all MVP types: text-content, welcome, content-video, mcq, tabs, accordion, final-assessment.
- Each row has correct `requires_fields`, `editor_support`, `ai_proposable`, `scorm_exportable`.
- Migration is idempotent (uses INSERT ... ON CONFLICT DO NOTHING or pre-checks).
- Downgrade removes seeded rows by type key.

**Effort:** 45 minutes
**Dependencies:** Task 1 (table exists)

---

### Task 11: Write CourseAssembler Unit Tests

**File to create:**
- `tests/test_course_assembler.py`

**Acceptance:**
- Test class `TestAssembleCreatePage` (5+ tests): happy path, multi-component, unsupported type rejection, auto-order, title truncation.
- Test class `TestAssembleUpdatePage` (3+ tests): component replacement, optimistic lock conflict, nonexistent page.
- Test class `TestAssembleDeletePage` (3+ tests): cascade, reindexing, delete last page.
- Test class `TestValidatePayload` (6+ tests): valid, unsupported type, missing field, empty components, delete without pageId, title too long.
- All tests use async fixtures with in-memory SQLite or test PostgreSQL.
- Coverage >= 85%.

**Effort:** 4 hours
**Dependencies:** Task 4 (CourseAssembler), existing test fixtures

---

### Task 12: Write ComponentTypeResolver Unit Tests

**File to create:**
- `tests/test_component_type_resolver.py`

**Acceptance:**
- Test class `TestCompatibility` (3+ tests): is_compatible true/false, get_supported_types subset.
- Test class `TestValidateComponent` (2+ tests): valid data, missing field.
- All tests use seeded `component_type_compatibility` data.

**Effort:** 1.5 hours
**Dependencies:** Task 3 (ComponentTypeResolver), Task 2 (ORM model)

---

### Task 13: Write Assembly Integration Tests

**File to create:**
- `tests/test_course_assembly_api.py`

**Acceptance:**
- Test class `TestAssemblyAPI` (7+ tests):
  - Validate assembly valid proposal -> 200 with valid=True.
  - Validate assembly invalid proposal -> 200 with valid=False and errors.
  - Validate assembly nonexistent proposal -> 404.
  - Component types endpoint -> 200 with type list.
  - Assembly apply creates page in DB -> 200 with created status.
  - Already applied proposal -> 409.
  - Unsupported type apply -> 422.

**Effort:** 3 hours
**Dependencies:** Tasks 7, 8, 9 (endpoints), existing test infrastructure

---

### Task 14: Document Data Transformation Mapping

**File to modify:**
- `docs/AI_Implemenation/00_User_StoriesUseCases/US-AI-030_COURSE_ASSEMBLY_INTO_EDITOR.md` (this file)

**Acceptance:**
- Section 1.5 (Data Transformation Mapping) has complete field-level mapping table.
- Section 1.6 (Component Type Compatibility Matrix) has complete matrix with notes.
- Section 1.8 (Error Conditions) has all error codes documented.
- All API contracts in section 2.5 have complete request/response examples.
- All environment variables in section 2.8 are documented.

**Effort:** 1 hour
**Dependencies:** All prior tasks (contracts validated during implementation)

---

## Summary

| Metric | Value |
|---|---|
| New files | 6 (`course_assembler.py`, `component_type_resolver.py`, `assembly_repo.py`, `assembly_dtos.py`, migration 1, migration 2) |
| Modified files | 3-4 (router, models/__init__.py, proposal apply endpoint) |
| New DB tables | 1 (`component_type_compatibility`) |
| New API endpoints | 2 (`GET /ai/component-types`, `POST /ai/proposals/{id}/validate-assembly`) |
| Enhanced endpoints | 1 (`POST /ai/proposals/{id}/apply` — now uses CourseAssembler) |
| New service classes | 2 (`CourseAssembler`, `ComponentTypeResolver`) |
| Total estimated effort | ~28 hours |
| Key non-regression invariant | Manual page/component CRUD is unchanged |
| Key risk | Proposal apply endpoint (US-AI-011/012/013) must be ready for CourseAssembler integration |
