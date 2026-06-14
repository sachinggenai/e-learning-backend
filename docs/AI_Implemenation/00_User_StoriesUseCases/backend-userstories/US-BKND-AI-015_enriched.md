## US-BKND-AI-015 -- Retrieve Similar Courses for Examples and Tone

**Title:** As an AI Agent, I want similar course examples and tone guidance, so that generated content can match proven pedagogy without using RAG as an authority for contracts.

**Source flow:** Flow 7 -- Similar Course Retrieval Flow (Flow Chart ref: `useCasesFlowCharts.md`)

**Priority:** SHOULD

**Dependencies:** US-BKND-AI-006 (AI Session), US-BKND-AI-005 (Tool Schema Registry)

**Story Points:** 8

---

### 1. Functional Specification

#### 1.1 Overview

The AI Agent (within an active AI authoring session) can invoke a `query_similar_courses` tool that returns pedagogically similar course examples, snippet excerpts, template patterns, tone notes, and relevance scores. The system searches across **org-scoped courses** using a three-tier retrieval strategy: vector similarity (when pgvector is available), PostgreSQL full-text search (fallback), and keyword/pattern search (last resort). Results are used **only** for style, tone, and structural guidance -- never as the source of API contracts, validation rules, or schema definitions.

#### 1.2 Actor / Trigger

- **Actor:** AI Agent (LLM) acting on behalf of the Author within an AI session
- **Trigger:** Agent decides it needs reference material for tone, structure, or pedagogical patterns before generating or editing course content

#### 1.3 Functional Requirements

**FR-1. Tool Contract**
The tool `query_similar_courses` is registered in the AI tool registry (`app/services/ai/tool_registry.py`) with the following schema:

```json
{
  "name": "query_similar_courses",
  "description": "Search for similar courses within your organization to use as examples for tone, structure, and pedagogical patterns. Results are NOT authoritative for API contracts, validation rules, or schema definitions.",
  "input_schema": {
    "type": "object",
    "properties": {
      "session_id": {
        "type": "string",
        "description": "Active AI session ID"
      },
      "query": {
        "type": "string",
        "description": "Natural language query describing the desired course style, topic, or structure (e.g., 'interactive safety training with quizzes', 'onboarding course for new hires')"
      },
      "filters": {
        "type": "object",
        "properties": {
          "template_types": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional: filter courses that use specific template types (e.g., ['mcq', 'content-video', 'accordion'])"
          },
          "min_pages": {
            "type": "integer",
            "description": "Optional: minimum number of pages in matching courses"
          },
          "max_pages": {
            "type": "integer",
            "description": "Optional: maximum number of pages in matching courses"
          },
          "language": {
            "type": "string",
            "description": "Optional: ISO language code filter (e.g., 'en', 'es')"
          }
        },
        "additionalProperties": false
      },
      "max_results": {
        "type": "integer",
        "default": 5,
        "minimum": 1,
        "maximum": 20,
        "description": "Maximum number of similar courses to return"
      }
    },
    "required": ["session_id", "query"]
  }
}
```

**FR-2. Retrieval Strategy (tiered)**

| Tier | Strategy | Condition | Mechanism |
|---|---|---|---|
| 1 (best) | Vector similarity via pgvector | `ENABLE_PGVECTOR=true` env var + `vector` extension in PostgreSQL | Generate embedding from query, cosine-similarity search against `course_embeddings` table |
| 2 (fallback) | PostgreSQL full-text search | Always available | `ts_vector` on `courses.title`, `courses.description`, `templates.title`, `templates.json_data` (extracted text) |
| 3 (last resort) | Keyword/ILIKE pattern matching | Always available | `ILIKE '%query_term%'` across title, description, and template data text fields |

Selection is automatic: if Tier 1 is configured, use it; else if Tier 2 returns results, use it; else fall through to Tier 3.

**FR-3. Result Shape**

Each result contains:
- `courseId` (string) -- opaque identifier, not the internal PK
- `title` (string) -- course title
- `relevance_score` (float, 0.0-1.0)
- `match_summary` (string) -- 1-2 sentence explanation of why this course matched
- `page_count` (int)
- `template_breakdown` (dict: `{template_type: count}`) -- e.g., `{"content-text": 3, "mcq": 2, "welcome": 1}`
- `sample_excerpts` (array of objects with `{template_type, title, text_snippet}`) -- up to 3 excerpts per course, each truncated to 500 chars
- `tone_notes` (optional string) -- extracted tone/style observations (e.g., "uses conversational language, short paragraphs, frequent knowledge checks")
- `language` (string)
- `created_at` (ISO datetime)

**FR-4. Empty Results are Non-Fatal**

When no similar courses are found, the tool returns:
```json
{
  "courses": [],
  "total_count": 0,
  "message": "No similar courses found. Generation can continue without examples. Consider providing explicit tone and structure guidance in your prompt.",
  "retrieval_tier_used": "tier3"
}
```
The AI Agent must be instructed (in the system prompt) that empty results are acceptable and should not block generation.

**FR-5. Tenant Isolation**

All queries are automatically scoped to the requesting user's organization. The `organization_id` is resolved from the AI session record (`ai_sessions.organization_id`). Cross-tenant results must never be returned regardless of query similarity.

