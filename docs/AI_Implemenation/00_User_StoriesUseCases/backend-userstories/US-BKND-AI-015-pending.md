# US-BKND-AI-015 — Advanced RAG: Pending Items

**Status:** ~25% complete | **Estimate:** 26 hours | **Source:** `VALIDATION_REPORT.md` Flow #4 / #13

---

## Current State (What "Works")

Only **Tier-3 keyword search** is partially implemented:

1. **`app/routers/ai_tools.py:726-809`** — `POST /tools/query_similar_courses` does basic `ILIKE` keyword matching against course titles/descriptions. No PII redaction, no tone inference, no Tier-1/2 fallback, no enrichment.
2. **`app/services/ai/chat_orchestrator.py:331-333`** — The mock handler for `query_similar_courses` returns **hardcoded empty results**: `{"courses": [], "total_count": 0}`. Intent detection at line 227-230 recognizes "similar course" keywords but routes to the stub.

---

## Missing Files (6 new)

| # | File | Purpose |
|---|------|---------|
| 1 | `app/models/course_embedding.py` | `CourseEmbeddingRecord` ORM model for `course_embeddings` table (see spec §2.4) |
| 2 | `app/repositories/similar_course_repo.py` | Tier-1 (pgvector), Tier-2 (PostgreSQL full-text), Tier-3 (keyword) search + `enrich_results` + PII redaction utilities (see spec §2.5) |
| 3 | `app/services/ai/similar_course_service.py` | Orchestrates tiered fallback: Tier-1 → Tier-2 → Tier-3, result shaping, empty-result handling (see spec §2.6) |
| 4 | `app/services/ai/embedding_provider.py` | Abstract `EmbeddingProvider` ABC + `OpenAIBackend` (text-embedding-ada-002) + `MockEmbeddingProvider` + factory function (see spec §2.7) |
| 5 | `app/routers/ai_similar_courses.py` | Optional REST endpoint `POST /ai/similar-courses` for admin/UI access outside tool context (see spec §2.9) |
| 6 | `alembic/versions/*_add_course_embeddings.py` | Migration creating `course_embeddings` table (with conditional pgvector ivfflat index) and `course_similarity_cache` table (see spec §2.11) |

---

## Missing Integration Points (5 modifications)

| # | What | File to modify | Detail |
|---|------|---------------|--------|
| 7 | Register `query_similar_courses` tool schema | `app/services/ai/tool_registry.py` | Entire file does not exist. Needs to be created with full JSON schema per FR-1 (see spec §2.8) |
| 8 | Wire `SimilarCourseService` into orchestrator | `app/services/ai/chat_orchestrator.py` | Replace mock handler (line 331-333) with real `similar_course_service.query_similar_courses()` dispatch |
| 9 | Add `similar_course_retrieval` feature flag | `app/utils/feature_flags.py` | Default `false`. Gate tool invocation with clear error when disabled (see spec §2.2) |
| 10 | Import `course_embedding` model | `app/main.py` + `alembic/env.py` | Register for startup table auto-create and autogenerate detection (see spec §2.2) |

---

## Missing Capabilities (8 gaps in current "Tier-3" implementation)

| # | Capability | Detail |
|---|-----------|--------|
| 11 | **Tier-1: pgvector vector search** | Cosine-similarity via `<=>` operator against `course_embeddings`. Gated by `ENABLE_PGVECTOR=true`. No pgvector extension installed in any environment. (see spec FR-2 Tier 1) |
| 12 | **Tier-2: PostgreSQL full-text search** | `ts_vector`/`ts_query` with weighted ranking (`setweight`) across `courses.title` (A), `courses.description` (B), `templates.title` (C). No full-text indexes exist on these tables. (see spec FR-2 Tier 2) |
| 13 | **PII redaction in excerpts** | Regex covering email, US phone, SSN patterns. `_PII_PATTERNS` regex + `.sub("[REDACTED]", ...)`. Currently no redaction at all in the existing endpoint. (see spec FR-6) |
| 14 | **Safe field excerpt extraction** | `SAFE_EXCERPT_FIELDS` allowlist excludes `isCorrect`, `correctAnswer`, `correctAnswers`, scoring config, user-specific fields. Currently extracts raw component data without filtering. (see spec FR-6) |
| 15 | **Tone/style inference** | `_derive_tone_notes()` heuristic based on template type composition (e.g., mcq → "uses knowledge checks", accordion → "organizes in expandable sections"). Not implemented. (see spec FR-3: `tone_notes`) |
| 16 | **Result enrichment** | Template breakdown (`template_breakdown` dict), sample excerpts (up to 3 per course, max 500 chars), match summaries, proper `relevance_score` (0.0-1.0 normalized). Current endpoint returns flat, un-enriched results. (see spec §2.5 `enrich_results`) |
| 17 | **Empty-result non-fatal guidance** | Returns `message: "Generation can continue without examples. Consider providing explicit tone and structure guidance in your prompt."` with `retrieval_tier_used`. Current mock just returns `{courses: [], total_count: 0}` with no guidance. (see spec FR-4) |
| 18 | **System prompt source-of-truth warning** | Instruction: _"The `query_similar_courses` tool returns example courses for tone and structural reference only. Do NOT derive API contracts, validation rules, template schemas, or configuration values from these results."_ Not present in system prompt. (see spec FR-7) |

---

## Missing Tests (22 scenarios)

