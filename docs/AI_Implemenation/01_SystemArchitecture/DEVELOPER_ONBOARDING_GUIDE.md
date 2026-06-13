# Developer Onboarding Guide: AI Course Authoring System

**Date:** 2026-06-13  
**Status:** Production Grade  
**Audience:** Backend Engineers, Frontend Engineers, DevOps, QA  
**Duration:** 2–4 hours for full onboarding  

---

## Quick Navigation

- **New to the project?** Start with [Architecture Overview](#architecture-overview)
- **Getting your dev environment?** Go to [Local Setup](#local-setup)
- **Working on a specific chunk?** See [Chunk Breakdown](#chunk-breakdown)
- **Debugging an issue?** Check [Troubleshooting](#troubleshooting)
- **Need API details?** Read [Tool Schemas](./TOOL_SCHEMAS_CLAUDE_NATIVE.md)
- **Running tests?** See [Testing Guide](#testing-guide)

---

## 1. Architecture Overview

### What We're Building

A **Claude-powered AI course authoring system** that helps educators create courses through conversational AI instead of manual page-by-page authoring. The system is:

- **Multi-tenant** (supports multiple organizations)
- **Production-safe** (all AI decisions are reviewed before applying)
- **SCORM-compliant** (exports to SCORM 1.2 / 2004)
- **Accessible** (WCAG 2.1 AA compliance)
- **Auditable** (all AI actions logged for compliance)

### Key Architecture Decision: Propose → Validate → Confirm → Apply

This is the **safety backbone** of the system:

```
User Request
    ↓
AI Proposes Change (proposal_id returned, no mutation)
    ↓
Frontend shows Diff/Preview to User (in UI modal)
    ↓
User Approves (user_confirmed=true)
    ↓
Frontend applies proposal (user explicitly requested this)
    ↓
AI Calls apply_* tool
    ↓
Database mutates ✅
```

**Why this pattern?** 
- AI cannot accidentally mutate data
- User has final say on every change
- Full audit trail for compliance

### Component Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (React)                          │
│  - CourseEditor: Manual or AI mode                          │
│  - AIChat Panel: Chat with Claude                            │
│  - Diff Preview: Show AI changes before apply               │
└────────────────────────┬────────────────────────────────────┘
                         │ REST API
                         ↓
┌─────────────────────────────────────────────────────────────┐
│                  Backend API (FastAPI)                       │
│  - Session Manager: Scope & lifecycle                        │
│  - Tool Registry: Template & schema definitions             │
│  - Validator: Business rules enforcement                     │
│  - Permission Layer: Multi-tenant scoping                    │
└────────────────┬─────────────────────────┬──────────────────┘
                 │                         │
                 ↓ Anthropic API           ↓ PostgreSQL
           ┌──────────────┐           ┌──────────────┐
           │ Claude Model │           │  Database    │
           │  (Sonnet)    │           │ (Courses,    │
           └──────────────┘           │  Pages, etc) │
                                      └──────────────┘
```

### Data Flow Example: Propose Creating a Page

```
Frontend (AIChat)
  │
  ├─→ POST /api/v1/ai/tools/propose_create_page
  │      Headers: Authorization: Session {sessionId}
  │      Body: {
  │        "title": "Introduction",
  │        "template_type": "text-content",
  │        "data": { ... }
  │      }
  │
  ↓
Backend (Session Middleware)
  1. Validates session exists and not expired
  2. Checks user has access to course_id
  3. Forwards to tool handler
  │
  ↓
Backend (Validator)
  1. Validates template data against schema
  2. Validates business rules (min/max items, etc.)
  3. Validates accessibility (WCAG)
  │
  ↓
Response Back to Frontend
  {
    "proposal_id": "xyz123",
    "preview_page": { ... },
    "validation_status": "valid",
    "validation_messages": []
  }
  │
  ↓
Frontend (UI Modal)
  Shows preview and asks user: "Create this page?"
  │
  ├─ User clicks "Create"
  │      │
  │      ↓
  │  POST /api/v1/ai/tools/apply_page_proposal
  │       Headers: Authorization: Session {sessionId}
  │       Body: {
  │         "proposal_id": "xyz123",
  │         "user_confirmed": true
  │       }
  │
  └─→ Page created in database ✅
```

---

## 2. Local Setup

### Prerequisites

- **Python 3.10+** (for backend)
- **Node.js 18+** (for frontend)
- **Docker + Docker Compose** (for PostgreSQL, Redis)
- **Git** (version control)
- **VS Code** (recommended editor with Python + TypeScript extensions)

### Step 1: Clone Repository

```bash
# If the frontend repo is not already present locally:
git clone https://github.com/your-org/e-learning-frontend.git
cd e-learning-frontend

# If you already have the frontend workspace locally, use that path instead:
# cd C:\Users\ADMIN\e-learning-frontend
```

### Step 2: Set Up Backend

```bash
# Create Python virtual environment
python -m venv venv

# Activate it
source venv/bin/activate  # macOS/Linux
# or
venv\Scripts\activate  # Windows PowerShell

# Install dependencies
pip install -r requirements.txt

# Copy env template
cp .env.example .env

# Edit .env with local settings
# Key variables:
#   DATABASE_URL=postgresql://user:password@localhost:5432/elearning
#   REDIS_URL=redis://localhost:6379/0
#   ANTHROPIC_API_KEY=sk-ant-...
#   AI_AUTHORING_ENABLED=true  (for dev)
```

### Step 3: Set Up Database

```bash
# Start Docker containers (PostgreSQL + Redis)
docker-compose up -d

# Run migrations
alembic upgrade head

# Seed test data (optional)
python scripts/seed_db.py
```

### Step 4: Start Backend Server

```bash
# From project root, in venv
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Server should be at http://localhost:8000
# API docs at http://localhost:8000/docs (Swagger UI)
```

### Step 5: Set Up Frontend

```bash
# In another terminal, from project root
cd frontend/

# Install dependencies
npm install

# Start dev server
npm run dev

# Frontend at http://localhost:3000
```

### Step 6: Verify Setup

```bash
# Test backend health
curl http://localhost:8000/health

# Test frontend loads
open http://localhost:3000

# Check feature flag
curl http://localhost:8000/api/v1/ai/feature-status
# Should show: { "aiAuthoringEnabled": true }
```

---

## 3. Architecture Concepts

### Session Management

A **session** is a scoped container for one user's AI authoring work on one course.

**Key Properties:**
- **Immutable course_id:** Once created, session cannot switch courses
- **24h expiry:** Sessions automatically cleanup after 24 hours
- **Single user:** User_id is baked into session (no sharing)
- **Authorization header:** All tool calls require `Authorization: Session {sessionId}`

**When is a session created?**
- User clicks "✨ Build with AI" button in course editor
- Frontend POSTs to `/api/v1/ai/sessions` with user_id, course_id, org_id
- Backend creates session and returns session_id
- Frontend stores session_id in localStorage

**When is a session ended?**
- User clicks "Exit AI Mode"
- Session expires after 24 hours (automatic cleanup)
- User logs out

**Why sessions?**
- Prevents AI from accidentally mutating wrong course
- Enforces permission boundaries (can only access own course)
- Provides clear scope for logging and audit trails
- Enables rate limiting per user

### State Management Rule: DB is Always Source of Truth

**Critical:** The AI (Claude) must **never assume state from conversation history**.

❌ **WRONG:**
```
User: "Create a page with title 'Intro'"
AI: "I'll add this page to your course which currently has 3 pages..."
   (AI is using conversation history, not fresh DB state)
```

✅ **RIGHT:**
```
User: "Create a page with title 'Intro'"
AI: Call list_pages (with session header)
   → Response: pages array with latest count from DB
AI: "I can see your course currently has 3 pages. I'll add page 4."
```

**Rule of Thumb:**
- Before EVERY edit (create/update/delete): Call list_pages or fetch_page first
- Parse response to understand current state
- Only then propose changes based on actual DB state
- This prevents race conditions if multiple sessions active simultaneously

### Permission Scoping

Every API call is validated at **two levels**:

**Level 1: Session Middleware**
```python
# In app/middleware/session_middleware.py
def validate_session_scope(request):
    session = session_manager.get_session(session_id)
    if not session:
        raise 401 Unauthorized
    request.state.session = session
    # session now available to route handlers
```

**Level 2: Route Handler**
```python
# In each route handler
@router.post("/tools/fetch_page")
def fetch_page(page_id: str, session = Depends(get_session)):
    # Verify page belongs to session's course
    page = db.query(Page).filter(
        Page.id == page_id,
        Page.course_id == session.course_id  # ← KEY CHECK
    ).first()
    
    if not page:
        raise 403 Forbidden  # Not 404 to avoid info leak
```

**What this prevents:**
- User A cannot see/edit user B's courses
- Multi-tenant data leakage
- Accidental cross-organization modifications

---

## 4. Chunk Breakdown

### Phasing Strategy

The AI authoring system is built in **10 chunks**, roughly 3 sprints (2 weeks each).

Each chunk is **independently deployable** and **tested before moving to next chunk**.

```
Week 1 (Sprint 1):
  Chunk 0: Foundation & Feature Flag      ← You are here
  Chunk 1: Template Registry & Schemas
  Chunk 2: Session & State Management

Week 2 (Sprint 2):
  Chunk 3: Validation & Gating Pipeline
  Chunk 4: Propose/Apply Patterns
  Chunk 5: File Ingestion Pipeline

Week 3 (Sprint 3):
  Chunk 6: Claude Integration (System Prompt)
  Chunk 7: Tool Execution & Error Handling
  Chunk 8: Rate Limiting & Cost Controls
  Chunk 9: Production Hardening
  Chunk 10: Full E2E Testing & Launch
```

### Working on a Specific Chunk

**Each chunk has:**
1. **Detailed task breakdown** (CHUNK_0-2_DETAILED_TASK_BREAKDOWNS.md)
2. **E2E test cases** (E2E_TEST_CASE_TEMPLATES.md)
3. **Sign-off criteria** (must all pass before next chunk)

**Your workflow per chunk:**

```
1. Read CHUNK_{N}-{N+2}_DETAILED_TASK_BREAKDOWNS.md
   ↓
2. Understand subtasks, acceptance criteria, time estimates
   ↓
3. Create feature branch: git checkout -b chunk-{n}-{feature}
   ↓
4. Implement code (follow best practices below)
   ↓
5. Write tests (unit + E2E from templates)
   ↓
6. Run full test suite: npm run test && npx cypress run
   ↓
7. Submit PR for code review
   ↓
8. After approval, merge to main
   ↓
9. QA runs E2E test cases from templates
   ↓
10. If all tests pass: chunk signed off, move to next chunk
```

### Chunk Dependencies

```
Chunk 0 ← Feature flag, env config, logging
  ↓
Chunk 1 ← Template registry (depends on Chunk 0)
  ↓
Chunk 2 ← Session management (depends on Chunks 0–1)
  ↓
Chunk 3 ← Validation pipeline (depends on Chunks 0–2)
  ↓
Chunks 4–10 ← Depend on Chunks 0–3
```

**Key**: Don't start Chunk N+1 until Chunk N is fully signed off.

---

## 5. Development Best Practices

### Code Organization

**Backend (FastAPI):**
```
app/
├── main.py              # FastAPI app instance
├── config.py            # Settings & env variables
├── middleware/
│   └── session_middleware.py  # Session validation
├── models/
│   ├── course.py        # SQLAlchemy models
│   ├── page.py
│   ├── template_definition.py
│   └── session_context.py
├── services/
│   ├── session_manager.py     # Session lifecycle
│   ├── template_registry.py   # Template definitions
│   ├── ai_validator.py        # Schema validation
│   ├── ai_config.py           # Model config
│   └── ai_logging.py          # Audit logging
├── routers/
│   ├── ai_sessions.py         # /api/v1/ai/sessions
│   ├── ai_templates.py        # /api/v1/ai/templates
│   ├── ai_tools.py            # /api/v1/ai/tools/*
│   ├── courses.py             # /api/v1/courses
│   └── pages.py               # /api/v1/pages
└── tests/
    ├── test_session_manager.py
    ├── test_template_registry.py
    └── e2e/                    # Playwright tests
```

**Frontend (React):**
```
src/
├── context/
│   └── AISessionContext.tsx    # Session state
├── components/
│   ├── CourseEditor/
│   │   ├── CourseEditor.tsx
│   │   ├── AIChat Panel.tsx
│   │   ├── DiffPreview.tsx
│   │   └── ProposalModal.tsx
│   └── Common/
│       └── ...
├── services/
│   ├── apiClient.ts           # HTTP client (with session header)
│   └── aiToolsClient.ts       # AI tools API wrapper
└── tests/
    ├── unit/
    └── e2e/
```

### Security Checklist

Before submitting ANY PR:

- [ ] **No secrets in code** (API keys, passwords) → use `.env`
- [ ] **No hardcoded user IDs** → use `getCurrentUserId()` from auth context
- [ ] **Session validation** every route → check `Depends(get_session)`
- [ ] **Permission scoping** enforced → verify course_id matches session
- [ ] **No cross-tenant data leak** → filters include organization_id
- [ ] **Input validation** → all user inputs validated before DB
- [ ] **Error messages** don't leak info → no table names, no user emails

### Code Review Checklist

When reviewing a PR:

```
Architecture:
  ☐ Follows chunk specification
  ☐ Doesn't break existing chunks
  ☐ Session/permission scoping correct
  
Correctness:
  ☐ All tests pass
  ☐ No security issues
  ☐ Edge cases handled
  
Performance:
  ☐ No N+1 queries
  ☐ Caching used where appropriate
  ☐ No unnecessary API calls
  
Documentation:
  ☐ Code commented where complex
  ☐ E2E tests written
  ☐ README updated if needed
```

---

## 6. Testing Guide

### Unit Tests

**Backend (pytest):**
```bash
# Run all tests
pytest

# Run specific file
pytest tests/test_session_manager.py

# Run with coverage
pytest --cov=app --cov-report=html

# Run only Chunk 0 tests
pytest tests/ -k "chunk0"
```

**Frontend (Jest):**
```bash
# Run all tests
npm run test

# Watch mode (re-run on file change)
npm run test:watch

# With coverage
npm run test:coverage
```

### E2E Tests

```bash
# Open Cypress UI (recommended for dev)
npx cypress open

# Run headless (for CI)
npx cypress run

# Run specific test file
npx cypress run --spec "cypress/e2e/chunk0-feature-flag.cy.ts"

# Run with specific browser
npx cypress run --browser chrome
```

### Test Naming Conventions

**Unit Tests:**
```python
# tests/test_session_manager.py
def test_session_creation():
    """Session is created with correct defaults."""

def test_session_scope_enforcement():
    """Cannot access pages from different course."""

def test_session_expiry_cleanup():
    """Expired sessions are removed automatically."""
```

**E2E Tests:**
```typescript
// cypress/e2e/chunk0-feature-flag.cy.ts
describe("Chunk 0: Feature Flag", () => {
  it("TC-CH0-FEATURE_FLAG-DISABLED: AI button hidden when disabled", () => {
    // ...
  });
});
```

**Naming:** `test_` (Python) or `it(...)` (TypeScript), with clear description of what's being tested.

---

## 7. Debugging Guide

### Common Issues

#### Issue: "Session invalid or expired"

**Symptom:**
```
POST /api/v1/ai/tools/list_pages
Error: 401 Unauthorized - Session invalid or expired
```

**Causes & Fixes:**
1. Session header missing
   ```bash
   # Wrong:
   curl http://localhost:8000/api/v1/ai/tools/list_pages
   
   # Right:
   curl -H "Authorization: Session abc123" \
     http://localhost:8000/api/v1/ai/tools/list_pages
   ```

2. Session ID incorrect or expired
   ```javascript
   // In frontend console:
   console.log(localStorage.getItem("ai_session"));
   // Should show: { sessionId: "xyz123", ... }
   ```

3. Backend not restarted after Chunk 2 deployment
   ```bash
   # Restart backend
   docker restart api  # or ctrl-c and restart uvicorn
   ```

#### Issue: "You do not have permission to access this page"

**Symptom:**
```
POST /api/v1/ai/tools/fetch_page
Error: 403 Forbidden - You do not have permission to access this page
```

**Causes & Fixes:**
1. Trying to access page from wrong course
   ```
   Session-1 scoped to course-1
   Trying to fetch page from course-2 → 403
   ```
   **Fix:** Verify page_id belongs to session's course_id

2. Cross-tenant permission issue
   ```
   Org-A user trying to access Org-B page → 403
   ```
   **Fix:** Ensure user_id and org_id match in session creation

#### Issue: "Validation error: max_length_exceeded"

**Symptom:**
```json
{
  "status": "error",
  "code": "VALIDATION_ERROR",
  "message": "Page title exceeds max length (200 characters)"
}
```

**Fix:**
```typescript
// Check template schema constraints
const schema = await fetch("/api/v1/ai/templates/registry")
  .then(r => r.json());

const titleSchema = schema.templates["text-content"].schema.properties.title;
console.log(titleSchema); // { type: "string", maxLength: 200 }

// Truncate input
const title = userInput.slice(0, 200);
```

### Debugging Tools

**Backend:**
```python
# Add debug logging
import logging
logger = logging.getLogger(__name__)

def my_function(x):
    logger.debug(f"Processing: {x}")  # Won't appear in tests
    logger.info(f"Result: {x * 2}")   # Always logged
    return x * 2

# Run with debug output
python -c "import logging; logging.basicConfig(level=logging.DEBUG)" && pytest
```

**Frontend:**
```typescript
// Add console logging
console.log("Session:", session);
console.log("Pages:", pages);

// Check network requests (DevTools → Network tab)
// All requests should have Authorization header

// Check localStorage
console.log(localStorage.getItem("ai_session"));
```

**Database:**
```bash
# Connect to DB and inspect data
docker exec -it postgres psql -U user -d elearning

# Inside psql:
SELECT * FROM courses LIMIT 5;
SELECT * FROM pages WHERE course_id = 'course-1';
SELECT * FROM sessions LIMIT 1;
```

---

## 8. Key Files & Documentation

### Essential Reading (in order)

1. **PRODUCTION_READY_AI_AUTHORING_ARCHITECTURE.md** (30 pages)
   - Complete architecture specification
   - Read before starting any Chunk 0+

2. **TOOL_SCHEMAS_CLAUDE_NATIVE.md** (550 lines)
   - All 12 tool definitions in Claude format
   - Reference when building tool handlers

3. **CHUNK_0-2_DETAILED_TASK_BREAKDOWNS.md** (specific to your chunk)
   - Detailed subtasks, acceptance criteria, time estimates
   - Your spec for what to implement

4. **E2E_TEST_CASE_TEMPLATES.md** (test cases)
   - Templates and examples for testing your chunk
   - Use for manual QA or automation

5. **openapi-v3.1-complete.yaml** (API reference)
   - Backend API specification
   - Reference for existing endpoints

### Code Examples

**Creating a session (backend):**
```python
# app/routers/ai_sessions.py
from app.services.session_manager import session_manager

@router.post("")
def create_session(request: CreateSessionRequest):
    session = session_manager.create_session(
        user_id=request.user_id,
        course_id=request.course_id,
        organization_id=request.organization_id,
    )
    return {
        "sessionId": session.session_id,
        "expiresAt": session.expires_at.isoformat(),
    }
```

**Fetching pages with session scope (backend):**
```python
# app/routers/ai_tools.py
@router.post("/tools/list_pages")
async def list_pages(session: SessionContext = Depends(get_session)):
    # Session middleware already verified session is valid
    # Now query only pages from session's course
    pages = db.query(Page).filter(
        Page.course_id == session.course_id
    ).all()
    
    return {
        "pages": [
            {
                "page_id": p.id,
                "title": p.title,
                "template_type": p.template_type,
            }
            for p in pages
        ]
    }
```

**Using session in frontend:**
```typescript
// src/components/AIChat Panel.tsx
import { useAISession } from "../context/AISessionContext";

export function AIChatPanel() {
  const { session, createSession, isSessionActive } = useAISession();
  const { courseId } = useParams();

  useEffect(() => {
    if (!session && courseId) {
      createSession(courseId);
    }
  }, []);

  const callTool = async (toolName: string, input: any) => {
    const response = await fetch(
      `/api/v1/ai/tools/${toolName}`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Session ${session.sessionId}`,
        },
        body: JSON.stringify(input),
      }
    );
    return response.json();
  };

  return <div>{/* Chat UI */}</div>;
}
```

---

## 9. Glossary

| Term | Definition |
|------|-----------|
| **Session** | Scoped container for one user's AI authoring work on one course; immutable course_id, 24h expiry |
| **Proposal** | AI-generated change (create/update/delete); requires user approval before apply |
| **Apply** | Execute a proposal; mutates database; requires user_confirmed=true |
| **Template Type** | One of 5 allowed types: text-content, tabs, accordion, click-reveal, final-assessment |
| **Tool** | Claude-callable function; 12 tools for session, page, validation operations |
| **Chunk** | Sprint-sized deliverable (1–2 days); 10 chunks total for full phasing |
| **Source of Truth** | Database (PostgreSQL) is always the authoritative state; AI must re-fetch before edit |
| **Permission Scoping** | Multi-tenant enforcement: user can only access own organization's courses |
| **Feature Flag** | Environment variable to enable/disable AI features (off by default) |
| **Propose-Validate-Confirm-Apply** | Safety pattern: AI proposes → DB validates → user confirms → applies |

---

## 10. Getting Help

### Where to Find Answers

| Question | Resource |
|----------|----------|
| "What tool should I use?" | TOOL_SCHEMAS_CLAUDE_NATIVE.md |
| "How do I implement [feature]?" | CHUNK_{N}_DETAILED_TASK_BREAKDOWNS.md |
| "What tests do I need?" | E2E_TEST_CASE_TEMPLATES.md |
| "What's the architecture?" | PRODUCTION_READY_AI_AUTHORING_ARCHITECTURE.md |
| "How do I test locally?" | This document (Local Setup section) |
| "What endpoints exist?" | openapi-v3.1-complete.yaml |

### Asking for Help

**In PRs:**
```
@backend-lead I'm working on Chunk 1, Task 1.2 (validator module).
Can you review the schema validation logic? 
It should reject < 2 tabs per the spec.

PR: #123
```

**On Slack:**
```
"Working on Chunk 0 feature flag. Got `ModuleNotFoundError` on config.py import.
Backend not restarted since I pushed code. Already ran `docker restart api`.
Error: ..."
```

---

## 11. Checklist: Your First Week

**Day 1:**
- [ ] Clone repo and get local setup running
- [ ] Read PRODUCTION_READY_AI_AUTHORING_ARCHITECTURE.md (sections 1–5)
- [ ] Understand the Session → Tools → Validation flow (draw a diagram!)

**Day 2:**
- [ ] Read CHUNK_0-2_DETAILED_TASK_BREAKDOWNS.md for your assigned chunk
- [ ] Create feature branch and start first task
- [ ] Ask clarifying questions in PR comments

**Day 3–4:**
- [ ] Implement all subtasks for your chunk
- [ ] Run tests (unit + E2E)
- [ ] Submit PR for code review

**Day 5:**
- [ ] Incorporate feedback from code review
- [ ] All tests pass
- [ ] QA runs E2E test cases
- [ ] Chunk signed off and merged to main

---

## 12. Appendix: Key Repositories

**Backend API:**
- Location: `app/` directory
- Language: Python 3.10+
- Framework: FastAPI + SQLAlchemy
- Tests: pytest + Playwright
- Docs: Auto-generated at `/docs`

**Frontend:**
- Location: `src/` directory
- Language: TypeScript 4.9+
- Framework: React 18+
- Tests: Jest + Cypress
- Build: Vite

**Deployment:**
- Staging: [staging-url]
- Production: [prod-url]
- CI/CD: GitHub Actions (see `.github/workflows/`)

---

*Document Version: 1.0*  
*Status: Production Grade*  
*Last Updated: 2026-06-13*  
*Maintained By: AI Architecture Team*