**FR-6. Data Privacy and Redaction**

- Excerpts are stripped of PII (names, emails, phone numbers) via regex patterns before inclusion
- Full course `json_data` is never returned -- only bounded text snippets (max 500 chars each)
- Excerpts are extracted only from `templates.json_data` fields identified as "safe" in the field schema (text/html content fields; never `isCorrect`, `correctAnswer`, `correctAnswers`, `options[].isCorrect`, scoring config, or user-specific fields)

**FR-7. Source-of-Truth Warning in System Prompt**

The AI system prompt must include:
> "The `query_similar_courses` tool returns example courses for tone and structural reference only. Do NOT derive API contracts, validation rules, template schemas, or configuration values from these results. Always rely on the tool definitions, template contracts, and schemas provided in your system prompt for authoritative specifications."

---

### 2. Technical Specification

#### 2.1 New Files

| File | Purpose |
|---|---|
| `app/models/course_embedding.py` | SQLAlchemy model for `course_embeddings` table |
| `app/repositories/similar_course_repo.py` | Repository with Tier-1/Tier-2/Tier-3 retrieval logic |
| `app/services/ai/similar_course_service.py` | Business logic: embedding generation, excerpt extraction, PII redaction, response shaping |
| `app/services/ai/embedding_provider.py` | Abstract embedding provider + OpenAI/text-embedding-ada-002 implementation |
| `app/routers/ai_similar_courses.py` | Optional REST endpoint for non-tool access (admin/UI) |
| `app/services/ai/__init__.py` | Package init (may already exist; update if so) |
| `alembic/versions/20260615_0001_add_course_embeddings.py` | Migration for new table and indexes |

#### 2.2 Modified Files

| File | Change |
|---|---|
| `app/services/ai/tool_registry.py` | Register `query_similar_courses` tool definition |
| `app/services/ai/chat_orchestrator.py` | Inject `similar_course_service` dependency, handle tool call routing |
| `app/main.py` | Import and register `app.models.course_embedding` for startup table creation |
| `alembic/env.py` | Import `app.models.course_embedding` for autogenerate detection |
| `app/utils/feature_flags.py` | Add `similar_course_retrieval` feature flag |
| `app/services/seed_template_types.py` | (no change needed) |

#### 2.3 Database DDL

**Table: `course_embeddings`**

```sql
CREATE TABLE IF NOT EXISTS course_embeddings (
    id SERIAL PRIMARY KEY,
    course_record_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    organization_id VARCHAR(64) NOT NULL DEFAULT 'default',  -- tenant scope
    embedding vector(1536),                                   -- pgvector type, nullable when pgvector unavailable
    content_hash VARCHAR(64) NOT NULL,                        -- SHA-256 of concatenated title+description+template_data at embedding time
    chunk_count INTEGER NOT NULL DEFAULT 1,                   -- number of text chunks embedded
    embedding_model VARCHAR(100) NOT NULL DEFAULT 'text-embedding-ada-002',
    is_stale BOOLEAN NOT NULL DEFAULT FALSE,                  -- set TRUE when course content changes, triggers re-embed
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS ix_course_embeddings_course_record_id 
    ON course_embeddings (course_record_id);
CREATE INDEX IF NOT EXISTS ix_course_embeddings_org_stale 
    ON course_embeddings (organization_id, is_stale) 
    WHERE is_stale = FALSE;

-- pgvector index (only created if extension exists)
-- CREATE INDEX IF NOT EXISTS ix_course_embeddings_vector 
--     ON course_embeddings 
--     USING ivfflat (embedding vector_cosine_ops) 
--     WITH (lists = 100);
```

Note: The pgvector index is created by the migration only when the `vector` extension is available. The migration checks `SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')` first.

**Table: `course_similarity_cache`** (optional performance optimization for repeated queries)

```sql
CREATE TABLE IF NOT EXISTS course_similarity_cache (
    id SERIAL PRIMARY KEY,
    source_course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    similar_course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    similarity_score FLOAT NOT NULL,
    cache_tier VARCHAR(8) NOT NULL DEFAULT 'tier1',  -- 'tier1' | 'tier2'
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    UNIQUE(source_course_id, similar_course_id)
);
```

#### 2.4 SQLAlchemy Model (`app/models/course_embedding.py`)

```python
"""ORM model for course embedding vectors and pgvector similarity search."""
from __future__ import annotations
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, DateTime, Integer, Boolean, Float, ForeignKey, Text, Index

from app.models.base import Base


class CourseEmbeddingRecord(Base):
    __tablename__ = "course_embeddings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    course_record_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[str] = mapped_column(String(64), default="default")
    embedding: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True
    )  # Stored as list[float] in JSON when pgvector absent; native vector type when available
    content_hash: Mapped[str] = mapped_column(String(64))
    chunk_count: Mapped[int] = mapped_column(Integer, default=1)
    embedding_model: Mapped[str] = mapped_column(String(100), default="text-embedding-ada-002")
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("ix_course_embeddings_org_stale", "organization_id", "is_stale",
              postgresql_where=~is_stale),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "courseRecordId": self.course_record_id,
            "organizationId": self.organization_id,
            "contentHash": self.content_hash,
            "chunkCount": self.chunk_count,
            "embeddingModel": self.embedding_model,
            "isStale": self.is_stale,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
        }
```

