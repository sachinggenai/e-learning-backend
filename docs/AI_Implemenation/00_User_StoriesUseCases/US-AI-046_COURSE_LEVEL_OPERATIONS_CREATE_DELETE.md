# US-AI-046: AI-Assisted Course-Level Operations — Create and Delete Courses

**Status:** Draft  
**Priority:** SHOULD  
**Depends on:** US-AI-011 (Create Page Proposal and Apply), US-AI-013 (Delete Page Proposal and Confirm)  
**Source gap:** Research Audit GAP item — the existing 12 tool schemas cover page-level CRUD (list_pages, fetch_page, propose_create_page, propose_update_page, propose_delete_page, etc.) but no tool exists for course-level create/delete via the AI agent. The manual course CRUD at `/api/v1/courses` (POST, GET, PATCH, DELETE) is functionally complete; this story wraps those capabilities into AI-proposable, gated operations.  
**Story Owner:** Technical Product Owner  

---

## 1. FUNCTIONAL SPECIFICATION

### 1.1 User Story

As an Author, I want the AI agent to propose creating a new course shell (with AI-generated metadata) and to propose deleting an existing course through the same safe propose-validate-confirm-apply gating pipeline used for page operations, so that course-level operations are as safe, auditable, and reversible as page-level operations.

### 1.2 Overview

This story adds two course-level tool operations to the AI tool registry that mirror the page-level propose/apply pattern already established by US-AI-011 and US-AI-013:

1. **Course Creation via AI**: The AI agent can propose a new course shell with AI-generated metadata (title, description, learning objectives, language, theme). The proposal is validated for uniqueness and schema correctness, returned as a preview, and only created in the database after explicit user confirmation. After creation, the system optionally creates the first welcome page and navigates the user to the course editor.

2. **Course Deletion via AI**: The AI agent can propose deleting an entire course. Because this is a maximally destructive operation, the gating is stricter than page deletion: it requires a two-phase confirmation (proposal with dependency impact analysis, then explicit confirmation with a typed confirmation phrase). The deletion cascades to all pages, components, assets, and associated AI records. A full before-snapshot is preserved in the audit trail.

Both operations reuse the existing `CourseRepository` for persistence and the existing `PageRepository`/`ComponentRepository` for cascading page operations. Both write audit entries and outbox events as specified in US-AI-010.

### 1.3 Actors

| Actor | Role |
|---|---|
| Author (User) | Initiates course create/delete via AI chat or UI; reviews previews; confirms or cancels |
| AI Agent | Calls `propose_create_course` and `propose_delete_course` tools; never calls mutation APIs directly |
| Backend System | Enforces propose/confirm/apply gating; validates metadata; handles dependency analysis for deletes; executes transactional mutations + audit + outbox |
| Frontend | Renders course creation preview and destructive deletion confirmation modal; refreshes editor/navigation state after operation |
| Admin/Compliance | Queries audit logs for course-level AI operations |

### 1.4 Functional Requirements

**FR-1 — Course Creation Proposal Tool**: The system MUST expose an AI tool `propose_create_course` that accepts a JSON payload containing course metadata (title, description, language, theme, optional learning objectives) and returns a proposal with a preview of the course shell, a generated courseId, and a validation status. The tool MUST NOT create any database records; it returns only a proposal.

**FR-2 — Course Metadata AI Generation**: When the user provides a natural-language instruction (e.g., "Create a course on data science fundamentals"), the AI agent MUST generate the course metadata (title, description, target audience, learning objectives, suggested language and theme) and pass it into `propose_create_course`. The generated title MUST respect the 200-character maximum enforced by `CourseRecord.title`.

**FR-3 — Course Uniqueness Validation**: The proposal MUST validate that the proposed `courseId` (either AI-generated or user-specified) does not already exist in the `courses` table. If a conflict is detected, the proposal MUST return a validation error with code `COURSE_ID_CONFLICT`, and the AI agent MUST re-propose with a different courseId. The system MAY auto-suggest a unique courseId by appending a suffix.

**FR-4 — Course Creation Apply**: After user confirmation, the system MUST execute a database transaction that: (a) creates the `CourseRecord` row, (b) optionally creates a welcome `PageRecord` with a default component, (c) writes an audit log entry with the full before (empty) and after (course data) snapshots, (d) writes an outbox event `CourseCreatedByAI`, and (e) returns the new course with its courseId, page count, and metadata.

**FR-5 — Course Deletion Proposal Tool**: The system MUST expose an AI tool `propose_delete_course` that accepts a `courseId` and returns a proposal containing: course identity metadata (title, page count, component count, asset count), a dependency impact analysis result, and a `confirmationRequired: true` flag. The tool MUST NOT perform any deletion.

**FR-6 — Course Deletion Dependency Impact Analysis**: Before returning a delete proposal, the system MUST analyze all downstream dependencies: (a) all pages and components on the course and their total count, (b) any export packages or import jobs referencing the course, (c) any assessment/scoring data referencing the course, (d) the course status (draft vs published), and (e) any AI sessions currently active on this course. The analysis MUST be returned as a structured `dependencyReport` in the proposal response.

**FR-7 — Course Deletion Confirmation and Apply**: Because course deletion is the most destructive operation in the system, the confirmation gate MUST be stricter than page deletion: (a) the frontend MUST require the user to type the course title verbatim into a confirmation input field before the "Delete" button becomes active, (b) a confirmation token bound to session, proposal, courseId, and a 15-minute expiry is required, (c) the deletion executes in a single transaction cascading to all pages, components, assets, and AI session records, and (d) a full before-snapshot (all pages with all components serialized) is preserved in the audit log.

**FR-8 — AI-Generated First Page (Welcome Screen)**: On course creation, the system MAY optionally generate an initial welcome page using a `text-content` or `welcome` template with a default component populated from the course title and description. This is configurable via feature flag `AI_CREATE_WELCOME_PAGE` (default: true). If enabled, the welcome page is created in the same transaction as the course, and the page count in the response includes it.

### 1.5 User Flows

#### Flow A: AI Course Creation (Happy Path)

```
1. User types: "Create a new course on Python programming for beginners"
2. AI agent receives the request in the chat orchestrator
3. AI agent generates course metadata via LLM:
   {
     "title": "Python Programming for Beginners",
     "description": "A comprehensive introduction to Python programming covering variables, control flow, functions, and basic data structures.",
     "language": "en",
     "targetAudience": "Absolute beginners with no prior coding experience",
     "learningObjectives": ["Write basic Python scripts", "Use variables and data types", "Implement control flow with conditionals and loops"]
   }
4. AI agent calls propose_create_course(metadata)
5. Backend validates:
   - Course title meets length constraints (1-200 chars)
   - Description within 500-char limit
   - Language is a supported LanguageType
   - Generated courseId does not conflict with existing course
6. Backend generates a deterministic courseId from the title (e.g., "python-programming-for-beginners") and appends an 8-char suffix if collision detected (e.g., "python-programming-for-beginners-a1b2c3d4")
7. Backend returns proposal with:
   - proposalId (UUID v4)
   - coursePreview: { courseId, title, description, language, targetAudience, learningObjectives }
   - validationStatus: "valid"
   - suggestedFirstPage: "Welcome to Python Programming" (welcome template)
8. Frontend renders course creation preview panel showing title, description, learning objectives, and optional "Include welcome page" toggle
9. User reviews and clicks "Create Course"
10. Frontend calls apply_create_course(proposalId, userConfirmed=true, createWelcomePage=true)
11. Backend begins transaction:
    a. Update proposal status to APPLYING
    b. Create CourseRecord with the proposed metadata
    c. Create PageRecord with title "Welcome to Python Programming", template type "content-text", order 0, with a default component containing the course description
    d. Update proposal status to APPLIED
    e. Write audit entry (before={}, after={course data})
    f. Write outbox event CourseCreatedByAI
    g. Commit transaction
12. Backend returns success with courseId, pageId of welcome page, and full course state
13. Frontend navigates to the course editor for the newly created course
14. Chat panel shows: "Your course 'Python Programming for Beginners' has been created with a welcome page. You can now add more pages or edit content."
```

#### Flow B: AI Course Creation (Error Path — Duplicate courseId)

```
1. User asks to create a course with title "Data Science 101"
2. AI agent calls propose_create_course(...) with generated courseId "data-science-101"
3. Backend detects course "data-science-101" already exists
4. Backend returns validation error: { status: "error", code: "COURSE_ID_CONFLICT", message: "Course 'data-science-101' already exists", suggestedAlternative: "data-science-101-b2x9k7m1" }
5. AI agent re-calls propose_create_course with the suggested alternative courseId
6. Backend confirms no conflict, returns valid proposal
7. Flow continues from step 8 of Happy Path
```

