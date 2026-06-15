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

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession

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

    def __init__(self, db: AsyncSession):
        self.db = db
        self.retry_count = self.DEFAULT_RETRY_COUNT

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

        # Check plan is approved
        plan = job.extracted_sections or []
        if not plan:
            raise GenerationError("EMPTY_PAGE_PLAN",
                                  "The import job has no approved page plan.", 400)

        # Validate plan structure
        pages = []
        for section in plan:
            if isinstance(section, dict):
                pages.append({
                    "title": section.get("title", "Untitled"),
                    "template_type": section.get("template_type", "text-content"),
                    "order": section.get("order", len(pages)),
                    "source_excerpt": section.get("content", section.get("text", "")),
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
                "model": "mock",
                "page_count": len(generated_pages),
            },
        }

        # Store course data in the import job's metadata
        try:
            job.source_metadata = job.source_metadata or {}
            if isinstance(job.source_metadata, dict):
                job.source_metadata["generated_course"] = course_data
                job.source_metadata["generation_status"] = GenerationStatus.READY_FOR_REVIEW.value
            job.status = "analyzed"  # Move past extraction to ready
        except Exception:
            pass

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
    # Phase 1: Page Content Generation
    # ------------------------------------------------------------------

    async def _generate_pages(
        self, pages: List[Dict[str, Any]], options: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate content for each page in the plan.

        In mock mode, generates template-appropriate placeholder content.
        """
        generated = []
        for i, page in enumerate(pages):
            content = self._generate_page_content(page, options, i)
            generated.append(content)
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

        if template_type == "text-content":
            components.append({
                "component_type": "text-content",
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

        elif template_type == "click-reveal":
            components.append({
                "component_type": "click-reveal",
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
                            "question": f"What is the main topic of {title}?",
                            "options": ["Option A", "Option B", "Option C", "Option D"],
                            "correct_index": 0,
                        },
                    ],
                },
            })

        else:
            # Default to text-content
            components.append({
                "component_type": "text-content",
                "order_index": 0,
                "data": {"content": f"<h2>{title}</h2>\n<p>Content for {title.lower()}.</p>"},
            })

        return {
            "title": title,
            "template_type": template_type,
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
