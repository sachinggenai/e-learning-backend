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

        # ── TRD-CGQ Phase 2: FeatureDetector integration ──────────
        from app.services.ai.feature_detector import FeatureDetector
        detector = FeatureDetector()
        total = len(pages)
        features_list = [detector.detect(
            p.get("source_excerpt", ""), i, total
        ) for i, p in enumerate(pages)]

        # Pass all page titles into options so assessment generator can use them
        page_titles = [p.get("title", f"Page {i + 1}") for i, p in enumerate(pages)]
        enriched_options = dict(options)
        enriched_options["page_titles"] = page_titles
        enriched_options["_all_pages"] = pages

        generated = []
        for i, page in enumerate(pages):
            features = features_list[i] if i < len(features_list) else None
            content = self._generate_page_content(page, enriched_options, i, features)
            generated.append(content)
        return generated

    async def _generate_pages_with_llm(
        self, pages: List[Dict[str, Any]], options: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate pages using template-specific agents with tier-based routing.

        TRD-CGQ Phase 3A/3D: Pages are grouped by template tier (SMALL/MID/LARGE)
        and each group gets the optimal model + specialized agent.
        Falls back through model escalation chain on failure.
        """
        from app.services.ai.fanout import StreamManager
        from app.services.ai.config import get_ai_config
        from app.services.ai.llm_client import LLMClient
        from app.services.ai.template_tier_router import TemplateTierRouter
        from app.services.ai.agents.template_agents import create_agent_for_template

        cfg = get_ai_config()
        tier_router = TemplateTierRouter(model_registry=cfg)

        # Get JSON repair instance
        json_repair = None
        try:
            from app.services.ai.json_repair import JSONRepair
            json_repair = JSONRepair()
        except Exception:
            pass

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

        # ── Phase 3A: Group pages by template tier ──────────────────
        tier_groups = tier_router.group_pages_by_tier(pages)

        # Process tier groups: LARGE first (assessments), then MID, then SMALL
        all_generated: Dict[int, Dict[str, Any]] = {}  # page_index -> result

        for tier in [tier_router.LARGE, tier_router.MID, tier_router.SMALL]:
            tier_pages = tier_groups.get(tier, [])
            if not tier_pages:
                continue

            tier_page_indices = [idx for idx, _ in tier_pages]
            tier_page_dicts = [p for _, p in tier_pages]
            tier_templates = [templates[i] for i in tier_page_indices]

            model_id = tier_router.get_model_for_tier(tier)
            escalation_chain = getattr(cfg, "model_escalation_chain", ["qwen2.5:7b", "phi3:mini", "mock"])

            # Try models in escalation chain for this tier
            tier_success = False
            last_error = None
            for model_name in escalation_chain:
                if model_name == "mock":
                    break
                try:
                    try:
                        model_cfg = cfg.get_model(model_name)
                    except ValueError:
                        continue

                    provider = _provider_from_model_config(model_cfg)
                    llm_client = LLMClient(
                        provider=provider,
                        model=model_cfg.api_model_name if model_cfg else model_name,
                    )

                    # ── Phase 3D: Template-specific agent ──────────
                    # Use the first page's template type to pick agent
                    primary_ttype = tier_page_dicts[0].get("template_type", "content-text")
                    agent = create_agent_for_template(
                        template_type=primary_ttype,
                        llm_client=llm_client,
                        json_repair=json_repair,
                        max_retries=2,
                    )

                    stream_mgr = StreamManager()
                    result = await stream_mgr.fan_out_pages(
                        job_id=options.get("job_id", f"gen-{id(pages)}"),
                        pages=tier_page_dicts,
                        templates=tier_templates,
                        rag_context=options.get("rag_context", []),
                        course_context=course_context,
                        generate_func=agent.generate_page,
                    )

                    self._last_model_used = model_name
                    self._last_provider_used = model_cfg.provider if model_cfg else "ollama"

                    logger.info(
                        "Tier %s generation complete (model=%s): %d pages, "
                        "%d success, %d fallback, %d error",
                        tier.value, model_name, len(result.pages),
                        sum(1 for p in result.pages if p.status == "success"),
                        sum(1 for p in result.pages if p.status == "fallback"),
                        sum(1 for p in result.pages if p.status == "error"),
                    )

                    # Map results back to original page indices
                    for pr in result.pages:
                        orig_idx = tier_page_indices[pr.page_index] if pr.page_index < len(tier_page_indices) else pr.page_index
                        if pr.status in ("success", "fallback") and pr.data:
                            all_generated[orig_idx] = pr.data
                        else:
                            mock = self._generate_page_content(pages[orig_idx], options, orig_idx)
                            mock["generation_metadata"] = {
                                "fallback": True,
                                "reason": pr.error or f"LLM generation failed on model {model_name}",
                                "method": "mock",
                                "attempted_model": model_name,
                                "tier": tier.value,
                            }
                            all_generated[orig_idx] = mock

                    tier_success = True
                    break

                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "Tier %s generation attempt with %s failed: %s",
                        tier.value, model_name, exc,
                    )
                    continue

            # If tier failed all models, use mock for its pages
            if not tier_success:
                logger.error(
                    "Tier %s failed all models. Last error: %s. Using mock for %d pages.",
                    tier.value, last_error, len(tier_pages),
                )
                for idx, page in tier_pages:
                    mock = self._generate_page_content(page, options, idx)
                    mock["generation_metadata"] = {
                        "fallback": True,
                        "reason": f"Tier {tier.value} failed all models",
                        "method": "mock",
                        "tier": tier.value,
                    }
                    all_generated[idx] = mock

        # Assemble results in original page order
        generated = [all_generated[i] for i in sorted(all_generated.keys())]

        # Log tier routing stats
        stats = tier_router.get_stats()
        logger.info(
            "Template tier routing: %d pages -> SMALL=%d (%.0f%%) MID=%d (%.0f%%) LARGE=%d (%.0f%%)",
            stats["total_pages"],
            stats["routing_counts"].get("small", 0), stats["small_pct"],
            stats["routing_counts"].get("mid", 0), stats["mid_pct"],
            stats["routing_counts"].get("large", 0), stats["large_pct"],
        )

        return generated

    # ═══════════════════════════════════════════════════════════════════
    # Phase 2A: Template-Specific Content Generators (TRD-CGQ §5.4)
    # ═══════════════════════════════════════════════════════════════════

    def _generate_page_content(
        self,
        page: Dict[str, Any],
        options: Dict[str, Any],
        index: int,
        features: Any = None,
    ) -> Dict[str, Any]:
        """Dispatch to the correct template-specific generator.

        TRD-CGQ Phase 2A: Routes each template type to its dedicated generator
        which uses FeatureDetector results to decide on multi-component output.
        """
        template_type = page.get("template_type", "text-content")
        title = page.get("title", f"Page {index + 1}")
        source = page.get("source_excerpt", "")
        all_titles = options.get("page_titles", []) or [
            p.get("title", "") for p in options.get("_all_pages", [])
        ]

        # Accept both old (legacy) and new (canonical) type names
        if template_type in ("text-content", "content-text"):
            return self._build_page(title, template_type, page, index, source,
                self._generate_text_content(title, source, features))
        elif template_type == "accordion":
            return self._build_page(title, template_type, page, index, source,
                self._generate_accordion_content(title, source, features))
        elif template_type == "tabs":
            return self._build_page(title, template_type, page, index, source,
                self._generate_tabs_content(title, source, features))
        elif template_type in ("click-reveal",):
            return self._build_page(title, template_type, page, index, source,
                self._generate_click_reveal_content(title, source, features))
        elif template_type == "final-assessment":
            return self._build_page(title, template_type, page, index, source,
                self._generate_assessment_content(title, source, features, all_titles))
        else:
            # Default to content-text
            return self._build_page(title, template_type, page, index, source,
                self._generate_text_content(title, source, features))

    def _build_page(
        self,
        title: str,
        template_type: str,
        page: Dict[str, Any],
        index: int,
        source: str,
        components: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Assemble a page dict from generated components."""
        from app.models.course import normalize_template_type
        return {
            "title": title,
            "template_type": normalize_template_type(template_type),
            "order": page.get("order", index),
            "components": components,
            "source_excerpt": source[:500] if source else "",
        }

    # ── Text Content ──────────────────────────────────────────────────

    def _generate_text_content(
        self, title: str, source: str, features: Any,
    ) -> List[Dict[str, Any]]:
        """Generate content-text component with optional callout + key takeaways.

        TRD-CGQ Phase 2A: Uses FeatureDetector to decide whether to add
        callout boxes and key-takeaway lists for multi-component output.
        """
        components: List[Dict[str, Any]] = []

        # Main content component
        components.append({
            "component_type": "content-text",
            "order_index": 0,
            "data": {
                "content": (
                    f"<h2>{title}</h2>\n"
                    f"<p>{source[:500] if source else 'Content for ' + title.lower() + '.'}</p>"
                ),
            },
        })

        # Callout box if content has callout pattern
        if features and features.has_callout:
            components.append({
                "component_type": "content-text",
                "order_index": len(components),
                "data": {
                    "content": (
                        f"<div class=\"callout-box\">\n"
                        f"  <h3>Key Takeaway</h3>\n"
                        f"  <p>{source[100:350] if len(source) > 150 else 'The most important concept from this section.'}</p>\n"
                        f"</div>"
                    ),
                },
            })

        # Key takeaways list if section has list patterns or multiple sub-topics
        sub_count = features.sub_topic_count if features else 0
        has_list = features.has_list if features else False
        if has_list or sub_count >= 2:
            points = min(3, max(1, sub_count))
            components.append({
                "component_type": "content-text",
                "order_index": len(components),
                "data": {
                    "content": (
                        f"<h3>Key Points</h3>\n<ul>\n"
                        + "\n".join(
                            f"  <li>Key point {i + 1} related to {title.lower()}</li>"
                            for i in range(points)
                        )
                        + "\n</ul>"
                    ),
                },
            })

        return components

    # ── Accordion ─────────────────────────────────────────────────────

    def _generate_accordion_content(
        self, title: str, source: str, features: Any,
    ) -> List[Dict[str, Any]]:
        """Generate accordion component with detected sub-topics as panels.

        TRD-CGQ Phase 2A: Uses FeatureDetector.sub_topic_count to decide
        number of accordion items. Falls back to a 3-item generic accordion
        when no sub-topics detected.
        """
        items: List[Dict[str, str]] = []
        sub_count = features.sub_topic_count if features else 0

        if sub_count >= 3:
            for i in range(min(sub_count, 6)):
                items.append({
                    "title": f"Topic {i + 1}: {title}",
                    "content": (
                        source[(i * 100):(i * 100 + 200)] if source and len(source) > i * 100
                        else f"Detailed explanation of topic {i + 1} from source material."
                    ),
                })
        else:
            items = [
                {
                    "title": "Overview",
                    "content": f"Introduction to {title} and key concepts.",
                },
                {
                    "title": "Key Details",
                    "content": source[:300] if source else f"Detailed information about {title.lower()}.",
                },
                {
                    "title": "Summary",
                    "content": f"Key takeaways and practical applications of {title.lower()}.",
                },
            ]

        return [{
            "component_type": "accordion",
            "order_index": 0,
            "data": {"items": items},
        }]

    # ── Tabs ──────────────────────────────────────────────────────────

    def _generate_tabs_content(
        self, title: str, source: str, features: Any,
    ) -> List[Dict[str, Any]]:
        """Generate tabs component with parallel sub-topics or procedure steps.

        TRD-CGQ Phase 2A: Procedure steps → Preparation/Step-by-Step/Result tabs.
        Parallel sub-topics → one tab per sub-topic.
        No strong signal → generic Overview/Details/Examples tabs.
        """
        tabs: List[Dict[str, str]] = []
        sub_count = features.sub_topic_count if features else 0
        has_procedure = features.has_procedure_steps if features else False

        if has_procedure:
            tabs = [
                {"title": "Preparation", "content": "What you need before starting this procedure."},
                {"title": "Step-by-Step", "content": source[:400] if source else "Follow these steps in order to complete the task correctly."},
                {"title": "Result", "content": "What you should see after completing all the steps successfully."},
            ]
        elif sub_count >= 2:
            tabs = [
                {
                    "title": f"Aspect {i + 1}",
                    "content": source[(i * 100):(i * 100 + 200)] if source and len(source) > i * 100
                    else f"Content for aspect {i + 1} of {title.lower()}.",
                }
                for i in range(min(sub_count, 5))
            ]
        else:
            tabs = [
                {"title": "Overview", "content": source[:200] if source else f"Introduction to {title.lower()}."},
                {"title": "Details", "content": "More detailed information and examples."},
                {"title": "Examples", "content": "Practical examples and use cases."},
            ]

        return [{
            "component_type": "tabs",
            "order_index": 0,
            "data": {"tabs": tabs},
        }]

    # ── Click-Reveal ──────────────────────────────────────────────────

    def _generate_click_reveal_content(
        self, title: str, source: str, features: Any,
    ) -> List[Dict[str, Any]]:
        """Generate click-reveal component with Q&A pairs.

        When Q&A pattern is detected in the source, extracts question/answer
        pairs. Falls back to generic reveal points.
        """
        items: List[Dict[str, str]] = []
        has_qa = features.has_qa_pattern if features else False

        if has_qa:
            # Extract Q&A-style items from source
            items = [
                {"title": f"Q: What is {title}?",
                 "content": f"A: {source[:200] if source else 'Key concept explanation.'}"},
                {"title": "Q: Why is this important?",
                 "content": "This concept is fundamental to understanding the broader subject matter."},
                {"title": "Q: How does this apply in practice?",
                 "content": "Apply this knowledge by considering real-world scenarios and examples."},
            ]
        else:
            items = [
                {"title": f"Key Point 1: {title}",
                 "content": source[:200] if source else f"First key point about {title.lower()}."},
                {"title": f"Key Point 2: Details",
                 "content": "Additional details and context for deeper understanding."},
            ]

        return [{
            "component_type": "click-reveal",
            "order_index": 0,
            "data": {"items": items},
        }]

    # ── Assessment ────────────────────────────────────────────────────

    def _generate_assessment_content(
        self,
        title: str,
        source: str,
        features: Any,
        all_page_titles: List[str],
    ) -> List[Dict[str, Any]]:
        """Generate assessment with rules-based MCQs (TRD-CGQ Phase 2B / R5).

        Phase 2B: Always generates >= 3 topic-labeled MCQs from page titles.
        Each question references a course topic, with 4 options and feedback.
        Configurable min questions via AI_RULES_BASED_MCQ_MIN_QUESTIONS.

        Args:
            all_page_titles: Titles of all pages in the course (used to
                            generate topic-specific questions).
        """
        from app.services.ai.config import get_ai_config
        cfg = get_ai_config()
        min_questions = getattr(cfg, "rules_based_mcq_min_questions", 3)

        # Use page titles for topic-specific stems; fall back to generic
        topics = [t for t in all_page_titles if t and t != title] if all_page_titles else []
        if not topics:
            topics = [
                "the core concepts",
                "key principles and best practices",
                "practical applications",
                "common challenges and solutions",
                "emerging trends and future directions",
            ]

        questions: List[Dict[str, Any]] = []
        for i in range(max(min_questions, len(topics[:5]))):
            topic = topics[i] if i < len(topics) else f"topic {i + 1}"
            questions.append({
                "id": f"q-{i + 1}",
                "type": "mcq",
                "question": f"Which of the following best describes the main concept of {topic}?",
                "options": [
                    {
                        "id": f"q{i + 1}-a",
                        "text": f"The correct understanding of {topic.lower()}",
                        "isCorrect": True,
                    },
                    {
                        "id": f"q{i + 1}-b",
                        "text": f"A partial understanding that misses key details about {topic.lower()}",
                        "isCorrect": False,
                    },
                    {
                        "id": f"q{i + 1}-c",
                        "text": f"A common misconception related to {topic.lower()}",
                        "isCorrect": False,
                    },
                    {
                        "id": f"q{i + 1}-d",
                        "text": "An unrelated concept from a different domain",
                        "isCorrect": False,
                    },
                ],
                "feedback": f"Review the section on {topic} for a detailed explanation of the correct answer.",
            })

        return [{
            "component_type": "final-assessment",
            "order_index": 0,
            "data": {
                "passing_score": 80,
                "questions": questions,
            },
        }]

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


def _provider_from_model_config(model_cfg: Any) -> Any:
    """Convert a ModelConfig's provider string to an LLMProvider enum.

    Used by model escalation chain to create LLMClient with the correct
    provider for each model in the chain.
    """
    from app.services.ai.llm_client import LLMProvider
    if model_cfg is None:
        return LLMProvider.MOCK
    provider_name = (model_cfg.provider or "").lower()
    if provider_name == "ollama":
        return LLMProvider.OLLAMA
    if provider_name in ("anthropic", "anthropic"):
        return LLMProvider.ANTHROPIC
    return LLMProvider.MOCK
