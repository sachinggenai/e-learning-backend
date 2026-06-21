# US-PEND-008: Fix FK Type Mismatch — UUID → Integer

| Field | Value |
|-------|-------|
| **Type** | 🐛 Bug |
| **Priority** | 🟡 HIGH |
| **Batch** | 2 — Config/Migration Fixes |
| **Depends On** | None |
| **Estimated Effort** | 30 minutes |
| **Target Files** | `app/models/workflow.py:141-145`, `alembic/versions/20260620_0002_create_workflow_tables.py:103-105` |

---

## User Story

**As a** DBA reviewing the database schema,  
**I want** foreign key constraints to reference columns of matching types,  
**So that** PostgreSQL can enforce referential integrity between workflow_jobs and ai_sessions.

---

## Intent of Work

`workflow_jobs.session_id` is typed `PG_UUID` (UUID), but it references `ai_sessions.id` which is `Integer` (auto-increment). PostgreSQL will reject this FK constraint because the types don't match. The migration already has conditional logic that silently skips FK creation if `ai_sessions` doesn't exist — but even if it exists, the type mismatch prevents constraint creation.

**Fix:** Change `session_id` FK to reference `ai_sessions.session_id` (a `String(64)` business ID column), or change `workflow_jobs.session_id` to `Integer`, or explicitly remove the FK and document that referential integrity is handled at the application layer.

**Recommendation:** Reference `ai_sessions.session_id` (String) since the workflow stores business IDs throughout.

---

## Current State

```python
# app/models/workflow.py, lines 141-145
session_id: Mapped[Optional[_uuid.UUID]] = mapped_column(
    PG_UUID(as_uuid=True),                                    # UUID type
    ForeignKey("ai_sessions.id", ondelete="SET NULL"),        # References Integer column
    nullable=True,
)
```

```python
# Migration file, lines 103-105
op.create_foreign_key(
    "fk_wf_jobs_session", "workflow_jobs",
    "ai_sessions", ["session_id"], ["id"],                    # UUID → Integer mismatch
    ondelete="SET NULL"
)
```

**Facts confirmed (2026-06-21):**
- `ai_sessions` table: `id` = `Integer` (auto-increment PK), `session_id` = `String(64)` (business ID)
- `workflow_jobs.session_id` = `PG_UUID(as_uuid=True)`
- Postgres does NOT allow FK between UUID and Integer columns
- Migration uses conditional FK creation (checks if `ai_sessions` exists first)

---

## Expected State

**Option A (Recommended):** Reference business ID column
```python
session_id: Mapped[Optional[str]] = mapped_column(
    String(64),
    ForeignKey("ai_sessions.session_id", ondelete="SET NULL"),
    nullable=True,
)
```

**Option B:** Remove FK, enforce at application layer
```python
session_id: Mapped[Optional[str]] = mapped_column(
    String(64),
    nullable=True,
    comment="References ai_sessions.session_id (enforced at app layer)",
)
```

---

## Technical Details

### Analysis

`ai_sessions` model has two identifier columns:
- `id`: `Integer`, auto-increment, primary key (internal)
- `session_id`: `String(64)`, unique, business identifier (external)

The workflow engine uses business IDs everywhere (`job_id` is UUID, `course_id` is string business ID). `session_id` in the workflow context refers to the AI session's business ID, not its internal integer PK. So changing to `String(64)` referencing `ai_sessions.session_id` is correct.

### Implementation Steps (Option A)

1. Open `app/models/workflow.py`
2. Line 141: Change type from `Optional[_uuid.UUID]` to `Optional[str]`
3. Line 143: Change `PG_UUID(as_uuid=True)` to `String(64)`
4. Line 144: Change `ForeignKey("ai_sessions.id", ...)` to `ForeignKey("ai_sessions.session_id", ...)`
5. Update migration file line 103-105: Change column type from `sa.UUID()` to `sa.String(64)`, reference `session_id` instead of `id`

### Scope Boundary

- **IN SCOPE:** Fix column type + FK reference in model and migration
- **OUT OF SCOPE:** Changing `ai_sessions` schema, other FKs in workflow tables

---

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-1 | `workflow_jobs.session_id` column type matches `ai_sessions.session_id` (String) |
| AC-2 | Foreign key constraint creates successfully in PostgreSQL (or is explicitly documented as app-layer) |
| AC-3 | Existing `session_id` values in workflow jobs are valid strings |
| AC-4 | SQLAlchemy model reflects the correct type |

---

## Functional Expectations

- Workflow jobs can be associated with AI sessions
- `ON DELETE SET NULL` works: deleting a session nullifies the job's session_id
- Application code using `job.session_id` receives a string, not a UUID object

## Non-Functional Expectations

- Migration is cleanly reversible
- No data loss (column is nullable, existing rows get NULL)

---

## Validation Steps

```bash
# 1. Check ai_sessions.session_id type
python -c "
from app.models.ai_models import AISession
print(f'session_id type: {AISession.session_id.type}')  # Should be String(64)
print(f'id type: {AISession.id.type}')  # Should be Integer
"

# 2. Check workflow_jobs.session_id type after fix
python -c "
from app.models.workflow import WorkflowJob
print(f'session_id type: {WorkflowJob.session_id.type}')  # Should be String(64)
"

# 3. Run migration on test DB and verify FK
alembic upgrade head
psql -c "SELECT conname, contype FROM pg_constraint WHERE conname = 'fk_wf_jobs_session';"
# Should show 'f' (foreign key) type
```