#### Flow C: AI Course Deletion (Happy Path)

```
1. User types: "Delete the Python Programming course"
2. AI agent calls list_pages() to confirm it knows which course is active
3. AI agent resolves the active course from session context
4. AI agent calls propose_delete_course(sessionId, courseId="python-programming-for-beginners")
5. Backend validates:
   - Session is active and owns this courseId
   - Course exists and is not already deleted
   - No existing proposal with PENDING_CONFIRMATION for this courseId+sessionId
6. Backend performs dependency analysis:
   - 8 pages found (1 welcome + 7 content pages)
   - 12 components total across all pages
   - 0 export jobs referencing this course
   - 1 active AI session (the current one)
   - Course status: "draft"
7. Backend generates confirmation_token (64-char hex, SHA256 stored)
8. Backend creates proposal with status=PENDING_CONFIRMATION, operation=delete_course
9. Proposal response includes:
   - proposalId
   - coursePreview: { courseId, title, pageCount: 8, componentCount: 12, status: "draft" }
   - dependencyReport: { totalPages: 8, totalComponents: 12, activeSessions: 1, exportReferences: 0, assessmentPages: 1 }
   - confirmationTokenExpiresAt (now + 15 min)
   - confirmationRequired: true
10. Frontend renders destructive confirmation modal:
    - Red banner: "DANGER: This will permanently delete the course 'Python Programming for Beginners' and all 8 pages, 12 components, and associated data."
    - Dependency report summary
    - Irreversible action notice
    - Confirmation input field: "Type the course title to confirm:"
    - "Cancel" button (always enabled)
    - "Delete Course" button (disabled until exact title is typed)
11. User types "Python Programming for Beginners" into the confirmation input
12. "Delete Course" button becomes enabled
13. User clicks "Delete Course"
14. Frontend calls confirm_delete_course(sessionId, proposalId, userConfirmedDelete=true, confirmationPhrase="Python Programming for Beginners")
15. Backend validates:
    - Proposal exists and status is PENDING_CONFIRMATION
    - confirmationPhrase matches the actual course title (case-sensitive exact match)
    - Token has not expired
    - Course still exists (re-check for 410 GONE)
16. Backend begins transaction:
    a. Before-snapshot: serialize all pages, components, and course metadata
    b. Update proposal status to APPLYING
    c. Delete all ComponentRecord rows for the course (via PageRepository + ComponentRepository)
    d. Delete all PageRecord rows for the course
    e. Delete the CourseRecord
    f. Invalidate any active AI sessions for this course (set status to TERMINATED)
    g. Remove course from RAG index (if US-AI-015 implemented)
    h. Update proposal status to APPLIED
    i. Write audit entry with full before-snapshot
    j. Write outbox event CourseDeletedByAI
    k. Commit transaction
17. Backend returns { status: "deleted", courseId, title, message: "Course 'Python Programming for Beginners' has been permanently deleted." }
18. Frontend navigates away from the deleted course (back to course list)
19. Chat panel confirms: "The course 'Python Programming for Beginners' has been deleted. All 8 pages and 12 components have been removed."
```

#### Flow D: AI Course Deletion (Error Path — Stale / Changed)

```
1. User proposes to delete a course (propose_delete_course returns valid proposal)
2. Meanwhile, another author adds 2 pages to the same course
3. User returns after 20 minutes (token expired) and confirms deletion
4. Backend returns 409 CONFLICT: "Course has changed since proposal. Please re-propose deletion to see updated dependency report."
5. Frontend displays error with option to re-propose
6. User clicks "Re-analyze" → AI agent re-calls propose_delete_course
7. Updated proposal now shows 10 pages, 14 components, updated dependency report
8. User reviews and confirms again
9. Deletion proceeds
```

### 1.6 UI/UX Requirements

**Course Creation Preview Panel (similar to page proposal preview):**
- Card layout showing: Title (large heading), Description (paragraph), Language badge, Theme badge (if applicable)
- Learning objectives displayed as numbered list
- Auto-generated courseId shown in monospace font with copy button
- Toggle switch: "Create welcome page" (default: on)
- "Create Course" primary button
- "Cancel" secondary button
- Validation errors shown inline with field references
- If courseId conflict: show warning with auto-suggested alternative, one-click accept

**Course Deletion Confirmation Modal:**
- Full-screen overlay, cannot be dismissed by clicking outside (must click Cancel or type confirmation)
- Red/orange danger theme with warning icons
- Section 1: Course identity — courseId, title, status (draft/published), created date
- Section 2: Dependency report — total pages, total components, total assets, active AI sessions, export references
- Section 3: Irreversible action warning — "This action cannot be undone. All course content will be permanently deleted."
- Section 4: Confirmation input — text field with label "Type the course title to confirm deletion:"
- Submit button: "Permanently Delete Course" — disabled until input matches title exactly
- Cancel button: always enabled
- Button disable state also applies to keyboard Enter (Enter does not submit unless button is enabled)
- On successful deletion: redirect to course list with a success toast notification
- On error: show inline error with retry options

---

## 2. TECHNICAL SPECIFICATION

### 2.1 API Contracts

#### Tool: `propose_create_course`

```
name: "propose_create_course"
description: "Propose a new course shell with AI-generated metadata. Does NOT create any database records."
idempotent: false
permissionScope: "org_level (creates within user's organization)"
```

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "title": {
      "type": "string",
      "minLength": 1,
      "maxLength": 200,
      "description": "Course title"
    },
    "description": {
      "type": "string",
      "maxLength": 500,
      "description": "Course description"
    },
    "language": {
      "type": "string",
      "enum": ["en", "es", "fr", "de", "it", "pt", "nl", "pl", "ru", "ja", "ko", "zh"],
      "default": "en",
      "description": "Course language"
    },
    "targetAudience": {
      "type": "string",
      "maxLength": 200,
      "description": "Target audience description"
    },
    "learningObjectives": {
      "type": "array",
      "items": {
        "type": "string",
        "maxLength": 200
      },
      "minItems": 0,
      "maxItems": 10,
      "description": "List of learning objectives"
    },
    "theme": {
      "type": "string",
      "enum": ["default", "dark", "light", "corporate"],
      "default": "default",
      "description": "Course theme"
    },
    "suggestedCourseId": {
      "type": "string",
      "pattern": "^[a-zA-Z0-9_-]+$",
      "maxLength": 64,
      "description": "Optional: preferred courseId. System auto-generates if omitted."
    }
  },
  "required": ["title"]
}
```

**Output Schema:**
```json
{
  "type": "object",
  "properties": {
    "status": {
      "type": "string",
      "enum": ["success", "error"]
    },
    "proposalId": {
      "type": "string",
      "format": "uuid",
      "description": "UUID of this proposal (used for apply)"
    },
    "coursePreview": {
      "type": "object",
      "properties": {
        "courseId": { "type": "string", "description": "Assigned or validated courseId" },
        "title": { "type": "string" },
        "description": { "type": "string" },
        "language": { "type": "string" },
        "targetAudience": { "type": "string" },
        "learningObjectives": {
          "type": "array",
          "items": { "type": "string" }
        },
        "theme": { "type": "string" },
        "suggestedWelcomePage": {
          "type": "object",
          "properties": {
            "title": { "type": "string" },
            "templateType": { "type": "string" }
          },
          "description": "Suggested first page if welcome page generation is enabled"
        }
      }
    },
    "validationStatus": {
      "type": "string",
      "enum": ["valid", "warning", "error"]
    },
    "validationMessages": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "severity": { "type": "string", "enum": ["error", "warning", "info"] },
          "field": { "type": "string" },
          "message": { "type": "string" },
          "code": { "type": "string" }
        }
      }
    }
  },
  "required": ["status", "proposalId", "coursePreview", "validationStatus"]
}
```

**Error Responses (besides standard error envelope):**
- `COURSE_ID_CONFLICT`: The generated or suggested courseId already exists. Response includes `suggestedAlternative` with a unique courseId suggestion.

#### Tool: `apply_create_course`

```
name: "apply_create_course"
description: "Apply a proposed course creation. Creates the CourseRecord, optional welcome page, writes audit and outbox."
idempotent: true
permissionScope: "org_level"
```

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "proposalId": {
      "type": "string",
      "format": "uuid",
      "description": "UUID returned from propose_create_course"
    },
    "userConfirmed": {
      "type": "boolean",
      "description": "Must be true. Confirms user approval."
    },
    "createWelcomePage": {
      "type": "boolean",
      "default": true,
      "description": "Whether to auto-generate a welcome page"
    }
  },
  "required": ["proposalId", "userConfirmed"]
}
```

