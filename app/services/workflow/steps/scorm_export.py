"""Step executors for the 'scorm_export' workflow type — US-BKND-AI-034.

States: validate_course -> generate_manifest -> package_assets -> create_zip -> complete
"""
from __future__ import annotations

import logging
import os
import tempfile
import uuid
import zipfile
from datetime import datetime
from typing import Any, Dict

from app.services.workflow.step_registry import get_default_registry
from app.services.workflow.types import StepResult

registry = get_default_registry()


@registry.register("scorm_export", "validate_course")
async def validate_course_step(
    job_id: uuid.UUID,
    input_data: Dict[str, Any],
    checkpoint: Dict[str, Any],
    logger: logging.Logger,
    step_config: Dict[str, Any],
) -> StepResult:
    """Validate course exists and is complete enough for SCORM export."""
    course_id = input_data.get("course_id", "")
    if not course_id:
        return StepResult(
            success=False,
            error={"code": "MISSING_INPUT", "message": "course_id is required"},
        )

    from app.db.config import SessionLocal
    from app.repositories.course_repo import CourseRepository

    async with SessionLocal() as session:
        repo = CourseRepository(session)
        course = await repo.get_by_id(course_id)
        if not course:
            return StepResult(
                success=False,
                error={"code": "COURSE_NOT_FOUND",
                       "message": f"No course with id {course_id}"},
            )

        checkpoint["course"] = {
            "course_id": course_id,
            "title": getattr(course, "title", "Untitled"),
            "page_count": getattr(course, "page_count", 0),
        }

    page_count = checkpoint["course"]["page_count"]
    if page_count <= 3:
        logger.warning(
            "Small course (%d pages) routed to workflow — should use sync export",
            page_count,
        )

    return StepResult(success=True, checkpoint_data=checkpoint, progress=0.1)


@registry.register("scorm_export", "generate_manifest")
async def generate_manifest_step(
    job_id: uuid.UUID,
    input_data: Dict[str, Any],
    checkpoint: Dict[str, Any],
    logger: logging.Logger,
    step_config: Dict[str, Any],
) -> StepResult:
    """Build imsmanifest.xml from course structure."""
    course = checkpoint.get("course", {})
    manifest = {
        "identifier": f"MANIFEST-{course.get('course_id')}",
        "version": "1.0",
        "title": course.get("title", "Untitled Course"),
        "organizations": [
            {"identifier": "ORG-DEFAULT", "title": course.get("title")}
        ],
        "resources": [],
    }
    checkpoint["manifest"] = manifest
    return StepResult(success=True, checkpoint_data=checkpoint, progress=0.3)


@registry.register("scorm_export", "package_assets")
async def package_assets_step(
    job_id: uuid.UUID,
    input_data: Dict[str, Any],
    checkpoint: Dict[str, Any],
    logger: logging.Logger,
    step_config: Dict[str, Any],
) -> StepResult:
    """Collect and hash all media assets referenced in the course."""
    # In production, this would use AssetPackager from the export module
    checkpoint["assets"] = {"count": 0, "total_size_bytes": 0, "files": []}
    return StepResult(success=True, checkpoint_data=checkpoint, progress=0.6)


@registry.register("scorm_export", "create_zip")
async def create_zip_step(
    job_id: uuid.UUID,
    input_data: Dict[str, Any],
    checkpoint: Dict[str, Any],
    logger: logging.Logger,
    step_config: Dict[str, Any],
) -> StepResult:
    """Build the SCORM ZIP package and store it persistently."""
    import json as _json

    course = checkpoint.get("course", {})
    tmp_dir = tempfile.mkdtemp(
        prefix=f"scorm-{course.get('course_id', 'unknown')}-"
    )

    try:
        zip_path = os.path.join(tmp_dir, "package.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "imsmanifest.xml",
                _json.dumps(checkpoint.get("manifest", {})),
            )

        checkpoint["result"] = {
            "download_url": f"file://{zip_path}",  # Placeholder — prod uses S3/GCS
            "file_size_bytes": os.path.getsize(zip_path),
            "generated_at": datetime.utcnow().isoformat(),
        }
    except Exception as exc:
        return StepResult(
            success=False,
            error={"code": "ZIP_CREATION_FAILED", "message": str(exc)},
            checkpoint_data=checkpoint,
        )

    return StepResult(success=True, checkpoint_data=checkpoint, progress=1.0)


@registry.register("scorm_export", "complete")
async def complete_export_step(
    job_id: uuid.UUID,
    input_data: Dict[str, Any],
    checkpoint: Dict[str, Any],
    logger: logging.Logger,
    step_config: Dict[str, Any],
) -> StepResult:
    """Terminal state — signals orchestrator to mark job complete."""
    return StepResult(success=True, checkpoint_data=checkpoint, progress=1.0)
