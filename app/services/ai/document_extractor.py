"""Document text extraction for PDF and DOCX files — US-PEND-021.

Extracts text from uploaded documents so the AI can generate course content
from existing training materials. Integrates into ingestion_service.py.

Supported formats:
    - PDF via pdfplumber
    - DOCX via python-docx (with paragraph style preservation per TRD R1)
    - TXT/MD (passthrough — already handled by ingestion_service._extract_text)

TRD-CGQ Phase 1: DOCX extraction now preserves paragraph style metadata
(style_name, is_heading, heading_level) so DocumentSplitter can use REAL
heading styles instead of degraded regex heuristics.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ai_authoring")


class DocumentExtractor:
    """Extracts text from PDF and DOCX files for AI course generation.

    Usage:
        extractor = DocumentExtractor()
        text = await extractor.extract(file_path, mime_type)           # plain text (backward compat)
        structured = extractor.extract_structured(file_path)            # DOCX with paragraph styles
    """

    # Maximum pages to process (safety limit for large documents)
    MAX_PAGES = 100
    # Maximum characters to extract (prevents token overflow)
    MAX_CHARS = 500_000

    async def extract(self, file_path: str, mime_type: str) -> str:
        """Extract text from a document file (backward-compatible plain text).

        Args:
            file_path: Absolute path to the uploaded file.
            mime_type: MIME type (e.g. "application/pdf",
                       "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

        Returns:
            Extracted plain text.

        Raises:
            ValueError: Unsupported MIME type.
            FileNotFoundError: File does not exist at file_path.
        """
        if mime_type == "application/pdf":
            return await self._extract_pdf(file_path)
        elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            structured = self._extract_docx_structured(file_path)
            return structured["raw_text"]
        else:
            raise ValueError(f"Unsupported MIME type for extraction: {mime_type}")

    def extract_structured(self, file_path: str) -> Dict[str, Any]:
        """Extract structured paragraph data from a DOCX file.

        TRD-CGQ R1: Preserves real paragraph style metadata from python-docx
        so DocumentSplitter can use Heading 1/2/3 styles for accurate section
        boundary detection — not degraded regex heuristics.

        Args:
            file_path: Absolute path to the uploaded DOCX file.

        Returns:
            dict with:
                raw_text: str — plain text (backward compatible)
                paragraphs: List[dict] — each with {style_name, text, is_heading, heading_level}
                table_text: str — extracted table content
                total_chars: int

        Raises:
            ValueError: File cannot be read or is not a valid DOCX.
            ImportError: python-docx not installed.
        """
        return self._extract_docx_structured(file_path)

    async def _extract_pdf(self, file_path: str) -> str:
        """Extract text from a PDF file using pdfplumber."""
        try:
            import pdfplumber
        except ImportError:
            raise ImportError(
                "pdfplumber is required for PDF extraction. "
                "Install with: pip install pdfplumber>=0.10.0"
            )

        text_parts = []
        try:
            with pdfplumber.open(file_path) as pdf:
                pages = pdf.pages[:self.MAX_PAGES]
                logger.info(
                    "Extracting text from PDF: %d pages (max %d)",
                    len(pdf.pages), self.MAX_PAGES,
                )
                for page in pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
                    if sum(len(t) for t in text_parts) > self.MAX_CHARS:
                        break
        except Exception as exc:
            logger.error("PDF extraction failed for %s: %s", file_path, exc)
            raise ValueError(f"Failed to extract text from PDF: {exc}") from exc

        full_text = "\n\n".join(text_parts)
        return full_text[:self.MAX_CHARS]

    # ── DOCX: backward-compatible plain text (delegates to structured) ─

    async def _extract_docx(self, file_path: str) -> str:
        """Extract plain text from a DOCX file (backward compatible)."""
        structured = self._extract_docx_structured(file_path)
        return structured["raw_text"]

    # ── DOCX: structured extraction with paragraph styles (TRD R1) ────

    def _extract_docx_structured(self, file_path: str) -> Dict[str, Any]:
        """Extract structured paragraph data from DOCX preserving style metadata.

        TRD-CGQ R1 fix: Previously _extract_docx() discarded para.style.name.
        Now we preserve it so DocumentSplitter can use REAL heading styles
        (Heading 1, Heading 2, etc.) instead of degraded regex heuristics
        on flattened text.

        Returns dict with:
            raw_text: str — plain text joined by newlines (backward compatible)
            paragraphs: List[dict] — [{style_name, text, is_heading, heading_level}, ...]
            table_text: str — extracted table content
            total_chars: int — total character count
        """
        try:
            import docx
        except ImportError:
            raise ImportError(
                "python-docx is required for DOCX extraction. "
                "Install with: pip install python-docx>=1.0.0"
            )

        try:
            doc = docx.Document(file_path)
            paragraphs: List[Dict[str, Any]] = []
            text_parts: List[str] = []
            total_chars = 0

            for para in doc.paragraphs:
                text = para.text.strip()
                if not text:
                    continue

                # ── Preserve REAL paragraph style metadata (TRD R1) ──
                style_name = para.style.name if para.style else "Normal"
                is_heading = (
                    style_name.startswith("Heading")
                    or style_name.startswith("heading")
                    or style_name.lower() in ("title", "subtitle")
                )
                heading_level = 0
                if is_heading:
                    # Parse "Heading 1" → 1, "Heading 2" → 2, etc.
                    parts = style_name.split()
                    if len(parts) > 1 and parts[-1].isdigit():
                        heading_level = int(parts[-1])
                    elif style_name.lower() == "title":
                        heading_level = 1  # Title = top-level heading
                    elif style_name.lower() == "subtitle":
                        heading_level = 2
                    else:
                        heading_level = 1  # Generic heading

                paragraphs.append({
                    "style_name": style_name,
                    "text": text,
                    "is_heading": is_heading,
                    "heading_level": heading_level,
                })
                text_parts.append(text)
                total_chars += len(text)

                if total_chars > self.MAX_CHARS:
                    break

            # ── Extract table text ──────────────────────────────────
            table_lines: List[str] = []
            for table in doc.tables:
                for row in table.rows:
                    row_text = " | ".join(
                        cell.text for cell in row.cells if cell.text.strip()
                    )
                    if row_text:
                        table_lines.append(row_text)
                        total_chars += len(row_text)

            table_text = "\n".join(table_lines)
            raw_text = "\n".join(text_parts)[:self.MAX_CHARS]

            logger.info(
                "Extracted %d chars, %d paragraphs (%d headings) from DOCX: %s",
                total_chars, len(paragraphs),
                sum(1 for p in paragraphs if p["is_heading"]),
                file_path,
            )

            return {
                "raw_text": raw_text,
                "paragraphs": paragraphs,
                "table_text": table_text,
                "total_chars": min(total_chars, self.MAX_CHARS),
            }
        except Exception as exc:
            logger.error("DOCX extraction failed for %s: %s", file_path, exc)
            raise ValueError(f"Failed to extract text from DOCX: {exc}") from exc
