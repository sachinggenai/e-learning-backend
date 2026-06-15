# US-BKND-AI-050: Stale Detection and Merge Resolution

**Status:** ✅ COMPLETE
**Priority:** SHOULD
**Sprint:** 7
**Implemented:** 2026-06-15

## Summary

Stale proposal detection with three-level classification (current, compatible, conflict), three-way auto-merge for non-overlapping changes, structured conflict reporting with field-level diff details, and force-overwrite capability for explicit user confirmation scenarios.

## Files Created/Modified

| File | Action | Description |
|---|---|---|
| `app/services/ai/stale_detector.py` | NEW | StaleDetector with SHA-256 hashing, staleness classification, three-way merge, conflict reporting, force overwrite |
| `tests/run_stale_detection_tests.py` | NEW | 32 tests covering hashing, all staleness levels, auto-merge, conflicts, edge cases |

## Staleness Classification

| Level | Condition | Action |
|---|---|---|
| CURRENT | base_hash == current_hash | Apply changes directly |
| STALE_COMPATIBLE | Non-overlapping local+remote changes | Auto-merge both sets of changes |
| STALE_CONFLICT | Same field changed in both | Return structured conflict report |

## Key Design Decisions

1. **Deterministic SHA-256 hashing** — JSON serialized with sorted keys for consistency
2. **Field-level diff** — Compares individual keys rather than full state strings for precise conflict detection
3. **Three-way merge** — BASE (fetched state) vs LOCAL (current DB) vs REMOTE (AI proposed) using `_diff_states` and `_apply_changes`
4. **Force overwrite** — Preserves current state for audit trail, requires explicit user confirmation
5. **Nested dict handling** — Deep merge for nested objects, shallow overwrite for scalars
