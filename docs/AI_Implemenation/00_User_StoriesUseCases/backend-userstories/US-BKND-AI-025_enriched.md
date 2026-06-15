# US-BKND-AI-025: Prompt Safety and Content Guardrails

**Status:** ✅ COMPLETE
**Priority:** MUST
**Sprint:** 5
**Implemented:** 2026-06-15

## Summary

Three-layer guardrail system for AI chat safety: (1) Input Guard detects 9 prompt injection/jailbreak patterns, (2) PII Scanner detects 10 PII types with redact/reject/mask modes, (3) Output Guard blocks 7 configurable blocked terms plus PII leaks. Safety events are persisted non-blocking for admin audit.

## Files Created/Modified

| File | Action | Description |
|---|---|---|
| `app/services/ai/safety_service.py` | MODIFIED | Added safety event persistence (non-blocking), configurable blocked terms via env, 3 new injection patterns, 3 new PII patterns, trace_id tracking, safe fallback message |
| `app/models/ai_safety_event.py` | NEW | ORM model for `ai_safety_events` table with indexes and constraints |
| `app/repositories/ai_safety_event_repo.py` | NEW | Repository with `create_non_blocking()`, `list_by_type()`, `count_by_type()` |
| `app/routers/ai_admin.py` | NEW | Admin endpoints: list/get safety events, safety statistics |
| `app/models/__init__.py` | MODIFIED | Export AISafetyEvent |
| `app/main.py` | MODIFIED | Register ai_admin router, import ai_safety_event for table creation |
| `.env.example` | MODIFIED | Added AI_PII_REDACTION_MODE, AI_BLOCKED_TERMS_LIST, AI_PII_SCAN_IPS |
| `tests/run_safety_guardrails_tests.py` | NEW | 57 tests covering injection, PII, output blocking, configurable terms, disabled modes |

## Key Design Decisions

1. **Non-blocking persistence** — Safety event writes are fire-and-forget. Failures are logged, never block the request pipeline.
2. **Configurable blocked terms** — `AI_BLOCKED_TERMS_LIST` env var allows operators to customize blocked output terms.
3. **Three PII modes** — reject (block prompt), redact (replace with placeholders), mask (asterisk middle characters).
4. **Enhanced patterns** — 9 injection patterns (up from 6), 10 PII patterns (up from 7), including GitHub/Google/Facebook tokens.
5. **Admin audit trail** — Safety events queryable via `GET /api/v1/ai/admin/safety-events` and `GET /api/v1/ai/admin/safety-stats`.
6. **Safe fallback** — Blocked outputs return a consistent safe message: "I'm sorry, I can't provide that response."

## See Also

- [US-AI-025 Full Spec](../US-AI-025_PROMPT_SAFETY_CONTENT_GUARDRAILS.md) — Complete specification
- [US-BKND-AI-023](US-BKND-AI-023_enriched.md) — AI Chat Endpoint (integrates with safety scanning)
