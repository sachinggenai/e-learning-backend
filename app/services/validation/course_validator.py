"""Course-Level Structural Validator — US-BKND-AI-008 FR-004.

Validates course-wide structural concerns:
- Page count (must have at least 1 page)
- Page order indices form a zero-based contiguous sequence
- No duplicate page IDs exist
- All page template_type values are in the active allowlist

Also provides accessibility heuristic checks (FR-006):
- Page titles are non-empty with minimum length
- Image components have altText
- Final-assessment has introText/instructions
"""

from __future__ import annotations

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field


@dataclass
class CourseValidationIssue:
    """A single course-level or accessibility validation finding."""
    code: str
    field: str
    message: str
    severity: str = "error"  # error, warning, info
    page_id: Optional[str] = None
    hint: Optional[str] = None


class CourseLevelValidator:
    """Validates course-level structure and accessibility heuristics.

    All methods are pure functions — no async DB access needed.
    Input data (pages list) comes from the caller.
    """

    # Known template type keys from AI-005
    ALLOWED_TEMPLATE_TYPES = {
        "text-content", "tabs", "accordion",
        "click-reveal", "final-assessment",
    }

    # Accessibility thresholds
    MIN_PAGE_TITLE_LENGTH = 3
    MIN_CONTENT_LENGTH_FOR_HEADING_CHECK = 50

    def validate_course_structure(
        self, pages: List[Dict[str, Any]]
    ) -> List[CourseValidationIssue]:
        """Run all course-level structural checks.

        Args:
            pages: List of page dicts, each with at least:
                   page_id, title, order (order_index), template_type, components

        Returns:
            List of CourseValidationIssue (empty if valid).
        """
        issues: List[CourseValidationIssue] = []

        issues.extend(self._check_empty_course(pages))
        issues.extend(self._check_page_order_contiguity(pages))
        issues.extend(self._check_duplicate_page_ids(pages))
        issues.extend(self._check_template_types(pages))
        issues.extend(self._check_empty_pages(pages))

        return issues

    def validate_accessibility(
        self, pages: List[Dict[str, Any]]
    ) -> List[CourseValidationIssue]:
        """Run all accessibility heuristic checks.

        Returns warnings only (never blocking errors per FR-006).
        """
        issues: List[CourseValidationIssue] = []

        for page in pages:
            page_id = page.get("page_id", "")
            issues.extend(self._check_page_title_length(page))
            issues.extend(self._check_image_alt_text(page))
            issues.extend(self._check_assessment_instructions(page))

        return issues

    # ── Structural checks ──────────────────────────────────────

    def _check_empty_course(
        self, pages: List[Dict[str, Any]]
    ) -> List[CourseValidationIssue]:
        """Course must have at least one page."""
        if not pages:
            return [
                CourseValidationIssue(
                    code="COURSE_EMPTY",
                    field="pages",
                    message="Course has no pages. Add at least one page before validating.",
                    severity="error",
                    hint="Create a page via POST /api/v1/courses/{courseId}/pages",
                )
            ]
        return []

    def _check_page_order_contiguity(
        self, pages: List[Dict[str, Any]]
    ) -> List[CourseValidationIssue]:
        """Page order indices must form a zero-based contiguous sequence."""
        if not pages:
            return []

        orders = sorted(p.get("order", p.get("order_index", 0)) for p in pages)
        expected = list(range(len(orders)))

        if orders != expected:
            # Find the first gap
            for i, expected_order in enumerate(expected):
                if i >= len(orders) or orders[i] != expected_order:
                    return [
                        CourseValidationIssue(
                            code="PAGE_ORDER_GAP",
                            field="pages",
                            message=(
                                f"Page orders must be contiguous from 0. "
                                f"Expected order {expected_order} at index {i}, "
                                f"got {orders[i] if i < len(orders) else 'missing'}."
                            ),
                            severity="error",
                            hint="Reindex page orders via PATCH /courses/{id}/pages/reorder",
                        )
                    ]

        return []

    def _check_duplicate_page_ids(
        self, pages: List[Dict[str, Any]]
    ) -> List[CourseValidationIssue]:
        """No two pages may share the same page_id."""
        seen: set = set()
        for p in pages:
            pid = p.get("page_id", "")
            if pid in seen:
                return [
                    CourseValidationIssue(
                        code="DUPLICATE_PAGE_ID",
                        field="pages",
                        message=f"Duplicate page ID found: '{pid}'.",
                        severity="error",
                        page_id=pid,
                        hint="Ensure every page has a unique page_id.",
                    )
                ]
            seen.add(pid)
        return []

    def _check_template_types(
        self, pages: List[Dict[str, Any]]
    ) -> List[CourseValidationIssue]:
        """All template_type values must be in the active allowlist."""
        for p in pages:
            ttype = p.get("template_type", "")
            if ttype and ttype not in self.ALLOWED_TEMPLATE_TYPES:
                return [
                    CourseValidationIssue(
                        code="UNSUPPORTED_TEMPLATE_TYPE",
                        field=f"pages.template_type",
                        message=(
                            f"Unsupported template type '{ttype}' on page "
                            f"'{p.get('page_id', 'unknown')}'. "
                            f"Allowed types: {sorted(self.ALLOWED_TEMPLATE_TYPES)}"
                        ),
                        severity="error",
                        page_id=p.get("page_id"),
                        hint=f"Use one of: {', '.join(sorted(self.ALLOWED_TEMPLATE_TYPES))}",
                    )
                ]
        return []

    def _check_empty_pages(
        self, pages: List[Dict[str, Any]]
    ) -> List[CourseValidationIssue]:
        """Each page must have at least one component."""
        for p in pages:
            comps = p.get("components", [])
            if not comps:
                return [
                    CourseValidationIssue(
                        code="PAGE_NO_COMPONENTS",
                        field=f"pages.components",
                        message=(
                            f"Page '{p.get('title', p.get('page_id', 'unknown'))}' "
                            f"has no components. Each page must have at least one component."
                        ),
                        severity="error",
                        page_id=p.get("page_id"),
                        hint="Add at least one component to this page.",
                    )
                ]
        return []

    # ── Accessibility checks (FR-006) ───────────────────────────

    def _check_page_title_length(
        self, page: Dict[str, Any]
    ) -> List[CourseValidationIssue]:
        """Page titles should be descriptive (min 3 chars)."""
        title = page.get("title", "")
        if not title or len(title.strip()) < self.MIN_PAGE_TITLE_LENGTH:
            return [
                CourseValidationIssue(
                    code="PAGE_TITLE_TOO_SHORT",
                    field="title",
                    message=(
                        f"Page title is too short or empty "
                        f"('{title}' — {len(title)} chars). "
                        f"Use a descriptive title (min {self.MIN_PAGE_TITLE_LENGTH} chars)."
                    ),
                    severity="warning",
                    page_id=page.get("page_id"),
                    hint="Use a descriptive title for accessibility and navigation.",
                )
            ]
        return []

    def _check_image_alt_text(
        self, page: Dict[str, Any]
    ) -> List[CourseValidationIssue]:
        """Image components must have non-empty altText (FR-006)."""
        issues = []
        for i, comp in enumerate(page.get("components", [])):
            ctype = comp.get("component_type", comp.get("componentType", ""))
            if ctype in ("image", "img"):
                data = comp.get("data", {})
                alt = data.get("altText") or data.get("alt_text") or data.get("alt")
                if not alt or not str(alt).strip():
                    issues.append(
                        CourseValidationIssue(
                            code="MISSING_ALT_TEXT",
                            field=f"components[{i}].data.altText",
                            message=(
                                f"Image component on page "
                                f"'{page.get('title', page.get('page_id', ''))}' "
                                f"is missing alt text."
                            ),
                            severity="warning",
                            page_id=page.get("page_id"),
                            hint="Add descriptive alt text for screen readers.",
                        )
                    )
        return issues

    def _check_assessment_instructions(
        self, page: Dict[str, Any]
    ) -> List[CourseValidationIssue]:
        """Final-assessment pages should have introText/instructions."""
        ttype = page.get("template_type", "")
        if ttype != "final-assessment":
            return []

        # Check for introText at page level or in first component data
        data = page.get("data", {})
        has_intro = (
            data.get("introText")
            or data.get("intro_text")
            or data.get("instructions")
        )
        if not has_intro:
            # Check component data
            for comp in page.get("components", []):
                cdata = comp.get("data", {})
                if cdata.get("introText") or cdata.get("instructions"):
                    has_intro = True
                    break

        if not has_intro:
            return [
                CourseValidationIssue(
                    code="ASSESSMENT_MISSING_INSTRUCTIONS",
                    field="data.introText",
                    message=(
                        f"Final assessment page "
                        f"'{page.get('title', page.get('page_id', ''))}' "
                        f"has no introduction text. Add introText for accessibility."
                    ),
                    severity="warning",
                    page_id=page.get("page_id"),
                    hint="Add an introText field with assessment instructions.",
                )
            ]
        return []
