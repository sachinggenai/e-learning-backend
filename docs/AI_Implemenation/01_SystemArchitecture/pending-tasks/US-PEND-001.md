# US-PEND-001: Fix `ValidationEngine` ImportError in Workflow Step

| Field | Value |
|-------|-------|
| **Type** | 🐛 Bug |
| **Priority** | 🔴 CRITICAL |
| **Batch** | 1 — Do First |
| **Depends On** | None |
| **Estimated Effort** | 15 minutes |
| **Target File** | `app/services/workflow/steps/course_generation.py` line 228 |

---

## User Story

**As a** platform operator deploying the workflow engine,  
**I want** the `course_generation` workflow to import successfully at startup,  
**So that** the workflow engine can accept and execute course generation jobs.

---

## Intent of Work

Fix an incorrect class import that prevents the entire workflow package from loading. The import `from app.services.ai.validation_engine import ValidationEngine` references a class that does not exist. The actual class in that module is `TemplateValidationEngine`. This import error cascades: `steps/course_generation.py` → `steps/__init__.py` → `workflow/__init__.py` → `app/main.py`, so the entire workflow subsystem is unavailable.

---

## Current State

```python
# app/services/workflow/steps/course_generation.py, line 228
from app.services.ai.validation_engine import ValidationEngine  # ← DOES NOT EXIST

engine = ValidationEngine()
valid, issues = await engine.validate_course_structure(course_structure)  # ← METHOD DOES NOT EXIST
```

**Facts confirmed by code review (2026-06-21):**
- `app/services/ai/validation_engine.py` exists and contains class `TemplateValidationEngine`
- `TemplateValidationEngine` has method `validate(template_data: dict) -> Tuple[bool, List[str]]`
- No class named `ValidationEngine` exists anywhere in the codebase
- No method named `validate_course_structure()` exists on any class
- This import runs at module load time (top-level import), so the error occurs during `import app.services.workflow`, before any job is submitted

---

## Expected State

```python
from app.services.ai.validation_engine import TemplateValidationEngine
from app.services.ai.template_contracts import AITemplateContractsService

contracts = AITemplateContractsService()
engine = TemplateValidationEngine(contracts_service=contracts)
result = await engine.validate(
    template_type="course_structure",  # ← REQUIRED first positional arg
    data=course_structure,             # ← the dict we want to validate
    scope="full",
)
# result.valid: bool  — True if valid
# result.issues: List[str] — list of validation errors
```

The workflow package imports successfully. `POST /api/v1/workflows` with `workflow_type=course_generation` proceeds past the `validate_course` step without `ImportError` or `AttributeError`.

---

## Technical Details

### 🔍 RE-VALIDATED Analysis (2026-06-21)

The module `app/services/ai/validation_engine.py` was inspected. It contains:

```
class TemplateValidationEngine:
    def __init__(self, contracts_service: AITemplateContractsService): ...
    async def validate(self, template_type: str, data: Dict[str, Any],
                       scope: Literal["schema_only","business_rules","full"] = "full") -> ValidationResult: ...
```

**Key corrections from re-validation:**
- `__init__` takes `contracts_service`, NOT `strict_mode`
- `validate()` takes `(template_type: str, data: dict)` — TWO required positional args, not one
- Return type is `ValidationResult` (Pydantic model with `.valid: bool` and `.issues: List[str]`), NOT `Tuple[bool, List[str]]`
- `ValidationResult` is imported from `app.services.ai.validation_engine`
- NOTE: `validate_course_structure()` DOES exist on `CourseValidator` at `app/services/validation/course_validator.py:49` — but that's a different class. The step function currently imports from `validation_engine` which has `TemplateValidationEngine`.

### Implementation Steps

1. Open `app/services/workflow/steps/course_generation.py`
2. Change line 209 (import): `from app.services.ai.validation_engine import ValidationEngine` → `from app.services.ai.validation_engine import TemplateValidationEngine, ValidationResult`
3. Add import: `from app.services.ai.template_contracts import AITemplateContractsService`
4. Change line 227-229: Replace `engine = ValidationEngine()` with `engine = TemplateValidationEngine(contracts_service=AITemplateContractsService())`
5. Change line 230: Replace `valid, issues = await engine.validate_course_structure(course_structure)` with the `validate(template_type="course_structure", data=course_structure)` call shown above
6. Update downstream code to use `result.valid` and `result.issues` instead of tuple unpacking
7. Verify: `python -c "from app.services.workflow.steps.course_generation import validate_course"` succeeds silently

### Scope Boundary

- **IN SCOPE:** Fix the import, class name, and method call in `course_generation.py`
- **OUT OF SCOPE:** Changing `TemplateValidationEngine.validate()` behavior, schema changes, other files

---

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-1 | `from app.services.workflow.steps.course_generation import validate_course` executes without error |
| AC-2 | `from app.services.workflow import *` (the package `__init__.py`) executes without error |
| AC-3 | `from app.main import app` succeeds and includes workflow routes |
| AC-4 | Call to `TemplateValidationEngine.validate()` receives correct dict and returns `Tuple[bool, List[str]]` |

---

## Functional Expectations

- Step `validate_course` in `course_generation` workflow validates generated course structure using existing `TemplateValidationEngine`
- Validation failures are reported as `StepResult` with `success=False` and issues list
- No change to existing `TemplateValidationEngine` behavior for non-workflow callers

## Non-Functional Expectations

- Zero changes to `TemplateValidationEngine` or `validation_engine.py` (regression risk)
- Import time unchanged (same single-class import)
- No new dependencies

---

## Validation Steps

```bash
# 1. Verify import succeeds
python -c "from app.services.workflow.steps.course_generation import validate_course"

# 2. Verify package import succeeds
python -c "from app.services.workflow import *"

# 3. Verify app starts with workflow routes
python -c "from app.main import app; print([r.path for r in app.routes if 'workflow' in r.path])"
# Expected: 6+ workflow routes printed

# 4. Run existing test suite
python tests/run_workflow_engine_tests.py
# Expected: 146 passed, 0 failed
```

---

## Unit Tests

No new test file needed. The existing `tests/run_workflow_engine_tests.py` Category E tests (`test_step_functions_registered_for_course_generation`) will catch import regressions.

Optionally add to `tests/run_workflow_engine_tests.py`:
```python
def test_validate_course_step_calls_template_validator():
    """Verify validate_course uses TemplateValidationEngine.validate()"""
    from app.services.workflow.steps.course_generation import validate_course
    from app.services.ai.validation_engine import TemplateValidationEngine
    import inspect
    source = inspect.getsource(validate_course)
    assert "TemplateValidationEngine" in source
    assert ".validate(" in source
    assert "ValidationEngine" not in source  # old name must be gone
```
