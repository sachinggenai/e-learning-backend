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
# PEND-021-IO: Ingestion Idempotency — course_id update on re-upload
# ═══════════════════════════════════════════════════════════════════

async def test_reupload_idempotent_same_course():
    """PEND021-IO-01: Re-upload with same course_id does NOT mutate job."""
    from app.services.ai.ingestion_service import AIIngestionService
    from app.db.config import SessionLocal
    import hashlib

    async with SessionLocal() as db:
        svc = AIIngestionService(db)
        content = b"test-ingestion-io-01-" + uuid.uuid4().bytes
        file_hash = hashlib.sha256(content).hexdigest()

        # Create a fresh job
        job = await svc.create_job(
            file=__import__("io").BytesIO(content),
            filename="test-io-01.docx",
            session_id="test-session-io",
            user_id="u-io",
            organization_id="org-io",
            course_id="COURSE-IO-01",
        )
        original_course = job.course_id
        original_meta = dict(job.source_metadata or {})

        # Re-upload same file with same course_id
        job2 = await svc.create_job(
            file=__import__("io").BytesIO(content),
            filename="test-io-01.docx",
            session_id="test-session-io",
            user_id="u-io",
            organization_id="org-io",
            course_id="COURSE-IO-01",
        )
        check("PEND021-IO-01: Same job returned", job2.job_id == job.job_id)
        check("PEND021-IO-01: course_id unchanged", job2.course_id == original_course)
        # Clean up
        await db.delete(job)
        await db.commit()


async def test_reupload_different_course_resets_gen_status():
    """PEND021-IO-02: Re-upload with different course_id resets generation_status."""
    from app.services.ai.ingestion_service import AIIngestionService
    from app.db.config import SessionLocal
    import hashlib

    async with SessionLocal() as db:
        svc = AIIngestionService(db)
        content = b"test-ingestion-io-02-" + uuid.uuid4().bytes

        # Create and complete a job
        job = await svc.create_job(
            file=__import__("io").BytesIO(content),
            filename="test-io-02.docx",
            session_id="test-session-io",
            user_id="u-io",
            organization_id="org-io",
            course_id="COURSE-IO-OLD",
        )
        job.source_metadata = {"generation_status": "completed", "applied_at": "2026-01-01", "applied_pages": 5}
        await db.commit()

        # Re-upload with different course_id
        job2 = await svc.create_job(
            file=__import__("io").BytesIO(content),
            filename="test-io-02.docx",
            session_id="test-session-io",
            user_id="u-io",
            organization_id="org-io",
            course_id="COURSE-IO-NEW",
        )
        meta = job2.source_metadata or {}
        check("PEND021-IO-02: course_id updated to new", job2.course_id == "COURSE-IO-NEW")
        check("PEND021-IO-02: gen_status reset to ready_for_review",
              meta.get("generation_status") == "ready_for_review")
        check("PEND021-IO-02: applied_at removed", "applied_at" not in meta)
        check("PEND021-IO-02: applied_pages removed", "applied_pages" not in meta)
        # Clean up
        await db.delete(job)
        await db.commit()


async def test_reupload_different_course_not_completed():
    """PEND021-IO-03: Re-upload with different course_id when NOT completed
    only updates course_id, does NOT touch generation_status."""
    from app.services.ai.ingestion_service import AIIngestionService
    from app.db.config import SessionLocal
    import hashlib

    async with SessionLocal() as db:
        svc = AIIngestionService(db)
        content = b"test-ingestion-io-03-" + uuid.uuid4().bytes

        job = await svc.create_job(
            file=__import__("io").BytesIO(content),
            filename="test-io-03.docx",
            session_id="test-session-io",
            user_id="u-io",
            organization_id="org-io",
            course_id="COURSE-IO-OLD",
        )
        job.source_metadata = {"generation_status": "generating", "page_count": 3}
        await db.commit()

        job2 = await svc.create_job(
            file=__import__("io").BytesIO(content),
            filename="test-io-03.docx",
            session_id="test-session-io",
            user_id="u-io",
            organization_id="org-io",
            course_id="COURSE-IO-NEW",
        )
        meta = job2.source_metadata or {}
        check("PEND021-IO-03: course_id updated", job2.course_id == "COURSE-IO-NEW")
        check("PEND021-IO-03: gen_status NOT reset (not completed)",
              meta.get("generation_status") == "generating")
        # Clean up
        await db.delete(job)
        await db.commit()


