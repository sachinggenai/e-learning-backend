# US-PEND-006: Clarify Workflow Engine Feature Flag Default & Documentation

| Field | Value |
|-------|-------|
| **Type** | 🔧 Change Request |
| **Priority** | 🟢 MEDIUM |
| **Batch** | 1 — Do First |
| **Depends On** | None |
| **Estimated Effort** | 10 minutes |
| **Target Files** | `app/utils/feature_flags.py` line 77, `.env.example` line 195 |

---

## ⚠️ RE-VALIDATION NOTE (2026-06-21)

**The original version of this story claimed the engine would "NEVER start" because the feature flag defaults to `False` and `is_enabled()` doesn't check env vars. This was WRONG.** The `FeatureFlagService.__init__()` calls `_apply_environment_overrides()` (lines 112-125 of `feature_flags.py`) which:

1. Sets `flag.enabled = True` for any flag whose `environments` list matches the current `APP_ENV`
2. Checks `FEATURE_DURABLE_WORKFLOW_ENGINE` env var for explicit override

Since `durable_workflow_engine` lists ALL 4 environments (DEVELOPMENT, QA, STAGING, PRODUCTION), the flag is set to `True` at startup in any deployment. The engine WILL start. The env var IS read. **This story has been rewritten to be about documentation clarity, not a bug fix.**

---

## User Story

**As a** developer reading the feature flags configuration,  
**I want** the `enabled=False` default to not mislead me into thinking the engine is disabled,  
**So that** I understand the effective behavior (enabled in all environments) at a glance.

---

## Intent of Work

The `durable_workflow_engine` flag has `enabled=False` as its Python default (line 77), but this value is **never effective** — `_apply_environment_overrides()` immediately sets it to `True` in any deployed environment. This creates confusion: a developer reading the code sees `False`, but the engine starts anyway. The `.env.example` has the env var commented out, which is correct since it's optional, but the comment doesn't explain what the default behavior is.

Two small changes: (1) Set the Python default to `True` to match effective behavior. (2) Improve the `.env.example` comment to document the override mechanism.

---

## Current State

```python
# feature_flags.py, lines 75-80
FeatureFlag(
    name="durable_workflow_engine",
    enabled=False,              # ← MISLEADING: immediately overridden by _apply_environment_overrides()
    description="Durable workflow engine (PostgreSQL-backed)",
    environments=[DEVELOPMENT, QA, STAGING, PRODUCTION],  # ← This is what actually enables it
),
```

```python
# feature_flags.py, lines 112-125 — THE ACTUAL ENABLE MECHANISM
def _apply_environment_overrides(self):
    current_env = os.getenv("APP_ENV", "development").lower()
    for flag in self.flags.values():
        if current_env in flag.environments:   # ← durable_workflow_engine is in ALL envs
            flag.enabled = True                 # ← So it's ALWAYS enabled
        env_key = f"FEATURE_{flag.name.upper()}"
        env_val = os.getenv(env_key, "").lower()
        if env_val in ("true", "1", "yes"):
            flag.enabled = True
        elif env_val in ("false", "0", "no"):
            flag.enabled = False                # ← Explicit disable works
```

```bash
# .env.example, line 195
# FEATURE_DURABLE_WORKFLOW_ENGINE=true   # ← Commented out, no explanation of default
```

**Facts confirmed by re-validation (2026-06-21):**
- `_apply_environment_overrides()` at lines 112-125 IS the env var check
- The flag IS enabled in all environments via the `environments` list
- `FEATURE_DURABLE_WORKFLOW_ENGINE=false` in `.env` WILL disable the engine
- The `enabled=False` default is misleading but harmless (it's overridden before any check occurs)

---

## Expected State

```python
# feature_flags.py, line 77
FeatureFlag(
    name="durable_workflow_engine",
    enabled=True,               # ← Reflects effective behavior (enabled in all envs)
    description="Durable workflow engine (PostgreSQL-backed). Disable with FEATURE_DURABLE_WORKFLOW_ENGINE=false in .env",
    environments=[DEVELOPMENT, QA, STAGING, PRODUCTION],
),
```

```bash
# .env.example, line 195
# FEATURE_DURABLE_WORKFLOW_ENGINE=false   # Set to false to disable the workflow engine
# Default: enabled in all environments
```

---

## Technical Details

### Implementation Steps

1. Open `app/utils/feature_flags.py`
2. Line 77: Change `enabled=False` → `enabled=True`
3. Update the description string to document how to disable
4. Open `.env.example`
5. Line 195: Change the commented line to show `=false` as the example and add a default note
6. Verify: `python -c "from app.utils.feature_flags import is_feature_enabled; assert is_feature_enabled('durable_workflow_engine') == True"`

### Scope Boundary

- **IN SCOPE:** Change default from False to True, improve documentation
- **OUT OF SCOPE:** Changing `_apply_environment_overrides()` logic, changing other flags

---

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-1 | `enabled=True` is the Python default for `durable_workflow_engine` |
| AC-2 | `is_feature_enabled("durable_workflow_engine")` returns `True` without any env var |
| AC-3 | Setting `FEATURE_DURABLE_WORKFLOW_ENGINE=false` in `.env` still disables the engine |
| AC-4 | `.env.example` documents the default behavior and how to override |

---

## Functional Expectations

- Engine starts automatically in all environments (no change — this already worked)
- Developer reading the code sees `True` and understands the engine is on
- Ops can still disable with `FEATURE_DURABLE_WORKFLOW_ENGINE=false`

## Non-Functional Expectations

- Zero behavior change (engine was already enabled)
- `_apply_environment_overrides()` unchanged
- All other feature flags unaffected

---

## Validation Steps

```bash
# 1. Default = True
python -c "from app.utils.feature_flags import is_feature_enabled; assert is_feature_enabled('durable_workflow_engine') == True"

# 2. Env var override = False
$env:FEATURE_DURABLE_WORKFLOW_ENGINE = 'false'
python -c "from app.utils.feature_flags import FeatureFlagService; svc = FeatureFlagService(); assert svc.is_enabled('durable_workflow_engine') == False; print('OK')"
$env:FEATURE_DURABLE_WORKFLOW_ENGINE = ''

# 3. Verify source default
grep -A5 "durable_workflow_engine" app/utils/feature_flags.py | grep "enabled"
# Expected: enabled=True
```
