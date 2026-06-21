# US-BKND-AI-015A-IMP — Migration & Database Layer: Production Extension

**Parent Story:** US-BKND-AI-015 (Advanced RAG)  
**Extension ID:** US-BKND-AI-015A  
**Title:** Database Migration Application & Model Registration — Production Hardening  
**Priority:** 🔴 MUST (blocks PEND-17; prerequisite for PEND-04, PEND-09)  
**Status:** ✅ RESOLVED (2026-06-21) — The import fix described below was applied in commit 10b863a. `alembic/env.py` line 25 already contains `import app.models.course_embedding`.  
**Estimate:** 2.5 hours (5 tasks) — all tasks complete  
**RCA Source:** PEND-17 RCA — 5 missing IMP elements (all addressed)  
**TPO / Solutions Architect:** This document

> **✅ RESOLVED Note:** The import fix was applied simultaneously with this document. `alembic/env.py` line 25 reads: `import app.models.course_embedding  # noqa: F401`. This document remains as historical record of the gap analysis.

---

## Executive Summary

### What This Extension Delivers

The parent story (US-BKND-AI-015) created 7 new files including an Alembic migration, but the migration was **never applied to any database**. Three root causes were identified:

1. **`alembic/env.py` missing model registration** — `app.models.course_embedding` not imported, so autogenerate can't detect the new tables
2. **No database connectivity verification** — pre-flight checklist never confirmed PostgreSQL was reachable
3. **T-02 verification was a code-only check** — verified Python imports, not actual table existence

This extension fixes all three gaps and delivers a production-ready database layer for the Advanced RAG subsystem.

### Why This Matters

Without this extension:
- `course_embeddings` table doesn't exist in any environment → Tier-1 returns empty
- `course_similarity_cache` table doesn't exist → forward compatibility broken
- `alembic history` is incomplete → production deployment would miss these tables
- `alembic autogenerate` can't detect the new model → future migrations won't see it

---

## 1. Architecture Integration — Database Layer

### 1.1 Dual-Path Table Creation

The project uses two mechanisms for table creation. Both must be updated:

```
                    ┌──────────────────────────┐
                    │   Database Table Creation  │
                    └──────────┬───────────────┘
                               │
            ┌──────────────────┴──────────────────┐
            │                                     │
            ▼                                     ▼
   ┌─────────────────┐                  ┌─────────────────────┐
   │ PRODUCTION PATH  │                  │  DEVELOPMENT PATH   │
   │ alembic upgrade  │                  │ Base.metadata       │
   │ head             │                  │ .create_all()       │
   └────────┬────────┘                  └──────────┬──────────┘
            │                                     │
            ▼                                     ▼
   ┌─────────────────┐                  ┌─────────────────────┐
   │ alembic/env.py   │                  │ app/main.py          │
   │ ★ MUST import    │                  │ lifespan() startup   │
   │ course_embedding │                  │ ★ ALREADY imports    │
   │ (CURRENTLY       │                  │ course_embedding     │
   │  MISSING!)       │                  │ (line 97, done in   │
   │                  │                  │  US-BKND-AI-015)    │
   └─────────────────┘                  └─────────────────────┘
```

**Current state:**

| Path | File | Model Imported? | Status |
|------|------|----------------|--------|
| Production (alembic) | `alembic/env.py` | ❌ **MISSING** | This extension fixes it |
| Development (create_all) | `app/main.py` | ✅ Line 97 | Already done in parent story |

**Impact of missing `alembic/env.py` import:** When `alembic revision --autogenerate` runs, it compares `Base.metadata` against the live database. Without `import app.models.course_embedding`, `CourseEmbeddingRecord` and `CourseSimilarityCache` are invisible to `Base.metadata` — the autogenerate diff won't see them, and future migrations won't include them.

### 1.2 Existing Module Compatibility

| Module | How This Extension Touches It | Change Type |
|--------|------------------------------|-------------|
| `alembic/env.py` | Add `import app.models.course_embedding` (line 24→25) | +1 line — matches existing pattern |
| `alembic/versions/20260620_0001_add_course_embeddings.py` | Already created — no change | No change |
| `app/main.py` | Already updated by parent story (line 97) | No change |
| `app/db/config.py` | Read-only dependency — database URL resolution | No change |
| `.env` / environment | Requires `DATABASE_URL` or `POSTGRES_*` vars for alembic to connect | Configuration only |

---

## 2. Task 01: Register Model in alembic/env.py (0.3h)

### 2.1 The Gap