async def test_reupload_empty_course_id_noop():
    """PEND021-IO-04: Re-upload with empty course_id does NOT update."""
    from app.services.ai.ingestion_service import AIIngestionService
    from app.db.config import SessionLocal
    import hashlib

    async with SessionLocal() as db:
        svc = AIIngestionService(db)
        content = b"test-ingestion-io-04-" + uuid.uuid4().bytes

        job = await svc.create_job(
            file=__import__("io").BytesIO(content),
            filename="test-io-04.docx",
            session_id="test-session-io",
            user_id="u-io",
            organization_id="org-io",
            course_id="COURSE-IO-04",
        )
        original_course = job.course_id

        # Re-upload with empty course_id
        job2 = await svc.create_job(
            file=__import__("io").BytesIO(content),
            filename="test-io-04.docx",
            session_id="test-session-io",
            user_id="u-io",
            organization_id="org-io",
            course_id="",
        )
        check("PEND021-IO-04: course_id unchanged (empty)", job2.course_id == original_course)
        # Clean up
        await db.delete(job)
        await db.commit()


# ═══════════════════════════════════════════════════════════════════
# PEND-021-GEN: generate-course idempotency on completed jobs
# ═══════════════════════════════════════════════════════════════════

async def test_generate_idempotent_completed_job():
    """PEND021-GEN-01: Completed job with cached course → resets to ready_for_review."""
    from app.services.ai.course_generator import CourseGenerator, GenerationStatus
    from app.db.config import SessionLocal
    import hashlib

    async with SessionLocal() as db:
        svc = CourseGenerator(db)
        content = b"test-gen-io-01-" + uuid.uuid4().bytes
        file_hash = hashlib.sha256(content).hexdigest()

        # Create a completed job with generated course data
        from app.services.ai.ingestion_service import AIIngestionService
        ing_svc = AIIngestionService(db)
        job = await ing_svc.create_job(
            file=__import__("io").BytesIO(content),
            filename="test-gen-01.docx",
            session_id="test-session-gen",
            user_id="u-gen",
            organization_id="org-gen",
            course_id="COURSE-GEN-01",
        )
        job.source_metadata = {
            "generation_status": "completed",
            "applied_at": "2026-01-01",
            "applied_pages": 5,
            "generated_course": {
                "title": "Test Course",
                "description": "A test",
                "pages": [
                    {"title": "Page 1", "template_type": "content-text", "order": 0, "components": [
                        {"component_type": "content-text", "order_index": 0, "data": {"content": "Hello"}}
                    ]},
                    {"title": "Page 2", "template_type": "content-text", "order": 1, "components": []},
                ],
                "validation_results": [],
            },
        }
        job.status = "completed"
        await db.commit()

        result = await svc.start_generation(
            import_job_id=job.job_id, session_id="ses", user_id="u", course_id="C1",
        )
        check("PEND021-GEN-01: status = ready_for_review",
              result["status"] == GenerationStatus.READY_FOR_REVIEW.value)
        check("PEND021-GEN-01: idempotent = True",
              result.get("idempotent") is True)
        check("PEND021-GEN-01: pages preserved",
              result["total_pages"] == 2)

        # Verify metadata updated
        await db.refresh(job)
        meta_after = job.source_metadata or {}
        check("PEND021-GEN-01: gen_status reset in DB",
              meta_after.get("generation_status") == "ready_for_review")
        check("PEND021-GEN-01: applied_at removed",
              "applied_at" not in meta_after)
        check("PEND021-GEN-01: job.status = generated",
              job.status == "generated")

        # Clean up
        await db.delete(job)
        await db.commit()


async def test_generate_completed_no_cached_course_raises():
    """PEND021-GEN-02: Completed job WITHOUT cached course → raises error."""
    from app.services.ai.course_generator import CourseGenerator, GenerationError
    from app.db.config import SessionLocal
    import hashlib

    async with SessionLocal() as db:
        content = b"test-gen-io-02-" + uuid.uuid4().bytes
        from app.services.ai.ingestion_service import AIIngestionService
        ing_svc = AIIngestionService(db)
        job = await ing_svc.create_job(
            file=__import__("io").BytesIO(content),
            filename="test-gen-02.docx",
            session_id="test-session-gen",
            user_id="u-gen",
            organization_id="org-gen",
            course_id="COURSE-GEN-02",
        )
        job.source_metadata = {"generation_status": "completed"}  # No generated_course key
        job.status = "completed"
        await db.commit()

        svc = CourseGenerator(db)
        raised = False
        try:
            await svc.start_generation(
                import_job_id=job.job_id, session_id="ses", user_id="u", course_id="C2",
            )
        except GenerationError as e:
            raised = True
            check("PEND021-GEN-02: raises GenerationError", e.code == "NO_GENERATED_COURSE")
        check("PEND021-GEN-02: error was raised", raised)

        # Clean up
        await db.delete(job)
        await db.commit()


# ═══════════════════════════════════════════════════════════════════
# PEND-021-FP: Content fingerprint dedup on re-apply
# ═══════════════════════════════════════════════════════════════════

