"""Semantic document section splitter — TRD-CGQ Phase 1.

Replaces naive blank-line splitting (_extract_text) with semantic boundary
detection. Uses python-docx paragraph styles for DOCX, heading detection
for MD/TXT, and optional LLM pass for semantic boundaries.

Primary path (R1 fix): _split_by_structured_paragraphs() consumes REAL
paragraph style metadata from DocumentExtractor.extract_structured().
Fallback: _split_by_heading_heuristics() for TXT/MD/PDF/flat text.

LLM-free mode: Uses typographic heuristics (paragraph styles, heading
patterns, numbered lists, section breaks) to detect logical boundaries.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Section:
    """A semantically coherent section of a document.

    Attributes:
        index: Zero-based position in the document.
        heading: Detected heading or "Untitled Section N".
        content: Full section text.
        content_preview: First 500 chars (for LLM prompts / API responses).
        char_count: Total character count.
        features: Content features for template selection (filled later by FeatureDetector).
        source_style: How the section boundary was detected ("heading_style", "md_heading", "heuristic").
    """
    index: int
    heading: str
    content: str
    content_preview: str = ""
    char_count: int = 0
    features: Optional[dict] = None
    source_style: str = "heuristic"

    def __post_init__(self):
        if not self.content_preview:
            self.content_preview = self.content[:500]
        if not self.char_count:
            self.char_count = len(self.content)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to the dict format expected by ingestion_service / API."""
        return {
            "index": self.index,
            "heading": self.heading,
            "content_preview": self.content_preview,
            "char_count": self.char_count,
            "source_style": self.source_style,
        }


