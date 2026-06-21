# US-PEND-007: Unify Workflow Engine Config Wiring — PRECISE CONSTRUCTOR MATCH

| Field | Value |
|-------|-------|
| **Type** | 🔧 Change Request |
| **Priority** | 🟡 HIGH |
| **Batch** | 2 — Config Fixes |
| **Depends On** | Batch 1 (US-PEND-001 through 006) |
| **Estimated Effort** | 2.5 hours (increased — constructor must be extended) |
| **Target Files** | `app/main.py:139-148`, `app/services/ai/config.py:112-120`, `app/services/workflow/orchestrator.py:56-68,377` |

---

## ⚠️ CRITICAL: Constructor Signature Verified Against Actual Code

The orchestrator constructor at `orchestrator.py:56-62` has **EXACTLY 4 PARAMETERS**:

```python
def __init__(
    self,
    worker_id: str | None = None,
    poll_interval_seconds: float = 1.0,
    heartbeat_interval_seconds: float = 5.0,
    max_concurrency: int = 4,
):
```

**There are NO params for `lock_timeout_ms`, `stale_threshold_seconds`, or `max_job_duration_seconds`.** These must be ADDED to the constructor to complete this story. Any code that passes 7 params will crash with `TypeError`.

---

## User Story

**As a** platform operator configuring the workflow engine,
**I want** to set all workflow engine parameters in `.env` and have them actually take effect,
**So that** I don't need to modify Python source code to tune polling intervals, heartbeat timings, or worker concurrency.

---

## Intent of Work

The workflow engine's configuration is read from **3 different places using 3 different patterns**:

1. **`AIConfig` fields** (8 fields in `config.py:113-120`) — loaded from env vars, but only 1 of 8 is consumed
2. **Direct `os.getenv()`** in `main.py:140-141` and `orchestrator.py:377` — bypasses config system
3. **Constructor defaults** — `poll_interval_seconds` and `heartbeat_interval_seconds` hardcoded at 1.0 and 5.0

Result: `WORKFLOW_POLL_INTERVAL`, `WORKFLOW_HEARTBEAT_INTERVAL`, `WORKFLOW_STALE_THRESHOLD` env vars are **silently ignored**.

---

## Current State

```python
# main.py:139-142 — reads env vars directly, bypassing AIConfig
# ai_cfg is IN SCOPE (loaded at line 125) but NOT USED here
orchestrator = WorkflowOrchestrator(
    worker_id=os.getenv("WORKFLOW_WORKER_ID"),   # None → auto-gen
    max_concurrency=int(os.getenv("WORKFLOW_MAX_CONCURRENCY", "4")),
    # NOTE: poll_interval_seconds and heartbeat_interval_seconds NOT passed — use hardcoded defaults
)

# orchestrator.py:377 — reads env directly, bypassing AIConfig
stale_threshold = int(os.getenv("WORKFLOW_STALE_THRESHOLD", "30"))

# config.py:317-324 — all 8 fields loaded from env, but only 2 are consumed
workflow_worker_id=os.getenv("WORKFLOW_WORKER_ID", "worker-1"),
workflow_max_concurrency=_env_int("WORKFLOW_MAX_CONCURRENCY", 4),
workflow_poll_interval=float(os.getenv("WORKFLOW_POLL_INTERVAL", "1.0")),    # DEAD — never consumed
workflow_heartbeat_interval=float(os.getenv("WORKFLOW_HEARTBEAT_INTERVAL", "5.0")),  # DEAD — never consumed
workflow_lock_timeout_ms=_env_int("WORKFLOW_LOCK_TIMEOUT_MS", 5000),          # DEAD — never consumed
workflow_stale_threshold=_env_int("WORKFLOW_STALE_THRESHOLD", 30),            # DEAD — orchestrator gets from os.getenv
workflow_max_duration_seconds=_env_int("WORKFLOW_MAX_DURATION_SECONDS", 86400), # DEAD — never consumed
workflow_enabled=_env_bool("WORKFLOW_ENABLED", True),                         # DEAD — feature flag handles this
```

---

## Expected State

**Phase 1: Extend orchestrator constructor** (add 3 params to `orchestrator.py:56-62`):

