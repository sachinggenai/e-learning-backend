# RCA: Why US-BKND-AI-015 (Advanced RAG) Was Only ~25% Implemented

**Date:** 2026-06-20  
**Method:** 5-Why + Event Timeline Analysis  
**Finding:** INDEX.md marked COMPLETE; actual implementation at 25% (Tier-3 keyword only, no Tier-1/2, no embedding infrastructure)

---

## 1. Executive Summary

US-BKND-AI-015 (Retrieve Similar Courses for Examples and Tone) was declared **✅ COMPLETE** in the [INDEX.md](INDEX.md) alongside 46 other stories, but the actual implementation covers only ~25% of the specification. The story's enriched specification (1037 lines) describes a full three-tier retrieval architecture with embedding providers, pgvector, PostgreSQL full-text search, PII redaction, and result enrichment. What shipped: a basic ILIKE keyword-matching endpoint and a mock handler that returns hardcoded empty results.

**Root Cause:** The implementation conflated "tool surface exists" (the chat orchestrator can invoke a tool named `query_similar_courses`) with "story complete" (full three-tier retrieval with embedding infrastructure). This was compounded by INDEX.md being marked COMPLETE at the specification-writing stage, with no post-implementation verification against the actual code.

---

## 2. Event Timeline

| Date | Commit | What Happened | Impact |
|------|--------|--------------|--------|
| Jun 13 | `c45422b` | "added some userstories" — USER_STORIES.md expanded | Stories defined at high level |
| Jun 13 | (docs created) | `PRODUCTION_READY_AI_AUTHORING_ARCHITECTURE.md` written with 10-chunk phased plan. **RAG/vector search not allocated to any chunk.** | RAG left without a delivery phase |
| Jun 14 | `f93257f` | "added user storeis" — 82 files, 134K lines. All enriched specs created including `US-BKND-AI-015_enriched.md` (1037 lines). INDEX.md created with 47 stories, **US-BKND-AI-015 marked COMPLETE already.** | Status set before any code written |
| Jun 14 | `f93257f` | `RESEARCH_AUDIT.md` created. **GAP-8 flagged US-AI-015 as ⚠️**: "Missing: Vector index technology choice. Reranker algorithm. Embedding model. Index refresh schedule." | Warning sign — ignored |
| Jun 15 | `f6d4f1b` | "implement 17 backend AI user stories" — 115 files, 24K lines. **US-BKND-AI-015 NOT in the list of 17 stories implemented.** The `query_similar_courses` endpoint in `ai_tools.py` was built as a dependency of US-BKND-AI-023 (Chat Orchestrator), not as a standalone story implementation. INDEX updated to 44/47. | Infrastructure code (embedding, pgvector) never created |
| Jun 15 | `2406e8f` | "complete all 47 backend AI user stories (100%)" — 3 final stories. INDEX updated to 47/47 ALL COMPLETE. | US-BKND-AI-015 remains listed as COMPLETE despite ~25% implementation |
| Jun 15 | `7737eb2` | OpenAPI schema updated with 44 AI endpoints | `query_similar_courses` endpoint documented |
| Jun 15 | `07139b9` | CLAUDE.md added | No mention of RAG gaps |
| Jun 15 | `3da5ba7` | **VALIDATION_REPORT.md** created — correctly identifies "Advanced RAG: 25% — Template retrieval works; vector search stubbed" | Truth surfaces — but 4 commits AFTER "100% complete" declaration |

---

## 3. Root Cause Analysis (5-Why)

### Why #1: Why wasn't US-BKND-AI-015 fully implemented?

Because the implementation delivered only the API surface (the tool endpoint and orchestrator hook) without the underlying retrieval infrastructure (embedding models, pgvector, full-text search, PII redaction, result enrichment).

### Why #2: Why was only the API surface built?

Because US-BKND-AI-015's tool endpoint was implemented **as a dependency** of US-BKND-AI-023 (Chat Endpoint / LLM Interaction Loop), not as a standalone story. The chat orchestrator needed to be able to call `query_similar_courses` and get a response. A minimal stub (`return {"courses": [], "total_count": 0}`) satisfied that dependency. The orchestrator story was MUST priority; the RAG story was SHOULD.