class DocumentSplitter:
    """Splits extracted text into semantic sections.

    Two primary entry points:
        split_structured(paragraphs, filename)  — DOCX with real style metadata (R1)
        split(text, filename, fmt)              — TXT/MD/PDF/flat text (heuristic)

    Usage:
        splitter = DocumentSplitter(use_llm=False)  # Pure heuristics
        sections = splitter.split(text, filename, detected_format)

        splitter = DocumentSplitter(use_llm=True)    # LLM-enhanced (Phase 3)
        sections = await splitter.split_async(text, filename, detected_format)
    """

    def __init__(self, use_llm: bool = False, llm_client=None):
        self.use_llm = use_llm
        self.llm_client = llm_client

    # ── Public API ─────────────────────────────────────────────────────

    def split(self, text: str, filename: str, fmt: str = "md") -> List[Section]:
        """Split text into sections using heuristics only.

        Args:
            text: Plain text content.
            filename: Original filename (used as fallback heading).
            fmt: Format hint — "md", "txt", "docx", "pdf".

        Returns:
            List of Section objects (at least 1).
        """
        if not text or not text.strip():
            return [self._make_section(0, filename, [])]

        if fmt in ("md", "txt"):
            return self._split_by_headings(text, filename)
        # For docx/pdf that went through plain-text extraction (backward compat)
        return self._split_by_heading_heuristics(text, filename)

    async def split_async(
        self, text: str, filename: str, fmt: str = "md"
    ) -> List[Section]:
        """Split text into sections, optionally using LLM for semantic boundaries.

        Phase 1: LLM refinement is a no-op (use_llm defaults to False).
        Phase 3: When use_llm=True with llm_client, calls _llm_refine_boundaries.
        """
        sections = self.split(text, filename, fmt)
        if self.use_llm and self.llm_client and len(sections) > 1:
            sections = await self._llm_refine_boundaries(sections)
        return sections

    def split_structured(
        self, paragraphs: List[Dict[str, Any]], filename: str
    ) -> List[Section]:
        """Primary DOCX boundary detector: uses REAL paragraph styles from python-docx.

        TRD-CGQ R1 fix: Consumes structured paragraph data (with style_name,
        is_heading, heading_level) from DocumentExtractor.extract_structured().
        This is the accurate path — no regex guessing.

        Args:
            paragraphs: List of dicts from DocumentExtractor, each with:
                {style_name, text, is_heading, heading_level}
            filename: Original filename (fallback heading).

        Returns:
            List of Section objects.
        """
        if not paragraphs:
            return [self._make_section(0, filename, [])]

        sections: List[Section] = []
        current_lines: List[str] = []
        current_heading = filename
        current_style = "heading_style"

        for para in paragraphs:
            text = para.get("text", "")

            # ── REAL heading detection from style metadata ──────────
            if para.get("is_heading"):
                if current_lines:
                    sections.append(self._make_section(
                        len(sections), current_heading, current_lines, current_style,
                    ))
                current_heading = text  # Use the heading's own text
                current_lines = []
                current_style = "heading_style"
                continue

            current_lines.append(text)

        # Don't forget the last section
        if current_lines:
            sections.append(self._make_section(
                len(sections), current_heading, current_lines, current_style,
            ))

        # ── Fallback: if no heading styles found, try text heuristics ──
        if len(sections) <= 1:
            flat_text = "\n".join(p.get("text", "") for p in paragraphs)
            heuristic_sections = self._split_by_heading_heuristics(flat_text, filename)
            if len(heuristic_sections) > len(sections):
                return heuristic_sections

        return sections

    # ── Heuristic Splitters (TXT / MD / PDF / fallback) ─────────────────

    def _split_by_headings(self, text: str, filename: str) -> List[Section]:
        """MD/TXT: detect sections by markdown headings and blank-line groups.

        Uses markdown heading markers (#, ##, etc.) as primary boundaries.
        Groups content between headings. Falls back to blank-line paragraph
        grouping when no headings are present.
        """
        lines = text.split("\n")
        sections: List[Section] = []
        current_lines: List[str] = []
        current_heading = filename
        current_style = "heuristic"

        for line in lines:
            stripped = line.strip()

            # Markdown heading (#, ##, ###, etc.)
            if stripped.startswith("#"):
                if current_lines:
                    sections.append(self._make_section(
                        len(sections), current_heading, current_lines, current_style,
                    ))
                current_heading = stripped.lstrip("#").strip()
                current_lines = []
                current_style = "md_heading"
                continue

            # Blank line = potential section boundary
            if not stripped:
                # Only split when we have enough accumulated content
                if len(current_lines) > 3:
                    sections.append(self._make_section(
                        len(sections), current_heading, current_lines, current_style,
                    ))
                    current_heading = filename
                    current_lines = []
                    current_style = "heuristic"
                continue

            current_lines.append(line)

        # Don't forget the last section
        if current_lines:
            sections.append(self._make_section(
                len(sections), current_heading, current_lines, current_style,
            ))

        return sections if sections else [self._make_section(0, filename, lines)]

    def _split_by_heading_heuristics(self, text: str, filename: str) -> List[Section]:
        """Fallback: detect sections by typographic heading patterns.

        Used when no structural metadata is available (PDF, flat TXT, DOCX
        without heading styles). Detects:
        - ALL CAPS short lines (< 120 chars)
        - Numbered headings ("Module 1", "Section 2.3", "1. Topic")
        - Title-case phrases (10-60 chars, starts with capital)
        - Lines ending with colon (potential topic marker)
        """
        lines = text.split("\n")
        sections: List[Section] = []
        current_lines: List[str] = []
        current_heading = filename

        # Pre-compiled heading patterns
        heading_patterns = [
            # ALL CAPS short line (typical for PowerPoint-exported headings)
            re.compile(r'^[A-Z][A-Z0-9\s\-\–\.\,\:\;\!\/\(\)]{4,119}$'),
            # Numbered module/unit/lesson/chapter/section/topic/part
            re.compile(
                r'^(?:Module|Unit|Lesson|Chapter|Section|Topic|Part)\s+\d+',
                re.IGNORECASE,
            ),
            # Numbered heading (1. Title, 2) Topic, etc.)
            re.compile(r'^\d+[\.\)]\s+[A-Z]'),
            # Title-case phrase (10-60 chars, starts with capital letter)
            re.compile(r'^[A-Z][a-z\s]{10,60}$'),
            # Topic marker ending with colon (short, < 80 chars)
            re.compile(r'^.{3,79}:$'),
        ]

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # Check if this line looks like a heading
            is_heading = any(p.match(stripped) for p in heading_patterns)

            if is_heading and current_lines:
                sections.append(self._make_section(
                    len(sections), current_heading, current_lines, "heuristic",
                ))
                current_heading = stripped
                current_lines = []
            else:
                current_lines.append(line)

        if current_lines:
            sections.append(self._make_section(
                len(sections), current_heading, current_lines, "heuristic",
            ))

        return sections if sections else [self._make_section(0, filename, lines)]

    # ── LLM Enhancement (Phase 3 stub) ──────────────────────────────────

    async def _llm_refine_boundaries(
        self, sections: List[Section]
    ) -> List[Section]:
        """Use LLM to merge over-split sections or split under-split ones.

        Phase 3: Full implementation with LLM call for semantic boundary
        detection. Phase 1: Returns sections unchanged (no-op stub).
        """
        if len(sections) <= 1 or not self.llm_client:
            return sections

        # Stub — Phase 3 will add actual LLM call here
        logger.debug(
            "LLM refinement not yet implemented — returning %d sections unchanged",
            len(sections),
        )
        return sections

    # ── Helpers ────────────────────────────────────────────────────────

    def _make_section(
        self,
        idx: int,
        heading: str,
        lines: List[str],
        source_style: str = "heuristic",
    ) -> Section:
        """Create a Section from accumulated lines."""
        content = "\n".join(lines)
        return Section(
            index=idx,
            heading=heading if heading else f"Untitled Section {idx + 1}",
            content=content,
            content_preview=content[:500],
            char_count=len(content),
            source_style=source_style,
        )
