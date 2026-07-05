"""Template-to-Model Tier Router — TRD-CGQ Phase 3A.

Routes each page to the appropriate model tier based on its template type,
implementing the decision tree from TRD §4.3:

  content-text / welcome / summary  → TIER_SMALL  (phi3:mini / any available)
  accordion / tabs / click-reveal   → TIER_MID    (qwen2.5:7b / preferred 7B+)
  final-assessment / mcq            → TIER_LARGE  (largest available model)

Cost optimization: Simple text pages use cheap/fast models, complex
interactive content and assessments use larger models.

Used by course_generator.py _generate_pages_with_llm() to group pages
by tier and run each group with the appropriate model.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class TemplateTier(str, Enum):
    """Model tiers for template-type-based routing."""
    SMALL = "small"    # Simple text pages — cheapest model
    MID = "mid"        # Interactive content — mid-tier model
    LARGE = "large"    # Assessments — largest available model


# ── Template → Tier mapping ───────────────────────────────────────────

TEMPLATE_TIER_MAP: Dict[str, TemplateTier] = {
    "content-text": TemplateTier.SMALL,
    "welcome": TemplateTier.SMALL,
    "summary": TemplateTier.SMALL,
    "content-video": TemplateTier.SMALL,
    "content-media": TemplateTier.SMALL,
    "accordion": TemplateTier.MID,
    "tabs": TemplateTier.MID,
    "click-reveal": TemplateTier.MID,
    "final-assessment": TemplateTier.LARGE,
    "mcq": TemplateTier.LARGE,
}

# ── Tier → preferred models (ordered by preference) ───────────────────

TIER_MODEL_PREFERENCES: Dict[TemplateTier, List[str]] = {
    TemplateTier.SMALL: ["phi3:mini", "qwen2.5:7b"],
    TemplateTier.MID: ["qwen2.5:7b", "phi3:mini"],
    TemplateTier.LARGE: ["qwen2.5:7b", "phi3:mini"],
}


@dataclass
class TierAssignment:
    """Result of routing a page to a model tier."""
    page_index: int
    template_type: str
    tier: TemplateTier
    model_id: str
    fallback_model_id: str


class TemplateTierRouter:
    """Routes pages to model tiers based on template type.

    Usage:
        router = TemplateTierRouter()
        groups = router.group_pages_by_tier(pages)
        for tier, tier_pages in groups.items():
            model = router.get_model_for_tier(tier)
            # Generate tier_pages with model
    """

    def __init__(self, model_registry: Any = None):
        """Initialize with optional model registry for model resolution.

        Args:
            model_registry: AIConfig instance or dict for looking up available models.
        """
        self._model_registry = model_registry
        self._routing_stats: Dict[str, int] = {
            TemplateTier.SMALL.value: 0,
            TemplateTier.MID.value: 0,
            TemplateTier.LARGE.value: 0,
        }

    # ── Public API ─────────────────────────────────────────────────

    def classify_page(self, template_type: str) -> TemplateTier:
        """Determine which model tier a page needs based on its template type.

        Args:
            template_type: Canonical template type (e.g., "accordion", "content-text").

        Returns:
            TemplateTier enum value. Unknown types default to SMALL.
        """
        tier = TEMPLATE_TIER_MAP.get(template_type, TemplateTier.SMALL)
        self._routing_stats[tier.value] += 1
        return tier

    def get_model_for_tier(self, tier: TemplateTier) -> str:
        """Resolve the best available model for a tier.

        Checks the model registry for availability, falls back through
        the preference list, and returns the first available model.
        """
        preferences = TIER_MODEL_PREFERENCES.get(tier, ["phi3:mini"])

        if self._model_registry:
            for model_id in preferences:
                try:
                    model = self._model_registry.get_model(model_id)
                    if model and model.status == "active":
                        return model_id
                except Exception:
                    continue

        return preferences[0]  # Return preferred even if not verified

    def group_pages_by_tier(
        self, pages: List[Dict[str, Any]],
    ) -> Dict[TemplateTier, List[Tuple[int, Dict[str, Any]]]]:
        """Group pages by their required model tier.

        Args:
            pages: List of page dicts with "template_type" key.

        Returns:
            Dict mapping TemplateTier → List of (page_index, page_dict).
        """
        groups: Dict[TemplateTier, List[Tuple[int, Dict[str, Any]]]] = {
            TemplateTier.SMALL: [],
            TemplateTier.MID: [],
            TemplateTier.LARGE: [],
        }

        for i, page in enumerate(pages):
            ttype = page.get("template_type", "content-text")
            tier = self.classify_page(ttype)
            groups[tier].append((i, page))

        return groups

    def create_tier_assignments(
        self, pages: List[Dict[str, Any]],
    ) -> List[TierAssignment]:
        """Create model assignments for all pages.

        Returns a TierAssignment per page with the assigned model.
        Used when the generation fan-out needs per-page model selection.
        """
        assignments = []
        for i, page in enumerate(pages):
            ttype = page.get("template_type", "content-text")
            tier = self.classify_page(ttype)
            model = self.get_model_for_tier(tier)
            # Fallback: if preferred model fails, try next in preferences
            prefs = TIER_MODEL_PREFERENCES.get(tier, ["phi3:mini"])
            fallback = prefs[1] if len(prefs) > 1 else prefs[0]

            assignments.append(TierAssignment(
                page_index=i,
                template_type=ttype,
                tier=tier,
                model_id=model,
                fallback_model_id=fallback,
            ))

        return assignments

    def get_stats(self) -> Dict[str, Any]:
        """Return routing statistics for observability."""
        total = sum(self._routing_stats.values())
        return {
            "routing_counts": dict(self._routing_stats),
            "total_pages": total,
            "small_pct": round(self._routing_stats[TemplateTier.SMALL.value] / max(total, 1) * 100, 1),
            "mid_pct": round(self._routing_stats[TemplateTier.MID.value] / max(total, 1) * 100, 1),
            "large_pct": round(self._routing_stats[TemplateTier.LARGE.value] / max(total, 1) * 100, 1),
        }