### Unit Tests (7)
| ID | Scenario | Expected |
|----|----------|----------|
| UT-1 | `EmbeddingProvider.mock.embed("safety training")` | 1536-dim float vector |
| UT-2 | `MockEmbeddingProvider.embed("hello")` twice | Deterministic (identical) output |
| UT-3 | PII redaction: `"Contact john@test.com or call 555-123-4567"` | `"Contact [REDACTED] or call [REDACTED]"` |
| UT-4 | `_extract_excerpt` with MCQ `questions[].question` | Returns question text, truncated to 500 chars |
| UT-5 | `_extract_excerpt` with `isCorrect: true` in data | `isCorrect` excluded (not in `SAFE_EXCERPT_FIELDS`) |
| UT-6 | `_empty_result("No matches")` | `courses=[]`, `total_count=0`, message includes "continue without examples" |
| UT-7 | `_derive_tone_notes` with `{welcome, mcq, summary}` | String containing "introduction", "knowledge checks", "recap" |

### Integration Tests (5)
| ID | Scenario | Expected |
|----|----------|----------|
| IT-1 | `search_fulltext(session, "safety course", 5)` | Course with "safety" in title returned with score > 0 |
| IT-2 | `search_keyword(session, "onboarding", 5)` | At least one result with score 0.5 |
| IT-3 | `query_similar_courses` with empty string | Empty result with "Query is empty" message |
| IT-4 | `enrich_results` populates all fields | `template_breakdown`, `sample_excerpts`, `tone_notes` all present |
| IT-5 | Cross-tenant isolation: org-A query, only org-B courses exist | Zero results from org-B |

### API Tests (4)
| ID | Scenario | Expected |
|----|----------|----------|
| AT-1 | `POST /api/v1/ai/similar-courses` valid body | 200 with `courses` array |
| AT-2 | Same endpoint, empty query | 422 validation error |
| AT-3 | Tool adapter via chat orchestrator | Well-formed dict result |
| AT-4 | `FEATURE_SIMILAR_COURSE_RETRIEVAL=false` | Feature-disabled error |

### Security Tests (2)
| ID | Scenario | Expected |
|----|----------|----------|
| ST-1 | PII in course content: email in template body | Excerpt redacts email |
| ST-2 | Cross-tenant: org-A session, org-B courses only | Empty results |

**Test file to create:** `tests/run_similar_course_tests.py`

---

## Missing Infra / Config (6 env vars)

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_PGVECTOR` | `false` | Enable pgvector Tier-1 vector search |
| `EMBEDDING_PROVIDER` | `mock` | `mock` or `openai` |
| `OPENAI_API_KEY` | (empty) | Required when `EMBEDDING_PROVIDER=openai` |
| `EMBEDDING_MODEL` | `text-embedding-ada-002` | OpenAI embedding model name |
| `SIMILAR_COURSE_MAX_RESULTS` | `20` | Hard upper limit on result count |
| `SIMILAR_COURSE_CACHE_TTL_MINUTES` | `60` | Cache TTL for similarity results |

---

## Missing Database Objects

### Table: `course_embeddings`
- `id` SERIAL PK
- `course_record_id` INTEGER FK → `courses(id)` ON DELETE CASCADE
- `organization_id` VARCHAR(64) NOT NULL DEFAULT 'default'
- `embedding` vector(1536) — nullable (pgvector unavailable)
- `content_hash` VARCHAR(64) NOT NULL — SHA-256 for staleness detection
- `chunk_count` INTEGER NOT NULL DEFAULT 1
- `embedding_model` VARCHAR(100) NOT NULL DEFAULT 'text-embedding-ada-002'
- `is_stale` BOOLEAN NOT NULL DEFAULT FALSE — set TRUE on content change
- `created_at`, `updated_at` timestamps
- **Indexes:** `ix_course_embeddings_course_record_id`, `ix_course_embeddings_org_stale` (partial WHERE is_stale=FALSE), `ix_course_embeddings_vector` (ivfflat, conditional on pgvector extension)

### Table: `course_similarity_cache`
- `id` SERIAL PK
- `source_course_id` INTEGER FK → `courses(id)` ON DELETE CASCADE
- `similar_course_id` INTEGER FK → `courses(id)` ON DELETE CASCADE
- `similarity_score` FLOAT NOT NULL
- `cache_tier` VARCHAR(8) NOT NULL DEFAULT 'tier1'
- `expires_at` TIMESTAMP WITHOUT TIME ZONE NOT NULL
- UNIQUE(`source_course_id`, `similar_course_id`)

---

## Deferred to Future Iterations (not in this scope)

| Iteration | Feature |
|-----------|---------|
| 2 | Scheduled re-embedding job — poll `is_stale=TRUE` and refresh vectors via background worker |
| 3 | Cross-organization admin search — bypass tenant scoping with `ADMIN_ROLE` gate |
| 4 | Hybrid search (RRF) — Reciprocal Rank Fusion combining vector + full-text scores |
| 5 | Multi-modal embeddings — thumbnail/image embeddings for visual-style similarity |
| 6 | Feedback loop — track which RAG results lead to accepted proposals; down-rank underperformers |
| 7 | Real-time similarity during editing — auto-suggest similar pages in sidebar while author edits |

---

## Key References

- **Story spec:** `docs/AI_Implemenation/00_User_StoriesUseCases/backend-userstories/US-BKND-AI-015_enriched.md`
- **Architecture doc:** `docs/AI_Implemenation/01_SystemArchitecture/PRODUCTION_READY_AI_AUTHORING_ARCHITECTURE.md` — §7 RAG vs. Tools Strategy, §8.2 RAG Indexing Strategy
- **Validation report:** `docs/AI_Implemenation/01_SystemArchitecture/VALIDATION_REPORT.md` — Flow #4 (v1.0): "Advanced RAG 25%", Flow #13 (Similar Course Retrieval): "82% compliance, vector search future"
- **Current implementation:** `app/routers/ai_tools.py:719-809`, `app/services/ai/chat_orchestrator.py:227-333`
- **Related flows:** Flow #4 (Create Proposal v1.0), Flow #13 (Similar Course Retrieval)
