"""Similar Course Retrieval Service — US-BKND-AI-015.

Orchestrates three-tier retrieval with automatic fallback.
Feature-flag gated. Session-scoped for tenant isolation.

Matcher: Constructor takes db: AsyncSession only (matches AISessionService,
AIProposalService, etc.)
"""
from __future__ import annotations

import hashlib
import logging
import time
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
            # ── Trace: empty query (non-retrieval) ──────────────────
            from app.services.ai.session_tracer import SessionTracer as _Tracer2
            _t2 = _Tracer2(self.db)
            await _t2.start_span(
                session_id=session_id,
                trace_type="rag_retrieval",
                operation="query_similar_courses",
                input_payload={"query": query, "max_results": max_results},
            )
            return self._empty_result("Query is empty.", "none")

        max_results = max(1, min(max_results, 20))

        # ── 3. Tiered retrieval with per-tier timing ──────────
        raw_results: list[dict] = []
        tier_used = "tier1"
        t0_total = time.perf_counter()
        tier1_ms = 0.0
        tier2_ms = 0.0
        tier3_ms = 0.0

        # ── Session trace: RAG retrieval start ──────────────────────
        from app.services.ai.session_tracer import SessionTracer
        tracer = SessionTracer(self.db)
        rag_span = await tracer.start_span(
            session_id=session_id,
            trace_type="rag_retrieval",
            operation="query_similar_courses",
            input_payload={
                "query": query,
                "max_results": max_results,
                "filters": filters,
                "organization_id": organization_id,
            },
            metadata={"embedding_provider": type(self.embedding_provider).__name__},
        )

        # Tier 1: Vector search
        t0 = time.perf_counter()
        try:
            embedding = await self.embedding_provider.embed(query)
            raw_results = await self.retrieval_repo.search_vector(
                embedding, organization_id, max_results
            )
        except Exception as exc:
            logger.info("Tier-1 unavailable (degrading): %s", exc)
            raw_results = []
        tier1_ms = (time.perf_counter() - t0) * 1000

        # Tier 2: Full-text search
        if not raw_results:
            tier_used = "tier2"
            t0 = time.perf_counter()
            try:
                raw_results = await self.retrieval_repo.search_fulltext(
                    query, organization_id, max_results
                )
            except Exception as exc:
                logger.warning("Tier-2 failed (degrading): %s", exc)
                raw_results = []
            tier2_ms = (time.perf_counter() - t0) * 1000

        # Tier 3: Keyword search
        if not raw_results:
            tier_used = "tier3"
            t0 = time.perf_counter()
            try:
                raw_results = await self.retrieval_repo.search_keyword(
                    query, organization_id, max_results
                )
            except Exception as exc:
                logger.error("Tier-3 failed — all tiers exhausted: %s", exc)
                raw_results = []
            tier3_ms = (time.perf_counter() - t0) * 1000

        # ── 3a. Audit: log retrieval event with per-tier metrics ──
        try:
            from app.services.ai.audit_service import AIAuditService
            audit = AIAuditService(self.db)
            query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
            await audit.log(
                session_id=session_id,
                user_id=user_id or session.user_id,
                organization_id=organization_id,
                course_id="",  # Retrieval is not course-specific
                action=AIAuditService.ACTION_SIMILAR_COURSE_RETRIEVAL,
                target_type="retrieval",
                details={
                    "tier_used": int(tier_used[-1]),  # 1, 2, or 3
                    "result_count": len(raw_results),
                    "query_hash": query_hash,
                    "embedding_model": (
                        self.embedding_provider.model_name
                        if hasattr(self.embedding_provider, 'model_name')
                        else "unknown"
                    ),
                    "latency": {
                        "tier1_ms": round(tier1_ms, 2),
                        "tier2_ms": round(tier2_ms, 2),
                        "tier3_ms": round(tier3_ms, 2),
                        "total_ms": round((time.perf_counter() - t0_total) * 1000, 2),
                    },
                },
            )
        except Exception as exc:
            logger.warning("Audit logging failed (non-fatal): %s", exc)

        # ── 4. Empty after all tiers ────────────────────────
        if not raw_results:
            await tracer.end_span(
                rag_span,
                output_payload={
                    "results": [],
                    "total_count": 0,
                    "retrieval_tier_used": tier_used,
                    "tier_latency_ms": {
                        "tier1": tier1_ms, "tier2": tier2_ms, "tier3": tier3_ms,
                    },
                },
                latency_ms=(time.perf_counter() - t0_total) * 1000,
                metadata={"tier_used": tier_used},
            )
            return self._empty_result("No similar courses found.", tier_used)

        # ── 5. Enrich ───────────────────────────────────────
        enriched = await self.retrieval_repo.enrich_results(raw_results, query)

        # ── 6. Post-filter ──────────────────────────────────
        if filters:
            enriched = self._apply_filters(enriched, filters)

        # ── 7. Slice ────────────────────────────────────────
        top = enriched[:max_results]

        # ── Trace: RAG retrieval complete ────────────────────
        await tracer.end_span(
            rag_span,
            output_payload={
                "results": [
                    {
                        "courseId": r.get("courseId", r.get("course_id", "")),
                        "title": r.get("title", ""),
                        "relevance_score": r.get("relevance_score", 0),
                        "page_count": r.get("page_count", 0),
                    }
                    for r in top
                ],
                "total_count": len(top),
                "retrieval_tier_used": tier_used,
                "tier_latency_ms": {
                    "tier1": round(tier1_ms, 2),
                    "tier2": round(tier2_ms, 2),
                    "tier3": round(tier3_ms, 2),
                },
            },
            latency_ms=round((time.perf_counter() - t0_total) * 1000, 2),
            metadata={"tier_used": tier_used},
        )

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
