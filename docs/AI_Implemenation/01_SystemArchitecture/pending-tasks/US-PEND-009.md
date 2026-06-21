# US-PEND-009: Fix 3 Migration Schema Issues

| Field | Value |
|-------|-------|
| **Type** | 🐛 Bug |
| **Priority** | 🟢 MEDIUM |
| **Batch** | 2 — Config/Migration Fixes |
| **Depends On** | None |
| **Estimated Effort** | 30 minutes |
| **Target File** | `alembic/versions/20260620_0002_create_workflow_tables.py` |

---

## User Story

**As a** DBA deploying schema migrations to production,  
**I want** the migration DDL to produce column types that match the SQLAlchemy ORM models exactly,  
**So that** there are no type mismatch surprises, silent data truncation, or JSON deserialization errors.

---

## Intent of Work

The migration file `20260620_0002_create_workflow_tables.py` has 3 schema issues that diverge from the ORM model definitions:

1. **JSONB `server_default="{}"`** (line 55): Produces a PostgreSQL text literal `'{}'` instead of `'{}'::jsonb`. When SQLAlchemy reads the column, it may attempt to deserialize a string as JSON, causing a type error.

2. **`sa.REAL()` vs `Float`** (line 56): Migration uses `sa.REAL()` (single-precision float4). The ORM model uses `Float` (double-precision float8). Values written as float4 lose precision when read back as float8.

3. **Conditional FK** (line 99-105): Migration checks if `ai_sessions` table exists. If created later by `Base.metadata.create_all()`, the FK is never added. The ORM model's `ForeignKey` annotation has no corresponding database constraint.

---

## Current State

```python
# Migration file line 55
sa.Column("checkpoint_data", JSONB(), nullable=False, server_default="{}"),
# BUG: "{}" is text, not jsonb. Should be sa.text("'{}'::jsonb")

# Migration file line 56
sa.Column("progress", sa.REAL(), nullable=False, server_default="0"),
# BUG: REAL is float4. ORM model line 103 uses Float (float8)

# Migration file lines 99-105
if 'ai_sessions' in inspector.get_table_names():
    op.create_foreign_key("fk_wf_jobs_session", ...)
# BUG: Silently skips FK if table doesn't exist at migration time
```

**Facts confirmed (2026-06-21):**
- ORM model `workflow.py:103`: `progress: Mapped[float] = mapped_column(Float, ...)`
- `Float` in SQLAlchemy defaults to `Float(precision=None)` → float8 (double precision)
- `sa.REAL()` → float4 (single precision, ~7 significant digits)
- `server_default="{}"` produces text default, not JSONB default

---

## Expected State

```python
# Fix 1: Proper JSONB default
sa.Column("checkpoint_data", JSONB(), nullable=False,
          server_default=sa.text("'{}'::jsonb")),

# Fix 2: Consistent float type
sa.Column("progress", sa.Float(), nullable=False, server_default="0"),

# Fix 3: Document conditional FK with explicit comment
# NOTE: FK to ai_sessions skipped if table missing (created later by create_all)
# The application layer enforces referential integrity via repository validation
```

---

## Technical Details

### Implementation Steps

1. Open migration file
2. Line 55: Change `server_default="{}"` → `server_default=sa.text("'{}'::jsonb")`
3. Line 56: Change `sa.REAL()` → `sa.Float()`
4. Lines 99-105: Add comment explaining conditional FK; optionally remove conditional and always create FK (if deployment guarantees `ai_sessions` exists before workflow tables)
5. Re-run migration: `alembic downgrade -1 && alembic upgrade head`

### Scope Boundary

- **IN SCOPE:** Fix 3 DDL issues in migration file
- **OUT OF SCOPE:** Changing ORM models, adding new migrations

---

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-1 | `checkpoint_data` column default is `'{}'::jsonb` (proper JSONB type) in PostgreSQL |
| AC-2 | `progress` column type is `double precision` (float8) matching ORM model |
| AC-3 | Migration downgrades cleanly: `alembic downgrade -1` succeeds |
| AC-4 | Migration upgrades cleanly: `alembic upgrade head` succeeds |

---

## Functional Expectations

- New workflow jobs get `checkpoint_data = {}` as a JSONB object (not text)
- Progress values (0.0-1.0) stored and retrieved without precision loss
- FK behavior is documented and understood by the team

## Non-Functional Expectations

- Zero changes to ORM model behavior
- Migration remains reversible

---

## Validation Steps

```bash
# 1. Verify column types in PostgreSQL after migration
psql -c "
SELECT column_name, data_type, udt_name, column_default
FROM information_schema.columns
WHERE table_name = 'workflow_jobs'
  AND column_name IN ('checkpoint_data', 'progress');
"
# Expected: checkpoint_data = jsonb, progress = double precision

# 2. Test JSONB default behavior
psql -c "INSERT INTO workflow_jobs (job_id, workflow_type) VALUES (gen_random_uuid(), 'test') RETURNING checkpoint_data;"
# Expected: {} (jsonb object, not string)

# 3. Verify migration is reversible
alembic downgrade -1
alembic upgrade head
```