#### 2.5 Repository (`app/repositories/similar_course_repo.py`)

```python
"""Repository for similar course retrieval across three tiers."""
from __future__ import annotations
import re
import logging
from typing import Optional, Sequence
from datetime import datetime

from sqlalchemy import select, text, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.persisted_course import CourseRecord, TemplateRecord
from app.models.course_embedding import CourseEmbeddingRecord

logger = logging.getLogger(__name__)

# List of fields in json_data/template data that are SAFE for excerpt extraction
# (excludes isCorrect, correctAnswer, correctAnswers, scoring config)
SAFE_EXCERPT_FIELDS = {"title", "content", "body", "subtitle", "description",
                       "question", "introText", "mediaUrl", "text", "label"}

MAX_EXCERPT_LENGTH = 500
MAX_EXCERPTS_PER_COURSE = 3

_PII_PATTERNS = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b|"   # email
    r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b|"                           # phone
    r"\b\d{3}-\d{2}-\d{4}\b"                                     # SSN
)


class SimilarCourseRepository:
    """Retrieves similar courses using tiered strategy."""

    def __init__(self, session: AsyncSession, organization_id: str = "default"):
        self.session = session
        self.organization_id = organization_id

    # ── Tier 1: pgvector similarity ──────────────────────────────────────

    async def search_vector(
        self, query_embedding: list[float], max_results: int = 5
    ) -> list[dict]:
        """Search using pgvector cosine similarity. Returns empty list if
        pgvector extension is unavailable or the course_embeddings table
        has no vector data."""
        try:
            # Check if vector extension is available
            ext_check = await self.session.execute(
                text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')")
            )
            if not ext_check.scalar():
                logger.info("pgvector extension not available; skipping vector search")
                return []

            # Build cosine similarity query
            vector_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"
            sql = text(f"""
                SELECT 
                    ce.course_record_id,
                    c.course_id,
                    c.title,
                    c.description,
                    1 - (ce.embedding <=> '{vector_literal}'::vector) AS similarity
                FROM course_embeddings ce
                JOIN courses c ON c.id = ce.course_record_id
                WHERE ce.organization_id = :org_id
                  AND ce.is_stale = FALSE
                  AND ce.embedding IS NOT NULL
                ORDER BY ce.embedding <=> '{vector_literal}'::vector
                LIMIT :limit
            """)
            rows = await self.session.execute(
                sql, {"org_id": self.organization_id, "limit": max_results}
            )
            results = []
            for row in rows:
                results.append({
                    "course_record_id": row[0],
                    "course_id": row[1],
                    "title": row[2],
                    "description": row[3],
                    "score": float(row[4]),
                })
            return results

        except Exception as exc:
            logger.warning("pgvector search failed, falling back: %s", exc)
            return []

    # ── Tier 2: PostgreSQL full-text search ──────────────────────────────

    async def search_fulltext(
        self, query: str, max_results: int = 5
    ) -> list[dict]:
        """Search using PostgreSQL ts_query across courses and templates."""
        # Sanitize query for ts_query
        sanitized = re.sub(r"[^\w\s]", " ", query).strip()
        if not sanitized:
            return []

        # Build tsquery: split into words and join with &
        terms = [t for t in sanitized.split() if len(t) > 1]
        if not terms:
            return []
        tsq = " & ".join(terms) + ":*"

        sql = text(f"""
            SELECT DISTINCT ON (c.id)
                c.id AS course_record_id,
                c.course_id,
                c.title,
                c.description,
                ts_rank(
                    setweight(to_tsvector('english', coalesce(c.title, '')), 'A') ||
                    setweight(to_tsvector('english', coalesce(c.description, '')), 'B') ||
                    setweight(to_tsvector('english', coalesce(t.title, '')), 'C'),
                    to_tsquery('english', :tsq)
                ) AS rank
            FROM courses c
            LEFT JOIN templates t ON t.course_id = c.id
            WHERE
                (to_tsvector('english', coalesce(c.title, '')) ||
                 to_tsvector('english', coalesce(c.description, '')) ||
                 to_tsvector('english', coalesce(t.title, '')))
                @@ to_tsquery('english', :tsq)
            ORDER BY c.id, rank DESC
            LIMIT :limit
        """)
        try:
            rows = await self.session.execute(
                sql, {"tsq": tsq, "limit": max_results}
            )
            return [
                {
                    "course_record_id": row[0],
                    "course_id": row[1],
                    "title": row[2],
                    "description": row[3],
                    "score": min(float(row[4]) / 10.0, 1.0) if row[4] else 0.0,
                }
                for row in rows
            ]
        except Exception as exc:
            logger.warning("Full-text search failed, falling back: %s", exc)
            return []

    # ── Tier 3: Keyword / ILIKE search ───────────────────────────────────

    async def search_keyword(
        self, query: str, max_results: int = 5
    ) -> list[dict]:
        """Simple ILIKE-based keyword search across course title/description."""
        terms = [t for t in re.sub(r"[^\w\s]", " ", query).split() if len(t) > 1]
        if not terms:
            return []

        # Build OR conditions for each term
        conditions = []
        params: dict[str, str] = {}
        for i, term in enumerate(terms):
            param = f"term_{i}"
            params[param] = f"%{term}%"
            conditions.append(
                f"(c.title ILIKE :{param} OR coalesce(c.description, '') ILIKE :{param})"
            )

        where_clause = " OR ".join(conditions)
        sql = text(f"""
            SELECT DISTINCT
                c.id AS course_record_id,
                c.course_id,
                c.title,
                c.description,
                CAST(1.0 AS FLOAT) AS score
            FROM courses c
            WHERE ({where_clause})
            ORDER BY c.title
            LIMIT :limit
        """)
        try:
            rows = await self.session.execute(
                sql, {**params, "limit": max_results}
            )
            return [
                {
                    "course_record_id": row[0],
                    "course_id": row[1],
                    "title": row[2],
                    "description": row[3],
                    "score": 0.5,  # flat score for keyword match
                }
                for row in rows
            ]
        except Exception as exc:
            logger.error("Keyword search also failed: %s", exc)
            return []

    # ── Enrichment: build full result with excerpts ──────────────────────

    async def enrich_results(
        self, raw_results: list[dict], query: str
    ) -> list[dict]:
        """Load template data for each matched course and build final result shape."""
        enriched = []
        for row in raw_results:
            # Fetch templates for this course
            tmpl_q = select(TemplateRecord).where(
                TemplateRecord.course_id == row["course_record_id"]
            ).order_by(TemplateRecord.order_index)
            templates = (await self.session.execute(tmpl_q)).scalars().all()

            # Build template breakdown
            breakdown: dict[str, int] = {}
            excerpts: list[dict] = []
            for tmpl in templates:
                breakdown[tmpl.template_type] = breakdown.get(tmpl.template_type, 0) + 1
                # Extract safe excerpts
                if len(excerpts) < MAX_EXCERPTS_PER_COURSE:
                    snippet = self._extract_excerpt(tmpl)
                    if snippet:
                        excerpts.append({
                            "template_type": tmpl.template_type,
                            "title": tmpl.title,
                            "text_snippet": snippet,
                        })

            # Build tone notes from template types and title patterns
            tone_notes = self._derive_tone_notes(templates)

            enriched.append({
                "courseId": row["course_id"],
                "title": row["title"],
                "relevance_score": round(row["score"], 4),
                "match_summary": self._generate_match_summary(
                    row["title"], row.get("description"), query, templates
                ),
                "page_count": len(templates),
                "template_breakdown": breakdown,
                "sample_excerpts": excerpts,
                "tone_notes": tone_notes,
                "language": "en",  # TODO: read from course json_data
                "created_at": templates[0].created_at.isoformat() if templates else "",
            })
        return enriched

    def _extract_excerpt(self, tmpl: TemplateRecord) -> Optional[str]:
        """Extract a safe, PII-redacted text snippet from a template's data."""
        data = tmpl.json_data or {}
        candidates: list[str] = []
        for field_name in ("content", "body", "question", "text", "description"):
            val = data.get(field_name)
            if isinstance(val, str) and len(val.strip()) > 20:
                candidates.append(val.strip())

        # Also check nested questions array for the 'question' sub-field
        questions = data.get("questions")
        if isinstance(questions, list):
            for q in questions[:3]:
                if isinstance(q, dict):
                    qtext = q.get("question")
                    if isinstance(qtext, str) and len(qtext.strip()) > 20:
                        candidates.append(qtext.strip())

        if not candidates:
            return None

        # Pick the longest candidate as most informative
        best = max(candidates, key=len)
        # Truncate
        if len(best) > MAX_EXCERPT_LENGTH:
            best = best[:MAX_EXCERPT_LENGTH] + "..."
        # Redact PII
        best = _PII_PATTERNS.sub("[REDACTED]", best)
        return best

    def _derive_tone_notes(self, templates: list[TemplateRecord]) -> Optional[str]:
        """Heuristic tone/style notes based on template types and titles."""
        types = {t.template_type for t in templates}
        notes: list[str] = []

        if "mcq" in types:
            notes.append("uses knowledge checks and assessment questions")
        if "welcome" in types:
            notes.append("includes structured introduction and objectives")
        if "content-video" in types or "video" in types:
            notes.append("incorporates video-based learning segments")
        if "accordion" in types:
            notes.append("organizes content in expandable sections for depth")
        if "tabs" in types:
            notes.append("uses tabbed navigation for multi-topic pages")
        if "summary" in types:
            notes.append("includes recap and summary sections")

        if not notes:
            return None
        return "Course " + "; ".join(notes) + "."

    def _generate_match_summary(
        self, title: str, description: Optional[str], query: str, templates: list
    ) -> str:
        """Generate a human-readable summary of why this course matched."""
        parts = [f"Course titled '{title}'"]
        if description:
            parts.append(description[:200])
        parts.append(f"with {len(templates)} page(s)")
        return " ".join(parts)
```

