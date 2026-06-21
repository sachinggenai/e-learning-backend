# US-PEND-020: Embedding Population Background Worker — FULLY ENRICHED

| Field | Value |
|-------|-------|
| **Type** | 🆕 New Task (Feature) |
| **Priority** | 🟡 HIGH |
| **Batch** | 6 — Feature Development |
| **Depends On** | US-PEND-017 (pgvector + Docker) |
| **Estimated Effort** | 2-3 days |
| **Target Files** | New: `app/workers/embedding_worker.py`. Modify: `app/main.py` |

---

## User Story

**As a** course author searching for similar courses,
**I want** the course embedding database populated with vectors for all existing courses,
**So that** Tier-1 semantic search returns relevant results instead of always falling through to Tier-2.

---

## Current State (Code Verified 2026-06-21)

- `upsert_embedding()` method exists in `similar_course_repo.py` but is **never called**
- `course_embeddings` table has **0 rows**
- `search_vector()` returns `[]` every time → Tier-1 always falls through
- `similar_course_repo.py:1018-1023`: Comment: "NOT called anywhere in the MVP code path"
- `EmbeddingProvider` at `embedding_provider.py:23` — abstract ABC with `embed(text) -> list[float]`
- `OpenAIBackend` at `embedding_provider.py:49` — uses `text-embedding-ada-002` (1536-dim)
- `MockEmbeddingProvider` at `embedding_provider.py:122` — deterministic mock for testing
- `get_embedding_provider()` at `embedding_provider.py:153` — singleton factory, reads `EMBEDDING_PROVIDER` env var
- **No background worker infrastructure exists** — must be built from scratch

---

## 🔧 Open-Source Tooling Selection

| Tool | Version | Purpose | Why Selected |
|------|---------|---------|-------------|
| **sentence-transformers** | 3.x | Local embedding model (no API calls) | Runs entirely locally; no API costs; 768-dim vectors; supports 50+ languages; MIT license |
| **all-MiniLM-L6-v2** | v2 | Default embedding model | 384-dim; 80MB download; ~1400 sentences/sec on CPU; widely benchmarked |
| **asyncio** | Python 3.12 stdlib | Background task scheduling | Zero dependencies; already used by workflow orchestrator |

**Why sentence-transformers over alternatives:**
- **sentence-transformers** vs OpenAI API: Zero API costs, works offline, no rate limits. For a background worker processing hundreds of courses, API costs would be significant.
- **all-MiniLM-L6-v2** vs `text-embedding-ada-002`: 384-dim vs 1536-dim means smaller index, faster search. Quality is 80-85% of ada-002 for semantic search at 1/100th the cost.
- **sentence-transformers** vs spaCy: sentence-transformers produces dense semantic vectors; spaCy produces sparse linguistic vectors. Semantic search needs dense vectors.

### Add to `requirements.txt`:
```
sentence-transformers>=3.0.0
```

---

## Enriched Implementation

### File: `app/workers/embedding_worker.py`

