"""Course Generation Service - US-BKND-AI-019.

Orchestrates full course generation from an approved page plan (US-AI-017).
Creates page content via LLM, validates against template schemas, assembles
a batch proposal, and supports user review before transactional apply.

Architecture:
    Upload -> Extract (017) -> Plan Review (017) -> Generate (019) -> Review -> Apply

The generation is async: a job record tracks progress. Each page is generated
individually with validation feedback loops.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import normalize_template_type

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Job Status
# ---------------------------------------------------------------------------

class GenerationStatus(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    READY_FOR_REVIEW = "ready_for_review"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Content Fingerprint — dedup identical re-applies
# ---------------------------------------------------------------------------

def _compute_course_fingerprint(pages_data: List[Dict[str, Any]]) -> str:
    """Compute a deterministic content hash for deduplication.

    Normalizes page order, titles, template types, and component content
    (first 500 chars) so that identical course content always produces
    the same fingerprint regardless of UUIDs or minor whitespace changes.

    Returns a 64-char hex SHA-256 digest.
    """
    normalized = []
    sorted_pages = sorted(pages_data, key=lambda p, idx=0: p.get("order", idx))
    for i, p in enumerate(sorted_pages):
        components = []
        comps = sorted(p.get("components", []), key=lambda c, idx=0: c.get("order_index", idx))
        for j, c in enumerate(comps):
            comp_data = c.get("data", {})
            components.append({
                "type": c.get("component_type", ""),
                "content": str(comp_data.get("content", ""))[:500],
                "order": c.get("order_index", j),
            })
        normalized.append({
            "title": p.get("title", ""),
            "template_type": p.get("template_type", ""),
            "order": p.get("order", i),
            "components": components,
        })
    return hashlib.sha256(
        json.dumps(normalized, sort_keys=True).encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------
# Course Generator
# ---------------------------------------------------------------------------

class CourseGenerator:
    """Generates full course content from an approved page plan.

    In production mode, calls the LLM for each page. In mock mode,
    generates template-appropriate placeholder content for testing.

    Usage:
        gen = CourseGenerator(db)
        job = await gen.start_generation(import_job_id, session_id, user_id)
        # Poll: job = await gen.get_job_status(job_id)
        # On ready: await gen.apply_generated_course(job_id, user_id)
    """

    DEFAULT_RETRY_COUNT = 2

    def __init__(
        self,
        db: AsyncSession,
        use_llm: Optional[bool] = None,
        llm_client: Any = None,
    ):
        self.db = db
        self.retry_count = self.DEFAULT_RETRY_COUNT
        self._last_model_used = "mock"     # Updated during generation for provenance
        self._last_provider_used = "mock"  # Updated during generation for provenance
        # Auto-detect: use LLM when AI is configured and enabled,
        # with explicit override via AI_GENERATION_PROVIDER env var (G-07 fix)
        if use_llm is None:
            provider_env = os.getenv("AI_GENERATION_PROVIDER", "").lower()
            if provider_env in ("llm", "anthropic"):
                use_llm = True
            elif provider_env == "mock":
                use_llm = False
            else:
                from app.services.ai.config import get_ai_config
                cfg = get_ai_config()
                use_llm = bool(
                    cfg.ai_authoring_enabled
                    and cfg.anthropic_api_key
                    and cfg.ai_status.value in ("configured",)
                )
        self.use_llm = use_llm
        self._llm_client = llm_client

    # ------------------------------------------------------------------
    # Phase 0: Initiate Generation
    # ------------------------------------------------------------------

    async def start_generation(
        self,
        import_job_id: str,
        session_id: str,
        user_id: str,
        organization_id: str = "",
        course_id: str = "",
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Start course generation from an approved page plan.

        Args:
            import_job_id: The ingestion job with approved page plan.
            session_id: Active AI session.
            user_id: Authenticated user.
            organization_id: Tenant org.
            course_id: Optional target course (merge mode) or empty for new.
            options: Generation options (model, tone, audience, etc.)

        Returns:
            Job status dict with job_id, status, page_count.
        """
        # Validate import job
        job = await self._get_import_job(import_job_id)
        if job is None:
            raise GenerationError("IMPORT_JOB_NOT_FOUND",
                                  f"Import job '{import_job_id}' not found.", 404)

        # Guard: job must be in plan_approved, generated, or completed state.
        # Completed jobs can re-enter generation via the idempotency path below.
        if job.status not in ("plan_approved", "generated", "completed"):
            raise GenerationError(
                "INVALID_STATE",
                f"Job must be in 'plan_approved', 'generated', or 'completed' state, "
                f"currently '{job.status}'. "
                "Approve the page plan before generating content.",
                400,
            )

        # ── Idempotency: completed job → reset and return cached course ──
        if job.status == "completed":
            meta_check = dict(job.source_metadata or {})
            existing_course = meta_check.get("generated_course")
            if not existing_course or not isinstance(existing_course, dict):
                raise GenerationError(
                    "NO_GENERATED_COURSE",
                    "Job is completed but has no cached course data. "
                    "Re-upload the source document to regenerate.",
                    400,
                )
            meta_check["generation_status"] = GenerationStatus.READY_FOR_REVIEW.value
            meta_check.pop("applied_at", None)
            meta_check.pop("applied_pages", None)
            # Keep content_fingerprint — used by apply for dedup
            job.source_metadata = meta_check
            job.status = "generated"
            await self.db.commit()

            # Clear old idempotency record so re-apply isn't blocked by stale cache
            from app.models.ai_models import AIIdempotencyKeyRecord
            from app.services.ai.idempotency_service import IdempotencyService
            from sqlalchemy import delete as sa_delete_idem
            old_key = IdempotencyService.generate_key(import_job_id, user_id)
            await self.db.execute(
                sa_delete_idem(AIIdempotencyKeyRecord).where(
                    AIIdempotencyKeyRecord.idempotency_key == old_key
                )
            )
            await self.db.commit()
            pages_data = existing_course.get("pages", [])
            return {
                "job_id": import_job_id,
                "status": GenerationStatus.READY_FOR_REVIEW.value,
                "total_pages": len(pages_data),
                "generated_pages": len(pages_data),
                "course_title": existing_course.get("title", "Generated Course"),
                "idempotent": True,
                "message": (
                    "Returning existing course — generation_status reset "
                    "to ready_for_review for re-apply."
                ),
                "pages": [
                    {
                        "title": p["title"],
                        "template_type": p.get("template_type", "content-text"),
                        "component_count": len(p.get("components", [])),
                        "validation_status": "valid",
                    }
                    for p in pages_data
                ],
                "validation": {
                    "total": len(pages_data),
                    "errors": 0,
                    "warnings": 0,
                },
            }

        # Check plan is approved
        raw = job.extracted_sections or {}
        if not raw:
            raise GenerationError("EMPTY_PAGE_PLAN",
                                  "The import job has no approved page plan.", 400)

        # Handle both formats:
        #   (A) Legacy list: [{"heading": ..., "content_preview": ..., ...}, ...]
        #   (B) Approved plan dict: {"plan": [...], "approved": true, ...}
        if isinstance(raw, dict) and "plan" in raw:
            plan = raw["plan"]
        elif isinstance(raw, list):
            plan = raw
        else:
            raise GenerationError("EMPTY_PAGE_PLAN",
                                  "The import job has no approved page plan.", 400)

        if not isinstance(plan, list) or len(plan) == 0:
            raise GenerationError("EMPTY_PAGE_PLAN",
                                  "The import job has no approved page plan.", 400)

        # Validate plan structure
        pages = []
        for section in plan:
            if isinstance(section, dict):
                pages.append({
                    "title": section.get("proposed_title") or section.get("title", "Untitled"),
                    "template_type": section.get("suggested_template_type") or section.get("template_type", "content-text"),
                    "order": section.get("order", len(pages)),
                    "source_excerpt": section.get("content_preview") or section.get("content", section.get("text", "")),
                })

        if not pages:
            raise GenerationError("EMPTY_PAGE_PLAN",
                                  "No valid pages found in the approved plan.", 400)

        # Run generation (synchronous in mock mode, async in production)
        try:
            generated_pages = await self._generate_pages(pages, options or {})
        except Exception as e:
            raise GenerationError("PAGE_GENERATION_FAILED",
                                  f"Page generation failed: {str(e)}", 500)

        # Validate generated pages
        validation_results = self._validate_generated_pages(generated_pages)

        # Check for blocking errors
        errors = [v for v in validation_results if v.get("severity") == "error"]
        if errors:
            return {
                "job_id": import_job_id,
                "status": GenerationStatus.FAILED.value,
                "total_pages": len(pages),
                "generated_pages": len(generated_pages),
                "validation_errors": errors,
            }

        # Build course data
        course_title = (options or {}).get("course_title",
                        job.detected_type or "Generated Course")

        course_data = {
            "title": course_title,
            "description": (options or {}).get("description", ""),
            "pages": generated_pages,
            "validation_results": validation_results,
            "provenance": {
                "import_job_id": import_job_id,
                "generated_at": datetime.utcnow().isoformat(),
                "model": self._last_model_used or "mock",
                "provider": self._last_provider_used or "mock",
                "page_count": len(generated_pages),
            },
        }

        # Store course data in the import job's metadata
        # IMPORTANT: reassign the entire dict to trigger SQLAlchemy mutation tracking
        meta = dict(job.source_metadata or {})
        meta["generated_course"] = course_data
        meta["generation_status"] = GenerationStatus.READY_FOR_REVIEW.value
        job.source_metadata = meta
        job.status = "generated"  # Distinct state: course generated, ready for review/apply
        self.db.add(job)
        await self.db.commit()

        return {
            "job_id": import_job_id,
            "status": GenerationStatus.READY_FOR_REVIEW.value,
            "total_pages": len(pages),
            "generated_pages": len(generated_pages),
            "course_title": course_title,
            "pages": [
                {
                    "title": p["title"],
                    "template_type": p["template_type"],
                    "component_count": len(p.get("components", [])),
                    "validation_status": next(
                        (v.get("status", "valid") for v in validation_results
                         if v.get("page_index") == i), "valid"
                    ),
                }
                for i, p in enumerate(generated_pages)
            ],
            "validation": {
                "total": len(validation_results),
                "errors": len(errors),
                "warnings": len([v for v in validation_results if v.get("severity") == "warning"]),
            },
        }

    async def get_job_status(self, import_job_id: str) -> Dict[str, Any]:
        """Get the current status of a course generation job."""
        job = await self._get_import_job(import_job_id)
        if job is None:
            raise GenerationError("IMPORT_JOB_NOT_FOUND",
                                  f"Import job '{import_job_id}' not found.", 404)

        meta = job.source_metadata or {}
        if isinstance(meta, dict):
            course_data = meta.get("generated_course", {})
            status = meta.get("generation_status", "pending")
            return {
                "job_id": import_job_id,
                "status": status,
                "course_title": course_data.get("title", ""),
                "total_pages": len(course_data.get("pages", [])),
                "course_data": course_data if status == "ready_for_review" else None,
            }

        return {
            "job_id": import_job_id,
            "status": "pending",
            "course_title": "",
            "total_pages": 0,
            "course_data": None,
        }

    # ------------------------------------------------------------------
    # Phase: Apply Generated Course
    # ------------------------------------------------------------------

    async def apply_generated_course(
        self,
        import_job_id: str,
        user_id: str,
        organization_id: str = "",
    ) -> Dict[str, Any]:
        """Apply a generated course: create Course + Pages + Components in DB.

        Reads the generated_course from the job's source_metadata, creates
        all records in a single transaction, and marks the job as committed.

        Returns the final course with all created pages and components.
        """
        job = await self._get_import_job(import_job_id)
        if job is None:
            raise GenerationError("IMPORT_JOB_NOT_FOUND",
                                  f"Import job '{import_job_id}' not found.", 404)

        meta = job.source_metadata or {}
        if not isinstance(meta, dict):
            raise GenerationError("NO_GENERATED_COURSE",
                                  "No generated course data found in import job.", 400)

        course_data = meta.get("generated_course")
        if not course_data or not isinstance(course_data, dict):
            raise GenerationError("NO_GENERATED_COURSE",
                                  "No generated course data found. Run generation first.", 400)

        gen_status = meta.get("generation_status", "")
        if gen_status != "ready_for_review":
            raise GenerationError("COURSE_NOT_READY",
                                  f"Course is not ready for apply. Current status: {gen_status}", 400)

        pages_data = course_data.get("pages", [])
        if not pages_data:
            raise GenerationError("NO_PAGES",
                                  "Generated course has no pages to apply.", 400)

        course_title = course_data.get("title", job.detected_type or "Generated Course")
        course_description = course_data.get("description", "")
        course_id = job.course_id or f"COURSE-{import_job_id[:8]}"

        # ── Create (or update) the CourseRecord FIRST ──────────────────
        # Must exist before pages are flushed to satisfy FK constraint.
        from app.repositories.course_repo import CourseRepository

        course_repo = CourseRepository(self.db)
        await course_repo.upsert(
            course_id=course_id,
            title=course_title,
            description=course_description or "",
            data={"source_import_job_id": import_job_id},
            status="draft",
        )

        # ── Content fingerprint check (dedup identical re-applies) ────
        new_fingerprint = _compute_course_fingerprint(pages_data)
        existing_fingerprint = meta.get("content_fingerprint", "")

        if existing_fingerprint and existing_fingerprint == new_fingerprint:
            logger.info(
                "Content fingerprint match for job %s — skipping re-apply",
                import_job_id[:8],
            )
            return {
                "course_id": course_id,
                "course_title": course_title,
                "pages_created": 0,
                "pages": [],
                "idempotent": True,
                "message": "Content unchanged — no re-apply needed.",
            }

        # ── Delete existing pages (re-apply or content-changed scenario)
        # Components cascade-delete via FK ondelete CASCADE.
        from app.models.page_component import PageRecord, ComponentRecord
        from app.repositories.page_component_repo import PageRepository
        from sqlalchemy import delete as sa_delete
        import uuid as _uuid

        page_repo = PageRepository(self.db)

        # Remove old pages so re-apply doesn't duplicate
        if existing_fingerprint:
            logger.info(
                "Content fingerprint changed for job %s — replacing pages",
                import_job_id[:8],
            )
        await self.db.execute(
            sa_delete(PageRecord).where(PageRecord.course_id == course_id)
        )
        await self.db.flush()

        # ── Create fresh pages and components ──────────────────────────
        created_pages = []
        for i, p in enumerate(pages_data):
            page_id = str(_uuid.uuid4())
            page = PageRecord(
                page_id=page_id,
                course_id=course_id,
                title=p.get("title", f"Page {i + 1}"),
                order_index=p.get("order", i),
                layout={
                    "templateType": p.get("template_type", "content-text"),
                },
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )

            # Create components for this page
            components = p.get("components", [])
            for j, comp in enumerate(components):
                component = ComponentRecord(
                    component_id=str(_uuid.uuid4()),
                    page_id=page_id,
                    component_type=comp.get("component_type", "content-text"),
                    order_index=comp.get("order_index", j),
                    data=comp.get("data", {}),
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
                page.components.append(component)

            self.db.add(page)
            created_pages.append(page)

        await self.db.commit()

        # Mark job as committed — build new dict for mutation tracking
        final_meta = dict(job.source_metadata or {})
        final_meta["generation_status"] = "completed"
        final_meta["applied_at"] = datetime.utcnow().isoformat()
        final_meta["applied_pages"] = len(created_pages)
        final_meta["content_fingerprint"] = new_fingerprint
        job.source_metadata = final_meta
        job.status = "completed"
        self.db.add(job)
        await self.db.commit()

        return {
            "course_id": course_id,
            "course_title": course_title,
            "pages_created": len(created_pages),
            "pages": [
                {
                    "page_id": p.page_id,
                    "title": p.title,
                    "order": p.order_index,
                    "template_type": (p.layout or {}).get("templateType", "content-text"),
                    "component_count": len(p.components),
                }
                for p in created_pages
            ],
        }

    # ------------------------------------------------------------------
    # Phase 1: Page Content Generation
    # ------------------------------------------------------------------

    async def _generate_pages(
        self, pages: List[Dict[str, Any]], options: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate content for each page in the plan.

        When use_llm=True and LLM client is available, uses AGT-07 Content Generator
        for AI-powered content generation (G-07 fix).
        Otherwise falls back to mock placeholder content.
        """
        if self.use_llm:
            try:
                return await self._generate_pages_with_llm(pages, options)
            except Exception as exc:
                logger.warning(
                    "LLM generation failed (%s) — falling back to mock generation", exc
                )
                self._last_model_used = "mock"
                self._last_provider_used = "mock"

        # Mock fallback (original behaviour)
        if not self.use_llm:
            self._last_model_used = "mock"
            self._last_provider_used = "mock"
        generated = []
        for i, page in enumerate(pages):
            content = self._generate_page_content(page, options, i)
            generated.append(content)
        return generated

    async def _generate_pages_with_llm(
        self, pages: List[Dict[str, Any]], options: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate pages using AGT-07 Content Generator Agent via LLM.

        Uses the StreamManager for parallel generation when Redis is available,
        or asyncio.gather with semaphore as fallback.
        """
        from app.services.ai.agents.content_generator_agent import ContentGeneratorAgent
        from app.services.ai.fanout import StreamManager
        from app.services.ai.config import get_ai_config
        from app.services.ai.llm_client import LLMClient, LLMProvider

        cfg = get_ai_config()
        llm_client = self._llm_client
        if llm_client is None:
            provider = _resolve_generation_provider(cfg)
            llm_client = LLMClient(provider=provider)

        # Track the actual model/provider used for provenance (G4 fix)
        self._last_model_used = llm_client.model
        self._last_provider_used = llm_client.provider.value

        # Get JSON repair instance
        json_repair = None
        try:
            from app.services.ai.json_repair import JSONRepair
            json_repair = JSONRepair()
        except Exception:
            pass

        agent = ContentGeneratorAgent(
            llm_client=llm_client,
            json_repair=json_repair,
            max_retries=3,
        )

        # Build template assignments from page plans
        templates = []
        for page in pages:
            ttype = page.get("template_type", "content-text")
            templates.append({
                "template_type": ttype,
                "confidence": 0.85,
                "method": "plan",
                "reasoning": f"Assigned from page plan: {ttype}",
            })

        # Course context from options
        course_context = {
            "title": options.get("course_title", "Generated Course"),
            "description": options.get("description", ""),
            "audience": options.get("audience", "adult learners"),
            "tone": options.get("tone", "professional"),
        }

        # Use StreamManager for parallel generation
        stream_mgr = StreamManager()
        result = await stream_mgr.fan_out_pages(
            job_id=options.get("job_id", f"gen-{id(pages)}"),
            pages=pages,
            templates=templates,
            rag_context=options.get("rag_context", []),
            course_context=course_context,
            generate_func=agent.generate_page,
        )

        logger.info(
            "LLM generation complete: %d pages, backend=%s, %.0fms, "
            "%d success, %d fallback, %d error",
            len(result.pages), result.backend, result.total_duration_ms,
            sum(1 for p in result.pages if p.status == "success"),
            sum(1 for p in result.pages if p.status == "fallback"),
            sum(1 for p in result.pages if p.status == "error"),
        )

        # Convert PageResults to dict format
        generated = []
        for pr in result.pages:
            if pr.status in ("success", "fallback") and pr.data:
                generated.append(pr.data)
            else:
                # Failed page — use mock fallback
                idx = pr.page_index
                mock = self._generate_page_content(pages[idx], options, idx)
                mock["generation_metadata"] = {
                    "fallback": True,
                    "reason": pr.error or "LLM generation failed",
                    "method": "mock",
                }
                generated.append(mock)

        return generated

    def _generate_page_content(
        self, page: Dict[str, Any], options: Dict[str, Any], index: int
    ) -> Dict[str, Any]:
        """Generate content for a single page (mock mode).

        Produces template-appropriate component data based on the
        suggested template type.
        """
        template_type = page.get("template_type", "text-content")
        title = page.get("title", f"Page {index + 1}")
        source = page.get("source_excerpt", "")

        components = []

        # Accept both old (legacy) and new (canonical) type names for backward compat
        if template_type in ("text-content", "content-text"):
            components.append({
                "component_type": "content-text",
                "order_index": 0,
                "data": {
                    "content": (
                        f"<h2>{title}</h2>\n"
                        f"<p>This section covers key concepts related to {title.lower()}.</p>\n"
                        f"<p>Based on: {source[:200] if source else 'course material'}</p>"
                    ),
                },
            })

        elif template_type == "accordion":
            components.append({
                "component_type": "accordion",
                "order_index": 0,
                "data": {
                    "items": [
                        {"title": f"Introduction to {title}",
                         "content": f"Overview of key concepts in {title.lower()}."},
                        {"title": "Key Details",
                         "content": source[:300] if source else "Detailed information about this topic."},
                        {"title": "Summary",
                         "content": f"Key takeaways from {title.lower()}."},
                    ],
                },
            })

        elif template_type == "tabs":
            components.append({
                "component_type": "tabs",
                "order_index": 0,
                "data": {
                    "tabs": [
                        {"title": "Overview", "content": f"Introduction to {title.lower()}."},
                        {"title": "Details", "content": source[:200] if source else "Details here."},
                        {"title": "Examples", "content": "Practical examples and use cases."},
                    ],
                },
            })

        elif template_type in ("click-reveal",):
            # Legacy type — normalizes to accordion; items shape is compatible
            components.append({
                "component_type": "accordion",
                "order_index": 0,
                "data": {
                    "items": [
                        {"title": f"Q: What is {title}?",
                         "content": f"A: {source[:200] if source else 'Key concept explanation.'}"},
                        {"title": "Q: Why is this important?",
                         "content": "This concept is fundamental to understanding the course material."},
                    ],
                },
            })

        elif template_type == "final-assessment":
            components.append({
                "component_type": "final-assessment",
                "order_index": 0,
                "data": {
                    "passing_score": 80,
                    "questions": [
                        {
                            "id": f"q-{index}-1",
                            "type": "mcq",
                            "question": f"What is the main topic of {title}?",
                            "options": [
                                {"id": "opt-a", "text": "Option A — Correct", "isCorrect": True},
                                {"id": "opt-b", "text": "Option B", "isCorrect": False},
                                {"id": "opt-c", "text": "Option C", "isCorrect": False},
                                {"id": "opt-d", "text": "Option D", "isCorrect": False},
                            ],
                        },
                    ],
                },
            })

        else:
            # Default to content-text
            components.append({
                "component_type": "content-text",
                "order_index": 0,
                "data": {"content": f"<h2>{title}</h2>\n<p>Content for {title.lower()}.</p>"},
            })

        return {
            "title": title,
            "template_type": normalize_template_type(template_type),
            "order": page.get("order", index),
            "components": components,
            "source_excerpt": source[:500] if source else "",
        }

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_generated_pages(
        self, pages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Validate all generated pages against template schemas."""
        results = []
        for i, page in enumerate(pages):
            ttype = page.get("template_type", "text-content")
            components = page.get("components", [])
            title = page.get("title", "")

            page_errors = []
            page_warnings = []

            # Basic validation
            if not title:
                page_errors.append("Page title is required")
            if not components:
                page_errors.append("Page must have at least one component")

            # Template-specific checks
            if ttype == "final-assessment":
                for comp in components:
                    questions = comp.get("data", {}).get("questions", [])
                    if not questions:
                        page_warnings.append("Assessment has no questions")
                    passing = comp.get("data", {}).get("passing_score", 0)
                    if passing < 0 or passing > 100:
                        page_errors.append("Passing score must be 0-100")

            if ttype == "accordion":
                for comp in components:
                    items = comp.get("data", {}).get("items", [])
                    if not items:
                        page_warnings.append("Accordion has no items")

            if ttype == "tabs":
                for comp in components:
                    tabs = comp.get("data", {}).get("tabs", [])
                    if not tabs:
                        page_warnings.append("Tabs component has no tabs")

            severity = "error" if page_errors else ("warning" if page_warnings else "valid")
            results.append({
                "page_index": i,
                "page_title": title,
                "status": severity,
                "errors": page_errors,
                "warnings": page_warnings,
                "severity": severity,
            })

        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_import_job(self, job_id: str):
        """Fetch an import job by ID."""
        from app.models.ai_models import AIIngestionJobRecord
        from sqlalchemy import select

        q = select(AIIngestionJobRecord).where(
            AIIngestionJobRecord.job_id == job_id
        )
        result = await self.db.execute(q)
        return result.scalar_one_or_none()


class GenerationError(Exception):
    """Structured error for course generation."""
    def __init__(self, code: str, message: str, http_status: int = 400):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


# ── TRD-CGQ G4 fix: Provider resolution ────────────────────────────────


def _resolve_generation_provider(cfg) -> Any:
    """Resolve the actual LLM provider for provenance tracking.

    TRD-CGQ G4 fix: Previously provider was always labeled "anthropic"
    when an API key was set, even if the actual backend was Ollama
    (via a custom base URL) or DeepSeek. Now we detect from config.

    Priority:
    1. cfg.generation_provider explicit setting ("ollama", "anthropic", "mock")
    2. cfg.primary_model_id lookup in model registry → provider field
    3. anthropic_api_key presence → LLMProvider.ANTHROPIC
    4. Fallback → LLMProvider.MOCK

    Returns LLMProvider enum value.
    """
    from app.services.ai.llm_client import LLMProvider

    # 1. Explicit generation_provider config
    explicit = (getattr(cfg, "generation_provider", "") or "").lower()
    if explicit == "ollama":
        return LLMProvider.OLLAMA
    if explicit == "anthropic":
        return LLMProvider.ANTHROPIC
    if explicit == "mock":
        return LLMProvider.MOCK

    # 2. Check model registry for the primary model's provider
    try:
        model_cfg = cfg.get_model(cfg.primary_model_id)
        if model_cfg and model_cfg.provider:
            provider_name = model_cfg.provider.lower()
            if provider_name == "ollama":
                return LLMProvider.OLLAMA
            if provider_name in ("anthropic", "anthropic"):
                return LLMProvider.ANTHROPIC
    except Exception:
        pass

    # 3. Fall back to API key presence
    if cfg.anthropic_api_key:
        return LLMProvider.ANTHROPIC

    # 4. Default
    return LLMProvider.MOCK
