# US-AI-016 -- Add File Upload and Ingestion Job Foundation for AI

**As an Author, I want to upload source documents for AI analysis, so that course generation can begin from existing material.**

- **Source flows:** File Ingestion / Document Import Flow (flow 8), Full Course from Uploaded File Scenario Flow (flow 10)
- **Priority:** MUST for file-import MVP
- **Depends on:** US-AI-004 (AI persistence foundations) -- requires `ai_ingestion_jobs` table alongside the existing `import_jobs` table
- **Primary dependency on existing code:** Reuses `ImportJobRepository`, `ImportService`, `StrategyRegistry`, `StorageService` patterns; creates new `app/routers/ai_ingestion.py` router, `app/services/ai/ingestion_service.py` service, and `app/repositories/ai_ingestion_repository.py` repository.

---

## 1. Functional Specification

### 1.1 Summary

The platform MUST provide a dedicated document upload and ingestion endpoint that accepts PDF, DOCX, and configurable package types (ZIP/SCORM), creates a durable ingestion job with a polling URL, performs deterministic extraction of text content and structure, and stages the extracted payload for downstream AI segmentation (US-AI-017) and course generation (US-AI-019). The ingestion flow MUST be decoupled from the existing SCORM import pipeline at the router level but MAY reuse `ImportService` and `StrategyRegistry` for ZIP/SCORM packages behind the scenes.

### 1.2 User Interactions

1. **Upload trigger:** Author clicks "Upload Source Document" from the AI panel or course editor toolbar. A file picker dialog opens accepting `.pdf`, `.docx`, `.zip`, `.txt`, `.md` extensions (configurable).
2. **Upload progress:** Frontend streams the upload (multi-part/form-data) and shows a progress bar. Backend validates the file synchronously -- MIME type, magic-byte signature, size quota, virus-scan policy hook.
3. **Job creation:** On acceptance, backend creates an `ai_ingestion_jobs` row and returns `201 Created` with `{job_id, status: "uploaded", upload_url: "/api/v1/ai/ingestions/{job_id}"}`.
4. **Extraction (async):** Backend spawns a background extraction (or returns immediately and the frontend polls). Extraction status advances: `uploaded` -> `extracting` -> `analyzed`/`failed`.
5. **Polling:** Frontend polls `GET /api/v1/ai/ingestions/{job_id}` every 2 seconds while status is not terminal. Response includes `status`, `progress` (0.0-1.0), `extracted_preview` (once analyzed), `warnings`, `error`.
6. **Success state:** When `status == "analyzed"`, the response includes `extracted_sections[]`, `detected_type`, `page_count`, `warnings[]`, and `source_metadata`. No pages are created yet -- this is purely staging.
7. **Failure state:** When `status == "failed"`, the response includes `error` with an actionable message and error code. The job can be retried by POSTing a new file with the same `original_filename` and `correlation_id` for idempotent deduplication.
8. **Cleanup:** Stale ingestion jobs (older than 7 days, status `uploaded` or `analyzed`) are garbage-collected by a scheduled cleanup task.

### 1.3 Business Rules

| Rule | Behavior |
|------|----------|
| Unsupported file type | HTTP 400 with error code `UNSUPPORTED_FILE_TYPE` and accepted extensions list |
| File too large | HTTP 413 with `FILE_TOO_LARGE` (configurable per tenant, default 50MB for PDF/DOCX, 200MB for ZIP) |
| Empty/corrupt file | HTTP 400 with `CORRUPT_FILE` after magic-byte validation fails |
| Zip-slip detected | HTTP 400 with `SUSPICIOUS_ARCHIVE` |
| Duplicate upload (same SHA256) within TTL | Return existing job ID with `status: "duplicate"` and reference to the original job (idempotent retry) |
| SCORM package (ZIP with imsmanifest.xml) | Route through existing `ImportService` with `Scorm12Strategy`, return job in `import_jobs` but mirrored in `ai_ingestion_jobs` via `linked_import_job_id` |
| Extraction timeout (default 5 min) | Job transitions to `failed` with `EXTRACTION_TIMEOUT` |
| No extractable text content | Job transitions to `analyzed` with `extracted_sections: []` and a warning `NO_EXTRACTABLE_CONTENT` |
| AI feature flag disabled | All routes return 404; no upload or ingestion state is created |

---

## 2. Technical Specification

### 2.1 New Database Table -- `ai_ingestion_jobs`

```sql
-- Alembic migration: add_ai_ingestion_jobs_table.py
CREATE TABLE ai_ingestion_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          VARCHAR(64) NOT NULL UNIQUE,
    status          VARCHAR(32) NOT NULL DEFAULT 'uploaded',   -- uploaded, extracting, analyzed, failed
    progress        FLOAT NOT NULL DEFAULT 0.0,                -- 0.0 to 1.0
    file_name       VARCHAR(500) NOT NULL,
    file_size       INTEGER NOT NULL,
    file_hash       VARCHAR(64),                                -- SHA-256 hex
    mime_type       VARCHAR(100),
    detected_type   VARCHAR(32),                                -- 'pdf', 'docx', 'scorm12', 'json_payload', 'txt', 'md'
    source_path     VARCHAR(1000),                              -- internal storage path
    course_id       VARCHAR(64),                                -- optional target course ID (from session context)
    session_id      VARCHAR(64),                                -- FK: ai_sessions.job_id (US-AI-004)
    correlation_id  VARCHAR(64),                                -- client-generated idempotency key
    extracted_sections JSON,                                    -- array of {index, heading, content_preview, char_count, media_refs[]}
    warnings        JSON,                                       -- array of string warnings
    error_message   TEXT,
    error_code      VARCHAR(64),
    linked_import_job_id VARCHAR(64),                           -- when ZIP routes to existing import_jobs table
    source_metadata JSON,                                       -- {page_count, author, title, language, creation_date}
    created_at      DATETIME NOT NULL DEFAULT (datetime('now')),
    updated_at      DATETIME NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX ix_ai_ingestion_jobs_job_id ON ai_ingestion_jobs (job_id);
CREATE INDEX ix_ai_ingestion_jobs_status ON ai_ingestion_jobs (status);
CREATE INDEX ix_ai_ingestion_jobs_session_id ON ai_ingestion_jobs (session_id);
CREATE INDEX ix_ai_ingestion_jobs_correlation_id ON ai_ingestion_jobs (correlation_id);
CREATE INDEX ix_ai_ingestion_jobs_file_hash ON ai_ingestion_jobs (file_hash);
```

### 2.2 New ORM Model -- `app/models/ai_models.py`

```python
"""ORM models for AI module persistence (US-AI-004, US-AI-016, etc.)."""

from __future__ import annotations
from datetime import datetime
from typing import Optional, List
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, DateTime, JSON, Text, Integer, Float, ForeignKey
from app.models.base import Base


class AIngestionJob(Base):
    __tablename__ = "ai_ingestion_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    file_name: Mapped[str] = mapped_column(String(500))
    file_size: Mapped[int] = mapped_column(Integer)
    file_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    detected_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    source_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    course_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    extracted_sections: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    warnings: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    linked_import_job_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "jobId": self.job_id,
            "status": self.status,
            "progress": self.progress,
            "fileName": self.file_name,
            "fileSize": self.file_size,
            "fileHash": self.file_hash,
            "mimeType": self.mime_type,
            "detectedType": self.detected_type,
            "courseId": self.course_id,
            "sessionId": self.session_id,
            "correlationId": self.correlation_id,
            "extractedSections": self.extracted_sections,
            "warnings": self.warnings,
            "errorMessage": self.error_message,
            "errorCode": self.error_code,
            "linkedImportJobId": self.linked_import_job_id,
            "sourceMetadata": self.source_metadata,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }
```