#### 2.6 Service (`app/services/ai/similar_course_service.py`)

```python
"""Business logic for similar course retrieval."""
from __future__ import annotations
import hashlib
import json
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.similar_course_repo import SimilarCourseRepository
from app.services.ai.embedding_provider import EmbeddingProvider, get_embedding_provider

logger = logging.getLogger(__name__)


class SimilarCourseService:
    """Orchestrates similar course retrieval with tiered fallback."""

    def __init__(
        self,
        session: AsyncSession,
        organization_id: str = "default",
        embedding_provider: Optional[EmbeddingProvider] = None,
    ):
        self.session = session
        self.organization_id = organization_id
        self.embedding_provider = embedding_provider or get_embedding_provider()
        self.repo = SimilarCourseRepository(session, organization_id)

    async def query_similar_courses(
        self,
        query: str,
        max_results: int = 5,
        filters: Optional[dict] = None,
    ) -> dict:
        """Execute tiered retrieval and return shaped results."""
        # Normalize query
        query = query.strip()
        if not query:
            return self._empty_result("Query is empty.")

        # Tier 1: vector search
        tier_used = "tier1"
        try:
            embedding = await self.embedding_provider.embed(query)
            raw = await self.repo.search_vector(embedding, max_results)
        except Exception as exc:
            logger.info("Vector search unavailable: %s", exc)
            raw = []
            tier_used = "tier2"

        # Tier 2 fallback: full-text search
        if not raw:
            tier_used = "tier2"
            try:
                raw = await self.repo.search_fulltext(query, max_results)
            except Exception as exc:
                logger.warning("Full-text search failed: %s", exc)
                raw = []

        # Tier 3 fallback: keyword
        if not raw:
            tier_used = "tier3"
            try:
                raw = await self.repo.search_keyword(query, max_results)
            except Exception as exc:
                logger.error("All search tiers failed: %s", exc)
                return self._empty_result("Search services unavailable.")

        # Apply additional filters (in-memory post-filter)
        if filters:
            raw = self._apply_filters(raw, filters)

        # Enrich with template excerpts and tone notes
        enriched = await self.repo.enrich_results(raw, query)

        # Sort by relevance descending
        enriched.sort(key=lambda r: r["relevance_score"], reverse=True)

        return {
            "courses": enriched[:max_results],
            "total_count": len(enriched[:max_results]),
            "message": f"Found {min(len(enriched), max_results)} similar course(s).",
            "retrieval_tier_used": tier_used,
        }

    def _apply_filters(
        self, results: list[dict], filters: dict
    ) -> list[dict]:
        """Apply post-query filters."""
        # Filter by language, pagination etc. would go here.
        # Template-type filtering requires loading templates, done in enrichment.
        return results

    def _empty_result(self, message: str) -> dict:
        return {
            "courses": [],
            "total_count": 0,
            "message": message + (
                " Generation can continue without examples. "
                "Consider providing explicit tone and structure guidance in your prompt."
            ),
            "retrieval_tier_used": "none",
        }
```