**Output Schema:**
```json
{
  "type": "object",
  "properties": {
    "status": { "type": "string", "enum": ["created", "rejected", "error"] },
    "courseId": { "type": "string" },
    "course": {
      "type": "object",
      "properties": {
        "courseId": { "type": "string" },
        "title": { "type": "string" },
        "description": { "type": "string" },
        "language": { "type": "string" },
        "status": { "type": "string", "default": "draft" },
        "pageCount": { "type": "integer" },
        "welcomePageId": { "type": "string", "description": "pageId of welcome page if created" },
        "createdAt": { "type": "string", "format": "date-time" },
        "updatedAt": { "type": "string", "format": "date-time" }
      }
    },
    "message": { "type": "string" }
  },
  "required": ["status", "courseId"]
}
```

#### Tool: `propose_delete_course`

```
name: "propose_delete_course"
description: "Propose deleting an entire course. Returns dependency impact analysis. Does NOT perform any deletion."
idempotent: false
permissionScope: "current_session_courseId"
```

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "courseId": {
      "type": "string",
      "description": "The courseId of the course to delete"
    }
  },
  "required": ["courseId"]
}
```

**Output Schema:**
```json
{
  "type": "object",
  "properties": {
    "status": { "type": "string", "enum": ["success", "error"] },
    "proposalId": { "type": "string", "format": "uuid" },
    "coursePreview": {
      "type": "object",
      "properties": {
        "courseId": { "type": "string" },
        "title": { "type": "string" },
        "status": { "type": "string" },
        "pageCount": { "type": "integer" },
        "componentCount": { "type": "integer" },
        "assetCount": { "type": "integer" },
        "createdAt": { "type": "string", "format": "date-time" },
        "updatedAt": { "type": "string", "format": "date-time" }
      }
    },
    "dependencyReport": {
      "type": "object",
      "properties": {
        "totalPages": { "type": "integer" },
        "totalComponents": { "type": "integer" },
        "totalAssets": { "type": "integer" },
        "activeSessions": { "type": "integer", "description": "Active AI sessions on this course" },
        "exportReferences": { "type": "integer", "description": "Export jobs referencing this course" },
        "assessmentPages": { "type": "integer", "description": "Number of final-assessment pages" },
        "importJobs": { "type": "integer", "description": "Import jobs referencing this course" }
      }
    },
    "confirmationTokenExpiresAt": { "type": "string", "format": "date-time" },
    "confirmationRequired": { "type": "boolean", "default": true }
  },
  "required": ["status", "proposalId", "coursePreview", "dependencyReport", "confirmationRequired"]
}
```

#### Tool: `confirm_delete_course`

```
name: "confirm_delete_course"
description: "Confirm and execute course deletion. Requires the exact course title as a typed confirmation phrase."
idempotent: false
permissionScope: "current_session_courseId"
```

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "proposalId": {
      "type": "string",
      "format": "uuid",
      "description": "UUID returned from propose_delete_course"
    },
    "userConfirmedDelete": {
      "type": "boolean",
      "description": "Must be true."
    },
    "confirmationPhrase": {
      "type": "string",
      "description": "User must type the exact course title as a confirmation safeguard."
    }
  },
  "required": ["proposalId", "userConfirmedDelete", "confirmationPhrase"]
}
```

**Output Schema:**
```json
{
  "type": "object",
  "properties": {
    "status": { "type": "string", "enum": ["deleted", "cancelled", "error", "conflict"] },
    "courseId": { "type": "string" },
    "title": { "type": "string" },
    "message": { "type": "string" },
    "auditEntryId": { "type": "string", "description": "ID of the audit log entry for this deletion" }
  },
  "required": ["status", "courseId", "message"]
}
```

**Error Responses:**
- `410 GONE`: Course was already deleted (idempotency guard).
- `409 CONFLICT`: Course has changed since the proposal was created; user must re-propose.
- `422 CONFIRMATION_PHRASE_MISMATCH`: The typed phrase does not match the course title exactly.
- `401 TOKEN_EXPIRED`: The confirmation token has expired (15-minute window).
- `404 PROPOSAL_NOT_FOUND`: Proposal ID does not exist or was already used.

### 2.2 Database Schema

#### New Columns on `ai_proposals` Table (extend existing)

The `ai_proposals` table from US-AI-004 must support course-level operations. Add or clarify the following columns:

```sql
-- Enhancement to existing ai_proposals table to support course-level operations
ALTER TABLE ai_proposals ADD COLUMN IF NOT EXISTS operation_type VARCHAR(32) NOT NULL DEFAULT 'page_create';
-- operation_type now includes: 'page_create', 'page_update', 'page_delete', 'course_create', 'course_delete'

ALTER TABLE ai_proposals ADD COLUMN IF NOT EXISTS confirmation_phrase_hash VARCHAR(64) NULL;
-- SHA256 hash of the expected typed confirmation phrase (course title for course_delete).
-- NULL for non-delete operations.

ALTER TABLE ai_proposals ADD COLUMN IF NOT EXISTS before_snapshot JSONB NULL;
-- Full serialized state before the operation.
-- For course_delete: complete serialization of CourseRecord + all PageRecords + all ComponentRecords.

ALTER TABLE ai_proposals ADD COLUMN IF NOT EXISTS after_candidate JSONB NULL;
-- The proposed new state (for course_create: the course metadata).
```

#### New Columns on `ai_proposals` (full DDL for reference)

```sql
-- Full ai_proposals table DDL (including US-AI-004 columns for context)
CREATE TABLE IF NOT EXISTS ai_proposals (
    id              SERIAL PRIMARY KEY,
    proposal_id     VARCHAR(64) UNIQUE NOT NULL,
    session_id      VARCHAR(64) NOT NULL REFERENCES ai_sessions(session_id) ON DELETE CASCADE,
    user_id         VARCHAR(64) NOT NULL,
    organization_id VARCHAR(64) NOT NULL,
    course_id       VARCHAR(64),
    page_id         VARCHAR(64),

    -- Operation type: page_create, page_update, page_delete, course_create, course_delete
    operation_type  VARCHAR(32) NOT NULL,

    -- Proposal state machine
    status          VARCHAR(32) NOT NULL DEFAULT 'pending_review',
    -- pending_review, approved, applying, applied, rejected, expired, failed

    -- Input payload that was proposed
    input_payload   JSONB NOT NULL,

    -- Validation result
    validation_status   VARCHAR(16),  -- valid, warning, error
    validation_result   JSONB,
    validation_messages JSONB,

    -- Before/after snapshots for audit
    before_snapshot     JSONB,
    after_candidate     JSONB,

    -- Staleness detection
    base_hash       VARCHAR(64),

    -- Confirmation token (SHA256 hash, never plaintext)
    confirmation_token_sha256   VARCHAR(64),
    confirmation_token_expires_at TIMESTAMPTZ,
    confirmation_phrase_hash    VARCHAR(64),
    confirmation_phrase_expected VARCHAR(200),  -- stored for UI display; never used for comparison

    -- Timestamps
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '24 hours'),
    applied_at      TIMESTAMPTZ,

    -- Foreign keys
    FOREIGN KEY (session_id) REFERENCES ai_sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX idx_ai_proposals_session ON ai_proposals(session_id);
CREATE INDEX idx_ai_proposals_course ON ai_proposals(course_id);
CREATE INDEX idx_ai_proposals_operation ON ai_proposals(operation_type);
CREATE INDEX idx_ai_proposals_status ON ai_proposals(status);
CREATE INDEX idx_ai_proposals_expires ON ai_proposals(expires_at);
```

#### Audit Log Entry for Course Operations

```sql
-- ai_audit_logs table (from US-AI-004)
-- Course-level operations add these operation_type values:
-- 'course_created_by_ai', 'course_deleted_by_ai'

-- Example row for course creation:
-- operation_type: 'course_created_by_ai'
-- before_snapshot: {}
-- after_snapshot: { "course": { "courseId": "...", "title": "...", "pages": [ ... ] } }

-- Example row for course deletion:
-- operation_type: 'course_deleted_by_ai'
-- before_snapshot: { "course": { "courseId": "...", "title": "...", "pages": [ ... all pages with all components ... ] } }
-- after_snapshot: {}
```

### 2.3 Service/Module Design

