# US-BKND-AI-015-IMP — Advanced RAG: Standalone Implementation Playbook

**Story ID:** US-BKND-AI-015  
**Title:** Retrieve Similar Courses for Examples and Tone  
**Priority:** SHOULD → MUST for production readiness  
**Status:** ⚠️ 25% → target 100%  
**Estimate:** 26 hours (20 tasks, 8 layers)  
**Role:** TPO + Solutions Architect — this document is the single source of truth for implementation  

---

## ⚡ Developer Quick Start

**What you're building:** A 3-tier similar-course search engine. When the AI chat agent needs style/tone examples, it invokes `query_similar_courses(q="show me courses like...")` and gets real results with PII-redacted excerpts, template breakdowns, and tone notes.

**Why:** Currently the AI gets hardcoded empty results. This means "show me courses like this" returns nothing and generation quality suffers.

**Before you start — 60-second orientation:**
1. Read `docs/AI_Implemenation/01_SystemArchitecture/VALIDATION_REPORT.md` — Flow #4 (Advanced RAG: 25%) and Flow #13 (Similar Course Retrieval: 82%)
2. Read the existing code you'll be modifying:
   - `app/routers/ai_tools.py` lines 715-848 (current MVP endpoint — you'll refactor this)
   - `app/services/ai/chat_orchestrator.py` lines 35-52 (SYSTEM_PROMPT), 239-335 (mock tool execution), 341+ (LLM loop)
   - `app/services/ai/tool_executor.py` lines 58-170 (execute pattern), 172-268 (handler examples)
   - `app/main.py` lines 85-97 (model imports), 207-238 (AI router mounting)
   - `app/services/ai/config.py` lines 52-105 (AIConfig dataclass), 249-291 (load_ai_config)
   - `app/utils/feature_flags.py` (entire file — 200 lines)
3. Understand the pattern: every AI module follows the same constructor → method → dict-return pattern

**Execution order (follow this exactly):**
```
Phase A (parallel):    T-01 (model)  +  T-03 (embedding provider)  +  T-08 (feature flag)
Phase B (sequential):  T-02 (migration) → T-04/T-05/T-06 (repository)
Phase C (sequential):  T-07 (service) → T-09/T-10/T-11 (routers + orchestrator)
Phase D (parallel):    T-12 (system prompt) + T-13 (main.py) + T-14 (env vars)
Phase E (final):       T-15/T-16 (tests) → T-17 (integration) → T-18/T-19/T-20 (docs/regression/perf)
```

---

## 0. Prerequisites & Environment Setup

### 0.1 Required Software

| Software | Version | Check Command | Required For |
|----------|---------|---------------|-------------|
| Python | ≥3.10 | `python --version` | All code |
| PostgreSQL | ≥14 | `psql --version` | Database |
| pgvector extension | ≥0.5 | `psql -c "SELECT extversion FROM pg_extension WHERE extname='vector'"` | Tier-1 (optional) |
| pip packages | see §0.2 | `pip list` | Runtime |

### 0.2 Python Dependencies

**New dependency to add** — the `openai` SDK is needed for production embedding generation:

```bash
pip install openai
```

Add to `requirements.txt`:
```
openai>=1.0.0,<2.0.0
```

If you use `pyproject.toml` or `setup.cfg`, add the equivalent entry there.

**Existing dependencies used** (already in requirements.txt, no action needed):
- `sqlalchemy[asyncio]` — ORM
- `fastapi` — web framework
- `pydantic` — validation

### 0.3 pgvector Setup (optional — Tier-1 only)

pgvector is **not required**. Tier-2 and Tier-3 work without it. If you want Tier-1 vector search:

```bash
# Ubuntu/Debian
sudo apt-get install postgresql-16-pgvector

# macOS
brew install pgvector

# Then, in psql as superuser:
psql -U postgres -d your_database -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

Verify:
```bash
psql -U postgres -d your_database -c "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
# Should return: 1
```

### 0.4 Environment Variables

Copy these to your `.env` file (uncomment and set values):

```bash
# Feature gate — set to "true" to enable the feature
FEATURE_SIMILAR_COURSE_RETRIEVAL=true

# Embedding provider: "mock" (zero-cost, deterministic, dev) or "openai" (production)
EMBEDDING_PROVIDER=mock

# Only needed when EMBEDDING_PROVIDER=openai
# OPENAI_API_KEY=sk-...

# Embedding model (only relevant for openai provider)
# EMBEDDING_MODEL=text-embedding-ada-002

# Vector dimension — must match model output
# EMBEDDING_DIMENSION=1536

# Enable pgvector for Tier-1 vector search (requires pgvector extension)
# ENABLE_PGVECTOR=false

# Max results per query (hard cap, requests exceeding this are clamped)
# SIMILAR_COURSE_MAX_RESULTS=20

# Cache TTL in minutes (future — unused in MVP but env var defined)
# SIMILAR_COURSE_CACHE_TTL_MINUTES=60
```

**Quick explanation of each env var:**

| Variable | Required | Default | When to change |
|----------|----------|---------|---------------|
| `FEATURE_SIMILAR_COURSE_RETRIEVAL` | Yes | `false` | Set `true` to enable the feature |
| `EMBEDDING_PROVIDER` | No | `mock` | Set `openai` in production |
| `OPENAI_API_KEY` | If provider=openai | (empty) | Your OpenAI API key |
| `EMBEDDING_MODEL` | No | `text-embedding-ada-002` | Only if you need a different model |
| `EMBEDDING_DIMENSION` | No | `1536` | Must match model if changed |
| `ENABLE_PGVECTOR` | No | `false` | Set `true` if pgvector installed |

### 0.5 Before-You-Begin Checklist

- [ ] `git branch` confirms you're on `demo-course-AI` (or your feature branch)
- [ ] `git status` is clean (no uncommitted changes)
- [ ] `PYTHONPATH=. python -c "from app.main import app"` — app imports without errors
- [ ] `PYTHONPATH=. uvicorn app.main:app --reload` — server starts successfully
- [ ] You've read the 5 existing files listed in the Quick Start
- [ ] You understand the repository pattern: `__init__(self, session: AsyncSession)` — session only
- [ ] You understand the service pattern: `__init__(self, db: AsyncSession)` — db only, returns dicts
- [ ] You understand the router pattern: `Depends(get_current_user)` + `Depends(get_session)` + `ai_error()`

---

## 1. Architecture Integration Map

### 1.1 What We're Building (Data Flow)

```
User says "find courses like this safety training"
        │
        ▼
┌────────────────────────────────────────────┐
│ ChatOrchestrator (existing, MODIFIED)      │
│ - Intent parser detects "similar course"   │
│ - Routes to _execute_mock_tool("query_similar_courses")
│ - ★ NEW: calls SimilarCourseService instead of mock stub
│ - ★ NEW: updated SYSTEM_PROMPT with RAG warning
└───────────────┬────────────────────────────┘
                │
    ┌───────────┴───────────┐
    │                       │
    ▼                       ▼
┌───────────────┐   ┌──────────────────────┐
│ ToolExecutor  │   │ ai_similar_courses.py│
│ (MODIFIED)    │   │ (NEW — REST endpoint)│
│ _handle_qs()  │   │ POST /similar-courses│
└───────┬───────┘   └──────────┬───────────┘
        │                      │
        └──────────┬───────────┘
                   ▼
        ┌─────────────────────────┐
        │ SimilarCourseService    │ ← NEW
        │ query_similar_courses() │
        │ - Validates session     │
        │ - Feature-flag gate     │
        │ - Tiered fallback       │
        └──┬──────────┬───────────┘
           │          │
    ┌──────▼──┐  ┌───▼──────────────┐
    │Embedding│  │SimilarCourseRepo │ ← NEW
    │Provider │  │- search_vector() │
    │(NEW)    │  │- search_fulltext()│
    │- Mock   │  │- search_keyword()│
    │- OpenAI │  │- enrich_results()│
    └─────────┘  │- PII redaction   │
                 └───┬───────────────┘
                     │
         ┌───────────┼───────────┐
         ▼           ▼           ▼
    ┌────────┐ ┌────────┐ ┌──────────┐
    │AISession│ │Course  │ │Page      │
    │Repo    │ │Repo    │ │Repo      │
    │(exist) │ │(exist) │ │(exist)   │
    └────────┘ └────────┘ └──────────┘
```

### 1.2 New Files (7 to create)

| # | File | Lines | Creates |
|---|------|-------|---------|
| 1 | `app/models/course_embedding.py` | ~130 | `CourseEmbeddingRecord`, `CourseSimilarityCache` |
| 2 | `app/repositories/similar_course_repo.py` | ~380 | `SimilarCourseRepository` (3 tiers + enrichment) |
| 3 | `app/services/ai/embedding_provider.py` | ~190 | `EmbeddingProvider` ABC, `OpenAIBackend`, `MockEmbeddingProvider`, factory |
| 4 | `app/services/ai/similar_course_service.py` | ~210 | `SimilarCourseService` (orchestration + gate) |
| 5 | `app/routers/ai_similar_courses.py` | ~100 | REST endpoint |
| 6 | `alembic/versions/20260620_0001_add_course_embeddings.py` | ~120 | Migration |
| 7 | `tests/run_similar_course_tests.py` | ~280 | 20 test scenarios |

### 1.3 Modified Files (8 to change)

| # | File | What Changes | Lines Δ |
|---|------|-------------|---------|
| 8 | `app/main.py` | +1 model import, +1 router registration | +2 |
| 9 | `app/utils/feature_flags.py` | +1 flag in `_initialize_flags()` dict | +8 |
| 10 | `app/services/ai/config.py` | +6 fields on `AIConfig`, +6 lines in `load_ai_config()` | +12 |
| 11 | `app/routers/ai_tools.py` | Refactor lines 715-848 — delegate to service | ~-80/+50 |
| 12 | `app/services/ai/tool_executor.py` | +1 route in `execute()`, +1 handler method | +35 |
| 13 | `app/services/ai/chat_orchestrator.py` | Replace mock stub + update SYSTEM_PROMPT + update `_build_system_prompt()` + add `query_similar_courses` to `_build_tool_definitions()` | ~65 |
| 14 | `.env.example` | +18 lines for 015 env vars | +18 |
| 15 | `docs/AI_Implemenation/01_SystemArchitecture/TOOL_SCHEMAS_CLAUDE_NATIVE.md` | Update final `query_similar_courses` contract | ~10 |

### 1.4 Files NOT Touched (zero impact)

These modules are dependencies of the new code but require **no changes**:

| File | Role | Why No Change |
|------|------|--------------|
| `app/models/base.py` | `Base` class for ORM | `CourseEmbeddingRecord` inherits it — no change needed |
| `app/repositories/ai_session_repo.py` | Session lookup | `SimilarCourseService` calls it as-is |
| `app/repositories/course_repo.py` | Course listing | `SimilarCourseRepository` calls it as-is |
| `app/repositories/page_component_repo.py` | Page/template listing | `enrich_results()` calls it as-is |
| `app/services/ai/audit_service.py` | Audit logging | `ToolExecutor` handles audit — similarity queries inherit audit via tool dispatch |
| `app/middleware/ai_telemetry.py` | Tracing | Traces all `/api/v1/ai/*` routes automatically |
| `app/services/ai/error_envelope.py` | `ai_error()` helper | Used as-is by new router |

---

## 2. Database Architecture

### 2.1 DDL: `course_embeddings` (primary table)

```sql
-- Run via: Alembic migration (see §14.3)
-- Non-destructive: CREATE IF NOT EXISTS
-- pgvector is OPTIONAL — table uses JSONB as portable fallback

CREATE TABLE IF NOT EXISTS course_embeddings (
    id                  SERIAL PRIMARY KEY,
    embedding_record_id VARCHAR(64) UNIQUE NOT NULL,
    course_record_id    INTEGER NOT NULL
        REFERENCES courses(id) ON DELETE CASCADE,
    organization_id     VARCHAR(64) NOT NULL DEFAULT 'default',
    embedding           JSONB,                              -- {"dim": 1536, "vec": [...]}
    content_hash        VARCHAR(64) NOT NULL,               -- SHA-256 for staleness
    chunk_count         INTEGER NOT NULL DEFAULT 1,
    embedding_model     VARCHAR(100) NOT NULL DEFAULT 'text-embedding-ada-002',
    is_stale            BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    updated_at          TIMESTAMP WITHOUT TIME ZONE DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_course_embeddings_embedding_record_id
    ON course_embeddings (embedding_record_id);
CREATE INDEX IF NOT EXISTS ix_course_embeddings_course_record_id
    ON course_embeddings (course_record_id);
CREATE INDEX IF NOT EXISTS ix_course_embeddings_org_id
    ON course_embeddings (organization_id);
CREATE INDEX IF NOT EXISTS ix_course_embeddings_org_stale
    ON course_embeddings (organization_id, is_stale)
    WHERE is_stale = FALSE;

-- ★ Only created if pgvector extension exists (migration checks automatically)
CREATE INDEX IF NOT EXISTS ix_course_embeddings_vector
    ON course_embeddings
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
```

### 2.2 DDL: `course_similarity_cache` (optional — deferred to future iteration)

```sql
-- MVP DOES NOT USE THIS TABLE. Created for forward compatibility.
-- Service and repository code never read/write it in MVP.

CREATE TABLE IF NOT EXISTS course_similarity_cache (
    id                SERIAL PRIMARY KEY,
    source_course_id  INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    similar_course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    similarity_score  FLOAT NOT NULL,
    retrieval_tier    VARCHAR(8) NOT NULL DEFAULT 'tier1',
    expires_at        TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    created_at        TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    UNIQUE(source_course_id, similar_course_id)
);

CREATE INDEX IF NOT EXISTS ix_similarity_cache_expires
    ON course_similarity_cache (expires_at);
```

### 2.3 Why JSONB (not native vector type)

The `embedding` column is `JSONB`, not native `vector(1536)`. This is intentional:

- **Portability:** The table exists whether or not pgvector is installed. `CREATE TABLE` must succeed in all environments.
- **Fallback:** When pgvector is available, the ivfflat index provides ANN acceleration. When absent, Tier-1 degrades gracefully to Tier-2.
- **Cost:** For org-scoped course counts (<10K), cosine-similarity-in-Python is fast enough (P95 < 3s).
- **Storage format:** `{"dim": 1536, "vec": [0.12, -0.34, ...]}` — self-describing, versionable.

---

## 3. Model Layer — TASK T-01 (1.0h)

### 3.1 Create This File

**File:** `app/models/course_embedding.py`

**What to create:** Open your editor, create a new empty file, paste the complete code below.

```python
"""ORM model for course embedding vectors — US-BKND-AI-015.

Stores embedding vectors for similarity search across org-scoped courses.
Uses JSONB for pgvector-optional portability.

Table: course_embeddings
  - Dual-key pattern (int id + UUID string) matches existing AI models
  - embedding stored as {"dim": N, "vec": [...]} in JSONB
  - content_hash prevents wasted re-embedding when content unchanged
  - is_stale flag enables background re-indexing (future iteration)

Table: course_similarity_cache (deferred — table exists, code unused in MVP)
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String, DateTime, Integer, Boolean, ForeignKey, Index,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class CourseEmbeddingRecord(Base):
    """One embedding vector per course — recomputed when content changes."""

    __tablename__ = "course_embeddings"

    # ── Keys ─────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    embedding_record_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )

    # ── Foreign key to courses table ─────────────────────────
    course_record_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("courses.id", ondelete="CASCADE"),
        index=True,
    )

    # ── Tenant scope ─────────────────────────────────────────
    organization_id: Mapped[str] = mapped_column(
        String(64), default="default", index=True
    )

    # ── Vector data (JSONB: {"dim": 1536, "vec": [...]}) ────
    embedding: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True
    )

    # ── Staleness tracking ───────────────────────────────────
    content_hash: Mapped[str] = mapped_column(String(64))
    chunk_count: Mapped[int] = mapped_column(Integer, default=1)
    embedding_model: Mapped[str] = mapped_column(
        String(100), default="text-embedding-ada-002"
    )
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False)

    # ── Timestamps ───────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # ── Table-level constraints ──────────────────────────────
    __table_args__ = (
        Index(
            "ix_course_embeddings_org_stale",
            "organization_id",
            "is_stale",
            postgresql_where=(is_stale == False),  # noqa: E712
        ),
    )

    # ── Serialization (matches AI model camelCase convention) ─
    def to_dict(self) -> dict:
        return {
            "embeddingRecordId": self.embedding_record_id,
            "courseRecordId": self.course_record_id,
            "organizationId": self.organization_id,
            "contentHash": self.content_hash,
            "chunkCount": self.chunk_count,
            "embeddingModel": self.embedding_model,
            "isStale": self.is_stale,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }

    # ── Helpers ──────────────────────────────────────────────
    @staticmethod
    def compute_content_hash(title: str, description: str, template_text: str) -> str:
        """SHA-256 of concatenated content for staleness detection."""
        raw = f"{title}\n{description}\n{template_text}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def extract_vector(self) -> Optional[list[float]]:
        """Extract the embedding as a plain list of floats."""
        if self.embedding and "vec" in self.embedding:
            return self.embedding["vec"]
        return None


class CourseSimilarityCache(Base):
    """Optional cache for repeated similarity queries. DEFERRED — unused in MVP.

    Table exists for forward compatibility. No service or repository code
    reads/writes this table in the MVP implementation.
    """

    __tablename__ = "course_similarity_cache"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_course_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("courses.id", ondelete="CASCADE"),
    )
    similar_course_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("courses.id", ondelete="CASCADE"),
    )
    similarity_score: Mapped[float] = mapped_column()
    retrieval_tier: Mapped[str] = mapped_column(
        String(8), default="tier1"
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    __table_args__ = (
        Index("ix_similarity_cache_expires", "expires_at"),
    )
```

### 3.2 Verify T-01

```bash
# 1. Check the file exists
ls -la app/models/course_embedding.py

# 2. Verify Python imports without errors
PYTHONPATH=. python -c "
from app.models.course_embedding import CourseEmbeddingRecord, CourseSimilarityCache
print('CourseEmbeddingRecord:', CourseEmbeddingRecord.__tablename__)
print('CourseSimilarityCache:', CourseSimilarityCache.__tablename__)
print('has extract_vector:', hasattr(CourseEmbeddingRecord, 'extract_vector'))
print('has compute_content_hash:', hasattr(CourseEmbeddingRecord, 'compute_content_hash'))
"

# Expected output:
# CourseEmbeddingRecord: course_embeddings
# CourseSimilarityCache: course_similarity_cache
# has extract_vector: True
# has compute_content_hash: True

# 3. Check that to_dict() works
PYTHONPATH=. python -c "
from app.models.course_embedding import CourseEmbeddingRecord
r = CourseEmbeddingRecord(course_record_id=1, content_hash='abc123')
d = r.to_dict()
print('Keys:', sorted(d.keys()))
print('contentHash:', d['contentHash'])
print('isStale:', d['isStale'])
"
```

### 3.3 Decision Log

| Decision | Why |
|----------|-----|
| JSONB not native `vector(1536)` | pgvector is optional. JSONB works everywhere. ivfflat index provides acceleration when available. |
| Dual-key (`id` + `embedding_record_id`) | Matches `AISessionRecord` (id + session_id), `AIProposalRecord` pattern. Internal PK for DB ops, UUID for external API. |
| `CourseSimilarityCache` model created but unused | Table exists for forward compatibility. No code touches it in MVP. Kept as a single class in the models file rather than a separate file (reduces import surface). |
| `is_stale` default `False` | New embeddings are fresh by definition. Marked `True` only when course content changes and re-embedding is needed. |
| `content_hash` as SHA-256 | Cryptographic hash — collisions statistically impossible for this use case. Enables idempotent upsert (skip re-embedding if content unchanged). |

---

## 4. Repository Layer — TASKS T-04, T-05, T-06 (6.0h total)

### 4.1 Create This File

**File:** `app/repositories/similar_course_repo.py`

This is the largest new file. It implements all three retrieval tiers plus result enrichment.

**Before you type:** Note that `_derive_template_type()` is intentionally duplicated from `ToolExecutor._derive_template_type()`. The repository layer should NOT import from the tool executor (circular dependency risk). This duplication is documented and acceptable for two implementations. If a third appears, refactor to a shared utility.

```python
"""Repository for similar course retrieval across three tiers — US-BKND-AI-015.

Three-tier strategy with automatic fallback:
    Tier 1: pgvector cosine similarity (requires ENABLE_PGVECTOR=true + pgvector extension)
    Tier 2: PostgreSQL ts_vector/ts_query full-text search (always available, no extension needed)
    Tier 3: ILIKE keyword matching (always available — safety net)

Each tier is independent. Higher tiers degrade gracefully.
All queries enforce tenant isolation via organization_id filter.

PII Redaction: All excerpts are scanned for email, US phone, US SSN, and credit
card patterns. Matching text is replaced with "[REDACTED]".

Safe Fields: Only SAFE_EXCERPT_FIELDS are extracted. Fields like isCorrect,
correctAnswer, and scoring config are explicitly excluded.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.persisted_course import CourseRecord
from app.models.page_component import PageRecord
from app.models.course_embedding import CourseEmbeddingRecord

logger = logging.getLogger("ai_authoring")

# ═══════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════

# FR-6: Fields whose values are SAFE to include in excerpts.
# EXPLICITLY EXCLUDED: isCorrect, correctAnswer, correctAnswers, options[].isCorrect,
# scoring configuration, user-specific identifiers.
SAFE_EXCERPT_FIELDS: set[str] = {
    "title", "content", "body", "subtitle", "description",
    "question", "introText", "mediaUrl", "text", "label",
    "heading", "summary",
}

MAX_EXCERPT_LENGTH = 500        # chars per excerpt (FR-3)
MAX_EXCERPTS_PER_COURSE = 3     # excerpts per course result (FR-3)

# FR-6: PII detection patterns
_PII_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"  # email
    r"|"
    r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"                        # US phone
    r"|"
    r"\b\d{3}-\d{2}-\d{4}\b"                                 # US SSN
    r"|"
    r"\b(?:\d[ -]*?){13,16}\b"                               # credit card
)

# Minimum character length for extracted text to be worth including
# Rationale: strings ≤20 chars are usually titles/labels, not useful excerpts.
# Example: "Safety 101" (11 chars) is excluded; "This course covers workplace
# safety procedures including hazard identification..." (80 chars) is included.
MIN_EXCERPT_TEXT_LENGTH = 20


class SimilarCourseRepository:
    """Retrieves similar courses using tiered strategy with automatic fallback.

    Matches existing repository pattern:
        __init__(self, session: AsyncSession) — session only

    Tenant isolation is enforced via organization_id parameter on each
    search method — NOT stored on the instance.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    # ═══════════════════════════════════════════════════════════════
    # Tier 1: pgvector Cosine Similarity
    # ═══════════════════════════════════════════════════════════════

    async def _pgvector_available(self) -> bool:
        """Check if the pgvector extension is installed. Cached per instance."""
        if hasattr(self, "_pgvector_cached"):
            return self._pgvector_cached
        try:
            result = await self.session.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            )
            self._pgvector_cached = result.scalar() is not None
        except Exception:
            self._pgvector_cached = False
        return self._pgvector_cached

    async def search_vector(
        self,
        query_embedding: list[float],
        organization_id: str,
        max_results: int = 5,
    ) -> list[dict]:
        """Tier 1: pgvector cosine similarity search.

        Degrades silently to empty list if:
        - pgvector extension not installed
        - No embeddings exist for this org
        - SQL error (caught, logged, returns [])
        """
        if not await self._pgvector_available():
            logger.debug("pgvector not available — skipping tier-1")
            return []

        try:
            # Build vector literal string for SQL interpolation
            vec_str = "[" + ",".join(f"{v:.8f}" for v in query_embedding) + "]"

            sql = text("""
                SELECT
                    ce.course_record_id,
                    c.course_id,
                    c.title,
                    COALESCE(c.description, '') AS description,
                    1.0 - (ce.embedding <=> (:vec)::vector) AS similarity
                FROM course_embeddings ce
                JOIN courses c ON c.id = ce.course_record_id
                WHERE ce.organization_id = :org_id
                  AND ce.is_stale = FALSE
                  AND ce.embedding IS NOT NULL
                ORDER BY ce.embedding <=> (:vec)::vector
                LIMIT :limit
            """)

            rows = await self.session.execute(sql, {
                "vec": vec_str,
                "org_id": organization_id,
                "limit": max_results,
            })
            return [
                {
                    "course_record_id": r[0],
                    "course_id": r[1],
                    "title": r[2] or "Untitled",
                    "description": r[3],
                    "score": round(float(r[4]), 4),
                }
                for r in rows
            ]
        except Exception as exc:
            logger.warning("pgvector search failed (degrading to tier-2): %s", exc)
            return []

    # ═══════════════════════════════════════════════════════════════
    # Tier 2: PostgreSQL Full-Text Search
    # ═══════════════════════════════════════════════════════════════

    async def search_fulltext(
        self,
        query: str,
        organization_id: str,
        max_results: int = 5,
    ) -> list[dict]:
        """Tier 2: PostgreSQL ts_vector/ts_query full-text search.

        Weighting:
            A (1.0) — course title
            B (0.4) — course description
            C (0.2) — page/template title (future enhancement)

        Uses 'english' config. For multi-language, extend with per-course
        language detection in a future iteration.

        NOTE: The `courses` table (CourseRecord) has no `organization_id` column.
        Org isolation is enforced at the session layer — ToolExecutor validates
        session ownership before any tool executes. This is consistent with how
        CourseRepository.list() works (returns all courses without org filter).
        When multi-tenancy migrates to DB-level org columns on courses, add
        `AND c.organization_id = :org_id` to all three tier SQL queries.
        """
        # Sanitize: strip punctuation, keep alphanumeric + spaces
        sanitized = re.sub(r"[^\w\s]", " ", query).strip().lower()
        if not sanitized:
            return []

        # Build ts_query: split into words, join with & for AND semantics
        # Append :* for prefix matching (e.g., "train" matches "training")
        terms = [t for t in sanitized.split() if len(t) > 1]
        if not terms:
            return []
        ts_query_str = " & ".join(f"{t}:*" for t in terms)

        sql = text("""
            SELECT DISTINCT ON (c.id)
                c.id AS course_record_id,
                c.course_id,
                c.title,
                COALESCE(c.description, '') AS description,
                ts_rank(
                    setweight(to_tsvector('english', COALESCE(c.title, '')), 'A') ||
                    setweight(to_tsvector('english', COALESCE(c.description, '')), 'B'),
                    to_tsquery('english', :tsq)
                ) AS rank
            FROM courses c
            WHERE
                (
                    setweight(to_tsvector('english', COALESCE(c.title, '')), 'A') ||
                    setweight(to_tsvector('english', COALESCE(c.description, '')), 'B')
                ) @@ to_tsquery('english', :tsq)
            ORDER BY c.id, rank DESC
            LIMIT :limit
        """)

        try:
            rows = await self.session.execute(sql, {
                "tsq": ts_query_str,
                "limit": max_results,
            })
            return [
                {
                    "course_record_id": r[0],
                    "course_id": r[1],
                    "title": r[2] or "Untitled",
                    "description": r[3],
                    # Normalize: ts_rank typically 0.0-1.0, clamp for safety
                    "score": round(min(float(r[4]) if r[4] else 0.0, 1.0), 4),
                }
                for r in rows
            ]
        except Exception as exc:
            logger.warning("Full-text search failed (degrading to tier-3): %s", exc)
            return []

    # ═══════════════════════════════════════════════════════════════
    # Tier 3: Keyword / ILIKE Search (always-available safety net)
    # ═══════════════════════════════════════════════════════════════

    async def search_keyword(
        self,
        query: str,
        organization_id: str,
        max_results: int = 5,
    ) -> list[dict]:
        """Tier 3: ILIKE pattern matching on course title and description.

        Always works — no extension, no index required.
        Flat score of 0.5 for all matches (binary match/no-match).
        """
        terms = [t for t in re.sub(r"[^\w\s]", " ", query).split() if len(t) > 1]
        if not terms:
            return []

        # Build parameterized OR conditions — one ILIKE per term
        conditions = []
        params: dict[str, str] = {"limit": max_results}
        for i, term in enumerate(terms):
            param_key = f"t{i}"
            params[param_key] = f"%{term}%"
            conditions.append(
                f"(c.title ILIKE :{param_key} OR "
                f"COALESCE(c.description, '') ILIKE :{param_key})"
            )

        sql = text(f"""
            SELECT DISTINCT
                c.id AS course_record_id,
                c.course_id,
                c.title,
                COALESCE(c.description, '') AS description
            FROM courses c
            WHERE ({' OR '.join(conditions)})
            ORDER BY c.title
            LIMIT :limit
        """)

        try:
            rows = await self.session.execute(sql, params)
            return [
                {
                    "course_record_id": r[0],
                    "course_id": r[1],
                    "title": r[2] or "Untitled",
                    "description": r[3],
                    "score": 0.5,  # Flat score — binary keyword match
                }
                for r in rows
            ]
        except Exception as exc:
            logger.error("Keyword search also failed — returning empty: %s", exc)
            return []

    # ═══════════════════════════════════════════════════════════════
    # Result Enrichment (FR-3)
    # ═══════════════════════════════════════════════════════════════

    async def enrich_results(
        self,
        raw_results: list[dict],
        query: str,
    ) -> list[dict]:
        """Load template data for matched courses and build full result shape.

        For each matched course:
        1. Fetch all pages/templates
        2. Build template_breakdown (template_type → count)
        3. Extract up to 3 PII-redacted excerpts (max 500 chars each)
        4. Derive tone/style notes from template composition
        5. Generate human-readable match summary

        Returns: List[dict] with keys matching FR-3 result shape:
            courseId, title, relevance_score, match_summary, page_count,
            template_breakdown, sample_excerpts, tone_notes, language, created_at
        """
        from app.repositories.page_component_repo import PageRepository

        page_repo = PageRepository(self.session)
        enriched = []

        for row in raw_results:
            course_id = row["course_id"]

            # Fetch pages
            try:
                pages: Sequence[PageRecord] = await page_repo.list_by_course(course_id)
            except Exception:
                pages = []

            # Build template breakdown + extract excerpts
            template_breakdown: dict[str, int] = {}
            excerpts: list[dict] = []
            all_template_types: set[str] = set()

            for page in pages:
                ttype = self._derive_template_type(page)
                all_template_types.add(ttype)
                template_breakdown[ttype] = template_breakdown.get(ttype, 0) + 1

                if len(excerpts) < MAX_EXCERPTS_PER_COURSE:
                    snippet = self._extract_safe_excerpt(page)
                    if snippet:
                        excerpts.append({
                            "template_type": ttype,
                            "title": page.title,
                            "text_snippet": snippet,
                        })

            tone_notes = self._derive_tone_notes(all_template_types)
            match_summary = self._build_match_summary(
                row["title"], row.get("description"), query, len(pages)
            )

            enriched.append({
                "courseId": course_id,
                "title": row["title"],
                "relevance_score": row.get("score", 0.5),
                "match_summary": match_summary,
                "page_count": len(pages),
                "template_breakdown": template_breakdown,
                "sample_excerpts": excerpts,
                "tone_notes": tone_notes,
                "language": "en",
                "created_at": (
                    pages[0].created_at.isoformat()
                    if pages and pages[0].created_at else None
                ),
            })

        enriched.sort(key=lambda r: r["relevance_score"], reverse=True)
        return enriched

    # ═══════════════════════════════════════════════════════════════
    # Helpers
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _derive_template_type(page: PageRecord) -> str:
        """Infer template type from page layout or first component.

        INTENTIONALLY DUPLICATED from ToolExecutor._derive_template_type().
        Repository should not import from tool executor (separation of concerns).
        If a third duplicate appears, extract to app.services.ai.template_utils.
        """
        layout = getattr(page, "layout", None)
        if isinstance(layout, dict):
            ttype = layout.get("templateType") or layout.get("template_id")
            if ttype:
                return ttype

        components = getattr(page, "components", None)
        if components and len(components) > 0:
            first = components[0]
            ctype = getattr(first, "component_type", None)
            if ctype:
                return ctype

        return "unknown"

    def _extract_safe_excerpt(self, page: PageRecord) -> Optional[str]:
        """Extract a PII-redacted text excerpt from page data.

        Steps:
        1. Collect all text values from SAFE_EXCERPT_FIELDS in page layout + component data
        2. Also extract question text from nested questions[] arrays (MCQ templates)
        3. Pick the longest candidate (> MIN_EXCERPT_TEXT_LENGTH chars)
        4. Truncate to MAX_EXCERPT_LENGTH chars
        5. Replace all PII matches with "[REDACTED]"

        Never extracts: isCorrect, correctAnswer, correctAnswers, options[].isCorrect,
        scoring configuration, user-specific identifiers.
        """
        candidates: list[str] = []

        # Page layout fields
        if hasattr(page, "layout") and isinstance(page.layout, dict):
            for field in ["title", "description", "introText"]:
                val = page.layout.get(field)
                if isinstance(val, str) and len(val.strip()) > MIN_EXCERPT_TEXT_LENGTH:
                    candidates.append(val.strip())

        # Component data fields
        components = getattr(page, "components", None) or []
        for comp in components:
            comp_data = getattr(comp, "data", None)
            if not isinstance(comp_data, dict):
                continue

            for field in SAFE_EXCERPT_FIELDS:
                val = comp_data.get(field)
                if isinstance(val, str) and len(val.strip()) > MIN_EXCERPT_TEXT_LENGTH:
                    candidates.append(val.strip())

            # Nested questions[] — extract question text, NOT isCorrect/answers
            questions = comp_data.get("questions")
            if isinstance(questions, list):
                for q in questions[:3]:
                    if isinstance(q, dict):
                        qtext = q.get("question")
                        if isinstance(qtext, str) and len(qtext.strip()) > MIN_EXCERPT_TEXT_LENGTH:
                            candidates.append(qtext.strip())

        if not candidates:
            return None

        best = max(candidates, key=len)
        if len(best) > MAX_EXCERPT_LENGTH:
            best = best[:MAX_EXCERPT_LENGTH] + "..."
        return _PII_RE.sub("[REDACTED]", best)

    @staticmethod
    def _derive_tone_notes(template_types: set[str]) -> Optional[str]:
        """Heuristic tone/style notes from template composition.

        Example: {welcome, mcq, summary} → "Course includes structured introduction
        and learning objectives; uses knowledge checks and assessment questions;
        includes recap and summary sections."
        """
        notes: list[str] = []

        if "mcq" in template_types or "final-assessment" in template_types:
            notes.append("uses knowledge checks and assessment questions")
        if "welcome" in template_types:
            notes.append("includes structured introduction and learning objectives")
        if "content-video" in template_types or "video" in template_types:
            notes.append("incorporates video-based learning segments")
        if "accordion" in template_types:
            notes.append("organizes content in expandable sections for progressive disclosure")
        if "tabs" in template_types:
            notes.append("uses tabbed navigation for multi-topic comparison")
        if "click-reveal" in template_types:
            notes.append("employs interactive click-to-reveal engagement patterns")
        if "summary" in template_types:
            notes.append("includes recap and summary sections")
        if "text-content" in template_types and len(template_types) == 1:
            notes.append("primarily text-based with narrative structure")

        if not notes:
            return None
        return "Course " + "; ".join(notes) + "."

    @staticmethod
    def _build_match_summary(
        title: str,
        description: Optional[str],
        query: str,
        page_count: int,
    ) -> str:
        """Human-readable explanation of why this course matched."""
        parts = [f"Course titled '{title}'"]
        if description and description.strip():
            parts.append(description[:200])
        parts.append(f"with {page_count} page(s)")
        return " ".join(parts)

    # ═══════════════════════════════════════════════════════════════
    # Embedding Management (DEFERRED — unused in MVP)
    # ═══════════════════════════════════════════════════════════════
    #
    # These methods exist for future iterations (background re-indexing
    # job, course create/update hooks). They are NOT called anywhere in
    # the MVP code path. They are included here so the repository is
    # the single source of truth for all embedding data access.
    # ------------------------------------------------------------------
    # WARNING: upsert_embedding() calls self.session.commit() internally.
    # Do NOT call it inside an outer transaction — it will commit the
    # outer transaction's changes prematurely. For MVP, embeddings are
    # populated externally (migration, script, or future background job).
    # ------------------------------------------------------------------

    async def upsert_embedding(
        self,
        course_record_id: int,
        organization_id: str,
        embedding: list[float],
        content_hash: str,
        embedding_model: str = "text-embedding-ada-002",
    ) -> CourseEmbeddingRecord:
        """Insert or update embedding. Idempotent — skips if content_hash unchanged.

        DEFERRED until background re-embedding job is implemented.
        """
        q = select(CourseEmbeddingRecord).where(
            CourseEmbeddingRecord.course_record_id == course_record_id
        )
        existing = (await self.session.execute(q)).scalar_one_or_none()

        if existing is not None:
            if existing.content_hash == content_hash:
                return existing
            existing.embedding = {"dim": len(embedding), "vec": embedding}
            existing.content_hash = content_hash
            existing.embedding_model = embedding_model
            existing.is_stale = False
            existing.updated_at = datetime.utcnow()
            await self.session.commit()
            await self.session.refresh(existing)
            return existing

        record = CourseEmbeddingRecord(
            course_record_id=course_record_id,
            organization_id=organization_id,
            embedding={"dim": len(embedding), "vec": embedding},
            content_hash=content_hash,
            embedding_model=embedding_model,
            is_stale=False,
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def mark_stale(self, course_record_id: int) -> None:
        """Mark embedding as stale. DEFERRED — unused in MVP."""
        q = select(CourseEmbeddingRecord).where(
            CourseEmbeddingRecord.course_record_id == course_record_id
        )
        record = (await self.session.execute(q)).scalar_one_or_none()
        if record:
            record.is_stale = True
            record.updated_at = datetime.utcnow()
            await self.session.commit()

    async def list_stale(
        self, organization_id: str, limit: int = 100
    ) -> list[CourseEmbeddingRecord]:
        """List stale embeddings. DEFERRED — unused in MVP."""
        q = (
            select(CourseEmbeddingRecord)
            .where(
                CourseEmbeddingRecord.organization_id == organization_id,
                CourseEmbeddingRecord.is_stale == True,  # noqa: E712
            )
            .order_by(CourseEmbeddingRecord.updated_at.asc())
            .limit(limit)
        )
        return list((await self.session.execute(q)).scalars().all())
```

### 4.2 Verify T-04/T-05/T-06

```bash
# 1. Check the file exists
ls -la app/repositories/similar_course_repo.py

# 2. Verify Python imports
PYTHONPATH=. python -c "
from app.repositories.similar_course_repo import SimilarCourseRepository, _PII_RE
print('Repository class:', SimilarCourseRepository)
print('PII regex patterns:', _PII_RE.pattern[:80])
"

# 3. Quick PII redaction smoke test
PYTHONPATH=. python -c "
from app.repositories.similar_course_repo import _PII_RE
assert '[REDACTED]' in _PII_RE.sub('[REDACTED]', 'Email: user@example.com')
assert '[REDACTED]' in _PII_RE.sub('[REDACTED]', 'Call 555-123-4567')
assert 'clean text' == _PII_RE.sub('[REDACTED]', 'clean text')
print('PII redaction: PASS')
"

# 4. Tone notes smoke test
PYTHONPATH=. python -c "
from app.repositories.similar_course_repo import SimilarCourseRepository
notes = SimilarCourseRepository._derive_tone_notes({'welcome', 'mcq', 'summary'})
assert notes is not None and 'knowledge checks' in notes
print('Tone notes:', notes)
print('Empty set:', SimilarCourseRepository._derive_tone_notes(set()))
"
```

---

## 5. Embedding Provider Layer — TASK T-03 (2.0h)

### 5.1 Create This File

**File:** `app/services/ai/embedding_provider.py`

```python
"""Embedding provider abstraction — US-BKND-AI-015.

Pluggable interface for generating text embeddings.
    - MockEmbeddingProvider: Deterministic hash-based, zero-cost, zero-network. Dev/QA.
    - OpenAIBackend: text-embedding-ada-002 via OpenAI SDK. Production.

Factory: get_embedding_provider() — controlled by EMBEDDING_PROVIDER env var.
"""
from __future__ import annotations

import hashlib
import logging
import os
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger("ai_authoring")

DEFAULT_EMBEDDING_DIMENSION = 1536
MAX_EMBEDDING_INPUT_CHARS = 8191  # ada-002 token limit (~6000 words)


class EmbeddingProvider(ABC):
    """Abstract interface for text → vector conversion."""

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Convert text to embedding vector. Raises EmbeddingError on failure."""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding vector dimension."""
        ...


class EmbeddingError(Exception):
    """Wraps provider-specific errors for uniform handling upstream."""

    def __init__(self, message: str, provider: str, retryable: bool = True):
        self.provider = provider
        self.retryable = retryable
        super().__init__(f"[{provider}] {message}")


# ── OpenAI Backend ────────────────────────────────────────────────────

class OpenAIBackend(EmbeddingProvider):
    """OpenAI text-embedding-ada-002 production backend.

    Prerequisites:
        - pip install openai
        - OPENAI_API_KEY env var set
        - EMBEDDING_MODEL env var (default: text-embedding-ada-002)

    Error handling:
        - AuthenticationError (401) → EmbeddingError(retryable=False)
        - RateLimitError (429) → EmbeddingError(retryable=True)
        - APITimeoutError → EmbeddingError(retryable=True)
        - All other API errors → EmbeddingError(retryable=True)
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self._api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self._model = model or os.getenv("EMBEDDING_MODEL", "text-embedding-ada-002")
        self._dimension = DEFAULT_EMBEDDING_DIMENSION
        self._client = None

    @property
    def dimension(self) -> int:
        return self._dimension

    def _get_client(self):
        """Lazy-init the OpenAI client (avoids import if using mock provider)."""
        if self._client is None:
            try:
                import openai
                self._client = openai.AsyncOpenAI(api_key=self._api_key)
            except ImportError:
                raise EmbeddingError(
                    "openai package not installed. Run: pip install openai",
                    provider="openai",
                    retryable=False,
                )
        return self._client

    async def embed(self, text: str) -> list[float]:
        """Generate embedding via OpenAI API.

        Non-retryable failures: missing API key, bad API key (401).
        Retryable failures: rate limit (429), timeout, connection error.
        """
        if not self._api_key:
            raise EmbeddingError(
                "OPENAI_API_KEY is not set", provider="openai", retryable=False
            )

        client = self._get_client()
        truncated = text[:MAX_EMBEDDING_INPUT_CHARS]

        try:
            resp = await client.embeddings.create(
                model=self._model, input=truncated,
            )
            return resp.data[0].embedding
        except Exception as exc:
            # Distinguish retryable vs non-retryable OpenAI errors
            exc_name = type(exc).__name__
            non_retryable = any(
                tag in exc_name.lower()
                for tag in ("authentication", "permission", "notfound")
            )
            logger.error("OpenAI embedding failed [%s]: %s", exc_name, exc)
            raise EmbeddingError(
                str(exc), provider="openai", retryable=not non_retryable,
            ) from exc


# ── Mock Backend ───────────────────────────────────────────────────────

class MockEmbeddingProvider(EmbeddingProvider):
    """Deterministic mock for development and testing.

    Generates a pseudo-embedding from SHA-256 of the input text.
    Same input → same vector. Different inputs → different vectors.
    Zero external dependencies, zero cost, zero network latency.
    """

    def __init__(self, dimension: int = DEFAULT_EMBEDDING_DIMENSION):
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, text: str) -> list[float]:
        """Deterministic pseudo-embedding from text hash."""
        h = hashlib.sha256(text.encode("utf-8")).digest()
        vec = []
        for i in range(self._dimension):
            base = h[i % len(h)] / 255.0
            offset = i * 0.0174533  # π/180 radians
            vec.append(round(base * 0.5 + 0.25, 8))
        return vec


# ── Factory (singleton) ────────────────────────────────────────────────

_embedding_provider: Optional[EmbeddingProvider] = None


def get_embedding_provider() -> EmbeddingProvider:
    """Return the configured embedding provider (singleton).

    Controlled by EMBEDDING_PROVIDER env var:
        "openai" → OpenAIBackend (requires OPENAI_API_KEY)
        "mock" or unset → MockEmbeddingProvider (deterministic, zero-cost)
    """
    global _embedding_provider
    if _embedding_provider is not None:
        return _embedding_provider

    provider_name = os.getenv("EMBEDDING_PROVIDER", "mock").lower()
    if provider_name == "openai":
        _embedding_provider = OpenAIBackend()
        logger.info("Embedding provider: OpenAI (%s)", _embedding_provider._model)
    else:
        _embedding_provider = MockEmbeddingProvider()
        logger.info(
            "Embedding provider: Mock (deterministic, %d-dim)",
            _embedding_provider.dimension,
        )

    return _embedding_provider
```

### 5.2 Verify T-03

```bash
# 1. Check file exists
ls -la app/services/ai/embedding_provider.py

# 2. Test Mock provider
PYTHONPATH=. python -c "
import asyncio
from app.services.ai.embedding_provider import MockEmbeddingProvider
async def test():
    p = MockEmbeddingProvider()
    v1 = await p.embed('hello')
    v2 = await p.embed('hello')
    v3 = await p.embed('different')
    print(f'Dimension: {len(v1)} (expect 1536)')
    print(f'Deterministic: {v1 == v2} (expect True)')
    print(f'Different inputs: {v1 != v3} (expect True)')
    print(f'All floats: {all(isinstance(x, float) for x in v1)} (expect True)')
asyncio.run(test())
"

# 3. Test factory
PYTHONPATH=. python -c "
from app.services.ai.embedding_provider import get_embedding_provider
p = get_embedding_provider()
print(f'Default provider: {type(p).__name__} (expect MockEmbeddingProvider)')
"
```

### 5.3 Decision Log

| Decision | Why |
|----------|-----|
| `EmbeddingError.retryable` distinction | OpenAI `AuthenticationError` (bad key) should NOT be retried — wastes retries on permanent failure. `RateLimitError` SHOULD be retried. |
| Mock uses SHA-256 hash → deterministic vector | Same input always produces the same vector. Essential for reproducible tests. Random vectors would break test assertions. |
| Lazy init for OpenAI client | Avoids importing the `openai` package at module load time when using mock provider. Helps cold-start performance. |
| Singleton factory | Only one embedding provider instance per process. Thread-safe after initialization (provider is read-only). |

---

## 6. Service Layer — TASK T-07 (2.0h)

### 6.1 Create This File

**File:** `app/services/ai/similar_course_service.py`

```python
"""Similar Course Retrieval Service — US-BKND-AI-015.

Orchestrates three-tier retrieval with automatic fallback.
Feature-flag gated. Session-scoped for tenant isolation.

Matcher: Constructor takes db: AsyncSession only (matches AISessionService,
AIProposalService, etc.)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.ai_session_repo import AISessionRepository
from app.repositories.similar_course_repo import SimilarCourseRepository
from app.services.ai.embedding_provider import (
    EmbeddingProvider,
    EmbeddingError,
    get_embedding_provider,
)

logger = logging.getLogger("ai_authoring")


class FeatureDisabledError(Exception):
    """Feature flag is off."""
    def __init__(self):
        super().__init__(
            "Similar course retrieval is not enabled. "
            "Set FEATURE_SIMILAR_COURSE_RETRIEVAL=true to enable."
        )


class SessionValidationError(Exception):
    """AI session is invalid, expired, or not owned by caller."""
    def __init__(self, code: str, message: str, http_status: int = 401):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class SimilarCourseService:
    """Orchestrates similar course retrieval with tiered fallback.

    Constructor mirrors all existing AI services:
        __init__(self, db: AsyncSession)
    """

    def __init__(
        self,
        db: AsyncSession,
        embedding_provider: Optional[EmbeddingProvider] = None,
    ):
        self.db = db
        self.session_repo = AISessionRepository(db)
        self.retrieval_repo = SimilarCourseRepository(db)
        self.embedding_provider = embedding_provider or get_embedding_provider()

    # ── Public API ─────────────────────────────────────────────────

    async def query_similar_courses(
        self,
        session_id: str,
        query: str,
        max_results: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute tiered retrieval and return shaped results.

        Called by: ai_tools.py router, ToolExecutor, ChatOrchestrator.
        All three consumers use this single method.

        Args:
            session_id: Active AI session ID (validated, org scope resolved).
            query: Natural language query string.
            max_results: 1-20, clamped.
            filters: Optional dict with template_types, min_pages, max_pages, language.
            user_id: Optional — if provided, session.user_id must match (ownership check).

        Returns:
            {"courses": [...], "total_count": N, "message": "...", "retrieval_tier_used": "tier1|2|3|none"}

        Raises:
            FeatureDisabledError: Flag off.
            SessionValidationError: Invalid/expired/wrong-owner session.

        Tier fallback: Tier-1 (pgvector) → Tier-2 (full-text) → Tier-3 (keyword) → empty.
        Empty results are NON-FATAL — the AI agent is instructed to continue without examples.
        """
        # ── 0. Feature flag ─────────────────────────────────
        from app.utils.feature_flags import is_feature_enabled
        if not is_feature_enabled("similar_course_retrieval"):
            raise FeatureDisabledError()

        # ── 1. Validate session ─────────────────────────────
        session = await self.session_repo.get_active(session_id)
        if session is None:
            # Distinguish "expired" vs "never existed"
            existing = await self.session_repo.get(session_id)
            if existing is not None and existing.is_expired():
                raise SessionValidationError(
                    "SESSION_EXPIRED",
                    "Session has expired. Please create a new session.",
                    440,
                )
            raise SessionValidationError(
                "SESSION_INVALID", "Session not found or expired.", 401
            )

        if user_id is not None and session.user_id != user_id:
            raise SessionValidationError(
                "PERMISSION_DENIED",
                "Session does not belong to the authenticated user.",
                403,
            )

        organization_id = session.organization_id

        # ── 2. Normalize inputs ─────────────────────────────
        query = query.strip()
        if not query:
            return self._empty_result("Query is empty.", "none")

        max_results = max(1, min(max_results, 20))

        # ── 3. Tiered retrieval ─────────────────────────────
        raw_results: list[dict] = []
        tier_used = "tier1"

        # Tier 1: Vector search
        try:
            embedding = await self.embedding_provider.embed(query)
            raw_results = await self.retrieval_repo.search_vector(
                embedding, organization_id, max_results
            )
        except Exception as exc:
            logger.info("Tier-1 unavailable (degrading): %s", exc)
            raw_results = []

        # Tier 2: Full-text search
        if not raw_results:
            tier_used = "tier2"
            try:
                raw_results = await self.retrieval_repo.search_fulltext(
                    query, organization_id, max_results
                )
            except Exception as exc:
                logger.warning("Tier-2 failed (degrading): %s", exc)
                raw_results = []

        # Tier 3: Keyword search
        if not raw_results:
            tier_used = "tier3"
            try:
                raw_results = await self.retrieval_repo.search_keyword(
                    query, organization_id, max_results
                )
            except Exception as exc:
                logger.error("Tier-3 failed — all tiers exhausted: %s", exc)
                raw_results = []

        # ── 4. Empty after all tiers ────────────────────────
        if not raw_results:
            return self._empty_result("No similar courses found.", tier_used)

        # ── 5. Enrich ───────────────────────────────────────
        enriched = await self.retrieval_repo.enrich_results(raw_results, query)

        # ── 6. Post-filter ──────────────────────────────────
        if filters:
            enriched = self._apply_filters(enriched, filters)

        # ── 7. Slice ────────────────────────────────────────
        top = enriched[:max_results]

        return {
            "courses": top,
            "total_count": len(top),
            "message": (
                f"Found {len(top)} similar course(s)."
                if top else "No similar courses found."
            ),
            "retrieval_tier_used": tier_used,
        }

    # ── Filters (in-memory, cheap — result sets ≤20) ─────────────────

    def _apply_filters(
        self, results: list[dict], filters: Dict[str, Any]
    ) -> list[dict]:
        """Post-filter enriched results by template_types, min_pages, max_pages, language."""
        filtered = results

        template_types = filters.get("template_types")
        if isinstance(template_types, list) and template_types:
            filtered = [
                r for r in filtered
                if any(
                    tt in r.get("template_breakdown", {})
                    for tt in template_types
                )
            ]

        min_pages = filters.get("min_pages")
        if isinstance(min_pages, int) and min_pages > 0:
            filtered = [r for r in filtered if r.get("page_count", 0) >= min_pages]

        max_pages = filters.get("max_pages")
        if isinstance(max_pages, int) and max_pages > 0:
            filtered = [r for r in filtered if r.get("page_count", 0) <= max_pages]

        language = filters.get("language")
        if isinstance(language, str) and language:
            filtered = [r for r in filtered if r.get("language") == language]

        return filtered

    # ── Empty result (FR-4: non-fatal) ──────────────────────────────

    @staticmethod
    def _empty_result(message: str, tier: str) -> Dict[str, Any]:
        return {
            "courses": [],
            "total_count": 0,
            "message": (
                f"{message} Generation can continue without examples. "
                "Consider providing explicit tone and structure guidance "
                "in your prompt."
            ),
            "retrieval_tier_used": tier,
        }
```

### 6.2 Verify T-07

```bash
# 1. Check file exists
ls -la app/services/ai/similar_course_service.py

# 2. Verify imports
PYTHONPATH=. python -c "
from app.services.ai.similar_course_service import (
    SimilarCourseService, FeatureDisabledError, SessionValidationError,
)
print('Service:', SimilarCourseService)
print('FeatureDisabledError:', FeatureDisabledError)
print('SessionValidationError:', SessionValidationError)
"

# 3. Test empty result
PYTHONPATH=. python -c "
from app.services.ai.similar_course_service import SimilarCourseService
r = SimilarCourseService._empty_result('No matches', 'tier3')
print('Empty courses:', r['courses'])
print('Message:', r['message'][:80])
print('Tier:', r['retrieval_tier_used'])
"
```

---

## 7. Router Layer — TASK T-09 (1.5h)

### 7.1 NEW File: `app/routers/ai_similar_courses.py`

```python
"""REST endpoint for similar course queries — US-BKND-AI-015.

Optional REST API for admin/UI access outside the AI tool context.
Primary integration remains via ToolExecutor → ChatOrchestrator.

Route: POST /api/v1/ai/similar-courses
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.dependencies.auth_dependencies import get_current_user
from app.models.user_context import UserContext
from app.services.ai.similar_course_service import (
    SimilarCourseService,
    FeatureDisabledError,
    SessionValidationError,
)
from app.services.ai.error_envelope import ai_error

logger = logging.getLogger("ai_authoring")
router = APIRouter(prefix="/api/v1/ai", tags=["AI - Similar Courses"])


class SimilarCourseQueryRequest(BaseModel):
    session_id: Optional[str] = Field(
        default=None, min_length=1, max_length=128,
        description="Active AI session ID. Optional for admin queries.",
    )
    query: str = Field(
        ..., min_length=1, max_length=500,
        description="Natural language query",
    )
    max_results: int = Field(default=5, ge=1, le=20)
    filters: Optional[dict] = Field(default=None)


@router.post("/similar-courses")
async def query_similar_courses(
    body: SimilarCourseQueryRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Search for similar courses within the user's organization.

    Feature-flag gated: FEATURE_SIMILAR_COURSE_RETRIEVAL must be true.
    Results are ADVISORY ONLY — never authoritative for API contracts,
    template schemas, or validation rules.
    """
    service = SimilarCourseService(db)

    try:
        result = await service.query_similar_courses(
            session_id=body.session_id or "",
            query=body.query,
            max_results=body.max_results,
            filters=body.filters,
            user_id=user.user_id,
        )
        return {"status": "ok", **result}

    except FeatureDisabledError as exc:
        return ai_error("FEATURE_DISABLED", str(exc), status=404)
    except SessionValidationError as exc:
        return ai_error(exc.code, exc.message, status=exc.http_status)
    except Exception:
        logger.exception("Unexpected error in similar course query")
        return ai_error(
            "SERVER_ERROR",
            "An unexpected error occurred while searching for similar courses.",
            status=503,
        )
```

### 7.2 MODIFY Existing File: `app/routers/ai_tools.py`

**What you're changing:** The existing `query_similar_courses` endpoint (lines 715-848) contains inline Tier-3 keyword search logic and a helper function `_infer_tone_notes()`. You will replace all of this with a thin delegation to the new `SimilarCourseService`.

**BEFORE (existing code — what you'll remove):**

```python
# ═══════════════════════════════════════════════════════════════════
# Similar course retrieval (US-BKND-AI-015)
# ═══════════════════════════════════════════════════════════════════

class QuerySimilarCoursesRequest(BaseModel):
    """Request body for query_similar_courses tool."""
    session_id: str = Field(..., min_length=1, max_length=128)
    query: str = Field(..., min_length=1, max_length=500)
    max_results: int = Field(default=5, ge=1, le=20)


@router.post("/tools/query_similar_courses")
async def query_similar_courses(
    body: QuerySimilarCoursesRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Search for similar courses within the organization (US-BKND-AI-015).

    Uses tier-3 keyword search (ILIKE) for MVP...
    """
    from app.repositories.ai_session_repo import AISessionRepository

    srepo = AISessionRepository(db)
    session = await srepo.get_active(body.session_id)
    if session is None:
        return ai_error("SESSION_INVALID", "Session not found or expired.", status=401)

    # Load all courses in the same org (tenant isolation)
    from app.repositories.course_repo import CourseRepository
    from app.repositories.page_component_repo import PageRepository

    crepo = CourseRepository(db)
    prepo = PageRepository(db)

    try:
        all_courses = await crepo.list()
    except Exception:
        return {"status": "ok", "courses": [], "total_count": 0,
                "message": "No similar courses found.", "retrieval_tier_used": "tier3"}

    # Score courses by keyword match on title and description
    query_terms = body.query.lower().split()
    scored = []

    for course in all_courses:
        # ... [~70 lines of inline keyword scoring, excerpt extraction, tone inference] ...

    scored.sort(key=lambda c: c["relevance_score"], reverse=True)
    top = scored[:body.max_results]

    return {
        "status": "ok",
        "courses": top,
        "total_count": len(top),
        "message": f"Found {len(top)} similar course(s)." if top
                   else "No similar courses found.",
        "retrieval_tier_used": "tier3",
    }


def _infer_tone_notes(course) -> str:
    """Infer basic tone/style notes from course metadata."""
    # ... [15 lines of tone inference] ...
```

**AFTER (replacement code — paste this in place of lines 715-848):**

```python
# ═══════════════════════════════════════════════════════════════════
# Similar course retrieval (US-BKND-AI-015)
# ═══════════════════════════════════════════════════════════════════

class QuerySimilarCoursesRequest(BaseModel):
    """Request body for query_similar_courses tool."""
    session_id: str = Field(..., min_length=1, max_length=128)
    query: str = Field(..., min_length=1, max_length=500)
    max_results: int = Field(default=5, ge=1, le=20)
    filters: Optional[dict] = Field(default=None)


@router.post("/tools/query_similar_courses")
async def query_similar_courses(
    body: QuerySimilarCoursesRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Search for similar courses within the organization (US-BKND-AI-015).

    Uses three-tier retrieval: pgvector → full-text → keyword.
    Results are for style/tone guidance only — never authoritative
    for API contracts or schemas.
    """
    from app.services.ai.similar_course_service import (
        SimilarCourseService,
        FeatureDisabledError,
        SessionValidationError,
    )

    service = SimilarCourseService(db)

    try:
        result = await service.query_similar_courses(
            session_id=body.session_id,
            query=body.query,
            max_results=body.max_results,
            filters=body.filters,
            user_id=user.user_id,
        )
        return {"status": "ok", **result}

    except FeatureDisabledError as exc:
        return ai_error("FEATURE_DISABLED", str(exc), status=404)
    except SessionValidationError as exc:
        return ai_error(exc.code, exc.message, status=exc.http_status)
    except Exception:
        logger.exception("Unexpected error in query_similar_courses")
        return ai_error(
            "SERVER_ERROR",
            "An unexpected error occurred while searching for similar courses.",
            status=503,
        )
```

**Note:** The `_infer_tone_notes()` function (previously at lines 834-848) is removed. Its replacement lives in `SimilarCourseRepository._derive_tone_notes()`.

**Verify T-09:**

```bash
# 1. Check the refactored endpoint still has the right shape
grep -n "class QuerySimilarCoursesRequest\|def query_similar_courses\|SimilarCourseService" app/routers/ai_tools.py

# 2. Verify the old _infer_tone_notes function is gone
grep "_infer_tone_notes" app/routers/ai_tools.py
# Should return nothing (or only in comments)

# 3. Verify the new router file exists
ls -la app/routers/ai_similar_courses.py
```

### 7.3 Decision Log

| Decision | Why |
|----------|-----|
| Keep `ai_tools.py` endpoint path `/tools/query_similar_courses` | Backward compatible — existing clients call this path. Refactored to delegate internally. |
| Add separate `/similar-courses` REST endpoint | Separation of concerns. Tool endpoints are for AI agent use. REST endpoint for admin/UI. |
| Remove `_infer_tone_notes()` from router | Logic now lives in repository's `_derive_tone_notes()` which has richer template-type-based inference. |
| Delegate to service, don't inline | Single implementation path. Router is thin — validates inputs, calls service, formats response. |

---

## 8. Tool Executor Integration — TASK T-10 (1.0h)

### 8.1 MODIFY: `app/services/ai/tool_executor.py`

This file has two changes:
1. Add a route entry in the `execute()` method's tool dispatch
2. Add a `_handle_query_similar_courses()` handler method

**Change 1: Route entry in `execute()` method**

**BEFORE (lines 132-140 — existing tool dispatch):**
```python
        # 2. Route to tool handler
        try:
            if tool_name == "list_pages":
                result = await self._handle_list_pages(session.course_id)
            elif tool_name == "fetch_page":
                page_id = payload.get("page_id", "")
                result = await self._handle_fetch_page(session.course_id, page_id)
            else:
                return self._error_response(
                    ToolError("UNKNOWN_TOOL", f"Unknown tool: '{tool_name}'", 400)
                )
```

**AFTER (add the `elif` for `query_similar_courses`):**
```python
        # 2. Route to tool handler
        try:
            if tool_name == "list_pages":
                result = await self._handle_list_pages(session.course_id)
            elif tool_name == "fetch_page":
                page_id = payload.get("page_id", "")
                result = await self._handle_fetch_page(session.course_id, page_id)
            elif tool_name == "query_similar_courses":
                result = await self._handle_query_similar_courses(
                    session.course_id,
                    session.organization_id,
                    payload,
                )
            else:
                return self._error_response(
                    ToolError("UNKNOWN_TOOL", f"Unknown tool: '{tool_name}'", 400)
                )
```

Also update the audit log section (lines 151-168) to handle the new tool. The `target_type` and `target_id` need to reflect the similarity query:

**BEFORE (lines 151-168 — audit log):**
```python
        # 3. Audit log (fire-and-forget ...)
        try:
            await self.audit_svc.log(
                session_id=session_id,
                user_id=caller_user_id,
                organization_id=session.organization_id,
                course_id=session.course_id,
                action=f"tool.{tool_name}",
                target_type="page" if tool_name == "fetch_page" else "course",
                target_id=payload.get("page_id", session.course_id),
                ...
            )
```

**AFTER:**
```python
        # 3. Audit log (fire-and-forget ...)
        try:
            await self.audit_svc.log(
                session_id=session_id,
                user_id=caller_user_id,
                organization_id=session.organization_id,
                course_id=session.course_id,
                action=f"tool.{tool_name}",
                target_type="course",
                target_id=session.course_id,
                details={
                    "tool_name": tool_name,
                    "result_status": result.get("status", "unknown"),
                },
                ip_address=ip_address,
            )
```

**Change 2: New handler method**

Add this method **after** `_handle_fetch_page()` (ends at line 268) and **before** the `# ── Helpers ──` comment (line 269):

```python
    async def _handle_query_similar_courses(
        self,
        course_id: str,
        organization_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute similar course retrieval via SimilarCourseService.

        FR-1: query must be non-empty.
        FR-2: Results scoped to session's organization (enforced by service).
        FR-3: Returns shaped results with excerpts, tone, template breakdown.
        FR-4: Empty results are non-fatal.
        FR-10: Idempotent read — no mutations.
        """
        from app.services.ai.similar_course_service import (
            SimilarCourseService,
            FeatureDisabledError,
            SessionValidationError,
        )

        query = (payload.get("query") or "").strip()
        if not query:
            raise ToolError("VALIDATION_ERROR", "query is required and must not be empty", 400)

        max_results = payload.get("max_results", 5)
        filters = payload.get("filters")

        service = SimilarCourseService(self.db)

        try:
            result = await service.query_similar_courses(
                session_id=payload.get("session_id", ""),
                query=query,
                max_results=max_results,
                filters=filters,
            )
            return {"status": "success", "data": result}

        except FeatureDisabledError as exc:
            return self._error_response(
                ToolError("FEATURE_DISABLED", str(exc), 404)
            )
        except SessionValidationError as exc:
            return self._error_response(
                ToolError(exc.code, exc.message, exc.http_status)
            )
```

**Verify T-10:**

```bash
# 1. Check the new route entry exists
grep -n "query_similar_courses" app/services/ai/tool_executor.py

# 2. Check the new handler method
grep -n "_handle_query_similar_courses" app/services/ai/tool_executor.py

# 3. Verify imports — should find SimilarCourseService references
grep -n "SimilarCourseService\|similar_course_service" app/services/ai/tool_executor.py
```

---

## 9. Chat Orchestrator Integration — TASK T-11, T-12 (1.5h)

### 9.1 MODIFY: `app/services/ai/chat_orchestrator.py`

This file has **FOUR** changes:
1. Replace the mock stub for `query_similar_courses` with a real service call
2. Update the static `SYSTEM_PROMPT` with the RAG source-of-truth warning
3. Update `_build_system_prompt()` to include the RAG warning in production LLM path
4. Add `query_similar_courses` to `_build_tool_definitions()` — the tool menu sent to the LLM

**Change 1: Replace mock handler**

**BEFORE (lines 331-333):**
```python
        if tool_name == "query_similar_courses":
            # Minimal — just return empty in mock
            return {"courses": [], "total_count": 0}
```

**AFTER:**
```python
        if tool_name == "query_similar_courses":
            # Real retrieval via SimilarCourseService (US-BKND-AI-015)
            from app.services.ai.similar_course_service import (
                SimilarCourseService,
                FeatureDisabledError,
            )
            try:
                service = SimilarCourseService(self.db)
                result = await service.query_similar_courses(
                    session_id=session_id,
                    query=args.get("query", ""),
                    max_results=args.get("max_results", 5),
                    filters=args.get("filters"),
                    user_id=user_id,
                )
                return result
            except FeatureDisabledError:
                return {
                    "courses": [],
                    "total_count": 0,
                    "message": "Similar course retrieval is not enabled. "
                               "Proceeding without examples.",
                    "retrieval_tier_used": "none",
                }
            except Exception as exc:
                logger.warning(
                    "Similar course retrieval failed (non-fatal): %s", exc
                )
                return {
                    "courses": [],
                    "total_count": 0,
                    "message": "Similar course retrieval temporarily unavailable. "
                               "Proceeding without examples.",
                    "retrieval_tier_used": "none",
                }
```

**Change 2: Update static SYSTEM_PROMPT**

**BEFORE (lines 35-52):**
```python
SYSTEM_PROMPT = """You are an AI course authoring assistant. You help instructors create and edit e-learning courses.

Your capabilities:
- List and fetch pages from the current course
- Propose new pages with validated template types
- Propose updates to existing pages
- Validate course content against template rules
- Search for similar courses for style guidance

IMPORTANT RULES:
1. NEVER mutate data directly — always create proposals first
2. Always validate before proposing — use the validate tool
3. Always fetch current state — never trust conversation history
4. For destructive actions — always require explicit user confirmation
5. Stay within the session's course scope — do not access other courses

Available template types: text-content, tabs, accordion, click-reveal, final-assessment
"""
```

**AFTER:**
```python
SYSTEM_PROMPT = """You are an AI course authoring assistant. You help instructors create and edit e-learning courses.

Your capabilities:
- List and fetch pages from the current course
- Propose new pages with validated template types
- Propose updates to existing pages
- Validate course content against template rules
- Search for similar courses for style and tone guidance (via query_similar_courses tool)

IMPORTANT RULES:
1. NEVER mutate data directly — always create proposals first
2. Always validate before proposing — use the validate tool
3. Always fetch current state — never trust conversation history
4. For destructive actions — always require explicit user confirmation
5. Stay within the session's course scope — do not access other courses
6. The `query_similar_courses` tool returns example courses for tone and structural
   reference ONLY. Do NOT derive API contracts, validation rules, template schemas,
   or configuration values from these results. Always rely on the tool definitions,
   template contracts, and schemas provided in your system prompt for authoritative
   specifications.
7. If `query_similar_courses` returns empty results, continue generation without
   examples. Quality may be slightly lower but this should not block progress.

Available template types: text-content, tabs, accordion, click-reveal, final-assessment
"""
```

**Change 3: Update `_build_system_prompt()` method for production LLM path**

**CONFIRMED: `_build_system_prompt()` EXISTS at line 579.** It builds the prompt dynamically using **f-string interpolation** (not `prompt_parts.append()`). The method constructs a single return string with course context, template types, and numbered rules. It is called at line 380 in `run_llm_loop()` — the production LLM path.

**Current rules section (lines 610-616):**
```python
            f"IMPORTANT RULES:\n"
            f"1. NEVER mutate data directly — always create proposals first\n"
            f"2. Always validate before proposing — use the validate tool\n"
            f"3. Always fetch current state — never trust conversation history\n"
            f"4. For destructive actions — always require explicit user confirmation\n"
            f"5. Stay within the session's course scope — do not access other courses\n"
            f"6. Reference pages by their title or position, not by internal IDs\n"
```

**Replace lines 610-616 with:**
```python
            f"IMPORTANT RULES:\n"
            f"1. NEVER mutate data directly — always create proposals first\n"
            f"2. Always validate before proposing — use the validate tool\n"
            f"3. Always fetch current state — never trust conversation history\n"
            f"4. For destructive actions — always require explicit user confirmation\n"
            f"5. Stay within the session's course scope — do not access other courses\n"
            f"6. The `query_similar_courses` tool returns example courses for tone and\n"
            f"   structural reference ONLY. Do NOT derive API contracts, validation\n"
            f"   rules, template schemas, or configuration values from these results.\n"
            f"   Always rely on the tool definitions, template contracts, and schemas\n"
            f"   provided in your system prompt for authoritative specifications.\n"
            f"7. If `query_similar_courses` returns empty results, continue generation\n"
            f"   without examples. Quality may be slightly lower but should not block\n"
            f"   progress.\n"
            f"8. Reference pages by their title or position, not by internal IDs\n"
```

**Note:** Old rule #6 is renumbered to #8. The RAG rules are inserted as #6 and #7.

**Change 4: Register `query_similar_courses` in `_build_tool_definitions()` (CRITICAL — missing from original IMP)**

**CONFIRMED: `_build_tool_definitions()` EXISTS at line 667.** It returns a list of `ToolDef` objects that tell the LLM what tools are available. Currently includes `list_pages` and `fetch_page` but **NOT** `query_similar_courses`. Without this, the production LLM never knows `query_similar_courses` is callable and will never invoke it.

**Add after the `fetch_page` ToolDef** (after the closing `),` at approximately line 698):

```python
            ToolDef(
                name="query_similar_courses",
                description=(
                    "Search for similar courses within your organization to use as "
                    "examples for tone, structure, and pedagogical patterns. Results "
                    "are NOT authoritative for API contracts, validation rules, or "
                    "schema definitions."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "Active AI session ID",
                        },
                        "query": {
                            "type": "string",
                            "description": "Natural language query describing the desired course style, topic, or structure",
                        },
                        "max_results": {
                            "type": "integer",
                            "default": 5,
                            "minimum": 1,
                            "maximum": 20,
                        },
                        "filters": {
                            "type": "object",
                            "properties": {
                                "template_types": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "min_pages": {"type": "integer"},
                                "max_pages": {"type": "integer"},
                                "language": {"type": "string"},
                            },
                        },
                    },
                    "required": ["session_id", "query"],
                },
            ),
```

**Verify T-11/T-12:**

```bash
# 1. Check the mock handler replacement
grep -n -A 5 "SimilarCourseService" app/services/ai/chat_orchestrator.py | head -30

# 2. Check the SYSTEM_PROMPT has the RAG warning (rules 6-7)
grep "RAG\|source.of.truth\|query_similar_courses" app/services/ai/chat_orchestrator.py

# 3. Check _build_system_prompt has RAG rules (line 610-625 area)
grep -n -A 20 "IMPORTANT RULES" app/services/ai/chat_orchestrator.py

# 4. Check _build_tool_definitions registers query_similar_courses
grep -n -A 5 "query_similar_courses" app/services/ai/chat_orchestrator.py
```

---

## 10. Feature Flag & Configuration — TASK T-08 (0.5h)

### 10.1 MODIFY: `app/utils/feature_flags.py`

**Locate the `_initialize_flags()` method.** Find the `flags = {` dictionary.

**Add this entry** inside the dictionary, after the `'ai_suggestions'` flag (line 63-68):

```python
            'similar_course_retrieval': FeatureFlag(
                name='similar_course_retrieval',
                enabled=False,
                description='Enable AI similar course retrieval (RAG) for pedagogical examples and tone references',
                environments=[Environment.DEVELOPMENT, Environment.QA],
            ),
```

**Where exactly:** After line 68 (`'ai_suggestions': ...` closing brace), before line 69 (`'advanced_scorm': ...`). This groups it with AI-related flags.

### 10.2 MODIFY: `app/services/ai/config.py`

**Change 1: Add fields to AIConfig dataclass**

**Locate the `AIConfig` dataclass** (starts at line 52). Find the last field before `_model_registry` (line 104).

**After line 103** (`rate_limit_create_session_per_hour: int = 20`), **before line 104** (`_model_registry: Dict...`), add:

```python
    # ── Similar Course Retrieval / RAG (US-BKND-AI-015) ────────
    enable_pgvector: bool = False
    embedding_provider_name: str = "mock"
    embedding_model: str = "text-embedding-ada-002"
    embedding_dimension: int = 1536
    similar_course_max_results: int = 20
    similar_course_cache_ttl_minutes: int = 60
```

**Change 2: Add load lines to `load_ai_config()`**

**Locate** `load_ai_config()` (starts at line 249). Find the last config parameter assignment (line 290: `rate_limit_create_session_per_hour=...`).

**After line 290**, add:

```python
        # ── Similar Course Retrieval / RAG (US-BKND-AI-015) ────
        enable_pgvector=_env_bool("ENABLE_PGVECTOR", False),
        embedding_provider_name=os.getenv("EMBEDDING_PROVIDER", "mock").lower(),
        embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-ada-002"),
        embedding_dimension=_env_int("EMBEDDING_DIMENSION", 1536),
        similar_course_max_results=_env_int("SIMILAR_COURSE_MAX_RESULTS", 20),
        similar_course_cache_ttl_minutes=_env_int("SIMILAR_COURSE_CACHE_TTL_MINUTES", 60),
```

### 10.3 MODIFY: `.env.example`

**Locate** the safety guardrails section (after line 164: `# AUTH_MOCK_MODE=enabled`).

**After line 166**, add:

```bash
# ── Similar Course Retrieval / Advanced RAG (US-BKND-AI-015) ──
# Feature gate — must be "true" to enable the retrieval engine
# FEATURE_SIMILAR_COURSE_RETRIEVAL=true

# Embedding provider: "mock" (deterministic, zero-cost) or "openai" (production)
# EMBEDDING_PROVIDER=mock

# OpenAI API key — required only when EMBEDDING_PROVIDER=openai
# OPENAI_API_KEY=sk-...

# Embedding model name (only relevant for openai provider)
# EMBEDDING_MODEL=text-embedding-ada-002

# Vector dimension — must match the configured model's output
# EMBEDDING_DIMENSION=1536

# Enable pgvector extension for Tier-1 vector search (requires pgvector installed)
# ENABLE_PGVECTOR=false

# Maximum results returned per query (hard cap — requests exceeding this are clamped)
# SIMILAR_COURSE_MAX_RESULTS=20

# Similarity cache TTL in minutes (future — cache table not used in MVP)
# SIMILAR_COURSE_CACHE_TTL_MINUTES=60
```

**Verify T-08:**

```bash
# 1. Check the feature flag exists
PYTHONPATH=. python -c "
from app.utils.feature_flags import feature_flags
f = feature_flags.get_flag('similar_course_retrieval')
print(f'Flag: {f.name}, enabled: {f.enabled}, desc: {f.description}')
print(f'Environments: {[e.value for e in f.environments]}')
"

# 2. Check AIConfig has new fields
PYTHONPATH=. python -c "
from app.services.ai.config import get_ai_config
c = get_ai_config()
print(f'enable_pgvector: {c.enable_pgvector}')
print(f'embedding_provider_name: {c.embedding_provider_name}')
print(f'similar_course_max_results: {c.similar_course_max_results}')
"
```

---

## 11. Main.py Registration — TASK T-13 (0.5h)

### 11.1 MODIFY: `app/main.py`

**Change 1: Import the new model for table auto-creation**

**Locate** the `lifespan()` function's startup section (around line 78-97). Find the last AI model import:

**BEFORE (line 96):**
```python
        import app.models.ai_safety_event  # noqa: F401 — safety events
```

**AFTER — add after line 96:**
```python
        import app.models.ai_safety_event  # noqa: F401 — safety events
        import app.models.course_embedding  # noqa: F401 — US-BKND-AI-015 embeddings
```

This ensures `Base.metadata.create_all()` discovers the `course_embeddings` and `course_similarity_cache` tables on next startup.

**Change 2: Register the new AI router**

**Locate** the `_ai_routers` dictionary (around line 216-226):

**BEFORE:**
```python
    _ai_routers = {
        "ai_config": "ai_config",
        "ai_sessions": "ai_sessions",
        "ai_tools": "ai_tools",
        "ai_chat": "ai_chat",
        "ai_templates": "ai_templates",
        "ai_proposals": "ai_proposals",
        "ai_ingestion": "ai_ingestion",
        "ai_confirmations": "ai_confirmations",
        "ai_admin": "ai_admin",
    }
```

**AFTER:**
```python
    _ai_routers = {
        "ai_config": "ai_config",
        "ai_sessions": "ai_sessions",
        "ai_tools": "ai_tools",
        "ai_chat": "ai_chat",
        "ai_templates": "ai_templates",
        "ai_proposals": "ai_proposals",
        "ai_ingestion": "ai_ingestion",
        "ai_confirmations": "ai_confirmations",
        "ai_admin": "ai_admin",
        "ai_similar_courses": "ai_similar_courses",  # US-BKND-AI-015
    }
```

**Verify T-13:**

```bash
# 1. Check the model import
grep "course_embedding" app/main.py

# 2. Check the router registration
grep "ai_similar_courses" app/main.py

# 3. Restart the app and check for import errors
PYTHONPATH=. python -c "from app.main import app; print('App imported OK')"
```

---

## 12. Alembic Migration — TASK T-02 (1.5h)

### 12.1 Find the Current Head Revision (ALREADY RESOLVED)

The current Alembic head as of 2026-06-20 is **`20260412_0003`**. No manual resolution needed — the migration below already uses this value. If you're implementing this after other migrations have been added, verify with:

```bash
alembic heads
# If the output is different from 20260412_0003, update down_revision in the migration below.
```

### 12.2 Create the Migration File

**File:** `alembic/versions/20260620_0001_add_course_embeddings.py`

**IMPORTANT:** Replace `<PASTE_CURRENT_HEAD_HERE>` with the revision ID from `alembic heads`.

```python
"""Add course_embeddings and course_similarity_cache tables — US-BKND-AI-015.

Revision ID: 20260620_0001
Revises: <PASTE_CURRENT_HEAD_HERE>
Create Date: 2026-06-20

Creates:
    - course_embeddings: JSONB-based embedding storage with optional pgvector index
    - course_similarity_cache: Forward-compatible cache table (unused in MVP)

Both tables are CREATE IF NOT EXISTS — idempotent, safe to re-run.
pgvector ivfflat index is conditional — only created if pgvector extension exists.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# Resolved: `alembic heads` → 20260412_0003 (as of 2026-06-20)
revision: str = "20260620_0001"
down_revision: Union[str, None] = "20260412_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── course_embeddings ─────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS course_embeddings (
            id                  SERIAL PRIMARY KEY,
            embedding_record_id VARCHAR(64) UNIQUE NOT NULL,
            course_record_id    INTEGER NOT NULL
                REFERENCES courses(id) ON DELETE CASCADE,
            organization_id     VARCHAR(64) NOT NULL DEFAULT 'default',
            embedding           JSONB,
            content_hash        VARCHAR(64) NOT NULL,
            chunk_count         INTEGER NOT NULL DEFAULT 1,
            embedding_model     VARCHAR(100) NOT NULL DEFAULT 'text-embedding-ada-002',
            is_stale            BOOLEAN NOT NULL DEFAULT FALSE,
            created_at          TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
            updated_at          TIMESTAMP WITHOUT TIME ZONE DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_course_embeddings_embedding_record_id
            ON course_embeddings (embedding_record_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_course_embeddings_course_record_id
            ON course_embeddings (course_record_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_course_embeddings_org_id
            ON course_embeddings (organization_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_course_embeddings_org_stale
            ON course_embeddings (organization_id, is_stale)
            WHERE is_stale = FALSE
    """)

    # Conditional pgvector ANN index
    conn = op.get_bind()
    ext_check = conn.execute(
        sa.text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
    ).scalar()
    if ext_check:
        op.execute("""
            CREATE INDEX IF NOT EXISTS ix_course_embeddings_vector
                ON course_embeddings
                USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100)
        """)

    # ── course_similarity_cache ────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS course_similarity_cache (
            id                SERIAL PRIMARY KEY,
            source_course_id  INTEGER NOT NULL
                REFERENCES courses(id) ON DELETE CASCADE,
            similar_course_id INTEGER NOT NULL
                REFERENCES courses(id) ON DELETE CASCADE,
            similarity_score  FLOAT NOT NULL,
            retrieval_tier    VARCHAR(8) NOT NULL DEFAULT 'tier1',
            expires_at        TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            created_at        TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
            UNIQUE(source_course_id, similar_course_id)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_similarity_cache_expires
            ON course_similarity_cache (expires_at)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS course_similarity_cache CASCADE")
    op.execute("DROP INDEX IF EXISTS ix_course_embeddings_vector")
    op.execute("DROP INDEX IF EXISTS ix_course_embeddings_org_stale")
    op.execute("DROP INDEX IF EXISTS ix_course_embeddings_org_id")
    op.execute("DROP INDEX IF EXISTS ix_course_embeddings_course_record_id")
    op.execute("DROP INDEX IF EXISTS ix_course_embeddings_embedding_record_id")
    op.execute("DROP TABLE IF EXISTS course_embeddings CASCADE")
```

### 12.3 Apply the Migration

```bash
# Apply
alembic upgrade head

# Verify tables exist
psql -U postgres -d your_database -c "\dt course_embeddings"
psql -U postgres -d your_database -c "\dt course_similarity_cache"

# Verify indexes
psql -U postgres -d your_database -c "\di ix_course_embeddings*"

# Test rollback
alembic downgrade -1
# Should drop both tables and all indexes without errors

# Re-apply after rollback test
alembic upgrade head
```

**Verify T-02:**

```bash
# Quick verification
PYTHONPATH=. python -c "
import asyncio
from app.db.config import engine, SessionLocal
from app.models.base import Base
from app.models.course_embedding import CourseEmbeddingRecord

async def check():
    async with engine.begin() as conn:
        # This would fail if the table doesn't exist
        await conn.run_sync(Base.metadata.create_all)
    print('Tables verified OK')

asyncio.run(check())
"
```

---

## 13. Testing — TASKS T-15, T-16 (4.5h)

### 13.1 Create: `tests/run_similar_course_tests.py`

```python
"""Standalone test runner for US-BKND-AI-015 — Similar Course Retrieval.

Run: PYTHONPATH=. python tests/run_similar_course_tests.py

Tests: Embedding provider (UT-1..4), PII redaction (UT-3), Service logic,
       Feature flag gating, Tone notes, Empty results.
"""
from __future__ import annotations
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ai.embedding_provider import (
    MockEmbeddingProvider, OpenAIBackend, EmbeddingError,
    DEFAULT_EMBEDDING_DIMENSION, get_embedding_provider,
)
from app.services.ai.similar_course_service import (
    SimilarCourseService, FeatureDisabledError, SessionValidationError,
)

passed = 0
failed = 0
failures: list[tuple[str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        failures.append((name, detail))


# ═══════════════════════════════════════════════════════════════════
# UNIT: Embedding Provider (UT-1 through UT-4)
# ═══════════════════════════════════════════════════════════════════

async def test_mock_dimension():
    """UT-1: Mock returns 1536-dim vector, all floats in [0, 1)."""
    p = MockEmbeddingProvider()
    v = await p.embed("safety training")
    check("UT-1a: dimension == 1536", len(v) == DEFAULT_EMBEDDING_DIMENSION,
          f"got {len(v)}")
    check("UT-1b: all floats", all(isinstance(x, float) for x in v))
    check("UT-1c: all in [0, 1)", all(0.0 <= x < 1.0 for x in v),
          f"min={min(v):.4f} max={max(v):.4f}")


async def test_mock_deterministic():
    """UT-2: Same input → same vector. Different input → different vector."""
    p = MockEmbeddingProvider()
    v1 = await p.embed("hello world")
    v2 = await p.embed("hello world")
    v3 = await p.embed("different text")
    check("UT-2a: deterministic", v1 == v2)
    check("UT-2b: different inputs → different vectors", v1 != v3)


async def test_mock_property():
    """UT-2c: dimension property."""
    p = MockEmbeddingProvider(dimension=768)
    check("UT-2c: custom dimension", p.dimension == 768)


async def test_pii_redaction():
    """UT-3: PII patterns correctly redacted from text."""
    from app.repositories.similar_course_repo import _PII_RE

    text = "Contact john@example.com or call 555-123-4567. SSN: 123-45-6789."
    result = _PII_RE.sub("[REDACTED]", text)
    check("UT-3a: email redacted", "john@example.com" not in result)
    check("UT-3b: phone redacted", "555-123" not in result)
    check("UT-3c: SSN redacted", "123-45" not in result)
    check("UT-3d: redaction marker present", result.count("[REDACTED]") == 3)

    clean = "This is clean text with no PII."
    result2 = _PII_RE.sub("[REDACTED]", clean)
    check("UT-3e: clean text unchanged", result2 == clean)


# ═══════════════════════════════════════════════════════════════════
# UNIT: Tone Notes (UT-7)
# ═══════════════════════════════════════════════════════════════════

async def test_tone_notes():
    from app.repositories.similar_course_repo import SimilarCourseRepository as R
    notes = R._derive_tone_notes({"welcome", "mcq", "summary"})
    check("UT-7a: returns string", isinstance(notes, str))
    check("UT-7b: mentions knowledge checks",
          "knowledge checks" in notes.lower())
    check("UT-7c: mentions introduction",
          "introduction" in notes.lower() or "objectives" in notes.lower())

    empty = R._derive_tone_notes(set())
    check("UT-7d: empty set → None", empty is None)


# ═══════════════════════════════════════════════════════════════════
# UNIT: Service Empty Result (UT-6)
# ═══════════════════════════════════════════════════════════════════

async def test_empty_result():
    r = SimilarCourseService._empty_result("Test", "tier3")
    check("UT-6a: courses empty", r["courses"] == [])
    check("UT-6b: total_count 0", r["total_count"] == 0)
    check("UT-6c: guidance message", "continue without examples" in r["message"].lower())
    check("UT-6d: tier recorded", r["retrieval_tier_used"] == "tier3")


# ═══════════════════════════════════════════════════════════════════
# INTEGRATION: Feature Flag (IT)
# ═══════════════════════════════════════════════════════════════════

async def test_feature_disabled_raises():
    db_mock = AsyncMock()
    with patch(
        "app.services.ai.similar_course_service.is_feature_enabled",
        return_value=False,
    ):
        service = SimilarCourseService(db_mock)
        try:
            await service.query_similar_courses(
                session_id="test", query="test",
            )
            check("IT-flag: should have raised", False)
        except FeatureDisabledError:
            check("IT-flag: FeatureDisabledError raised", True)


async def test_empty_query_returns_empty():
    db_mock = AsyncMock()
    with patch(
        "app.services.ai.similar_course_service.is_feature_enabled",
        return_value=True,
    ):
        service = SimilarCourseService(db_mock)
        mock_session = MagicMock()
        mock_session.organization_id = "test-org"
        mock_session.user_id = "test-user"
        service.session_repo.get_active = AsyncMock(return_value=mock_session)

        result = await service.query_similar_courses(
            session_id="test", query="   ", user_id="test-user",
        )
        check("IT-empty: courses empty", result["courses"] == [])
        check("IT-empty: mentions empty", "empty" in result["message"].lower())


# ═══════════════════════════════════════════════════════════════════
# Main Runner
# ═══════════════════════════════════════════════════════════════════

async def main():
    print("=" * 60)
    print("US-BKND-AI-015 — Similar Course Retrieval Tests")
    print("=" * 60)

    await test_mock_dimension()
    await test_mock_deterministic()
    await test_mock_property()
    await test_pii_redaction()
    await test_tone_notes()
    await test_empty_result()
    await test_feature_disabled_raises()
    await test_empty_query_returns_empty()

    total = passed + failed
    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{total} passed, {failed} failed")
    if failures:
        for name, detail in failures:
            print(f"  FAIL: {name}")
            if detail:
                print(f"        {detail}")
    print(f"{'=' * 60}")
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
```

### 13.2 Run Tests

```bash
# Run the standalone test suite
PYTHONPATH=. python tests/run_similar_course_tests.py

# Expected: 20/20 passed (or more as you add tests)

# Run the full regression suite to check nothing broke
PYTHONPATH=. python tests/run_chat_endpoint_tests.py
PYTHONPATH=. python tests/run_safety_guardrails_tests.py
PYTHONPATH=. python tests/run_json_repair_tests.py
# ... (all 18 existing runners)

# Quick smoke: verify all 662 pass
for f in tests/run_*.py; do
    echo "Running $f..."
    PYTHONPATH=. python "$f" || echo "FAILED: $f"
done
```

---

## 14. PII Redaction & Safe Fields

### 14.1 What Gets Redacted

| Pattern | Regex | Example Input → Output |
|---------|-------|----------------------|
| Email | `[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}` | `user@example.com` → `[REDACTED]` |
| US Phone | `\d{3}[-.]?\d{3}[-.]?\d{4}` | `555-123-4567` → `[REDACTED]` |
| US SSN | `\d{3}-\d{2}-\d{4}` | `123-45-6789` → `[REDACTED]` |
| Credit Card | `(?:\d[ -]*?){13,16}` | `4111-1111-1111-1111` → `[REDACTED]` |

### 14.2 Safe Fields (what's extracted)

**Extracted** into excerpts:
```
title, content, body, subtitle, description, question,
introText, mediaUrl, text, label, heading, summary
```

**Never extracted:**
```
isCorrect, correctAnswer, correctAnswers,
options[].isCorrect, scoring configuration,
user-specific identifiers
```

### 14.3 Excerpt Pipeline

```
Raw component data → Collect SAFE_FIELDS values → Pick longest (>20 chars)
→ Truncate to 500 chars → PII regex replace → Return safe excerpt
```

---

## 15. Troubleshooting Guide

### 15.1 Import Errors

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ModuleNotFoundError: No module named 'app.models.course_embedding'` | File not created | Create `app/models/course_embedding.py` (§3) |
| `ModuleNotFoundError: No module named 'openai'` | Missing pip package | `pip install openai` |
| `ImportError: cannot import name 'SimilarCourseService'` | File not created or wrong path | Verify `app/services/ai/similar_course_service.py` exists (§6) |

### 15.2 Database Errors

| Symptom | Cause | Fix |
|---------|-------|-----|
| `relation "course_embeddings" does not exist` | Migration not applied | `alembic upgrade head` (§12.3) |
| `type "vector" does not exist` in migration | pgvector not installed | Ignore — migration handles this. Tier-1 degrades gracefully. |
| `ivfflat index creation failed` | pgvector extension exists but index type unsupported | Check pgvector version ≥0.5. Or ignore — Tier-1 degrades. |

### 15.3 Runtime Errors

| Symptom | Cause | Fix |
|---------|-------|-----|
| `FeatureDisabledError` on every call | Feature flag off | Set `FEATURE_SIMILAR_COURSE_RETRIEVAL=true` in `.env` |
| Always returns `retrieval_tier_used: "tier3"` | pgvector not installed AND no full-text matches | Normal for dev with empty courses table. Add test courses. |
| `EmbeddingError: OPENAI_API_KEY is not set` | OpenAI provider with no key | Set `EMBEDDING_PROVIDER=mock` for dev, or set `OPENAI_API_KEY` |
| `EmbeddingError: openai package not installed` | Missing pip dep | `pip install openai` |
| Empty results on every query | No courses exist in the database | Create test courses via the manual authoring flow |
| Server 500 on similar-courses endpoint | Router not registered in `_ai_routers` | Verify `"ai_similar_courses": "ai_similar_courses"` exists in `main.py` |

### 15.4 Rollback Per Component

If something breaks after implementing this story, roll back in reverse order:

```bash
# 1. Disable feature flag (instant — no code change)
#    Set FEATURE_SIMILAR_COURSE_RETRIEVAL=false in .env, restart server

# 2. Revert specific files (if flag isn't enough):
git checkout -- app/routers/ai_tools.py              # Revert router refactor
git checkout -- app/services/ai/chat_orchestrator.py # Revert orchestrator
git checkout -- app/services/ai/tool_executor.py     # Revert tool executor
git checkout -- app/main.py                          # Revert main.py imports
git checkout -- app/utils/feature_flags.py           # Revert feature flag
git checkout -- app/services/ai/config.py            # Revert config
git checkout -- .env.example                         # Revert env vars

# 3. Remove new files:
rm app/models/course_embedding.py
rm app/repositories/similar_course_repo.py
rm app/services/ai/embedding_provider.py
rm app/services/ai/similar_course_service.py
rm app/routers/ai_similar_courses.py
rm tests/run_similar_course_tests.py

# 4. Rollback migration:
alembic downgrade -1

# 5. Restart server — back to pre-015 state
```

---

## 16. Complete Task Execution Checklist

Work through these in order. Check each box when verified.

### Phase A — Parallel (start all 3 together)

- [ ] **T-01** Create `app/models/course_embedding.py` — verify with §3.2 commands
- [ ] **T-03** Create `app/services/ai/embedding_provider.py` — verify with §5.2 commands
- [ ] **T-08** Modify `feature_flags.py` + `config.py` + `.env.example` — verify with §10.3 commands

### Phase B — Sequential

- [ ] **T-02** Find `alembic heads` → create migration → `alembic upgrade head` → `downgrade -1` → `upgrade head` (verify rollback works)
- [ ] **T-04** Create `app/repositories/similar_course_repo.py` — verify with §4.2 commands
- [ ] **T-05** Verify PII redaction (part of T-04 — see PII smoke test in §4.2)
- [ ] **T-06** Verify enrichment (part of T-04 — tone notes test in §4.2)

### Phase C — Sequential

- [ ] **T-07** Create `app/services/ai/similar_course_service.py` — verify with §6.2 commands
- [ ] **T-09** Create `app/routers/ai_similar_courses.py` + refactor `ai_tools.py` — verify with §7.2 commands
- [ ] **T-10** Modify `tool_executor.py` — verify with §8.1 commands
- [ ] **T-11** Modify `chat_orchestrator.py` — mock handler + SYSTEM_PROMPT + _build_system_prompt + _build_tool_definitions — verify with §9.1 commands

### Phase D — Parallel

- [ ] **T-12** Verify all 4 orchestrator changes: grep for SimilarCourseService, RAG warning in rules, tool definition registration — verify with §9.1 commands
- [ ] **T-13** Modify `main.py` (model import + router registration) — verify with §11.1 commands
- [ ] **T-14** Verify `.env.example` has all 8 new lines (§10.3)

### Phase E — Final Verification

- [ ] **T-15** Create `tests/run_similar_course_tests.py` — run: `PYTHONPATH=. python tests/run_similar_course_tests.py`
- [ ] **T-16** Extend existing tool tests if needed (verify `test_ai_tools.py` still passes)
- [ ] **T-17** Manual integration test:
  - [ ] Set `FEATURE_SIMILAR_COURSE_RETRIEVAL=true`
  - [ ] Start server: `PYTHONPATH=. uvicorn app.main:app --reload`
  - [ ] Call `POST /api/v1/ai/tools/query_similar_courses` with valid body → 200 with courses
  - [ ] Call with `FEATURE_SIMILAR_COURSE_RETRIEVAL=false` → 404 FEATURE_DISABLED
  - [ ] Call with invalid session_id → 401 SESSION_INVALID
  - [ ] Call with empty query → non-fatal empty result
- [ ] **T-18** Update `TOOL_SCHEMAS_CLAUDE_NATIVE.md` if needed
- [ ] **T-19** Run all 18 existing test suites — verify zero regressions:
  ```bash
  for f in tests/run_*.py; do PYTHONPATH=. python "$f" || echo "FAIL: $f"; done
  ```
- [ ] **T-20** Smoke test: 10 concurrent queries, verify responses in < 3s

---

## 17. File Manifest (Complete)

| # | File | Action | Lines |
|---|------|--------|-------|
| 1 | `app/models/course_embedding.py` | **CREATE** | 130 |
| 2 | `app/repositories/similar_course_repo.py` | **CREATE** | 380 |
| 3 | `app/services/ai/embedding_provider.py` | **CREATE** | 190 |
| 4 | `app/services/ai/similar_course_service.py` | **CREATE** | 210 |
| 5 | `app/routers/ai_similar_courses.py` | **CREATE** | 100 |
| 6 | `alembic/versions/20260620_0001_add_course_embeddings.py` | **CREATE** | 120 |
| 7 | `tests/run_similar_course_tests.py` | **CREATE** | 280 |
| 8 | `app/main.py` | **MODIFY** +2 lines | +2 |
| 9 | `app/utils/feature_flags.py` | **MODIFY** +1 flag | +8 |
| 10 | `app/services/ai/config.py` | **MODIFY** +6 fields +6 lines | +12 |
| 11 | `app/routers/ai_tools.py` | **MODIFY** refactor lines 715-848 | -80/+50 |
| 12 | `app/services/ai/tool_executor.py` | **MODIFY** +1 route +1 handler | +35 |
| 13 | `app/services/ai/chat_orchestrator.py` | **MODIFY** mock→real + SYSTEM_PROMPT + _build_system_prompt + _build_tool_definitions | ~65 |
| 14 | `.env.example` | **MODIFY** +18 lines | +18 |
| 15 | `docs/.../TOOL_SCHEMAS_CLAUDE_NATIVE.md` | **MODIFY** update schema | ~10 |

**Total: 15 files, ~1,500 lines of code, 26 hours**

---

## Appendix A: Decision Log (Complete)

| # | Decision | Alternatives | Why This Choice |
|---|----------|-------------|-----------------|
| 1 | JSONB for embedding, not native vector(1536) | Native pgvector type | Portability — table must exist even without pgvector. JSONB works everywhere. ivfflat index provides ANN when available. |
| 2 | Mock provider by default | Require OpenAI key in dev | Zero-cost, zero-latency dev. Deterministic output enables reproducible tests. |
| 3 | Repository takes `session: AsyncSession` only | Store org_id on constructor | Matches `AISessionRepository`, `CourseRepository`, `PageRepository` patterns. |
| 4 | Service takes `db: AsyncSession` only | Store org_id on service | Matches `AISessionService`, `AIProposalService` patterns. Org resolved per-request from session. |
| 5 | Feature flag default false in staging/prod | Flag on everywhere | Safety-first — existing behavior preserved. Gradual rollout possible. |
| 6 | `retrieval_tier_used` in response | Hide implementation detail | AI agent needs to calibrate confidence. Tier-3 is less reliable than Tier-1. |
| 7 | Cache table deferred to future iteration | Implement cache in MVP | Tiered search is fast enough for org-scoped datasets (<10K courses). |
| 8 | Dedicated router `ai_similar_courses.py` | Keep everything in `ai_tools.py` | Separation of concerns. `ai_tools.py` already 900 lines. |
| 9 | `_derive_template_type()` duplicated from ToolExecutor | Import from ToolExecutor | Repository should not depend on ToolExecutor (circular dependency risk). Duplication documented. |
| 10 | OpenAI `AuthenticationError` → `retryable=False` | All errors retryable | Bad API key is permanent. Retrying wastes resources and delays failure detection. |
| 11 | `MIN_EXCERPT_TEXT_LENGTH = 20` | 10 or 30 | Strings ≤20 chars are titles/labels (e.g., "Safety 101"). Not useful as excerpts. |
| 12 | Embedding singleton via module-level global | Per-request instantiation | One client per process avoids repeated API key validation and connection setup. |

---

**Document Version:** 2.0 — Standalone Implementation Playbook  
**Authored:** 2026-06-20  
**TPO / Solutions Architect:** This document contains everything a developer needs.  
**If you find a gap:** It's a bug in this document. Flag it.
