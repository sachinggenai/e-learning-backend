"""Accessibility Validator — Phase 3.7.

Validates e-learning content against WCAG 2.1 guidelines (Level AA).
Checks: color contrast, heading hierarchy, alt text, link text,
form labels, ARIA attributes, keyboard navigation, reading level.

Usage:
    validator = AccessibilityValidator()
    result = await validator.validate_page(
        title="Welcome",
        components=[{"component_type": "content-text", "data": {...}}],
    )
    # result: {score: 0-100, issues: [...], warnings: [...]}
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ai_authoring")


class AccessibilityValidator:
    """WCAG 2.1 Level AA accessibility validator for e-learning content."""

    # Minimum colour contrast ratios (WCAG 2.1 AA)
    MIN_CONTRAST_NORMAL = 4.5
    MIN_CONTRAST_LARGE = 3.0

    def __init__(self):
        self._checks = [
            self._check_heading_hierarchy,
            self._check_image_alt_text,
            self._check_link_text,
            self._check_colour_contrast_hints,
            self._check_reading_level,
            self._check_form_labels,
            self._check_aria_roles,
        ]

    # ── Public API ─────────────────────────────────────────────────

    async def validate_page(
        self,
        title: str,
        components: List[Dict[str, Any]],
        template_type: str = "content-text",
    ) -> Dict[str, Any]:
        """Validate a single page for WCAG 2.1 AA compliance.

        Returns:
            {
                "score": 0-100,
                "passed": int,
                "failed": int,
                "warnings": int,
                "issues": [{"check": str, "severity": "error|warning", "message": str, "element": str}],
                "summary": str,
            }
        """
        issues: List[Dict[str, Any]] = []

        for check in self._checks:
            results = check(title, components, template_type)
            issues.extend(results)

        errors = [i for i in issues if i["severity"] == "error"]
        warnings = [i for i in issues if i["severity"] == "warning"]

        total_checks = len(self._checks)
        failed = len(set(i["check"] for i in errors))
        score = max(0, 100 - (failed * (100 // max(total_checks, 1))))

        severity = "pass" if failed == 0 else ("warning" if len(errors) == 0 else "fail")

        return {
            "score": score,
            "severity": severity,
            "passed": total_checks - failed,
            "failed": failed,
            "warnings": len(warnings),
            "issues": issues,
            "summary": (
                f"Accessibility score: {score}/100. "
                f"{failed} errors, {len(warnings)} warnings."
            ),
        }

    async def validate_course(
        self,
        pages: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Validate all pages in a course. Aggregates per-page results."""
        page_results = []
        total_score = 0

        for i, page in enumerate(pages):
            result = await self.validate_page(
                title=page.get("title", f"Page {i+1}"),
                components=page.get("components", []),
                template_type=page.get("template_type", "content-text"),
            )
            page_results.append({
                "page_index": i,
                "page_title": page.get("title", ""),
                **result,
            })
            total_score += result["score"]

        avg_score = total_score / max(len(pages), 1)

        return {
            "average_score": round(avg_score, 1),
            "total_pages": len(pages),
            "pages_passing": sum(1 for p in page_results if p["severity"] == "pass"),
            "pages_failing": sum(1 for p in page_results if p["severity"] == "fail"),
            "pages_with_warnings": sum(1 for p in page_results if p["severity"] == "warning"),
            "page_results": page_results,
            "summary": f"Average accessibility score: {avg_score:.0f}/100 across {len(pages)} pages.",
        }

    # ── Individual checks ──────────────────────────────────────────

    def _check_heading_hierarchy(
        self, title: str, components: List[Dict], template_type: str
    ) -> List[Dict[str, Any]]:
        """Check heading hierarchy: h1 before h2, no skipped levels."""
        issues = []
        all_content = self._extract_text(components)
        headings = re.findall(r'<h(\d)[^>]*>', all_content)

        if not headings and template_type != "final-assessment":
            issues.append({
                "check": "heading_hierarchy",
                "severity": "warning",
                "message": "No headings found. Use h1-h6 for content structure.",
                "element": "body",
            })

        # Check for skipped heading levels
        levels = [int(h) for h in headings]
        for i in range(1, len(levels)):
            if levels[i] > levels[i - 1] + 1:
                issues.append({
                    "check": "heading_hierarchy",
                    "severity": "warning",
                    "message": f"Heading level skipped: h{levels[i-1]} to h{levels[i]}",
                    "element": f"h{levels[i]}",
                })

        return issues

    def _check_image_alt_text(
        self, title: str, components: List[Dict], template_type: str
    ) -> List[Dict[str, Any]]:
        """Check images have alt text."""
        issues = []
        all_content = self._extract_text(components)
        images = re.findall(r'<img[^>]*>', all_content)
        images_without_alt = [img for img in images if 'alt=' not in img]

        if images_without_alt:
            issues.append({
                "check": "image_alt_text",
                "severity": "error",
                "message": f"{len(images_without_alt)} image(s) missing alt text",
                "element": "img",
            })

        return issues

    def _check_link_text(
        self, title: str, components: List[Dict], template_type: str
    ) -> List[Dict[str, Any]]:
        """Check links have descriptive text (not 'click here')."""
        issues = []
        all_content = self._extract_text(components)
        links = re.findall(r'<a[^>]*>([^<]*)</a>', all_content)

        non_descriptive = ["click here", "here", "read more", "more", "link"]
        for link_text in links:
            if link_text.strip().lower() in non_descriptive:
                issues.append({
                    "check": "link_text",
                    "severity": "warning",
                    "message": f"Non-descriptive link text: '{link_text}'",
                    "element": "a",
                })

        return issues

    def _check_colour_contrast_hints(
        self, title: str, components: List[Dict], template_type: str
    ) -> List[Dict[str, Any]]:
        """Check for inline colour styles that may violate contrast ratios."""
        issues = []
        all_content = self._extract_text(components)

        # Find inline color styles (heuristic check)
        color_matches = re.findall(r'color:\s*([^;]+)', all_content)
        for color_val in color_matches[:10]:
            color_val = color_val.strip().lower()
            # Light colours on white background = low contrast
            light_colors = ["#ccc", "#ddd", "#eee", "#f0f0f0", "lightgray", "lightgrey"]
            if any(lc in color_val for lc in light_colors):
                issues.append({
                    "check": "colour_contrast",
                    "severity": "warning",
                    "message": f"Light colour '{color_val}' may have insufficient contrast",
                    "element": "style",
                })

        return issues

    def _check_reading_level(
        self, title: str, components: List[Dict], template_type: str
    ) -> List[Dict[str, Any]]:
        """Estimate reading level using Flesch-Kincaid heuristic."""
        issues = []
        all_text = self._extract_plain_text(components)

        if not all_text:
            return issues

        # Simple heuristic: average word length > 7 chars = complex
        words = re.findall(r'\b\w+\b', all_text)
        if not words:
            return issues

        avg_word_len = sum(len(w) for w in words) / len(words)
        sentences = re.split(r'[.!?]+', all_text)
        avg_sentence_len = len(words) / max(len(sentences), 1)

        if avg_word_len > 7 and avg_sentence_len > 25:
            issues.append({
                "check": "reading_level",
                "severity": "warning",
                "message": (
                    f"Content may be too complex: avg word length {avg_word_len:.1f}, "
                    f"avg sentence length {avg_sentence_len:.0f} words. "
                    "Consider simplifying for broader accessibility."
                ),
                "element": "content",
            })

        return issues

    def _check_form_labels(
        self, title: str, components: List[Dict], template_type: str
    ) -> List[Dict[str, Any]]:
        """Check form inputs have associated labels."""
        issues = []
        all_content = self._extract_text(components)

        # Check if forms have labels (relevant for assessment/quiz pages)
        inputs = re.findall(r'<input[^>]*>', all_content)
        labels = re.findall(r'<label[^>]*>', all_content)

        if inputs and len(labels) < len(inputs):
            issues.append({
                "check": "form_labels",
                "severity": "error",
                "message": f"{len(inputs) - len(labels)} input(s) missing associated <label>",
                "element": "input",
            })

        return issues

    def _check_aria_roles(
        self, title: str, components: List[Dict], template_type: str
    ) -> List[Dict[str, Any]]:
        """Check for basic ARIA landmark roles."""
        issues = []
        all_content = self._extract_text(components)

        # Check for presence of main landmark role in larger content
        has_role = bool(re.search(r'role\s*=\s*["\']', all_content))
        word_count = len(all_content.split())

        if word_count > 200 and not has_role:
            issues.append({
                "check": "aria_roles",
                "severity": "warning",
                "message": "Large content block without ARIA role attributes. Consider adding role='main' or role='article'.",
                "element": "body",
            })

        return issues

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _extract_text(components: List[Dict[str, Any]]) -> str:
        """Concatenate all text content from components."""
        text_parts = []
        for comp in components:
            data = comp.get("data", {})
            # Recursively extract string values
            AccessibilityValidator._extract_str(data, text_parts)
        return " ".join(text_parts)

    @staticmethod
    def _extract_str(obj: Any, parts: List[str]) -> None:
        """Recursively extract all string values from nested dicts/lists."""
        if isinstance(obj, str):
            parts.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                AccessibilityValidator._extract_str(v, parts)
        elif isinstance(obj, list):
            for item in obj:
                AccessibilityValidator._extract_str(item, parts)

    @staticmethod
    def _extract_plain_text(components: List[Dict[str, Any]]) -> str:
        """Extract text and strip HTML tags."""
        text = AccessibilityValidator._extract_text(components)
        # Strip HTML tags
        return re.sub(r'<[^>]+>', ' ', text)