### 2.3 New Repository -- `app/repositories/ai_ingestion_repository.py`

```python
"""Repository for AI Ingestion Jobs.

This is the NEW dedicated ingestion repository, distinct from the existing
ImportJobRepository which remains for the traditional SCORM import path.
"""

import uuid
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete

from app.models.ai_models import AIngestionJob

logger = logging.getLogger(__name__)


class AIngestionRepository:
    """Async repository for AI ingestion jobs."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        file_name: str,
        file_size: int,
        mime_type: Optional[str] = None,
        file_hash: Optional[str] = None,
        course_id: Optional[str] = None,
        session_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        source_path: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> AIngestionJob:
        if job_id is None:
            job_id = str(uuid.uuid4())

        record = AIngestionJob(
            job_id=job_id,
            status="uploaded",
            progress=0.0,
            file_name=file_name,
            file_size=file_size,
            mime_type=mime_type,
            file_hash=file_hash,
            course_id=course_id,
            session_id=session_id,
            correlation_id=correlation_id,
            source_path=source_path or "",
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        logger.info("Created ingestion job %s for file %s", job_id, file_name)
        return record

    async def get_by_id(self, job_id: str) -> Optional[AIngestionJob]:
        stmt = select(AIngestionJob).where(AIngestionJob.job_id == job_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_correlation_id(self, correlation_id: str) -> Optional[AIngestionJob]:
        stmt = select(AIngestionJob).where(
            AIngestionJob.correlation_id == correlation_id
        ).order_by(AIngestionJob.created_at.desc()).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_file_hash(self, file_hash: str, max_age_hours: int = 24) -> Optional[AIngestionJob]:
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        stmt = select(AIngestionJob).where(
            AIngestionJob.file_hash == file_hash,
            AIngestionJob.created_at >= cutoff,
            AIngestionJob.status.in_(["analyzed", "failed"]),
        ).order_by(AIngestionJob.created_at.desc()).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_status(
        self,
        job_id: str,
        status: str,
        progress: float = 0.0,
        error_message: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> Optional[AIngestionJob]:
        stmt = (
            update(AIngestionJob)
            .where(AIngestionJob.job_id == job_id)
            .values(
                status=status,
                progress=progress,
                error_message=error_message,
                error_code=error_code,
                updated_at=datetime.utcnow(),
            )
            .returning(AIngestionJob)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.scalar_one_or_none()

    async def update_extraction(
        self,
        job_id: str,
        extracted_sections: List[Dict[str, Any]],
        detected_type: str,
        source_metadata: Dict[str, Any],
        warnings: Optional[List[str]] = None,
        progress: float = 1.0,
    ) -> Optional[AIngestionJob]:
        stmt = (
            update(AIngestionJob)
            .where(AIngestionJob.job_id == job_id)
            .values(
                status="analyzed",
                progress=progress,
                extracted_sections=extracted_sections,
                detected_type=detected_type,
                source_metadata=source_metadata,
                warnings=warnings or [],
                updated_at=datetime.utcnow(),
            )
            .returning(AIngestionJob)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.scalar_one_or_none()

    async def link_import_job(self, job_id: str, import_job_id: str) -> Optional[AIngestionJob]:
        stmt = (
            update(AIngestionJob)
            .where(AIngestionJob.job_id == job_id)
            .values(
                linked_import_job_id=import_job_id,
                status="analyzed",
                progress=1.0,
                updated_at=datetime.utcnow(),
            )
            .returning(AIngestionJob)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.scalar_one_or_none()

    async def delete(self, job_id: str) -> bool:
        stmt = delete(AIngestionJob).where(AIngestionJob.job_id == job_id)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

    async def list_by_status(self, status: str, limit: int = 50) -> List[AIngestionJob]:
        stmt = select(AIngestionJob).where(
            AIngestionJob.status == status
        ).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def cleanup_stale(self, max_age_hours: int = 168) -> int:  # 7 days
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        stmt = delete(AIngestionJob).where(AIngestionJob.created_at < cutoff)
        result = await self.session.execute(stmt)
        await self.session.commit()
        count = result.rowcount
        if count:
            logger.info("Cleaned up %d stale ingestion jobs older than %d hours", count, max_age_hours)
        return count
```

### 2.4 New Service -- `app/services/ai/ingestion_service.py`

