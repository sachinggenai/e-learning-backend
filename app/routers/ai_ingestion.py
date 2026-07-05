"""AI Ingestion Router — US-BKND-AI-016.

File upload and ingestion job endpoints for AI document processing.
"""

import logging
from fastapi import APIRouter, Body, Depends, Request, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.dependencies.auth_dependencies import get_current_user
from app.models.user_context import UserContext
from app.services.ai.error_envelope import ai_error
from app.services.ai.ingestion_service import AIIngestionService, IngestionError

logger = logging.getLogger("ai_authoring")
router = APIRouter(prefix="/ai", tags=["AI - Ingestion"])


@router.post("/ingestions")
async def upload_document(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    course_id: str = Form(default=""),
    correlation_id: str = Form(default=""),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Upload a document for AI ingestion (US-BKND-AI-016).

    Accepts PDF, DOCX, TXT, MD, ZIP files up to 50MB.
    Returns a job_id for polling extraction progress.
    """
    if not file.filename:
        return ai_error("VALIDATION_ERROR", "No file provided.", status=400)

    try:
        svc = AIIngestionService(db)
        job = await svc.create_job(
            file=file.file,
            filename=file.filename,
            session_id=session_id,
            user_id=user.user_id,
            organization_id=user.organization_id,
            course_id=course_id,
            correlation_id=correlation_id,
        )
    except IngestionError as e:
        return ai_error(code=e.code, message=e.message, status=e.http_status)

    return {
        "status": "ok",
        "job_id": job.job_id,
        "job_status": job.status,
        "progress": job.progress,
        "detected_type": job.detected_type,
        "file_name": job.file_name,
        "file_size": job.file_size,
        "extracted_sections": job.extracted_sections,
        "warnings": job.warnings,
        "source_metadata": job.source_metadata,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


@router.get("/ingestions/{job_id}")
async def get_ingestion_job(
    job_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Poll ingestion job status (US-BKND-AI-016)."""
    svc = AIIngestionService(db)
    job = await svc.get_job(job_id)
    if job is None:
        return ai_error("NOT_FOUND", f"Ingestion job '{job_id}' not found.", status=404)

    return {
        "status": "ok",
        "job_id": job.job_id,
        "job_status": job.status,
        "progress": job.progress,
        "detected_type": job.detected_type,
        "file_name": job.file_name,
        "extracted_sections": job.extracted_sections,
        "warnings": job.warnings,
        "error_message": job.error_message,
        "error_code": job.error_code,
        "source_metadata": job.source_metadata,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


@router.get("/ingestions")
async def list_ingestion_jobs(
    session_id: str = "",
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """List ingestion jobs for a session."""
    svc = AIIngestionService(db)
    jobs = await svc.list_by_session(session_id) if session_id else []

    return {
        "status": "ok",
        "items": [j.to_dict() for j in jobs],
        "total": len(jobs),
    }


# ═══════════════════════════════════════════════════════════════════
# Page breakdown (US-BKND-AI-017)
# ═══════════════════════════════════════════════════════════════════

from pydantic import BaseModel, Field
from typing import Optional as Opt, List


class ProposePageBreakdownRequest(BaseModel):
    """Request body for propose_page_breakdown. job_id is in the URL path."""
    session_id: str = Field(..., min_length=1, max_length=128)
    job_id: str = Field(default="", min_length=0, max_length=128)
    max_pages: int = Field(default=50, ge=1, le=100)


class ReviewPagePlanRequest(BaseModel):
    """Request body for review_page_plan. job_id is in the URL path."""
    session_id: str = Field(..., min_length=1, max_length=128)
    job_id: str = Field(default="", min_length=0, max_length=128)
    approved: bool = Field(default=True)
    modifications: List[dict] = Field(default_factory=list)


@router.post("/ingestions/{job_id}/propose-breakdown")
async def propose_page_breakdown(
    job_id: str,
    body: ProposePageBreakdownRequest,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Generate a page breakdown plan from ingested document sections.

    US-BKND-AI-017: Maps extracted sections to proposed pages with
    suggested template types. For MVP, each section becomes one page.
    The LLM-driven segmentation will be added in US-BKND-AI-023.

    Idempotent: if the job already has a plan (from a prior run), returns
    the existing plan without regenerating.
    """
    svc = AIIngestionService(db)
    job = await svc.get_job(job_id)
    if job is None:
        return ai_error("NOT_FOUND", f"Ingestion job '{job_id}' not found.", status=404)

    # ── Idempotency: return existing plan if already generated ─────
    existing_plan = None
    raw = job.extracted_sections or {}
    if isinstance(raw, dict) and "plan" in raw:
        existing_plan = raw["plan"]

    if existing_plan and job.status in ("completed", "plan_approved", "generated", "page_plan_ready"):
        # Re-transition finished jobs back to page_plan_ready so review-plan accepts them.
        # page_plan_ready jobs stay as-is; everything else resets to page_plan_ready.
        did_reset = False
        if job.status != "page_plan_ready":
            job.status = "page_plan_ready"
            await db.commit()
            did_reset = True
        return {
            "status": "ok",
            "job_id": job.job_id,
            "plan": existing_plan,
            "total_proposed": len(existing_plan),
            "source_sections": raw.get("total_sections", len(existing_plan)),
            "validation": {
                "valid": True,
                "coverage": 1.0,
                "errors": [],
                "warnings": [],
            },
            "idempotent": True,
            "message": (
                "Returning existing plan — status reset to page_plan_ready for re-review."
                if did_reset
                else "Returning existing plan (job already processed)."
            ),
        }

    # ── State guard: only allow regeneration from fresh states ─────
    if job.status not in ("analyzed", "uploaded"):
        return ai_error(
            "INVALID_STATE",
            f"Job must be in 'analyzed' state to propose a breakdown, "
            f"currently '{job.status}'. Upload a new file to start fresh, "
            f"or re-process an existing job by re-uploading the source document.",
            status=400,
        )

    if not raw:
        return ai_error("NO_CONTENT",
            "No extracted sections found. Upload a document with extractable text.", status=422)

    # Resolve sections: prefer dict format, fall back to list
    if isinstance(raw, dict) and "plan" in raw:
        sections = raw["plan"]
    elif isinstance(raw, list):
        sections = raw
    else:
        return ai_error("NO_CONTENT",
            "No extracted sections found. Upload a document with extractable text.", status=422)

    if not isinstance(sections, list) or len(sections) == 0:
        return ai_error("NO_CONTENT",
            "No valid sections in the extracted content.", status=422)

    # Build page plan via LLM with RAG context (falls back to rule-based)
    pages = await _llm_propose_breakdown(sections, max_pages=body.max_pages)

    # Store plan on job and transition state
    job.extracted_sections = {
        "plan": pages,
        "total_sections": len(sections),
        "pages_proposed": len(pages),
        "generated_at": __import__("datetime").datetime.utcnow().isoformat(),
    }
    job.status = "page_plan_ready"
    await db.commit()

    return {
        "status": "ok",
        "job_id": job.job_id,
        "plan": pages,
        "total_proposed": len(pages),
        "source_sections": len(sections),
        "validation": {
            "valid": True,
            "coverage": len(pages) / max(len(sections), 1),
            "errors": [],
            "warnings": _build_plan_warnings(sections, pages),
        },
        "idempotent": False,
    }


@router.post("/ingestions/{job_id}/review-plan")
async def review_page_plan(
    job_id: str,
    body: ReviewPagePlanRequest,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Approve or modify a page breakdown plan (US-BKND-AI-017).

    On approval, locks the plan and transitions the job to 'plan_approved'.
    On rejection, returns the job to 'analyzed' for re-planning.
    """
    svc = AIIngestionService(db)
    job = await svc.get_job(job_id)
    if job is None:
        return ai_error("NOT_FOUND", f"Ingestion job '{job_id}' not found.", status=404)

    # Guard: must be in page_plan_ready (or analyzed for legacy jobs)
    if job.status not in ("page_plan_ready", "analyzed"):
        return ai_error(
            "INVALID_STATE",
            f"Job must be in 'page_plan_ready' state to review, currently '{job.status}'. "
            "Run propose-breakdown first to generate a page plan.",
            status=400,
        )

    if body.approved:
        # Apply modifications if any — resolve existing plan from either format
        if body.modifications:
            raw = job.extracted_sections or {}
            if isinstance(raw, dict) and "plan" in raw:
                existing = raw["plan"]
                total_sections = raw.get("total_sections", len(existing))
            elif isinstance(raw, list):
                existing = raw
                total_sections = len(raw)
            else:
                existing = []
                total_sections = 0

            updated = _apply_plan_modifications(existing, body.modifications)
            job.extracted_sections = {
                "plan": updated,
                "total_sections": total_sections,
                "pages_proposed": len(updated),
                "approved_at": __import__("datetime").datetime.utcnow().isoformat(),
                "approved": True,
            }

        job.status = "plan_approved"
        await db.commit()
        return {
            "status": "ok",
            "job_id": job.job_id,
            "plan_status": "approved",
            "message": "Page plan approved. Ready for content generation.",
        }
    else:
        job.status = "analyzed"  # Return to analyzed for re-planning
        await db.commit()
        return {
            "status": "ok",
            "job_id": job.job_id,
            "plan_status": "rejected",
            "message": "Page plan rejected. You can re-upload or request a new breakdown.",
        }


# ── US-BKND-AI-019: Course Generation Endpoints ──────────────────

from pydantic import BaseModel as PydanticBaseModel, Field as PydanticField


class GenerateCourseRequest(PydanticBaseModel):
    import_job_id: str = PydanticField(..., min_length=1)
    course_id: str = PydanticField(default="")
    options: dict = PydanticField(default_factory=dict)


class ApplyCourseRequest(PydanticBaseModel):
    idempotency_key: str = PydanticField(
        default="",
        description="Optional idempotency key for safe retry. Auto-generated if omitted.",
    )


@router.post("/generate-course")
async def generate_course(
    body: GenerateCourseRequest,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Generate a full course from an approved page plan (US-BKND-AI-019).

    Initiates course generation from the approved page plan in an import job.
    Returns the generation result with course preview data.
    """
    from app.services.ai.course_generator import CourseGenerator, GenerationError

    try:
        gen = CourseGenerator(db)
        result = await gen.start_generation(
            import_job_id=body.import_job_id,
            session_id="",
            user_id=user.user_id,
            organization_id=user.organization_id,
            course_id=body.course_id,
            options=body.options,
        )
    except GenerationError as e:
        return ai_error(e.code, e.message, status=e.http_status)

    return {"status": "ok", **result}


@router.get("/generate-course/{import_job_id}")
async def get_generation_status(
    import_job_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Get the status of a course generation job (US-BKND-AI-019)."""
    from app.services.ai.course_generator import CourseGenerator, GenerationError

    try:
        gen = CourseGenerator(db)
        result = await gen.get_job_status(import_job_id)
    except GenerationError as e:
        return ai_error(e.code, e.message, status=e.http_status)

    return {"status": "ok", **result}


@router.post("/generate-course/{import_job_id}/apply")
async def apply_generated_course(
    import_job_id: str,
    body: ApplyCourseRequest = Body(default=None),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Apply a generated course — creates Course, Pages, and Components (US-BKND-AI-019).

    Commits all generated pages and components to the database in a single
    transaction. Marks the import job as completed on success.

    Supports idempotency via optional `idempotency_key` in the request body.
    If omitted, a deterministic key is derived from import_job_id + user_id.
    """
    from app.services.ai.course_generator import CourseGenerator, GenerationError
    from app.services.ai.idempotency_service import IdempotencyService

    # Resolve idempotency key (caller-provided or auto-generated)
    effective_key = (
        body.idempotency_key if body and body.idempotency_key
        else IdempotencyService.generate_key(import_job_id, user.user_id)
    )

    idem_svc = IdempotencyService(db)

    # 1. Check for cached result
    cached = await idem_svc.check(effective_key, user.user_id, "")
    if cached is not None:
        logger.info("Idempotency hit for apply job %s", import_job_id[:8])
        return {"status": "ok", "cached": True, **cached}

    # 2. Execute apply
    try:
        gen = CourseGenerator(db)
        result = await gen.apply_generated_course(
            import_job_id=import_job_id,
            user_id=user.user_id,
            organization_id=user.organization_id,
        )
    except GenerationError as e:
        return ai_error(e.code, e.message, status=e.http_status)
    except Exception:
        logger.exception("Failed to apply generated course for job %s", import_job_id)
        return ai_error("SERVER_ERROR",
            "An unexpected error occurred while applying the course.", status=503)

    # 3. Store idempotency result (first-write-wins)
    try:
        await idem_svc.store(effective_key, user.user_id, "", result, status=200)
    except Exception:
        logger.warning("Failed to store idempotency key for apply job %s", import_job_id[:8])

    return {"status": "ok", "cached": False, **result}


# ── Phase 1.4: Parallel Generation Endpoint ─────────────────────────

class ParallelGenerateRequest(PydanticBaseModel):
    import_job_id: str = PydanticField(..., min_length=1)
    course_id: str = PydanticField(default="")
    concurrency: int = PydanticField(default=3, ge=1, le=10)
    options: dict = PydanticField(default_factory=dict)


@router.post("/generate-course/parallel")
async def generate_course_parallel(
    body: ParallelGenerateRequest,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Generate a full course using parallel page generation (Phase 1.4).

    Uses Redis Streams for fan-out when Redis is available, or asyncio.gather
    with semaphore as fallback. N pages generate concurrently (configurable
    via concurrency parameter or AI_GENERATION_CONCURRENCY env var).

    Returns immediately with the result — generation is synchronous in the
    HTTP request (typically 1-2 min for a 30-page course vs 8-15 min sequential).
    For truly async execution, use the workflow endpoints.
    """
    from app.services.ai.course_generator import CourseGenerator, GenerationError
    from app.services.ai.fanout import StreamManager

    logger.info(
        "Parallel generation requested: job=%s user=%s concurrency=%d",
        body.import_job_id, user.user_id, body.concurrency,
    )

    # Override concurrency for this run
    import os as _os
    _os.environ["AI_GENERATION_CONCURRENCY"] = str(body.concurrency)

    try:
        gen = CourseGenerator(db, use_llm=True)
        result = await gen.start_generation(
            import_job_id=body.import_job_id,
            session_id="",
            user_id=user.user_id,
            organization_id=user.organization_id,
            course_id=body.course_id,
            options={"job_id": body.import_job_id, **body.options},
        )
    except GenerationError as e:
        return ai_error(e.code, e.message, status=e.http_status)

    return {"status": "ok", "mode": "parallel", "concurrency": body.concurrency, **result}


async def _llm_propose_breakdown(
    sections: list, max_pages: int = 50
) -> list:
    """Propose page breakdown using heuristics-first, LLM-enhanced approach.

    TRD-CGQ Phase 2C: Uses FeatureDetector + TemplateSelector as primary path.
    Confident sections (score margin >= 0.3) use heuristic result directly.
    Ambiguous sections get LLM refinement with model escalation.

    Falls back to rule-based breakdown if both heuristics and LLM are unavailable.
    """
    if not sections:
        return []

    # ── Phase 2C: Heuristics-first template selection ─────────────
    try:
        heuristic_pages = _heuristic_breakdown(sections, max_pages)
        if heuristic_pages:
            # Count ambiguous pages that need LLM refinement
            ambiguous_count = sum(
                1 for p in heuristic_pages if p.get("needs_llm_refinement")
            )
            if ambiguous_count == 0:
                logger.info(
                    "All %d pages resolved via heuristics — no LLM needed",
                    len(heuristic_pages),
                )
                return heuristic_pages

            logger.info(
                "%d/%d pages need LLM refinement for ambiguous templates",
                ambiguous_count, len(heuristic_pages),
            )
            # --- TRD-CGQ Phase 3B: LLM refinement for ambiguous pages ---
            try:
                refined = await _llm_refine_ambiguous(heuristic_pages, sections)
                if refined and len(refined) > 0:
                    return refined
            except Exception as exc:
                logger.warning("LLM refinement failed: %s — using heuristic results", exc)

            # Clear the needs_llm_refinement flag since we're using heuristics
            for p in heuristic_pages:
                p.pop("needs_llm_refinement", None)
            return heuristic_pages
    except Exception as exc:
        logger.warning("Heuristic breakdown failed: %s — falling back to LLM", exc)

    # ── LLM path (backward compatible) ────────────────────────────
    try:
        pages = await _call_llm_for_breakdown(sections, max_pages)
        if pages and len(pages) > 0:
            return pages
    except Exception:
        pass  # Fall through to rule-based

    # Fallback: rule-based breakdown
    return _rule_based_breakdown(sections, max_pages)


async def _call_llm_for_breakdown(sections: list, max_pages: int) -> list:
    """Call LLM via MCP Gateway to propose page breakdown."""
    import json as _json

    # Build template schema context
    template_schemas = _get_template_schemas()

    # Build RAG context from similar courses
    rag_context = await _get_rag_context(sections)

    # Build prompt
    sections_text = ""
    for i, sec in enumerate(sections[:max_pages * 2]):  # Allow merging
        if not isinstance(sec, dict):
            continue
        heading = sec.get("heading") or sec.get("proposed_title") or f"Section {i+1}"
        preview = sec.get("content_preview") or sec.get("content", "")[:500]
        chars = sec.get("char_count", len(preview))
        sections_text += (
            f"--- Section {i} ({chars} chars) ---\n"
            f"Heading: {heading}\n"
            f"Content: {preview}\n\n"
        )

    rag_text = ""
    if rag_context:
        rag_text = "\nSIMILAR COURSES (for structure reference):\n"
        for c in rag_context[:3]:
            ttypes = c.get("template_breakdown", {})
            rag_text += (
                f"- {c.get('title', '')}: {c.get('page_count', 0)} pages, "
                f"templates: {ttypes}\n"
            )

    prompt = (
        f"You are an instructional design expert. Analyze the following document "
        f"sections and create an optimal page breakdown for an e-learning course.\n\n"
        f"AVAILABLE TEMPLATE TYPES:\n{_json.dumps(template_schemas, indent=2)}\n\n"
        f"{rag_text}\n"
        f"DOCUMENT SECTIONS:\n{sections_text}\n"
        f"INSTRUCTIONS:\n"
        f"1. Generate a descriptive title for each page (NOT the filename)\n"
        f"2. Choose the best template type from the available list\n"
        f"3. Merge very small sections (<200 chars) with adjacent sections\n"
        f"4. Split very large sections (>5000 chars) into multiple pages\n"
        f"5. Ensure at least one page uses final-assessment if quiz/test content exists\n"
        f"6. Maximum {max_pages} pages total\n"
        f"7. Provide a brief rationale for each template choice\n\n"
        f"Return ONLY a JSON array:\n"
        f'[{{"title": "...", "template_type": "...", "rationale": "...", '
        f'"source_section_ids": [0,1], "order": 0}}, ...]\n'
    )

    # Call LLM via MCP Gateway with model escalation (TRD-CGQ Phase 2C / P6)
    import httpx
    breakdown_models = _get_breakdown_model_chain()
    last_error = None

    for attempt, model_name in enumerate(breakdown_models):
        if model_name == "mock":
            raise ValueError("Breakdown model chain exhausted") from last_error
        try:
            async with httpx.AsyncClient(timeout=120.0) as http:
                resp = await http.post(
                    "http://localhost:8004/v1/chat/completions",
                    json={
                        "model": model_name,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 8192,  # Large JSON needs headroom
                        "temperature": 0.3,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            break  # Success — exit escalation loop
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Breakdown LLM attempt %d failed (model=%s): %s",
                attempt + 1, model_name, exc,
            )
            continue
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    # Extract JSON from response
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]
    # Repair truncated JSON (LLM may hit token limit mid-JSON)
    content = content.strip()
    if content and not content.endswith("]"):
        # Try to close the array gracefully
        last_good = max(
            content.rfind('"}'), content.rfind('"}],'), content.rfind('}]')
        )
        if last_good > 0:
            content = content[:last_good + 2] + "\n]"
    if content and content.startswith("[") and content.rstrip().endswith("]"):
        content = content[content.index("["):content.rindex("]") + 1]

    plan = _json.loads(content)
    if not isinstance(plan, list) or len(plan) == 0:
        raise ValueError("LLM returned invalid plan structure")

    # Normalize LLM field names → storage format
    for i, page in enumerate(plan):
        # LLM returns: title, template_type, rationale, source_section_ids, order
        page["proposed_title"] = (
            page.get("proposed_title") or page.get("title") or f"Page {i+1}"
        )
        page["suggested_template_type"] = (
            page.get("suggested_template_type") or page.get("template_type")
            or page.get("type") or "content-text"
        )
        page["rationale"] = page.get("rationale") or page.get("reason", "")
        page.setdefault("order", page.get("order", i))
        page.setdefault("char_count", page.get("char_count", 0))
        page.setdefault("source_section_ids", page.get("source_section_ids", [str(i)]))
        if "content_preview" not in page:
            sids = page.get("source_section_ids", [str(i)])
            previews = []
            for sid in sids:
                idx = int(sid) if str(sid).isdigit() else i
                if 0 <= idx < len(sections):
                    sec = sections[idx]
                    previews.append(
                        sec.get("content_preview") or sec.get("content", "")
                    )
            page["content_preview"] = " ".join(previews)[:200]

    return plan


def _get_template_schemas() -> dict:
    """Return available template types with FULL component schemas.

    Loads from TEMPLATE_SCHEMAS in content_generator_agent so the LLM
    sees exact component structure requirements for each template type.
    Falls back to descriptions if schemas unavailable.
    """
    try:
        from app.services.ai.agents.content_generator_agent import TEMPLATE_SCHEMAS
        return dict(TEMPLATE_SCHEMAS)  # Full component schemas
    except ImportError:
        pass

    # Fallback: rich descriptions (used when agent module not available)
    return {
        "content-text": {
            "description": "Rich text page with headings, paragraphs, lists. Best for explanatory content, definitions, theory.",
            "typical_use": "Topic explanations, concept definitions, theory pages",
            "min_content_chars": 200,
            "components": [{"component_type": "content-text", "order_index": 0,
                "data": {"content": "<h2>Title</h2><p>Educational body text with definitions, examples, key takeaways.</p>"}}]
        },
        "tabs": {
            "description": "Tabbed layout with 2-6 tabs. Best for comparing options, organizing subtopics, step-by-step guides.",
            "typical_use": "Comparisons, multi-perspective topics, process steps",
            "min_content_chars": 500,
            "components": [{"component_type": "tabs", "order_index": 0,
                "data": {"tabs": [{"title": "Tab 1", "content": "Content for first tab..."},
                                   {"title": "Tab 2", "content": "Content for second tab..."}]}}]
        },
        "accordion": {
            "description": "Expandable Q&A or topic sections with 2-20 items. Best for FAQs, detailed breakdowns, progressive disclosure.",
            "typical_use": "FAQs, detailed topic breakdowns, knowledge checks",
            "min_content_chars": 400,
            "components": [{"component_type": "accordion", "order_index": 0,
                "data": {"items": [{"title": "Question or topic 1", "content": "Expanded answer or detail..."}]}}]
        },
        "click-reveal": {
            "description": "Interactive reveal elements with 2-10 items. Best for discovery learning, key points, scenario exploration.",
            "typical_use": "Discovery activities, key point reveals, scenario walkthroughs",
            "min_content_chars": 300,
            "components": [{"component_type": "accordion", "order_index": 0,
                "data": {"items": [{"title": "Reveal point 1", "content": "Hidden detail..."}]}}]
        },
        "final-assessment": {
            "description": "Graded quiz with 3-50 questions (MCQ, true/false, etc). Best for end-of-course assessment, knowledge validation.",
            "typical_use": "End-of-course tests, knowledge checks, certification exams",
            "min_content_chars": 300,
            "components": [{"component_type": "final-assessment", "order_index": 0,
                "data": {"passing_score": 80,
                    "questions": [{"id": "q-1", "type": "mcq", "question": "Question text?",
                        "options": [{"id": "a", "text": "Correct answer", "isCorrect": True},
                                     {"id": "b", "text": "Wrong answer", "isCorrect": False}],
                        "feedback": "Explanation here."}]}}]
        },
    }


async def _get_rag_context(sections: list) -> list:
    """Retrieve similar course structures from RAG for context.

    Uses the embedding provider + pgvector directly (not the full service)
    to avoid session dependency during breakdown.
    """
    try:
        import httpx
        from app.services.ai.embedding_provider import get_embedding_provider
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text
        import os

        query = " ".join([
            s.get("heading", "") or s.get("proposed_title", "") or ""
            for s in sections[:3] if isinstance(s, dict)
        ])[:500]

        if not query.strip():
            return []

        # Get embedding
        provider = get_embedding_provider()
        vec = await provider.embed(query)
        vec_str = "[" + ",".join(f"{v:.8f}" for v in vec) + "]"

        db_url = os.getenv("DATABASE_URL", "")
        if not db_url:
            return []

        engine = create_async_engine(db_url)
        async with engine.connect() as conn:
            r = await conn.execute(text(
                "SELECT c.course_id, c.title, "
                "1 - (ce.embedding <=> CAST(:qv AS vector)) AS similarity "
                "FROM course_embeddings ce "
                "JOIN courses c ON c.id = ce.course_record_id "
                "WHERE NOT ce.is_stale "
                "ORDER BY ce.embedding <=> CAST(:qv AS vector) LIMIT 3"
            ), {"qv": vec_str})
            rows = [(r[0], r[1], float(r[2])) for r in r]

        await engine.dispose()
        return [
            {"courseId": cid, "title": title, "relevance_score": score}
            for cid, title, score in rows if score > 0.3
        ]
    except Exception:
        return []


def _rule_based_breakdown(sections: list, max_pages: int) -> list:
    """Fallback: rule-based one-section-per-page breakdown.

    TRD-CGQ Phase 2C: Uses TemplateSelector for smarter template assignment.
    Falls back to simple _suggest_template() on any error.
    """
    try:
        from app.services.ai.feature_detector import FeatureDetector
        from app.services.ai.template_selector import TemplateSelector
        detector = FeatureDetector()
        selector = TemplateSelector()
        total = max(len(sections), 1)

        pages = []
        for i, sec in enumerate(sections[:max_pages]):
            if not isinstance(sec, dict):
                continue
            heading = sec.get("heading") or sec.get("proposed_title") or f"Section {i + 1}"
            content = sec.get("content_preview") or sec.get("content", "")
            char_count = sec.get("char_count", 0)

            # Use TemplateSelector for better template assignment
            features = detector.detect(content, i, total)
            best = selector.select(features)

            pages.append({
                "proposed_title": heading[:200],
                "suggested_template_type": best.template_type,
                "rationale": (
                    f"Section '{heading[:80]}' ({char_count} chars) mapped to "
                    f"{best.template_type}. {best.reasoning}"
                ),
                "source_section_ids": [str(i)],
                "order": i,
                "char_count": char_count,
                "content_preview": content[:200],
            })
        return pages
    except Exception:
        # Ultimate fallback: original _suggest_template approach
        pages = []
        for i, sec in enumerate(sections[:max_pages]):
            if not isinstance(sec, dict):
                continue
            heading = sec.get("heading") or sec.get("proposed_title") or f"Section {i + 1}"
            content = sec.get("content_preview") or sec.get("content", "")
            char_count = sec.get("char_count", 0)
            suggested = _suggest_template(heading, content)
            pages.append({
                "proposed_title": heading[:200],
                "suggested_template_type": suggested,
                "rationale": f"Section '{heading[:80]}' ({char_count} chars) mapped to {suggested}.",
                "source_section_ids": [str(i)],
                "order": i,
                "char_count": char_count,
                "content_preview": content[:200],
            })
        return pages


def _suggest_template(heading: str, content: str) -> str:
    """Suggest a template type based on content analysis.

    Returns canonical BUILTIN_TEMPLATE_TYPES only.
    Kept for backward compatibility — prefer TemplateSelector for new code.
    """
    text = (heading + " " + content).lower()
    if any(w in text for w in ["quiz", "assessment", "test", "question", "score"]):
        return "final-assessment"
    if any(w in text for w in ["tab", "compare", "versus", "vs"]):
        return "tabs"
    if any(w in text for w in ["faq", "question", "answer", "accordion"]):
        return "accordion"
    if any(w in text for w in ["click", "reveal", "discover", "explore"]):
        return "accordion"  # click-reveal → accordion (canonical)
    return "content-text"   # was "text-content"


# ── TRD-CGQ Phase 2C: Breakdown model resolution ──────────────────────


def _get_breakdown_model_chain() -> list:
    """Return the model escalation chain for breakdown/classification.

    TRD-CGQ Phase 2C / P6: Tries models in order; first success wins.
    "mock" signals final fallback to rule-based breakdown.
    Uses the same chain as content generation by default.
    """
    try:
        from app.services.ai.config import get_ai_config
        cfg = get_ai_config()
        chain = getattr(cfg, "model_escalation_chain", ["qwen2.5:7b", "phi3:mini", "mock"])
        if isinstance(chain, list) and chain:
            return list(chain)
    except Exception:
        pass
    return ["qwen2.5:7b", "phi3:mini", "mock"]


# ── TRD-CGQ Phase 3B: LLM refinement for ambiguous templates ─────────


async def _llm_refine_ambiguous(heuristic_pages: list, sections: list) -> list:
    """Refine ambiguous template assignments using LLM.

    Only sends ambiguous pages (needs_llm_refinement=True) to the LLM.
    Confident pages retain their heuristic assignment.

    Returns merged list with LLM-refined + heuristic pages.
    """
    ambiguous_indices = [
        i for i, p in enumerate(heuristic_pages)
        if p.get("needs_llm_refinement")
    ]
    if not ambiguous_indices:
        return heuristic_pages

    logger.info(
        "LLM refinement: %d ambiguous pages out of %d total",
        len(ambiguous_indices), len(heuristic_pages),
    )

    try:
        from app.services.ai.template_selector import TemplateSelector
        from app.services.ai.feature_detector import FeatureDetector
        from app.services.ai.llm_client import LLMClient, LLMProvider

        detector = FeatureDetector()

        # Use a small model for classification
        try:
            from app.services.ai.config import get_ai_config
            cfg = get_ai_config()
            refinement_model = getattr(cfg, "template_selector_model", "phi3:mini")
            model_cfg = cfg.get_model(refinement_model)
            provider_name = model_cfg.provider.lower() if model_cfg else "ollama"
            if provider_name == "ollama":
                provider = LLMProvider.OLLAMA
            elif provider_name == "anthropic":
                provider = LLMProvider.ANTHROPIC
            else:
                provider = LLMProvider.MOCK
        except Exception:
            provider = LLMProvider.MOCK
            refinement_model = "mock"

        if provider == LLMProvider.MOCK:
            logger.info("No LLM available for refinement — keeping heuristic assignments")
            for p in heuristic_pages:
                p.pop("needs_llm_refinement", None)
            return heuristic_pages

        llm_client = LLMClient(provider=provider, model=refinement_model)
        selector = TemplateSelector(llm_client=llm_client)

        for idx in ambiguous_indices:
            page = heuristic_pages[idx]
            section_idx = page.get("source_section_ids", [str(idx)])
            sid = int(section_idx[0]) if section_idx and str(section_idx[0]).isdigit() else idx

            if 0 <= sid < len(sections):
                sec = sections[sid]
                if isinstance(sec, dict):
                    content = sec.get("content") or sec.get("content_preview", "")
                    features = detector.detect(content, idx, max(len(heuristic_pages), 1))

                    # Get top candidates for the LLM to choose from
                    candidates = selector.score_all(features)[:3]
                    if len(candidates) >= 2:
                        best = await selector.llm_refine(features, candidates, content)
                        page["suggested_template_type"] = best.template_type
                        page["rationale"] = (
                            f"LLM-refined: {best.reasoning} "
                            f"(score={best.score:.2f}, confidence={best.confidence:.2f})"
                        )

            page.pop("needs_llm_refinement", None)

        logger.info("LLM refinement complete for %d ambiguous pages", len(ambiguous_indices))
        return heuristic_pages

    except Exception as exc:
        logger.warning("LLM refinement batch failed: %s — keeping heuristic assignments", exc)
        for p in heuristic_pages:
            p.pop("needs_llm_refinement", None)
        return heuristic_pages


# ── TRD-CGQ Phase 2C: Heuristic breakdown ────────────────────────────


def _heuristic_breakdown(sections: list, max_pages: int = 50) -> list:
    """Generate page breakdown using FeatureDetector + TemplateSelector.

    TRD-CGQ Phase 2C: ZERO-LLM path with section merging per TRD §5.5.
    Merging rules:
      1. Consecutive "Tab N —" sections under a parent PAGE → merge into 1 page
      2. Consecutive "Section N —" / FAQ items under a parent → merge into 1 page
      3. Consecutive "Question N" items under an assessment parent → merge into 1 page
      4. Sections < 200 chars merge with next section
      5. Sections sharing same source_section_ids → dedup
    """

    from app.services.ai.feature_detector import FeatureDetector
    from app.services.ai.template_selector import TemplateSelector

    detector = FeatureDetector()
    selector = TemplateSelector()
    total = max(len(sections), 1)

    # --- Step 1: Detect parent/child relationships ---
    # A "parent" section is a PAGE header (PAGE X — ...) or has template metadata
    # Children follow the parent until the next parent section

    import re
    _PARENT_PAGE_RE = re.compile(r'^PAGE\s+\d+\s*[\—\-–]', re.IGNORECASE)
    _TAB_CHILD_RE = re.compile(r'^Tab\s+\d+\s*[\—\-–]', re.IGNORECASE)
    _SECTION_CHILD_RE = re.compile(r'^Section\s+\d+\s*[\—\-–]', re.IGNORECASE)
    _SLIDE_CHILD_RE = re.compile(r'^Slide\s+\d+\s*[\—\-–]', re.IGNORECASE)
    _QUESTION_RE = re.compile(r'^Question\s+\d+', re.IGNORECASE)

    # Build merged groups: list of (merged_heading, merged_template, [section_indices])
    merged_groups = []
    current_group_indices = []
    current_parent_heading = None
    current_parent_template = None
    is_assessment_group = False

    for i, sec in enumerate(sections[:max_pages]):
        if not isinstance(sec, dict):
            continue

        heading = sec.get("heading", "")
        content = sec.get("content") or sec.get("content_preview", "")
        char_count = sec.get("char_count", len(content))

        is_parent = bool(_PARENT_PAGE_RE.match(heading))
        is_tab = bool(_TAB_CHILD_RE.match(heading))
        is_section = bool(_SECTION_CHILD_RE.match(heading))
        is_slide = bool(_SLIDE_CHILD_RE.match(heading))
        is_question = bool(_QUESTION_RE.match(heading))

        # Detect assessment group from parent heading
        if is_parent and ("assessment" in heading.lower() or "quiz" in heading.lower()):
            is_assessment_group = True
        elif is_parent:
            is_assessment_group = False

        # Start a new group when we hit a parent section
        if is_parent:
            # Flush previous group
            if current_group_indices:
                merged_groups.append({
                    "heading": current_parent_heading or "Untitled Page",
                    "indices": current_group_indices,
                    "is_assessment": is_assessment_group,
                    "child_type": _detect_child_type(current_group_indices, sections),
                })
            current_group_indices = [i]
            current_parent_heading = heading
            current_parent_template = None  # Will be detected from features
        elif is_tab or is_section or is_slide or is_question:
            # Child section — belongs to current parent group
            current_group_indices.append(i)
        else:
            # Standalone section — if current group exists and this looks new, flush
            if current_group_indices and not is_tab and not is_section and not is_slide and not is_question:
                # Check if this is a new standalone topic
                if char_count > 100 and not heading.startswith(("—", "-", "—")):
                    merged_groups.append({
                        "heading": current_parent_heading or "Untitled Page",
                        "indices": current_group_indices,
                        "is_assessment": is_assessment_group,
                        "child_type": _detect_child_type(current_group_indices, sections),
                    })
                    current_group_indices = [i]
                    current_parent_heading = heading
                    is_assessment_group = False
                else:
                    current_group_indices.append(i)
            else:
                current_group_indices.append(i)

    # Flush final group
    if current_group_indices:
        merged_groups.append({
            "heading": current_parent_heading or sections[current_group_indices[0]].get("heading", "Untitled Page"),
            "indices": current_group_indices,
            "is_assessment": is_assessment_group,
            "child_type": _detect_child_type(current_group_indices, sections),
        })

    # --- Step 2: Merge small standalone groups ---
    # Groups with < 200 chars merge with the next group
    merged_groups = _merge_small_groups(merged_groups, sections)

    # --- Step 3: Build pages from merged groups ---
    pages = []
    for gidx, group in enumerate(merged_groups):
        indices = group["indices"]
        if not indices:
            continue

        # Determine template from the parent (first) section
        parent_sec = sections[indices[0]]
        parent_heading = group["heading"]
        parent_content = parent_sec.get("content") or parent_sec.get("content_preview", "")
        combined_content = " ".join(
            (sections[j].get("content") or sections[j].get("content_preview", ""))
            for j in indices if isinstance(sections[j], dict)
        )
        total_chars = sum(
            sections[j].get("char_count", 0)
            for j in indices if isinstance(sections[j], dict)
        )

        features = detector.detect(combined_content, gidx, max(len(merged_groups), 1))
        best, needs_llm = selector.select_with_confidence(features)

        # Override template for known group types
        suggested_template = best.template_type
        if group.get("child_type") == "tabs" and suggested_template == "content-text":
            suggested_template = "tabs"
        elif group.get("child_type") == "accordion" and suggested_template == "content-text":
            suggested_template = "accordion"
        elif group.get("is_assessment"):
            suggested_template = "final-assessment"

        # Build merged source_section_ids
        source_ids = [str(j) for j in indices]

        pages.append({
            "proposed_title": parent_heading[:200],
            "suggested_template_type": suggested_template,
            "rationale": (
                f"{best.reasoning} (score={best.score:.2f}, "
                f"confidence={best.confidence:.2f}, method={best.method}, "
                f"merged={len(indices)} sections, {total_chars} total chars)"
            ),
            "source_section_ids": source_ids,
            "order": gidx,
            "char_count": total_chars,
            "content_preview": combined_content[:200],
            "needs_llm_refinement": needs_llm,
            "merged_sections": len(indices),
        })

    return pages


def _detect_child_type(indices: list, sections: list) -> str:
    """Detect whether child sections form tabs, accordion, or assessment content."""
    if not indices or len(indices) < 2:
        return "single"

    headings = [
        sections[i].get("heading", "")
        for i in indices if i < len(sections) and isinstance(sections[i], dict)
    ]
    headings_lower = " ".join(headings).lower()

    import re
    if any(re.match(r'^Tab\s+\d+', h, re.IGNORECASE) for h in headings):
        return "tabs"
    if any(re.match(r'^Section\s+\d+', h, re.IGNORECASE) for h in headings):
        return "accordion"
    if any(re.match(r'^Question\s+\d+', h, re.IGNORECASE) for h in headings):
        return "assessment"
    if "assessment" in headings_lower or "quiz" in headings_lower:
        return "assessment"
    if any(re.match(r'^Slide\s+\d+', h, re.IGNORECASE) for h in headings):
        return "accordion"

    return "single"


def _merge_small_groups(groups: list, sections: list) -> list:
    """Merge groups with < 200 total chars into adjacent groups."""
    if len(groups) <= 1:
        return groups

    merged = []
    skip_next = False

    for i, group in enumerate(groups):
        if skip_next:
            skip_next = False
            continue

        total_chars = sum(
            sections[j].get("char_count", 0)
            for j in group["indices"]
            if j < len(sections) and isinstance(sections[j], dict)
        )

        # Merge small groups with the next group
        if total_chars < 200 and i + 1 < len(groups):
            next_group = groups[i + 1]
            merged.append({
                "heading": group["heading"],
                "indices": group["indices"] + next_group["indices"],
                "is_assessment": group["is_assessment"] or next_group["is_assessment"],
                "child_type": group.get("child_type") or next_group.get("child_type", "single"),
            })
            skip_next = True
        else:
            merged.append(group)

    return merged


def _build_plan_warnings(sections: list, pages: list) -> list:
    """Build warnings for the page plan."""
    warnings = []
    if len(pages) > 50:
        warnings.append("Large course detected. Consider merging sections.")
    # Check for very short sections
    for s in sections:
        if s.get("char_count", 0) < 50:
            warnings.append(f"Very short section: '{s.get('heading', 'untitled')[:60]}'")
    return warnings[:10]


def _apply_plan_modifications(plan: list, mods: list) -> list:
    """Apply user modifications to the page plan."""
    for mod in mods:
        action = mod.get("action", "")
        idx = mod.get("index", -1)
        if action == "retitle" and 0 <= idx < len(plan):
            plan[idx]["proposed_title"] = mod.get("title", plan[idx]["proposed_title"])
        elif action == "change_template" and 0 <= idx < len(plan):
            plan[idx]["suggested_template_type"] = mod.get("template_type", plan[idx]["suggested_template_type"])
        elif action == "merge" and idx >= 0:
            # Simple merge: append next page's sections
            if idx + 1 < len(plan):
                plan[idx]["source_section_ids"].extend(plan[idx + 1]["source_section_ids"])
                plan[idx]["content_preview"] += " | " + plan[idx + 1].get("content_preview", "")
                plan.pop(idx + 1)
    return plan