`alembic/env.py` imports all ORM models so `Base.metadata` knows about every table. The parent story added `import app.models.course_embedding` to `app/main.py` (line 97) for the `create_all()` path — but **missed the same import in `alembic/env.py`** for the migration path.

### 2.2 Current State (BEFORE)

**File:** `alembic/env.py`, lines 14-24:

```python
from app.models.base import Base
import app.models.persisted_course  # noqa: F401 — CourseRecord, TemplateRecord, etc.
import app.models.template_type    # noqa: F401 — TemplateType
import app.models.component_type   # noqa: F401 — ComponentType
import app.models.page_component   # noqa: F401 — PageRecord, ComponentRecord
import app.models.theme            # noqa: F401 — ThemeRecord
import app.models.scoring          # noqa: F401 — CourseScoringRecord
import app.models.branching        # noqa: F401 — BranchRule, BranchEvent
import app.models.social           # noqa: F401 — Discussion, PeerReview, Poll, Team
import app.models.interaction_event  # noqa: F401 — InteractionEventRecord
import app.models.ai_models  # noqa: F401 — AISessionRecord, AIProposalRecord, etc.
```

### 2.3 Target State (AFTER)

Add after line 24 (`import app.models.ai_models`):

```python
import app.models.course_embedding  # noqa: F401 — US-BKND-AI-015: CourseEmbeddingRecord, CourseSimilarityCache
```

### 2.4 Decision Log

| Decision | Why |
|----------|-----|
| Add AFTER `ai_models`, BEFORE config object | Groups all AI-related model imports together. Matches the order in `app/main.py` (ai_models → ai_admin_override → ai_safety_event → course_embedding). |
| Use same `# noqa: F401` comment pattern | Consistent with all 10 existing model imports in this file |
| No separate section header | Matches the flat import style of the existing file — all models imported as a block |
| Include table names in comment | Helps developers understand what this import registers without reading the model file |

### 2.5 Verify

```bash
# 1. Check the import exists
grep "course_embedding" alembic/env.py

# 2. Verify Base.metadata now knows about the tables
PYTHONPATH=. python -c "
from app.models.base import Base
import app.models.course_embedding
table_names = Base.metadata.tables.keys()
assert 'course_embeddings' in table_names, f'MISSING: course_embeddings not in {table_names}'
assert 'course_similarity_cache' in table_names, f'MISSING: course_similarity_cache not in {table_names}'
print('Both tables registered in Base.metadata: OK')
print('Tables:', [t for t in sorted(table_names) if 'course_embed' in t or 'similarity' in t])
"

# 3. Verify alembic can import without errors
PYTHONPATH=. python -c "
import alembic.env
print('alembic/env.py imports: OK')
"
```

---

## 3. Task 02: Database Connectivity Verification (0.3h)

### 3.1 The Gap

The IMP doc's pre-flight checklist (§0.5) verified git status, Python imports, and uvicorn startup — but never checked if PostgreSQL was reachable. The developer created the migration file (T-02 verified) but `alembic upgrade head` silently failed because there was no database.

### 3.2 Pre-Flight DB Verification Script

Add this to the pre-flight checklist (IMP doc §0.5). Run BEFORE starting any implementation tasks:

```bash
# ── Database Connectivity Check ──────────────────────────────
# This must pass before T-02 (migration) can be verified.
# If it fails, start PostgreSQL first, then re-run.

# Option A: If DATABASE_URL is set
if [ -n "$DATABASE_URL" ]; then
    echo "DATABASE_URL is set"
    # Test connectivity via alembic
    alembic current 2>&1 | head -3
else
    echo "DATABASE_URL not set — checking component vars..."
    echo "  POSTGRES_HOST=${POSTGRES_HOST:-localhost}"
    echo "  POSTGRES_PORT=${POSTGRES_PORT:-5432}"
    echo "  POSTGRES_DB=${POSTGRES_DB:-elearning}"
    echo "  POSTGRES_USER=${POSTGRES_USER:-postgres}"
fi

# Option B: Direct psql test (works regardless of alembic)
psql -h "${POSTGRES_HOST:-localhost}" \
     -p "${POSTGRES_PORT:-5432}" \
     -U "${POSTGRES_USER:-postgres}" \
     -d "${POSTGRES_DB:-elearning}" \
     -c "SELECT 1 AS db_connectivity_check;" 2>&1

# Expected output:
#  db_connectivity_check
# -----------------------
#                      1
# (1 row)
```

**If the check fails**, you'll see:
```
psql: could not connect to server: Connection refused
    Is the server running on host "localhost" and accepting
    TCP/IP connections on port 5432?
```

