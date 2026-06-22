"""AI Ingestion Router — US-BKND-AI-016.

File upload and ingestion job endpoints for AI document processing.
"""

import logging
from fastapi import APIRouter, Depends, Request, UploadFile, File, Form
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
    """Request body for propose_page_breakdown."""
    session_id: str = Field(..., min_length=1, max_length=128)
    job_id: str = Field(..., min_length=1, max_length=128)
    max_pages: int = Field(default=50, ge=1, le=100)


class ReviewPagePlanRequest(BaseModel):
    """Request body for review_page_plan."""
    session_id: str = Field(..., min_length=1, max_length=128)
    job_id: str = Field(..., min_length=1, max_length=128)
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
    """
    svc = AIIngestionService(db)
    job = await svc.get_job(job_id)
    if job is None:
        return ai_error("NOT_FOUND", f"Ingestion job '{job_id}' not found.", status=404)
    if job.status != "analyzed":
        return ai_error("INVALID_STATE",
            f"Job must be in 'analyzed' state, currently '{job.status}'.", status=400)

    sections = job.extracted_sections or []
    if not sections:
        return ai_error("NO_CONTENT",
            "No extracted sections found. Upload a document with extractable text.", status=422)

    # Build page plan: each section → one page
    pages = []
    for i, sec in enumerate(sections[:body.max_pages]):
        heading = sec.get("heading", f"Section {i+1}")
        content = sec.get("content_preview", "")
        char_count = sec.get("char_count", 0)

        # Suggest template type based on content hints
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

    # Store plan on job
    job.extracted_sections = {
        "plan": pages,
        "total_sections": len(sections),
        "pages_proposed": len(pages),
        "generated_at": __import__("datetime").datetime.utcnow().isoformat(),
    }
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

    if body.approved:
        # Apply modifications if any
        if body.modifications:
            existing = (job.extracted_sections or {}).get("plan", [])
            updated = _apply_plan_modifications(existing, body.modifications)
            job.extracted_sections = {
                "plan": updated,
                "total_sections": (job.extracted_sections or {}).get("total_sections", 0),
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


def _suggest_template(heading: str, content: str) -> str:
    """Suggest a template type based on content analysis."""
    text = (heading + " " + content).lower()
    if any(w in text for w in ["quiz", "assessment", "test", "question", "score"]):
        return "final-assessment"
    if any(w in text for w in ["tab", "compare", "versus", "vs"]):
        return "tabs"
    if any(w in text for w in ["faq", "question", "answer", "accordion"]):
        return "accordion"
    if any(w in text for w in ["click", "reveal", "discover", "explore"]):
        return "click-reveal"
    return "text-content"


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
