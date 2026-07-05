"""Zero-LLM content feature detection for template selection — TRD-CGQ Phase 1.

All features are computed from plain text using regex and counting —
no model calls, no API dependencies. Runs in < 1ms per section.

Used by TemplateSelector (Phase 1C) to score template suitability,
and by content generators (Phase 2A) to build multi-component pages.

English-only for Phase 1. Non-English content detected and flagged
so the pipeline can skip heuristics and use LLM refinement directly (R3).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class ContentFeatures:
    """Structural and semantic features extracted from a document section.

    All fields are computed deterministically from the text — no randomness,
    no model calls. Fields are designed to feed directly into template
    scoring heuristics (TemplateSelector).

    Features are grouped into structural, heading, sub-topic, content pattern,
    semantic signal, and position categories.
    """

    # ── Structural ──────────────────────────────────────────────────
    char_count: int = 0
    line_count: int = 0
    paragraph_count: int = 0
    avg_paragraph_length: float = 0.0

    # ── Heading detection ───────────────────────────────────────────
    has_heading: bool = False
    heading_count: int = 0
    bold_text_count: int = 0

    # ── Sub-topic detection ─────────────────────────────────────────
    sub_topic_count: int = 0
    sub_topics_independent: bool = False   # Each sub-topic can stand alone
    sub_topics_parallel: bool = False      # Sub-topics are equal alternatives

    # ── Content patterns ────────────────────────────────────────────
    has_qa_pattern: bool = False
    has_list: bool = False
    has_callout: bool = False
    has_image_refs: bool = False
    has_table: bool = False
    has_code_block: bool = False

    # ── Semantic signals ────────────────────────────────────────────
    has_intro_language: bool = False
    has_summary_language: bool = False
    has_assessment_keywords: bool = False
    has_term_definitions: bool = False
    has_procedure_steps: bool = False
    has_narrative_structure: bool = False

    # ── Position ────────────────────────────────────────────────────
    section_position: float = 0.0
    is_first: bool = False
    is_last: bool = False
    is_before_assessment: bool = False

    # ── Language (R3: English-only detection) ───────────────────────
    detected_language: str = "en"


class FeatureDetector:
    """Extract ContentFeatures from a text section.

    Pure regex + counting — no external dependencies, runs in < 1ms.

    Usage:
        detector = FeatureDetector()
        features = detector.detect(text, section_index=0, total_sections=10)
    """

    # ═══════════════════════════════════════════════════════════════════
    # Regex patterns (compiled once at class level)
    # ═══════════════════════════════════════════════════════════════════

    # Heading patterns
    _HEADING_PAT = re.compile(
        r'^#+\s|^[A-Z][\w\s]{5,50}$', re.MULTILINE,
    )
    _BOLD_PAT = re.compile(r'\*\*(.+?)\*\*')

    # Sub-topic patterns: markdown headings, numbered lists, title: prefixes
    _SUBTOPIC_PAT = re.compile(
        r'^(?:#+|\d+[\.\)]|[A-Z][\w\s]{3,40}:)', re.MULTILINE,
    )

    # Q&A detection
    _QA_PAT = re.compile(
        r'(?:Q:.*\n.*A:|What\s+is\s+.+\?|How\s+(?:do|does|can|should|would)\s+.+\?'
        r'|Which\s+of\s+the\s+following.+\?|True\s+or\s+[Ff]alse)',
        re.MULTILINE,
    )

    # List detection (bullet points, numbered lists)
    _LIST_PAT = re.compile(
        r'^[\-\*\•\→\✓\✔\☑\▸\▪]\s|^\d+[\.\)]\s', re.MULTILINE,
    )

    # Callout / highlighted content
    _CALLOUT_PAT = re.compile(
        r'(?:Note|Tip|Warning|Important|Did you know|Key Takeaway|Remember'
        r'|Caution|Pro Tip|Best Practice|Heads Up| FYI)',
        re.IGNORECASE,
    )

    # Image / figure references
    _IMAGE_PAT = re.compile(
        r'!\[|\[image\]|\[figure\]|\(fig\s|\(see\s(?:fig|figure)'
        r'|Figure\s+\d|Image\s+\d|Diagram|Screenshot',
        re.IGNORECASE,
    )

    # Table detection (markdown pipe tables)
    _TABLE_PAT = re.compile(r'\|.+\|.*\n\|[-|]+\|')

    # Code blocks
    _CODE_PAT = re.compile(r'```|`[^`]+`')

    # Introduction / welcome language
    _INTRO_PAT = re.compile(
        r'\b(?:welcome|introduction|overview|getting\s+started|about\s+this\s+course'
        r'|learning\s+objectives?|course\s+overview|what\s+you\'ll?\s+learn'
        r'|prerequisites?|agenda|outline)\b',
        re.IGNORECASE,
    )

    # Summary / conclusion language
    _SUMMARY_PAT = re.compile(
        r'\b(?:summary|conclusion|key\s+takeaways?|in\s+summary|to\s+summarize'
        r'|wrap\s+up|recap|review|putting\s+it\s+all\s+together'
        r'|what\s+we\s+(?:have\s+)?learned|next\s+steps)\b',
        re.IGNORECASE,
    )

    # Assessment / quiz / test language
    _ASSESS_PAT = re.compile(
        r'\b(?:quiz|test|assessment|check\s+your\s+(?:knowledge|understanding)'
        r'|evaluation|exam|knowledge\s+check|self-assessment|graded|score'
        r'|multiple\s+choice|true\s+or\s+false|fill\s+in\s+the\s+blank)\b',
        re.IGNORECASE,
    )

    # Term: definition patterns ("Term — definition" or "Term: definition")
    _TERM_PAT = re.compile(
        r'\b(\w[\w\s]{2,30})\s*[:\-—]\s*.{10,}',
    )

    # Procedure / step-by-step patterns
    _PROCEDURE_PAT = re.compile(
        r'(?:step\s+\d|first,?\s|next,?\s|then,?\s|finally,?\s'
        r'|1\.\s.*\n\s*2\.\s|Stage\s+\d|Phase\s+\d)',
        re.IGNORECASE,
    )

    # ── Language detection (R3: English-only limitations) ──────────

    # Common English function words — if < 2 appear in the text,
    # it's probably not English (or too short to matter).
    _ENGLISH_FUNCTION_WORDS = re.compile(
        r'\b(?:the|and|that|have|for|not|with|you|this|but|his|her|they'
        r'|from|their|what|which|when|where|about|each|will|would|there'
        r'|their|them|these|those|some|other|more|also|into|over|back'
        r'|after|before|between|through|during|because)\b',
        re.IGNORECASE,
    )

    # ── Public API ─────────────────────────────────────────────────────

    def detect(
        self,
        text: str,
        section_index: int = 0,
        total_sections: int = 1,
    ) -> ContentFeatures:
        """Extract all features from a text section.

        Args:
            text: The section's full text content.
            section_index: Zero-based position in the document.
            total_sections: Total number of sections in the document.

        Returns:
            ContentFeatures dataclass with all features populated.
        """
        if not text or not text.strip():
            return self._empty_features(section_index, total_sections)

        lines = text.strip().split("\n")
        non_empty = [l for l in lines if l.strip()]
        # Count paragraphs: non-heading lines with > 10 chars of body text
        para_count = sum(
            1 for l in non_empty
            if not l.startswith("#") and not l.startswith("```") and len(l.strip()) > 10
        )

        # ── Compute features ───────────────────────────────────────
        return ContentFeatures(
            # Structural
            char_count=len(text),
            line_count=len(lines),
            paragraph_count=para_count,
            avg_paragraph_length=(
                sum(len(l.strip()) for l in non_empty) / max(len(non_empty), 1)
            ),

            # Heading detection
            has_heading=bool(
                non_empty and self._HEADING_PAT.match(non_empty[0].strip())
            ),
            heading_count=len(self._HEADING_PAT.findall(text)),
            bold_text_count=len(self._BOLD_PAT.findall(text)),

            # Sub-topic detection
            sub_topic_count=len(self._SUBTOPIC_PAT.findall(text)),
            sub_topics_independent=self._check_independent_subtopics(non_empty),
            sub_topics_parallel=self._check_parallel_subtopics(non_empty),

            # Content patterns
            has_qa_pattern=bool(self._QA_PAT.search(text)),
            has_list=bool(self._LIST_PAT.search(text)),
            has_callout=bool(self._CALLOUT_PAT.search(text)),
            has_image_refs=bool(self._IMAGE_PAT.search(text)),
            has_table=bool(self._TABLE_PAT.search(text)),
            has_code_block=bool(self._CODE_PAT.search(text)),

            # Semantic signals
            has_intro_language=bool(self._INTRO_PAT.search(text)),
            has_summary_language=bool(self._SUMMARY_PAT.search(text)),
            has_assessment_keywords=bool(self._ASSESS_PAT.search(text)),
            has_term_definitions=bool(self._TERM_PAT.search(text)),
            has_procedure_steps=bool(self._PROCEDURE_PAT.search(text)),
            has_narrative_structure=(
                len(text) > 500 and len(non_empty) > 3 and not self._LIST_PAT.search(text)
            ),

            # Position
            section_position=section_index / max(total_sections, 1),
            is_first=section_index == 0,
            is_last=section_index == total_sections - 1,
            is_before_assessment=section_index == total_sections - 2,

            # Language detection (R3)
            detected_language=self._detect_language(text),
        )

    def detect_from_section(
        self,
        section: Any,  # document_splitter.Section (avoid circular import)
        total_sections: int = 1,
    ) -> ContentFeatures:
        """Detect features from a Section object.

        Convenience wrapper that extracts text + position from a Section.
        """
        return self.detect(
            text=getattr(section, "content", ""),
            section_index=getattr(section, "index", 0),
            total_sections=total_sections,
        )

    # ── Private Helpers ────────────────────────────────────────────────

    def _check_independent_subtopics(self, lines: list) -> bool:
        """Check if sub-topics can be read independently (accordion pattern).

        True when 3+ sub-headings exist and each is followed by
        sufficient body text (> 50 chars) — suggesting each sub-topic
        is a self-contained unit.
        """
        sub_headings = [
            i for i, l in enumerate(lines)
            if self._SUBTOPIC_PAT.match(l.strip())
        ]
        if len(sub_headings) < 3:
            return False

        # Check that sub-topics have body text between them
        independent_count = 0
        for idx, pos in enumerate(sub_headings):
            next_pos = (
                sub_headings[idx + 1] if idx + 1 < len(sub_headings)
                else len(lines)
            )
            body_lines = lines[pos + 1:next_pos]
            body_text = " ".join(l.strip() for l in body_lines if l.strip())
            if len(body_text) > 50:  # Each sub-topic has meaningful content
                independent_count += 1

        return independent_count >= 3

    def _check_parallel_subtopics(self, lines: list) -> bool:
        """Check if sub-topics are parallel alternatives (tabs pattern).

        True when 2+ sub-headings have similar-length titles (±30% of
        average), suggesting they are equal/parallel choices rather than
        a sequential hierarchy.
        """
        sub_headings = [
            l.strip() for l in lines
            if self._SUBTOPIC_PAT.match(l.strip())
        ]
        if len(sub_headings) < 2:
            return False

        lengths = [len(h) for h in sub_headings]
        avg = sum(lengths) / len(lengths)
        if avg == 0:
            return False

        # Parallel if heading lengths are similar (within 30% of average)
        return all(abs(l - avg) / avg < 0.3 for l in lengths)

    def _detect_language(self, text: str) -> str:
        """Detect whether text is English or non-English.

        R3: Phase 1 heuristics are English-only by design. Non-English
        content should skip heuristics and use LLM refinement directly.

        Uses English function-word frequency as a simple proxy.
        Requires at least 200 chars for reliable detection — shorter
        texts default to "en" to avoid false non-English flags.
        """
        if len(text) < 200:
            return "en"  # Too short to reliably detect

        matches = len(self._ENGLISH_FUNCTION_WORDS.findall(text))
        # Expect ~8+ English function words per 500 chars for English text
        expected = len(text) / 500 * 8

        if matches < max(2, expected * 0.3):
            return "unknown"

        return "en"

    def _empty_features(
        self, section_index: int, total_sections: int
    ) -> ContentFeatures:
        """Return minimal features for an empty section."""
        return ContentFeatures(
            char_count=0,
            line_count=0,
            section_position=section_index / max(total_sections, 1),
            is_first=section_index == 0,
            is_last=section_index == total_sections - 1,
            is_before_assessment=section_index == total_sections - 2,
        )
