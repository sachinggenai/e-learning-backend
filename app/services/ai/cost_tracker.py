"""Cost Tracking and Token Budget Enforcement - US-BKND-AI-036.

Tracks AI token usage, computes costs from a configurable pricing table,
enforces per-user and per-tenant budgets, and provides usage reporting.

Architecture:
    Post-billing: usage is recorded AFTER provider responds.
    Cost computed from token counts * pricing table rates.
    Budget checks use accumulated usage + current request tokens.
    Warning headers at 80%+ threshold; 429 when exceeded.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pricing Table (USD per 1M tokens) — configurable via env
# ---------------------------------------------------------------------------

DEFAULT_PRICING: Dict[str, Dict[str, float]] = {
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-haiku-4-20250514": {"input": 0.80, "output": 4.00, "cache_read": 0.08, "cache_write": 1.00},
    "claude-opus-4-20250514":  {"input": 15.00, "output": 75.00, "cache_read": 1.50, "cache_write": 18.75},
    "mock":                      {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0},
}

# Budget defaults
DEFAULT_USER_DAILY_TOKEN_LIMIT = 100000
DEFAULT_TENANT_MONTHLY_COST_CAP_USD = 500.0
WARNING_THRESHOLD = 0.80  # 80%


class BudgetExceededError(Exception):
    """Raised when a budget is exceeded."""
    def __init__(self, code: str, message: str, details: Optional[Dict] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


class CostTracker:
    """Tracks AI usage and enforces token/cost budgets.

    Usage:
        tracker = CostTracker()
        tracker.record(session_id, user_id, tenant_id, model, input_tokens, output_tokens)
        budget_ok, info = tracker.check_budget(user_id, tenant_id, estimated_input=500)
    """

    def __init__(self):
        # In-memory usage store (replace with DB for production)
        self._usage: List[Dict[str, Any]] = []
        self._aggregates: Dict[str, Dict[str, Any]] = {}  # key -> {tokens, cost}
        self.pricing = self._load_pricing()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(
        self,
        session_id: str,
        user_id: str,
        tenant_id: str,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        latency_ms: float = 0.0,
    ) -> Dict[str, Any]:
        """Record a usage event after an LLM provider responds.

        Returns the computed cost for this record.
        """
        cost = self._compute_cost(
            model_id, input_tokens, output_tokens,
            cache_read_tokens, cache_write_tokens,
        )

        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "session_id": session_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "model_id": model_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_write_tokens": cache_write_tokens,
            "total_tokens": input_tokens + output_tokens,
            "cost_usd": cost,
            "latency_ms": latency_ms,
        }
        self._usage.append(record)

        # Update aggregates
        today = date.today().isoformat()
        user_key = f"user:{user_id}:{today}"
        tenant_key = f"tenant:{tenant_id}:{date.today().strftime('%Y-%m')}"

        for key in [user_key, tenant_key]:
            agg = self._aggregates.setdefault(key, {
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_cost_usd": 0.0,
            })
            agg["total_input_tokens"] += input_tokens
            agg["total_output_tokens"] += output_tokens
            agg["total_cost_usd"] += cost

        logger.debug(
            "Usage recorded: user=%s model=%s tokens=%d cost=$%.4f",
            user_id, model_id, input_tokens + output_tokens, cost,
        )

        return record

    def check_budget(
        self,
        user_id: str,
        tenant_id: str,
        estimated_input_tokens: int = 0,
        estimated_output_tokens: int = 0,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Check if a request would exceed budgets.

        Returns (allowed, info) where info has budget status details.
        """
        today = date.today().isoformat()
        month = date.today().strftime("%Y-%m")
        user_key = f"user:{user_id}:{today}"
        tenant_key = f"tenant:{tenant_id}:{month}"

        # User daily token budget
        user_agg = self._aggregates.get(user_key, {"total_input_tokens": 0, "total_output_tokens": 0, "total_cost_usd": 0.0})
        user_tokens_used = user_agg["total_input_tokens"] + user_agg["total_output_tokens"]
        user_limit = int(os.getenv("AI_USER_DAILY_TOKEN_LIMIT", str(DEFAULT_USER_DAILY_TOKEN_LIMIT)))
        estimated_new = estimated_input_tokens + estimated_output_tokens

        info = {
            "user_tokens_used": user_tokens_used,
            "user_token_limit": user_limit,
            "user_remaining": max(0, user_limit - user_tokens_used),
            "user_pct_used": (user_tokens_used / user_limit * 100) if user_limit > 0 else 0,
            "tenant_cost_usd": user_agg["total_cost_usd"],
        }

        # Check user daily limit
        if user_tokens_used + estimated_new > user_limit:
            return False, {**info, "exceeded": "user_daily_tokens"}

        # Tenant monthly cost cap
        tenant_agg = self._aggregates.get(tenant_key, {"total_input_tokens": 0, "total_output_tokens": 0, "total_cost_usd": 0.0})
        tenant_cost = tenant_agg["total_cost_usd"]
        tenant_cap = float(os.getenv("AI_TENANT_MONTHLY_COST_CAP_USD", str(DEFAULT_TENANT_MONTHLY_COST_CAP_USD)))

        info["tenant_cost_usd"] = tenant_cost
        info["tenant_cost_cap_usd"] = tenant_cap
        info["tenant_pct_used"] = (tenant_cost / tenant_cap * 100) if tenant_cap > 0 else 0

        if tenant_cost >= tenant_cap:
            return False, {**info, "exceeded": "tenant_monthly_cost"}

        # Warning threshold
        if user_tokens_used / user_limit >= WARNING_THRESHOLD if user_limit > 0 else False:
            info["warning"] = "user_approaching_limit"
        if tenant_cost / tenant_cap >= WARNING_THRESHOLD if tenant_cap > 0 else False:
            info["warning"] = info.get("warning", "") + " tenant_approaching_cap"

        return True, info

    def get_user_usage(self, user_id: str, days: int = 7) -> Dict[str, Any]:
        """Get recent usage for a user."""
        recent = [
            r for r in self._usage
            if r["user_id"] == user_id
        ][-100:]  # Last 100 records

        total_tokens = sum(r["total_tokens"] for r in recent)
        total_cost = sum(r["cost_usd"] for r in recent)

        return {
            "user_id": user_id,
            "records": recent[-days:],
            "total_records": len(recent),
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 4),
            "by_model": self._group_by(recent, "model_id", "total_tokens"),
        }

    def get_tenant_usage(self, tenant_id: str) -> Dict[str, Any]:
        """Get monthly usage for a tenant."""
        month = date.today().strftime("%Y-%m")
        tenant_key = f"tenant:{tenant_id}:{month}"
        agg = self._aggregates.get(tenant_key, {
            "total_input_tokens": 0, "total_output_tokens": 0, "total_cost_usd": 0.0,
        })

        return {
            "tenant_id": tenant_id,
            "period": month,
            **agg,
        }

    def get_usage_report(self) -> Dict[str, Any]:
        """Get a summary usage report."""
        today = date.today().isoformat()
        total_tokens = sum(r["total_tokens"] for r in self._usage)
        total_cost = sum(r["cost_usd"] for r in self._usage)

        # Today's usage
        today_records = [r for r in self._usage if r["timestamp"].startswith(today)]
        today_tokens = sum(r["total_tokens"] for r in today_records)
        today_cost = sum(r["cost_usd"] for r in today_records)

        return {
            "total_tokens_all_time": total_tokens,
            "total_cost_all_time_usd": round(total_cost, 4),
            "today_tokens": today_tokens,
            "today_cost_usd": round(today_cost, 4),
            "total_requests": len(self._usage),
            "by_model": self._group_by(self._usage, "model_id", "total_tokens"),
        }

    # ------------------------------------------------------------------
    # Pricing
    # ------------------------------------------------------------------

    def _compute_cost(
        self, model_id: str, input_tokens: int, output_tokens: int,
        cache_read: int = 0, cache_write: int = 0,
    ) -> float:
        """Compute USD cost from token counts and pricing table."""
        rates = self.pricing.get(model_id, self.pricing.get("mock", {"input": 0, "output": 0}))

        cost = 0.0
        cost += (input_tokens / 1_000_000) * rates.get("input", 0)
        cost += (output_tokens / 1_000_000) * rates.get("output", 0)
        cost += (cache_read / 1_000_000) * rates.get("cache_read", 0)
        cost += (cache_write / 1_000_000) * rates.get("cache_write", 0)
        return round(cost, 6)

    def _load_pricing(self) -> Dict[str, Dict[str, float]]:
        """Load pricing table from env or defaults."""
        pricing = dict(DEFAULT_PRICING)
        raw = os.getenv("AI_PRICING_TABLE", "")
        if raw:
            try:
                import json
                custom = json.loads(raw)
                pricing.update(custom)
            except Exception:
                logger.warning("Failed to parse AI_PRICING_TABLE, using defaults")
        return pricing

    @staticmethod
    def _group_by(records: List[Dict], key: str, sum_key: str) -> Dict[str, Any]:
        """Group records by a key and sum a numeric field."""
        result: Dict[str, Any] = {}
        for r in records:
            k = r.get(key, "unknown")
            result.setdefault(k, 0)
            result[k] += r.get(sum_key, 0)
        return result
