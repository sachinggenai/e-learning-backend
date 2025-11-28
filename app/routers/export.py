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

 
@router.get("/export/status/{export_id}", summary="Get Export Status")
async def get_export_status(export_id: str):
    """
    Get status of an export operation
    
    Phase 1 implementation returns immediate status since exports are
    synchronous.
    Future phases may implement async export processing with job queues.
    """
    # For Phase 1, all exports are immediate/synchronous
    # This endpoint is prepared for future async implementation
    return {
        "success": True,
        "export_id": export_id,
        "status": "completed",  # Phase 1: always completed immediately
        "message": "Export operations are synchronous in Phase 1",
        "timestamp": datetime.utcnow().isoformat()
    }

class ScormExportRequest(BaseModel):
    format: str = "scorm1.2"
    include_media: bool = True

@router.post("/export/scorm/{course_id}", summary="Export Persisted Course as SCORM Package")
async def export_persisted_course(
    course_id: int,
    request: ScormExportRequest,
    session: AsyncSession = Depends(get_session)
) -> StreamingResponse:
    """
    Export a persisted course (by ID) as a SCORM package.
    """
    repo = CourseRepository(session)
    try:
        # Fetch course record
        course_record = await repo.get(course_id)
        
        # Convert to Pydantic model
        # Merge metadata with json_data
        course_data = course_record.json_data.copy()
        course_data['courseId'] = course_record.course_id
        course_data['title'] = course_record.title
        if course_record.description:
            course_data['description'] = course_record.description
            
        # Ensure templates exist in data
        if 'templates' not in course_data:
            # If templates are stored in a separate table, we might need to fetch them
            # But for now assuming they are in json_data or we need to fetch them
            # The seed script puts them in TemplateRecord, NOT in CourseRecord.json_data['templates']
            # Wait, the seed script does:
            # json_data={"pages": [], "templates": []} for course
            # and creates TemplateRecords.
            
            # If the application uses TemplateRecords, we need to fetch them and put them into the Course object.
            pass

        # Fetch templates if they are not in json_data
        # We need to check if we should fetch from TemplateRepo
        from ..repositories.template_repo import TemplateRepository
        template_repo = TemplateRepository(session)
        templates = await template_repo.list(course_record.id)
        
        # Add default author if missing
        if 'author' not in course_data:
            course_data['author'] = "Unknown Author"

        if templates:
            # Convert TemplateRecords to dicts and add to course_data
            course_data['templates'] = []
            for t in templates:
                t_data = t.json_data.copy()
                
                # Map types
                t_type = t.template_type
                if t_type == 'video':
                    t_type = 'content-video'
                elif t_type == 'quiz':
                    t_type = 'mcq'
                elif t_type in ['content-image', 'interactive']:
                    # Map unsupported types to content-text for now
                    t_type = 'content-text'
                
                # Map data structure to TemplateData
                mapped_data = {}
                
                # Extract content string
                raw_content = t_data.get('content', {})
                if isinstance(raw_content, dict):
                    if 'text' in raw_content:
                        mapped_data['content'] = raw_content['text']
                    elif 'welcomeMessage' in raw_content:
                        mapped_data['content'] = raw_content['welcomeMessage']
                    elif 'description' in raw_content:
                        mapped_data['content'] = raw_content['description']
                    else:
                        mapped_data['content'] = "Content"
                else:
                    mapped_data['content'] = str(raw_content) if raw_content else "Content"
                
                if 'subtitle' in t_data:
                    mapped_data['subtitle'] = t_data['subtitle']
                
                if t_type == 'content-video':
                    if isinstance(raw_content, dict):
                        mapped_data['videoUrl'] = raw_content.get('videoUrl')
                        if not mapped_data['videoUrl']:
                             mapped_data['videoUrl'] = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ' # Default valid URL
                    else:
                        mapped_data['videoUrl'] = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'

                if t_type == 'mcq':
                    # Extract questions and map 'correct' to 'isCorrect'
                    questions = []
                    if isinstance(raw_content, dict) and 'questions' in raw_content:
                        for q in raw_content['questions']:
                            mapped_q = {
                                "id": q.get("id", "q1"),
                                "question": q.get("question", "Question"),
                                "options": []
                            }
                            for opt in q.get("options", []):
                                mapped_opt = {
                                    "id": opt.get("id", "opt1"),
                                    "text": opt.get("text", "Option"),
                                    "isCorrect": opt.get("correct", False)
                                }
                                mapped_q["options"].append(mapped_opt)
                            questions.append(mapped_q)
                    
                    if not questions:
                         questions = [{
                            "id": "q1",
                            "question": "Placeholder Question",
                            "options": [
                                {"id": "opt1", "text": "Option 1", "isCorrect": True},
                                {"id": "opt2", "text": "Option 2", "isCorrect": False}
                            ]
                        }]
                    mapped_data['questions'] = questions

                template_obj = {
                    "id": t.template_uid,
                    "type": t_type,
                    "title": t.title,
                    "order": t.order_index,
                    "data": mapped_data
                }
                course_data['templates'].append(template_obj)
        
        # Validate/Convert to Course model
        validated_course = Course(**course_data)
        
        # Generate SCORM
        zip_buffer = await scorm_service.generate_scorm_package(validated_course)
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
    except Exception as e:
        logger.error("SCORM export failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")