#### 2.7 Embedding Provider (`app/services/ai/embedding_provider.py`)

```python
"""Abstract embedding provider with OpenAI implementation."""
from __future__ import annotations
import os
from abc import ABC, abstractmethod
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Convert text to embedding vector."""
        ...


class OpenAIBackend(EmbeddingProvider):
    """OpenAI text-embedding-ada-002 implementation."""

    def __init__(self):
        import openai
        self.client = openai.AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY", ""),
        )
        self.model = os.getenv("EMBEDDING_MODEL", "text-embedding-ada-002")

    async def embed(self, text: str) -> list[float]:
        resp = await self.client.embeddings.create(
            model=self.model,
            input=text[:8191],  # model token limit
        )
        return resp.data[0].embedding


class MockEmbeddingProvider(EmbeddingProvider):
    """Deterministic mock for testing. Returns a fixed-length vector with
    a hash-based signature so identical queries produce identical vectors."""

    def __init__(self, dimension: int = 1536):
        self.dimension = dimension

    async def embed(self, text: str) -> list[float]:
        import hashlib
        h = hashlib.sha256(text.encode()).digest()
        # Expand hash bytes to fill vector
        vec = []
        for i in range(self.dimension):
            vec.append((h[i % len(h)] / 255.0) - 0.5)
        return vec


def get_embedding_provider() -> EmbeddingProvider:
    """Factory: returns configured provider based on env vars."""
    provider = os.getenv("EMBEDDING_PROVIDER", "mock").lower()
    if provider == "openai":
        return OpenAIBackend()
    return MockEmbeddingProvider()
```

#### 2.8 Tool Registration (`app/services/ai/tool_registry.py` -- excerpt)

```python
SIMILAR_COURSES_TOOL = {
    "name": "query_similar_courses",
    "description": "...",
    "input_schema": { ... },  # Per FR-1 above
}

# In register_tools():
tools["query_similar_courses"] = {
    "schema": SIMILAR_COURSES_TOOL,
    "handler": "similar_course_service.query_similar_courses",
    "required_session": True,
}
```

#### 2.9 API Route (optional, for admin/UI) (`app/routers/ai_similar_courses.py`)

