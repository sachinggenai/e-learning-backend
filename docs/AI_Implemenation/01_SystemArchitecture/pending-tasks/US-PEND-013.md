# US-PEND-013: Fix Dead `complete_export_step` — Never Invoked by Orchestrator

| Field | Value |
|-------|-------|
| **Type** | 🐛 Bug |
| **Priority** | 🟡 HIGH |
| **Batch** | 3 — Reliability Fixes |
| **Depends On** | US-PEND-005 |
| **Estimated Effort** | 20 minutes |
| **Target Files** | `app/services/workflow/orchestrator.py:246`, `app/services/workflow/steps/scorm_export.py:142-151` |

---

## User Story

**As a** developer reading the SCORM export workflow code,  
**I want** every registered step function to be reachable by the orchestrator,  
**So that** I don't waste time debugging why `complete_export_step` never executes.

---

## Intent of Work

`complete_export_step` is registered in the step registry and intended to finalize the export (set `download_url`, record completion). But the orchestrator loop exits **before** it can be called:

```python
# orchestrator.py:246
while current_state_name not in ("complete", "failed", "cancelled"):
    # execute step...
# ← Loop exits when state is "complete". The "complete" step NEVER executes.
```

Fix: Either change the loop to execute the `complete` state step before exiting, or remove the dead `complete_export_step` registration (if orchestrator handles completion automatically).

---

## Current State

```python
# orchestrator.py:246 — loop exits before "complete" state executes
while current_state_name not in ("complete", "failed", "cancelled"):
    step_fn = self._step_registry.get(job.workflow_type, current_state_name)
    ...

# scorm_export.py:142-151 — registered but dead code
@register_step("scorm_export", "complete")
async def complete_export_step(job_id, input_data, checkpoint, logger, step_config):
    """This function will never be called by the orchestrator."""
    ...
```

**Facts confirmed (2026-06-21):**
- 9 step functions registered: 4 `course_generation` + 5 `scorm_export`
- `scorm_export` has 5 states: `validate_course`, `generate_manifest`, `package_assets`, `create_zip`, `complete`
- Only `complete` state is affected — all others have transition states that re-enter the loop
- The orchestrator handles completion metadata (`completed_at`, status=`complete`) automatically after the loop exits

---

## Expected State

**Recommended:** Remove the `complete` state from the scorm_export state machine. The orchestrator handles completion automatically. The `create_zip` step should be the terminal state, and it should set the final `download_url` and metadata in its checkpoint update.

```python
# scorm_export.py — remove the dead step registration
# @register_step("scorm_export", "complete")  ← REMOVE
# async def complete_export_step(...):          ← REMOVE
#     ...

# Create_zip step should transition to "complete" state
# The orchestrator handles the rest
```

---

## Technical Details

### Implementation Steps

1. Remove `complete_export_step` function and its decorator from `scorm_export.py`
2. Update `create_zip` step to set `next_state="complete"` in its `StepResult`
3. Move any important `complete_export_step` logic (if any) into `create_zip`
4. Verify step registry count: should be 8 instead of 9
5. Update any documentation referencing 5 scorm_export states → 4 states

### Scope Boundary

- **IN SCOPE:** Remove dead step, adjust state machine
- **OUT OF SCOPE:** Changing orchestrator loop logic

---

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-1 | `complete_export_step` is removed from `scorm_export.py` |
| AC-2 | `create_zip` step sets `next_state="complete"` |
| AC-3 | Step registry shows 4 scorm_export steps (not 5) |
| AC-4 | SCORM export workflow still reaches `status="complete"` (handled by orchestrator) |

---

## Functional Expectations

- SCORM export workflow completes successfully with 4 active steps
- `create_zip` handles finalization (download URL, package metadata)
- No change to API response format for completed SCORM export jobs

## Non-Functional Expectations

- Step registry count decreases by 1 (dead code removed)
- No change to orchestrator loop behavior

---

## Validation Steps

```bash
# 1. Verify dead step removed
grep -n "complete_export_step" app/services/workflow/steps/scorm_export.py
# Should return NO matches

# 2. Verify create_zip transitions to "complete"
grep -A5 "next_state" app/services/workflow/steps/scorm_export.py | grep "complete"

# 3. Verify registry count
python -c "
from app.services.workflow.step_registry import get_default_registry
steps = get_default_registry().list_steps('scorm_export')
print(f'scorm_export steps: {len(steps)}')  # Should be 4
for name, fn in steps:
    print(f'  {name}: {fn.__name__}')
"

# 4. Run tests
python tests/run_workflow_engine_tests.py
```
