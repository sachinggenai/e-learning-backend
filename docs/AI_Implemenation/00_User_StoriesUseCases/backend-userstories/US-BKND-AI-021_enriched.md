# US-BKND-AI-021: Production Observability, Rate Limits, and Rollout Gates

**Status:** ✅ COMPLETE
**Priority:** MUST
**Sprint:** 6
**Implemented:** 2026-06-15

## Summary

Production-grade operational controls for the AI authoring subsystem: trace ID propagation across all AI requests, per-user/per-tenant/per-endpoint rate limiting with sliding-window counters, and structural telemetry for monitoring dashboards.

## Files Created/Modified

| File | Action | Description |
|---|---|---|
| `app/middleware/ai_telemetry.py` | NEW | Trace ID propagation, request timing, structured logging, contextvar |
| `app/middleware/ai_rate_limiter.py` | NEW | InProcessRateLimitStore + AIRateLimitMiddleware for tenant/user/endpoint limits |
| `app/main.py` | MODIFIED | Registered AITelemetryMiddleware and AIRateLimitMiddleware |
| `tests/run_observability_tests.py` | NEW | 28 tests covering rate limit store, middleware dispatch, trace IDs, UUID validation |

## Rate Limit Categories

| Category | Default Limit | Window |
|---|---|---|
| Tenant requests | 1000 | 1 minute |
| User requests | 100 | 1 minute |
| Endpoint burst | 20 | 10 seconds |

## Key Design Decisions

1. **In-process rate store (MVP)** — Sliding-window counters in memory; replaceable with Redis for multi-instance deployment
2. **Middleware ordering** — Rate limiter outermost (can short-circuit with 429), telemetry innermost (traces all passing requests)
3. **ContextVar for trace_id** — Services access trace_id via `get_current_trace_id()` without passing it through function signatures
4. **Fail-open on store issues** — Rate limit store failures allow requests through rather than blocking
5. **Blocked requests not counted** — Rate-limited requests don't increment counters (prevents lockout)
6. **Structured 429 responses** — Retry-After header + JSON error envelope matching AI error pattern

## Configuration (env vars)

- `AI_RATE_LIMIT_USER_REQUESTS` (default: 100)
- `AI_RATE_LIMIT_TENANT_REQUESTS` (default: 1000)
- `AI_RATE_LIMIT_ENDPOINT_BURST` (default: 20)

## See Also

- [US-AI-021 Full Spec](../US-AI-021_OBSERVABILITY_RATE_LIMITS_ROLLOUT_GATES.md) — Complete specification