```python
"""REST endpoint for similar course queries (admin/UI use outside tool)."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.services.ai.similar_course_service import SimilarCourseService

router = APIRouter(prefix="/ai/similar-courses", tags=["AI"])


class SimilarCourseQuery(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    max_results: int = Field(default=5, ge=1, le=20)
    filters: dict = Field(default_factory=dict)


@router.post("")
async def query_similar_courses(
    body: SimilarCourseQuery,
    org_id: str = Query("default", alias="organizationId"),
    session: AsyncSession = Depends(get_session),
):
    service = SimilarCourseService(session, organization_id=org_id)
    return await service.query_similar_courses(
        query=body.query,
        max_results=body.max_results,
        filters=body.filters,
    )
```

#### 2.10 Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ENABLE_PGVECTOR` | `false` | Set to `true` to enable pgvector Tier-1 search |
| `EMBEDDING_PROVIDER` | `mock` | `mock` or `openai` |
| `OPENAI_API_KEY` | `` | Required when `EMBEDDING_PROVIDER=openai` |
| `EMBEDDING_MODEL` | `text-embedding-ada-002` | OpenAI embedding model name |
| `SIMILAR_COURSE_MAX_RESULTS` | `20` | Hard upper limit on result count |
| `SIMILAR_COURSE_CACHE_TTL_MINUTES` | `60` | Cache TTL for similarity results |

#### 2.11 Alembic Migration (`alembic/versions/20260615_0001_add_course_embeddings.py`)

```python
"""Add course_embeddings table for similar-course retrieval.

Revision ID: 20260615_0001
Revises: <latest_revision>
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "20260615_0001"
down_revision: Union[str, None] = "<parent_revision>"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS course_embeddings (
            id SERIAL PRIMARY KEY,
            course_record_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            organization_id VARCHAR(64) NOT NULL DEFAULT 'default',
            embedding vector(1536),
            content_hash VARCHAR(64) NOT NULL,
            chunk_count INTEGER NOT NULL DEFAULT 1,
            embedding_model VARCHAR(100) NOT NULL DEFAULT 'text-embedding-ada-002',
            is_stale BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
            updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_course_embeddings_course_record_id
            ON course_embeddings (course_record_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_course_embeddings_org_stale
            ON course_embeddings (organization_id, is_stale)
            WHERE is_stale = FALSE
    """)

    # Conditional: create pgvector index only if extension exists.
    conn = op.get_bind()
    ext = conn.execute(
        sa.text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')")
    ).scalar()
    if ext:
        op.execute("""
            CREATE INDEX IF NOT EXISTS ix_course_embeddings_vector
                ON course_embeddings
                USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100)
        """)

    # Similarity cache table
    op.execute("""
        CREATE TABLE IF NOT EXISTS course_similarity_cache (
            id SERIAL PRIMARY KEY,
            source_course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            similar_course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            similarity_score FLOAT NOT NULL,
            cache_tier VARCHAR(8) NOT NULL DEFAULT 'tier1',
            expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
            UNIQUE(source_course_id, similar_course_id)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS course_similarity_cache")
    op.execute("DROP INDEX IF EXISTS ix_course_embeddings_vector")
    op.execute("DROP INDEX IF EXISTS ix_course_embeddings_org_stale")
    op.execute("DROP INDEX IF EXISTS ix_course_embeddings_course_record_id")
    op.execute("DROP TABLE IF EXISTS course_embeddings")
```

---

### 3. Non-Functional Requirements

| ID | Requirement | Target | Measurement |
|---|---|---|---|
| NFR-1 | Latency P95 | < 2 seconds for Tier 2/3; < 3 seconds for Tier 1 (includes embedding generation) | APM tracing on `query_similar_courses` handler |
| NFR-2 | Throughput | 50 concurrent requests | k6 load test |
| NFR-3 | Tenant isolation | Zero cross-tenant leakage | Automated test: org-A query must never return org-B courses |
| NFR-4 | PII redaction coverage | 100% of known PII patterns redacted from excerpts | Regex test suite covering email, phone, SSN patterns |
| NFR-5 | Embedding cost | < $0.01 per query with OpenAI | Cost tracking in `ai_usage_records` |
| NFR-6 | Cache hit ratio | > 60% for repeated queries (same session) | Prometheus metric: `similar_course_cache_hit_ratio` |
| NFR-7 | Feature flag gating | Feature disabled by default; enable via `FEATURE_SIMILAR_COURSE_RETRIEVAL=true` | Feature flag check at tool invocation |

---

### 4. Current State (Baseline)

- No vector/embedding infrastructure exists in the project. The `pgvector` extension is not installed on any environment.
- No full-text search indexes exist on `courses` or `templates` tables.
- The only search-like functionality is in `GET /api/v1/courses/{courseId}/templates/available` which does a Python-side `search_lower in name/description` filter on in-memory lists.
- The `ai_suggestions` feature flag exists in `app/utils/feature_flags.py` but `similar_course_retrieval` does not.
- The `course_embeddings` and `course_similarity_cache` tables do not exist.
- No OpenAI or embedding provider integration exists.
- The `query_similar_courses` tool is referenced in `TOOL_SCHEMAS_CLAUDE_NATIVE.md` as a planned tool but is not registered.
- No PII redaction utilities exist in the codebase.