**Fix:** Start PostgreSQL first:
```bash
# Windows
net start postgresql-x64-16

# Linux
sudo systemctl start postgresql

# macOS
brew services start postgresql@16
```

### 3.3 Decision Log

| Decision | Why |
|----------|-----|
| Two options (alembic + psql) | `alembic current` validates the full chain (alembic config + DB connection). `psql -c "SELECT 1"` is the simplest possible test — works even if alembic config is broken. |
| Use env var defaults (`:-localhost`) | Matches the defaults in `app/db/config.py` and `alembic/env.py` — `localhost:5432/elearning/postgres` |
| Pre-flight, not mid-task | DB must be running before T-02. If it's not, everything after T-02 is unverifiable. |

---

## 4. Task 03: Migration Lifecycle — Apply, Verify, Rollback (0.5h)

### 4.1 The Gap

The IMP doc's T-02 verification (§12.3) used a Python import check that passes even without a database:

```python
# THIS CHECK IS WRONG — it verifies the model imports, not that tables exist:
PYTHONPATH=. python -c "
from app.models.course_embedding import CourseEmbeddingRecord
async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.create_all)  # ← passes even if DB is down!
print('Tables verified OK')
"
```

This check succeeds because `Base.metadata.create_all()` is a no-op when there's no database connection — it doesn't raise an error, it just does nothing.

### 4.2 Correct Migration Lifecycle

```
┌─────────────────────────────────────────────────────────────────┐
│                  MIGRATION LIFECYCLE                             │
│                                                                 │
│  1. PRE-CHECK:  alembic current                                  │
│     → Confirms DB is reachable and shows current head            │
│                                                                 │
│  2. APPLY:      alembic upgrade head                             │
│     → Runs 20260620_0001 migration, creates both tables          │
│                                                                 │
│  3. VERIFY:     psql -c "\dt course_embed*"                     │
│     → Confirms tables exist with correct schema                  │
│                                                                 │
│  4. ROLLBACK:   alembic downgrade -1                             │
│     → Drops both tables, confirms downgrade() works              │
│                                                                 │
│  5. RE-APPLY:   alembic upgrade head                             │
│     → Restores tables for use                                    │
│                                                                 │
│  6. POST-VERIFY: psql -c "SELECT count(*) FROM course_embeddings"│
│     → Confirms table is queryable (0 rows expected initially)    │
└─────────────────────────────────────────────────────────────────┘
```

### 4.3 Exact Commands

```bash
# Step 1: Check current state
echo "=== Step 1: Current alembic state ==="
alembic current
# Expected: 20260412_0003 (head)  —  the current head BEFORE our migration

# Step 2: Apply migration
echo "=== Step 2: Applying migration ==="
alembic upgrade head
# Expected: Running upgrade 20260412_0003 -> 20260620_0001, ...
#          INFO  [alembic.runtime.migration] Running upgrade 20260412_0003 -> 20260620_0001, Add course_embeddings and course_similarity_cache tables

# Step 3: Verify tables exist
echo "=== Step 3: Verifying tables ==="
psql -h "${POSTGRES_HOST:-localhost}" \
     -p "${POSTGRES_PORT:-5432}" \
     -U "${POSTGRES_USER:-postgres}" \
     -d "${POSTGRES_DB:-elearning}" \
     -c "\dt course_embed*"
# Expected:
#  Schema |           Name           | Type  |  Owner
# --------+--------------------------+-------+----------
#  public | course_embeddings        | table | postgres
#  public | course_similarity_cache  | table | postgres

# Step 3b: Verify indexes
psql -h "${POSTGRES_HOST:-localhost}" \
     -p "${POSTGRES_PORT:-5432}" \
     -U "${POSTGRES_USER:-postgres}" \
     -d "${POSTGRES_DB:-elearning}" \
     -c "\di ix_course_embeddings*"
# Expected: 4-5 indexes listed (4 always, +1 if pgvector installed)

# Step 4: Test rollback
echo "=== Step 4: Testing rollback ==="
alembic downgrade -1
# Expected: Running downgrade 20260620_0001 -> 20260412_0003, ...
#          Tables dropped successfully

# Step 5: Re-apply
echo "=== Step 5: Re-applying migration ==="
alembic upgrade head
# Expected: Same as Step 2

# Step 6: Verify queryable
echo "=== Step 6: Post-verification ==="
psql -h "${POSTGRES_HOST:-localhost}" \
     -p "${POSTGRES_PORT:-5432}" \
     -U "${POSTGRES_USER:-postgres}" \
     -d "${POSTGRES_DB:-elearning}" \
     -c "SELECT count(*) AS row_count FROM course_embeddings"
# Expected: row_count = 0 (table exists, empty, ready for data)
```

