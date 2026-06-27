"""AGT-06: Template Selector Agent — Phase 2.5.

Phase 5 of the course generation pipeline.
Task: Select the optimal template for each page using a hybrid approach:
    1. Deterministic keyword rules (~85% of cases — fast, cheap, consistent)
    2. LLM fallback for edge cases (~15%)

Model: Planner tier (when LLM needed)
Temperature: 0.2 (low — we want consistent classification)

Design:
    - Rule-based classifier with 5 keyword categories
    - Confidence threshold: >= 0.80 uses rule, below uses LLM
    - Rules cover: assessment, comparison, FAQ, interactive, video
    - LLM fallback provides {template_type, confidence, reasoning}
    - Graceful fallback to content-text on any failure
"""

from __future__ import annotations

import json as _json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ai_authoring")

# ── Rule-Based Template Classifier ─────────────────────────────────

# Each rule has keywords and a confidence score.
# Multiple matches → highest confidence wins.
TEMPLATE_RULES: Dict[str, Dict[str, Any]] = {
    "assessment": {
        "keywords": [
            "quiz", "test", "assessment", "exam", "check your knowledge",
            "evaluate", "score", "passing", "questions", "mcq",
            "multiple choice", "true or false", "fill in the blank",
        ],
        "template": "final-assessment",
        "confidence": 0.95,
    },
    "comparison": {
        "keywords": [
            "compare", "contrast", "versus", "vs", "differences",
            "similarities", "pros and cons", "advantages", "disadvantages",
            "side by side", "comparison table",
        ],
        "template": "tabs",
        "confidence": 0.90,
    },
    "faq": {
        "keywords": [
            "faq", "frequently asked", "common questions",
            "q&a", "questions and answers", "inquiry",
        ],
        "template": "accordion",
        "confidence": 0.90,
    },
    "interactive": {
        "keywords": [
            "interactive", "click", "reveal", "explore", "discover",
            "drag", "flip", "card", "scenario", "what would you do",
            "decision point", "branching",
        ],
        "template": "click-reveal",
        "confidence": 0.85,
    },
    "video": {
        "keywords": [
            "video", "watch", "animation", "demonstration",
            "screencast", "walkthrough", "tutorial video",
        ],
        "template": "content-text",  # content-text with embedded video
        "confidence": 0.80,
    },
}


TEMPLATE_SELECTOR_SYSTEM_PROMPT = """You are an e-learning template selection expert.
Given a page plan entry and its source content, select the most appropriate template type.

TEMPLATE TYPES:
- content-text: Rich text page with headings, paragraphs, images, videos, callouts
- tabs: Multi-tab layout for comparing concepts, phases, or perspectives
- accordion: Expandable sections for Q&A, drill-downs, or detailed topics
- click-reveal: Interactive reveal elements for engagement and self-checks
- final-assessment: Quiz with MCQs, passing score, and answer feedback

SELECTION CRITERIA:
1. Does the content contain quiz/assessment material? → final-assessment
2. Does it compare multiple concepts? → tabs
3. Is it Q&A or drill-down format? → accordion
4. Is it interactive (click-to-reveal, scenarios)? → click-reveal
5. Is it primarily informational text? → content-text

OUTPUT: Return JSON: {"template_type": "...", "confidence": 0.0-1.0, "reasoning": "..."}"""