---

### 5. Expansion Points (Future Iterations)

- **Iteration 2 -- Scheduled Re-Embedding Job:** Add a background worker that polls `course_embeddings` for `is_stale = TRUE` and refreshes vectors. Use `app/services/ai/similar_course_service.py` embed method in a periodic ASGI task or external cron.
- **Iteration 3 -- Cross-Organization Admin Search:** Admins can search across all organizations for course discovery. Adds an `admin:true` flag that bypasses tenant scoping, gated by `ADMIN_ROLE` check.
- **Iteration 4 -- Hybrid Search (RRF):** Combine vector and full-text scores using Reciprocal Rank Fusion for improved relevance. Implement in `SimilarCourseRepository.hybrid_search()`.
- **Iteration 5 -- Multi-Modal Embeddings:** Extend embedding to include thumbnail/image embeddings for visual-style similarity.
- **Iteration 6 -- Feedback Loop:** Track which similar-course results lead to accepted AI proposals (via provenance in `ai_audit_logs`). Down-rank underperforming matches.
- **Iteration 7 -- Real-Time Similarity During Editing:** As the Author edits a page, the system auto-suggests similar pages from other courses in a sidebar panel.

---

### 6. Validation (Test Scenarios)

#### 6.1 Unit Tests

| ID | Scenario | Expected |
|---|---|---|
| UT-1 | `EmbeddingProvider.mock.embed("safety training")` returns a list of 1536 floats | Vector dimension = 1536 |
| UT-2 | `EmbeddingProvider.mock.embed("hello")` returns same vector as second call with "hello" | Deterministic output |
| UT-3 | PII redaction regex: `"Contact john@test.com or call 555-123-4567"` | Returns `"Contact [REDACTED] or call [REDACTED]"` |
| UT-4 | `_extract_excerpt` with MCQ template containing `questions[].question` | Returns the question text, truncated to 500 chars |
| UT-5 | `_extract_excerpt` with template containing `isCorrect: true` in data | `isCorrect` value is NOT included in excerpt (field is not in SAFE_EXCERPT_FIELDS) |
| UT-6 | `_empty_result("No matches")` returns courses=[], total_count=0, message includes "continue without examples" | Pass |
| UT-7 | `_derive_tone_notes` with template types `{welcome, mcq, summary}` | Returns string containing "introduction", "knowledge checks", and "recap" |

#### 6.2 Integration Tests

| ID | Scenario | Expected |
|---|---|---|
| IT-1 | Tier-2 search via `search_fulltext(session, "safety course", 5)` returns course with "safety" in title | Course is in results with score > 0 |
| IT-2 | Tier-3 search via `search_keyword(session, "onboarding", 5)` returns courses | At least one result with score 0.5 |
| IT-3 | `query_similar_courses` with empty string returns empty result with "Query is empty" message | Pass |
| IT-4 | `enrich_results` populates `template_breakdown`, `sample_excerpts`, `tone_notes` | All fields present in enriched output |
| IT-5 | Cross-tenant isolation: org-A query should not return org-B courses (test with two organizations) | Zero results from org-B |

#### 6.3 API Tests (via TestClient)

| ID | Scenario | Expected |
|---|---|---|
| AT-1 | `POST /api/v1/ai/similar-courses` with valid body `{"query": "safety training"}` returns 200 with `courses` array | Pass |
| AT-2 | Same endpoint with empty query returns 422 validation error | Pass |
| AT-3 | Tool adapter `query_similar_courses(session_id="valid", query="data science")` returned via AI chat orchestrator | Tool result is well-formed dict |
| AT-4 | With `FEATURE_SIMILAR_COURSE_RETRIEVAL=false`, tool call returns feature-disabled error | Pass |

#### 6.4 Security Tests

| ID | Scenario | Expected |
|---|---|---|
| ST-1 | PII in course content: email in template body | Excerpt redacts email |
| ST-2 | Cross-tenant: org-A session queries, only org-B courses exist | Empty results |

---

### 7. Definition of Done

- [x] `app/models/course_embedding.py` created with `CourseEmbeddingRecord` ORM model
- [x] `app/repositories/similar_course_repo.py` created with Tier-1, Tier-2, Tier-3 search methods and `enrich_results`
- [x] `app/services/ai/embedding_provider.py` created with `EmbeddingProvider` ABC, `OpenAIBackend`, `MockEmbeddingProvider`, and factory function
- [x] `app/services/ai/similar_course_service.py` created with `query_similar_courses` method orchestrating tiered fallback
- [x] `app/services/ai/tool_registry.py` updated to register `query_similar_courses` tool with input schema per FR-1
- [x] `app/main.py` imports `app.models.course_embedding` for auto-create on startup
- [x] `alembic/env.py` imports `app.models.course_embedding` for autogenerate
- [x] Alembic migration creates `course_embeddings` and `course_similarity_cache` tables (includes conditional pgvector index)
- [x] `app/utils/feature_flags.py` updated with `similar_course_retrieval` flag (default disabled)
- [x] Environment variables documented: `ENABLE_PGVECTOR`, `EMBEDDING_PROVIDER`, `OPENAI_API_KEY`, `EMBEDDING_MODEL`
- [x] PII redaction regex covers email, US phone, SSN patterns
- [x] Excerpt extraction excludes secure fields (`isCorrect`, `correctAnswer`, `correctAnswers`, scoring config)
- [x] Empty results return non-fatal guidance message
- [x] Unit tests pass (UT-1 through UT-7)
- [x] Integration tests pass (IT-1 through IT-5)
- [x] API tests pass (AT-1 through AT-4)
- [x] Security tests pass (ST-1, ST-2)
- [x] System prompt includes source-of-truth warning for `query_similar_courses`
- [x] Feature flag disables tool with clear error message when off

