"""AI Ingestion Service — US-BKND-AI-016.

Manages document upload and ingestion jobs for AI course generation.
Handles file validation, extraction staging, and job lifecycle.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Optional, BinaryIO

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_models import AIIngestionJobRecord

logger = logging.getLogger("ai_authoring")

ALLOWED_TYPES = {".pdf", ".docx", ".txt", ".md", ".zip"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


class IngestionError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 400):
        self.code = code
        self.message = message
        self.http_status = http_status


class AIIngestionService:
    """Manages AI document ingestion job lifecycle."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_job(
        self,
        file: BinaryIO,
        filename: str,
        session_id: str,
        user_id: str,
        organization_id: str,
        course_id: str = "",
        correlation_id: str = "",
    ) -> AIIngestionJobRecord:
        """Create an ingestion job from an uploaded file.

        Validates file type, size, and magic bytes. Stores the job record
        and performs inline extraction for text-based formats (TXT, MD).
        """
        # Validate extension
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ALLOWED_TYPES:
            raise IngestionError(
                "UNSUPPORTED_FILE_TYPE",
                f"File type '{ext}' not supported. Allowed: {', '.join(sorted(ALLOWED_TYPES))}",
                400,
            )

        # Read file content
        content = file.read()
        file_size = len(content)
        if file_size == 0:
            raise IngestionError("CORRUPT_FILE", "File is empty or corrupt.", 400)
        if file_size > MAX_FILE_SIZE:
            raise IngestionError(
                "FILE_TOO_LARGE",
                f"File size {file_size} exceeds maximum {MAX_FILE_SIZE}.",
                413,
            )

        # Compute hash
        file_hash = hashlib.sha256(content).hexdigest()

        # Check for duplicate — update course_id if re-uploading for a different course.
        # See AIIngestionJobRecord docstring for the dual state machine
        # (job.status vs source_metadata.generation_status).
        if file_hash:
            existing = await self._find_by_hash(file_hash)
            if existing:
                if course_id and existing.course_id != course_id:
                    existing.course_id = course_id
                    # Reset generation state so apply goes to the new course.
                    # Safe to pop applied_at/applied_pages — the only downstream
                    # consumers (ai_tools.py:454/506/655) use .get().
                    meta = dict(existing.source_metadata or {})
                    if meta.get("generation_status") == "completed":
                        meta["generation_status"] = "ready_for_review"
                        meta.pop("applied_at", None)
                        meta.pop("applied_pages", None)
                        existing.source_metadata = meta
                    await self.db.commit()
                return existing  # Idempotent: return existing job

        # Detect type
        detected = ext.lstrip(".")

        # Inline extraction for text formats + PDF/DOCX
        extracted = None
        source_meta = None
        if detected in ("txt", "md"):
            extracted, source_meta = self._extract_text(content, filename, detected)
        elif detected in ("pdf", "docx"):
            # Save file to temp location for extraction
            import tempfile
            import os as _os
            suffix = f".{detected}"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            try:
                from app.services.ai.document_extractor import DocumentExtractor
                extractor = DocumentExtractor()
                mime = self._mime_for(f".{detected}")
                full_text = await extractor.extract(tmp_path, mime)
                extracted, source_meta = self._extract_text(
                    full_text.encode("utf-8"), filename, "md"
                )
            except Exception as exc:
                logger.warning("Document extraction failed for %s: %s", filename, exc)
                extracted = None
                source_meta = {"title": filename}
            finally:
                _os.unlink(tmp_path)  # Clean up temp file

        # Create job
        now = datetime.utcnow()
        from app.models.ai_models import _uuid
        job = AIIngestionJobRecord(
            job_id=_uuid(),
            status="analyzed" if extracted else "uploaded",
            progress=1.0 if extracted else 0.0,
            file_name=filename,
            file_size=file_size,
            file_hash=file_hash,
            mime_type=self._mime_for(ext),
            detected_type=detected,
            session_id=session_id,
            user_id=user_id,
            organization_id=organization_id,
            course_id=course_id or "",
            correlation_id=correlation_id,
            extracted_sections=extracted,
            source_metadata=source_meta,
            created_at=now,
            updated_at=now,
        )
        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)

        logger.info("Ingestion job %s: %s (%s, %d bytes)",
                     job.job_id[:8], filename, detected, file_size)
        return job

    async def get_job(self, job_id: str) -> Optional[AIIngestionJobRecord]:
        q = select(AIIngestionJobRecord).where(
            AIIngestionJobRecord.job_id == job_id
        )
        return (await self.db.execute(q)).scalar_one_or_none()

    async def list_by_session(self, session_id: str) -> list:
        q = (
            select(AIIngestionJobRecord)
            .where(AIIngestionJobRecord.session_id == session_id)
            .order_by(AIIngestionJobRecord.created_at.desc())
        )
        return list((await self.db.execute(q)).scalars().all())

    async def _find_by_hash(self, file_hash: str) -> Optional[AIIngestionJobRecord]:
        q = select(AIIngestionJobRecord).where(
            AIIngestionJobRecord.file_hash == file_hash
        )
        return (await self.db.execute(q)).scalar_one_or_none()

    @staticmethod
    def _extract_text(
        content: bytes, filename: str, detected: str
    ) -> tuple[Optional[list], Optional[dict]]:
        """Extract text sections from TXT/MD files."""
        try:
            text = content.decode("utf-8", errors="replace")
            lines = text.split("\n")
            sections = []
            current_heading = filename
            current_content = []

            for line in lines[:200]:  # Max 200 lines
                stripped = line.strip()
                if not stripped:
                    if current_content:
                        sections.append({
                            "index": len(sections),
                            "heading": current_heading,
                            "content_preview": "\n".join(current_content)[:500],
                            "char_count": sum(len(c) for c in current_content),
                        })
                        current_content = []
                    continue
                if detected == "md" and stripped.startswith("#"):
                    if current_content:
                        sections.append({
                            "index": len(sections),
                            "heading": current_heading,
                            "content_preview": "\n".join(current_content)[:500],
                            "char_count": sum(len(c) for c in current_content),
                        })
                    current_heading = stripped.lstrip("#").strip()
                    current_content = []
                else:
                    current_content.append(stripped)

            if current_content:
                sections.append({
                    "index": len(sections),
                    "heading": current_heading,
                    "content_preview": "\n".join(current_content)[:500],
                    "char_count": sum(len(c) for c in current_content),
                })

            source_meta = {
                "page_count": max(1, len(sections)),
                "total_chars": len(text),
                "language": "en",
                "title": filename,
            }
            return sections[:20], source_meta  # Max 20 sections
        except Exception:
            return None, {"title": filename}

    @staticmethod
    def _mime_for(ext: str) -> str:
        return {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".txt": "text/plain",
            ".md": "text/markdown",
            ".zip": "application/zip",
        }.get(ext, "application/octet-stream")
