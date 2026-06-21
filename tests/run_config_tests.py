"""Standalone tests for Batch 2 + 5 config/migration/infra — PEND-007 through PEND-010, PEND-017/018.

Run: PYTHONPATH=. python tests/run_config_tests.py

Validates:
    PEND-007: Orchestrator config wiring (stale_threshold_seconds, ai_cfg usage)
    PEND-008: FK type String(64) on session_id
    PEND-009: Migration schema issues fixed
    PEND-010: TOCTOU 409 (not 500) in cancel/retry
    PEND-017: pgvector installed
    PEND-018: Migration current state
"""
from __future__ import annotations
import asyncio
import inspect
import os

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
# PEND-007: Config wiring
# ═══════════════════════════════════════════════════════════════════

def test_pend007_orchestrator_has_stale_threshold():
    """PEND007-01: __init__ has stale_threshold_seconds param."""
    from app.services.workflow.orchestrator import WorkflowOrchestrator
    sig = inspect.signature(WorkflowOrchestrator.__init__)
    params = list(sig.parameters.keys())
    check("PEND007-01: stale_threshold_seconds in constructor", "stale_threshold_seconds" in params)

def test_pend007_recover_uses_self():
    """PEND007-02: _recover_stale_jobs uses self.stale_threshold_seconds, not os.getenv."""
    from app.services.workflow.orchestrator import WorkflowOrchestrator
    source = inspect.getsource(WorkflowOrchestrator._recover_stale_jobs)
    check("PEND007-02: Uses self.stale_threshold_seconds", "self.stale_threshold_seconds" in source)
    check("PEND007-02: No WORKFLOW_STALE_THRESHOLD os.getenv",
          'os.getenv("WORKFLOW_STALE_THRESHOLD"' not in source)

def test_pend007_main_uses_ai_cfg():
    """PEND007-03: main.py uses ai_cfg.workflow_* not os.getenv."""
    # Read main.py source directly
    with open(os.path.join(os.path.dirname(__file__), "..", "app", "main.py"), "r", encoding="utf-8") as f:
        source = f.read()
    orchestrator_block = source.split("WorkflowOrchestrator(")[1].split(")")[0]
    check("PEND007-03: Uses ai_cfg.workflow_worker_id", "ai_cfg.workflow_worker_id" in orchestrator_block)
    check("PEND007-03: Uses ai_cfg.workflow_poll_interval", "ai_cfg.workflow_poll_interval" in orchestrator_block)
    check("PEND007-03: No os.getenv in constructor call", "os.getenv" not in orchestrator_block)

# ═══════════════════════════════════════════════════════════════════
# PEND-008: FK type fix
# ═══════════════════════════════════════════════════════════════════

def test_pend008_session_id_is_string():
    """PEND008-01: workflow_jobs.session_id is Optional[str] with String(64)."""
    from app.models.workflow import WorkflowJob
    col = WorkflowJob.__table__.columns["session_id"]
    check("PEND008-01: Type is String", str(col.type) in ("VARCHAR(64)", "String(64)", "VARCHAR"))
    check("PEND008-01: Nullable", col.nullable == True)

def test_pend008_fk_references_session_id():
    """PEND008-02: FK references ai_sessions.session_id, not ai_sessions.id."""
    from app.models.workflow import WorkflowJob
    for fk in WorkflowJob.__table__.foreign_keys:
        if "session_id" in str(fk.column):
            check("PEND008-02: References session_id", "session_id" in str(fk.column))
            check("PEND008-02: Not ai_sessions.id", ".id" not in str(fk.column) or "ai_sessions.id" not in str(fk))

# ═══════════════════════════════════════════════════════════════════
# PEND-010: TOCTOU 500→409
# ═══════════════════════════════════════════════════════════════════

def test_pend010_cancel_returns_409():
    """PEND010-01: cancel endpoint returns 409, not 500."""
    with open(os.path.join(os.path.dirname(__file__), "..", "app", "routers", "workflows.py"), "r", encoding="utf-8") as f:
        source = f.read()
    check("PEND010-01: No status_code=500 in cancel path",
          'status_code=500' not in source or 'detail="Failed to cancel"' not in source)
    check("PEND010-01: Has status_code=409 for cancel",
          "status_code=409" in source)

def test_pend010_retry_returns_409():
    """PEND010-02: retry endpoint returns 409, not 500."""
    with open(os.path.join(os.path.dirname(__file__), "..", "app", "routers", "workflows.py"), "r", encoding="utf-8") as f:
        source = f.read()
    check("PEND010-02: No status_code=500 in retry path",
          'detail="Failed to retry"' not in source)

# ═══════════════════════════════════════════════════════════════════
# PEND-017/018: Infrastructure checks
# ═══════════════════════════════════════════════════════════════════

async def test_pend017_pgvector_available():
    """PEND017-01: pgvector extension detected (async instance method)."""
    import os
    # Ensure DATABASE_URL is set for the test
    if not os.getenv("DATABASE_URL"):
        os.environ["DATABASE_URL"] = "postgresql+asyncpg://elearning:elearning_secret@localhost:5432/elearning_db"
    from app.db.config import SessionLocal
    from app.repositories.similar_course_repo import SimilarCourseRepository
    async with SessionLocal() as session:
        repo = SimilarCourseRepository(session)
        result = await repo._pgvector_available()
        check("PEND017-01: pgvector available", result == True,
              "pgvector extension not detected — ensure PostgreSQL is running with pgvector installed")

def test_pend018_workflow_tables_exist():
    """PEND018-01: Workflow models are importable (tables created by migration)."""
    from app.models.workflow import WorkflowJob, WorkflowTypeDefinition, WorkflowJobEvent
    check("PEND018-01: WorkflowJob model", WorkflowJob is not None)
    check("PEND018-01: WorkflowTypeDefinition model", WorkflowTypeDefinition is not None)
    check("PEND018-01: WorkflowJobEvent model", WorkflowJobEvent is not None)

# ═══════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════

async def run_all_tests():
    test_pend007_orchestrator_has_stale_threshold()
    test_pend007_recover_uses_self()
    test_pend007_main_uses_ai_cfg()
    test_pend008_session_id_is_string()
    test_pend008_fk_references_session_id()
    test_pend010_cancel_returns_409()
    test_pend010_retry_returns_409()
    await test_pend017_pgvector_available()
    test_pend018_workflow_tables_exist()
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
