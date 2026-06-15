"""Dependency Impact Analyzer for Destructive Page Operations.

US-BKND-AI-013: Analyzes all course dependencies that would be affected
by deleting a page, producing categorized warnings for the confirmation
modal. Checks branching rules, scoring configs, final assessment status,
navigation ordering, and course-level resource impact.
"""

from __future__ import annotations

import logging
from typing import List, Dict, Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.branching import BranchRule
from app.models.page_component import PageRecord, ComponentRecord
from app.models.scoring import CourseScoringRecord

logger = logging.getLogger(__name__)


class DependencyAnalyzer:
    """Checks what course features depend on a specific page.

    Provides a consolidated dependency report used by the delete proposal
    flow to surface warnings before the user confirms the destructive action.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def analyze(
        self,
        course_id: str,
        page: PageRecord,
    ) -> List[Dict[str, Any]]:
        """Run all dependency checks and return consolidated warning list.

        Args:
            course_id: The course ID.
            page: The PageRecord to analyze.

        Returns:
            List of warning dicts, each with:
                - category: str ('branching', 'scoring', 'final_assessment',
                  'navigation', 'only_page')
                - severity: str ('info', 'warning', 'error')
                - message: str (human-readable)
                - affected_ids: list[str] (related entity IDs)
        """
        warnings: List[Dict[str, Any]] = []

        # Run all checks — each returns a list of warnings
        branching_warnings = await self.check_branching_rules(course_id, page.page_id)
        warnings.extend(branching_warnings)

        scoring_warnings = await self.check_scoring_dependencies(course_id, page)
        warnings.extend(scoring_warnings)

        final_assessment_warnings = self.check_final_assessment(page)
        warnings.extend(final_assessment_warnings)

        navigation_warnings = await self.check_navigation_impact(course_id, page)
        warnings.extend(navigation_warnings)

        return warnings

    # ------------------------------------------------------------------
    # Branching Rule Dependencies
    # ------------------------------------------------------------------

    async def check_branching_rules(
        self, course_id: str, page_id: str
    ) -> List[Dict[str, Any]]:
        """Find branch rules that reference this page."""
        q = select(BranchRule).where(
            BranchRule.course_id == course_id,
            (
                (BranchRule.source_page_id == page_id)
                | (BranchRule.default_target_page_id == page_id)
            ),
        )
        result = await self.session.execute(q)
        rules = result.scalars().all()

        warnings: List[Dict[str, Any]] = []
        for rule in rules:
            # Check if any condition targets this page
            conditions = getattr(rule, "conditions", None) or []
            has_condition_target = False
            for cond in conditions:
                if isinstance(cond, dict) and cond.get("targetPageId") == page_id:
                    has_condition_target = True
                    break

            if has_condition_target:
                warnings.append({
                    "category": "branching",
                    "severity": "warning",
                    "message": (
                        f"Branch rule '{rule.title}' has a condition "
                        f"targeting this page."
                    ),
                    "affected_ids": [rule.branch_id],
                })

            if getattr(rule, "default_target_page_id", None) == page_id:
                warnings.append({
                    "category": "branching",
                    "severity": "warning",
                    "message": (
                        f"Branch rule '{rule.title}' uses this page as the "
                        f"default target for unmatched conditions."
                    ),
                    "affected_ids": [rule.branch_id],
                })

            if getattr(rule, "source_page_id", None) == page_id:
                warnings.append({
                    "category": "branching",
                    "severity": "info",
                    "message": (
                        f"Branch rule '{rule.title}' originates from this page. "
                        f"Deleting the page will remove the rule's source."
                    ),
                    "affected_ids": [rule.branch_id],
                })

        return warnings

    # ------------------------------------------------------------------
    # Scoring Dependencies
    # ------------------------------------------------------------------

    async def check_scoring_dependencies(
        self, course_id: str, page: PageRecord
    ) -> List[Dict[str, Any]]:
        """Check if course scoring configs reference components on this page."""
        q = select(CourseScoringRecord).where(
            CourseScoringRecord.course_id == course_id
        )
        result = await self.session.execute(q)
        scoring_configs = result.scalars().all()

        warnings: List[Dict[str, Any]] = []
        component_ids_on_page = {
            comp.component_id for comp in (page.components or [])
        }

        for config in scoring_configs:
            component_scores = getattr(config, "component_scores", None) or {}
            if isinstance(component_scores, dict):
                affected = [
                    cid for cid in component_scores
                    if cid in component_ids_on_page
                ]
                if affected:
                    warnings.append({
                        "category": "scoring",
                        "severity": "warning",
                        "message": (
                            f"Scoring configuration references "
                            f"{len(affected)} component(s) on this page. "
                            f"Deleting the page will remove these scoring rules."
                        ),
                        "affected_ids": affected,
                    })

        return warnings

    # ------------------------------------------------------------------
    # Final Assessment Check
    # ------------------------------------------------------------------

    def check_final_assessment(self, page: PageRecord) -> List[Dict[str, Any]]:
        """Check if the page contains a final-assessment component."""
        for comp in (page.components or []):
            comp_type = getattr(comp, "component_type", None)
            if comp_type == "final-assessment":
                comp_id = getattr(comp, "component_id", "unknown")
                return [{
                    "category": "final_assessment",
                    "severity": "warning",
                    "message": (
                        "This page contains the final assessment. Deleting it "
                        "will remove all scoring and completion configuration "
                        "for this course."
                    ),
                    "affected_ids": [comp_id],
                }]
        return []

    # ------------------------------------------------------------------
    # Navigation Impact
    # ------------------------------------------------------------------

    async def check_navigation_impact(
        self, course_id: str, page: PageRecord
    ) -> List[Dict[str, Any]]:
        """Check navigation/ordering impact of deleting this page."""
        warnings: List[Dict[str, Any]] = []

        # Check how many pages remaining in course
        from app.models.page_component import PageRecord as PR

        q = select(PR).where(PR.course_id == course_id)
        result = await self.session.execute(q)
        all_pages = list(result.scalars().all())

        if len(all_pages) <= 1:
            warnings.append({
                "category": "only_page",
                "severity": "error",
                "message": (
                    "This is the only page in the course. Deleting it will "
                    "leave the course with zero pages. Consider deleting the "
                    "course instead."
                ),
                "affected_ids": [course_id],
            })

        # Check if first or last page
        page_order = getattr(page, "order_index", None)
        if page_order is not None and len(all_pages) > 1:
            sorted_pages = sorted(all_pages, key=lambda p: getattr(p, "order_index", 0))
            if sorted_pages and sorted_pages[0].page_id == page.page_id:
                warnings.append({
                    "category": "navigation",
                    "severity": "info",
                    "message": (
                        "This is the first page in the course. "
                        "The next page will become the new first page."
                    ),
                    "affected_ids": [
                        sorted_pages[1].page_id if len(sorted_pages) > 1 else ""
                    ],
                })
            if sorted_pages and sorted_pages[-1].page_id == page.page_id:
                warnings.append({
                    "category": "navigation",
                    "severity": "info",
                    "message": (
                        "This is the last page in the course. "
                        "The previous page will become the new last page."
                    ),
                    "affected_ids": [
                        sorted_pages[-2].page_id if len(sorted_pages) > 1 else ""
                    ],
                })

        return warnings
