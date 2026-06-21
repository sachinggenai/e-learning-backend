# US-PEND-005: Fix `CourseRepository.get_by_id()` + Exception Handling in SCORM Export Step

| Field | Value |
|-------|-------|
| **Type** | 🐛 Bug |
| **Priority** | 🔴 CRITICAL |
| **Batch** | 1 — Do First |
| **Depends On** | None |
| **Estimated Effort** | 10 minutes (was 5 min — increased due to exception handling) |
| **Target File** | `app/services/workflow/steps/scorm_export.py` lines 42-48 |

---

## User Story

**As a** course author exporting a course to SCORM,
**I want** the SCORM export workflow to fetch my course data correctly and handle missing courses gracefully,
**So that** the SCORM package contains actual course content instead of crashing with unhandled exceptions.

---

## Intent of Work

**Two bugs, not one.** The original story only identified the method name bug. The enriched review found a second bug: exception handling.

### Bug 1: Wrong method name (original)
`repo.get_by_id(course_id)` — `CourseRepository` has no `get_by_id()` method. The correct method is `get_by_course_id(course_id)`.

### Bug 2: Silent exception propagation (discovered 2026-06-21)
`get_by_course_id()` **RAISES `CourseNotFoundError`** when the course doesn't exist. It does NOT return `None`. The current code at line 43 checks `if not course:` which is **dead code** — the exception would have already propagated. After fixing Bug 1, the `if not course` check still won't execute because the exception fires first. Must add `try/except CourseNotFoundError`.

---

## Current State (Code Verified 2026-06-21)

```python
# scorm_export.py, lines 42-48 — ACTUAL CODE ON DISK
course = await repo.get_by_id(course_id)  # ← Bug 1: AttributeError (no method 'get_by_id')
if not course:                             # ← Bug 2: DEAD CODE (get_by_course_id RAISES, doesn't return None)
    return StepResult(
        success=False,
        error={"code": "COURSE_NOT_FOUND",
               "message": f"No course with id {course_id}"},
    )
```

**Facts confirmed against actual code on disk:**

| Claim | File:Line | Verification |
|-------|-----------|-------------|
| `CourseRepository` has `get(pk: int)` | `course_repo.py:58` | Returns CourseRecord or raises `CourseNotFoundError` |
| `CourseRepository` has `get_by_course_id(course_id: str)` | `course_repo.py:67-74` | `result.scalar_one_or_none()` → if None: `raise CourseNotFoundError` |
| `CourseRepository` has NO `get_by_id` | Full file grep | No method named `get_by_id` exists |
| `CourseNotFoundError` is defined | `course_repo.py:15` | `class CourseNotFoundError(Exception)` |

---

## Expected State (Exact Code — Copy-Paste Ready)

```python
# scorm_export.py, lines 37-48 — REPLACE WITH:
from app.db.config import SessionLocal
from app.repositories.course_repo import CourseRepository, CourseNotFoundError  # ← ADD CourseNotFoundError

async with SessionLocal() as session:
    repo = CourseRepository(session)
    try:
        course = await repo.get_by_course_id(course_id)  # ← FIXED method name
    except CourseNotFoundError:                           # ← ADDED exception handler
        return StepResult(
            success=False,
            error={"code": "COURSE_NOT_FOUND",
                   "message": f"No course with id {course_id}"},
        )

    checkpoint["course"] = {
        "course_id": course_id,
        "title": getattr(course, "title", "Untitled"),
        "page_count": getattr(course, "page_count", 0),
    }
```

---

## Implementation Steps

1. Open `app/services/workflow/steps/scorm_export.py`
2. Line 38: Add `CourseNotFoundError` to the import from `app.repositories.course_repo`:
   ```python
   from app.repositories.course_repo import CourseRepository, CourseNotFoundError
   ```
3. Line 42: Change `repo.get_by_id(course_id)` → `repo.get_by_course_id(course_id)`
4. Lines 42-48: Wrap `repo.get_by_course_id()` in `try/except CourseNotFoundError`
5. Remove the dead `if not course:` check — it will never be reached
6. Verify: `python -c "from app.services.workflow.steps.scorm_export import validate_course_step"` succeeds

---

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | `await repo.get_by_course_id(course_id)` returns course record | Integration test with existing course ID |
| AC-2 | Non-existent course returns `StepResult(success=False, error.code="COURSE_NOT_FOUND")` | Integration test with fake course ID |
| AC-3 | No `AttributeError: 'CourseRepository' object has no attribute 'get_by_id'` | Static check: `grep "get_by_id" scorm_export.py` returns 0 matches |
| AC-4 | No unhandled `CourseNotFoundError` propagating to orchestrator | Test: call step with invalid course_id → step returns error, doesn't raise |

---

## Validation

```bash
# 1. Verify get_by_course_id raises, doesn't return None
python -c "
from app.repositories.course_repo import CourseRepository, CourseNotFoundError
import inspect
sig = inspect.signature(CourseRepository.get_by_course_id)
print(f'Signature: get_by_course_id{sig}')
# Check for raise in source
import inspect as ins
src = ins.getsource(CourseRepository.get_by_course_id)
assert 'raise CourseNotFoundError' in src
print('OK: raises CourseNotFoundError on miss')
"

# 2. Verify source has try/except
python -c "
from app.services.workflow.steps.scorm_export import validate_course_step
import inspect
source = inspect.getsource(validate_course_step)
assert 'get_by_course_id' in source
assert 'get_by_id' not in source
assert 'CourseNotFoundError' in source
assert 'try:' in source and 'except CourseNotFoundError:' in source
print('OK: Correct method + exception handling')
"

# 3. Run tests
python tests/run_workflow_engine_tests.py
```
