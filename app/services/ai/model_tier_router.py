"""Two-Tier Model Architecture - US-BKND-AI-044.

Routes AI tasks between two model tiers for cost optimization:
- PLANNER (fast/cheap): Intent classification, tool selection, simple queries
- GENERATOR (powerful/expensive): Content creation, complex proposals, assessments

Architecture:
    Request -> Classify task type -> Route to Planner or Generator
    Planner: haiku-level model ($0.80/M input) for routing decisions
    Generator: sonnet/opus-level model ($3-15/M input) for content

Cost savings: ~60-80% by sending simple tasks to the cheap model.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ModelTier(str, Enum):
    PLANNER = "planner"      # Fast/cheap: haiku-class
    GENERATOR = "generator"  # Powerful/expensive: sonnet/opus-class


# Task classification keywords
PLANNER_TASKS = {
    "list_pages", "fetch_page", "query_similar", "help",
    "list", "show", "fetch", "find", "search", "what pages",
    "how many", "which page", "validate",
}

GENERATOR_TASKS = {
    "propose_create_page", "propose_update_page", "propose_delete_page",
    "generate_course", "assemble", "create", "update", "delete",
    "write", "generate", "design", "build", "compose",
    "assessment", "quiz", "question",
}

# Model mapping per tier (default: DeepSeek via Anthropic-compatible API)
DEFAULT_TIER_MODELS: Dict[str, str] = {
    ModelTier.PLANNER.value: "deepseek-v4-flash",
    ModelTier.GENERATOR.value: "deepseek-v4-pro[1m]",
}

# Cost comparison (per 1M tokens input)
TIER_COSTS: Dict[str, float] = {
    ModelTier.PLANNER.value: 0.30,     # DeepSeek Flash
    ModelTier.GENERATOR.value: 1.00,   # DeepSeek Pro
}


class ModelTierRouter:
    """Routes AI tasks to the appropriate model tier based on task type.

    Usage:
        router = ModelTierRouter()
        tier = router.classify_task(user_message, tool_name)
        model = router.get_model_for_tier(tier)
    """

    def __init__(self, planner_model: str = "", generator_model: str = ""):
        self.planner_model = planner_model or DEFAULT_TIER_MODELS[ModelTier.PLANNER.value]
        self.generator_model = generator_model or DEFAULT_TIER_MODELS[ModelTier.GENERATOR.value]
        self._routing_stats: Dict[str, int] = {
            ModelTier.PLANNER.value: 0,
            ModelTier.GENERATOR.value: 0,
        }

    def classify_task(
        self,
        user_message: str = "",
        tool_name: str = "",
        intent: str = "",
    ) -> ModelTier:
        """Classify which tier should handle this task.

        Priority: explicit tool_name > intent > message analysis.
        """
        # Tool-based classification (most reliable)
        if tool_name:
            if tool_name in GENERATOR_TASKS:
                tier = ModelTier.GENERATOR
            elif tool_name in PLANNER_TASKS:
                tier = ModelTier.PLANNER
            else:
                tier = self._classify_from_message(user_message)
        elif intent:
            if intent in GENERATOR_TASKS:
                tier = ModelTier.GENERATOR
            else:
                tier = ModelTier.PLANNER
        else:
            tier = self._classify_from_message(user_message)

        self._routing_stats[tier.value] += 1
        logger.debug("Routed to %s: tool=%s intent=%s", tier.value, tool_name, intent)
        return tier

    def get_model_for_tier(self, tier: ModelTier) -> str:
        """Get the model ID for a tier."""
        if tier == ModelTier.PLANNER:
            return self.planner_model
        return self.generator_model

    def get_model_for_task(
        self, user_message: str = "", tool_name: str = "", intent: str = ""
    ) -> str:
        """Convenience: classify + get model in one call."""
        tier = self.classify_task(user_message, tool_name, intent)
        return self.get_model_for_tier(tier)

    def estimate_cost_savings(self) -> Dict[str, Any]:
        """Estimate cost savings from two-tier routing.

        Compares actual routing against hypothetical all-generator costs.
        """
        planner_count = self._routing_stats[ModelTier.PLANNER.value]
        generator_count = self._routing_stats[ModelTier.GENERATOR.value]
        total = planner_count + generator_count

        if total == 0:
            return {"savings_pct": 0, "message": "No requests routed yet"}

        # Assume average 1K tokens per request for estimation
        avg_tokens = 1000
        planner_cost = planner_count * (avg_tokens / 1_000_000) * TIER_COSTS[ModelTier.PLANNER.value]
        generator_cost = generator_count * (avg_tokens / 1_000_000) * TIER_COSTS[ModelTier.GENERATOR.value]
        actual_total = planner_cost + generator_cost

        # Hypothetical: all-generator
        hypothetical = total * (avg_tokens / 1_000_000) * TIER_COSTS[ModelTier.GENERATOR.value]

        savings = hypothetical - actual_total
        savings_pct = (savings / hypothetical * 100) if hypothetical > 0 else 0

        return {
            "total_requests": total,
            "planner_requests": planner_count,
            "generator_requests": generator_count,
            "actual_cost_usd": round(actual_total, 6),
            "hypothetical_cost_all_generator_usd": round(hypothetical, 6),
            "savings_usd": round(savings, 6),
            "savings_pct": round(savings_pct, 1),
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get router statistics."""
        return {
            "routing_counts": dict(self._routing_stats),
            "planner_model": self.planner_model,
            "generator_model": self.generator_model,
            "cost_estimate": self.estimate_cost_savings(),
        }

    def _classify_from_message(self, message: str) -> ModelTier:
        """Classify tier from user message content."""
        if not message:
            return ModelTier.PLANNER

        lower = message.lower()

        # Check generator patterns first (more specific)
        for keyword in GENERATOR_TASKS:
            if keyword in lower:
                return ModelTier.GENERATOR

        # Default to planner for everything else
        return ModelTier.PLANNER