class TemplateSelectorAgent:
    """AGT-06: Hybrid template selector — rules first, LLM for edge cases.

    Usage:
        agent = TemplateSelectorAgent(llm_client=llm_client)
        result = await agent.select_template(
            page={"title": "Quiz: Chapter 1", "learning_objective": "..."},
            source_content="10 MCQs covering chapter 1 material...",
        )
        # → {"template_type": "final-assessment", "confidence": 0.95, "method": "rule"}
    """

    def __init__(
        self,
        llm_client: Any = None,
        confidence_threshold: float = 0.80,
    ):
        self.llm_client = llm_client
        self.confidence_threshold = confidence_threshold

    # ── Main selection method ─────────────────────────────────────

    async def select_template(
        self,
        page: Dict[str, Any],
        source_content: str,
    ) -> Dict[str, Any]:
        """Select the optimal template for a page.

        Hybrid approach:
        1. Apply deterministic keyword rules (covers ~85% of cases)
        2. If rule confidence < threshold, fall back to LLM
        3. If LLM unavailable, use best rule result or content-text default

        Returns:
            {template_type, confidence, reasoning, method}
        """
        # Step 1: Try deterministic rules
        rule_result = self._classify_by_rules(page, source_content)
        if rule_result and rule_result["confidence"] >= self.confidence_threshold:
            return {**rule_result, "method": "rule"}

        # Step 2: Try LLM fallback
        if self.llm_client is not None:
            try:
                llm_result = await self._classify_by_llm(page, source_content)
                return {**llm_result, "method": "llm"}
            except Exception as exc:
                logger.warning("LLM template selection failed: %s", exc)

        # Step 3: Use best available rule result or default
        if rule_result:
            return {**rule_result, "method": "rule_below_threshold"}
        return {
            "template_type": page.get("template_type", "content-text"),
            "confidence": 0.3,
            "reasoning": "Default fallback — no rules matched and LLM unavailable",
            "method": "fallback",
        }

    async def select_templates_batch(
        self,
        pages: List[Dict[str, Any]],
        source_contents: List[str],
    ) -> List[Dict[str, Any]]:
        """Select templates for multiple pages concurrently.

        Each page is independent — safe to run concurrently via asyncio.gather.
        """
        import asyncio
        tasks = [
            self.select_template(page, src)
            for page, src in zip(pages, source_contents)
        ]
        return await asyncio.gather(*tasks)

    # ── Rule-based classifier ─────────────────────────────────────

    def _classify_by_rules(
        self, page: Dict[str, Any], source_content: str
    ) -> Optional[Dict[str, Any]]:
        """Apply keyword rules. Returns None if no rule matches."""
        combined = (
            f"{page.get('title', '')} "
            f"{page.get('learning_objective', '')} "
            f"{source_content}"
        )
        combined_lower = combined.lower()

        best_match = None
        best_confidence = 0.0

        for rule_name, rule in TEMPLATE_RULES.items():
            match_count = sum(1 for kw in rule["keywords"] if kw in combined_lower)
            if match_count > 0:
                # Keywords are an OR set — matching any is a signal.
                # Don't penalize rules with comprehensive keyword lists.
                #   ≥2 matches → full base confidence
                #   1 match   → 70% of base confidence (weaker signal)
                if match_count >= 2:
                    weighted_confidence = rule["confidence"]
                else:
                    weighted_confidence = round(rule["confidence"] * 0.70, 2)

                if weighted_confidence > best_confidence:
                    best_confidence = weighted_confidence
                    best_match = {
                        "template_type": rule["template"],
                        "confidence": weighted_confidence,
                        "reasoning": (
                            f"Rule '{rule_name}' matched {match_count} "
                            f"keyword{'s' if match_count > 1 else ''}"
                        ),
                    }

        return best_match

    # ── LLM-based classifier ──────────────────────────────────────

    async def _classify_by_llm(
        self, page: Dict[str, Any], source_content: str
    ) -> Dict[str, Any]:
        """LLM-based template selection for edge cases."""
        prompt = (
            f"Page Title: {page.get('title', '')}\n"
            f"Learning Objective: {page.get('learning_objective', '')}\n"
            f"Source Content: {source_content[:1000]}\n\n"
            f"Select the best template type for this page."
        )

        response = await self.llm_client.chat(
            messages=[
                type('LLMMessage', (), {
                    'role': 'user', 'content': prompt,
                    'tool_calls': [], 'tool_results': [],
                })()
            ],
            system_prompt=TEMPLATE_SELECTOR_SYSTEM_PROMPT,
            temperature=0.2,
            max_tokens=256,
        )

        return self._parse_selection(getattr(response, 'content', str(response)))

    def _parse_selection(self, llm_output: str) -> Dict[str, Any]:
        """Parse LLM JSON output with repair."""
        content = llm_output.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        try:
            return _json.loads(content)
        except Exception:
            return {
                "template_type": "content-text",
                "confidence": 0.5,
                "reasoning": "Default — LLM output unparseable",
            }