```python
"""Background worker for populating course embeddings — US-PEND-020.

Runs as an asyncio background task. Periodically scans for courses
missing embeddings and generates vectors via sentence-transformers.

Architecture:
    EmbeddingWorker (asyncio task)
      → SELECT courses WHERE updated_at > last_embedding_at
      → For each course: sentence_transformer.encode(course_text)
      → similar_course_repo.upsert_embedding(course_id, vector)
      → UPDATE course SET last_embedding_at = NOW()
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class EmbeddingWorker:
    """Background worker that populates course_embeddings table.

    Usage in app/main.py lifespan():
        worker = EmbeddingWorker(poll_interval_seconds=300)
        await worker.start()
        # ... app runs ...
        await worker.stop()
    """

    def __init__(
        self,
        poll_interval_seconds: float = 300.0,  # 5 min default
        batch_size: int = 10,
    ):
        self.poll_interval = poll_interval_seconds
        self.batch_size = batch_size
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._model = None  # Lazy-loaded sentence-transformer model

    # ── Public API ──────────────────────────────────────

    async def start(self) -> None:
        """Start the worker background task."""
        if not self._is_pgvector_available():
            logger.info(
                "EmbeddingWorker: pgvector not available — worker disabled"
            )
            return

        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "EmbeddingWorker started (interval=%ds, batch=%d)",
            self.poll_interval, self.batch_size,
        )

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("EmbeddingWorker stopped")

    # ── Main Loop ───────────────────────────────────────

    async def _loop(self) -> None:
        """Main poll loop: process pending courses, then sleep."""
        # Process immediately on startup
        await self._process_batch()

        while self._running:
            try:
                await asyncio.sleep(self.poll_interval)
                await self._process_batch()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("EmbeddingWorker loop error — will retry")

    async def _process_batch(self) -> int:
        """Process one batch of courses needing embeddings."""
        from app.db.config import SessionLocal
        from app.repositories.similar_course_repo import SimilarCourseRepository
        from app.repositories.course_repo import CourseRepository

        processed = 0
        try:
            async with SessionLocal() as session:
                course_repo = CourseRepository(session)
                embedding_repo = SimilarCourseRepository(session)

                # Find courses without embeddings
                pending = await embedding_repo.find_courses_without_embeddings(
                    limit=self.batch_size
                )
                if not pending:
                    return 0

                model = self._get_model()
                for course in pending:
                    try:
                        course_text = self._build_course_text(course)
                        vector = model.encode(course_text).tolist()
                        await embedding_repo.upsert_embedding(
                            course_id=course.course_id,
                            embedding=vector,
                            model_name=self._model_name(),
                        )
                        processed += 1
                    except Exception as exc:
                        logger.error(
                            "Failed to embed course %s: %s",
                            getattr(course, 'course_id', 'unknown'), exc,
                        )

                await session.commit()

            if processed:
                logger.info(
                    "EmbeddingWorker: processed %d courses", processed
                )
        except Exception:
            logger.exception("EmbeddingWorker batch failed")

        return processed

    # ── Helpers ─────────────────────────────────────────

    def _get_model(self):
        """Lazy-load the sentence-transformer model (cached after first load)."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            model_name = os.getenv(
                "EMBEDDING_MODEL", "all-MiniLM-L6-v2"
            )
            logger.info("Loading embedding model: %s", model_name)
            self._model = SentenceTransformer(model_name)
        return self._model

    def _model_name(self) -> str:
        return os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

    def _build_course_text(self, course) -> str:
        """Build a text representation of a course for embedding."""
        parts = [
            getattr(course, 'title', ''),
            getattr(course, 'description', ''),
        ]
        # Include page titles if available
        pages = getattr(course, 'pages', None)
        if pages:
            for page in pages:
                parts.append(getattr(page, 'title', ''))
        return ' '.join(filter(None, parts))

    @staticmethod
    def _is_pgvector_available() -> bool:
        """Check if pgvector extension is installed."""
        try:
            from app.repositories.similar_course_repo import _pgvector_available
            return _pgvector_available()
        except Exception:
            return False
```

### File: Add `find_courses_without_embeddings()` to `SimilarCourseRepository`

In `app/repositories/similar_course_repo.py`:

```python
async def find_courses_without_embeddings(
    self, limit: int = 10
) -> list:
    """Find courses that don't have an embedding yet."""
    from app.models.course_embedding import CourseEmbedding
    from sqlalchemy import select

    # Get all course IDs that already have embeddings
    embedded_ids = select(CourseEmbedding.course_id)

    # Find courses NOT in that set
    from app.models.persisted_course import CourseRecord
    stmt = (
        select(CourseRecord)
        .where(CourseRecord.course_id.not_in(embedded_ids))
        .limit(limit)
    )
    result = await self.session.execute(stmt)
    return list(result.scalars().all())
```

### Integration in `app/main.py`

In the `lifespan()` function, add after the workflow orchestrator startup:

```python
# ── Embedding Worker (US-PEND-020) ──────────────────
embedding_worker = EmbeddingWorker(
    poll_interval_seconds=float(
        os.getenv("EMBEDDING_WORKER_INTERVAL", "300")
    ),
    batch_size=int(os.getenv("EMBEDDING_BATCH_SIZE", "10")),
)
app.state.embedding_worker = embedding_worker
await embedding_worker.start()
```

And in shutdown:
```python
if hasattr(app.state, 'embedding_worker'):
    await app.state.embedding_worker.stop()
```

---

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | Worker starts with application | Check logs for "EmbeddingWorker started" |
| AC-2 | All existing courses get embeddings | `psql -c "SELECT COUNT(*) FROM course_embeddings;"` > 0 |
| AC-3 | New courses get embeddings on next cycle | Create course → wait 5 min → check embeddings table |
| AC-4 | `search_vector()` returns results | `PYTHONPATH=. python -c "from app.repositories.similar_course_repo import search_vector; ..."` |
| AC-5 | Worker handles pgvector absence gracefully | Without pgvector: worker logs "disabled" and doesn't crash |
| AC-6 | Sentence-transformer model loads once (lazy) | Check logs for single "Loading embedding model" message |

---

## Validation

```bash
# 1. Install sentence-transformers
pip install sentence-transformers>=3.0.0

# 2. Verify import
PYTHONPATH=. python -c "from app.workers.embedding_worker import EmbeddingWorker; print('OK')"

# 3. Set env (mock for fast testing)
export EMBEDDING_PROVIDER=mock

# 4. Start app, wait for worker cycle
# Check logs for "EmbeddingWorker: processed N courses"

# 5. Verify embeddings populated
psql -c "SELECT course_id, model_name FROM course_embeddings LIMIT 5;"

# 6. Test search
PYTHONPATH=. python -c "
from app.repositories.similar_course_repo import search_vector
import asyncio
# This will work once embeddings exist
print('Search ready')
"
```
