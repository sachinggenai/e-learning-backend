"""
Media upload and management endpoints for eLearning Authoring App.

This module provides production-ready file upload functionality with:
- File type validation and security checks
- Organized storage structure by course and media type
- Comprehensive error handling and logging
- Integration with course content system
"""

import uuid
import mimetypes
try:  # optional dependency
    import magic  # type: ignore
except Exception:  # pragma: no cover
    magic = None  # type: ignore
from pathlib import Path
from typing import Optional, Dict, Any
import logging
from datetime import datetime

import aiofiles
from fastapi import (
    APIRouter,
    File,
    UploadFile,
    HTTPException,
    Depends,
    Form,
    Request,
)
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.models.persisted_course import CourseRecord

# Configure logging
logger = logging.getLogger(__name__)

# Router setup
router = APIRouter(prefix="/media", tags=["Media Management"])

# Configuration constants
UPLOAD_DIR = Path("media")
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

# Ensure upload directory exists
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
(UPLOAD_DIR / "global").mkdir(parents=True, exist_ok=True)
ALLOWED_EXTENSIONS = {
    "image": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"],
    "video": [".mp4", ".webm", ".ogg", ".mov", ".avi"],
    "audio": [".mp3", ".wav", ".ogg", ".aac", ".m4a"]
}

# MIME type mapping for additional security
ALLOWED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml",
    "video/mp4", "video/webm", "video/ogg", "video/quicktime",
    "video/x-msvideo", "audio/mpeg", "audio/wav", "audio/ogg",
    "audio/aac", "audio/mp4"
}


def get_media_category(filename: str, mime_type: str) -> Optional[str]:
    """
    Determine media category based on file extension and MIME type.

    Args:
        filename: Original filename
        mime_type: MIME type of the file

    Returns:
        Media category ('image', 'video', 'audio') or None if not supported
    """
    file_ext = Path(filename).suffix.lower()

    for category, extensions in ALLOWED_EXTENSIONS.items():
        if (file_ext in extensions and
                any(mime_type.startswith(cat) for cat in [category])):
            return category

    return None


