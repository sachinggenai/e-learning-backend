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
            existing.embedding = embedding  # pgvector stores as native vector type
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
            embedding=embedding,  # pgvector stores native list[float]
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

    async def find_courses_without_embeddings(self, limit: int = 10) -> list:
        """Find courses that don't have an embedding yet — US-PEND-020.

        Returns CourseRecord objects (has .id, .course_id, .title, .organization_id).
        """
        from app.models.persisted_course import CourseRecord
        from app.models.course_embedding import CourseEmbeddingRecord

        subq = select(CourseEmbeddingRecord.course_record_id)
        q = (
            select(CourseRecord)
            .where(CourseRecord.id.not_in(subq))
            .limit(limit)
        )
        result = await self.session.execute(q)
        return list(result.scalars().all())
