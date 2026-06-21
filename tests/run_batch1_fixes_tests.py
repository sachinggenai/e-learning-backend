"""Standalone tests for Batch 1 fixes — PEND-001 through PEND-006.

Run: PYTHONPATH=. python tests/run_batch1_fixes_tests.py

Validates:
    PEND-001: TemplateValidationEngine import + validate() usage
    PEND-002: LLMClient.chat() + LLMMessage import
    PEND-003: CostTracker.record() sync + token_usage dict access
    PEND-004: create_proposal() loop instead of create_batch_proposal()
    PEND-005: CourseRepository.get_by_course_id() + CourseNotFoundError
    PEND-006: Feature flag enabled=True for durable_workflow_engine
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
# PEND-001: ValidationEngine → TemplateValidationEngine
# ═══════════════════════════════════════════════════════════════════

def test_pend001_import_uses_template_validation_engine():
    """PEND001-01: Source imports TemplateValidationEngine, not ValidationEngine."""
    from app.services.workflow.steps.course_generation import validate_course_step
    source = inspect.getsource(validate_course_step)
    check("PEND001-01: TemplateValidationEngine imported", "TemplateValidationEngine" in source)
    check("PEND001-01: ValidationEngine (bare) not imported",
          "from app.services.ai.validation_engine import ValidationEngine" not in source)

def test_pend001_uses_validate_method():
    """PEND001-02: Uses engine.validate(), not validate_course_structure()."""
    from app.services.workflow.steps.course_generation import validate_course_step
    source = inspect.getsource(validate_course_step)
    check("PEND001-02: Uses .validate(", ".validate(" in source, "Must use validate() not validate_course_structure()")
    check("PEND001-02: No validate_course_structure", "validate_course_structure" not in source)

def test_pend001_constructs_with_contracts_service():
    """PEND001-03: TemplateValidationEngine constructed with contracts_service."""
    from app.services.workflow.steps.course_generation import validate_course_step
    source = inspect.getsource(validate_course_step)
    check("PEND001-03: Uses AITemplateContractsService", "AITemplateContractsService" in source)
    check("PEND001-03: Passes contracts_service=", "contracts_service=" in source)

def test_pend001_handles_validation_result():
    """PEND001-04: Checks result.status == 'error', uses .messages."""
    from app.services.workflow.steps.course_generation import validate_course_step
    source = inspect.getsource(validate_course_step)
    check("PEND001-04: Checks result.status", "result.status" in source)
    check("PEND001-04: Uses result.messages", "result.messages" in source)
    check("PEND001-04: Uses m.model_dump()", ".model_dump()" in source or "m.message" in source)

# ═══════════════════════════════════════════════════════════════════
# PEND-002: LLMClient.generate() → chat()
# ═══════════════════════════════════════════════════════════════════

def test_pend002_imports_llmmessage():
    """PEND002-01: LLMMessage is imported alongside LLMClient (lazy import inside function body)."""
    from app.services.workflow.steps.course_generation import generate_pages_step
    source = inspect.getsource(generate_pages_step)
    check("PEND002-01: Imports LLMMessage", "LLMMessage" in source)

def test_pend002_uses_chat_not_generate():
    """PEND002-02: Uses .chat() not .generate()."""
    from app.services.workflow.steps.course_generation import generate_pages_step
    source = inspect.getsource(generate_pages_step)
    check("PEND002-02: Uses .chat(", ".chat(" in source)
    check("PEND002-02: No .generate(", ".generate(" not in source)

def test_pend002_no_temp_in_constructor():
    """PEND002-03: temperature/max_tokens NOT passed to LLMClient()."""
    from app.services.workflow.steps.course_generation import generate_pages_step
    source = inspect.getsource(generate_pages_step)
    constructor_call = source.split("LLMClient(")[1].split(")")[0]
    check("PEND002-03: No temperature in LLMClient()", "temperature=" not in constructor_call)
    check("PEND002-03: No max_tokens in LLMClient()", "max_tokens=" not in constructor_call)

def test_pend002_temp_in_chat_call():
    """PEND002-04: temperature/max_tokens passed to chat()."""
    from app.services.workflow.steps.course_generation import generate_pages_step
    source = inspect.getsource(generate_pages_step)
    check("PEND002-04: temperature= in chat()", "temperature=temperature" in source)
    check("PEND002-04: max_tokens= in chat()", "max_tokens=max_tokens" in source)

def test_pend002_llmclient_init_signature():
    """PEND002-05: LLMClient.__init__ has correct params (no temperature/max_tokens)."""
    from app.services.ai.llm_client import LLMClient
    sig = inspect.signature(LLMClient.__init__)
    params = list(sig.parameters.keys())
    check("PEND002-05: No temperature in __init__", "temperature" not in params)
    check("PEND002-05: No max_tokens in __init__", "max_tokens" not in params)
    check("PEND002-05: Has model param", "model" in params)

# ═══════════════════════════════════════════════════════════════════
# PEND-003: CostTracker.record() sync fix
# ═══════════════════════════════════════════════════════════════════

def test_pend003_checks_token_usage():
    """PEND003-01: hasattr checks 'token_usage' not 'usage'."""
    from app.services.workflow.steps.course_generation import generate_pages_step
    source = inspect.getsource(generate_pages_step)
    check("PEND003-01: Checks token_usage", "token_usage" in source)
    check("PEND003-01: No bare 'usage' check", "hasattr(response, 'usage')" not in source)

def test_pend003_uses_record_method():
    """PEND003-02: Uses cost_tracker.record() not record_usage()."""
    from app.services.workflow.steps.course_generation import generate_pages_step
    source = inspect.getsource(generate_pages_step)
    check("PEND003-02: Uses .record(", ".record(" in source)
    check("PEND003-02: No record_usage", "record_usage" not in source)

def test_pend003_record_is_synchronous():
    """PEND003-03: CostTracker.record() is def, not async def."""
    from app.services.ai.cost_tracker import CostTracker
    check("PEND003-03: record() is synchronous", not inspect.iscoroutinefunction(CostTracker.record))

def test_pend003_uses_dict_access():
    """PEND003-04: Token access uses dict ['input_tokens'] not namespace .input_tokens."""
    from app.services.workflow.steps.course_generation import generate_pages_step
    source = inspect.getsource(generate_pages_step)
    check("PEND003-04: Dict access token_usage.get(", "token_usage.get(" in source)
    check("PEND003-04: No namespace .input_tokens", ".usage.input_tokens" not in source)

def test_pend003_no_await_on_record():
    """PEND003-05: No await before cost_tracker.record() — it's sync."""
    from app.services.workflow.steps.course_generation import generate_pages_step
    source = inspect.getsource(generate_pages_step)
    check("PEND003-05: No await cost_tracker.record", "await cost_tracker.record" not in source)