```
app/
  ai/
    __init__.py
    tool_registry.py          # Register course_create and course_delete tools
    course_operations.py      # Core service: create_course, delete_course logic
    
    # Existing files (from US-AI-011, US-AI-013) that need enhancement:
    proposal_service.py        # Enhanced to handle course-level proposal states
    confirmation_service.py    # Enhanced to handle typed-phrase confirmation for course deletes
    audit_service.py           # Already handles course-level ops? No — must add logging
    
services/
  ai/
    course_operations_service.py   # New service file
    
    # Existing (from US-AI-011, US-AI-013):
    proposal_service.py            # Extend proposal lifecycle for course operations
    confirmation_service.py        # Extend with typed-phrase validation
```

**`app/ai/course_operations.py` — Core Service Class:**

```python
"""
Service layer for AI-assisted course-level operations: create and delete.

Reuses existing CourseRepository, PageRepository, and ComponentRepository
for persistence. Follows the propose-validate-confirm-apply gating pattern.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.course_repo import CourseRepository, CourseConflictError, CourseNotFoundError
from app.repositories.page_component_repo import PageRepository, ComponentRepository
from app.services.ai.proposal_service import ProposalService
from app.services.ai.confirmation_service import ConfirmationService
from app.services.ai.audit_service import AuditService
from app.services.ai.outbox_service import OutboxService
from app.models.course import LanguageType, ThemeType


class CourseOperationError(Exception):
    """Base error for course-level operations."""

class CourseIdConflictError(CourseOperationError):
    """Raised when proposed courseId already exists."""

class ConfirmationPhraseMismatchError(CourseOperationError):
    """Raised when typed confirmation phrase does not match."""

class CourseChangedError(CourseOperationError):
    """Raised when course has changed since proposal was created."""


class CourseOperationsService:
    """
    Handles propose_create_course, apply_create_course,
    propose_delete_course, and confirm_delete_course.
    """

    PROPOSAL_TTL_MINUTES = 15  # Course delete confirmation window
    CONFIRMATION_TOKEN_BYTES = 32  # 64 hex chars

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session
        self.course_repo = CourseRepository(db_session)
        self.page_repo = PageRepository(db_session)
        self.component_repo = ComponentRepository(db_session)
        self.proposal_service = ProposalService(db_session)
        self.confirmation_service = ConfirmationService(db_session)
        self.audit_service = AuditService(db_session)
        self.outbox_service = OutboxService(db_session)

    async def propose_create_course(
        self,
        session_id: str,
        user_id: str,
        organization_id: str,
        title: str,
        description: Optional[str] = None,
        language: str = "en",
        target_audience: Optional[str] = None,
        learning_objectives: Optional[list[str]] = None,
        theme: str = "default",
        suggested_course_id: Optional[str] = None,
    ) -> dict:
        """
        Validate course metadata and return a proposal.
        Does NOT create any database records.
        """
        # 1. Generate courseId
        course_id = suggested_course_id or self._generate_course_id(title)

        # 2. Check uniqueness
        try:
            await self.course_repo.get_by_course_id(course_id)
            # Course exists — generate a unique alternative
            suffix = secrets.token_hex(4)  # 8-char hex suffix
            alternative = f"{course_id[:55]}-{suffix}"
            return {
                "status": "error",
                "code": "COURSE_ID_CONFLICT",
                "message": f"Course ID '{course_id}' already exists.",
                "suggestedAlternative": alternative,
            }
        except CourseNotFoundError:
            pass  # Course does not exist — good to proceed

        # 3. Validate metadata
        validation_messages = []
        if len(title) > 200:
            validation_messages.append({
                "severity": "error",
                "field": "title",
                "message": "Course title must be 200 characters or fewer.",
                "code": "TITLE_TOO_LONG",
            })
        if description and len(description) > 500:
            validation_messages.append({
                "severity": "warning",
                "field": "description",
                "message": "Description will be truncated to 500 characters.",
                "code": "DESCRIPTION_TOO_LONG",
            })
        if language not in self._SUPPORTED_LANGUAGES:
            validation_messages.append({
                "severity": "error",
                "field": "language",
                "message": f"Language '{language}' is not supported.",
                "code": "UNSUPPORTED_LANGUAGE",
            })

        has_errors = any(m["severity"] == "error" for m in validation_messages)
        validation_status = "error" if has_errors else "valid"

        if has_errors:
            return {
                "status": "error",
                "code": "VALIDATION_ERROR",
                "message": "Course metadata has validation errors.",
                "validationMessages": validation_messages,
            }

        # 4. Create proposal record
        proposal_id = str(uuid.uuid4())
        course_preview = {
            "courseId": course_id,
            "title": title,
            "description": description or "",
            "language": language,
            "targetAudience": target_audience or "",
            "learningObjectives": learning_objectives or [],
            "theme": theme,
            "suggestedWelcomePage": {
                "title": f"Welcome to {title}",
                "templateType": "content-text",
            },
        }

        await self.proposal_service.create_proposal(
            proposal_id=proposal_id,
            session_id=session_id,
            user_id=user_id,
            organization_id=organization_id,
            operation_type="course_create",
            input_payload={
                "title": title,
                "description": description,
                "language": language,
                "targetAudience": target_audience,
                "learningObjectives": learning_objectives,
                "theme": theme,
                "courseId": course_id,
            },
            validation_status=validation_status,
            validation_messages=validation_messages,
            after_candidate=course_preview,
        )

        return {
            "status": "success",
            "proposalId": proposal_id,
            "coursePreview": course_preview,
            "validationStatus": validation_status,
            "validationMessages": validation_messages,
        }

    async def apply_create_course(
        self,
        proposal_id: str,
        user_confirmed: bool,
        create_welcome_page: bool = True,
    ) -> dict:
        """
        Apply a previously proposed course creation.
        Executes in a single transaction.
        """
        if not user_confirmed:
            return {"status": "rejected", "courseId": "", "message": "User rejected the proposal."}

        # 1. Fetch and validate proposal
        proposal = await self.proposal_service.get_proposal(proposal_id)
        if proposal.operation_type != "course_create":
            return {"status": "error", "courseId": "", "message": "Proposal is not a course creation."}
        if proposal.status != "pending_review":
            return {"status": "error", "courseId": "", "message": f"Proposal is in state '{proposal.status}', expected 'pending_review'."}

        input_data = proposal.input_payload
        course_id = input_data["courseId"]
        title = input_data["title"]

        # 2. Re-check uniqueness (another session may have created it since proposal)
        try:
            await self.course_repo.get_by_course_id(course_id)
            return {
                "status": "conflict",
                "courseId": course_id,
                "message": "Course was already created by another session.",
            }
        except CourseNotFoundError:
            pass

        # 3. Execute transaction
        async with self.db_session.begin_nested():
            # Update proposal status
            await self.proposal_service.update_status(proposal_id, "applying")

            # Create CourseRecord
            course_record = await self.course_repo.create(
                course_id=course_id,
                title=title,
                description=input_data.get("description"),
                data={
                    "language": input_data.get("language", "en"),
                    "targetAudience": input_data.get("targetAudience"),
                    "learningObjectives": input_data.get("learningObjectives", []),
                    "theme": input_data.get("theme", "default"),
                    "author": input_data.get("userId", ""),
                },
            )

            # Optionally create welcome page
            welcome_page_id = None
            if create_welcome_page:
                from app.models.page_component import PageRecord, ComponentRecord
                welcome_page = PageRecord(
                    course_id=course_id,
                    title=f"Welcome to {title}",
                    order_index=0,
                )
                created_page = await self.page_repo.create(welcome_page)

                # Create a default text-content component on the welcome page
                welcome_component = ComponentRecord(
                    page_id=created_page.page_id,
                    component_type="content-text",
                    order_index=0,
                    data={
                        "content": input_data.get("description", f"Welcome to {title}!"),
                    },
                )
                await self.component_repo.create(welcome_component)
                welcome_page_id = created_page.page_id

            # Update proposal to applied
            await self.proposal_service.update_status(proposal_id, "applied", applied_at=datetime.utcnow())

            # Write audit log
            after_snapshot = {
                "course": {
                    "courseId": course_id,
                    "title": title,
                    "description": input_data.get("description"),
                    "pageCount": 1 if create_welcome_page else 0,
                    "welcomePageId": welcome_page_id,
                }
            }
            await self.audit_service.log(
                operation_type="course_created_by_ai",
                proposal_id=proposal_id,
                session_id=proposal.session_id,
                user_id=proposal.user_id,
                course_id=course_id,
                before_snapshot={},
                after_snapshot=after_snapshot,
            )

            # Write outbox event
            await self.outbox_service.emit(
                event_type="CourseCreatedByAI",
                aggregate_id=course_id,
                payload=after_snapshot,
            )

        return {
            "status": "created",
            "courseId": course_id,
            "course": {
                "courseId": course_id,
                "title": title,
                "description": input_data.get("description"),
                "language": input_data.get("language", "en"),
                "status": "draft",
                "pageCount": 1 if create_welcome_page else 0,
                "welcomePageId": welcome_page_id,
                "createdAt": datetime.utcnow().isoformat(),
                "updatedAt": datetime.utcnow().isoformat(),
            },
            "message": f"Course '{title}' created successfully.",
        }

    async def propose_delete_course(
        self,
        session_id: str,
        user_id: str,
        course_id: str,
    ) -> dict:
        """
        Propose deleting a course with dependency impact analysis.
        """
        # 1. Fetch course
        try:
            course_record = await self.course_repo.get_by_course_id(course_id)
        except CourseNotFoundError:
            return {"status": "error", "code": "NOT_FOUND", "message": f"Course '{course_id}' not found."}

        # 2. Perform dependency analysis
        pages = await self.page_repo.list_by_course(course_id)
        total_components = 0
        assessment_pages = 0
        for page in pages:
            total_components += len(page.components or [])
            # Check if page contains final-assessment components
            if page.components:
                for comp in page.components:
                    if comp.component_type == "final-assessment":
                        assessment_pages += 1
                        break

        # Count active AI sessions (simplified — actual query against ai_sessions table)
        active_sessions = await self._count_active_sessions(course_id)

        dependency_report = {
            "totalPages": len(pages),
            "totalComponents": total_components,
            "totalAssets": 0,  # Asset counting TBD — depends on asset store implementation
            "activeSessions": active_sessions,
            "exportReferences": 0,  # Export job counting TBD
            "assessmentPages": assessment_pages,
            "importJobs": 0,  # Import job counting TBD
        }

        # 3. Compute course hash for staleness tracking
        course_hash = self._compute_course_hash(course_record, pages)

        # 4. Generate confirmation token
        confirmation_token = secrets.token_hex(self.CONFIRMATION_TOKEN_BYTES)
        confirmation_token_sha256 = hashlib.sha256(confirmation_token.encode()).hexdigest()
        expires_at = datetime.utcnow() + timedelta(minutes=self.PROPOSAL_TTL_MINUTES)

        # 5. Serialize full before-snapshot
        before_snapshot = {
            "course": course_record.to_dict(),
            "pages": [p.to_dict(include_components=True) for p in pages],
        }

        # 6. Create proposal record
        proposal_id = str(uuid.uuid4())
        await self.proposal_service.create_proposal(
            proposal_id=proposal_id,
            session_id=session_id,
            user_id=user_id,
            organization_id=course_record.json_data.get("organization_id", ""),
            operation_type="course_delete",
            course_id=course_id,
            input_payload={"courseId": course_id},
            validation_status="valid",
            before_snapshot=before_snapshot,
            confirmation_token_sha256=confirmation_token_sha256,
            confirmation_token_expires_at=expires_at,
            confirmation_phrase_expected=course_record.title,
            confirmation_phrase_hash=hashlib.sha256(course_record.title.encode()).hexdigest(),
        )

        # 7. Return confirmation token (plaintext only in this response; never stored)
        return {
            "status": "success",
            "proposalId": proposal_id,
            "coursePreview": {
                "courseId": course_record.course_id,
                "title": course_record.title,
                "status": course_record.status,
                "pageCount": len(pages),
                "componentCount": total_components,
                "assetCount": 0,
                "createdAt": course_record.created_at.isoformat(),
                "updatedAt": course_record.updated_at.isoformat(),
            },
            "dependencyReport": dependency_report,
            "confirmationToken": confirmation_token,  # Plaintext; one-time return
            "confirmationTokenExpiresAt": expires_at.isoformat(),
            "confirmationRequired": True,
        }

    async def confirm_delete_course(
        self,
        proposal_id: str,
        user_confirmed_delete: bool,
        confirmation_phrase: str,
    ) -> dict:
        """
        Confirm and execute course deletion with typed-phrase safeguard.
        """
        if not user_confirmed_delete:
            return {"status": "cancelled", "courseId": "", "message": "Deletion cancelled by user."}

        # 1. Fetch proposal
        proposal = await self.proposal_service.get_proposal(proposal_id)
        if proposal.operation_type != "course_delete":
            return {"status": "error", "courseId": "", "message": "Proposal is not a course deletion."}

        course_id = proposal.course_id
        title = proposal.confirmation_phrase_expected

        # 2. Verify confirmation phrase
        expected_hash = proposal.confirmation_phrase_hash
        actual_hash = hashlib.sha256(confirmation_phrase.encode()).hexdigest()
        if actual_hash != expected_hash:
            return {
                "status": "error",
                "code": "CONFIRMATION_PHRASE_MISMATCH",
                "courseId": course_id,
                "message": "Typed confirmation phrase does not match the course title.",
            }

        # 3. Verify token not expired
        if proposal.confirmation_token_expires_at < datetime.utcnow():
            return {
                "status": "error",
                "code": "TOKEN_EXPIRED",
                "courseId": course_id,
                "message": "Confirmation window has expired (15 minutes). Please re-propose deletion.",
            }

        # 4. Re-check course exists and compute current hash
        try:
            course_record = await self.course_repo.get_by_course_id(course_id)
            current_pages = await self.page_repo.list_by_course(course_id)
            current_hash = self._compute_course_hash(course_record, current_pages)

            # 5. Staleness check (compare with proposal base_hash)
            # For simplicity, we compare page count as a staleness proxy;
            # a full content hash comparison is more robust.
            if current_hash != proposal.base_hash and current_hash is not None:
                return {
                    "status": "conflict",
                    "courseId": course_id,
                    "message": "Course has changed since the deletion proposal. Please re-propose to see updated impact analysis.",
                }
        except CourseNotFoundError:
            return {
                "status": "gone",
                "courseId": course_id,
                "message": "Course was already deleted.",
            }

        # 6. Execute deletion transaction
        async with self.db_session.begin_nested():
            await self.proposal_service.update_status(proposal_id, "applying")

            # Delete all components, then pages, then course
            for page in current_pages:
                for component in (page.components or []):
                    await self.component_repo.delete(component)
                await self.page_repo.delete(page)

            await self.course_repo.delete_record(course_record.id)

            # Terminate active AI sessions for this course
            await self._terminate_course_sessions(course_id)

            await self.proposal_service.update_status(proposal_id, "applied", applied_at=datetime.utcnow())

            # Write audit log with before-snapshot from proposal
            before_snapshot = proposal.before_snapshot
            await self.audit_service.log(
                operation_type="course_deleted_by_ai",
                proposal_id=proposal_id,
                session_id=proposal.session_id,
                user_id=proposal.user_id,
                course_id=course_id,
                before_snapshot=before_snapshot or {},
                after_snapshot={},
            )

            # Write outbox event
            await self.outbox_service.emit(
                event_type="CourseDeletedByAI",
                aggregate_id=course_id,
                payload={"courseId": course_id, "title": title},
            )

        return {
            "status": "deleted",
            "courseId": course_id,
            "title": title,
            "message": f"Course '{title}' has been permanently deleted.",
            "auditEntryId": proposal_id,
        }

    def _generate_course_id(self, title: str) -> str:
        """Generate a URL-safe courseId from the title."""
        import re
        # Lowercase, replace spaces/special chars with hyphens, collapse multiple hyphens
        course_id = title.lower()
        course_id = re.sub(r'[^a-z0-9]+', '-', course_id)
        course_id = re.sub(r'-+', '-', course_id).strip('-')
        return course_id[:64] or "untitled-course"

    def _compute_course_hash(self, course_record, pages) -> str:
        """Compute a deterministic hash of course + pages for staleness detection."""
        hash_input = {
            "course_id": course_record.course_id,
            "title": course_record.title,
            "updated_at": course_record.updated_at.isoformat(),
            "page_count": len(pages),
            "page_ids": sorted([p.page_id for p in pages]),
        }
        return hashlib.sha256(json.dumps(hash_input, sort_keys=True).encode()).hexdigest()

    async def _count_active_sessions(self, course_id: str) -> int:
        """Count active AI sessions for the given course."""
        from app.models.ai_session import AISessionRecord
        result = await self.db_session.execute(
            select(func.count()).select_from(AISessionRecord)
            .where(AISessionRecord.course_id == course_id)
            .where(AISessionRecord.status == "active")
        )
        return result.scalar() or 0

    async def _terminate_course_sessions(self, course_id: str) -> None:
        """Terminate all active AI sessions for the given course."""
        from app.models.ai_session import AISessionRecord
        await self.db_session.execute(
            update(AISessionRecord)
            .where(AISessionRecord.course_id == course_id)
            .where(AISessionRecord.status == "active")
            .values(status="terminated", terminated_reason="course_deleted")
        )

    _SUPPORTED_LANGUAGES = {"en", "es", "fr", "de", "it", "pt", "nl", "pl", "ru", "ja", "ko", "zh"}

    _SUPPORTED_THEMES = {"default", "dark", "light", "corporate"}
```

