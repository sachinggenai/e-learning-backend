# US-PEND-011: Persist Checkpoint Data on Step Failure Before Retry

| Field | Value |
|-------|-------|
| **Type** | 🐛 Bug |
| **Priority** | 🟡 HIGH |
| **Batch** | 3 — Reliability Fixes |
| **Depends On** | US-PEND-001, US-PEND-002, US-PEND-003 (same file must be importable) |
| **Estimated Effort** | 2.5 hours |
| **Target Files** | `app/services/workflow/orchestrator.py:326`, new method in `app/repositories/workflow_repository.py` |

---

## ⚠️ CRITICAL: Verified Repository API

After re-verifying `workflow_repository.py` (2026-06-21), here is the EXACT state:

| Method | Exists? | Accepts `checkpoint_data`? | What it does |
|--------|---------|---------------------------|--------------|
| `increment_retry(job_id)` | ✅ Line 299 | ❌ NO | Increments retry_count, sets status="pending", locked_by=None. Does NOT touch checkpoint_data. |
| `transition(job_id, new_status, new_state, previous_state, ...)` | ✅ Line 220 | ✅ YES (optional) | Full state transition with optional checkpoint_data. But REQUIRES `new_state` and `previous_state` which are available in the orchestrator loop. |
| `update_checkpoint(job_id, checkpoint_data)` | ❌ DOES NOT EXIST | N/A | Must be CREATED |

**Decision:** Create a NEW `update_checkpoint()` method. This is cleaner than overloading `transition()` which requires `new_state` and `previous_state` that don't change on retry.

---

## User Story

**As a** course author running a 50-page course generation job,
**I want** the job to resume from the last successfully generated page if it fails and retries,
**So that** I don't pay for 48 pages of LLM generation that get thrown away on a transient error.

---

## Intent of Work

When a workflow step fails but retries are allowed, the orchestrator calls `increment_retry()` which resets the job to `pending` status. However, it does **NOT** persist the checkpoint data accumulated during the failed attempt. On retry, `generate_pages` starts from `checkpoint.get("pages_state", {}).get("results", [])` — which is empty because the checkpoint was never saved.

For a 50-page course where the step fails on page 48 due to a transient LLM API error:
- 48 successfully generated pages are stored only in memory and **lost**
- On retry, generation restarts from page 0
- 48 LLM API calls wasted

---

## Current State (Code Verified 2026-06-21)

```python
# orchestrator.py, lines 315-327 — ACTUAL CODE ON DISK
if attempt <= max_retries_for_state and (
    job_max == 0 or attempt <= job_max
):
    job_logger.warning(
        "State '%s' failed (attempt %d/%d). Retrying.",
        current_state_name, attempt, max_retries_for_state,
    )
    await repo.append_event(...)
    await repo.increment_retry(job.job_id)  # ← BUG: checkpoint NOT saved
    return  # Exit; poll loop re-locks on next cycle
```

```python
# workflow_repository.py, lines 299-314 — ACTUAL CODE ON DISK
async def increment_retry(self, job_id: uuid.UUID) -> Optional[WorkflowJob]:
    stmt = (
        update(WorkflowJob)
        .where(WorkflowJob.job_id == job_id)
        .values(
            retry_count=WorkflowJob.retry_count + 1,
            current_retry_state=WorkflowJob.current_state,
            status="pending",
            locked_by=None,
            updated_at=datetime.utcnow(),
        )
        .returning(WorkflowJob)
    )
    result = await self.session.execute(stmt)
    await self.session.commit()
    return result.scalar_one_or_none()
    # NOTE: checkpoint_data is NOT in the values dict — NOT PERSISTED
```

---

## Expected State

### Step 1: Add `update_checkpoint()` method to `WorkflowRepository`

In `app/repositories/workflow_repository.py`, add after `increment_retry()` (around line 314):

```python
async def update_checkpoint(
    self, job_id: uuid.UUID, checkpoint_data: Dict[str, Any]
) -> None:
    """Persist checkpoint data without changing status/state (used before retry)."""
    stmt = (
        update(WorkflowJob)
        .where(WorkflowJob.job_id == job_id)
        .values(
            checkpoint_data=checkpoint_data,
            updated_at=datetime.utcnow(),
        )
    )
    await self.session.execute(stmt)
    await self.session.commit()
```

### Step 2: Call `update_checkpoint()` before `increment_retry()` in orchestrator

In `app/services/workflow/orchestrator.py`, around line 322-326, change:

```python
# BEFORE (line 322-326):
await repo.append_event(
    job.job_id, current_state_name, "retry",
    {"attempt": attempt, "error": step_result.error},
)
await repo.increment_retry(job.job_id)
return

# AFTER:
await repo.append_event(
    job.job_id, current_state_name, "retry",
    {"attempt": attempt, "error": step_result.error},
)
# PERSIST checkpoint BEFORE incrementing retry (resume from last success)
await repo.update_checkpoint(job.job_id, checkpoint)
await repo.increment_retry(job.job_id)
return
```

**This is the ONLY code change in the orchestrator.** The `checkpoint` dict (accumulated across steps in `_run_state_machine`) is saved to DB, then `increment_retry()` resets status to pending and releases the lock. On the next poll loop cycle, the job is re-acquired with the saved checkpoint, and `generate_pages_step` resumes from `checkpoint["pages_state"]["results"]` (the list of already-generated pages).

---

## Implementation Steps (Exact Order)

1. Open `app/repositories/workflow_repository.py`
2. After line 314 (end of `increment_retry`), add the `update_checkpoint()` method (7 lines, shown above)
3. Open `app/services/workflow/orchestrator.py`
4. Between lines 325 (`await repo.append_event(...)`) and 326 (`await repo.increment_retry(job.job_id)`), insert `await repo.update_checkpoint(job.job_id, checkpoint)`
5. Verify: `python -c "from app.repositories.workflow_repository import WorkflowRepository; assert hasattr(WorkflowRepository, 'update_checkpoint')"`

---

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | `update_checkpoint()` method exists on `WorkflowRepository` | `hasattr(WorkflowRepository, 'update_checkpoint')` |
| AC-2 | `update_checkpoint()` is called BEFORE `increment_retry()` in retry path | Source: `update_checkpoint` line appears before `increment_retry` line |
| AC-3 | On retry, `generate_pages` resumes from last successful page | Integration test: fail at page 5/10 → retry → only pages 6-10 generated |
| AC-4 | If checkpoint save fails (DB error), retry still proceeds (best-effort) | Try/except around `update_checkpoint` or let exception propagate (retry will still happen) |
| AC-5 | Successful steps still save checkpoint via `transition()` as before (no regression) | Existing tests pass |

---

## Validation

```bash
# 1. Verify update_checkpoint exists after fix
grep -n "async def update_checkpoint" app/repositories/workflow_repository.py
# Expected: 1 match

# 2. Verify call order in orchestrator
grep -A3 "retry" app/services/workflow/orchestrator.py | grep -E "update_checkpoint|increment_retry"
# Expected: update_checkpoint BEFORE increment_retry

# 3. Run tests
python tests/run_workflow_engine_tests.py
```
