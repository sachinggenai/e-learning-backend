"""Standalone tests for Batch 3 reliability fixes — PEND-011 through PEND-013.

Run: PYTHONPATH=. python tests/run_batch3_reliability_tests.py

Validates:
    PEND-011: update_checkpoint() exists + called before increment_retry()
    PEND-012: SCORM export finally block + StorageService usage
    PEND-013: Step count 8 (was 9), complete step removed
"""
from __future__ import annotations
import asyncio
import inspect
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

passed = 0
failed = 0
failures: list[tuple[str, str]] = []

def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        failures.append((name, detail))

# ═══════════════════════════════════════════════════════════════════
# PEND-011: Checkpoint persistence on retry
# ═══════════════════════════════════════════════════════════════════

def test_pend011_update_checkpoint_exists():
    """PEND011-01: WorkflowRepository has update_checkpoint() method."""
    from app.repositories.workflow_repository import WorkflowRepository
    check("PEND011-01: update_checkpoint exists", hasattr(WorkflowRepository, 'update_checkpoint'))

def test_pend011_update_checkpoint_called_before_increment_retry():
    """PEND011-02: update_checkpoint() called before increment_retry() in orchestrator."""
    from app.services.workflow.orchestrator import WorkflowOrchestrator
    source = inspect.getsource(WorkflowOrchestrator._run_state_machine)
    update_pos = source.find("update_checkpoint")
    retry_pos = source.find("increment_retry")
    check("PEND011-02: update_checkpoint before increment_retry",
          update_pos > 0 and retry_pos > update_pos,
          f"update_checkpoint at {update_pos}, increment_retry at {retry_pos}")

def test_pend011_increment_retry_no_checkpoint_param():
    """PEND011-03: increment_retry() does NOT accept checkpoint_data (separate call needed)."""
    from app.repositories.workflow_repository import WorkflowRepository
    sig = inspect.signature(WorkflowRepository.increment_retry)
    params = list(sig.parameters.keys())
    check("PEND011-03: increment_retry has no checkpoint_data param", "checkpoint_data" not in params)

# ═══════════════════════════════════════════════════════════════════
# PEND-012: SCORM export tempfile leak + download URL
# ═══════════════════════════════════════════════════════════════════

def test_pend012_imports_shutil():
    """PEND012-01: scorm_export.py imports shutil."""
    from app.services.workflow.steps.scorm_export import create_zip_step
    source = inspect.getsource(inspect.getmodule(create_zip_step))
    check("PEND012-01: Imports shutil", "import shutil" in source)

def test_pend012_has_finally_block():
    """PEND012-02: create_zip_step has finally block."""
    from app.services.workflow.steps.scorm_export import create_zip_step
    source = inspect.getsource(create_zip_step)
    check("PEND012-02: Has try:", "try:" in source)
    check("PEND012-02: Has finally:", "finally:" in source)

def test_pend012_calls_rmtree():
    """PEND012-03: shutil.rmtree called in finally."""
    from app.services.workflow.steps.scorm_export import create_zip_step
    source = inspect.getsource(create_zip_step)
    check("PEND012-03: shutil.rmtree in source", "rmtree" in source)
    check("PEND012-03: ignore_errors=True", "ignore_errors=True" in source)

def test_pend012_uses_storage_service():
    """PEND012-04: Uses StorageService, not file:// URL."""
    from app.services.workflow.steps.scorm_export import create_zip_step
    source = inspect.getsource(create_zip_step)
    check("PEND012-04: Uses StorageService", "StorageService" in source)
    check("PEND012-04: No file:// URL", "file://" not in source)

def test_pend012_storage_service_exists():
    """PEND012-05: StorageService class exists."""
    from app.services.storage import StorageService
    check("PEND012-05: save_scorm_package exists", hasattr(StorageService, 'save_scorm_package'))

# ═══════════════════════════════════════════════════════════════════
# PEND-013: Dead complete_export_step removed
# ═══════════════════════════════════════════════════════════════════

def test_pend013_step_count_is_8():
    """PEND013-01: 8 steps registered (was 9, complete removed)."""
    import app.services.workflow  # noqa: F401
    from app.services.workflow.step_registry import get_default_registry
    r = get_default_registry()
    count = len(r.registered_steps)
    check("PEND013-01: 8 steps total", count == 8, f"Got {count}")

def test_pend013_no_complete_step():
    """PEND013-02: No 'complete' step registered for scorm_export."""
    import app.services.workflow  # noqa: F401
    from app.services.workflow.step_registry import get_default_registry
    r = get_default_registry()
    steps = r.registered_steps
    check("PEND013-02: No scorm_export.complete", ("scorm_export", "complete") not in steps)

def test_pend013_all_scorm_steps_present():
    """PEND013-03: 4 scorm_export steps (validate_course, generate_manifest, package_assets, create_zip)."""
    import app.services.workflow  # noqa: F401
    from app.services.workflow.step_registry import get_default_registry
    r = get_default_registry()
    steps = r.registered_steps
    expected = [
        ("scorm_export", "validate_course"),
        ("scorm_export", "generate_manifest"),
        ("scorm_export", "package_assets"),
        ("scorm_export", "create_zip"),
    ]
    for key in expected:
        check(f"PEND013-03: {key[0]}.{key[1]} registered", key in steps)

# ═══════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════

async def run_all_tests():
    test_pend011_update_checkpoint_exists()
    test_pend011_update_checkpoint_called_before_increment_retry()
    test_pend011_increment_retry_no_checkpoint_param()
    test_pend012_imports_shutil()
    test_pend012_has_finally_block()
    test_pend012_calls_rmtree()
    test_pend012_uses_storage_service()
    test_pend012_storage_service_exists()
    test_pend013_step_count_is_8()
    test_pend013_no_complete_step()
    test_pend013_all_scorm_steps_present()
    print(f"\n{'='*60}")
    print(f"RESULTS: {passed} passed, {failed} failed")
    print(f"{'='*60}")
    if failures:
        for name, detail in failures:
            print(f"  FAIL: {name}")
            if detail:
                print(f"        {detail}")

if __name__ == "__main__":
    asyncio.run(run_all_tests())
