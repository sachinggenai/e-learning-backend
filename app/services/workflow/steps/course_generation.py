"""Step executors for the 'course_generation' workflow type — US-BKND-AI-034.

States: validate_input -> generate_pages -> validate_course -> create_batch_proposal -> complete

Uses shared StepRegistry singleton via get_default_registry().
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from app.services.workflow.step_registry import get_default_registry
from app.services.workflow.types import StepResult

registry = get_default_registry()


# ═══════════════════════════════════════════════════════════════════
# State: validate_input
# ═══════════════════════════════════════════════════════════════════

@registry.register("course_generation", "validate_input")
async def validate_input_step(
    job_id: uuid.UUID,
    input_data: Dict[str, Any],
    checkpoint: Dict[str, Any],
    logger: logging.Logger,
    step_config: Dict[str, Any],
) -> StepResult:
    """Validate that import_job_id exists and is plan_approved."""
    import_job_id = input_data.get("import_job_id")
    if not import_job_id:
        return StepResult(
            success=False,
            error={"code": "MISSING_INPUT", "message": "import_job_id is required"},
        )

    from app.db.config import SessionLocal
    from app.repositories.import_job_repository import ImportJobRepository

    async with SessionLocal() as session:
        repo = ImportJobRepository(session)
        job = await repo.get_by_id(import_job_id)
        if not job:
            return StepResult(
                success=False,
                error={"code": "IMPORT_JOB_NOT_FOUND",
                       "message": f"No import job with id {import_job_id}"},
            )
        if job.status != "plan_approved":
            return StepResult(
                success=False,
                error={"code": "INVALID_IMPORT_STATUS",
                       "message": f"Import job status is '{job.status}', expected 'plan_approved'"},
            )

        result_data = getattr(job, "result_data", None) or {}
        pages = result_data.get("pages", [])
        checkpoint["import_job"] = {
            "job_id": import_job_id,
            "course_id": getattr(job, "course_id", ""),
            "pages": pages,
            "course_metadata": result_data.get("courseMetadata", {}),
        }
        checkpoint["pages_state"] = {
            "total": len(pages),
            "generated": 0,
            "failed": 0,
            "results": [],
        }

    return StepResult(success=True, checkpoint_data=checkpoint, progress=0.05)


# ═══════════════════════════════════════════════════════════════════
# State: generate_pages
# ═══════════════════════════════════════════════════════════════════

@registry.register("course_generation", "generate_pages")
async def generate_pages_step(
    job_id: uuid.UUID,
    input_data: Dict[str, Any],
    checkpoint: Dict[str, Any],
    logger: logging.Logger,
    step_config: Dict[str, Any],
) -> StepResult:
    """Generate page content via LLM for each page in the approved plan.

    Integration points (all existing — no changes needed):
        - LLMClient.chat()
        - ModelTierRouter.classify_task()
        - CostTracker.record()
        - TemplateValidationEngine
    """
    import json as _json
    from app.services.ai.llm_client import LLMClient, LLMMessage
    from app.services.ai.model_tier_router import ModelTierRouter, ModelTier
    from app.services.ai.cost_tracker import CostTracker

    pages = checkpoint.get("import_job", {}).get("pages", [])
    pages_state = checkpoint.get("pages_state", {})
    total = pages_state.get("total", len(pages))
    generation_options = input_data.get("generation_options", {})
    course_metadata = checkpoint.get("import_job", {}).get("course_metadata", {})

    results = list(pages_state.get("results", []))
    start_index = len(results)

    model_name = generation_options.get(
        "model", os.getenv("AI_GENERATION_MODEL", "deepseek-v4-pro[1m]")
    )
    temperature = generation_options.get("temperature", 0.3)
    max_tokens = generation_options.get("max_tokens_per_page", 4096)

    llm_client = LLMClient(model=model_name)
    tier_router = ModelTierRouter()
    cost_tracker = CostTracker()

    for i in range(start_index, total):
        page = pages[i]
        prompt = _build_generation_prompt(page, course_metadata, generation_options)

        # Model routing: choose Planner vs Generator per page
        tier = tier_router.classify_task(
            f"generate page content for template {page.get('template_type', 'unknown')}"
        )
        if tier == ModelTier.PLANNER:
            llm_client.model = os.getenv("AI_PLANNER_MODEL", "deepseek-v4-flash")

        try:
            response = await llm_client.chat(
                messages=[LLMMessage(role="user", content=prompt)],
                temperature=temperature,
                max_tokens=max_tokens,
            )

            # Cost tracking: record after each LLM call
            if hasattr(response, 'token_usage') and response.token_usage:
                cost_tracker.record(
                    session_id=str(job_id),
                    user_id=input_data.get("user_id", "system"),
                    tenant_id=input_data.get("organization_id", ""),
                    model_id=model_name,
                    input_tokens=response.token_usage.get("input_tokens", 0),
                    output_tokens=response.token_usage.get("output_tokens", 0),
                )

            page_content = _parse_llm_response(response)

            # Validate page output
            valid, errors = _validate_page_content(page_content, page.get("template_type"))
            if not valid:
                return StepResult(
                    success=False,
                    error={
                        "code": "PAGE_VALIDATION_FAILED",
                        "message": f"Page {i} ('{page.get('title')}') validation failed: {errors}",
                        "page_index": i,
                        "validation_errors": errors,
                    },
                    checkpoint_data=checkpoint,
                    progress=(start_index + i) / max(total, 1),
                )

            results.append({
                "page_index": i,
                "title": page.get("title"),
                "template_type": page.get("template_type"),
                "content": page_content,
                "provenance": {
                    "model": llm_client.model,
                    "temperature": temperature,
                    "generated_at": datetime.utcnow().isoformat(),
                },
            })

            checkpoint["pages_state"] = {
                "total": total,
                "generated": len(results),
                "failed": 0,
                "results": results,
            }

        except Exception as exc:
            return StepResult(
                success=False,
                error={"code": "LLM_CALL_FAILED", "message": str(exc), "page_index": i},
                checkpoint_data=checkpoint,
                progress=(start_index + i) / max(total, 1),
            )

    return StepResult(success=True, checkpoint_data=checkpoint, progress=0.8)


# ═══════════════════════════════════════════════════════════════════
# State: validate_course
# ═══════════════════════════════════════════════════════════════════

@registry.register("course_generation", "validate_course")
async def validate_course_step(
    job_id: uuid.UUID,
    input_data: Dict[str, Any],
    checkpoint: Dict[str, Any],
    logger: logging.Logger,
    step_config: Dict[str, Any],
) -> StepResult:
    """Cross-page validation: schema compliance, navigation, assessment presence."""
    from app.services.ai.validation_engine import TemplateValidationEngine, ValidationResult
    from app.services.ai.template_contracts import AITemplateContractsService

    pages_state = checkpoint.get("pages_state", {})
    results = pages_state.get("results", [])

    contracts = AITemplateContractsService()
    engine = TemplateValidationEngine(contracts_service=contracts)
    course_structure = {
        "pages": [
            {
                "title": r.get("title"),
                "template_type": r.get("template_type"),
                "content": r.get("content"),
            }
            for r in results
        ],
        "metadata": checkpoint.get("import_job", {}).get("course_metadata", {}),
    }

    try:
        result = await engine.validate(
            template_type="course_structure",
            data=course_structure,
            scope="full",
        )
        if result.status == "error":
            return StepResult(
                success=False,
                error={
                    "code": "COURSE_VALIDATION_FAILED",
                    "message": "; ".join(m.message for m in result.messages),
                    "issues": [m.model_dump() for m in result.messages],
                },
            )
    except Exception as exc:
        return StepResult(
            success=False,
            error={"code": "VALIDATION_ERROR", "message": str(exc)},
        )

    return StepResult(success=True, progress=0.9)


# ═══════════════════════════════════════════════════════════════════
# State: create_batch_proposal
# ═══════════════════════════════════════════════════════════════════

@registry.register("course_generation", "create_batch_proposal")
async def create_batch_proposal_step(
    job_id: uuid.UUID,
    input_data: Dict[str, Any],
    checkpoint: Dict[str, Any],
    logger: logging.Logger,
    step_config: Dict[str, Any],
) -> StepResult:
    """Create a batch proposal from all generated pages."""
    from app.db.config import SessionLocal
    from app.services.ai.proposal_service import AIProposalService

    pages_state = checkpoint.get("pages_state", {})
    results = pages_state.get("results", [])
    import_job = checkpoint.get("import_job", {})

    if not results:
        return StepResult(
            success=False,
            error={"code": "NO_PAGES_GENERATED", "message": "No pages were generated"},
        )

    async with SessionLocal() as session:
        svc = AIProposalService(session)
        try:
            proposals = []
            for r in results:
                proposal = await svc.create_proposal(
                    session_id=str(job_id),
                    user_id=input_data.get("user_id", "system"),
                    organization_id=input_data.get("organization_id", ""),
                    course_id=import_job.get("course_id", ""),
                    operation="create_page",
                    resource_type="page",
                    data=r.get("content", {}),
                )
                proposals.append(proposal)

            checkpoint["result"] = {
                "proposals": proposals,
                "batch_proposal_id": str(job_id),
                "pages_generated": len(results),
                "course_preview_url": None,
            }
        except Exception as exc:
            return StepResult(
                success=False,
                error={"code": "BATCH_PROPOSAL_FAILED", "message": str(exc)},
            )

    return StepResult(success=True, checkpoint_data=checkpoint, progress=1.0)


# ═══════════════════════════════════════════════════════════════════
# Helpers (internal to this module)
# ═══════════════════════════════════════════════════════════════════

def _build_generation_prompt(
    page: Dict[str, Any],
    course_metadata: Dict[str, Any],
    options: Dict[str, Any],
) -> str:
    """Build LLM prompt for page generation. Basic implementation."""
    lang = options.get("language", "en")
    return (
        f"Generate e-learning page content for a course.\n"
        f"Title: {page.get('title', 'Untitled')}\n"
        f"Template: {page.get('template_type', 'text-content')}\n"
        f"Course context: {course_metadata.get('title', 'Untitled Course')}\n"
        f"Language: {lang}\n"
        f"Generate valid JSON matching the template schema."
    )


def _parse_llm_response(response) -> Dict[str, Any]:
    """Parse LLM response into structured page content."""
    import json as _json

    content = getattr(response, 'content', None)
    if content is None:
        raise ValueError("LLM response has no content")
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        return _json.loads(content)
    raise ValueError(f"Unexpected LLM response type: {type(content)}")


def _validate_page_content(
    content: Dict[str, Any], template_type: Optional[str]
) -> tuple:
    """Basic validation — returns (valid, errors_list)."""
    errors = []
    if not isinstance(content, dict):
        return False, ["Content must be a JSON object"]
    if not content:
        return False, ["Content is empty"]
    return len(errors) == 0, errors
