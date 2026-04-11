"""
Import API endpoints for SCORM package ingestion.

Provides REST endpoints for:
- Uploading and analyzing SCORM packages
- Polling import job status
- Previewing import results
- Committing imports to the database
"""

import logging
from typing import Optional
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Query
from pydantic import BaseModel

from app.db.config import get_session
from app.services.import_service import (
    ImportService,
    NoPayloadFoundError,
    ImportServiceError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/imports", tags=["imports"])


class ImportAnalysisResponse(BaseModel):
    """Response from import analysis."""
    job_id: str
    status: str
    progress: float
    course_data: Optional[dict] = None
    error: Optional[str] = None


class ImportStatusResponse(BaseModel):
    """Response from import status poll."""
    job_id: str
    status: str
    progress: float
    course_data: Optional[dict] = None
    error: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ImportCommitRequest(BaseModel):
    """Request to commit an import."""
    merge_with_course_id: Optional[str] = None


class ImportCommitResponse(BaseModel):
    """Response from import commit."""
    job_id: str
    status: str
    course_id: Optional[str] = None
    message: str


@router.post("/analyze", response_model=ImportAnalysisResponse)
async def analyze_import(
    file: UploadFile = File(...),
    course_id: Optional[str] = Query(None),
    session=Depends(get_session)
):
    """
    Analyze an uploaded SCORM package.

    This endpoint:
    1. Validates the uploaded ZIP file
    2. Extracts and parses JSON payloads
    3. Infers schemas for templates
    4. Stages the data for review

    Returns a job ID for polling status.

    Args:
        file: SCORM ZIP package (multipart/form-data)
        course_id: Optional target course ID for metadata
        session: Database session

    Returns:
        ImportAnalysisResponse with job ID
    """
    try:
        # Validate file type
        if not file.filename.endswith(".zip"):
            raise HTTPException(
                status_code=400,
                detail="File must be a ZIP archive (.zip)"
            )

        # Read file
        content = await file.read()

        # Create import service
        service = ImportService(session)

        # Analyze package
        job_id = await service.analyze_package(content, course_id=course_id)

        return ImportAnalysisResponse(
            job_id=job_id,
            status="analyzing",
            progress=0.5
        )

    except HTTPException:
        raise
    except NoPayloadFoundError as e:
        logger.error(f"No payload found in upload: {e}")
        raise HTTPException(
            status_code=400,
            detail="No JSON payloads found in package"
        )
    except ImportServiceError as e:
        logger.error(f"Import analysis error: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Import error: {str(e)}"
        )
    except Exception as e:
        logger.error(
            f"Unexpected error during import analysis: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Unexpected error during import analysis"
        )


@router.get("/jobs/{job_id}", response_model=ImportStatusResponse)
async def get_import_status(
    job_id: str,
    session=Depends(get_session)
):
    """
    Get the status of an import job.

    Args:
        job_id: Import job ID
        session: Database session

    Returns:
        ImportStatusResponse with current job status and data
    """
    try:
        service = ImportService(session)
        preview = await service.get_preview(job_id)

        if not preview:
            raise HTTPException(status_code=404, detail="Job not found")

        return ImportStatusResponse(
            job_id=preview["jobId"],
            status=preview["status"],
            progress=preview["progress"],
            course_data=preview["courseData"],
            created_at=preview["createdAt"],
            updated_at=preview["updatedAt"]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching import status: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Error fetching import status"
        )


@router.post("/jobs/{job_id}/commit", response_model=ImportCommitResponse)
async def commit_import(
    job_id: str,
    request: Optional[ImportCommitRequest] = None,
    session=Depends(get_session)
):
    """
    Commit an analyzed import to the database.

    This endpoint finalizes an import job that has been analyzed and
    previewed. In Phase 1, it just marks the job as committed. Phase 2
    will actually create the course record.

    Args:
        job_id: Import job ID
        request: Optional request body with additional parameters
        session: Database session

    Returns:
        ImportCommitResponse indicating success or failure
    """
    try:
        service = ImportService(session)
        result = await service.commit_import(job_id)

        return ImportCommitResponse(
            job_id=job_id,
            status="committed",
            course_id=result.get("courseId")
            or result.get("courseData", {}).get("courseId"),
            message="Import committed successfully"
        )

    except ImportServiceError as e:
        logger.error(f"Commit error: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Commit error: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error committing import: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Error committing import"
        )


@router.get("/jobs/{job_id}/preview")
async def get_import_preview(
    job_id: str,
    session=Depends(get_session)
):
    """
    Get a preview of the import data (alias for /jobs/{job_id}).

    Args:
        job_id: Import job ID
        session: Database session

    Returns:
        Import preview data
    """
    return await get_import_status(job_id, session)
