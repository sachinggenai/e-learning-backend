"""Template suitability scoring engine — TRD-CGQ Phase 1.

Phase 1: Rules-based scoring from ContentFeatures (ZERO LLM).
Phase 2/3: LLM refinement only for ambiguous cases (score margin < 0.3).

Rule arbitration per TRD R4:
  1. "welcome" beats all others when is_first=True AND score >= 0.80
  2. "final-assessment" beats all others when is_last=True AND score >= 0.70
  3. "summary" beats "content-text" when is_last=True
  4. Among accordion/tabs/click-reveal at similar scores (±0.15):
     prefer accordion > tabs > click-reveal (accessibility hierarchy)
  5. "content-text" is always the fallback when no rule fires above 0.50
  6. When top 2 scores are within 0.30 margin → flag for LLM refinement
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.services.ai.feature_detector import ContentFeatures

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Template Suitability Heuristics
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class TemplateScore:
    """Score for a single template type."""
    template_type: str
    score: float          # 0.0 - 1.0
    confidence: float     # 0.0 - 1.0 (how certain the score is)
    method: str           # "heuristic" | "llm"
    reasoning: str        # Human-readable explanation


# Valid canonical template types from template_contracts.py
VALID_TEMPLATES: List[str] = [
    "content-text", "tabs", "accordion", "click-reveal", "final-assessment",
    "welcome", "summary", "content-video", "content-media", "mcq",
]

# Accessibility hierarchy for tie-breaking (R4 rule 4)
_ACCESSIBILITY_PRIORITY: Dict[str, int] = {
    "accordion": 3,
    "tabs": 2,
    "click-reveal": 1,
}


# ── Individual Heuristic Rules ──────────────────────────────────────────
# Each function: ContentFeatures → Optional[TemplateScore]
# Return None means "this rule does not apply."


def _rule_welcome(f: ContentFeatures) -> Optional[TemplateScore]:
    """First section with intro language → welcome."""
    if f.is_first and f.has_intro_language:
        return TemplateScore(
            "welcome", 0.90, 0.90, "heuristic",
            "First section with introduction language",
        )
    return None


def _rule_assessment(f: ContentFeatures) -> Optional[TemplateScore]:
    """Assessment keywords + near end of document → final-assessment."""
    if f.has_assessment_keywords:
        return TemplateScore(
            "final-assessment", 0.90, 0.85, "heuristic",
            "Assessment keywords detected",
        )
    if f.is_last and (f.has_qa_pattern or f.char_count > 500):
        return TemplateScore(
            "final-assessment", 0.50, 0.40, "heuristic",
            "Last section — might be assessment",
        )
    return None


def _rule_summary(f: ContentFeatures) -> Optional[TemplateScore]:
    """Near end + summary language → summary."""
    if f.has_summary_language:
        return TemplateScore(
            "summary", 0.90, 0.85, "heuristic",
            "Summary language detected",
        )
    if f.is_last and not f.has_assessment_keywords:
        return TemplateScore(
            "summary", 0.45, 0.35, "heuristic",
            "Last section without assessment content",
        )
    return None


def _rule_click_reveal(f: ContentFeatures) -> Optional[TemplateScore]:
    """Q&A pattern → click-reveal."""
    if f.has_qa_pattern:
        return TemplateScore(
            "click-reveal", 0.85, 0.85, "heuristic",
            "Q&A pattern detected",
        )
    return None


def _rule_tabs(f: ContentFeatures) -> Optional[TemplateScore]:
    """2+ parallel sub-topics or procedure steps → tabs."""
    if f.sub_topics_parallel and f.sub_topic_count >= 2:
        return TemplateScore(
            "tabs", 0.80, 0.75, "heuristic",
            f"{f.sub_topic_count} parallel sub-topics detected",
        )
    if f.has_procedure_steps:
        return TemplateScore(
            "tabs", 0.75, 0.70, "heuristic",
            "Procedure/steps pattern detected",
        )
    return None


def _rule_accordion(f: ContentFeatures) -> Optional[TemplateScore]:
    """3+ independent sub-topics → accordion."""
    if f.sub_topics_independent and f.sub_topic_count >= 3:
        score = min(0.95, 0.70 + (f.sub_topic_count - 3) * 0.05)
        return TemplateScore(
            "accordion", score, 0.80, "heuristic",
            f"{f.sub_topic_count} independent sub-topics detected",
        )
    return None


def _rule_term_definitions(f: ContentFeatures) -> Optional[TemplateScore]:
    """Term: definition patterns → accordion."""
    if f.has_term_definitions and f.sub_topic_count >= 2:
        return TemplateScore(
            "accordion", 0.70, 0.65, "heuristic",
            f"{f.sub_topic_count} term definitions detected",
        )
    return None


def _rule_single_narrative(f: ContentFeatures) -> Optional[TemplateScore]:
    """Single topic with narrative flow → content-text."""
    if f.has_narrative_structure and f.sub_topic_count < 3 and not f.has_qa_pattern:
        return TemplateScore(
            "content-text", 0.90, 0.85, "heuristic",
            "Single narrative topic, no sub-topic structure",
        )
    return None


# All rules in evaluation order (earlier = higher logical priority)
ALL_RULES = [
    _rule_welcome,
    _rule_assessment,
    _rule_summary,
    _rule_click_reveal,
    _rule_tabs,
    _rule_accordion,
    _rule_term_definitions,
    _rule_single_narrative,
]

DEFAULT_TEMPLATE = TemplateScore(
    "content-text", 0.40, 0.30, "heuristic",
    "Fallback — no strong signal detected",
)


# ═══════════════════════════════════════════════════════════════════════
# Template Selector
# ═══════════════════════════════════════════════════════════════════════

class TemplateSelector:
    """Score and select templates for document sections.

    Phase 1: Pure heuristics (ZERO LLM dependency).
    Phase 2+: LLM refinement for ambiguous cases only.

    Usage:
        selector = TemplateSelector()
        scores = selector.score_all(features)          # All template scores
        best = selector.select(features)                # Single best template
        best, needs_llm = selector.select_with_confidence(features)  # + refinement flag
    """

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    # ── Public API ─────────────────────────────────────────────────────

    def score_all(self, features: ContentFeatures) -> List[TemplateScore]:
        """Score all applicable templates for a section.

        Returns list sorted by score descending. Always includes at least
        content-text as a minimum viable fallback.
        """
        # R3: Non-English → skip heuristics, return content-text fallback
        if features.detected_language != "en" and features.char_count > 200:
            logger.debug(
                "Non-English content detected (lang=%s) — skipping heuristics",
                features.detected_language,
            )
            return [TemplateScore(
                "content-text", 0.50, 0.30, "heuristic",
                f"Non-English content (lang={features.detected_language}) — "
                f"LLM refinement recommended",
            )]

        scores: List[TemplateScore] = []
        for rule in ALL_RULES:
            result = rule(features)
            if result is not None:
                scores.append(result)

        # Sort by score descending
        scores.sort(key=lambda s: s.score, reverse=True)

        # Always include content-text as minimum viable
        if not any(s.template_type == "content-text" for s in scores):
            scores.append(DEFAULT_TEMPLATE)

        # ── R4: Rule arbitration ───────────────────────────────────
        scores = self._arbitrate(scores, features)

        return scores

    def select(self, features: ContentFeatures) -> TemplateScore:
        """Select the best template. No LLM refinement.

        Returns the highest-scoring template after rule arbitration.
        Always returns a valid TemplateScore — never None.
        """
        scores = self.score_all(features)
        return scores[0] if scores else DEFAULT_TEMPLATE

    def select_with_confidence(
        self, features: ContentFeatures,
    ) -> Tuple[TemplateScore, bool]:
        """Select best template, indicating if LLM refinement is needed.

        Returns:
            (best_template, needs_llm_refinement)
            needs_llm_refinement is True when:
              - Top 2 scores are within 0.30 margin, AND
              - Best confidence < 0.80, OR
              - Non-English content detected
        """
        # R3: Non-English always flags LLM refinement
        if features.detected_language != "en" and features.char_count > 200:
            default = TemplateScore(
                "content-text", 0.50, 0.30, "heuristic",
                f"Non-English content (lang={features.detected_language}) — "
                f"LLM refinement required",
            )
            return default, True

        scores = self.score_all(features)
        if not scores:
            return DEFAULT_TEMPLATE, False

        best = scores[0]
        second = scores[1] if len(scores) > 1 else None

        needs_llm = (
            second is not None
            and (best.score - second.score) < 0.30
            and best.confidence < 0.80
        )

        return best, needs_llm

    def select_batch(
        self,
        features_list: List[ContentFeatures],
    ) -> List[Tuple[TemplateScore, bool]]:
        """Select templates for multiple sections at once.

        Useful for batch processing in propose-breakdown.
        """
        return [self.select_with_confidence(f) for f in features_list]

    # ── R4: Rule Arbitration ───────────────────────────────────────────

    def _arbitrate(
        self,
        scores: List[TemplateScore],
        features: ContentFeatures,
    ) -> List[TemplateScore]:
        """Resolve conflicting template scores per TRD R4 rules.

        Rules:
        1. "welcome" beats all others when is_first=True AND score >= 0.80
        2. "final-assessment" beats all others when is_last=True AND score >= 0.70
        3. "summary" beats "content-text" when is_last=True
        4. Among accordion/tabs/click-reveal at similar scores (±0.15):
           prefer accordion > tabs > click-reveal (accessibility hierarchy)
        5. "content-text" is always the fallback when no rule fires above 0.50
        6. When top 2 scores are within 0.30 margin → flag for LLM refinement
        """
        if not scores:
            return [DEFAULT_TEMPLATE]

        # Build lookup
        by_type: Dict[str, TemplateScore] = {}
        for s in scores:
            existing = by_type.get(s.template_type)
            if existing is None or s.score > existing.score:
                by_type[s.template_type] = s

        # ── Rule 1: Welcome dominates when is_first ────────────────
        welcome = by_type.get("welcome")
        if welcome and features.is_first and welcome.score >= 0.80:
            return [welcome] + [s for s in scores if s.template_type != "welcome"]

        # ── Rule 2: Assessment dominates when is_last ──────────────
        assessment = by_type.get("final-assessment")
        if assessment and features.is_last and assessment.score >= 0.70:
            return [assessment] + [s for s in scores if s.template_type != "final-assessment"]

        # ── Rule 3: Summary beats content-text when is_last ────────
        summary = by_type.get("summary")
        if summary and features.is_last:
            # Boost summary above content-text
            scores = [s for s in scores if s.template_type != "summary"]
            scores.insert(0, summary)

        # ── Rule 4: Accessibility hierarchy tie-breaking ───────────
        interactive = [
            s for s in scores
            if s.template_type in ("accordion", "tabs", "click-reveal")
        ]
        if len(interactive) >= 2:
            best_interactive = max(
                interactive,
                key=lambda s: (
                    s.score,  # Primary: score
                    _ACCESSIBILITY_PRIORITY.get(s.template_type, 0),  # Secondary: accessibility
                ),
            )
            # Remove lower-priority interactive types from the top spot
            # but keep them in the list for LLM refinement consideration
            top = scores[0]
            if (
                top.template_type in ("accordion", "tabs", "click-reveal")
                and top.template_type != best_interactive.template_type
                and abs(top.score - best_interactive.score) <= 0.15
            ):
                # Swap: best interactive goes first
                scores = [s for s in scores if s is not best_interactive]
                scores.insert(0, best_interactive)

        # ── Rule 5: Fallback when no strong signal ─────────────────
        if scores[0].score < 0.50:
            # Ensure content-text is available as fallback
            if not any(s.template_type == "content-text" for s in scores):
                scores.append(DEFAULT_TEMPLATE)
            # Move content-text to top if nothing else is strong
            ct_scores = [s for s in scores if s.template_type == "content-text"]
            if ct_scores and scores[0].score < 0.50:
                scores = [s for s in scores if s.template_type != "content-text"]
                scores.insert(0, ct_scores[0])

        return scores

    # ── LLM Refinement (Phase 2+ stub) ─────────────────────────────────

    async def llm_refine(
        self,
        features: ContentFeatures,
        candidates: List[TemplateScore],
        section_text: str,
    ) -> TemplateScore:
        """Use LLM to choose between ambiguous template candidates.

        Only called when select_with_confidence() returns needs_llm=True.
        Phase 1: Returns best heuristic candidate (no LLM call).
        Phase 2: Full implementation with LLM call.

        Works with any model size — small models do simple choice,
        large models can override with creative selections.
        """
        if not self.llm_client or not candidates:
            return candidates[0] if candidates else DEFAULT_TEMPLATE

        # Phase 2+ will add actual LLM call here
        logger.debug(
            "LLM refinement not yet implemented — returning best heuristic: %s",
            candidates[0].template_type if candidates else "content-text",
        )
        return candidates[0] if candidates else DEFAULT_TEMPLATE
