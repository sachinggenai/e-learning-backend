"""Hybrid Supervisor — Phase 2.6.

Provides LLM-based anomaly routing that augments the deterministic state machine.
When validation fails or anomalies are detected, the Supervisor decides whether
to re-plan, skip, abort, or retry using deterministic rules first (~90% coverage),
then a lightweight LLM call for ambiguous cases.

Graceful degradation: when LLM is unavailable, falls back to deterministic routing.
"""
from __future__ import annotations

import json as _json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ai_authoring")

# ── Route constants ─────────────────────────────────────────────────

ROUTE_REPLAN = "plan"
ROUTE_SKIP = "skip_and_continue"
ROUTE_ABORT = "__end__"
ROUTE_RETRY = "retry_current"

# ── System Prompt ───────────────────────────────────────────────────

SUPERVISOR_SYSTEM_PROMPT = """You are a workflow supervisor for an AI course generation pipeline.
Your job is to decide the next action when the pipeline encounters anomalies.

CONTEXT YOU WILL RECEIVE:
- current_phase: which pipeline phase had the issue
- error_count: number of validation errors
- warning_count: number of validation warnings
- total_pages: how many pages were generated
- budget_remaining: remaining cost budget (USD)
- previous_route_count: how many times we've already re-planned

POSSIBLE ACTIONS:
- "replan"  → Go back to the planning phase and regenerate the plan
- "skip"    → Skip validation errors and continue to the next phase
- "abort"   → Stop the pipeline (too many errors, not worth continuing)
- "retry"   → Retry the current phase (for transient errors)

DECISION RULES:
1. If error_count == 0, always "skip" (no issues)
2. If error_count <= 2 and total_pages > 5, "skip" with a note (minor issues)
3. If error_count > 5 and previous_route_count >= 2, "abort" (too many failures)
4. If error_count > 2 and previous_route_count < 2, "replan"
5. If budget_remaining < 0.05, "abort" (budget exhausted)
6. If error_count <= 5 and previous_route_count < 2, "retry"

OUTPUT FORMAT:
Return JSON: {"action": "replan|skip|abort|retry", "reasoning": "..."}"""


class SupervisorRouter:
    """Hybrid supervisor: deterministic by default, LLM for anomalies.

    Usage:
        supervisor = SupervisorRouter()
        decision = await supervisor.decide(
            current_phase="validate",
            error_count=3,
            total_pages=10,
            budget_remaining=0.50,
            previous_route_count=1,
        )
        # → "plan" or "skip_and_continue" or "__end__" or "retry_current"
    """

    def __init__(self, llm_client: Any = None):
        self._llm_client = llm_client
        self._router: Any = None
        try:
            from app.services.ai.model_tier_router import ModelTierRouter
            self._router = ModelTierRouter()
        except Exception:
            pass

    # ── Public API ─────────────────────────────────────────────────

    async def decide(
        self,
        current_phase: str,
        error_count: int,
        warning_count: int = 0,
        total_pages: int = 0,
        budget_remaining: float = 999.0,
        previous_route_count: int = 0,
    ) -> str:
        """Decide the next routing action.

        Returns one of: "plan" (re-plan), "skip_and_continue", "__end__" (abort),
        or "retry_current".
        """
        # ── Deterministic rules (cover ~90% of cases) ──────────
        if error_count == 0:
            return ROUTE_SKIP

        if previous_route_count >= 3:
            logger.warning(
                "Supervisor: aborting after %d re-plans", previous_route_count
            )
            return ROUTE_ABORT

        if budget_remaining < 0.05 and error_count > 0:
            logger.warning(
                "Supervisor: aborting — budget exhausted ($%.4f)", budget_remaining
            )
            return ROUTE_ABORT

        if error_count <= 2 and total_pages > 5:
            logger.info(
                "Supervisor: skipping minor errors (%d errors, %d pages)",
                error_count, total_pages,
            )
            return ROUTE_SKIP

        # ── LLM-based decision for ambiguous cases ────────────
        if self._llm_client is not None and previous_route_count < 2:
            try:
                return await self._llm_decide(
                    current_phase, error_count, warning_count,
                    total_pages, budget_remaining, previous_route_count,
                )
            except Exception as exc:
                logger.warning(
                    "Supervisor LLM decision failed: %s — using deterministic fallback", exc
                )

        # ── Deterministic fallback ────────────────────────────
        if error_count > 5:
            return ROUTE_ABORT
        if error_count > 2:
            return ROUTE_REPLAN
        return ROUTE_SKIP

    # ── LLM-based decision ─────────────────────────────────────────

    async def _llm_decide(
        self,
        current_phase: str,
        error_count: int,
        warning_count: int,
        total_pages: int,
        budget_remaining: float,
        previous_route_count: int,
    ) -> str:
        """Use LLM to make routing decision for ambiguous cases.

        Only called when the deterministic rules are inconclusive
        (e.g., moderate error count, first or second attempt).
        """
        prompt = (
            f"Pipeline phase '{current_phase}' encountered anomalies:\n"
            f"- {error_count} validation error(s)\n"
            f"- {warning_count} validation warning(s)\n"
            f"- {total_pages} pages generated\n"
            f"- ${budget_remaining:.4f} budget remaining\n"
            f"- Already re-planned {previous_route_count} time(s)\n\n"
            f"What should the pipeline do next?"
        )

        response = await self._llm_client.chat(
            messages=[
                type('LLMMessage', (), {
                    'role': 'user', 'content': prompt,
                    'tool_calls': [], 'tool_results': [],
                })()
            ],
            system_prompt=SUPERVISOR_SYSTEM_PROMPT,
            temperature=0.1,
            max_tokens=128,
        )

        content = getattr(response, 'content', str(response))
        try:
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            decision = _json.loads(content)
            action = decision.get("action", "skip")
            logger.info(
                "Supervisor LLM decision: %s (reason: %s)",
                action, decision.get("reasoning", "unknown"),
            )

            action_map = {
                "replan": ROUTE_REPLAN,
                "skip": ROUTE_SKIP,
                "abort": ROUTE_ABORT,
                "retry": ROUTE_RETRY,
            }
            return action_map.get(action, ROUTE_SKIP)
        except Exception:
            return ROUTE_SKIP
