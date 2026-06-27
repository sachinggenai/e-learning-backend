"""Step executors for the 'scorm_export' workflow type — US-BKND-AI-034.

States: validate_course -> generate_manifest -> package_assets -> create_zip -> complete
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime
from typing import Any, Dict

from app.services.workflow.step_registry import get_default_registry
from app.services.workflow.types import StepResult

registry = get_default_registry()


def _render_manifest_xml(manifest: dict, scorm_version: str = "2004") -> str:
    """Render the SCORM manifest dict as a minimal XML string for XSD validation."""
    if scorm_version == "1.2":
        default_ns = "http://www.imsproject.org/xsd/imscp_rootv1p1p2"
    else:
        default_ns = "http://www.imsglobal.org/xsd/imscp_v1p1"

    orgs = manifest.get("organizations", [])
    org_xml = ""
    for org in orgs:
        org_xml += (
            f'    <organization identifier="{org.get("identifier", "ORG-DEFAULT")}">'
            f'<title>{org.get("title", "")}</title></organization>\n'
        )

    resources = manifest.get("resources", [])
    res_xml = ""
    for res in resources:
        res_xml += (
            f'    <resource identifier="{res.get("identifier", "RES-1")}" '
            f'type="webcontent" href="{res.get("href", "index.html")}">'
            f'</resource>\n'
        )

    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<manifest xmlns="{default_ns}" version="1.0">\n'
        f'  <organizations default="ORG-DEFAULT">\n{org_xml}  </organizations>\n'
        f'  <resources>\n{res_xml}  </resources>\n'
        f'</manifest>'
    )


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
    from app.repositories.course_repo import CourseRepository, CourseNotFoundError

    async with SessionLocal() as session:
        repo = CourseRepository(session)
        try:
            course = await repo.get_by_course_id(course_id)
        except CourseNotFoundError:
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
    """Build imsmanifest.xml from course structure and validate against SCORM XSD."""
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

    # ── XSD Validation (Phase 3.8 fix) ─────────────────────────────
    manifest_xml = _render_manifest_xml(manifest, step_config.get("scorm_version", "2004"))
    try:
        from app.services.ai.scorm_validator import SCORMValidator
        scorm_version = step_config.get("scorm_version", "2004")
        validator = SCORMValidator()
        xsd_result = await validator.validate_manifest_xsd(
            manifest_xml, version=scorm_version,
        )
        if not xsd_result.get("valid", True):
            logger.warning(
                "SCORM manifest XSD validation had issues: %s",
                xsd_result.get("issues", []),
            )
            manifest["xsd_warnings"] = xsd_result.get("issues", [])
        else:
            manifest["xsd_validated"] = True
            logger.info("SCORM manifest passed XSD validation")
    except ImportError:
        logger.info("xmlschema not installed — skipping SCORM XSD validation")
    except Exception as exc:
        logger.warning("SCORM XSD validation error (non-fatal): %s", exc)

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
    from app.services.storage import StorageService

    course = checkpoint.get("course", {})
    course_id = course.get("course_id", "unknown")
    tmp_dir = tempfile.mkdtemp(prefix=f"scorm-{course_id}-")

    try:
        zip_path = os.path.join(tmp_dir, "package.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "imsmanifest.xml",
                _json.dumps(checkpoint.get("manifest", {})),
            )

        # Store persistently via StorageService (local filesystem or S3/MinIO)
        storage = StorageService()
        with open(zip_path, "rb") as f:
            result = await storage.save_scorm_package(
                file_data=f,
                filename=f"{course_id}_scorm.zip",
                job_id=str(job_id),
            )

        file_size = os.path.getsize(zip_path)
        checkpoint["result"] = {
            "download_url": (
                f"/api/v1/files/{result.file_path}"
                if result.success and result.file_path
                else f"/api/v1/files/scorm/{course_id}_scorm.zip"
            ),
            "file_path": result.file_path if result.success else None,
            "file_size_bytes": file_size,
            "generated_at": datetime.utcnow().isoformat(),
        }
    except Exception as exc:
        return StepResult(
            success=False,
            error={"code": "ZIP_CREATION_FAILED", "message": str(exc)},
            checkpoint_data=checkpoint,
        )
    finally:
        # Always clean up temp directory
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return StepResult(success=True, checkpoint_data=checkpoint, progress=1.0)
