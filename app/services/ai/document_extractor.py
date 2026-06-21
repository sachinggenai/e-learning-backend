"""Document text extraction for PDF and DOCX files — US-PEND-021.

Extracts text from uploaded documents so the AI can generate course content
from existing training materials. Integrates into ingestion_service.py.

Supported formats:
    - PDF via pdfplumber
    - DOCX via python-docx
    - TXT/MD (passthrough — already handled by ingestion_service._extract_text)
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("ai_authoring")


class DocumentExtractor:
    """Extracts text from PDF and DOCX files for AI course generation.

    Usage:
        extractor = DocumentExtractor()
        text = await extractor.extract(file_path, mime_type)
    """

    # Maximum pages to process (safety limit for large documents)
    MAX_PAGES = 100
    # Maximum characters to extract (prevents token overflow)
    MAX_CHARS = 500_000

    async def extract(self, file_path: str, mime_type: str) -> str:
        """Extract text from a document file.

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
            return await self._extract_docx(file_path)
        else:
            raise ValueError(f"Unsupported MIME type for extraction: {mime_type}")

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

    async def _extract_docx(self, file_path: str) -> str:
        """Extract text from a DOCX file using python-docx."""
        try:
            import docx
        except ImportError:
            raise ImportError(
                "python-docx is required for DOCX extraction. "
                "Install with: pip install python-docx>=1.0.0"
            )

        try:
            doc = docx.Document(file_path)
            text_parts = []
            for para in doc.paragraphs:
                if para.text.strip():
                    text_parts.append(para.text)
                if sum(len(t) for t in text_parts) > self.MAX_CHARS:
                    break

            # Also extract text from tables
            for table in doc.tables:
                for row in table.rows:
                    row_text = " | ".join(
                        cell.text for cell in row.cells if cell.text.strip()
                    )
                    if row_text:
                        text_parts.append(row_text)

            full_text = "\n".join(text_parts)
            logger.info(
                "Extracted %d chars from DOCX: %s", len(full_text), file_path
            )
            return full_text[:self.MAX_CHARS]
        except Exception as exc:
            logger.error("DOCX extraction failed for %s: %s", file_path, exc)
            raise ValueError(f"Failed to extract text from DOCX: {exc}") from exc
