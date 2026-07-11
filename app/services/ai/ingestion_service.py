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
                        meta.pop("content_fingerprint", None)
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

                if detected == "docx":
                    # ── TRD-CGQ Phase 1: Structured DOCX extraction ──
                    # Uses real paragraph styles for accurate section detection
                    structured = extractor.extract_structured(tmp_path)
                    raw_text = structured.get("raw_text", "")
                    paragraphs = structured.get("paragraphs", [])

                    # ── Template Marking System: check for markers before splitting ──
                    from app.services.ai.marked_document_parser import (
                        MarkedDocumentParser,
                    )
                    from app.services.ai.config import get_ai_config

                    cfg = get_ai_config()
                    if cfg.template_marking_enabled:
                        marker_parser = MarkedDocumentParser(
                            max_pages=cfg.template_marking_max_pages,
                            strict_mode=cfg.template_marking_strict_mode,
                        )
                        if marker_parser.has_markers(paragraphs):
                            marked_doc = marker_parser.parse(paragraphs)
                            has_errors = any(
                                e.severity == "error"
                                for e in marked_doc.parse_errors
                            )
                            if has_errors:
                                # Store errors for user feedback
                                source_meta = {
                                    "marked_document": marked_doc.to_dict(),
                                    "marker_status": "parse_error",
                                    "title": filename,
                                    "paragraph_count": len(paragraphs),
                                    "error_count": len([
                                        e for e in marked_doc.parse_errors
                                        if e.severity == "error"
                                    ]),
                                    "warning_count": len([
                                        e for e in marked_doc.parse_errors
                                        if e.severity == "warning"
                                    ]),
                                }
                                extracted = None
                                logger.warning(
                                    "Marker parse errors in %s: %d errors, %d warnings",
                                    filename,
                                    source_meta["error_count"],
                                    source_meta["warning_count"],
                                )
                            else:
                                # Successful marker parse
                                sections = _marked_doc_to_sections(marked_doc)
                                extracted = [s.to_dict() for s in sections]
                                source_meta = {
                                    "marked_document": marked_doc.to_dict(),
                                    "marker_status": "parsed",
                                    "page_count": len(marked_doc.pages),
                                    "total_chars": sum(
                                        len(p.raw_content)
                                        for p in marked_doc.pages
                                    ),
                                    "language": "en",
                                    "title": filename,
                                    "paragraph_count": len(paragraphs),
                                    "heading_count": sum(
                                        1 for p in paragraphs
                                        if p.get("is_heading")
                                    ),
                                }
                                logger.info(
                                    "Template markers parsed in %s: %d pages, %d components",
                                    filename,
                                    len(marked_doc.pages),
                                    sum(len(p.components) for p in marked_doc.pages),
                                )
                        else:
                            # No markers — use existing DocumentSplitter
                            from app.services.ai.document_splitter import DocumentSplitter
                            splitter = DocumentSplitter(use_llm=False)
                            sections = splitter.split_structured(paragraphs, filename)
                            extracted = [s.to_dict() for s in sections]
                            source_meta = {
                                "page_count": len(sections),
                                "total_chars": sum(s.char_count for s in sections),
                                "language": "en",
                                "title": filename,
                                "splitter_method": "structured_paragraphs",
                                "paragraph_count": len(paragraphs),
                                "heading_count": sum(1 for p in paragraphs if p.get("is_heading")),
                            }
                    else:
                        # Feature flag off — existing pipeline unchanged
                        from app.services.ai.document_splitter import DocumentSplitter
                        splitter = DocumentSplitter(use_llm=False)
                        sections = splitter.split_structured(paragraphs, filename)
                        extracted = [s.to_dict() for s in sections]
                        source_meta = {
                            "page_count": len(sections),
                            "total_chars": sum(s.char_count for s in sections),
                            "language": "en",
                            "title": filename,
                            "splitter_method": "structured_paragraphs",
                            "paragraph_count": len(paragraphs),
                            "heading_count": sum(1 for p in paragraphs if p.get("is_heading")),
                        }
                else:
                    # PDF: existing flow (pdfplumber doesn't expose styles)
                    mime = self._mime_for(f".{detected}")
                    full_text = await extractor.extract(tmp_path, mime)
                    extracted, source_meta = self._extract_text(
                        full_text.encode("utf-8"), filename, "md"
                    )
                    if source_meta:
                        source_meta["splitter_method"] = "blank_line_split"
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


# ── Template Marking System helper ────────────────────────────────────


def _marked_doc_to_sections(marked_doc) -> list:
    """Convert a MarkedDocument to the section dict format expected by the pipeline.

    Each page becomes one "section" with its component structure preserved
    in the content_preview. The full MarkedDocument is stored in
    source_metadata for the breakdown and generation steps.
    """
    from app.services.ai.document_splitter import Section

    sections = []
    for i, page in enumerate(marked_doc.pages):
        heading = page.title or f"Page {i + 1}"
        content_parts = []
        for comp in page.components:
            content_parts.append(f"[{comp.component_type}] {comp.raw_content}")
            for item in comp.items:
                content_parts.append(
                    f"  [{item.item_type}] {item.title}: {item.content}"
                )
        content = "\n".join(content_parts)
        sections.append(Section(
            index=i,
            heading=heading,
            content=content,
            content_preview=content[:500],
            char_count=len(content),
            source_style="marker",
        ))
    return sections
