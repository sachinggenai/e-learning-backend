"""Standalone test runner for US-BKND-AI-036 - Cost Tracking.

Tests CostTracker: usage recording, cost computation, budget checks,
warning thresholds, pricing table, usage reports.
"""
import os
from datetime import date
from unittest.mock import patch

from app.services.ai.cost_tracker import (
    CostTracker, BudgetExceededError,
    DEFAULT_USER_DAILY_TOKEN_LIMIT, DEFAULT_TENANT_MONTHLY_COST_CAP_USD,
    WARNING_THRESHOLD, DEFAULT_PRICING,
)

passed = 0
failed = 0
failures = []


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        failures.append((name, detail))
        print(f"  FAIL: {name} -- {detail}")


def main():
    global passed, failed

    # ===============================================================
    # Usage Recording
    # ===============================================================
    print("=== Usage Recording ===")
    tracker = CostTracker()

    # 1. Record usage
    rec = tracker.record("sess_1", "user_1", "tenant_1", "claude-sonnet-4-20250514",
                         input_tokens=500, output_tokens=200)
    check("record returns dict", isinstance(rec, dict))
    check("record has cost", rec["cost_usd"] > 0)
    check("record has tokens", rec["total_tokens"] == 700)
    check("record has model", rec["model_id"] == "claude-sonnet-4-20250514")

    # 2. Mock model (free)
    rec2 = tracker.record("sess_2", "user_2", "t2", "mock",
                          input_tokens=1000, output_tokens=500)
    check("mock model is free", rec2["cost_usd"] == 0.0)

    # 3. Multiple records accumulate
    tracker.record("sess_1", "user_1", "tenant_1", "claude-haiku-4-20250514",
                   input_tokens=300, output_tokens=100)
    usage = tracker.get_user_usage("user_1")
    check("user has 2 records", usage["total_records"] >= 2)
    check("user tokens accumulate", usage["total_tokens"] > 700)

    # ===============================================================
    # Cost Computation
    # ===============================================================
    print("\n=== Cost Computation ===")
    # Sonnet: $3/M input, $15/M output
    # 500 input = 500/1M * 3 = 0.0015
    # 200 output = 200/1M * 15 = 0.003
    # Total ≈ $0.0045
    cost = tracker._compute_cost("claude-sonnet-4-20250514", 500, 200)
    check("sonnet cost ~$0.0045", abs(cost - 0.0045) < 0.0001)

    # Haiku: $0.80/M input, $4/M output
    cost = tracker._compute_cost("claude-haiku-4-20250514", 500, 200)
    check("haiku cost ~$0.0012", abs(cost - 0.0012) < 0.0001)

    # Opus: $15/M input, $75/M output
    cost = tracker._compute_cost("claude-opus-4-20250514", 500, 200)
    check("opus cost ~$0.0225", abs(cost - 0.0225) < 0.0001)

    # Cache tokens
    cost = tracker._compute_cost("claude-sonnet-4-20250514", 0, 0, cache_read=100000, cache_write=50000)
    check("cache cost computed", cost > 0)

    # ===============================================================
    # Budget Checks
    # ===============================================================
    print("\n=== Budget Checks ===")
    tracker2 = CostTracker()

    # 4. Under budget
    allowed, info = tracker2.check_budget("user_a", "tenant_a")
    check("under budget", allowed)

    # 5. Budget info has required fields
    for field in ["user_tokens_used", "user_token_limit", "user_remaining"]:
        check(f"budget info has {field}", field in info)

    # 6. Simulate heavy usage that exceeds user daily limit
    tracker3 = CostTracker()
    # Record 100K tokens
    tracker3.record("s", "heavy_user", "t", "claude-sonnet-4-20250514",
                    input_tokens=90000, output_tokens=10000)
    allowed, info = tracker3.check_budget("heavy_user", "t", estimated_input_tokens=5000)
    check("heavy user at limit", not allowed)
    check("exceeded code", info.get("exceeded") == "user_daily_tokens")

    # 7. Warning threshold at 80%
    tracker4 = CostTracker()
    limit = DEFAULT_USER_DAILY_TOKEN_LIMIT
    tracker4.record("s", "warn_user", "t", "mock",
                    input_tokens=int(limit * 0.85), output_tokens=0)
    allowed, info = tracker4.check_budget("warn_user", "t")
    check("warning at 85%", "warning" in info or not allowed)

    # 8. Tenant cost cap
    tracker5 = CostTracker()
    # Simulate $600 of usage (above $500 cap)
    tracker5.record("s", "u", "big_tenant", "claude-opus-4-20250514",
                    input_tokens=40000000, output_tokens=0)  # ~$600
    allowed, info = tracker5.check_budget("u2", "big_tenant")
    check("tenant over cost cap", not allowed or info.get("tenant_pct_used", 0) > 80)

    # ===============================================================
    # Pricing Table
    # ===============================================================
    print("\n=== Pricing Table ===")
    check("has sonnet pricing", "claude-sonnet-4-20250514" in DEFAULT_PRICING)
    check("has haiku pricing", "claude-haiku-4-20250514" in DEFAULT_PRICING)
    check("has opus pricing", "claude-opus-4-20250514" in DEFAULT_PRICING)
    check("has mock pricing", "mock" in DEFAULT_PRICING)
    rates = DEFAULT_PRICING["claude-sonnet-4-20250514"]
    check("sonnet input rate", rates["input"] == 3.00)
    check("sonnet output rate", rates["output"] == 15.00)

    # ===============================================================
    # Usage Reports
    # ===============================================================
    print("\n=== Usage Reports ===")
    tracker6 = CostTracker()
    tracker6.record("s1", "u1", "t1", "claude-sonnet-4-20250514", 100, 50)
    tracker6.record("s2", "u1", "t1", "claude-haiku-4-20250514", 200, 100)

    # User report
    report = tracker6.get_user_usage("u1")
    check("user report has records", len(report["records"]) > 0)
    check("user report has total_tokens", report["total_tokens"] > 0)
    check("user report has total_cost", report["total_cost_usd"] > 0)
    check("user report has by_model", len(report["by_model"]) >= 1)

    # Tenant report
    report = tracker6.get_tenant_usage("t1")
    check("tenant report has period", "period" in report)
    check("tenant report has tokens", report["total_input_tokens"] > 0)

    # Global report
    report = tracker6.get_usage_report()
    check("global report has total_tokens", report["total_tokens_all_time"] > 0)
    check("global report has total_cost", report["total_cost_all_time_usd"] > 0)
    check("global report has today_tokens", "today_tokens" in report)
    check("global report has by_model", len(report["by_model"]) >= 1)
    check("global report has total_requests", report["total_requests"] > 0)

    # ===============================================================
    # Defaults
    # ===============================================================
    print("\n=== Defaults ===")
    check("default user daily tokens", DEFAULT_USER_DAILY_TOKEN_LIMIT == 100000)
    check("default tenant monthly cost", DEFAULT_TENANT_MONTHLY_COST_CAP_USD == 500.0)
    check("warning threshold 0.80", WARNING_THRESHOLD == 0.80)

    # ===============================================================
    # BudgetExceededError
    # ===============================================================
    print("\n=== BudgetExceededError ===")
    e = BudgetExceededError("USER_DAILY_LIMIT", "Daily token limit exceeded",
                            details={"limit": 100000, "used": 100000})
    check("error code", e.code == "USER_DAILY_LIMIT")
    check("error details", e.details["limit"] == 100000)

    print(f"\n{'='*60}")
    print(f"RESULTS: {passed} passed, {failed} failed")
    if failures:
        print("FAILURES:")
        for name, detail in failures:
            print(f"  - {name}: {detail}")
    print(f"{'='*60}")
    return failed == 0


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