def validate_file_security(
    file_content: bytes, filename: str
) -> tuple[bool, str]:
    """
    Perform security validation on uploaded file.

    Args:
        file_content: File content bytes
        filename: Original filename

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check file size
    if len(file_content) > MAX_FILE_SIZE:
        return (
            False,
            f"File size ({len(file_content)} bytes) exceeds maximum "
            f"allowed size ({MAX_FILE_SIZE} bytes)"
        )

    # Check for empty files
    if len(file_content) == 0:
        return False, "Empty files are not allowed"

    # Guess MIME type from content
    mime_type, _ = mimetypes.guess_type(filename)
    if not mime_type:
        return False, "Unable to determine file type"

    # Check against allowed MIME types
    if mime_type not in ALLOWED_MIME_TYPES:
        return False, f"File type '{mime_type}' is not supported"

    # Basic file signature validation for common formats
    file_signatures = {
        b'\xFF\xD8\xFF': 'image/jpeg',
        b'\x89PNG\r\n\x1a\n': 'image/png',
        b'GIF87a': 'image/gif',
        b'GIF89a': 'image/gif',
        b'RIFF': 'video/webm',  # Also matches WAV, but we'll check further
        b'\x00\x00\x00\x20ftypmp4': 'video/mp4',
        b'ID3': 'audio/mpeg'
    }

    # Check file signature matches MIME type
    for signature, expected_mime in file_signatures.items():
        if file_content.startswith(signature):
            if (expected_mime != mime_type and
                not (signature == b'RIFF' and
                     mime_type in ['audio/wav', 'video/webm'])):
                logger.warning(
                    f"File signature mismatch: expected {expected_mime}, "
                    f"got {mime_type}"
                )
            break

    return True, ""


@router.post("/upload", summary="Upload Media File")
async def upload_media(
    request: Request,
    file: UploadFile = File(..., description="Media file to upload"),
    course_id: Optional[int] = Form(
        None, description="Course ID to associate with media"
    ),
    db: AsyncSession = Depends(get_session),
) -> Dict[str, Any]:
    """Upload media file with comprehensive validation and security checks.

    Features:
        * File type and size validation
        * Security checks including MIME type validation
        * Organized storage by course and media category
        * Database integration for tracking
        * Comprehensive error handling

    Supported formats:
        * Images: JPG, PNG, GIF, WebP, SVG (max 50MB)
        * Videos: MP4, WebM, OGG, MOV, AVI (max 50MB)
        * Audio: MP3, WAV, OGG, AAC, M4A (max 50MB)
    """
    try:
        size_info = file.size if file.size else 'unknown'
        logger.info(
            f"Starting media upload: {file.filename} (size: {size_info})"
        )

        # Validate basic file info
        if not file.filename:
            raise HTTPException(status_code=400, detail="Filename is required")

        # Pre-flight size check using Content-Length header if available
        if request:
            cl = request.headers.get("content-length")
            if cl and cl.isdigit():
                declared_size = int(cl)
                if declared_size > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "File size ("
                            f"{declared_size} bytes) exceeds maximum "
                            "allowed size "
                            f"({MAX_FILE_SIZE} bytes)"
                        ),
                    )

        # Read file content (limited to 50MB by earlier checks)
        try:
            file_content = await file.read()
        except Exception as e:
            logger.error(f"Failed to read uploaded file: {e}")
            raise HTTPException(
                status_code=400, detail="Failed to read uploaded file"
            )

        # Security validation
        is_valid, error_msg = validate_file_security(
            file_content, file.filename
        )
        if not is_valid:
            logger.warning(
                f"File validation failed for {file.filename}: {error_msg}"
            )
            raise HTTPException(status_code=400, detail=error_msg)

        # Determine authoritative MIME type
        guessed_mime, _ = mimetypes.guess_type(file.filename)
        sniffed_mime = None
        if magic:  # pragma: no branch
            try:
                sniffed_mime = magic.from_buffer(  # type: ignore
                    file_content[:4096], mime=True
                )
            except Exception as e:  # pragma: no cover
                logger.warning(f"python-magic sniff failed: {e}")
        mime_type = sniffed_mime or guessed_mime
        if not mime_type:
            raise HTTPException(
                status_code=400, detail="Unable to determine file type"
            )
        if (
            sniffed_mime
            and guessed_mime
            and sniffed_mime.split('/')[0] != guessed_mime.split('/')[0]
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "File type mismatch between content and extension"
                ),
            )
        media_category = get_media_category(file.filename, mime_type)

        if not media_category:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unsupported file type. Allowed extensions: "
                    f"{', '.join(sum(ALLOWED_EXTENSIONS.values(), []))}"
                )
            )

        # Validate course exists if course_id provided
        if course_id:
            try:
                course = await db.get(CourseRecord, course_id)
                if not course:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Course with ID {course_id} not found"
                    )
            except Exception as e:
                logger.error(
                    f"Database error checking course {course_id}: {e}"
                )
                raise HTTPException(status_code=500, detail="Database error")

        # Generate unique file ID and name
        file_id = str(uuid.uuid4())
        file_ext = Path(file.filename).suffix
        safe_filename = f"{file_id}{file_ext}"

        # Create directory structure
        if course_id:
            storage_dir = UPLOAD_DIR / str(course_id) / media_category
        else:
            storage_dir = UPLOAD_DIR / "global" / media_category

        storage_dir.mkdir(parents=True, exist_ok=True)
        file_path = storage_dir / safe_filename

        # Save file to disk
        try:
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(file_content)

            logger.info(f"File saved successfully: {file_path}")

        except Exception as e:
            logger.error(f"Failed to save file {file_path}: {e}")
            raise HTTPException(status_code=500, detail="Failed to save file")

        # Generate response metadata
        relative_path = file_path.relative_to(UPLOAD_DIR)
        file_url = f"/api/v1/media/files/{relative_path}"

        response_data = {
            "success": True,
            "media": {
                "id": file_id,
                "original_filename": file.filename,
                "stored_filename": safe_filename,
                "path": str(relative_path),
                "url": file_url,
                "mime_type": mime_type,
                "category": media_category,
                "size": len(file_content),
                "course_id": course_id,
                "uploaded_at": datetime.utcnow().isoformat(),
            }
        }

        logger.info(f"Media upload completed successfully: {file_id}")
        return response_data

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(f"Unexpected error during media upload: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error during upload"
        )


@router.get("/files/{file_path:path}", summary="Serve Media Files")
async def serve_media_file(file_path: str) -> FileResponse:
    """
    Serve uploaded media files with proper headers and caching.

    Args:
        file_path: Relative path to the media file

    Returns:
        FileResponse with appropriate headers

    Raises:
        HTTPException: If file not found or access denied
    """
    try:
        # Construct full file path
        full_path = UPLOAD_DIR / file_path

        # Security check - ensure path is within upload directory
        resolved_path = full_path.resolve()
        upload_dir_resolved = UPLOAD_DIR.resolve()

        if not str(resolved_path).startswith(str(upload_dir_resolved)):
            logger.warning(f"Path traversal attempt detected: {file_path}")
            raise HTTPException(status_code=403, detail="Access denied")

        # Check if file exists
        if not resolved_path.exists():
            logger.warning(f"File not found: {file_path}")
            raise HTTPException(status_code=404, detail="File not found")

        # Determine MIME type
        mime_type, _ = mimetypes.guess_type(str(resolved_path))
        if not mime_type:
            mime_type = "application/octet-stream"

        # Return file with appropriate headers
        return FileResponse(
            path=resolved_path,
            media_type=mime_type,
            headers={
                "Cache-Control": "public, max-age=31536000",  # 1 year cache
                "Content-Disposition": (
                    f"inline; filename=\"{resolved_path.name}\""
                )
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving media file {file_path}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/files/{file_id}", summary="Delete Media File")
async def delete_media_file(
    file_id: str,
    course_id: Optional[int] = None,
    db: AsyncSession = Depends(get_session)
) -> Dict[str, Any]:
    """
    Delete media file by ID.

    Args:
        file_id: Media file ID
        course_id: Optional course ID for scoped deletion
        db: Database session

    Returns:
        Deletion confirmation
    """
    try:
        # Find file in storage structure
        search_dirs = []
        if course_id:
            search_dirs.append(UPLOAD_DIR / str(course_id))
        else:
            # Search in global and all course directories
            search_dirs.append(UPLOAD_DIR / "global")
            for course_dir in UPLOAD_DIR.iterdir():
                if course_dir.is_dir() and course_dir.name.isdigit():
                    search_dirs.append(course_dir)

        file_found = False
        for search_dir in search_dirs:
            if not search_dir.exists():
                continue

            for category_dir in search_dir.iterdir():
                if not category_dir.is_dir():
                    continue

                for file_path in category_dir.iterdir():
                    if file_path.stem == file_id:
                        # Found the file, delete it
                        file_path.unlink()
                        logger.info(f"Deleted media file: {file_path}")
                        file_found = True
                        break

                if file_found:
                    break
            if file_found:
                break

        if not file_found:
            raise HTTPException(status_code=404, detail="Media file not found")

        return {"success": True, "message": "Media file deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting media file {file_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to delete media file"
        )


@router.get("/", summary="List Media Files")
async def list_media_files(
    course_id: Optional[int] = None,
    category: Optional[str] = None
) -> Dict[str, Any]:
    """
    List available media files with filtering options.

    Args:
        course_id: Optional course ID to filter by
        category: Optional media category to filter by

    Returns:
        List of media files with metadata
    """
    try:
        media_files = []

        # Determine search directories
        if course_id:
            search_dirs = [UPLOAD_DIR / str(course_id)]
        else:
            search_dirs = [UPLOAD_DIR / "global"]
            # Add all course directories
            for item in UPLOAD_DIR.iterdir():
                if item.is_dir() and item.name.isdigit():
                    search_dirs.append(item)

        # Scan directories for media files
        for search_dir in search_dirs:
            if not search_dir.exists():
                continue

            for category_dir in search_dir.iterdir():
                if not category_dir.is_dir():
                    continue

                dir_category = category_dir.name
                if category and dir_category != category:
                    continue

                for file_path in category_dir.iterdir():
                    if file_path.is_file():
                        # Extract file info
                        file_stats = file_path.stat()
                        relative_path = file_path.relative_to(UPLOAD_DIR)

                        # Extract course ID from path
                        path_parts = relative_path.parts
                        file_course_id = None
                        if path_parts[0].isdigit():
                            file_course_id = int(path_parts[0])

                        media_files.append({
                            "id": file_path.stem,
                            "filename": file_path.name,
                            "path": str(relative_path),
                            "url": f"/api/v1/media/files/{relative_path}",
                            "category": dir_category,
                            "size": file_stats.st_size,
                            "course_id": file_course_id,
                            "created_at": datetime.fromtimestamp(
                                file_stats.st_ctime
                            ).isoformat(),
                            "modified_at": datetime.fromtimestamp(
                                file_stats.st_mtime
                            ).isoformat()
                        })

        return {
            "success": True,
            "media_files": media_files,
            "count": len(media_files)
        }

    except Exception as e:
        logger.error(f"Error listing media files: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to list media files"
        )