```python
"""AI Ingestion Service -- deterministic extraction from uploaded source documents.

Supports PDF, DOCX, TXT, MD, and ZIP/SCORM (routed to existing import strategies).
"""

import uuid
import hashlib
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Any, Optional, BinaryIO
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.ai_ingestion_repository import AIngestionRepository
from app.services.storage import StorageService, LocalFileSystemStorage
from app.services.import_service import ImportService

logger = logging.getLogger(__name__)


class IngestionServiceError(Exception):
    """Base exception for ingestion service errors."""
    pass


class UnsupportedFileTypeError(IngestionServiceError):
    """Raised when the uploaded file type is not supported."""
    pass


class FileTooLargeError(IngestionServiceError):
    """Raised when the uploaded file exceeds size limits."""
    pass


class ExtractionError(IngestionServiceError):
    """Raised when deterministic extraction fails."""
    pass


# Configuration with env var defaults
AI_INGESTION_MAX_FILE_SIZE_PDF = int(os.getenv("AI_INGESTION_MAX_FILE_SIZE_PDF", str(50 * 1024 * 1024)))     # 50 MB
AI_INGESTION_MAX_FILE_SIZE_ZIP = int(os.getenv("AI_INGESTION_MAX_FILE_SIZE_ZIP", str(200 * 1024 * 1024)))    # 200 MB
AI_INGESTION_ALLOWED_TYPES = os.getenv("AI_INGESTION_ALLOWED_TYPES", "pdf,docx,txt,md,zip").split(",")
AI_INGESTION_STORAGE_PATH = os.getenv("AI_INGESTION_STORAGE_PATH", "data/ingestion")
AI_INGESTION_MAX_EXTRACT_DURATION_SEC = int(os.getenv("AI_INGESTION_MAX_EXTRACT_DURATION_SEC", "300"))


FILE_TYPE_MAP = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".txt": "txt",
    ".md": "md",
    ".zip": "zip",
}

ZIP_STRATEGY_TYPES = {"zip"}


class IngestionService:
    """Service for AI document ingestion with deterministic extraction."""

    def __init__(self, db_session: AsyncSession):
        self.session = db_session
        self.repo = AIngestionRepository(db_session)
        self.storage = StorageService(
            storage=LocalFileSystemStorage(
                base_path=AI_INGESTION_STORAGE_PATH,
                base_url="/api/v1/ai/ingestions/files",
            )
        )

    async def upload_and_analyze(
        self,
        file_data: bytes,
        file_name: str,
        mime_type: Optional[str] = None,
        course_id: Optional[str] = None,
        session_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload a file, create an ingestion job, and perform extraction.

        Args:
            file_data: Raw file bytes
            file_name: Original filename
            mime_type: Client-declared MIME type
            course_id: Optional target course ID
            session_id: Optional AI session ID
            correlation_id: Optional client idempotency key

        Returns:
            Job dict with status and metadata

        Raises:
            UnsupportedFileTypeError: If file extension is not allowed
            FileTooLargeError: If file exceeds size limit
        """
        # 1. Validate file type
        ext = Path(file_name).suffix.lower()
        detected_type = FILE_TYPE_MAP.get(ext)
        if not detected_type or ext.lstrip(".") not in AI_INGESTION_ALLOWED_TYPES:
            raise UnsupportedFileTypeError(
                f"Unsupported file type '{ext}'. Accepted: {', '.join(AI_INGESTION_ALLOWED_TYPES)}"
            )

        # 2. Size check
        max_size = AI_INGESTION_MAX_FILE_SIZE_ZIP if detected_type == "zip" else AI_INGESTION_MAX_FILE_SIZE_PDF
        if len(file_data) > max_size:
            raise FileTooLargeError(
                f"File size {len(file_data)} bytes exceeds limit of {max_size} bytes"
            )

        # 3. SHA-256 dedup check (within 24h)
        file_hash = hashlib.sha256(file_data).hexdigest()
        existing = await self.repo.get_by_file_hash(file_hash, max_age_hours=24)
        if existing:
            logger.info(
                "Duplicate upload detected: hash %s matches existing job %s",
                file_hash[:16], existing.job_id,
            )
            return existing.to_dict()

        # 4. Save to storage
        job_id = str(uuid.uuid4())
        safe_name = f"{job_id}{ext}"
        storage_path = Path(AI_INGESTION_STORAGE_PATH) / job_id[0:2] / job_id[2:4] / safe_name
        os.makedirs(storage_path.parent, exist_ok=True)
        with open(storage_path, "wb") as f:
            f.write(file_data)

        # 5. Create job record
        job = await self.repo.create(
            job_id=job_id,
            file_name=file_name,
            file_size=len(file_data),
            mime_type=mime_type,
            file_hash=file_hash,
            course_id=course_id,
            session_id=session_id,
            correlation_id=correlation_id,
            source_path=str(storage_path),
        )

        # 6. If ZIP, hand off to import service
        if detected_type == "zip":
            return await self._handle_zip(job, file_data)

        # 7. Run deterministic extraction (synchronous within this call)
        return await self._extract(job, file_data, detected_type)

    async def _handle_zip(self, job: AIngestionJob, zip_data: bytes) -> Dict[str, Any]:
        """Route ZIP/SCORM packages to the existing ImportService."""
        await self.repo.update_status(job.job_id, "extracting", progress=0.2)

        try:
            import_service = ImportService(self.session)
            import_job_id = await import_service.analyze_package(zip_data, course_id=job.course_id)
            await self.repo.link_import_job(job.job_id, import_job_id)

            # ImportService already wrote to import_jobs; we mirror here
            return (await self.repo.get_by_id(job.job_id)).to_dict()

        except Exception as e:
            logger.error("ZIP analysis failed for job %s: %s", job.job_id, e)
            await self.repo.update_status(
                job.job_id, "failed", error_message=str(e), error_code="ZIP_ANALYSIS_FAILED"
            )
            return (await self.repo.get_by_id(job.job_id)).to_dict()

    async def _extract(
        self, job: AIngestionJob, file_data: bytes, detected_type: str
    ) -> Dict[str, Any]:
        """Run deterministic extraction for PDF, DOCX, TXT, MD."""
        await self.repo.update_status(job.job_id, "extracting", progress=0.3)

        try:
            extracted_sections = []
            warnings = []
            source_metadata: Dict[str, Any] = {}

            if detected_type == "pdf":
                extracted_sections, source_metadata = self._extract_pdf(file_data)
            elif detected_type == "docx":
                extracted_sections, source_metadata = self._extract_docx(file_data)
            elif detected_type in ("txt", "md"):
                content = file_data.decode("utf-8", errors="replace")
                extracted_sections, source_metadata = self._extract_plain_text(content, detected_type)

            if not extracted_sections:
                warnings.append("NO_EXTRACTABLE_CONTENT")

            await self.repo.update_extraction(
                job.job_id,
                extracted_sections=extracted_sections,
                detected_type=detected_type,
                source_metadata=source_metadata,
                warnings=warnings,
                progress=1.0,
            )

            return (await self.repo.get_by_id(job.job_id)).to_dict()

        except Exception as e:
            logger.error("Extraction failed for job %s: %s", job.job_id, e)
            await self.repo.update_status(
                job.job_id, "failed", error_message=str(e), error_code="EXTRACTION_FAILED"
            )
            return (await self.repo.get_by_id(job.job_id)).to_dict()

    def _extract_pdf(self, file_data: bytes) -> tuple[List[Dict], Dict]:
        """Extract sections from PDF bytes.

        NOTE: This is a placeholder. MVP scope includes the service interface;
        the actual PDF library integration (PyMuPDF / pdfminer.six) is added
        as an expansion point. Returns a single blob section for now.
        """
        return [], {"page_count": 0, "language": "unknown"}

    def _extract_docx(self, file_data: bytes) -> tuple[List[Dict], Dict]:
        """Extract sections from DOCX bytes.

        NOTE: Placeholder -- python-docx integration is an expansion point.
        """
        return [], {"page_count": 0, "author": None}

    def _extract_plain_text(self, content: str, detected_type: str) -> tuple[List[Dict], Dict]:
        """Extract sections from plain text or markdown.

        Splits on markdown headings (##, ###) or double-newlines as section
        boundaries.
        """
        import re
        sections = []
        lines = content.split("\n")
        current_heading = "Introduction"
        current_lines: List[str] = []
        char_count = 0

        for line in lines:
            heading_match = re.match(r"^(#{1,4})\s+(.+)$", line.strip()) if detected_type == "md" else None
            if heading_match:
                if current_lines:
                    text = "\n".join(current_lines).strip()
                    if text:
                        sections.append({
                            "index": len(sections),
                            "heading": current_heading,
                            "content_preview": text[:500],
                            "char_count": len(text),
                            "media_refs": [],
                        })
                        char_count += len(text)
                current_heading = heading_match.group(2).strip()
                current_lines = []
            else:
                current_lines.append(line)

        # Flush last section
        if current_lines:
            text = "\n".join(current_lines).strip()
            if text:
                sections.append({
                    "index": len(sections),
                    "heading": current_heading,
                    "content_preview": text[:500],
                    "char_count": len(text),
                    "media_refs": [],
                })
                char_count += len(text)

        return sections, {"char_count": char_count, "line_count": len(lines)}

    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get ingestion job by ID."""
        job = await self.repo.get_by_id(job_id)
        return job.to_dict() if job else None

    async def delete_job(self, job_id: str) -> bool:
        """Delete an ingestion job and its stored file."""
        job = await self.repo.get_by_id(job_id)
        if job and job.source_path:
            try:
                os.remove(job.source_path)
            except OSError:
                pass
        return await self.repo.delete(job_id)

    async def list_jobs(
        self, status: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """List ingestion jobs, optionally filtered by status."""
        if status:
            jobs = await self.repo.list_by_status(status, limit=limit)
        else:
            # basic list all -- pagination TBD
            jobs = await self.repo.list_by_status("uploaded", limit=limit) + \
                   await self.repo.list_by_status("extracting", limit=limit) + \
                   await self.repo.list_by_status("analyzed", limit=limit) + \
                   await self.repo.list_by_status("failed", limit=limit)
        return [j.to_dict() for j in jobs]

    async def cleanup_stale(self, max_age_hours: int = 168) -> int:
        """Remove ingestion jobs older than max_age_hours."""
        return await self.repo.cleanup_stale(max_age_hours=max_age_hours)
```