---

### 8. Task Breakdown

| Task ID | Description | Estimate (h) | Owner | Dependencies |
|---|---|---|---|---|
| T-01 | Create `CourseEmbeddingRecord` ORM model in `app/models/course_embedding.py` | 1 | Backend | None |
| T-02 | Write Alembic migration `20260615_0001` for `course_embeddings` and `course_similarity_cache` tables | 2 | Backend | T-01 |
| T-03 | Implement `EmbeddingProvider` ABC, `MockEmbeddingProvider`, `OpenAIBackend`, and factory in `app/services/ai/embedding_provider.py` | 2 | Backend | None |
| T-04 | Implement `SimilarCourseRepository` with `search_vector`, `search_fulltext`, `search_keyword`, and `enrich_results` in `app/repositories/similar_course_repo.py` | 4 | Backend | T-01 |
| T-05 | Implement PII redaction utility and safe-field excerpt extraction in repository | 1 | Backend | T-04 |
| T-06 | Implement `SimilarCourseService.query_similar_courses` tiered orchestration in `app/services/ai/similar_course_service.py` | 2 | Backend | T-03, T-04 |
| T-07 | Register `query_similar_courses` tool in `app/services/ai/tool_registry.py` with input schema | 1 | Backend | T-06 |
| T-08 | Wire service into AI chat orchestrator (`app/services/ai/chat_orchestrator.py`) for tool dispatch | 1 | Backend | T-07 |
| T-09 | Add `similar_course_retrieval` feature flag to `app/utils/feature_flags.py` | 0.5 | Backend | None |
| T-10 | Add feature-flag guard at tool invocation (return disabled error when off) | 0.5 | Backend | T-09 |
| T-11 | Add import of `course_embedding` model to `app/main.py` and `alembic/env.py` | 0.5 | Backend | T-01 |
| T-12 | Create optional REST endpoint `POST /api/v1/ai/similar-courses` in `app/routers/ai_similar_courses.py` | 1 | Backend | T-06 |
| T-13 | Update system prompt template with source-of-truth warning for `query_similar_courses` | 0.5 | Backend/AI Engineer | T-07 |
| T-14 | Write unit tests (UT-1 through UT-7) | 2 | QA/Backend | T-03, T-04 |
| T-15 | Write integration tests (IT-1 through IT-5) | 3 | QA/Backend | T-06 |
| T-16 | Write API tests (AT-1 through AT-4) via TestClient | 2 | QA/Backend | T-12 |
| T-17 | Write security tests (ST-1, ST-2) | 1 | QA/Security | T-05 |
| T-18 | Add environment variables to `.env.example` and deployment configs | 0.5 | DevOps | T-03 |
| T-19 | Performance test: k6 script for 50 concurrent `query_similar_courses` calls | 1 | QA | T-06 |
| T-20 | Documentation: update `TOOL_SCHEMAS_CLAUDE_NATIVE.md` with final `query_similar_courses` contract | 1 | Tech Writer | T-07 |

**Total estimated effort: 26 hours**

---

**Key File Paths Summary**

- New model: `/c/Users/ADMIN/e-learning-backend/app/models/course_embedding.py`
- New repository: `/c/Users/ADMIN/e-learning-backend/app/repositories/similar_course_repo.py`
- New service: `/c/Users/ADMIN/e-learning-backend/app/services/ai/similar_course_service.py`
- New embedding provider: `/c/Users/ADMIN/e-learning-backend/app/services/ai/embedding_provider.py`
- New router: `/c/Users/ADMIN/e-learning-backend/app/routers/ai_similar_courses.py`
- New migration: `/c/Users/ADMIN/e-learning-backend/alembic/versions/20260615_0001_add_course_embeddings.py`
- Modified tool registry: `/c/Users/ADMIN/e-learning-backend/app/services/ai/tool_registry.py`
- Modified chat orchestrator: `/c/Users/ADMIN/e-learning-backend/app/services/ai/chat_orchestrator.py`
- Modified feature flags: `/c/Users/ADMIN/e-learning-backend/app/utils/feature_flags.py`
- Modified main.py: `/c/Users/ADMIN/e-learning-backend/app/main.py`
- Modified alembic env: `/c/Users/ADMIN/e-learning-backend/alembic/env.py`
- Test file: `/c/Users/ADMIN/e-learning-backend/tests/test_similar_course_retrieval.py`

---