async def test_apply_with_same_content_is_noop():
    """PEND021-FP-01: Re-apply with same content → fingerprint match → no-op."""
    from app.services.ai.course_generator import CourseGenerator, _compute_course_fingerprint
    from app.db.config import SessionLocal
    import hashlib

    async with SessionLocal() as db:
        content = b"test-fp-01-" + uuid.uuid4().bytes
        from app.services.ai.ingestion_service import AIIngestionService
        ing_svc = AIIngestionService(db)
        job = await ing_svc.create_job(
            file=__import__("io").BytesIO(content),
            filename="test-fp-01.docx",
            session_id="test-session-fp",
            user_id="u-fp",
            organization_id="org-fp",
            course_id="COURSE-FP-01",
        )

        # Set up generated course data
        pages = [
            {"title": "Page A", "template_type": "content-text", "order": 0,
             "components": [{"component_type": "content-text", "order_index": 0,
             "data": {"content": "Hello world"}}]},
        ]
        job.source_metadata = {
            "generation_status": "ready_for_review",
            "generated_course": {"title": "Test", "pages": pages},
        }
        await db.commit()

        gen = CourseGenerator(db)
        r1 = await gen.apply_generated_course(
            import_job_id=job.job_id, user_id="u-fp",
        )
        check("PEND021-FP-01: first apply creates pages", r1["pages_created"] == 1)
        fp1 = (job.source_metadata or {}).get("content_fingerprint", "")
        check("PEND021-FP-01: fingerprint stored", bool(fp1))

        # Reset generation_status for re-apply (simulate generate-course)
        meta = dict(job.source_metadata or {})
        meta["generation_status"] = "ready_for_review"
        job.source_metadata = meta
        job.status = "generated"
        await db.commit()

        # Re-apply with same content
        r2 = await gen.apply_generated_course(
            import_job_id=job.job_id, user_id="u-fp",
        )
        check("PEND021-FP-01: re-apply no-op", r2["pages_created"] == 0)
        check("PEND021-FP-01: idempotent=true", r2.get("idempotent") is True)

        # Clean up
        from sqlalchemy import delete as sa_del
        from app.models.page_component import PageRecord
        await db.execute(sa_del(PageRecord).where(PageRecord.course_id == "COURSE-FP-01"))
        await db.delete(job)
        await db.commit()


async def test_apply_with_different_content_replaces():
    """PEND021-FP-02: Re-apply with different content → fingerprint mismatch → replace."""
    from app.services.ai.course_generator import CourseGenerator
    from app.db.config import SessionLocal

    async with SessionLocal() as db:
        content = b"test-fp-02-" + uuid.uuid4().bytes
        from app.services.ai.ingestion_service import AIIngestionService
        ing_svc = AIIngestionService(db)
        job = await ing_svc.create_job(
            file=__import__("io").BytesIO(content),
            filename="test-fp-02.docx",
            session_id="test-session-fp",
            user_id="u-fp",
            organization_id="org-fp",
            course_id="COURSE-FP-02",
        )

        pages_v1 = [
            {"title": "Page A", "template_type": "content-text", "order": 0,
             "components": [{"component_type": "content-text", "order_index": 0,
             "data": {"content": "Version 1 content"}}]},
        ]
        job.source_metadata = {
            "generation_status": "ready_for_review",
            "generated_course": {"title": "Test", "pages": pages_v1},
        }
        await db.commit()

        gen = CourseGenerator(db)
        r1 = await gen.apply_generated_course(
            import_job_id=job.job_id, user_id="u-fp",
        )
        check("PEND021-FP-02: first apply", r1["pages_created"] == 1)

        # Change content
        pages_v2 = [
            {"title": "Page B", "template_type": "content-text", "order": 0,
             "components": [{"component_type": "content-text", "order_index": 0,
             "data": {"content": "Completely different content here"}}]},
        ]
        meta = dict(job.source_metadata or {})
        meta["generation_status"] = "ready_for_review"
        meta["generated_course"] = {"title": "Test V2", "pages": pages_v2}
        job.source_metadata = meta
        job.status = "generated"
        await db.commit()

        r2 = await gen.apply_generated_course(
            import_job_id=job.job_id, user_id="u-fp",
        )
        check("PEND021-FP-02: content changed → replaces", r2["pages_created"] == 1)
        check("PEND021-FP-02: new title applied",
              r2["course_title"] == "Test V2")

        # Clean up
        from sqlalchemy import delete as sa_del
        from app.models.page_component import PageRecord
        await db.execute(sa_del(PageRecord).where(PageRecord.course_id == "COURSE-FP-02"))
        await db.delete(job)
        await db.commit()


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
    await test_reupload_idempotent_same_course()
    await test_reupload_different_course_resets_gen_status()
    await test_reupload_different_course_not_completed()
    await test_reupload_empty_course_id_noop()
    await test_generate_idempotent_completed_job()
    await test_generate_completed_no_cached_course_raises()
    await test_apply_with_same_content_is_noop()
    await test_apply_with_different_content_replaces()
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
