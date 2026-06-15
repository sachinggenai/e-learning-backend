# US-BKND-AI-019: Generate Full Course From Uploaded File

**Status:** ✅ COMPLETE
**Priority:** SHOULD
**Sprint:** 4
**Implemented:** 2026-06-15

## Summary

Course generation service that transforms an approved page plan (from US-AI-017 extraction) into a complete course with structured page content. Generates template-appropriate content for each page (text-content, accordion, tabs, click-reveal, final-assessment), validates against template schemas, and returns a course preview for user review.

## Files Created/Modified

| File | Action | Description |
|---|---|---|
| `app/services/ai/course_generator.py` | NEW | CourseGenerator service with mock content generation, validation, and job lifecycle |
| `app/routers/ai_ingestion.py` | MODIFIED | Added POST /generate-course and GET /generate-course/{job_id} endpoints |
| `tests/run_course_generation_tests.py` | NEW | 37 tests covering mock generation, all 5 template types, validation, error handling |

## Template-Specific Content Generation (Mock Mode)

| Template Type | Generated Content |
|---|---|
| text-content | HTML content with headings and source material integration |
| accordion | 3 items: Introduction, Key Details, Summary |
| tabs | 3 tabs: Overview, Details, Examples |
| click-reveal | Q&A format with source material |
| final-assessment | Passing score + question with options |

## Key Design Decisions

1. **Mock-first** — Content generation uses deterministic mock templates; LLM integration is configured for production
2. **Per-page validation** — Each generated page is validated against its template type with errors/warnings
3. **Job-based async** — Uses import job's source_metadata to track generation status across polls
4. **All-or-nothing validation** — Blocking errors prevent course generation from completing
5. **Provenance tracking** — Generated courses include source file info, timestamps, and model metadata

## See Also

- [US-AI-019 Full Spec](../US-AI-019_GENERATE_FULL_COURSE_FROM_FILE.md) — Complete functional and technical specification
- [US-BKND-AI-016](US-BKND-AI-016_enriched.md) — File Upload Foundation
- [US-BKND-AI-017](US-BKND-AI-017_enriched.md) — Document Extraction
