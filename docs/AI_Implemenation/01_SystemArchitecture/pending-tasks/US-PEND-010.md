# US-PEND-010: Fix TOCTOU Race — cancel_job Returns HTTP 500 Instead of 409

| Field | Value |
|-------|-------|
| **Type** | 🐛 Bug |
| **Priority** | 🟢 MEDIUM |
| **Batch** | 2 — Config/Migration Fixes |
| **Depends On** | None |
| **Estimated Effort** | 10 minutes |
| **Target File** | `app/routers/workflows.py` lines 260-272 |

---

## User Story

**As a** frontend developer integrating the workflow API,  
**I want** the cancel endpoint to return HTTP 409 Conflict when the job is already in a terminal state,  
**So that** I can show the correct error message to the user instead of a generic "Internal Server Error."

---

## Intent of Work

The `cancel_workflow` endpoint calls `_get_job_or_404()` which opens its own DB session, fetches the job, and closes the session — returning a **detached** ORM object. The caller checks the detached object's status. If the job's status changes between the fetch and the actual cancel operation (a TOCTOU race), `orchestrator.cancel_job()` returns `False`. The router then converts this to `HTTPException(status_code=500)` — a generic Internal Server Error. It should be `status_code=409 Conflict` since the resource state changed between read and write.

---

## Current State

```python
# routers/workflows.py, lines 260-272
job = await _get_job_or_404(job_id)  # Returns detached object
if job.status not in ("pending", "running"):
    raise HTTPException(status_code=409, detail="...")  # Correct for THIS check

# ... later ...
success = await orch.cancel_job(job_id)
if not success:
    raise HTTPException(status_code=500, detail="Failed to cancel job")  # ← BUG: should be 409
```

**Facts confirmed (2026-06-21):**
- `_get_job_or_404` creates its own `AsyncSession`, fetches job, closes session → detached object
- Between the status check and `cancel_job()`, another worker could complete the job
- `orchestrator.cancel_job()` returns `False` when job is not in a cancellable state
- Same pattern exists in `retry_workflow` endpoint

---

## Expected State

```python
success = await orch.cancel_job(job_id)
if not success:
    raise HTTPException(
        status_code=409,
        detail="Job cannot be cancelled. It may have already completed or been cancelled by another request."
    )
```

---

## Technical Details

### Implementation Steps

1. Open `app/routers/workflows.py`
2. Line 272: Change `status_code=500` → `status_code=409`
3. Update error message to explain the race condition
4. Apply same fix to `retry_workflow` endpoint if it has the same pattern
5. Verify: existing tests still pass

### Scope Boundary

- **IN SCOPE:** Fix HTTP status code in cancel and retry endpoints
- **OUT OF SCOPE:** Changing the TOCTOU architecture (that's a larger refactor — the race is harmless, just the error code is wrong)

---

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-1 | `cancel_job` returning `False` produces HTTP 409, not 500 |
| AC-2 | `retry_job` returning `False` produces HTTP 409, not 500 |
| AC-3 | Error message explains the conflict (not generic "Failed to cancel") |

---

## Functional Expectations

- Frontend receives proper HTTP semantics: 409 = "conflict with current state"
- Frontend can retry (fetch latest status and re-render) instead of showing "Server Error"

## Non-Functional Expectations

- Zero change to orchestrator behavior
- Zero change to database queries

---

## Validation Steps

```bash
# Manual check: status codes in source
grep -n "status_code=500" app/routers/workflows.py
# Should return 0 matches for cancel/retry paths

# Run tests
python tests/run_workflow_engine_tests.py
```