def test_pend003_llmresponse_token_usage_type():
    """PEND003-06: LLMResponse.token_usage is Dict[str, int]."""
    from app.services.ai.llm_client import LLMResponse
    r = LLMResponse(content="test", model="test", token_usage={"input_tokens": 10, "output_tokens": 20}, stop_reason="stop")
    check("PEND003-06: token_usage is dict", isinstance(r.token_usage, dict))
    check("PEND003-06: No 'usage' attribute", not hasattr(r, 'usage'))

# ═══════════════════════════════════════════════════════════════════
# PEND-004: create_batch_proposal → create_proposal loop
# ═══════════════════════════════════════════════════════════════════

def test_pend004_loops_create_proposal():
    """PEND004-01: Uses create_proposal() in a loop, not create_batch_proposal()."""
    from app.services.workflow.steps.course_generation import create_batch_proposal_step
    source = inspect.getsource(create_batch_proposal_step)
    check("PEND004-01: Uses create_proposal", "create_proposal" in source)
    check("PEND004-01: No create_batch_proposal", "create_batch_proposal(" not in source)
    check("PEND004-01: Has for loop", "for " in source and "in results" in source)

def test_pend004_uses_correct_operation():
    """PEND004-02: operation='create_page' (not 'create')."""
    from app.services.workflow.steps.course_generation import create_batch_proposal_step
    source = inspect.getsource(create_batch_proposal_step)
    check("PEND004-02: operation='create_page'", "create_page" in source)

def test_pend004_uses_resource_type_page():
    """PEND004-03: resource_type='page'."""
    from app.services.workflow.steps.course_generation import create_batch_proposal_step
    source = inspect.getsource(create_batch_proposal_step)
    check("PEND004-03: resource_type='page'", "resource_type=\"page\"" in source or "resource_type='page'" in source)