### 2.5 New Router -- `app/routers/ai_ingestion.py`

```python
"""AI Ingestion API endpoints -- file upload and ingestion job lifecycle.

Prefix: /api/v1/ai/ingestions
Tags: AI Ingestion
"""

import logging
from typing import Optional, List
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Query, Form

from app.db.config import get_session
from app.services.ai.ingestion_service import (
    IngestionService,
    IngestionServiceError,
    UnsupportedFileTypeError,
    FileTooLargeError,
)
from app.utils.error_envelope import api_http_exception

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai/ingestions", tags=["AI Ingestion"])

# --- Request/Response schemas ---

from pydantic import BaseModel


class IngestionStatusResponse(BaseModel):
    jobId: str
    status: str
    progress: float
    fileName: Optional[str] = None
    fileSize: Optional[int] = None
    fileHash: Optional[str] = None
    mimeType: Optional[str] = None
    detectedType: Optional[str] = None
    courseId: Optional[str] = None
    sessionId: Optional[str] = None
    correlationId: Optional[str] = None
    extractedSections: Optional[List[dict]] = None
    warnings: Optional[List[str]] = None
    errorMessage: Optional[str] = None
    errorCode: Optional[str] = None
    linkedImportJobId: Optional[str] = None
    sourceMetadata: Optional[dict] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None


class IngestionUploadResponse(BaseModel):
    jobId: str
    status: str
    progress: float
    correlationId: Optional[str] = None
    message: str = "File uploaded and queued for extraction"


class IngestionDeleteResponse(BaseModel):
    success: bool
    message: str


class IngestionListResponse(BaseModel):
    jobs: List[IngestionStatusResponse]
    total: int


# --- Endpoints ---


@router.post("/upload", response_model=IngestionUploadResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(..., description="Source document (PDF, DOCX, TXT, MD, ZIP)"),
    course_id: Optional[str] = Form(None, description="Target course ID"),
    session_id: Optional[str] = Form(None, description="AI session ID"),
    correlation_id: Optional[str] = Form(None, description="Client idempotency key"),
    db=Depends(get_session),
):
    """Upload a source document for AI ingestion and analysis.

    Supported formats: PDF, DOCX, TXT, MD, ZIP (SCORM packages).

    Returns a job ID immediately; the frontend polls GET /{job_id}
    for extraction status.
    """
    try:
        if not file.filename:
            raise api_http_exception(400, "MISSING_FILENAME", "Filename is required", field="file")

        content = await file.read()

        service = IngestionService(db)
        result = await service.upload_and_analyze(
            file_data=content,
            file_name=file.filename,
            mime_type=file.content_type,
            course_id=course_id,
            session_id=session_id,
            correlation_id=correlation_id,
        )

        return IngestionUploadResponse(
            jobId=result["jobId"],
            status=result["status"],
            progress=result["progress"],
            correlationId=result.get("correlationId"),
            message="File uploaded and queued for extraction",
        )

    except UnsupportedFileTypeError as e:
        raise api_http_exception(400, "UNSUPPORTED_FILE_TYPE", str(e), field="file")
    except FileTooLargeError as e:
        raise api_http_exception(413, "FILE_TOO_LARGE", str(e), field="file")
    except IngestionServiceError as e:
        logger.error("Ingestion error: %s", e)
        raise api_http_exception(500, "INGESTION_ERROR", str(e))
    except Exception as e:
        logger.error("Unexpected upload error: %s", e, exc_info=True)
        raise api_http_exception(500, "UPLOAD_UNEXPECTED", "Unexpected upload error")


@router.get("/{job_id}", response_model=IngestionStatusResponse)
async def get_ingestion_status(job_id: str, db=Depends(get_session)):
    """Get the current status and extracted data for an ingestion job."""
    service = IngestionService(db)
    job = await service.get_job(job_id)

    if not job:
        raise api_http_exception(404, "JOB_NOT_FOUND", f"Ingestion job {job_id} not found", field="job_id")

    return IngestionStatusResponse(**job)


@router.delete("/{job_id}", response_model=IngestionDeleteResponse)
async def delete_ingestion_job(job_id: str, db=Depends(get_session)):
    """Delete an ingestion job and its stored file."""
    service = IngestionService(db)
    job = await service.get_job(job_id)

    if not job:
        raise api_http_exception(404, "JOB_NOT_FOUND", f"Ingestion job {job_id} not found", field="job_id")

    deleted = await service.delete_job(job_id)
    if not deleted:
        raise api_http_exception(500, "DELETE_FAILED", f"Failed to delete job {job_id}")

    return IngestionDeleteResponse(success=True, message=f"Ingestion job {job_id} deleted")


@router.get("", response_model=IngestionListResponse)
async def list_ingestion_jobs(
    status: Optional[str] = Query(None, description="Filter by status (uploaded, extracting, analyzed, failed)"),
    limit: int = Query(50, description="Max results", ge=1, le=200),
    db=Depends(get_session),
):
    """List ingestion jobs with optional status filter."""
    service = IngestionService(db)
    jobs = await service.list_jobs(status=status, limit=limit)
    return IngestionListResponse(jobs=jobs, total=len(jobs))
```

### 2.6 Registration in `app/main.py`

Add to the existing import block:

```python
from app.routers import (
    # ... existing ...
    ai_ingestion,
)
```

Add to the `api_router` include block:

```python
api_router.include_router(ai_ingestion.router)
```

Guard with a feature flag check (conditional registration based on `AI_AUTHORING_ENABLED` or a dedicated `AI_INGESTION_ENABLED` env var).

### 2.7 Environment Variables -- New Additions to `.env.example`

```ini
# ============================================
# AI Ingestion Settings (US-AI-016)
# ============================================
# Master switch (also gated by AI_AUTHORING_ENABLED)
AI_INGESTION_ENABLED=true

# Allowed file extensions (comma-separated, no dots)
AI_INGESTION_ALLOWED_TYPES=pdf,docx,txt,md,zip

# Max file size per type (bytes)
AI_INGESTION_MAX_FILE_SIZE_PDF=52428800        # 50 MB
AI_INGESTION_MAX_FILE_SIZE_DOCX=52428800       # 50 MB
AI_INGESTION_MAX_FILE_SIZE_ZIP=209715200       # 200 MB

# Storage path relative to project root
AI_INGESTION_STORAGE_PATH=data/ingestion

# Max extraction duration in seconds (before timeout -> failed)
AI_INGESTION_MAX_EXTRACT_DURATION_SEC=300

# Stale job TTL in hours (cleanup target)
AI_INGESTION_CLEANUP_MAX_AGE_HOURS=168

# Enable SHA-256 dedup window (hours)
AI_INGESTION_DEDUP_WINDOW_HOURS=24
```

### 2.8 Alembic Migration

File: `alembic/versions/20260614_0001_add_ai_ingestion_jobs.py`

