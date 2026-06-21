"""Standalone tests for Batch 6 features — PEND-019 through PEND-023.

Run: PYTHONPATH=. python tests/run_batch6_features_tests.py

Validates:
    PEND-019: Retrieval audit logging (ACTION_SIMILAR_COURSE_RETRIEVAL, timing)
    PEND-020: EmbeddingWorker, find_courses_without_embeddings
    PEND-021: DocumentExtractor (PDF/DOCX)
    PEND-022: ContextManager._llm_summarize(), summarize threshold
    PEND-023: AI_SCORMValidator
"""
from __future__ import annotations
import asyncio
import inspect
import os
import tempfile
import uuid

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
# PEND-019: Retrieval audit logging
# ═══════════════════════════════════════════════════════════════════

def test_pend019_audit_action_constant():
    """PEND019-01: ACTION_SIMILAR_COURSE_RETRIEVAL defined."""
    from app.services.ai.audit_service import AIAuditService
    check("PEND019-01: Constant exists", hasattr(AIAuditService, 'ACTION_SIMILAR_COURSE_RETRIEVAL'))
    check("PEND019-01: Correct value", AIAuditService.ACTION_SIMILAR_COURSE_RETRIEVAL == "similar_course.retrieval")

def test_pend019_timing_in_service():
    """PEND019-02: similar_course_service uses time.perf_counter for tier timing."""
    from app.services.ai.similar_course_service import SimilarCourseService
    source = inspect.getsource(SimilarCourseService.query_similar_courses)
    check("PEND019-02: Uses perf_counter", "perf_counter" in source)
    check("PEND019-02: Has tier1_ms", "tier1_ms" in source)
    check("PEND019-02: Has tier2_ms", "tier2_ms" in source)
    check("PEND019-02: Has tier3_ms", "tier3_ms" in source)

def test_pend019_audit_log_call():
    """PEND019-03: Calls audit.log() with ACTION_SIMILAR_COURSE_RETRIEVAL."""
    from app.services.ai.similar_course_service import SimilarCourseService
    source = inspect.getsource(SimilarCourseService.query_similar_courses)
    check("PEND019-03: Has audit.log call", "audit.log(" in source)
    check("PEND019-03: Has ACTION_SIMILAR_COURSE_RETRIEVAL", "ACTION_SIMILAR_COURSE_RETRIEVAL" in source)

def test_pend019_query_hash():
    """PEND019-04: SHA-256 query hash in audit details (hashlib imported at module level)."""
    import app.services.ai.similar_course_service as mod
    module_source = inspect.getsource(mod)
    check("PEND019-04: Has hashlib import (module level)", "import hashlib" in module_source)
    # Also check the method source for usage
    source = inspect.getsource(mod.SimilarCourseService.query_similar_courses)
    check("PEND019-04: Has sha256 hash", "sha256" in source)
    check("PEND019-04: Has query_hash", "query_hash" in source)

# ═══════════════════════════════════════════════════════════════════
# PEND-020: Embedding Worker
# ═══════════════════════════════════════════════════════════════════

def test_pend020_worker_class_exists():
    """PEND020-01: EmbeddingWorker class importable."""
    from app.workers.embedding_worker import EmbeddingWorker
    check("PEND020-01: EmbeddingWorker exists", EmbeddingWorker is not None)

def test_pend020_worker_has_start_stop():
    """PEND020-02: EmbeddingWorker has start() and stop()."""
    from app.workers.embedding_worker import EmbeddingWorker
    check("PEND020-02: Has start", hasattr(EmbeddingWorker, 'start'))
    check("PEND020-02: Has stop", hasattr(EmbeddingWorker, 'stop'))
    check("PEND020-02: Has _process_batch", hasattr(EmbeddingWorker, '_process_batch'))

def test_pend020_uses_asyncio_to_thread():
    """PEND020-03: Uses asyncio.to_thread for CPU-bound encode()."""
    from app.workers.embedding_worker import EmbeddingWorker
    source = inspect.getsource(EmbeddingWorker._process_batch)
    check("PEND020-03: Uses asyncio.to_thread", "to_thread" in source)

def test_pend020_repo_method_exists():
    """PEND020-04: find_courses_without_embeddings() exists on SimilarCourseRepository."""
    from app.repositories.similar_course_repo import SimilarCourseRepository
    check("PEND020-04: find_courses_without_embeddings exists", hasattr(SimilarCourseRepository, 'find_courses_without_embeddings'))

def test_pend020_pgvector_check():
    """PEND020-05: _is_pgvector_available returns bool."""
    from app.workers.embedding_worker import EmbeddingWorker
    result = EmbeddingWorker._is_pgvector_available()
    check("PEND020-05: Returns bool", isinstance(result, bool))

# ═══════════════════════════════════════════════════════════════════
# PEND-021: Document Extractor
# ═══════════════════════════════════════════════════════════════════

def test_pend021_extractor_class():
    """PEND021-01: DocumentExtractor class exists."""
    from app.services.ai.document_extractor import DocumentExtractor
    check("PEND021-01: Class exists", DocumentExtractor is not None)
    e = DocumentExtractor()
    check("PEND021-01: Has extract method", hasattr(e, 'extract'))
    check("PEND021-01: Has _extract_pdf", hasattr(e, '_extract_pdf'))
    check("PEND021-01: Has _extract_docx", hasattr(e, '_extract_docx'))

