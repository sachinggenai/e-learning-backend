# US-BKND-AI-036: Cost Tracking and Token Budget Enforcement

**Status:** ✅ COMPLETE
**Priority:** SHOULD
**Sprint:** 6
**Implemented:** 2026-06-15

## Summary

Cost tracker service that records AI token usage after every LLM provider response, computes costs from a configurable pricing table, enforces per-user daily token limits and per-tenant monthly cost caps, and provides usage reporting with per-model breakdowns.

## Files Created/Modified

| File | Action | Description |
|---|---|---|
| `app/services/ai/cost_tracker.py` | NEW | CostTracker with usage recording, cost computation, budget checks, usage reports, pricing table |
| `tests/run_cost_tracking_tests.py` | NEW | 41 tests covering recording, pricing, budgets, warnings, reports |

## Pricing Table (USD per 1M tokens)

| Model | Input | Output | Cache Read | Cache Write |
|---|---|---|---|---|
| claude-sonnet-4 | $3.00 | $15.00 | $0.30 | $3.75 |
| claude-haiku-4 | $0.80 | $4.00 | $0.08 | $1.00 |
| claude-opus-4 | $15.00 | $75.00 | $1.50 | $18.75 |
| mock | $0 | $0 | $0 | $0 |

## Key Design Decisions

1. **Post-billing** — Usage recorded after provider responds; no pre-request estimation
2. **Cost computed, not stored** — Raw token counts stored; cost computed from pricing table for flexibility
3. **80% warning threshold** — Warning info returned before hard limit is reached
4. **Configurable pricing** — Pricing table loadable from AI_PRICING_TABLE env var as JSON
5. **Per-user daily token limits** (default 100K) + per-tenant monthly cost caps (default $500)
