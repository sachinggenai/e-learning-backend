"""
Course Export Router

Implements the SCORM export functionality for Phase 1 MVP.
Provides endpoints for generating SCORM-compliant course packages.
"""

from fastapi import APIRouter, HTTPException, Depends, Query, Body
from fastapi.responses import StreamingResponse
from ..models.course import Course, CourseExportRequest
from ..services.scorm_export import SCORMExportService
from ..utils.validation import validate_course_json
from ..utils.error_envelope import build_error, api_http_exception
import json
import os
import hashlib
import logging
import uuid
from datetime import datetime
from typing import Literal, Optional

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
router = APIRouter(tags=["Export"])
logger = logging.getLogger(__name__)

# Initialize SCORM service
scorm_service = SCORMExportService()

# ── Shared OpenAPI response models ────────────────────────────────────────────

class ExportValidationErrorItem(BaseModel):
    code: str
    field: str
    message: str
    hint: Optional[str] = None

class ExportValidationError422(BaseModel):
    detail: list


def _error_payload(code: str, message: str, field: str = "request", hint: Optional[str] = None) -> dict:
    details = {}
    if hint:
        details["hint"] = hint
    return build_error(
        code=code,
        message=message,
        field=field,
        details=details,
    )

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
                raise api_http_exception(
                    status_code=400,
                    code="VALIDATION_ERROR",
                    field="templates.order",
                    message=(
                        "Template orders must form a zero-based contiguous "
                        "sequence"
                    ),
                    details={"expected": expected, "actual": sorted(orders)},
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
        zip_bytes = zip_buffer.getvalue()
        zip_buffer.seek(0)
        
        # Create headers for download
        headers = {
            "Content-Disposition": f"attachment; filename={filename}",
            "Content-Type": "application/zip",
            "Content-Length": str(len(zip_bytes))
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
            len(zip_bytes),
        )

        # Return streaming response
        return StreamingResponse(
            io.BytesIO(zip_bytes),
            media_type="application/zip",
            headers=headers,
        )
        
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON in course data: %s", e)
        raise api_http_exception(
            status_code=400,
            code="INVALID_JSON",
            field="course",
            message="Invalid course JSON format",
            details={"error": str(e)},
        )
    
    except ValueError as e:
        logger.error("Course validation error: %s", e)
        raise api_http_exception(
            status_code=422,
            code="VALIDATION_ERROR",
            field="course",
            message=f"Invalid course data: {str(e)}",
        )
    
    except Exception as e:
        error_id = uuid.uuid4().hex[:12]
        logger.error("SCORM export failed [error_id=%s]: %s", error_id, e, exc_info=True)
        raise api_http_exception(
            status_code=500,
            code="INTERNAL_ERROR",
            field="course",
            message="Export failed",
            details={"errorId": error_id},
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
        error_id = uuid.uuid4().hex[:12]
        logger.error("Validation failed [error_id=%s]: %s", error_id, e, exc_info=True)
        raise api_http_exception(
            status_code=422,
            code="VALIDATION_ERROR",
            field="course",
            message="Validation failed",
            details={"errorId": error_id},
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
    format: Literal["scorm_1_2", "scorm_2004"] = "scorm_1_2"
    includeMedia: bool = True


# ── Structured 422 helpers ────────────────────────────────────────────────────

def _export_error(code: str, field: str, message: str, hint: Optional[str] = None) -> dict:
    entry: dict = {"code": code, "field": field, "message": message}
    if hint:
        entry["hint"] = hint
    return entry


def _validate_course_for_export(course_id: str, db_pages: list, comp_map: dict) -> list[dict]:
    """Return a list of structured validation errors. Empty list means valid."""
    errors: list[dict] = []

    if not db_pages:
        errors.append(_export_error(
            code="COURSE_NO_PAGES",
            field="pages",
            message="Course must contain at least one page",
            hint="Add at least one page before exporting",
        ))
        return errors  # no point checking further

    for idx, pg in enumerate(db_pages):
        components = comp_map.get(pg.page_id, [])
        if not components:
            errors.append(_export_error(
                code="PAGE_NO_COMPONENTS",
                field=f"pages[{idx}].components",
                message=f"Page '{pg.title}' must contain at least one component",
                hint="Open the page in the editor and add a component",
            ))

    return errors


class PersistedCourseExportValidationError(Exception):
    """Raised when stored course data cannot be exported safely."""


# Shared type normalization map for both page/component and TemplateRecord export paths.
# Maps legacy/AI-generated types → canonical BUILTIN_TEMPLATE_TYPES.
_TYPE_NORMALIZATION_MAP: dict[str, str] = {
    "text-content": "content-text",
    "text-with-media": "content-text",
    "content-media": "content-text",
    "content-audio": "content-text",
    "content-image": "content-text",
    "click-reveal": "accordion",       # Aligns with SCORM runtime (accordion-family transform)
    "interactive": "content-text",
    "video": "content-video",
    "quiz": "mcq",
    # Canonical types (identity mapping for safe pass-through)
    "content-text": "content-text",
    "accordion": "accordion",
    "tabs": "tabs",
    "final-assessment": "final-assessment",
    "content-video": "content-video",
    "mcq": "mcq",
    "welcome": "welcome",
    "summary": "summary",
}


def _normalize_component_type_to_template_type(comp_type: str) -> str:
    """Map AI-generated component types to valid Course BUILTIN_TEMPLATE_TYPES.

    Built-in types: welcome, content-video, mcq, content-text, summary,
    final-assessment, tabs, accordion, video, quiz
    """
    return _TYPE_NORMALIZATION_MAP.get(comp_type, "content-text")


def _component_data_with_content(comp_type: str, data: dict) -> dict:
    """
    Ensure component data has a 'content' key for legacy Course model validation.
    Synthesizes a plain-text fallback for rich component types that don't carry
    a top-level 'content' field (e.g. tabs, accordion).
    The SCORM service uses the full 'data' dict for rendering; 'content' is
    only needed to pass Pydantic's TemplateData.content validation.
    """
    if "content" in data:
        return data

    out = dict(data)

    if comp_type == "final-assessment":
        # For final assessment, sanitize questions field if it's malformed
        questions = out.get("questions")
        if isinstance(questions, str):
            # If questions is a string, it's malformed - try to parse it or clear it
            questions_str = (questions or "").strip()
            if not questions_str:
                # Empty string or whitespace - initialize as empty list
                out["questions"] = []
            else:
                # Try to parse as JSON, otherwise keep as string and let validation fail with better error
                try:
                    import json
                    parsed = json.loads(questions)
                    out["questions"] = parsed if isinstance(parsed, list) else []
                except (json.JSONDecodeError, TypeError):
                    # Keep as string - will fail validation with clear error message
                    pass
        elif not isinstance(questions, list):
            # If it's not a list or string, convert to empty list
            out["questions"] = []
        
        # Synthesize content from introText
        out["content"] = out.get("introText") or out.get("title") or "final-assessment"

    elif comp_type in ("text-with-media", "content-media"):
        # Preserve all text-with-media fields as-is; synthesize a
        # plain-text content fallback from body without overwriting mediaUrl.
        out["content"] = data.get("body") or comp_type

    elif comp_type == "tabs":
        tabs = data.get("tabs") or []
        out["content"] = " ".join(
            f"{t.get('title', '')} {t.get('body', '')}" for t in tabs
        ).strip() or comp_type

    elif comp_type == "accordion":
        panels = data.get("panels") or []
        out["content"] = " ".join(
            f"{p.get('title', '')} {p.get('body', '')}" for p in panels
        ).strip() or comp_type

    elif comp_type == "click-reveal":
        # Legacy type: data uses items: [{title, content}]
        # Synthesize content from items for backward-compatible export
        items = data.get("items") or []
        out["content"] = " ".join(
            f"{item.get('title', '')} {item.get('content', '')}" for item in items
        ).strip() or comp_type

    else:
        # Generic fallback: first non-URL string value found, or the type name
        import re as _re
        _url_pat = _re.compile(r'^https?://', _re.IGNORECASE)
        out["content"] = next(
            (str(v) for v in data.values()
             if isinstance(v, str) and v and not _url_pat.match(v)),
            comp_type,
        )

    return out


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

    normalized_type = _TYPE_NORMALIZATION_MAP.get(template_type, template_type)

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

    if normalized_type == "tabs":
        tabs = []
        if isinstance(raw_content, dict):
            tabs = raw_content.get("tabs") or []
        if not tabs:
            tabs = template_payload.get("tabs") or []
        if isinstance(tabs, list):
            mapped_data["tabs"] = tabs

    if normalized_type == "accordion":
        panels = []
        if isinstance(raw_content, dict):
            panels = raw_content.get("panels") or []
        if not panels:
            panels = template_payload.get("panels") or []
        if isinstance(panels, list):
            mapped_data["panels"] = panels

    if normalized_type in ("content-media", "text-with-media"):
        # Preserve all text-with-media fields from the template payload.
        # body — canonical rich-text field (preferred over content)
        body = None
        if isinstance(raw_content, dict):
            body = raw_content.get("body")
        if body is None:
            body = template_payload.get("body")
        if body:
            mapped_data["body"] = body

        # mediaUrl — absolute URL to the media asset
        media_url = None
        if isinstance(raw_content, dict):
            media_url = raw_content.get("mediaUrl") or raw_content.get("imageUrl")
        if not media_url:
            media_url = template_payload.get("mediaUrl") or template_payload.get("imageUrl")
        if media_url:
            mapped_data["mediaUrl"] = media_url

        # mediaType — "image" | "video"
        media_type = None
        if isinstance(raw_content, dict):
            media_type = raw_content.get("mediaType")
        if media_type is None:
            media_type = template_payload.get("mediaType")
        if media_type:
            mapped_data["mediaType"] = media_type

        # mediaPosition — "left" | "right" | "top" | "bottom"
        media_position = None
        if isinstance(raw_content, dict):
            media_position = raw_content.get("mediaPosition")
        if media_position is None:
            media_position = template_payload.get("mediaPosition")
        if media_position:
            mapped_data["mediaPosition"] = media_position

    return {
        "id": template_record.template_uid,
        "type": normalized_type,
        "title": template_record.title,
        "order": template_record.order_index,
        "data": mapped_data,
    }


# ── Theme resolution for SCORM export ────────────────────────────────────────

def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base (same as themes.py helper)."""
    from copy import deepcopy
    result = deepcopy(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = deepcopy(val)
    return result


# Sensible fallback when no theme is configured or found in DB
_FALLBACK_THEME = {
    "colors": {
        "primary": "#667eea", "secondary": "#764ba2", "accent": "#FF4081",
        "background": "#FFFFFF", "surface": "#F5F5F5", "text": "#212121",
        "textSecondary": "#757575", "border": "#E0E0E0",
        "success": "#10b981", "warning": "#F57C00", "error": "#D32F2F",
        "info": "#1976D2",
    },
    "typography": {
        "fontFamily": "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        "headingFont": "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        "baseFontSize": 16,
    },
    "componentStyles": {},
}


async def _resolve_theme_bundle(
    session: AsyncSession,
    course_record,
    db_pages: list,
    comp_map: dict,
) -> dict:
    """
    Resolve the full theme cascade for a course being exported.

    Returns a dict with:
      courseTheme  — fully resolved course-level theme (preset + course overrides)
      pageOverrides — { pageId: { partial theme overrides } }
      componentOverrides — { componentId: { styling dict } }
    """
    from app.repositories.theme_repo import ThemeRepository

    repo = ThemeRepository(session)

    # 1. Resolve base theme from course settings
    settings = (course_record.json_data or {}).get("settings", {})
    theme_id = settings.get("themeId")
    course_overrides = settings.get("themeOverrides", {})

    base_theme = None
    if theme_id:
        theme_record = await repo.get(theme_id)
        if theme_record:
            base_theme = {
                "colors": theme_record.colors or {},
                "typography": theme_record.typography or {},
                "componentStyles": theme_record.component_styles or {},
            }

    if not base_theme:
        # Try first preset as fallback
        presets = await repo.list(is_preset=True)
        if presets:
            t = presets[0]
            base_theme = {
                "colors": t.colors or {},
                "typography": t.typography or {},
                "componentStyles": t.component_styles or {},
            }
        else:
            base_theme = _FALLBACK_THEME.copy()

    # Apply course-level overrides on top of preset
    course_theme = _deep_merge(base_theme, course_overrides) if course_overrides else base_theme

    # 2. Collect page-level theme overrides
    page_overrides: dict = {}
    for pg in db_pages:
        if pg.theme_config:
            overrides = pg.theme_config.get("overrides", {})
            if overrides:
                page_overrides[pg.page_id] = overrides

    # 3. Collect component-level styling overrides
    component_overrides: dict = {}
    for pg in db_pages:
        for comp in comp_map.get(pg.page_id, []):
            if comp.styling:
                # Component styling may contain themeOverrides or direct overrides
                theme_ovr = comp.styling.get("themeOverrides", comp.styling)
                if theme_ovr:
                    component_overrides[comp.component_id] = theme_ovr

    return {
        "courseTheme": course_theme,
        "pageOverrides": page_overrides,
        "componentOverrides": component_overrides,
    }


@router.post(
    "/export/scorm/{courseId}",
    summary="Export Persisted Course as SCORM Package",
    responses={
        200: {"content": {"application/zip": {}}, "description": "SCORM ZIP archive"},
        404: {"description": "Course not found"},
        422: {"description": "Course exists but is not exportable — structured detail array returned"},
        500: {"description": "Internal export failure"},
    },
)
async def export_persisted_course(
    courseId: str,
    body: Optional[ScormExportRequest] = Body(None),
    format: Optional[Literal["scorm_1_2", "scorm_2004"]] = Query(
        default=None,
        description="SCORM format version (query param overrides body)",
    ),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """
    Export a persisted course (by ID) as a SCORM ZIP package.

    - **200**: Binary ZIP stream with `Content-Disposition` filename header.
    - **404**: Course ID not found in the database.
    - **422**: Course exists but validation failed (no pages, empty pages, etc.).
      Detail array contains machine-readable entries with `code`, `field`, `message`, optional `hint`.
    - **500**: Unexpected export failure.
    """
    repo = CourseRepository(session)
    try:
        course_record = await repo.get_by_course_id(courseId)
    except CourseNotFoundError:
        raise api_http_exception(
            status_code=404,
            code="NOT_FOUND",
            field="courseId",
            message=f"Course '{courseId}' not found in database",
            details={"courseId": courseId},
        )

    # Resolve format: query param > request body > default
    effective_format: str = format or (body.format if body else "scorm_1_2")

    try:
        from app.repositories.page_component_repo import PageRepository, ComponentRepository

        page_repo = PageRepository(session)
        comp_repo = ComponentRepository(session)
        db_pages = await page_repo.list_by_course(course_record.course_id)

        # Build component map upfront for validation and conversion
        comp_map: dict = {}
        for pg in db_pages:
            comp_map[pg.page_id] = await comp_repo.list_by_page(pg.page_id)

        # ── Build legacy Course model for SCORM service ──────────────────
        course_data = course_record.json_data.copy()
        course_data["courseId"] = course_record.course_id
        course_data["title"] = course_record.title
        if course_record.description:
            course_data["description"] = course_record.description
        if "author" not in course_data:
            course_data["author"] = "Unknown Author"

        # Prefer normalized TemplateRecord rows when present
        from ..repositories.template_repo import TemplateRepository
        template_repo = TemplateRepository(session)
        templates = await template_repo.list(course_record.id)

        # Legacy json_data blob templates (courses created via old POST body)
        json_blob_templates = course_data.get("templates") or []

        if templates:
            # TemplateRecord path — no page/component validation needed
            course_data["templates"] = [_map_template_record(t) for t in templates]
        elif json_blob_templates:
            # JSON blob path — templates already present in course_data, skip validation
            pass
        else:
            # Page/component path — apply structured validation
            validation_errors = _validate_course_for_export(courseId, db_pages, comp_map)
            if validation_errors:
                raise api_http_exception(
                    status_code=422,
                    code="VALIDATION_ERROR",
                    field="course",
                    message="Course is not exportable",
                    details={"errors": validation_errors},
                )

            course_data["templates"] = []
            for pg in db_pages:
                for comp in comp_map.get(pg.page_id, []):
                    normalized_type = _normalize_component_type_to_template_type(comp.component_type)
                    course_data["templates"].append({
                        "id": comp.component_id,
                        "type": normalized_type,
                        "title": pg.title,
                        "order": len(course_data["templates"]),
                        "pageId": pg.page_id,
                        "data": _component_data_with_content(
                            comp.component_type, comp.data or {}
                        ),
                    })

        # ── Resolve theme cascade ────────────────────────────────────────
        theme_bundle = await _resolve_theme_bundle(
            session, course_record, db_pages, comp_map,
        )

        validated_course = Course(**course_data)

        zip_buffer = await scorm_service.generate_scorm_package(
            validated_course, theme_bundle=theme_bundle,
        )
        filename = f"{validated_course.courseId}_scorm_{effective_format}.zip"
        zip_buffer.seek(0)

        return StreamingResponse(
            io.BytesIO(zip_buffer.getvalue()),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(zip_buffer.getvalue())),
            },
        )

    except HTTPException:
        raise
    except PersistedCourseExportValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=build_error(
                code="VALIDATION_ERROR",
                field="course",
                message=str(exc),
                details={
                    "errors": [
                        _export_error("EXPORT_VALIDATION_ERROR", "course", str(exc))
                    ]
                },
            ),
        )
    except PydanticValidationError as exc:
        errors = [
            _export_error(
                code="SCHEMA_VALIDATION_ERROR",
                field=".".join(str(l) for l in e.get("loc", [])),
                message=e.get("msg", "Validation error"),
            )
            for e in exc.errors()
        ]
        raise HTTPException(
            status_code=422,
            detail=build_error(
                code="VALIDATION_ERROR",
                field="course",
                message="Schema validation failed",
                details={"errors": errors},
            ),
        )
    except ValueError as exc:
        # Catch validation errors raised by Pydantic validators (e.g., @validator)
        error_msg = str(exc)
        raise HTTPException(
            status_code=422,
            detail=build_error(
                code="VALIDATION_ERROR",
                field="course",
                message=error_msg,
                details={
                    "errors": [
                        _export_error("VALIDATION_ERROR", "course", error_msg)
                    ]
                },
            ),
        )
    except Exception as exc:
        error_id = uuid.uuid4().hex[:12]
        logger.error(
            "SCORM export failed for %s [error_id=%s]: %s",
            courseId,
            error_id,
            exc,
            exc_info=True,
        )
        raise api_http_exception(
            status_code=500,
            code="INTERNAL_ERROR",
            field="course",
            message="Internal export failure",
            details={"errorId": error_id},
        )
