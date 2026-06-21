# US-PEND-004: Fix `create_batch_proposal()` Missing Method

| Field | Value |
|-------|-------|
| **Type** | 🐛 Bug |
| **Priority** | 🔴 CRITICAL |
| **Batch** | 1 — Do First |
| **Depends On** | US-PEND-001, US-PEND-002, US-PEND-003 (same file, later step) |
| **Estimated Effort** | 30 minutes |
| **Target Files** | `app/services/workflow/steps/course_generation.py` line 276, possibly `app/services/ai/proposal_service.py` |

---

## User Story

**As a** course author using AI generation,  
**I want** generated course pages to be converted into proposals automatically,  
**So that** I can review and apply AI-generated content through the existing proposal workflow.

---

## Intent of Work

The `create_batch_proposal` step calls `svc.create_batch_proposal(...)` — but `AIProposalService` has no such method. It has `create_proposal(session_id, user_id, organization_id, course_id, operation, resource_type, data)` which creates **one proposal at a time**. The step function needs to either (a) loop over pages and call `create_proposal()` individually, or (b) have a new `create_batch_proposal()` method added to `AIProposalService`.

Option (a) is recommended — it requires zero changes to existing services and follows the existing API contract.

---

## Current State

```python
# app/services/workflow/steps/course_generation.py, line 276

batch = await svc.create_batch_proposal(
    course_id=course_id,
    pages=pages,
    session_id=session_id,
    user_id=user_id,
)
```

**Facts confirmed (2026-06-21):**
- `AIProposalService` exists at `app/services/ai/proposal_service.py`
- `AIProposalService` has: `create_proposal()`, `apply_proposal()`, `cancel_proposal()`, `delete_proposal()`, `get_proposal()`, `list_proposals()`
- `AIProposalService` has NO method named `create_batch_proposal`
- `create_proposal` signature: `(self, session_id: str, user_id: str, organization_id: str, course_id: str, operation: str, resource_type: str, data: dict) -> Proposal`
- `operation` is one of: `"create"`, `"update"`, `"delete"`
- `resource_type` is one of: `"page"`, `"block"`, `"course_settings"`

---

## Expected State (Option A — Loop, recommended)

```python
proposals = []
for page in pages:
    proposal = await svc.create_proposal(
        session_id=session_id,
        user_id=user_id,
        organization_id=input_data.get("organization_id", ""),
        course_id=course_id,
        operation="create_page",            # ← MUST be "create_page", NOT "create"
        resource_type="page",
        data=page,
    )
    proposals.append(proposal)

batch = {"proposals": proposals, "count": len(proposals)}
```

**🔍 RE-VALIDATED:** The `_execute()` method in `AIProposalService` (line ~851) checks `if operation == "create_page"`, NOT `"create"`. Using `"create"` would create proposals that can never be applied.

---

## Technical Details

### 🔍 RE-VALIDATED Analysis (2026-06-21)

`create_proposal` actual signature:** `async def create_proposal(self, session_id: str, user_id: str, organization_id: str, course_id: str, operation: str, resource_type: str, data: Dict[str, Any], resource_id: Optional[str] = None) -> Dict[str, Any]`

**Valid operations from `_execute()`:** `"create_page"`, `"update_page"`, `"delete_page"`

### Implementation Steps (Option A)

1. Open `app/services/workflow/steps/course_generation.py`
2. Replace lines 274-278 (the `create_batch_proposal` call) with a loop calling `svc.create_proposal()` for each page
3. `organization_id` can be sourced from `input_data.get("organization_id", "")` (same pattern as cost tracking fix)
4. Set `operation="create"` (generated pages are always new)
5. Set `resource_type="page"` (generated content is page-level)
6. Wrap each page dict as the `data` parameter
7. Collect results into a list, return as checkpoint data

### Scope Boundary

- **IN SCOPE:** Replace single `create_batch_proposal` call with loop of `create_proposal` calls
- **OUT OF SCOPE:** Adding `create_batch_proposal` method to `AIProposalService` (can be done later if batching is needed for performance), changing proposal data format

---

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-1 | Each generated page results in one `create_proposal()` call |
| AC-2 | `operation="create"` and `resource_type="page"` are correctly set |
| AC-3 | `organization_id` is sourced from `input_data` (not hardcoded) |
| AC-4 | Result checkpoint contains list of created proposals with their IDs |
| AC-5 | Step succeeds if all proposals are created; fails with partial list if any fail |

---

## Functional Expectations

- Generated course pages become actual `Proposal` records in the AI system
- Proposals appear in the user's proposal list (`GET /api/v1/proposals`)
- Proposals can be reviewed and applied through existing UI flow
- If one page fails to create a proposal, remaining pages are still attempted (best-effort)

## Non-Functional Expectations

- Zero changes to `AIProposalService` (no regression risk for existing proposal endpoints)
- Each `create_proposal` call is a separate DB transaction (existing behavior)
- Total time: N sequential DB inserts for N pages (acceptable for ~10-50 pages per course)

---

## Validation Steps

```bash
# 1. Verify create_proposal signature
python -c "
from app.services.ai.proposal_service import AIProposalService
import inspect
sig = inspect.signature(AIProposalService.create_proposal)
params = list(sig.parameters.keys())
assert 'session_id' in params
assert 'course_id' in params
assert 'operation' in params
assert 'resource_type' in params
assert 'data' in params
print('OK')
"

# 2. Verify source uses create_proposal not create_batch_proposal
python -c "
from app.services.workflow.steps.course_generation import create_batch_proposal as step_fn
import inspect
source = inspect.getsource(step_fn)
assert 'create_proposal' in source
assert 'create_batch_proposal' not in source
print('OK')
"

# 3. Run tests
python tests/run_workflow_engine_tests.py
```

---

## Unit Tests

```python
def test_create_batch_proposal_uses_loop_of_create_proposal():
    """Verify step loops over pages calling create_proposal individually"""
    from app.services.workflow.steps.course_generation import create_batch_proposal as step_fn
    import inspect
    source = inspect.getsource(step_fn)
    assert 'create_proposal' in source
    assert 'create_batch_proposal' not in source
    # Should have a loop
    assert 'for' in source and 'pages' in source
    assert 'operation' in source and 'create' in source
    assert 'resource_type' in source and 'page' in source
```