```python
"""Add ai_ingestion_jobs table for AI document ingestion.

Revision ID: 20260614_0001
Revises: e8a7ce8be9ac  (tip of the current chain)
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "20260614_0001"
down_revision: Union[str, Sequence[str], None] = "e8a7ce8be9ac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_ingestion_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="uploaded"),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("file_name", sa.String(500), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=True),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("detected_type", sa.String(32), nullable=True),
        sa.Column("source_path", sa.String(1000), nullable=True),
        sa.Column("course_id", sa.String(64), nullable=True),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("extracted_sections", sa.JSON(), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("linked_import_job_id", sa.String(64), nullable=True),
        sa.Column("source_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ai_ingestion_jobs_job_id"), "ai_ingestion_jobs", ["job_id"], unique=True)
    op.create_index(op.f("ix_ai_ingestion_jobs_status"), "ai_ingestion_jobs", ["status"], unique=False)
    op.create_index(op.f("ix_ai_ingestion_jobs_session_id"), "ai_ingestion_jobs", ["session_id"], unique=False)
    op.create_index(op.f("ix_ai_ingestion_jobs_correlation_id"), "ai_ingestion_jobs", ["correlation_id"], unique=False)
    op.create_index(op.f("ix_ai_ingestion_jobs_file_hash"), "ai_ingestion_jobs", ["file_hash"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_ingestion_jobs_file_hash"), table_name="ai_ingestion_jobs")
    op.drop_index(op.f("ix_ai_ingestion_jobs_correlation_id"), table_name="ai_ingestion_jobs")
    op.drop_index(op.f("ix_ai_ingestion_jobs_session_id"), table_name="ai_ingestion_jobs")
    op.drop_index(op.f("ix_ai_ingestion_jobs_status"), table_name="ai_ingestion_jobs")
    op.drop_index(op.f("ix_ai_ingestion_jobs_job_id"), table_name="ai_ingestion_jobs")
    op.drop_table("ai_ingestion_jobs")
```

### 2.9 API Contract Summary

| Method | Path | Status | Purpose |
|--------|------|--------|---------|
| `POST` | `/api/v1/ai/ingestions/upload` | 201 | Upload document for ingestion |
| `GET` | `/api/v1/ai/ingestions/{job_id}` | 200 | Poll job status and extracted data |
| `DELETE` | `/api/v1/ai/ingestions/{job_id}` | 200 | Delete job and stored file |
| `GET` | `/api/v1/ai/ingestions` | 200 | List jobs with optional `?status=` filter |

### 2.10 Service Method Signatures

```python
class IngestionService:
    async def upload_and_analyze(
        self,
        file_data: bytes,
        file_name: str,
        mime_type: Optional[str] = None,
        course_id: Optional[str] = None,
        session_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]: ...

    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]: ...
    async def delete_job(self, job_id: str) -> bool: ...
    async def list_jobs(self, status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]: ...
    async def cleanup_stale(self, max_age_hours: int = 168) -> int: ...
```

### 2.11 Key Error Codes

| HTTP | Code | Condition |
|------|------|-----------|
| 400 | `UNSUPPORTED_FILE_TYPE` | File extension not in allowed list |
| 413 | `FILE_TOO_LARGE` | File exceeds per-type byte limit |
| 400 | `CORRUPT_FILE` | Magic-byte mismatch or zero-length |
| 400 | `SUSPICIOUS_ARCHIVE` | Zip-slip path detected |
| 400 | `MISSING_FILENAME` | Upload with no filename |
| 404 | `JOB_NOT_FOUND` | Unknown job_id |
| 500 | `EXTRACTION_FAILED` | Internal extraction error |
| 500 | `ZIP_ANALYSIS_FAILED` | ImportService pipeline error |

---

## 3. Non-Functional Requirements

### 3.1 Performance

| Metric | Target | Measurement |
|--------|--------|-------------|
| Upload acceptance (validation + job create) | < 500 ms p95 | App-level timer on POST /upload |
| PDF extraction (up to 50 pages) | < 5 s p95 | Extraction timer in service |
| DOCX extraction (up to 100KB) | < 3 s p95 | Extraction timer in service |
| Poll response | < 100 ms p95 | GET /{job_id} response timer |
| Concurrent uploads | 10 per node | Load test with 10 simultaneous 10MB uploads |
| Dedup check | < 50 ms | SHA-256 + DB query timer |

### 3.2 Security

1. **Magic-byte validation:** Reject files whose extension does not match the first 8 bytes content signature (PDF header `%PDF`, DOCX header `PK\x03\x04`, ZIP header `PK\x03\x04`).
2. **Zip-slip protection:** Reject entries with absolute paths or `..` segments (implemented in `ImportService._extract_zip`; reapply in the ZIP path handler).
3. **Path traversal:** In `source_path` resolution, call `Path.resolve()` and verify it starts with the configured `AI_INGESTION_STORAGE_PATH` (same pattern as `media.py` line 345).
4. **Storage isolation:** Files stored under `data/ingestion/` are NOT served by any static file handler. Access is only through the `DELETE` endpoint (no GET file content endpoint -- the extracted text is the product, not the binary).
5. **Session scoping:** When `session_id` is provided, the ingestion job is tied to that AI session. `GET` and `DELETE` should verify the caller's session matches (deferred to US-AI-017's authorization pass).

### 3.3 Data Retention

| State | Retention | Cleanup Trigger |
|-------|-----------|----------------|
| uploaded / extracting | 7 days | `cleanup_stale(max_age_hours=168)` |
| analyzed | 7 days after creation | `cleanup_stale()` |
| failed | 7 days after creation | `cleanup_stale()` |
| Stored binary file | Same as parent job | Cascade delete in `delete_job` |

### 3.4 Observability

- **Log every upload:** job_id, file_name, file_size, file_hash[:16], correlation_id, session_id, course_id.
- **Log every extraction:** job_id, detected_type, section_count, char_count, duration_ms.
- **Log every failure:** job_id, error_code, error_message, stack trace at DEBUG level.
- **Metrics to expose (Prometheus/Grafana ready):**
  - `ai_ingestion_uploads_total{status="accepted|rejected",type="pdf|docx|zip|txt|md"}`
  - `ai_ingestion_extraction_duration_seconds{type="pdf|docx|zip|txt|md"}`
  - `ai_ingestion_job_status{status="uploaded|extracting|analyzed|failed"}` (gauge)

### 3.5 Throughput and Rate Limiting

- Per-user rate limit: 10 uploads per minute (default, configurable via `AI_INGESTION_USER_RATE_LIMIT`).
- Per-tenant concurrent extraction: 3 jobs at a time (configurable via `AI_INGESTION_MAX_CONCURRENT`).
- Return `429 Too Many Requests` with `Retry-After` header when exceeded, using the same error envelope shape.

---

## 4. Current State

### 4.1 What Exists Today

1. **`/api/v1/imports/analyze`** (`app/routers/imports.py`): Accepts only `.zip` files, routes through `ImportService.analyze_package()` which uses `StrategyRegistry` (Scorm12Strategy or JsonPayloadStrategy). Returns `job_id` for polling.

2. **`/api/v1/imports/jobs/{job_id}`** (`app/routers/imports.py`): Polls status of `import_jobs` table through `ImportJobRepository`. Supports states: `pending`, `analyzing`, `analyzed`, `committing`, `committed`, `failed`.

