# US-BKND-AI-049: Confirmation Token System for Destructive Operations

**Status:** ✅ COMPLETE
**Priority:** MUST
**Sprint:** 2
**Implemented:** 2026-06-15

## Summary

Centralized Confirmation Token Service providing reusable token generation, scope binding (HMAC-SHA256), hashing, expiry, and validation uniformly across all destructive operation types (page delete, course delete, batch operations, asset removal).

## Files Created/Modified

| File | Action | Description |
|---|---|---|
| `app/services/ai/confirmation_token_service.py` | NEW | Core service: generate_token(), validate_token(), verify_resource_hash() |
| `app/schemas/ai_confirmation.py` | NEW | Pydantic DTOs: TokenValidationRequest, AdminOverrideRequest, ConfirmationResponse, etc. |
| `app/routers/ai_confirmations.py` | NEW | Generic POST /api/v1/ai/proposals/{id}/confirm endpoint |
| `app/models/ai_admin_override.py` | NEW | ORM model for ai_admin_overrides audit trail table |
| `app/models/ai_models.py` | MODIFIED | Added confirmation_token_sha256, confirmation_token_expires_at, confirmation_ttl_override_minutes, before_snapshot to AIProposalRecord |
| `app/models/__init__.py` | MODIFIED | Export AIAdminOverrideRecord |
| `app/services/ai/__init__.py` | MODIFIED | Updated docstring to include confirmation_token_service |
| `app/main.py` | MODIFIED | Registered ai_confirmations router; import ai_admin_override for table creation |
| `.env.example` | MODIFIED | Added AI_CONFIRMATION_TOKEN_TTL_MINUTES, AI_CONFIRMATION_TOKEN_TTL_OVERRIDES, AI_ADMIN_CONFIRMATION_BYPASS_ENABLED, etc. |
| `tests/run_confirmation_token_tests.py` | NEW | Comprehensive standalone test suite (67 tests, all passing) |

## Key Design Decisions

1. **Existing model adaptation:** Works with `AIProposalRecord.action_type` (not `operation`) to match the existing codebase convention
2. **Dual status support:** Accepts both `"PENDING_CONFIRMATION"` and `"pending"` as confirmable statuses
3. **Stateless service:** No DB session needed in constructor — token state is persisted in proposals
4. **HMAC-SHA256 scope binding:** `HMAC(token, sorted_scope_string)` for protection against length extension attacks
5. **Admin override:** Bypasses token validation but requires 20+ char reason; rate-limited separately

## See Also

- [US-AI-049 Full Spec](../US-AI-049_CONFIRMATION_TOKEN_SYSTEM.md) — Complete functional and technical specification
- [US-BKND-AI-013](../backend-userstories/US-BKND-AI-013_enriched.md) — Next story: Delete Page Proposal (depends on this)