**Evidence:** The `ai_tools.py` endpoint (lines 719-809) was created in the same commit that built the chat orchestrator. The orchestrator's mock handler (`chat_orchestrator.py:331-333`) returns empty results. Neither file references `SimilarCourseService`, `EmbeddingProvider`, or `SimilarCourseRepository` — the components specified in US-BKND-AI-015.

### Why #3: Why was a stub accepted as "complete"?

Because the **INDEX.md status was set at specification time, not verified against implementation.** When the enriched story specs were committed (Jun 14, `f93257f`), US-BKND-AI-015 was already marked COMPLETE in the INDEX. The status was copied forward through subsequent commits without cross-referencing against actual files on disk.

**Evidence:** The INDEX.md diff in commit `f93257f` shows the initial creation with US-BKND-AI-015 already marked COMPLETE. The story's specification has a "Definition of Done" checklist (20 items) — but none of the corresponding files (`course_embedding.py`, `similar_course_repo.py`, `similar_course_service.py`, `embedding_provider.py`) were ever created.

### Why #4: Why wasn't the gap caught during the "100% complete" declaration?

Because the **implementation was done in a single monolithic commit** (115 files, 24,627 insertions in `f6d4f1b`). With all code landing at once, there was no per-story review, no per-story test verification, and no diff that isolated what changed for US-BKND-AI-015 specifically.

Additionally, **the architecture roadmap did not allocate RAG to any delivery chunk**. The 10-chunk plan (Chunk 0 through Chunk 10) covers feature flags, tool contracts, sessions, validation, ingestion, routing, assembly, UI, refinement, and audit — but **RAG/vector search does not appear in any chunk's scope**. It was described in the architecture document (§7: RAG vs. Tools Strategy) but never assigned to a delivery phase.

### Why #5 (Root Cause): Why was RAG left out of the implementation plan?

Because the architecture treated RAG as **"production infrastructure"** (like Temporal, Kafka, Redis cache) rather than a first-class user story. The VALIDATION_REPORT explicitly categorizes the gap:

> *"Non-100% items are production infrastructure (Temporal, Kafka, vector search, Redis cache) that have MVP equivalents."*