async def test_pend021_extract_unsupported_type():
    """PEND021-02: Raises ValueError for unsupported MIME type."""
    from app.services.ai.document_extractor import DocumentExtractor
    e = DocumentExtractor()
    try:
        await e.extract("test.xyz", "application/unknown")
        check("PEND021-02: ValueError on unsupported type", False, "Should have raised ValueError")
    except ValueError:
        check("PEND021-02: ValueError on unsupported type", True)

def test_pend021_ingestion_integration():
    """PEND021-03: ingestion_service imports DocumentExtractor."""
    from app.services.ai.ingestion_service import AIIngestionService
    source = inspect.getsource(AIIngestionService.create_job)
    check("PEND021-03: Imports DocumentExtractor", "DocumentExtractor" in source)

def test_pend021_max_limits():
    """PEND021-04: MAX_PAGES and MAX_CHARS constants defined."""
    from app.services.ai.document_extractor import DocumentExtractor
    check("PEND021-04: MAX_PAGES = 100", DocumentExtractor.MAX_PAGES == 100)
    check("PEND021-04: MAX_CHARS = 500000", DocumentExtractor.MAX_CHARS == 500000)

# ═══════════════════════════════════════════════════════════════════
# PEND-022: LLM Context Summarization
# ═══════════════════════════════════════════════════════════════════

def test_pend022_llm_summarize_exists():
    """PEND022-01: ContextManager has _llm_summarize method."""
    from app.services.ai.context_manager import ContextManager
    check("PEND022-01: _llm_summarize exists", hasattr(ContextManager, '_llm_summarize'))

def test_pend022_summarize_threshold():
    """PEND022-02: _summarize_threshold set to 0.70."""
    from app.services.ai.context_manager import ContextManager
    mgr = ContextManager()
    check("PEND022-02: _summarize_threshold = 0.70", mgr._summarize_threshold == 0.70)

def test_pend022_summary_cache():
    """PEND022-03: _summary_cache dict initialized."""
    from app.services.ai.context_manager import ContextManager
    mgr = ContextManager()
    check("PEND022-03: _summary_cache is dict", isinstance(mgr._summary_cache, dict))

def test_pend022_uses_haiku_model():
    """PEND022-04: Uses claude-haiku-4-5 for summarization (cheap model)."""
    from app.services.ai.context_manager import ContextManager
    source = inspect.getsource(ContextManager._llm_summarize)
    check("PEND022-04: Uses haiku model", "haiku" in source.lower())

def test_pend022_low_temperature():
    """PEND022-05: Uses temperature=0.2 for factual summarization."""
    from app.services.ai.context_manager import ContextManager
    source = inspect.getsource(ContextManager._llm_summarize)
    check("PEND022-05: temperature=0.2", "temperature=0.2" in source)

# ═══════════════════════════════════════════════════════════════════
# PEND-023: SCORM AI Validation
# ═══════════════════════════════════════════════════════════════════

def test_pend023_validator_class():
    """PEND023-01: AI_SCORMValidator class exists."""
    from app.services.export_validator import AI_SCORMValidator
    check("PEND023-01: Class exists", AI_SCORMValidator is not None)

def test_pend023_has_methods():
    """PEND023-02: AI_SCORMValidator has validate_ai_content + validate_manifest."""
    from app.services.export_validator import AI_SCORMValidator
    v = AI_SCORMValidator()
    check("PEND023-02: Has validate_ai_content", hasattr(v, 'validate_ai_content'))
    check("PEND023-02: Has validate_manifest", hasattr(v, 'validate_manifest'))

def test_pend023_html_tag_list():
    """PEND023-03: ALLOWED_SCORM_HTML_TAGS contains common tags."""
    from app.services.export_validator import ALLOWED_SCORM_HTML_TAGS
    for tag in ["p", "div", "h1", "h2", "img", "ul", "li", "table", "a", "strong"]:
        check(f"PEND023-03: {tag} in allowed tags", tag in ALLOWED_SCORM_HTML_TAGS)

async def test_pend023_validate_empty_pages():
    """PEND023-04: Empty pages produce warnings, not errors."""
    from app.services.export_validator import AI_SCORMValidator
    v = AI_SCORMValidator()
    result = await v.validate_ai_content([{"title": "Empty", "content": ""}])
    check("PEND023-04: Empty page = warning, still valid", len(result["warnings"]) > 0 and result["valid"] == True)

async def test_pend023_detect_unescaped_xml():
    """PEND023-05: Unescaped & in content produces error."""
    from app.services.export_validator import AI_SCORMValidator
    v = AI_SCORMValidator()
    result = await v.validate_ai_content([{"title": "Test", "content": "A & B &copy; C"}])
    check("PEND023-05: Unescaped XML detected", len(result["errors"]) > 0 and not result["valid"])

# ═══════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════

async def run_all_tests():
    test_pend019_audit_action_constant()
    test_pend019_timing_in_service()
    test_pend019_audit_log_call()
    test_pend019_query_hash()
    test_pend020_worker_class_exists()
    test_pend020_worker_has_start_stop()
    test_pend020_uses_asyncio_to_thread()
    test_pend020_repo_method_exists()
    test_pend020_pgvector_check()
    test_pend021_extractor_class()
    await test_pend021_extract_unsupported_type()
    test_pend021_ingestion_integration()
    test_pend021_max_limits()
    test_pend022_llm_summarize_exists()
    test_pend022_summarize_threshold()
    test_pend022_summary_cache()
    test_pend022_uses_haiku_model()
    test_pend022_low_temperature()
    test_pend023_validator_class()
    test_pend023_has_methods()
    test_pend023_html_tag_list()
    await test_pend023_validate_empty_pages()
    await test_pend023_detect_unescaped_xml()
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
