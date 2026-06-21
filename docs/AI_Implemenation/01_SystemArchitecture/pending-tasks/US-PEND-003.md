# US-PEND-003: Fix `CostTracker.record_usage()` — Cost Tracking Silently Broken

| Field | Value |
|-------|-------|
| **Type** | 🐛 Bug |
| **Priority** | 🔴 CRITICAL |
| **Batch** | 1 — Do First |
| **Depends On** | US-PEND-002 (LLMClient fix — same function, adjacent lines) |
| **Estimated Effort** | 15 minutes |
| **Target File** | `app/services/workflow/steps/course_generation.py` lines 137-146 |

---

## User Story

**As a** platform administrator monitoring AI costs,
**I want** every LLM call made by the workflow engine to be recorded in the cost tracking system,
**So that** token consumption is accurately billed and budget limits are enforced.

---

## Intent of Work

The `generate_pages` step attempts to call `cost_tracker.record_usage()` after each LLM call. This method does not exist — `CostTracker` has `record()`. Additionally, the code accesses `response.usage.input_tokens` (namespace access), but `LLMResponse` stores token usage as `response.token_usage` which is a `Dict[str, int]` (dictionary access), not a namespace object.

The `hasattr(response, 'usage')` guard on line 137 silently evaluates to `False` every time, so the cost tracking block is **never entered**. All LLM costs from workflow execution are invisible to the billing system.

---

## Current State (Code Verified 2026-06-21)

```python
# app/services/workflow/steps/course_generation.py, lines 137-147 — ACTUAL CODE ON DISK

if hasattr(response, 'usage'):                          # ← Always False: LLMResponse has 'token_usage', not 'usage'
    cost_tracker.record_usage(                           # ← AttributeError: method is 'record', not 'record_usage'
        user_id=input_data.get("user_id", ""),
        model=llm_client.model,                          # ← Wrong kwarg: 'model' not in record() signature
        input_tokens=response.usage.input_tokens,        # ← Wrong access: token_usage is a dict, not namespace
        output_tokens=response.usage.output_tokens,      # ← Wrong access
        metadata={...},                                   # ← Wrong kwarg: 'metadata' not in record() signature
    )
```

**Facts confirmed against actual code on disk:**

| Claim | File:Line | Verification |
|-------|-----------|-------------|
| `record()` is `def`, NOT `async def` | `cost_tracker.py:68` | `def record(self, session_id, user_id, tenant_id, model_id, input_tokens, output_tokens, cache_read_tokens=0, cache_write_tokens=0, latency_ms=0.0) -> Dict[str, Any]` |
| `LLMResponse.token_usage` is `Dict[str, int]` | `llm_client.py:104` | `token_usage: Dict[str, int] = field(default_factory=dict)` |
| `LLMResponse` has NO attribute `usage` | `llm_client.py:99-106` | Fields: `content`, `tool_calls`, `stop_reason`, `token_usage`, `model`, `latency_ms` |
| `CostTracker` has NO method `record_usage` | `cost_tracker.py:68` | Only `record()` exists |

**The `record()` method is SYNCHRONOUS (`def`, not `async def`). Do NOT use `await`.**

---

## Expected State (Exact Code — Copy-Paste Ready)

```python
# course_generation.py, lines 137-147 — REPLACE WITH:
if hasattr(response, 'token_usage') and response.token_usage:
    cost_tracker.record(
        session_id=str(job_id),                          # Workflow job IS the session
        user_id=input_data.get("user_id", "system"),
        tenant_id=input_data.get("organization_id", ""),
        model_id=model_name,
        input_tokens=response.token_usage.get("input_tokens", 0),
        output_tokens=response.token_usage.get("output_tokens", 0),
    )
# NOTE: record() is synchronous — NO await keyword
```

**Why `session_id=str(job_id)`:** The step function receives `job_id` as a `uuid.UUID` parameter. The workflow job IS the execution context — there is no AI chat session for background workflows. Using `str(job_id)` uniquely identifies this workflow run in cost records. The `input_data` may not contain `session_id` (it comes from `SubmitWorkflowRequest.input` which is arbitrary JSON from the API caller).

---

## Implementation Steps

1. Open `app/services/workflow/steps/course_generation.py`
2. Line 137: Change `hasattr(response, 'usage')` → `hasattr(response, 'token_usage') and response.token_usage`
3. Line 138: Change `cost_tracker.record_usage(` → `cost_tracker.record(`
4. Lines 139-146: Replace ALL kwargs with the correct ones shown above
5. **DELETE the `await` keyword if present** — `record()` is `def`, not `async def`
6. Verify: `python -c "from app.services.workflow.steps.course_generation import generate_pages_step"` succeeds

---

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | `hasattr(response, 'token_usage')` evaluates to `True` when LLMResponse has token data | Unit test with mock LLMResponse |
| AC-2 | `cost_tracker.record(...)` receives all 6 required positional arguments | Check call matches `record()` signature exactly |
| AC-3 | `response.token_usage.get("input_tokens", 0)` correctly reads token count as int | Unit test |
| AC-4 | **NO `await` keyword before `cost_tracker.record()`** — method is synchronous | `grep "await cost_tracker"` in source must NOT match |
| AC-5 | No `AttributeError` for `record_usage` or `response.usage` | Existing workflow tests pass |

---

## Validation

```bash
# 1. Verify record() is synchronous
python -c "
from app.services.ai.cost_tracker import CostTracker
import inspect
assert not inspect.iscoroutinefunction(CostTracker.record), 'record() must NOT be async'
print('OK: record() is synchronous')
"

# 2. Verify token_usage is a dict
python -c "
from app.services.ai.llm_client import LLMResponse
r = LLMResponse(content='test', model='test', token_usage={'input_tokens': 10, 'output_tokens': 20}, finish_reason='stop')
assert hasattr(r, 'token_usage')
assert isinstance(r.token_usage, dict)
assert not hasattr(r, 'usage')
print('OK: token_usage is Dict[str, int], usage does not exist')
"

# 3. Run tests
python tests/run_workflow_engine_tests.py
```