3. **`/api/v1/imports/jobs/{job_id}/commit`**: Finalizes an import, creating `CourseRecord` and `TemplateRecord` records.

4. **`/api/v1/media/upload`** (`app/routers/media.py`): Media-focused upload (images, video, audio). 50MB limit, magic-byte validation, course-scoped storage. NOT suitable for documents.

5. **`ImportJob` model** (`app/models/persisted_course.py` lines 148-183): Tracks SCORM imports with `job_id`, `status`, `progress`, `course_id`, `source_file_path`, `error_message`, `result_data`.

6. **`ImportJobRepository`** (`app/repositories/import_job_repository.py`): Full CRUD with `create`, `get_by_id`, `update_status`, `update_result`, `update_course_id`, `list_by_status`, `delete`, `cleanup_old_pending`.

7. **`ImportService`** (`app/services/import_service.py`): Orchestrates ZIP extraction, payload discovery, schema inference, asset rewriting, template harvesting, and commit.

8. **`StorageService` / `AbstractStorage` / `LocalFileSystemStorage`** (`app/services/storage.py`): Abstract storage interface with local filesystem implementation. Used for SCORM packages but not wired to any document ingestion path.

### 4.2 What Is Missing (Gap Analysis)

| Capability | Current Status | This Story Delivers |
|------------|---------------|---------------------|
| PDF upload and extraction | Not supported | New `POST /ai/ingestions/upload` with placeholder extraction |
| DOCX upload and extraction | Not supported | Same endpoint with placeholder extraction |
| TXT/MD upload and extraction | Not supported | Same endpoint with basic heading-split extraction |
| Non-ZIP file type validation | Only `.zip` allowed | Extension + magic-byte validation for PDF/DOCX/TXT/MD |
| Dedicated ingestion DDL | No table for doc-source tracking | `ai_ingestion_jobs` table with full metadata |
| SHA-256 dedup | Not implemented | `get_by_file_hash()` with configurable window |
| Correlation / idempotency key | Not supported | `correlation_id` field on job and lookup |
| Session-bound ingestion | No session context | `session_id` FK (schema only; enforcement in US-AI-017) |
| Cross-reference to import_jobs | No linkage | `linked_import_job_id` column |
| Stale job cleanup | Only pending import_jobs | `cleanup_stale()` on ingestion_jobs |
| Binary storage management | Media has it; docs do not | `data/ingestion/` with sharded path |
| Feature flag gating | `ai_suggestions` exists but not ingestion | `AI_INGESTION_ENABLED` env var + conditional router |

---

## 5. Expansion Points

### 5.1 Immediate (MVP+1 -- US-AI-017)

| Expansion | What Changes |
|-----------|-------------|
| PDF extraction with PyMuPDF | Replace `_extract_pdf` placeholder with `fitz.open(stream=file_data)` calls; extract headings, paragraphs, tables, images, and their source offsets. |
| DOCX extraction with python-docx | Replace `_extract_docx` placeholder with `Document(stream)` iteration over paragraphs, runs, tables, and embedded images. |
| Authorization scoping | Verify `session_id` matches `ai_sessions` record; enforce user/org/course scope from session. |
| Resume / retry endpoint | `POST /ai/ingestions/{job_id}/retry` that re-queues a failed job for extraction. |
| Page plan preview endpoint | `GET /ai/ingestions/{job_id}/plan` returning the AI-segmented page breakdown (LLM call in US-AI-017). |

### 5.2 Future (Post-MVP)

| Expansion | What Changes |
|-----------|-------------|
| OCR for scanned PDFs | Integrate Tesseract or OCR service into the PDF extraction pipeline |
| Image extraction from documents | Save embedded images as `ExportAssetRecord` entries with content hashing |
| Support `.pptx` and `.xlsx` | Add to `FILE_TYPE_MAP` and implement section extractors |
| Cloud storage backend | `StorageService` abstraction already supports S3/GCS backends; swap `LocalFileSystemStorage` for `S3Storage` |
| Streaming upload | Enable `request.stream()` for files >100MB; update progress as chunks arrive |
| Virus scanning hook | Add `ClamAV` or cloud AV service call after file save, pre-extraction |
| Webhook on completion | `POST` to configured URL when job reaches `analyzed` or `failed` state |
| Admin UI for jobs | Expose `GET /api/v1/admin/ai/ingestions` with full filtering, pagination, and manual retry |

### 5.3 Cross-Cutting Integration Points

| Integration | Story | Specification |
|-------------|-------|---------------|
| AI session binding | US-AI-004 | `ai_ingestion_jobs.session_id` is an FK to `ai_sessions.job_id` (schema in this story; enforce in US-AI-017) |
| Page plan / segmentation | US-AI-017 | `GET /ai/ingestions/{job_id}/plan` consumed by LLM segmenter; uses `extracted_sections` as input |
| Batch proposal apply | US-AI-019 | Ingestion job ID stored on batch proposal for provenance |
| Durable workflow engine | US-AI-034 | Ingestion becomes first phase of `FileIngestionWorkflow` |
| Cost tracking | US-AI-036 | Log ingestion file_size and extraction duration as billable units |

---

## 6. Validation

### 6.1 Unit Tests

Add file: `tests/test_ai_ingestion_service.py`

| Test Case | What It Verifies | Expected Outcome |
|-----------|-----------------|------------------|
| `test_unsupported_file_type_rejected` | Upload `.exe` | `UnsupportedFileTypeError` raised |
| `test_file_too_large_rejected` | 60MB PDF | `FileTooLargeError` raised, 413 |
| `test_empty_file_rejected` | Zero-length upload | `CorruptFile` or magic-byte fail |
| `test_successful_txt_upload_and_analysis` | Small `.txt` | Job created, status=analyzed, extracted_sections populated |
| `test_successful_md_upload_with_headings` | Markdown with `##` headings | Sections match heading boundaries, correct char_count |
| `test_duplicate_upload_dedup` | Same file twice within 24h | Second call returns existing job_id |
| `test_duplicate_upload_different_correlation_id` | Same file, different correlation_id | Both accepted (no collision) |
| `test_zip_routes_to_import_service` | Valid SCORM zip | Job linked via `linked_import_job_id`, status=analyzed |
| `test_corrupt_zip_rejected` | Invalid ZIP bytes | Job status=failed, error_code=ZIP_ANALYSIS_FAILED |
| `test_get_job_not_found` | Random job_id | None returned |
| `test_delete_job_removes_file_and_record` | Existing job | DB row deleted, file removed from storage |
| `test_cleanup_stale_jobs` | Job older than 7 days | Row deleted by cleanup_stale() |
| `test_extract_plain_text_no_headings` | Plain text without markdown | Single section "Introduction" with full content |
| `test_extract_plain_text_empty` | Empty string | sections=[], warning NO_EXTRACTABLE_CONTENT |
| `test_job_lifecycle_transitions` | upload -> extracting -> analyzed | All states reachable, progress 0.0->1.0 |

### 6.2 Integration Tests

Add file: `tests/test_ai_ingestion_api.py`