### 2.4 Configuration Variables

| Variable | Type | Default | Description |
|---|---|---|---|
| `AI_CREATE_WELCOME_PAGE` | bool | `true` | Auto-create welcome page on AI course creation |
| `AI_COURSE_DELETE_CONFIRM_TIMEOUT_MINUTES` | int | `15` | Confirmation token expiry for course deletion |
| `AI_COURSE_ID_MAX_LENGTH` | int | `64` | Maximum length of auto-generated courseId |
| `AI_COURSE_DELETE_PHRASE_CONFIRMATION_ENABLED` | bool | `true` | Require typed title phrase for delete confirmation |
| `AI_COURSE_CREATE_MAX_OBJECTIVES` | int | `10` | Maximum number of learning objectives |

### 2.5 Integration Points

| Integration | Direction | Detail |
|---|---|---|
| `CourseRepository` | Used by | `course_operations.py` calls `create`, `get_by_course_id`, `delete_record` |
| `PageRepository` | Used by | `course_operations.py` calls `list_by_course`, `create`, `delete` |
| `ComponentRepository` | Used by | `course_operations.py` calls `create`, `delete` |
| `ProposalService` | Used by | Proposal lifecycle for course operations (create, update status, get) |
| `ConfirmationService` | Used by | Token generation and validation for course deletion |
| `AuditService` | Used by | Writing course-level audit entries |
| `OutboxService` | Used by | Emitting `CourseCreatedByAI` and `CourseDeletedByAI` events |
| `AISessionRecord` | Used by | Active session counting and termination on course delete |
| Tool Registry (US-AI-005) | Extended by | Register `propose_create_course`, `apply_create_course`, `propose_delete_course`, `confirm_delete_course` |
| System Prompt (US-AI-042) | Updated by | Add course-level operation capabilities to agent instructions |
| Frontend AI Module (US-AI-024) | Extended by | Add course creation preview panel and course deletion confirmation modal |
| RAG Index (US-AI-015) | Triggered by | Remove course from RAG index on deletion |

