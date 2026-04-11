"""
Course Export Router

Implements the SCORM export functionality for Phase 1 MVP.
Provides endpoints for generating SCORM-compliant course packages.
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from ..models.course import Course, CourseExportRequest
from ..services.scorm_export import SCORMExportService
from ..utils.validation import validate_course_json
import json
import os
import hashlib
import logging
from datetime import datetime

import io
from pydantic import BaseModel
try:
    from pydantic import ValidationError as PydanticValidationError
except ImportError:  # pragma: no cover
    from pydantic.error_wrappers import (  # type: ignore
        ValidationError as PydanticValidationError,
    )
from sqlalchemy.ext.asyncio import AsyncSession
from ..db.config import get_session
from ..repositories.course_repo import CourseRepository, CourseNotFoundError

# Initialize router and logger
router = APIRouter()
logger = logging.getLogger(__name__)

# Initialize SCORM service
scorm_service = SCORMExportService()

@router.post("/export", summary="Export Course as SCORM Package")
async def export_course(
    request: CourseExportRequest,
    validated_course: Course = Depends(validate_course_json)
) -> StreamingResponse:
    """
    Export course data as a SCORM-compliant ZIP package
    
    This endpoint implements the Phase 1 dummy SCORM export functionality:
    1. Validates the input course JSON against the schema
    2. Generates a basic SCORM manifest (imsmanifest.xml)
    3. Creates a simple HTML player file
    4. Packages everything into a ZIP file
    5. Returns the ZIP as a streaming download
    
    **Implementation follows Phase 1 requirements:**
    - Uses FastAPI streaming response for efficient downloads
    - Validates course data using Pydantic models
    - Generates basic SCORM-compliant structure
    - Handles errors gracefully with appropriate HTTP status codes
    """
    payload_snippet = request.course[:500]
    logger.info(f"Export request payload: {payload_snippet}...")
    try:
        logger.info(
            "Starting SCORM export for course: %s",
            validated_course.courseId,
        )

        # Additional validation per guide
        if not validated_course.templates:
            raise ValueError("Course must have at least one page")
        for page in validated_course.templates:
            if not all(hasattr(page, k) for k in ['id', 'title', 'type']):
                raise ValueError(f"Invalid page structure: {page}")

        # Validate ordering & detect non-sequential / duplicate template
        # order indices (spec BE-EXP-002)
        orders = [t.order for t in validated_course.templates]
        if orders:
            expected = list(range(len(orders)))
            if sorted(orders) != expected:
                logger.error(
                    "Template order validation failed (non-sequential or "
                    "duplicates)"
                )
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Template orders must form a zero-based contiguous "
                        "sequence"
                    ),
                )

        # Collect simple pre-export warnings (placeholder logic for BE-EXP-001)
        export_warnings = []
        if (
            not validated_course.title
            or len(validated_course.title.strip()) < 3
        ):
            export_warnings.append("Course title is very short")

        large_templates = [
            t
            for t in validated_course.templates
            if len(json.dumps(t.model_dump(mode="json"))) > 50_000
        ]
        if large_templates:
            export_warnings.append(
                f"{len(large_templates)} template(s) exceed recommended size"
            )

        # Generate SCORM package using the service
        zip_buffer = await scorm_service.generate_scorm_package(
            validated_course
        )
        filename = f"{validated_course.courseId}_scorm_package.zip"
        
        # Prepare streaming response
        zip_buffer.seek(0)
        
        # Create headers for download
        headers = {
            "Content-Disposition": f"attachment; filename={filename}",
            "Content-Type": "application/zip",
            "Content-Length": str(len(zip_buffer.getvalue()))
        }

        # Optional feature-flagged headers (BE-EXP-001)
        if os.getenv("EXPORT_HEADERS") == "1":
            try:
                course_json_sorted = json.dumps(
                    validated_course.model_dump(mode="json"), sort_keys=True
                ).encode("utf-8")
                course_hash = hashlib.md5(course_json_sorted).hexdigest()
                headers['X-Course-Hash'] = course_hash
                if export_warnings:
                    headers['X-Export-Warnings'] = json.dumps(export_warnings)
            except Exception as e:
                logger.warning("Failed to compute export headers: %s", e)

        logger.info(
            "SCORM export completed successfully. File size: %d bytes",
            len(zip_buffer.getvalue()),
        )

        # Return streaming response
        return StreamingResponse(
            io.BytesIO(zip_buffer.getvalue()),
            media_type="application/zip",
            headers=headers,
        )
        
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON in course data: %s", e)
        raise HTTPException(
            status_code=400,
            detail=f"Invalid course JSON format: {str(e)}"
        )
    
    except ValueError as e:
        logger.error("Course validation error: %s", e)
        raise HTTPException(
            status_code=400,
            detail=f"Invalid course data: {str(e)}"
        )
    
    except Exception as e:
        logger.error("SCORM export failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Export failed: {str(e)}"
        )

 
@router.post("/export/validate", summary="Validate Course Data for Export")
async def validate_course_for_export(
    request: CourseExportRequest,
    validated_course: Course = Depends(validate_course_json)
):
    """
    Validate course data without performing the actual export
    
    This endpoint allows frontend to validate course data before export:
    - Checks JSON format and schema compliance
    - Validates template structure and content
    - Returns detailed validation results
    - Estimates export file size
    """
    try:
        # Calculate estimated package size
        estimated_size = scorm_service.estimate_package_size(validated_course)

        # Perform additional validation checks
        validation_results = await scorm_service.validate_for_export(
            validated_course
        )

        # Compute a stable hash of transformed course for trace/debug
        course_hash = hashlib.md5(
            json.dumps(
                validated_course.model_dump(mode='json'),
                sort_keys=True
            ).encode('utf-8')
        ).hexdigest()

        return {
            "success": True,
            "message": "Course data is valid for export",
            "course_info": {
                "courseId": validated_course.courseId,
                "title": validated_course.title,
                "author": validated_course.author,
                "template_count": len(validated_course.templates),
                "asset_count": len(validated_course.assets)
            },
            "validation": validation_results,
            "trace": {"course_hash": course_hash},
            "estimated_size": estimated_size,
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"Validation failed: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Validation failed: {str(e)}"
        )

 
@router.get("/export/formats", summary="Get Supported Export Formats")
async def get_export_formats():
    """
    Get list of supported export formats
    
    Currently supports SCORM 1.2 (dummy implementation for Phase 1)
    Future phases will add more formats like SCORM 2004, xAPI, etc.
    """
    return {
        "success": True,
        "formats": [
            {
                "id": "scorm_1_2",
                "name": "SCORM 1.2",
                "description": (
                    "SCORM 1.2 compliant package (Phase 1 basic "
                    "implementation)"
                ),
                "file_extension": ".zip",
                "supported": True,
                "features": [
                    "Basic manifest generation",
                    "Simple HTML player",
                    "Course structure preservation",
                    "Asset bundling"
                ]
            }
        ],
        "timestamp": datetime.utcnow().isoformat()
    }

 
@router.get("/export/status/{exportId}", summary="Get Export Status")
async def get_export_status(exportId: str):
    """
    Get status of an export operation
    
    Phase 1 implementation returns immediate status since exports are
    synchronous.
    Future phases may implement async export processing with job queues.
    """
    # For Phase 1, all exports are immediate/synchronous
    # This endpoint is prepared for future async implementation
    return {
        "exportId": exportId,
        "status": "completed",  # Phase 1: always completed immediately
        "progress": 100,
        "downloadUrl": None,
        "error": None,
    }

class ScormExportRequest(BaseModel):
    format: str = "scorm_1_2"
    includeMedia: bool = True


class PersistedCourseExportValidationError(Exception):
    """Raised when stored course data cannot be exported safely."""


def _extract_text_content(template_uid: str, template_payload: dict) -> str:
    raw_content = template_payload.get("content")
    if isinstance(raw_content, str):
        return raw_content
    if isinstance(raw_content, dict):
        return (
            raw_content.get("text")
            or raw_content.get("welcomeMessage")
            or raw_content.get("description")
            or ""
        )
    if raw_content is None:
        return ""
    raise PersistedCourseExportValidationError(
        f"Template '{template_uid}' has unsupported content structure"
    )


def _normalize_questions(
    template_uid: str,
    questions: list[dict],
) -> list[dict]:
    if not questions:
        raise PersistedCourseExportValidationError(
            f"Template '{template_uid}' is missing MCQ questions"
        )

    normalized_questions = []
    for question_index, question in enumerate(questions):
        options = question.get("options", [])
        if not options:
            raise PersistedCourseExportValidationError(
                "Template "
                f"'{template_uid}' question {question_index + 1} "
                "has no options"
            )

        normalized_questions.append(
            {
                "id": question.get("id") or f"q{question_index + 1}",
                "question": question.get("question") or "",
                "options": [
                    {
                        "id": opt.get("id") or f"opt{opt_index + 1}",
                        "text": opt.get("text") or "",
                        "isCorrect": opt.get(
                            "correct",
                            opt.get("isCorrect", False),
                        ),
                    }
                    for opt_index, opt in enumerate(options)
                ],
            }
        )

    return normalized_questions


def _map_template_record(template_record) -> dict:
    template_payload = template_record.json_data.copy()
    raw_content = template_payload.get("content")
    template_type = template_record.template_type

    legacy_type_map = {
        "video": "content-video",
        "quiz": "mcq",
        "content-image": "content-text",
        "interactive": "content-text",
    }
    normalized_type = legacy_type_map.get(template_type, template_type)

    mapped_data = {
        "content": _extract_text_content(
            template_record.template_uid,
            template_payload,
        )
    }
    if "subtitle" in template_payload:
        mapped_data["subtitle"] = template_payload["subtitle"]

    if normalized_type == "content-video":
        video_url = None
        if isinstance(raw_content, dict):
            video_url = raw_content.get("videoUrl")
        if video_url is None:
            video_url = template_payload.get("videoUrl")
        if not video_url:
            raise PersistedCourseExportValidationError(
                "Template "
                f"'{template_record.template_uid}' is missing videoUrl"
            )
        mapped_data["videoUrl"] = video_url

    if normalized_type == "mcq":
        questions = []
        if isinstance(raw_content, dict):
            questions = raw_content.get("questions") or []
        if not questions:
            questions = template_payload.get("questions") or []
        mapped_data["questions"] = _normalize_questions(
            template_record.template_uid,
            questions,
        )

    return {
        "id": template_record.template_uid,
        "type": normalized_type,
        "title": template_record.title,
        "order": template_record.order_index,
        "data": mapped_data,
    }

@router.post(
    "/export/scorm/{courseId}",
    summary="Export Persisted Course as SCORM Package",
)
async def export_persisted_course(
    courseId: str,
    request: ScormExportRequest,
    session: AsyncSession = Depends(get_session)
) -> StreamingResponse:
    """
    Export a persisted course (by ID) as a SCORM package.
    """
    repo = CourseRepository(session)
    try:
        # Fetch course record
        course_record = await repo.get_by_course_id(courseId)
        
        # Convert to Pydantic model
        # Merge metadata with json_data
        course_data = course_record.json_data.copy()
        course_data['courseId'] = course_record.course_id
        course_data['title'] = course_record.title
        if course_record.description:
            course_data['description'] = course_record.description
            
        # Prefer normalized template records when present so export uses
        # the authoritative persisted representation.
        from ..repositories.template_repo import TemplateRepository
        template_repo = TemplateRepository(session)
        templates = await template_repo.list(course_record.id)

        # Add default author if missing
        if 'author' not in course_data:
            course_data['author'] = "Unknown Author"

        if templates:
            course_data['templates'] = [
                _map_template_record(template)
                for template in templates
            ]

        # ── Component-based pages (new format) ───────────────────────
        # If the course has pages with components, convert them to
        # legacy template format for the existing SCORM export service.
        from app.repositories.page_component_repo import (
            PageRepository,
            ComponentRepository,
        )
        page_repo = PageRepository(session)
        comp_repo = ComponentRepository(session)
        db_pages = await page_repo.list_by_course(course_record.course_id)

        if db_pages and "templates" not in course_data:
            course_data["templates"] = []

        for idx, pg in enumerate(db_pages):
            components = await comp_repo.list_by_page(pg.page_id)
            for comp in components:
                # Map each component to a legacy template entry so
                # the SCORM export service can handle it unchanged.
                course_data["templates"].append(
                    {
                        "id": comp.component_id,
                        "type": comp.component_type,
                        "title": pg.title,
                        "order": len(course_data["templates"]),
                        "data": comp.data or {},
                    }
                )
        
        # Validate/Convert to Course model
        validated_course = Course(**course_data)
        
        # Generate SCORM
        zip_buffer = await scorm_service.generate_scorm_package(
            validated_course
        )
        filename = f"{validated_course.courseId}_scorm_package.zip"
        
        zip_buffer.seek(0)
        
        headers = {
            "Content-Disposition": f"attachment; filename={filename}",
            "Content-Type": "application/zip",
            "Content-Length": str(len(zip_buffer.getvalue()))
        }
        
        return StreamingResponse(
            io.BytesIO(zip_buffer.getvalue()),
            media_type="application/zip",
            headers=headers,
        )

    except CourseNotFoundError:
        raise HTTPException(status_code=404, detail="Course not found")
    except PersistedCourseExportValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except PydanticValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())
    except HTTPException:
        raise
    except Exception as e:
        logger.error("SCORM export failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")