| Test Case | What It Verifies |
|-----------|-----------------|
| `test_upload_endpoint_returns_201` | POST with valid .txt returns 201 + jobId |
| `test_upload_endpoint_rejects_exe` | POST with .exe returns 400 + UNSUPPORTED_FILE_TYPE |
| `test_poll_endpoint_returns_status` | GET /{jobId} returns status "uploaded" before extraction |
| `test_delete_endpoint_removes_job` | DELETE /{jobId} returns 200, subsequent GET returns 404 |
| `test_list_endpoint_returns_all` | GET / returns all jobs with total count |
| `test_list_endpoint_filters_by_status` | GET /?status=analyzed returns only analyzed jobs |
| `test_correlation_id_dedup` | POST with same correlation_id within window returns existing job |
| `test_zip_upload_creates_import_job` | POST .zip creates both ingestion_job and import_job, linked |

### 6.3 Error Scenario Tests (via `test_client`)

| Test | Steps | Expected |
|------|-------|----------|
| Upload without file field | POST with no `file` part | 422 validation error |
| Upload with oversized file | 60MB payload | 413 FILE_TOO_LARGE |
| Poll non-existent job | Random UUID | 404 JOB_NOT_FOUND |
| Delete non-existent job | Random UUID | 404 JOB_NOT_FOUND |
| Upload with empty filename | `file=("", bytes, "txt")` | 400 MISSING_FILENAME |
| Upload with valid PDF bytes but .txt extension | Content-type mismatch | Placeholder: accepted (magic-byte check is an expansion) |
| Concurrent uploads (rate limit) | 11 requests in 1 second | Only first 10 accepted; 11th returns 429 |

### 6.4 Security Tests

| Test | What It Verifies |
|------|-----------------|
| Path traversal in GET | `/../etc/passwd` style path is rejected (DELETE only; not a serving endpoint) |
| Large zip bomb | Recursive zip that expands to >2GB is caught by size limit or extraction timeout |
| Corrupt zip with zip-slip path | `__init__.py` with `/etc/passwd` path caught by `SUSPICIOUS_ARCHIVE` |
| File with no extractable content | `warnings` includes `NO_EXTRACTABLE_CONTENT` |

### 6.5 Manual QA Checklist

- [ ] Upload a 10-page PDF via the soon-to-exist frontend panel; confirm job is created and status transitions to `analyzed` within 5 seconds.
- [ ] Upload the same PDF twice; second upload returns the same `jobId` with a note that it is a duplicate.
- [ ] Upload a DOCX file with tables and images; confirmed `extracted_sections` includes text content (image extraction TBD).
- [ ] Upload a SCORM 1.2 ZIP; confirm `linked_import_job_id` is populated and the existing import job is accessible via `/api/v1/imports/jobs/{import_job_id}`.
- [ ] Upload a `.exe` file; confirm HTTP 400 with `UNSUPPORTED_FILE_TYPE`.
- [ ] Poll a completed job; confirm `extracted_sections` array is present and contains at least one section with `heading`, `content_preview`, `char_count`.
- [ ] Delete a completed job; confirm HTTP 200, then confirm GET returns 404.
- [ ] Check `data/ingestion/` directory is cleaned up after job deletion.
- [ ] Run `cleanup_stale` with a low max_age; confirm old jobs are removed.
- [ ] Set `AI_INGESTION_ENABLED=false`; confirm all routes return 404.

---

## 7. Definition of Done

### 7.1 Code Complete

- [ ] `app/models/ai_models.py` created with `AIngestionJob` ORM model.
- [ ] `app/repositories/ai_ingestion_repository.py` created with all CRUD methods, dedup lookup, and cleanup.
- [ ] `app/services/ai/ingestion_service.py` created with upload, extraction (TXT/MD), and ZIP routing logic.
- [ ] `app/routers/ai_ingestion.py` created with 4 endpoints: POST upload, GET status, DELETE, GET list.
- [ ] Router registered in `app/main.py` with feature flag guard.
- [ ] Alembic migration `20260614_0001_add_ai_ingestion_jobs.py` created and tested (upgrade + downgrade).
- [ ] `.env.example` updated with all new `AI_INGESTION_*` variables.
- [ ] Error handling covers all error codes listed in section 2.11.

### 7.2 Tests Passing

- [ ] All unit tests in `tests/test_ai_ingestion_service.py` pass (minimum 15 tests).
- [ ] All integration tests in `tests/test_ai_ingestion_api.py` pass (minimum 7 tests).
- [ ] Existing test suite (`pytest tests/`) remains green -- no regressions.
- [ ] Test coverage for the new code >= 85% (verified with `pytest --cov`).

### 7.3 Validation

- [ ] Manual QA checklist (section 6.5) is executed and signed off.
- [ ] Load test: 10 concurrent 10MB uploads does not crash the server or degrade response times beyond NFR targets.
- [ ] Feature flag gating verified: disabling the flag returns 404 for all ingestion routes.

### 7.4 Documentation

- [ ] OpenAPI spec (auto-generated from routers) includes all new endpoints and schemas.
- [ ] Cross-reference in `docs/AI_Implemenation/01_SystemArchitecture/File_Ingestion_Document_Import_Flow.mmd` updated to reference `POST /api/v1/ai/ingestions/upload` and `GET /api/v1/ai/ingestions/{job_id}`.
- [ ] `BACKEND_IMPLEMENTATION_SUMMARY.md` updated with the new ingestion foundation.

### 7.5 Cleanup

- [ ] No `print()` or `TODO` comments remain in committed code (use `# NOTE:` for known expansion points).
- [ ] Stale `temp_*` files from testing are not checked in.
- [ ] Migration has been run against a clean SQLite + PostgreSQL database without errors.

---

## 8. Tasks

### Task 1: Database and ORM Layer

**File:** `app/models/ai_models.py` (new), `alembic/versions/20260614_0001_add_ai_ingestion_jobs.py` (new)

- Create the `AIngestionJob` ORM model in `app/models/ai_models.py` following the `ImportJob` pattern in `app/models/persisted_course.py`.
- Import `AIngestionJob` in `app/main.py` startup (alongside the other model imports) so `Base.metadata.create_all` picks it up.
- Generate and test the Alembic migration with both `upgrade()` and `downgrade()`.
- Add `index=True` on `job_id`, `status`, `session_id`, `correlation_id`, `file_hash`.
- Verify that `sqlite+aiosqlite://` (test) and `postgresql+asyncpg://` (production) both create the table correctly.

**Acceptance criteria:**
- `AIngestionJob` model has all columns from the DDL in section 2.1.
- Migration downgrade drops the table and indexes.
- `AIngestionJob.to_dict()` returns all fields as camelCase keys.

### Task 2: Repository Layer

**File:** `app/repositories/ai_ingestion_repository.py` (new)

- Implement `AIngestionRepository` following the `ImportJobRepository` pattern.
- Methods: `create`, `get_by_id`, `get_by_correlation_id`, `get_by_file_hash`, `update_status`, `update_extraction`, `link_import_job`, `delete`, `list_by_status`, `cleanup_stale`.
- `get_by_file_hash` must include a `max_age_hours` cutoff so dedup only applies within the configurable window.
- `update_extraction` atomically sets `status=analyzed`, `extracted_sections`, `detected_type`, `source_metadata`, `warnings`, and `progress=1.0`.
- `cleanup_stale` uses `delete` (not soft-delete) because the stored file must also be cleaned up by the caller.