---

## 3. NON-FUNCTIONAL REQUIREMENTS

### 3.1 Performance

| Metric | Target | Measurement |
|---|---|---|
| Course creation proposal (no DB write) | < 500ms p95 | Server-side timing of propose_create_course |
| Course creation apply (with welcome page) | < 2s p95 | Server-side timing of apply_create_course |
| Course deletion proposal (with dependency analysis) | < 1s p95 | Time to enumerate pages, components, and sessions |
| Course deletion apply (with cascade + audit + outbox) | < 5s for course with 50 pages | Time for full transactional deletion |
| Concurrent course creations | 10/s sustained | Under normal load (100 concurrent sessions) |
| Concurrent course deletions | 2/s sustained | Deletion is a heavy operation; rate limit conservatively |

### 3.2 Security

- **Confirmation token**: Cryptographically random (secrets.token_hex(32)), 64 hex characters. SHA256 hash stored in DB; plaintext returned only once in the proposal response.
- **Typed confirmation phrase**: For course deletion, the user must type the exact course title. Compared by SHA256 hash; the expected phrase is stored only for UI display and never used for verification comparison.
- **Authorization**: All course operations are scoped to the session's organization. A user may only create/delete courses within their own organization.
- **Input validation**: Course title max 200 chars, description max 500 chars, language must be in supported list, theme must be in supported enum, learning objectives max 10 items each max 200 chars.
- **No SQL injection**: All queries go through SQLAlchemy ORM parameterized queries.
- **Transaction isolation**: Use SERIALIZABLE isolation level for course deletion to prevent concurrent modifications during the deletion window.

### 3.3 Reliability

- **Idempotent apply**: `apply_create_course` with the same proposalId always creates the same course (re-check uniqueness; return existing courseId on duplicate attempt).
- **Transactional rollback**: All operations execute in a single database transaction. Any failure within the create or delete sequence rolls back the entire operation.
- **Outbox durability**: Outbox events are written in the same transaction as the mutation. If the outbox write fails, the mutation is rolled back.
- **Session termination on delete**: Active AI sessions on a deleted course are terminated with a reason code, preventing orphaned sessions from attempting operations on a nonexistent course.

### 3.4 Scalability

- **Large course deletion**: A course with 500+ pages must complete within 10 seconds. If the page count exceeds a configurable threshold (e.g., 200 pages), the deletion should be enqueued as an async workflow (US-AI-034) rather than executed synchronously.
- **Rate limiting**: Course creation must not exceed 10 per second per organization. Course deletion must not exceed 2 per minute per organization.
- **Storage**: Before-snapshots for course deletion may be large (a 50-page course serialized as full JSON could be 1-5 MB). Store in a separate `ai_audit_snapshots` table with S3/Blob storage for large objects, keeping only metadata references in the audit log table.

---

## 4. CURRENT STATE ASSESSMENT

### 4.1 What Exists

| Artifact | Status | Details |
|---|---|---|
| `CourseRecord` ORM model | EXISTS | `app/models/persisted_course.py` — fields: id, course_id, title, status, json_data, description, theme_json, custom_css, created_at, updated_at |
| `CourseRepository` | EXISTS | `app/repositories/course_repo.py` — methods: create, list, get, get_by_course_id, update_record, delete_record, upsert |
| Course CRUD routes | EXISTS | `app/routers/courses.py` — POST /courses (create), GET /courses (list), GET /courses/{courseId} (get), PATCH /courses/{courseId} (update), DELETE /courses/{courseId} (delete), PUT /courses/{courseId} (upsert) |
| `PageRecord` / `ComponentRecord` | EXISTS | `app/models/page_component.py` — pages and components with cascade delete |
| `PageRepository` / `ComponentRepository` | EXISTS | `app/repositories/page_component_repo.py` — list, get, create, update, delete, reorder |
| Proposal lifecycle | EXISTS (page-level) | US-AI-009/AI-010 implement proposal lifecycle for page operations |
| Confirmation token system | EXISTS (page-level) | US-AI-013 implements confirmation tokens for page deletion |
| Audit logging | EXISTS (page-level) | US-AI-010 implements audit logging for applied mutations |
| Outbox events | EXISTS (page-level) | US-AI-010/033 implement outbox events for downstream consumers |

### 4.2 What Must Be Created

| Artifact | Priority | Details |
|---|---|---|
| `app/ai/course_operations.py` | MUST | New service class with propose_create_course, apply_create_course, propose_delete_course, confirm_delete_course |
| Tool definitions (4 new tools) | MUST | `propose_create_course`, `apply_create_course`, `propose_delete_course`, `confirm_delete_course` registered in tool registry |
| Course creation preview panel (frontend) | MUST | UI component showing course metadata preview with create/cancel actions |
| Course deletion confirmation modal (frontend) | MUST | Typed-phrase confirmation modal with dependency impact report |
| System prompt update | SHOULD | Add course creation/deletion capabilities to agent instructions |
| RAG index removal on delete | COULD | If US-AI-015 (RAG) is implemented, add course removal from index on deletion |

### 4.3 What Must Be Modified

| Artifact | Change | Details |
|---|---|---|
| `ai_proposals` table | EXTEND | Add columns: operation_type (add 'course_create', 'course_delete' enum values), confirmation_phrase_hash, before_snapshot, after_candidate (if not already present) |
| Proposal status machine | EXTEND | Ensure course-level proposals follow the same state machine (pending_review -> applying -> applied, etc.) |
| Tool registry (US-AI-005) | EXTEND | Register 4 new tool schemas |
| AI session model | EXTEND | Add session termination reason and support for `terminated` status triggered by course deletion |
| Frontend AI module (US-AI-024) | EXTEND | Add course creation and deletion UI components and API client methods |
| Audit query interface (US-AI-020) | EXTEND | Support filtering by 'course_created_by_ai' and 'course_deleted_by_ai' operation types |

---

## 5. EXPANSION POINTS

### 5.1 Technical Expansion Points