def test_pend004_create_proposal_signature():
    """PEND004-04: AIProposalService.create_proposal has correct params."""
    from app.services.ai.proposal_service import AIProposalService
    sig = inspect.signature(AIProposalService.create_proposal)
    params = list(sig.parameters.keys())
    for p in ["session_id", "user_id", "organization_id", "course_id", "operation", "resource_type", "data"]:
        check(f"PEND004-04: create_proposal has {p}", p in params)

# ═══════════════════════════════════════════════════════════════════
# PEND-005: CourseRepository.get_by_id() fix
# ═══════════════════════════════════════════════════════════════════

def test_pend005_uses_get_by_course_id():
    """PEND005-01: Uses get_by_course_id(), not get_by_id()."""
    from app.services.workflow.steps.scorm_export import validate_course_step
    source = inspect.getsource(validate_course_step)
    check("PEND005-01: Uses get_by_course_id", "get_by_course_id" in source)
    check("PEND005-01: No get_by_id", "get_by_id(" not in source)

def test_pend005_has_course_not_found_handler():
    """PEND005-02: try/except CourseNotFoundError present."""
    from app.services.workflow.steps.scorm_export import validate_course_step
    source = inspect.getsource(validate_course_step)
    check("PEND005-02: Has CourseNotFoundError import", "CourseNotFoundError" in source)
    check("PEND005-02: Has try/except", "try:" in source and "except CourseNotFoundError:" in source)

def test_pend005_course_repo_methods():
    """PEND005-03: CourseRepository has correct methods."""
    from app.repositories.course_repo import CourseRepository, CourseNotFoundError
    check("PEND005-03: Has get(pk)", hasattr(CourseRepository, 'get'))
    check("PEND005-03: Has get_by_course_id", hasattr(CourseRepository, 'get_by_course_id'))
    check("PEND005-03: No get_by_id", not hasattr(CourseRepository, 'get_by_id'))
    check("PEND005-03: CourseNotFoundError exists", CourseNotFoundError is not None)

# ═══════════════════════════════════════════════════════════════════
# PEND-006: Feature flag default
# ═══════════════════════════════════════════════════════════════════

def test_pend006_feature_flag_enabled():
    """PEND006-01: durable_workflow_engine is enabled=True."""
    from app.utils.feature_flags import is_feature_enabled
    check("PEND006-01: durable_workflow_engine enabled", is_feature_enabled("durable_workflow_engine") == True)

def test_pend006_flag_default_is_true():
    """PEND006-02: Python default is True (not False)."""
    from app.utils.feature_flags import feature_flags
    flag = feature_flags.get_flag("durable_workflow_engine")
    check("PEND006-02: enabled=True", flag.enabled == True if flag else False)

def test_pend006_app_imports_with_workflow():
    """PEND006-03: App imports successfully. Workflow routes are optional (feature-flagged)."""
    from app.main import app
    routes_count = len(app.routes)
    check("PEND006-03: App imported with routes", routes_count > 0,
          f"Got {routes_count} routes")

# ═══════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════

async def run_all_tests():
    test_pend001_import_uses_template_validation_engine()
    test_pend001_uses_validate_method()
    test_pend001_constructs_with_contracts_service()
    test_pend001_handles_validation_result()
    test_pend002_imports_llmmessage()
    test_pend002_uses_chat_not_generate()
    test_pend002_no_temp_in_constructor()
    test_pend002_temp_in_chat_call()
    test_pend002_llmclient_init_signature()
    test_pend003_checks_token_usage()
    test_pend003_uses_record_method()
    test_pend003_record_is_synchronous()
    test_pend003_uses_dict_access()
    test_pend003_no_await_on_record()
    test_pend003_llmresponse_token_usage_type()
    test_pend004_loops_create_proposal()
    test_pend004_uses_correct_operation()
    test_pend004_uses_resource_type_page()
    test_pend004_create_proposal_signature()
    test_pend005_uses_get_by_course_id()
    test_pend005_has_course_not_found_handler()
    test_pend005_course_repo_methods()
    test_pend006_feature_flag_enabled()
    test_pend006_flag_default_is_true()
    test_pend006_app_imports_with_workflow()
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