**Acceptance criteria:**
- `create` returns a persisted `AIngestionJob` with a UUID `job_id`.
- `get_by_id` returns None for unknown IDs.
- `get_by_file_hash` returns None when no match within the window.
- `update_extraction` transitions the job to `analyzed` and sets sections.
- `cleanup_stale` removes rows older than `max_age_hours`.

### Task 3: Service Layer -- Ingestion Service

**File:** `app/services/ai/ingestion_service.py` (new)

- Implement `IngestionService` with all methods from section 2.10.
- `upload_and_analyze` implements the full pipeline: type validation, size check, SHA-256, dedup check, file save, job creation, extraction dispatch.
- TXT/MD extraction uses the heading-split algorithm from `_extract_plain_text`.
- PDF and DOCX extraction are stubs that return `([], {})` with a log warning. The stubs MUST be explicitly documented as expansion points so future developers know where to plug in PyMuPDF and python-docx.
- ZIP handling instantiates `ImportService` and calls `analyze_package`, then calls `link_import_job`.
- `get_job`, `delete_job`, `list_jobs`, `cleanup_stale` delegate to the repository.
- All config values loaded from `os.getenv` with the defaults listed in section 2.4.

**Acceptance criteria:**
- TXT upload produces `extracted_sections` with correct heading boundaries.
- MD upload with `## Level 2` headings creates correct section split.
- Empty TXT returns `warnings: ["NO_EXTRACTABLE_CONTENT"]`.
- ZIP upload delegates to `ImportService` and sets `linked_import_job_id`.
- PDF upload (stub) creates job with status `analyzed` and empty sections.
- Dedup: same SHA-256 within 24h returns existing `job_id`.
- `cleanup_stale` deletes jobs older than the specified hours.

### Task 4: Router Layer

**File:** `app/routers/ai_ingestion.py` (new)

- Implement all four endpoints with the exact request/response models from section 2.5.
- POST `/upload` reads the file with `await file.read()`, validates filename, then calls `service.upload_and_analyze`.
- Error handlers catch `UnsupportedFileTypeError` (400), `FileTooLargeError` (413), `IngestionServiceError` (500).
- GET `/{job_id}` returns `IngestionStatusResponse` or 404.
- DELETE `/{job_id}` returns `IngestionDeleteResponse` or 404.
- GET `/` returns `IngestionListResponse` with optional `?status=` filter.
- Register the router in `app/main.py` under the `api_router` with a feature flag check:

```python
if os.getenv("AI_INGESTION_ENABLED", "true").lower() == "true":
    api_router.include_router(ai_ingestion.router)
```

**Acceptance criteria:**
- `POST /api/v1/ai/ingestions/upload` with a valid .txt returns 201 and `jobId`.
- `POST` with `.exe` returns 400 and error code `UNSUPPORTED_FILE_TYPE`.
- `GET /api/v1/ai/ingestions/{job_id}` returns job data for an existing job.
- `GET /api/v1/ai/ingestions/{job_id}` returns 404 for a non-existent job.
- `DELETE /api/v1/ai/ingestions/{job_id}` returns 200 and subsequent GET returns 404.
- `GET /api/v1/ai/ingestions` returns a list with `total` count.
- Setting `AI_INGESTION_ENABLED=false` causes all four routes to return 404.

### Task 5: Configuration and Feature Flagging

**Files:** `.env.example`, `app/main.py`

- Add all `AI_INGESTION_*` variables to `.env.example` with documentation comments (see section 2.7).
- Add the conditional router registration guard in `app/main.py`.
- Ensure the existing `AI_AUTHORING_ENABLED` check also gates ingestion (ingestion should not work if AI authoring is disabled globally).

**Acceptance criteria:**
- `.env.example` contains all new variables with defaults.
- Setting `AI_AUTHORING_ENABLED=false` makes all ingestion routes return 404.
- Setting `AI_INGESTION_ENABLED=false` makes all ingestion routes return 404 (narrower gate).

### Task 6: Unit Tests

**File:** `tests/test_ai_ingestion_service.py` (new)

- 15+ unit tests covering the test scenarios in section 6.1.
- Use pytest-asyncio (the project already has `asyncio_mode = auto` in pytest.ini).
- Create a fixture that provides an `IngestionService` bound to the test session:

```python
@pytest.fixture
async def ingestion_service(test_session) -> IngestionService:
    return IngestionService(test_session)
```

- Mock `ImportService` for ZIP tests to avoid full SCORM parsing:

```python
@pytest.fixture
def mock_import_service(mocker):
    return mocker.patch(
        "app.services.ai.ingestion_service.ImportService",
        return_value=AsyncMock(spec=ImportService),
    )
```

**Acceptance criteria:**
- All 15+ tests pass in isolation.
- `pytest tests/test_ai_ingestion_service.py --cov=app.services.ai.ingestion_service --cov=app.repositories.ai_ingestion_repository` reports >= 85% coverage.

### Task 7: Integration / API Tests

**File:** `tests/test_ai_ingestion_api.py` (new)

- 7+ integration tests covering the test scenarios in section 6.2.
- Use the existing `test_client` fixture from `tests/conftest.py`.
- For ZIP tests, build a minimal SCORM-like ZIP using the same `_build_import_zip` pattern from `test_import_discovery.py`.
- Verify full lifecycle: upload -> poll -> verify extracted_sections -> delete.

**Acceptance criteria:**
- All API tests pass against the test client.
- Full end-to-end: uploading a `.txt` results in a pollable job with `analyzed` status and non-empty sections.

### Task 8: Stale Job Cleanup Scheduler

**File:** `app/services/ai/ingestion_service.py` (add method), `app/main.py` (lifespan hook)

- `IngestionService.cleanup_stale` already exists in the repository.
- Add a lifespan periodic task in `app/main.py` that runs cleanup on a schedule:

```python
import asyncio

async def _periodic_ingestion_cleanup():
    while True:
        try:
            async with SessionLocal() as session:
                service = IngestionService(session)
                count = await service.cleanup_stale()
                if count:
                    logger.info("Ingestion cleanup: removed %d stale jobs", count)
        except Exception:
            logger.exception("Ingestion cleanup error")
        await asyncio.sleep(3600)  # every hour
```

Wire into `lifespan`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing startup ...
    cleanup_task = asyncio.create_task(_periodic_ingestion_cleanup())
    yield
    cleanup_task.cancel()
```

**Acceptance criteria:**
- Cleanup runs every hour and removes ingestion jobs older than 7 days.
- Cleanup does not crash the server on error (logged and continues).

### Task 9: OpenAPI Documentation Alignment

- Run the app and verify the new endpoints appear in `/api/v1/docs` under the "AI Ingestion" tag.
- Verify that `IngestionStatusResponse`, `IngestionUploadResponse`, `IngestionDeleteResponse`, and `IngestionListResponse` schemas are present in the OpenAPI schema.

**Acceptance criteria:**
- Swagger UI shows all four endpoints with correct request/response models.
- Example values and descriptions render correctly.

### Task 10: Manual QA and Load Test

- Execute the manual QA checklist from section 6.5.
- Run a load test with 10 concurrent 10MB uploads using `httpx` or `locust`.
- Verify that the server does not crash and that response times stay under 500ms for upload acceptance and under 100ms for polling.

**Acceptance criteria:**
- All QA checklist items pass.
- Load test shows no errors and meets NFR targets.

---

**End of US-AI-016**

---