1. **Async Course Deletion for Large Courses**: Currently specified as synchronous (within the request-response cycle). For courses exceeding a configurable page threshold (e.g., 200 pages, 1000 components), the deletion should be delegated to the durable workflow engine (US-AI-034) as an async `CourseDeletionWorkflow`. The proposal still gating the user confirmation synchronously, but the actual deletion runs as a background job with progress tracking.

2. **Course Template Duplication**: The `propose_create_course` tool could be extended with an optional `copyFromCourseId` parameter that clones all pages and components from an existing course into the new course shell. This enables AI-assisted course templating ("Create a new Python course similar to my existing JavaScript course structure"). The clone would deep-copy `PageRecord` and `ComponentRecord` rows, assign new UUIDs, and clear session-specific data (e.g., scores, completion data).

3. **Soft Delete with Undo Window**: Instead of hard-deleting courses immediately, the system could implement a "trash" or "soft-delete" pattern: mark the course as `deleted` with a 30-day retention window, move it to an archived schema, and provide an admin undo API within that window. The current specification hard-deletes for simplicity, but the audit snapshot already provides the data needed to implement a restoration proposal later.

4. **Batch Course Creation**: Allow the AI agent to propose creating multiple courses in a single proposal batch (e.g., "Create a full 6-module certification program with one course per module"). This reuses the batch proposal semantics from US-AI-029. Each course in the batch is created transactionally (all-or-nothing) or independently (best-effort).

### 5.2 Functional Expansion Points

1. **Course Metadata Update via AI**: After course creation, the AI agent should also support updating course metadata (title, description, language, theme, learning objectives) through the same propose/apply pattern. This is a natural extension: `propose_update_course` and `apply_update_course` tools, similar to `propose_update_page`.

2. **Course Duplication and Renaming**: Allow the AI to propose duplicating an existing course with a new title and courseId. This is pedagogically useful for creating variations of the same course for different audiences or languages. The duplication would include all pages, components, assets, and theme settings.

3. **Course Settings and Scoring Configuration**: Extend course creation to accept settings (autoplay, theme, duration) and scoring configuration (passing score, max attempts) directly from the AI proposal, rather than requiring the user to configure these manually after creation.

4. **AI Course Import from External Sources**: Extend course creation to accept a URL or file reference as source material. The AI would scrape or parse the external content (public URL, uploaded document) and create the course shell with pre-populated pages derived from the content. This integrates with US-AI-016 (File Upload) and US-AI-019 (Full Course from File).

---

## 6. VALIDATION & TESTING

### 6.1 Unit Tests

**UT-1 — `test_propose_create_course_success`**: Call `CourseOperationsService.propose_create_course` with valid metadata (title, description, language). Verify: (a) returns status "success", (b) returns a valid UUID `proposalId`, (c) `coursePreview` contains the expected title, description, and language, (d) `validationStatus` is "valid", (e) no `CourseRecord` was created (query the mock repository to confirm zero inserts).

**UT-2 — `test_propose_create_course_duplicate_id`**: Set up `CourseRepository.get_by_course_id` to raise `CourseNotFoundError` on first call (simulating unique courseId), then return an existing record on second call. Call `propose_create_course` with a title that produces a conflicting courseId. Verify: (a) returns status "error", (b) error code is `COURSE_ID_CONFLICT`, (c) `suggestedAlternative` is a non-empty string differing from the original courseId.

**UT-3 — `test_apply_create_course_creates_welcome_page`**: Mock `propose_create_course` to return a valid proposal. Call `apply_create_course(proposal_id, userConfirmed=True, createWelcomePage=True)`. Verify: (a) status is "created", (b) `CourseRepository.create` was called once, (c) `PageRepository.create` was called once (welcome page), (d) `ComponentRepository.create` was called once (default component), (e) `AuditService.log` was called with operation_type "course_created_by_ai", (f) `OutboxService.emit` was called with event_type "CourseCreatedByAI".

**UT-4 — `test_propose_delete_course_dependency_analysis`**: Set up a course with 3 pages (8 components total, 1 final-assessment page). Call `propose_delete_course` with the courseId. Verify: (a) returns status "success", (b) `dependencyReport.totalPages` is 3, (c) `dependencyReport.totalComponents` is 8, (d) `dependencyReport.assessmentPages` is 1, (e) `confirmationRequired` is true, (f) `confirmationTokenExpiresAt` is approximately 15 minutes from now.

**UT-5 — `test_confirm_delete_course_phrase_mismatch`**: Call `confirm_delete_course` with an intentionally wrong `confirmationPhrase`. Verify: (a) returns status "error", (b) error code is `CONFIRMATION_PHRASE_MISMATCH`, (c) no deletion occurred (mock `CourseRepository.delete_record` was not called), (d) `AuditService.log` was not called.

**UT-6 — `test_confirm_delete_course_token_expired`**: Set the `confirmation_token_expires_at` on the mock proposal to 20 minutes ago. Call `confirm_delete_course` with a valid phrase. Verify: (a) returns status "error", (b) error code is `TOKEN_EXPIRED`, (c) no deletion occurred.

**UT-7 — `test_confirm_delete_course_full_transaction`**: Set up a complete mock course with 3 pages and 5 components. Call `confirm_delete_course` with valid proposal, correct phrase, and unexpired token. Verify: (a) returns status "deleted", (b) `CourseRepository.delete_record` was called once, (c) `PageRepository.delete` was called 3 times, (d) `ComponentRepository.delete` was called 5 times, (e) `AuditService.log` was called with operation_type "course_deleted_by_ai" and before_snapshot containing all 3 pages, (f) `OutboxService.emit` was called with event_type "CourseDeletedByAI".

**UT-8 — `test_generate_course_id_sanitization`**: Call `_generate_course_id` with titles containing special characters, mixed case, and leading/trailing spaces. Verify: (a) "My Course!" produces "my-course", (b) "  Data Science 101: Intro  " produces "data-science-101-intro", (c) "$$$pecial!!!" produces "pecial", (d) result is at most 64 characters, (e) result matches `^[a-zA-Z0-9_-]+$`.

### 6.2 Integration Tests

**IT-1 — Course Create Then Delete via AI Tools**: Using a test database with all required tables:
1. Create an AI session with a valid course context (or null courseId for creation).
2. Call `propose_create_course` with title "Integration Test Course". Verify proposal returns.
3. Call `apply_create_course` with proposalId. Verify: (a) CourseRecord exists in database, (b) Welcome PageRecord exists in database, (c) Audit log has `course_created_by_ai` entry.
4. Call `propose_delete_course` with the created courseId. Verify proposal returns with dependency report.
5. Call `confirm_delete_course` with correct title phrase. Verify: (a) CourseRecord deleted, (b) PageRecord deleted, (c) ComponentRecord deleted, (d) Audit log has `course_deleted_by_ai` entry.

**IT-2 — Course Create Duplicate Detection**: Using a test database:
1. Create a course manually via `CourseRepository.create` with courseId "test-course".
2. Call `propose_create_course` with title that generates courseId "test-course". Verify `COURSE_ID_CONFLICT` error.
3. Call `propose_create_course` with `suggestedCourseId="test-course"`. Verify `COURSE_ID_CONFLICT` error.
4. Verify the original course still exists.

**IT-3 — Course Deletion With Active Session Termination**: Using a test database with `ai_sessions` table:
1. Create a course and an AI session for that course with status "active".
2. Call `propose_delete_course` then `confirm_delete_course` with valid inputs.
3. Verify: (a) The AI session record status changed to "terminated". (b) `terminated_reason` is "course_deleted".

**IT-4 — Double-Apply Idempotency for Course Creation**: Using a test database:
1. Create a valid course creation proposal.
2. Call `apply_create_course` — expect success with status "created".
3. Call `apply_create_course` again with the same proposalId. Verify: (a) Does not create a duplicate course, (b) Returns status "conflict" or "error" indicating the course already exists, (c) Only one `CourseRecord` with that courseId exists.

### 6.3 End-to-End Tests

**E2E-1 — Full AI Course Authoring Lifecycle**:
1. Open AI chat panel on an empty course list view.
2. Type: "Create a course on Project Management for Engineers".
3. Verify: AI generates metadata and shows creation preview panel with title, description, learning objectives.
4. Click "Create Course" with welcome page toggle ON.
5. Verify: Course appears in course list. Welcome page exists in course editor. Chat confirms creation.
6. Type: "Add a page on Risk Management basics".
7. Verify: AI proposes a text-content page; user confirms; page appears in editor.
8. Type: "Delete this course".
9. Verify: AI proposes deletion with dependency report (2 pages, 1+ components).
10. Type the course title in the confirmation input. Click "Permanently Delete Course".
11. Verify: Course removed from course list. Toast notification confirms deletion. Chat confirms.