```python
def __init__(
    self,
    worker_id: str | None = None,
    poll_interval_seconds: float = 1.0,
    heartbeat_interval_seconds: float = 5.0,
    max_concurrency: int = 4,
    stale_threshold_seconds: int = 30,       # ← NEW — was hardcoded in _recover_stale_jobs
):
    self.worker_id = worker_id or os.getenv(
        "WORKFLOW_WORKER_ID", f"worker-{_get_hostname()}"
    )
    self.poll_interval = poll_interval_seconds
    self.heartbeat_interval = heartbeat_interval_seconds
    self.max_concurrency = max_concurrency
    self.stale_threshold_seconds = stale_threshold_seconds  # ← NEW
    # ... rest unchanged
```

**Phase 2: Fix `_recover_stale_jobs()` to use `self.stale_threshold_seconds`** (`orchestrator.py:377`):

```python
# Before:
stale_threshold = int(os.getenv("WORKFLOW_STALE_THRESHOLD", "30"))

# After:
stale_threshold = self.stale_threshold_seconds
```

**Phase 3: Fix `main.py:139-142` to use `ai_cfg`** (which is in scope at line 125):

```python
orchestrator = WorkflowOrchestrator(
    worker_id=ai_cfg.workflow_worker_id,
    poll_interval_seconds=ai_cfg.workflow_poll_interval,
    heartbeat_interval_seconds=ai_cfg.workflow_heartbeat_interval,
    max_concurrency=ai_cfg.workflow_max_concurrency,
    stale_threshold_seconds=ai_cfg.workflow_stale_threshold,
)
```

**Phase 4: Cleanup `config.py`** — remove dead field `workflow_enabled` and `workflow_lock_timeout_ms`/`workflow_max_duration_seconds` if not used elsewhere:

```python
# REMOVE this line (feature flag handles enable/disable):
workflow_enabled: bool = True

# REMOVE from load_ai_config():
workflow_enabled=_env_bool("WORKFLOW_ENABLED", True),
```

---

## Implementation Steps (Exact Order)

1. **`orchestrator.py:56-62`**: Add `stale_threshold_seconds: int = 30` to `__init__`. Store as `self.stale_threshold_seconds`.
2. **`orchestrator.py:377`**: Replace `int(os.getenv("WORKFLOW_STALE_THRESHOLD", "30"))` with `self.stale_threshold_seconds`.
3. **`main.py:139-142`**: Replace `os.getenv(...)` calls with `ai_cfg.workflow_*` attributes.
4. **`config.py`**: Remove `workflow_enabled` field and its env-var loading line.
5. **`.env.example`**: Uncomment and document: `WORKFLOW_POLL_INTERVAL`, `WORKFLOW_HEARTBEAT_INTERVAL`, `WORKFLOW_STALE_THRESHOLD`.

---

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | All orchestrator config comes from `AIConfig` | `grep -n "os.getenv.*WORKFLOW" app/main.py` → 0 matches for orchestrator block |
| AC-2 | `orchestrator.py` has zero direct `os.getenv()` for workflow config | Only `__init__` defaults remain (not from env) |
| AC-3 | Changing `WORKFLOW_POLL_INTERVAL=2.0` in `.env` changes actual poll interval | Set env → restart → check logs |
| AC-4 | `config.py` has no unconsumed workflow fields | Every `workflow_*` field is passed to orchestrator constructor or used elsewhere |
| AC-5 | Orchestrator constructor has exactly 5 params after change (added `stale_threshold_seconds`) | `len(inspect.signature(WorkflowOrchestrator.__init__).parameters)` == 6 (incl self) |

---

## Validation

```bash
# 1. Verify constructor signature after fix
python -c "
from app.services.workflow.orchestrator import WorkflowOrchestrator
import inspect
sig = inspect.signature(WorkflowOrchestrator.__init__)
params = list(sig.parameters.keys())
print('Params:', params)
assert 'stale_threshold_seconds' in params, 'Must have stale_threshold_seconds'
assert 'poll_interval_seconds' in params
assert 'heartbeat_interval_seconds' in params
assert 'max_concurrency' in params
assert 'worker_id' in params
print('OK: Constructor has correct 5 params (+ self)')
"

# 2. Verify no raw os.getenv in orchestrator config path
grep -n "os.getenv.*WORKFLOW" app/services/workflow/orchestrator.py
# Expected: 0 matches (or only __init__ defaults)

# 3. Run tests
python tests/run_workflow_engine_tests.py
```