The `query_similar_courses` tool was needed for the chat orchestrator to function (it's one of the tools the LLM can invoke), but the **quality** of its results was deferred. The MVP equivalent — keyword search returning empty or keyword-matched results — was considered sufficient to unblock the orchestrator. The three-tier retrieval strategy, embedding generation, PII redaction, and result enrichment were categorized as "production hardening" that could come later.

**This is a categorization error.** US-BKND-AI-015 was spec'd as a self-contained backend user story with 20 tasks, 26 hours of effort, and its own test scenarios. The INDEX shows it as COMPLETE. But the implementation treated it as infrastructure plumbing to be filled in later. The story-complete declaration and the infrastructure-deferred decision were never reconciled.

---

## 4. Contributing Factors

| Factor | Weight | Explanation |
|--------|--------|-------------|
| **INDEX pre-marked COMPLETE** | 🔴 High | Status set at spec time (Jun 14) before any code existed. Never verified post-implementation. |
| **Monolithic commit** | 🔴 High | 115 files in one commit. No per-story traceability. Impossible to audit story-by-story. |
| **Story implemented as dependency** | 🟡 Medium | `query_similar_courses` tool surfaced for US-BKND-AI-023 (orchestrator), not as US-BKND-AI-015 itself. |
| **SHOULD priority** | 🟡 Medium | Low priority made it easy to silently defer. A MUST story would have had more scrutiny. |
| **Architecture phase gap** | 🟡 Medium | 10-chunk roadmap has no RAG chunk. RAG strategy is documented but not scheduled. |
| **RESEARCH_AUDIT warning ignored** | 🟡 Medium | GAP-8 specifically flagged US-AI-015 as ⚠️ with missing details. No action taken. |
| **External dependencies** | 🟢 Low | pgvector, OpenAI embedding API — easy excuses to defer. But mock providers were spec'd. |
| **No per-story test runner** | 🟢 Low | 18 test suites exist but none for `similar_course_retrieval`. Would have caught the gap. |

---

## 5. What "25% Complete" Actually Means

| Story Component | Spec Status | Code Status | % |
|-----------------|-------------|-------------|---|
| Tool contract (JSON schema) | §1.3 FR-1 — full schema with filters, limits | `ai_tools.py:719-725` — reduced schema (no `filters` object) | 60% |
| API endpoint | §2.9 — dedicated `/ai/similar-courses` router | `ai_tools.py:726` — `/tools/query_similar_courses` inline | 80% |
| Tier-3 keyword search | §2.5 — `search_keyword()` with scoring, safe excerpts | `ai_tools.py:758-808` — basic ILIKE, no safe-field filtering | 50% |
| Tier-2 full-text search | §2.5 — `search_fulltext()` with ts_vector/ts_query | **Not implemented** | 0% |
| Tier-1 vector search | §2.5 — `search_vector()` with pgvector cosine similarity | **Not implemented** | 0% |
| Embedding provider | §2.7 — ABC + OpenAI + Mock factory | **Not implemented** | 0% |
| SimilarCourseService | §2.6 — tiered orchestration with fallback | **Not implemented** | 0% |
| SimilarCourseRepository | §2.5 — all 3 tiers + `enrich_results` + PII | **Not implemented** | 0% |
| CourseEmbeddingRecord model | §2.4 — ORM for `course_embeddings` table | **Not implemented** | 0% |
| Alembic migration | §2.11 — `course_embeddings` + `course_similarity_cache` DDL | **Not implemented** | 0% |
| PII redaction | §2.5 — regex for email/phone/SSN | **Not implemented** | 0% |
| Safe field excerpt extraction | §2.5 — SAFE_EXCERPT_FIELDS allowlist | **Not implemented** | 0% |
| Tone/style inference | §2.5 — `_derive_tone_notes()` heuristic | **Not implemented** | 0% |
| Result enrichment | §2.5 — template breakdown, excerpts, match summaries | **Not implemented** | 0% |
| Feature flag | §2.2 — `similar_course_retrieval` flag | **Not implemented** | 0% |
| System prompt warning | §1.3 FR-7 — RAG not authoritative for contracts | **Not implemented** | 0% |
| Orchestrator dispatch | §2.2 — wire SimilarCourseService, replace mock | Mock returns `{courses: [], total_count: 0}` | 0% |
| Tests (22 scenarios) | §6 — UT + IT + AT + ST | **Not implemented** | 0% |
| Env vars (6) | §2.10 — ENABLE_PGVECTOR, EMBEDDING_PROVIDER, etc. | **Not in .env.example** | 0% |
| Tool registry registration | §2.8 — formal registration with schema | `chat_orchestrator.py` has inline intent routing, no registry | 20% |
| **WEIGHTED AVERAGE** | | | **~25%** |

The 25% is: a basic keyword-search endpoint exists, the orchestrator recognizes the intent, and the tool name is callable. Everything else — all 6 new files, all 5 integration modifications, all 8 capability gaps, all 22 tests — is missing.

---

## 6. Corrective Actions

### Immediate (this iteration)

| # | Action | Owner | Effort |
|---|--------|-------|--------|
| CA-1 | Update INDEX.md to reflect actual status: `⚠️ PARTIAL (Tier-3 only)` | Backend | 5 min |
| CA-2 | Add `similar_course_retrieval` feature flag (default `false`) so the tool can be disabled independently | Backend | 30 min |
| CA-3 | Add the 6 missing env vars to `.env.example` with documentation | Backend | 15 min |

### Short-Term (next sprint)

| # | Action | Owner | Effort |
|---|--------|-------|--------|
| CA-4 | Implement `EmbeddingProvider` + `MockEmbeddingProvider` (T-03) — zero external dependencies | Backend | 2h |
| CA-5 | Implement `SimilarCourseRepository` with `search_fulltext` + `search_keyword` + `enrich_results` + PII redaction (T-04 + T-05) — skips Tier-1 pgvector for now | Backend | 5h |
| CA-6 | Implement `SimilarCourseService.query_similar_courses` tiered orchestration Tier-2 → Tier-3 (T-06) | Backend | 2h |
| CA-7 | Wire service into `chat_orchestrator.py`, replacing mock handler (T-08) | Backend | 1h |
| CA-8 | Create test file `tests/run_similar_course_tests.py` with 22 scenarios (T-14 to T-17) | QA/Backend | 6h |

### Process Improvements (apply to all stories)

| # | Action | Owner |
|---|--------|-------|
| CA-9 | **Per-story commit discipline:** Each story implementation in its own commit with story ID in the message. No more monolithic "17 stories" commits. | Team |
| CA-10 | **INDEX status gating:** INDEX.md status can only be set to COMPLETE when: (a) all files in the story's "Key File Paths" section exist on disk, (b) the test file exists and passes, (c) the feature flag is registered. | Tech Lead |
| CA-11 | **DoD verification script:** Create a script that reads INDEX.md, parses each story's enriched spec, checks if specified files exist, and reports discrepancies. Run before any "X stories complete" declaration. | DevOps |
| CA-12 | **RESEARCH_AUDIT action items:** Any story flagged ⚠️ in a research audit must have its gaps addressed before the story can be marked COMPLETE. | Tech Lead |
| CA-13 | **Architecture chunk alignment:** The 10-chunk delivery plan must explicitly assign every SHOULD+ story to a chunk. RAG should have been Chunk 3.5 or similar. | Architect |

---

## 7. Lessons Learned

1. **"Tool surface exists" ≠ "Story complete."** A tool name in the orchestrator is a dependency shim, not a feature. The DoD checklist in the story spec must be the gate, not the orchestrator's ability to call the tool.

2. **Status tracking must be verified against filesystem truth.** INDEX.md marked COMPLETE before any code existed. A simple `ls app/models/course_embedding.py` would have caught the gap.

3. **Monolithic commits hide gaps.** When 115 files land in one commit, per-story review is impossible. The validation report (4 commits later) was the first time anyone checked per-flow coverage.

4. **SHOULD ≠ deferred silently.** It's valid to defer lower-priority stories, but the status must say `DEFERRED` or `PARTIAL`, not `COMPLETE`. The INDEX should distinguish "implemented" from "stubbed for MVP."

5. **Research audit findings must drive action.** GAP-8 warned about US-AI-015's missing details on Jun 14. No one created a ticket, added a TODO in code, or updated the INDEX. The finding was written and forgotten.

6. **Architecture documents and delivery plans must stay in sync.** The architecture doc has excellent RAG strategy detail (§7) but the 10-chunk roadmap has no RAG chunk. Strategy without a delivery slot becomes shelfware.

---

## 8. Secondary RCA: PEND-17 — Migration Not Applied (Post-Implementation Gap)

**Date Discovered:** 2026-06-20 (during re-implementation via IMP doc)  
**Status:** ✅ Resolved (dev environment)  
**Root Cause:** IMP doc verification used code-only check instead of database verification

### 8.1 What Happened

The full US-BKND-AI-015 implementation (June 20) created all 7 new files correctly, including the Alembic migration `20260620_0001_add_course_embeddings.py`. However, the migration was **never executed** against any database. Three sub-gaps caused this:

### 8.2 5-Why — PEND-17

| # | Why | Answer | Evidence |
|---|-----|--------|----------|
| **1** | Why wasn't the migration applied? | `alembic upgrade head` was never executed | Migration file existed but `alembic current` was never run |
| **2** | Why wasn't `alembic upgrade head` executed? | No PostgreSQL was reachable in the dev environment | `DATABASE_URL=NOT SET`, `POSTGRES_HOST=NOT SET` |
| **3** | Why didn't the missing database block implementation? | IMP doc pre-flight checklist never verified DB connectivity; T-02 verification used Python import check instead of actual `alembic upgrade head` | IMP doc §0.5: git/imports/uvicorn checked — no DB check. §12.3 Verify: `Base.metadata.create_all` passes without DB |
| **4** | Why did the IMP doc use a code-only verification? | The IMP doc's "Verify T-02" block (§12.3) ran a Python snippet that imports `CourseEmbeddingRecord` and calls `Base.metadata.create_all()` — which succeeds even with no database (silent no-op) | The Python check verifies the ORM model is importable, NOT that tables exist in PostgreSQL |
| **5** | Why wasn't this caught in final verification? | Phase E (final verification) runs `run_similar_course_tests.py` which uses mocks — it never hits a real database. The migration apply step is in Phase B (T-02), and the final phase never re-verifies DB table existence. | `run_similar_course_tests.py`: all 22 tests use `AsyncMock`, `MagicMock`, `patch` — zero real DB calls |

### 8.3 Additional Gap: alembic/env.py Model Registration

| Gap | Detail |
|-----|--------|
| **What** | `alembic/env.py` imports all ORM models so `Base.metadata` knows about every table — but `import app.models.course_embedding` was missing |
| **Impact** | `alembic revision --autogenerate` would not detect `CourseEmbeddingRecord` or `CourseSimilarityCache`. Future autogenerate migrations would miss these tables even after the migration is applied. |
| **Why missed** | The IMP doc §3.2 correctly added the import to `app/main.py` (line 97) for the `create_all()` path, but never mentioned `alembic/env.py` also needs the import for the migration path |
| **Fix** | Added `import app.models.course_embedding  # noqa: F401` to `alembic/env.py` line 25 (commit: `ba8793b`) |

### 8.4 Resolution

| Step | Action | Result |
|------|--------|--------|
| 1 | Added `import app.models.course_embedding` to `alembic/env.py` | ✅ Both tables now visible to `Base.metadata` |
| 2 | Set `DATABASE_URL` to Docker PostgreSQL | ✅ Connected to `elearning-postgres:5432` |
| 3 | Ran 6-step migration lifecycle | ✅ `alembic upgrade head` → `downgrade -1` → `upgrade head` all passed |
| 4 | Verified tables exist | ✅ `course_embeddings` + `course_similarity_cache` with 8 indexes |
| 5 | Updated documentation | ✅ `US-BKND-AI-015A-IMP.md` created (532 lines), `PENDING_TASKS_REPORT.md` updated |

---

## 9. Updated Status (Post-Implementation)

| Component | Before (Jun 15) | After Implementation (Jun 20) |
|-----------|-----------------|------------------------------|
| Code (7 new + 8 modified files) | 0% | ✅ **100%** — all 15 files exist and import correctly |
| Migration file | 0% | ✅ **Created** — `20260620_0001_add_course_embeddings.py` |
| Migration applied (dev) | 0% | ✅ **Applied** — `alembic current → 20260620_0001 (head)` |
| Migration applied (QA/staging/prod) | 0% | ❌ **Pending** — part of deployment pipeline |
| `alembic/env.py` model registration | 0% | ✅ **Fixed** — `import app.models.course_embedding` added |
| Tests | 0% | ✅ **22/22 passing** — `run_similar_course_tests.py` |
| Regression | N/A | ✅ **688/688 passing across 19 suites** — zero regressions |
| Documentation | Partial (spec only) | ✅ **Complete** — IMP doc (2,991L), RCA (this doc), Pending Tasks (386L), 015A Extension (532L) |
| **Overall** | **25%** | **✅ 100% (code) / 95% (deployment)** |

---

## 10. References

- [US-BKND-AI-015 Enriched Spec](US-BKND-AI-015_enriched.md) — 1037-line story specification with full code
- [US-BKND-AI-015 Pending Items](US-BKND-AI-015-pending.md) — Detailed gap analysis
- [US-BKND-AI-015-IMP.md](US-BKND-AI-015-IMP.md) — 2,991-line standalone implementation playbook
- [US-BKND-AI-015A-IMP.md](US-BKND-AI-015A-IMP.md) — 532-line migration/database layer extension
- [INDEX.md](INDEX.md) — Shows US-BKND-AI-015 as COMPLETE in Sprint 4
- [VALIDATION_REPORT.md](../01_SystemArchitecture/VALIDATION_REPORT.md) — Re-validated: 96% → 98% compliance
- [PENDING_TASKS_REPORT.md](../01_SystemArchitecture/PENDING_TASKS_REPORT.md) — 17 pending items, PEND-17 resolved
- [RESEARCH_AUDIT.md](../RESEARCH_AUDIT.md) — GAP-8 flagged US-AI-015 as ⚠️ pre-implementation
- [PRODUCTION_READY_AI_AUTHORING_ARCHITECTURE.md](../01_SystemArchitecture/PRODUCTION_READY_AI_AUTHORING_ARCHITECTURE.md) — §7 RAG strategy, §10 phased roadmap
- Commits: `f93257f` (specs + INDEX), `f6d4f1b` (17-story impl), `2406e8f` ("100%"), `3da5ba7` (validation), `ba8793b` (015 implementation + re-validation)
