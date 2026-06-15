# US-BKND-AI-013: Propose and Confirm Destructive Page Deletes

**Status:** ✅ COMPLETE
**Priority:** MUST
**Sprint:** 3
**Implemented:** 2026-06-15

## Summary

Two-phase gate for AI-proposed page deletion: (1) propose with dependency analysis and confirmation token, (2) confirm with token validation and transactional execution. Integrates with ConfirmationTokenService (US-BKND-AI-049) for scope-bound token gating.

## Files Created/Modified

| File | Action | Description |
|---|---|---|
| `app/services/ai/dependency_analyzer.py` | NEW | Impact analysis for branching, scoring, final assessment, navigation |
| `app/services/ai/proposal_service.py` | MODIFIED | Added propose_delete_page(), confirm_delete_page(), _compute_page_hash() |
| `app/routers/ai_proposals.py` | MODIFIED | Added POST delete-page and POST confirm-delete endpoints + DTOs |
| `tests/run_delete_proposal_tests.py` | NEW | 46 tests covering analyzer, hashing, service interfaces, router schemas, error handling, integration |

## Key Design Decisions

1. **Reuses AIProposalService** — New methods added to the existing service class rather than creating a separate orchestrator
2. **Works with existing schema** — Uses `action_type`, `target_type`, `target_id` columns (not separate `page_id`/`course_id` columns)
3. **ConfirmationTokenService integration** — Delegates token generation and validation to the centralized service from US-BKND-AI-049
4. **Deterministic page hash** — Includes page_id, title, order_index, updated_at, and all component IDs/types/orders/updated_ats
5. **Duplicate proposal detection** — Checks for existing pending delete proposals for the same page before creating a new one
6. **Idempotent delete** — Returns "already_deleted" if page no longer exists at confirmation time

## See Also

- [US-AI-013 Full Spec](../US-AI-013_DELETE_PAGE_EPIC.md) — Complete functional and technical specification
- [US-BKND-AI-049](US-BKND-AI-049_enriched.md) — Confirmation Token System (dependency)