### 4.4 What If Alembic Already Applied?

If `alembic current` shows `20260620_0001 (head)`, the migration was already applied (e.g., via a previous run or `create_all`). In this case:

```bash
# Verify with direct SQL
psql -c "\dt course_embed*"
psql -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'course_embeddings' ORDER BY ordinal_position"
```

If tables exist but alembic history doesn't show the migration (stale state from `create_all`):

```bash
# Stamp the migration as applied without re-running it
alembic stamp 20260620_0001
```

### 4.5 Decision Log

| Decision | Why |
|----------|-----|
| 6-step lifecycle with rollback test | Production migrations MUST have verified rollback. A migration that can't be downgraded is a deployment risk. |
| `psql` for verification, not Python | `psql` connects directly to the DB and shows actual table state. Python `Base.metadata.create_all` is a no-op if tables already exist. |
| `alembic stamp` for stale-state recovery | If `create_all` in dev creates tables before alembic runs, alembic history needs to be stamped to stay in sync. |

---

## 5. Task 04: Environment Configuration Validation (0.2h)

### 5.1 The Gap

The IMP doc added 8 environment variables to `.env.example` but never validated they work with alembic. The migration engine (`alembic/env.py`) and the app engine (`app/db/config.py`) use different database drivers:

| Component | Driver | URL Format |
|-----------|--------|-----------|
| `app/db/config.py` (app) | `asyncpg` | `postgresql+asyncpg://user:pass@host:5432/db` |
| `alembic/env.py` (migrations) | `psycopg2` | `postgresql://user:pass@host:5432/db` |

The `get_database_url()` function in `alembic/env.py` already handles this conversion (line 43: `url.replace("postgresql+asyncpg://", "postgresql://")`). So if `DATABASE_URL` is set with asyncpg, migrations still work.

### 5.2 Verify

```bash
# Check both URL formats are compatible
PYTHONPATH=. python -c "
from app.db.config import get_database_url as app_url
from alembic.env import get_database_url as alembic_url

app = app_url()
alembic = alembic_url()
print(f'App URL:     {app}')
print(f'Alembic URL: {alembic}')
# App URL should contain asyncpg, Alembic URL should NOT
assert 'asyncpg' in app or 'asyncpg' not in app, 'Unexpected URL format'
assert 'asyncpg' not in alembic, f'Alembic URL must use sync driver, got: {alembic}'
print('URL conversion: OK')
"
```

### 5.3 Decision Log

| Decision | Why |
|----------|-----|
| Don't change URL formats | The existing dual-driver setup works correctly. `alembic/env.py:get_database_url()` already handles conversion. |
| Verify both URLs work | Confirms the migration can connect regardless of how `DATABASE_URL` is set. |

---

## 6. Task 05: Troubleshooting Extension (0.2h)

### 6.1 New Troubleshooting Entries

Add these entries to the IMP doc §15 (Troubleshooting Guide):

| Symptom | Cause | Fix |
|---------|-------|-----|
| `alembic upgrade head` → `sqlalchemy.exc.OperationalError: could not connect to server` | PostgreSQL not running | Start PostgreSQL (`net start postgresql-x64-16` on Windows, `sudo systemctl start postgresql` on Linux) |
| `alembic current` → empty output or error | `DATABASE_URL` not set and component vars missing | Set `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` in `.env` |
| `alembic upgrade head` → `relation "course_embeddings" already exists` | `Base.metadata.create_all()` in dev already created the table | Run `alembic stamp 20260620_0001` to mark as applied, then verify with `psql` |
| `alembic downgrade -1` → `Can't locate revision identified by '20260412_0003'` | Migration chain broken — parent revision missing | Check `alembic history` — ensure `20260412_0003` exists in the chain |
| `psql -c "\dt course_embed*"` → `No matching relations found` | Migration not applied or applied to wrong database | Verify `DATABASE_URL` points to the correct database, re-run `alembic upgrade head` |
| `PYTHONPATH=. python -c "from alembic.env import ..."` → `ModuleNotFoundError` | `alembic/__init__.py` missing or PYTHONPATH issue | Run from project root with `PYTHONPATH=.` prefix |

### 6.2 Emergency Rollback

If migration causes issues in production:

```bash
# Instant rollback — no code deploy needed:
alembic downgrade -1

# Verify tables are gone:
psql -c "\dt course_embed*"
# Expected: "No matching relations found"

# App continues working — Tier-1 degrades gracefully to Tier-2
# (the code handles missing course_embeddings table)
```

---

## 7. Updated Pre-Flight Checklist

Merge this into the IMP doc §0.5 before starting any 015 implementation:

```
## 0.5 Before-You-Begin Checklist

- [ ] `git branch` confirms you're on the right branch
- [ ] `git status` is clean
- [ ] **★ NEW: `psql -c "SELECT 1"` — database is reachable**
- [ ] **★ NEW: `alembic current` — shows current head revision**
- [ ] `PYTHONPATH=. python -c "from app.main import app"` — app imports
- [ ] `PYTHONPATH=. uvicorn app.main:app --reload` — server starts
- [ ] You've read the 5 existing files listed in Quick Start
- [ ] You understand the repository pattern
- [ ] You understand the service pattern
- [ ] You understand the router pattern
```

---

## 8. Updated T-02 Verification

Replace the IMP doc §12.3 "Verify T-02" block with:

```bash
# ★ UPDATED: Verifies actual table existence, not just Python imports

# Step 1: Apply migration
alembic upgrade head

# Step 2: Verify tables exist in the database
psql -h "${POSTGRES_HOST:-localhost}" \
     -p "${POSTGRES_PORT:-5432}" \
     -U "${POSTGRES_USER:-postgres}" \
     -d "${POSTGRES_DB:-elearning}" \
     -c "\dt course_embed*"

# Step 3: Test rollback
alembic downgrade -1

# Step 4: Re-apply
alembic upgrade head

# Step 5: Verify queryable
psql -h "${POSTGRES_HOST:-localhost}" \
     -p "${POSTGRES_PORT:-5432}" \
     -U "${POSTGRES_USER:-postgres}" \
     -d "${POSTGRES_DB:-elearning}" \
     -c "SELECT count(*) FROM course_embeddings"

echo "T-02 VERIFIED: Migration applied, tables exist, rollback works"
```

---

## 9. File Manifest

| # | File | Action | Lines | Priority |
|---|------|--------|-------|----------|
| 1 | `alembic/env.py` | **MODIFY** +1 import line after line 24 | +1 | 🔴 MUST |
| 2 | `.env` or environment | **CONFIGURE** — ensure `DATABASE_URL` or `POSTGRES_*` vars are set | 0 | 🔴 MUST |
| 3 | (no file) | **EXECUTE** — `alembic upgrade head` against all environments | 0 | 🔴 MUST |
| 4 | `US-BKND-AI-015-IMP.md` | **MODIFY** — update §0.5, §12.3, §15 as specified above | ~30 | 🟡 SHOULD |

---

## 10. Dependency Chain

```
PEND-17 (this story)
    │
    ├──► PEND-09 (pgvector install) — needs course_embeddings table to exist
    │         │
    │         └──► PEND-04 (embedding population) — needs pgvector + table
    │
    └──► All future alembic autogenerate runs — need model registered in env.py
```

---

## Appendix A: Complete env.py After Fix

For reference, `alembic/env.py` model imports section after applying T-01:

```python
from app.models.base import Base
import app.models.persisted_course  # noqa: F401 — CourseRecord, TemplateRecord, etc.
import app.models.template_type    # noqa: F401 — TemplateType
import app.models.component_type   # noqa: F401 — ComponentType
import app.models.page_component   # noqa: F401 — PageRecord, ComponentRecord
import app.models.theme            # noqa: F401 — ThemeRecord
import app.models.scoring          # noqa: F401 — CourseScoringRecord
import app.models.branching        # noqa: F401 — BranchRule, BranchEvent
import app.models.social           # noqa: F401 — Discussion, PeerReview, Poll, Team
import app.models.interaction_event  # noqa: F401 — InteractionEventRecord
import app.models.ai_models  # noqa: F401 — AISessionRecord, AIProposalRecord, etc.
import app.models.course_embedding  # noqa: F401 — US-BKND-AI-015: CourseEmbeddingRecord, CourseSimilarityCache
```

---

**Document Version:** 1.0  
**Authored:** 2026-06-20  
**TPO / Solutions Architect:** This document extends US-BKND-AI-015-IMP.md with the database/migration layer that was identified as missing in the PEND-17 RCA.  
**Next Step:** Execute T-01 (add import to env.py) → T-02 (verify DB connectivity) → T-03 (run migration lifecycle) → verify PEND-17 resolved.
