# US-PEND-002: Fix `LLMClient.generate()` → `chat()` + Missing Import — CODE-VERIFIED

| Field | Value |
|-------|-------|
| **Type** | 🐛 Bug |
| **Priority** | 🔴 CRITICAL |
| **Batch** | 1 — Do First |
| **Depends On** | None |
| **Estimated Effort** | 20 minutes |
| **Target File** | `app/services/workflow/steps/course_generation.py` lines 99, 118-134 |

---

## User Story

**As a** course author using AI generation,
**I want** the workflow engine to call the LLM correctly when generating course pages,
**So that** my course generation jobs produce actual content instead of crashing with `AttributeError` or `NameError`.

---

## Intent of Work

**Three bugs in 5 lines of code:**

| Bug | Line | Current Code | Problem |
|-----|------|-------------|---------|
| 1 | 99 | `from app.services.ai.llm_client import LLMClient` | `LLMMessage` is **NOT imported** — will cause `NameError` |
| 2 | 118 | `LLMClient(model=model_name, temperature=temperature, max_tokens=max_tokens)` | `temperature`/`max_tokens` are not `__init__` params |
| 3 | 134 | `await llm_client.generate(prompt)` | `generate()` does not exist — method is `chat()` |

---

## Current State (Code Verified 2026-06-21)

```python
# Line 99 — ACTUAL IMPORT ON DISK (LLMMessage MISSING)
from app.services.ai.llm_client import LLMClient

# Lines 118-134 — ACTUAL CODE ON DISK
llm_client = LLMClient(model=model_name, temperature=temperature, max_tokens=max_tokens)
# ...
response = await llm_client.generate(prompt)
```

**Facts confirmed against actual code:**

| Claim | File:Line | Verification |
|-------|-----------|-------------|
| `LLMClient.__init__` has 5 params | `llm_client.py:147-153` | `__init__(self, provider, model, api_key, max_retries, timeout)` — NO `temperature`, NO `max_tokens` |
| `LLMClient.chat()` accepts `temperature`/`max_tokens` | `llm_client.py:165-172` | `chat(self, messages, tools, system_prompt, max_tokens=4096, temperature=0.7)` |
| `LLMClient` has NO `generate()` | Full class grep | Only `chat()` and `chat_stream()` exist |
| `LLMMessage` is a dataclass | `llm_client.py:56-61` | `LLMMessage(role: str, content: Optional[str]=None, tool_calls=[], tool_results=[])` |
| Import on line 99 is incomplete | `course_generation.py:99` | Only `LLMClient` — `LLMMessage` missing |

---

## Expected State (Exact Code — Copy-Paste Ready)

```python
# Line 99 — FIX: ADD LLMMessage to import
from app.services.ai.llm_client import LLMClient, LLMMessage

# Lines 118-121 — FIX: Remove temperature/max_tokens from constructor
llm_client = LLMClient(model=model_name)

# ... inside the for loop (around line 133-134) ...
# FIX: Replace generate() with chat(), wrap prompt in LLMMessage
response = await llm_client.chat(
    messages=[LLMMessage(role="user", content=prompt)],
    temperature=temperature,
    max_tokens=max_tokens,
)
```

---

## Implementation Steps

1. Open `app/services/workflow/steps/course_generation.py`
2. **Line 99**: Add `LLMMessage` to the existing import:
   ```python
   from app.services.ai.llm_client import LLMClient, LLMMessage
   ```
3. **Lines 118-121**: Remove `temperature=temperature, max_tokens=max_tokens` from `LLMClient(...)` call
4. **Lines 133-134**: Replace:
   ```python
   response = await llm_client.generate(prompt)
   ```
   With:
   ```python
   response = await llm_client.chat(
       messages=[LLMMessage(role="user", content=prompt)],
       temperature=temperature,
       max_tokens=max_tokens,
   )
   ```
5. Verify: `python -c "from app.services.workflow.steps.course_generation import generate_pages_step"` succeeds

---

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | `LLMMessage` is imported on line 99 | `grep "LLMMessage" course_generation.py` matches import line |
| AC-2 | `LLMClient(model=model_name)` constructor call succeeds | No `TypeError` for unexpected kwarg |
| AC-3 | `llm_client.chat(messages=[...], temperature=..., max_tokens=...)` returns `LLMResponse` | Integration test |
| AC-4 | No `AttributeError` for `generate()` | Static check: `grep "\.generate(" course_generation.py` returns 0 matches |

---

## Validation

```bash
# 1. Verify import includes LLMMessage
grep "from app.services.ai.llm_client import" app/services/workflow/steps/course_generation.py
# Expected: from app.services.ai.llm_client import LLMClient, LLMMessage

# 2. Verify generate() is gone
grep "\.generate(" app/services/workflow/steps/course_generation.py
# Expected: 0 matches

# 3. Verify chat() is used
grep "\.chat(" app/services/workflow/steps/course_generation.py
# Expected: 1 match (the fixed call)

# 4. Verify constructor has no temperature/max_tokens
python -c "
from app.services.workflow.steps.course_generation import generate_pages_step
import inspect
source = inspect.getsource(generate_pages_step)
assert 'LLMClient(model=model_name)' in source or 'LLMClient(model=' in source
assert 'temperature=temperature' not in source.split('LLMClient(')[1].split(')')[0]
print('OK')
"

# 5. Run tests
python tests/run_workflow_engine_tests.py
```