**E2E-2 — Course Deletion With Stale Proposal Conflict**:
1. Create a course via AI with 2 pages (use E2E tools or seed data).
2. Propose deleting the course (do not confirm yet).
3. In a separate browser tab, manually add a third page to the same course.
4. Return to the AI chat tab and confirm the deletion.
5. Verify: System returns a "course has changed" conflict error with option to re-propose.
6. Click "Re-analyze". Verify: Updated proposal shows 3 pages. Confirm deletion. Verify course is deleted.

### 6.4 Manual QA Steps

1. **Course creation with empty required fields**: Attempt to create a course with an empty title. Verify the proposal returns a validation error on the `title` field. Verify the AI agent attempts to correct and retry.

2. **Course creation with very long title**: Provide a title of 250 characters. Verify the proposal returns a `TITLE_TOO_LONG` validation error (title max 200). Verify the AI agent truncates or asks for a shorter title.

3. **Course deletion with wrong typed phrase**: In the deletion confirmation modal, type a phrase that does not exactly match the course title (e.g., wrong case, extra space). Verify the "Delete" button remains disabled. Verify the error message "Typed confirmation phrase does not match the course title."

4. **Course deletion expired confirmation**: Propose deleting a course but wait 16 minutes (beyond the 15-minute token expiry). Verify the confirmation returns a `TOKEN_EXPIRED` error. Verify the UI shows a "Re-propose" option.

5. **Course list after mass deletion**: Create 5 courses via AI. Delete 3 of them. Verify the course list shows only the 2 remaining courses. Verify the audit log contains all 5 creation events and 3 deletion events.

6. **Verify no orphaned pages after course deletion**: Use a database query to confirm that after course deletion, no `PageRecord` or `ComponentRecord` rows reference the deleted `course_id`. Verify the cascade delete from `CourseRecord` -> `PageRecord` -> `ComponentRecord` works correctly.

7. **Verify welcome page content correctness**: Create a course with a very specific description. Verify the welcome page's default component body text matches the course description (or a reasonable summary).

---

## 7. DEFINITION OF DONE

This story is done when all of the following are verified:

1. [ ] `propose_create_course` tool is registered in the AI tool registry and accepts the input schema specified in Section 2.1, returning a valid proposal with course preview.
2. [ ] `apply_create_course` tool is registered, idempotent, and creates a `CourseRecord` in the database with all provided metadata only when `userConfirmed=true`.
3. [ ] Welcome page with a default component is optionally created in the same transaction as the course creation (controlled by `createWelcomePage` flag, default: true).
4. [ ] Course uniqueness validation rejects duplicate courseIds with `COURSE_ID_CONFLICT` error and suggests an alternative.
5. [ ] `propose_delete_course` tool is registered and returns a dependency impact analysis with total page/component/asset counts, active sessions, and assessment page count.
6. [ ] `confirm_delete_course` tool requires a typed confirmation phrase matching the exact course title (case-sensitive) before executing deletion.
7. [ ] Course deletion cascades to all `PageRecord`, `ComponentRecord`, and terminates active AI sessions for the deleted course.
8. [ ] Confirmation token for course deletion expires after 15 minutes (configurable via `AI_COURSE_DELETE_CONFIRM_TIMEOUT_MINUTES`).
9. [ ] Staleness detection catches courses modified between proposal and confirmation, returning 409 CONFLICT.
10. [ ] Audit log entries are written for every applied course creation and deletion with full before/after snapshots.
11. [ ] Outbox events `CourseCreatedByAI` and `CourseDeletedByAI` are emitted atomically with the database mutation.
12. [ ] Frontend course creation preview panel renders course metadata with title, description, language, learning objectives, and welcome page toggle.
13. [ ] Frontend course deletion confirmation modal shows dependency report, requires exact title typing, and disables the delete button until the typed phrase matches.
14. [ ] All unit tests (UT-1 through UT-8) pass with >90% code coverage on the `course_operations.py` service.
15. [ ] Integration tests (IT-1 through IT-4) pass against a test database with real PostgreSQL.
16. [ ] End-to-end tests (E2E-1 and E2E-2) pass in a staging environment.
17. [ ] Manual QA steps (1-7) pass with documented results.
18. [ ] Existing manual course CRUD tests continue to pass (no regression).
19. [ ] System prompt updated to include course-level operation capabilities.
20. [ ] Configuration variables documented and added to the environment configuration template.
21. [ ] `ai_proposals` table migration is backwards-compatible with existing page-level proposals.
22. [ ] All 4 new tool schemas are versioned in the tool contract registry.

---

## 8. TASKS & SUB-TASKS

| Task ID | Description | Effort | Dependencies | Assigned To |
|---|---|---|---|---|
| **T1** | **Implement Course Operations Service** | **2 days** | US-AI-004, US-AI-005, US-AI-010 | Backend Engineer |
| T1.1 | Create `app/ai/course_operations.py` with `CourseOperationsService` class | 4h | US-AI-004 (ai_proposals table) | |
| T1.2 | Implement `propose_create_course` method with validation and courseId generation | 3h | T1.1 | |
| T1.3 | Implement `apply_create_course` method with transactional course + welcome page creation | 4h | T1.1, US-AI-011 (PageRepository) | |
| T1.4 | Implement `propose_delete_course` method with dependency impact analysis | 3h | T1.1 | |
| T1.5 | Implement `confirm_delete_course` method with typed-phrase and token validation | 4h | T1.1, US-AI-013 (confirmation token patterns) | |
| T1.6 | Add course hash computation and staleness detection | 2h | T1.4 | |
| T1.7 | Integrate audit logging and outbox events for course operations | 2h | T1.3, T1.5, US-AI-010 | |
| **T2** | **Extend Database Schema** | **1 day** | US-AI-004 | Backend Engineer |
| T2.1 | Add migration for `ai_proposals` extension columns (operation_type, confirmation_phrase_hash, before_snapshot, after_candidate) | 2h | — | |
| T2.2 | Add migration for `ai_sessions` `status` and `terminated_reason` columns (if not already present) | 1h | — | |
| T2.3 | Add indices on `ai_proposals(operation_type)` and `ai_proposals(course_id)` | 1h | T2.1 | |
| T2.4 | Write rollback script for all new migrations | 2h | T2.1, T2.2, T2.3 | |
| **T3** | **Register Tools and Update System Prompt** | **0.5 day** | T1, US-AI-005, US-AI-042 | AI Platform Engineer |
| T3.1 | Register `propose_create_course` and `apply_create_course` tool schemas in tool registry | 1h | T1.2, T1.3 | |
| T3.2 | Register `propose_delete_course` and `confirm_delete_course` tool schemas in tool registry | 1h | T1.4, T1.5 | |
| T3.3 | Update system prompt with course-level operation capabilities | 1h | — | |
| T3.4 | Add course operation configuration variables to environment template | 1h | — | |
| **T4** | **Build Frontend UI Components** | **2 days** | T1, US-AI-024 | Frontend Engineer |
| T4.1 | Build course creation preview panel component (metadata display, welcome page toggle, create/cancel actions) | 5h | T1.2, T1.3 | |
| T4.2 | Build course deletion confirmation modal (dependency report, typed-phrase input, delete/cancel actions) | 5h | T1.4, T1.5 | |
| T4.3 | Add AI API client methods for the 4 new course operation tools | 2h | T3.1, T3.2 | |
| T4.4 | Integrate course creation flow: chat proposal -> panel display -> apply -> navigate to editor | 3h | T4.1, T4.3 | |
| T4.5 | Integrate course deletion flow: chat proposal -> modal -> confirm -> redirect to course list | 3h | T4.2, T4.3 | |
| T4.6 | Add error handling for all error paths (conflict, expired, mismatch, gone) | 2h | T4.4, T4.5 | |
| **T5** | **Write Tests and QA** | **1.5 days** | T1 | QA Engineer |
| T5.1 | Write unit tests UT-1 through UT-8 for course operations service | 4h | T1 | |
| T5.2 | Write integration tests IT-1 through IT-4 with test database | 3h | T2, T5.1 | |
| T5.3 | Write end-to-end tests E2E-1 and E2E-2 | 3h | T4 | |
| T5.4 | Execute manual QA checklist (7 steps) and document results | 2h | T4 | |
| T5.5 | Verify no regression in existing course CRUD and page-level AI tests | 2h | T5.1, T5.2 | |
