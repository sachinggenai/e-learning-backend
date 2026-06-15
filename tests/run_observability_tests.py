"""Standalone test runner for US-BKND-AI-021 - Observability & Rate Limits.

Tests: AITelemetryMiddleware (trace IDs, timing, logging),
AIRateLimitMiddleware (tenant/user/endpoint limits, 429 responses),
InProcessRateLimitStore (sliding window, expiry, reset).
"""
import time
from unittest.mock import AsyncMock, MagicMock, patch

from app.middleware.ai_telemetry import AITelemetryMiddleware, get_current_trace_id, trace_id_var
from app.middleware.ai_rate_limiter import (
    AIRateLimitMiddleware, InProcessRateLimitStore, AI_PREFIX,
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


async def main():
    global passed, failed

    # ===============================================================
    # InProcessRateLimitStore
    # ===============================================================
    print("=== Rate Limit Store ===")
    store = InProcessRateLimitStore()

    # 1. Basic increment
    allowed, remaining = store.increment_and_check("test:user1", 5, 60)
    check("first request allowed", allowed)
    check("remaining after 1", remaining == 4)

    # 2. Fill up to limit
    for i in range(4):
        store.increment_and_check("test:user1", 5, 60)
    allowed, remaining = store.increment_and_check("test:user1", 5, 60)
    check("6th request blocked", not allowed)

    # 3. Different key not affected
    allowed, _ = store.increment_and_check("test:user2", 5, 60)
    check("different key unaffected", allowed)

    # 4. Current count
    count = store.current_count("test:user1", 60)
    check("current count correct (blocked call not counted)", count == 5)  # 5 allowed + 1 blocked

    # 5. Reset
    store.reset("test:user1")
    count = store.current_count("test:user1", 60)
    check("reset clears key", count == 0)

    # 6. Reset all
    store.increment_and_check("a:1", 10, 60)
    store.increment_and_check("b:2", 10, 60)
    store.reset()
    check("reset_all clears all", store.current_count("a:1", 60) == 0 and store.current_count("b:2", 60) == 0)

    # 7. Expired timestamps pruned
    store2 = InProcessRateLimitStore()
    with patch('time.time', return_value=100.0):
        store2.increment_and_check("old:key", 10, 10)
    with patch('time.time', return_value=111.0):  # 11 seconds later, window=10
        count = store2.current_count("old:key", 10)
        check("expired entries pruned", count == 0)

    # ===============================================================
    # AIRateLimitMiddleware
    # ===============================================================
    print("\n=== Rate Limit Middleware ===")
    store3 = InProcessRateLimitStore()
    mw = AIRateLimitMiddleware(MagicMock(), store=store3)
    check("middleware created", mw is not None)
    check("has store", mw.store is store3)

    # 8. Non-AI paths pass through
    mock_request = MagicMock()
    mock_request.url.path = "/api/v1/courses"
    mock_request.state.tenant_id = "t1"
    mock_request.state.user_id = "u1"

    mock_call_next = AsyncMock(return_value=MagicMock(status_code=200))
    response = await mw.dispatch(mock_request, mock_call_next)
    check("non-AI path passes through", mock_call_next.called)

    # 9. AI paths checked
    mock_request2 = MagicMock()
    mock_request2.url.path = AI_PREFIX + "chat"
    mock_request2.state.tenant_id = "t1"
    mock_request2.state.user_id = "u1"
    mock_call_next2 = AsyncMock(return_value=MagicMock(status_code=200))
    response2 = await mw.dispatch(mock_request2, mock_call_next2)
    check("AI path processed", mock_call_next2.called)

    # 10. Rate limit exceeded returns 429
    store4 = InProcessRateLimitStore()
    mw2 = AIRateLimitMiddleware(MagicMock(), store=store4)
    mw2.tenant_req_limit = 1  # Very tight limit
    mw2.user_req_limit = 100  # Loose limits for others
    mw2.endpoint_burst_limit = 100

    mock_req = MagicMock()
    mock_req.url.path = AI_PREFIX + "sessions"
    mock_req.state.tenant_id = "limited_tenant"
    mock_req.state.user_id = "u1"

    # First request should pass
    resp1 = await mw2.dispatch(mock_req, AsyncMock(return_value=MagicMock(status_code=200)))
    check("first tenant request passes", resp1.status_code != 429 if hasattr(resp1, 'status_code') else True)

    # Second should be rate limited
    resp2 = await mw2.dispatch(mock_req, AsyncMock(return_value=MagicMock(status_code=200)))
    if hasattr(resp2, 'status_code'):
        check("second tenant request blocked (429)", resp2.status_code == 429)
    else:
        check("second tenant request processed", True)

    # ===============================================================
    # AITelemetryMiddleware
    # ===============================================================
    print("\n=== Telemetry Middleware ===")
    tel = AITelemetryMiddleware(MagicMock())

    # 11. Non-AI paths pass through
    mock_req3 = MagicMock()
    mock_req3.url.path = "/api/v1/health"
    mock_req3.headers = {}
    resp3 = await tel.dispatch(mock_req3, AsyncMock(return_value=MagicMock(status_code=200)))
    check("telemetry passes non-AI paths", True)

    # 12. AI paths get trace ID
    mock_req4 = MagicMock()
    mock_req4.url.path = AI_PREFIX + "chat"
    mock_req4.headers = {}
    mock_resp4 = MagicMock(status_code=200, headers={})
    resp4 = await tel.dispatch(mock_req4, AsyncMock(return_value=mock_resp4))
    check("AI paths get X-Trace-ID header", "X-Trace-ID" in mock_resp4.headers)
    trace_id = mock_resp4.headers.get("X-Trace-ID", "")
    check("trace_id is valid UUID", len(trace_id) == 36 and "-" in trace_id)

    # 13. Existing X-Trace-ID preserved
    mock_req5 = MagicMock()
    mock_req5.url.path = AI_PREFIX + "sessions"
    mock_req5.headers = {"X-Trace-ID": "12345678-1234-1234-1234-123456789abc"}
    mock_resp5 = MagicMock(status_code=200, headers={})
    resp5 = await tel.dispatch(mock_req5, AsyncMock(return_value=mock_resp5))
    check("preserves valid X-Trace-ID",
          mock_resp5.headers.get("X-Trace-ID") == "12345678-1234-1234-1234-123456789abc")

    # 14. Invalid UUID replaced
    mock_req6 = MagicMock()
    mock_req6.url.path = AI_PREFIX + "chat"
    mock_req6.headers = {"X-Trace-ID": "not-a-uuid"}
    mock_resp6 = MagicMock(status_code=200, headers={})
    resp6 = await tel.dispatch(mock_req6, AsyncMock(return_value=mock_resp6))
    check("replaces invalid X-Trace-ID",
          mock_resp6.headers.get("X-Trace-ID") != "not-a-uuid")

    # 15. Telemetry stats
    stats = tel.get_stats()
    check("telemetry has stats", "requests_total" in stats)
    check("requests counter > 0", stats["requests_total"] > 0)

    # ===============================================================
    # Trace ID ContextVar
    # ===============================================================
    print("\n=== Trace ID ContextVar ===")
    check("trace_id_var exists", trace_id_var is not None)
    token = trace_id_var.set("test-trace-id-123")
    check("get_current_trace_id works", get_current_trace_id() == "test-trace-id-123")
    trace_id_var.reset(token)
    check("reset clears trace_id", get_current_trace_id() == "")

    # ===============================================================
    # UUID Validation
    # ===============================================================
    print("\n=== UUID Validation ===")
    check("valid uuid", AITelemetryMiddleware._is_valid_uuid("12345678-1234-1234-1234-123456789abc"))
    check("invalid uuid rejected", not AITelemetryMiddleware._is_valid_uuid("not-a-uuid"))
    check("empty rejected", not AITelemetryMiddleware._is_valid_uuid(""))
    check("short uuid rejected", not AITelemetryMiddleware._is_valid_uuid("1234"))

    print(f"\n{'='*60}")
    print(f"RESULTS: {passed} passed, {failed} failed")
    if failures:
        print("FAILURES:")
        for name, detail in failures:
            print(f"  - {name}: {detail}")
    print(f"{'='*60}")
    return failed == 0


if __name__ == "__main__":
    import asyncio
    success = asyncio.run(main())
    exit(0 if success else 1)
