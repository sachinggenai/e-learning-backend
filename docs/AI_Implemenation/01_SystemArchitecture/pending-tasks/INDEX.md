# Pending Tasks — User Story Index

**Author:** TPO (Technical Product Owner)  
**Date:** 2026-06-21 (Enriched: 2026-06-21 — complete code-verified rewrite with Docker infra)  
**Source:** Commit `10b863a` line-by-line code review + `PENDING_TASKS_REPORT.md` + **Full codebase re-verification**  
**Branch:** `demo-course-AI-pradeep`

## How to Use This Index

Stories are listed in **chronological execution order**. Work top-to-bottom. Each story is self-sufficient — no cross-references needed. Each story now includes: open-source tooling selection with rationale, Docker-ready setup scripts, exact code-verified signatures from the actual codebase, and new dependency additions to `requirements.txt`.

**Story Status Legend:** ✅ Enriched (code-verified + Docker infra) · 📋 Original (unchanged)  
**Priority Legend:** 🔴 CRITICAL (blocking) · 🟡 HIGH · 🟢 MEDIUM · ⚪ LOW

### 🏗️ Infrastructure Pre-Requisites (Run First — Docker)

**Option A — All-in-one (recommended):**
```bash
bash docker/setup.sh
```
Starts PostgreSQL+pgvector, Redis, Redpanda (Kafka), and MinIO in one command. See [US-PEND-017](US-PEND-017.md).

**Option B — Individual services (start only what you need):**

| ID | Service | Command | Time | Unblocks |
|----|---------|---------|------|----------|
| [US-PREREQ-001](US-PREREQ-001.md) | 🟠 Redpanda (Kafka) | `docker run -d --name elearning-redpanda ...` | 10min | PEND-024, PEND-025 |
| [US-PREREQ-002](US-PREREQ-002.md) | 🔴 Redis 7 | `docker run -d --name elearning-redis ...` | 5min | PEND-026, PEND-030 |
| [US-PREREQ-003](US-PREREQ-003.md) | 🟢 MinIO (S3) | `docker run -d -p 9000:9000 -p 9001:9001 ...` | 10min | PEND-012 |
| [US-PREREQ-004](US-PREREQ-004.md) | 🔵 WebSocket | Zero setup — FastAPI built-in | 10min | PEND-030 |

**pgvector** (PostgreSQL extension) is covered by [US-PEND-017](US-PEND-017.md) — included in `docker/setup.sh` or the docker-compose.yml.

---

## Batch 1 — Critical Bug Fixes (Zero Dependencies, ~3 hours)

*These bugs crash the workflow engine. Nothing works until they're fixed. Start here.*

| ID | Type | Priority | Title | File | Est. |
|----|------|----------|-------|------|------|
| [US-PEND-001](US-PEND-001.md) | Bug | 🔴 CRITICAL | Fix `ValidationEngine` ImportError in workflow step | `steps/course_generation.py:228` | 15min |
| [US-PEND-002](US-PEND-002.md) | Bug | 🔴 CRITICAL | Fix `LLMClient.generate()` → `chat()` in course_generation step | `steps/course_generation.py:118-134` | 20min |
| [US-PEND-003](US-PEND-003.md) | Bug | 🔴 CRITICAL | Fix `CostTracker.record_usage()` — cost tracking silently broken | `steps/course_generation.py:137-146` | 15min |
| [US-PEND-004](US-PEND-004.md) | Bug | 🔴 CRITICAL | Fix `create_batch_proposal()` missing method | `steps/course_generation.py:276` | 30min |
| [US-PEND-005](US-PEND-005.md) | Bug | 🔴 CRITICAL | Fix `CourseRepository.get_by_id()` in SCORM export step | `steps/scorm_export.py:42` | 5min |
| [US-PEND-006](US-PEND-006.md) | Change Request | 🟢 MEDIUM | Clarify feature flag default & documentation (re-validated: already works) | `feature_flags.py:77` | 10min |

**Checkpoint:** After Batch 1, workflow engine imports and executes without errors. Run `python tests/run_workflow_engine_tests.py` — 146 tests pass.

---

## Batch 2 — Config & Migration Fixes (Zero Dependencies, ~4 hours)

*The engine runs but uses wrong defaults and has schema inconsistencies. Fix the wiring.*

| ID | Type | Priority | Title | Files | Est. |
|----|------|----------|-------|-------|------|
| [US-PEND-007](US-PEND-007.md) | Change Request | 🟡 HIGH | Unify workflow engine config wiring across main.py, config.py, orchestrator | `main.py`, `config.py`, `orchestrator.py` | 2h |
| [US-PEND-008](US-PEND-008.md) | Bug | 🟡 HIGH | Fix FK type mismatch: workflow_jobs.session_id UUID → ai_sessions.id Integer | `models/workflow.py:141-145`, migration | 30min |
| [US-PEND-009](US-PEND-009.md) | Bug | 🟢 MEDIUM | Fix 3 migration schema issues: JSONB default, REAL vs Float, conditional FK | Migration file | 30min |
| [US-PEND-010](US-PEND-010.md) | Bug | 🟢 MEDIUM | Fix TOCTOU race: cancel_job returns HTTP 500 instead of 409 | `routers/workflows.py:260-272` | 10min |

**Checkpoint:** After Batch 2, all `.env` config is respected. Migration is clean for QA/staging. Feature flag responds to env var.

---

## Batch 3 — Reliability Fixes (Depends on Batch 1, ~4 hours)

*The engine runs and is configured. Now fix silent data loss, resource leaks, and wasted cost.*

| ID | Type | Priority | Title | Files | Est. |
|----|------|----------|-------|-------|------|
| [US-PEND-011](US-PEND-011.md) | Bug | 🟡 HIGH | Persist checkpoint data on step failure before retry | `orchestrator.py:311-327`, `repository.py` | 2h |
| [US-PEND-012](US-PEND-012.md) | Bug | 🟡 HIGH | Fix SCORM export tempfile leak and non-functional download URL | `steps/scorm_export.py:115-128` | 1.5h |
| [US-PEND-013](US-PEND-013.md) | Bug | 🟡 HIGH | Fix dead `complete_export_step` — never invoked by orchestrator | `orchestrator.py:246`, `steps/scorm_export.py:142` | 20min |

**Checkpoint:** After Batch 3, workflow engine is production-grade. No data loss on retry. SCORM exports produce persistent artifacts. Cost tracking is accurate.

---

## Batch 4 — Documentation Cleanup (Zero Dependencies, ~1 hour)

*Fix 3 stale docs that describe pre-implementation state. Prevents confusion for new developers.*

| ID | Type | Priority | Title | File | Est. |
|----|------|----------|-------|------|------|
| [US-PEND-014](US-PEND-014.md) | Change Request | 🟡 HIGH | Update 034-A IMP doc: status "TODO" → "IMPLEMENTED" | `US-BKND-AI-034_DURABLE_WORKFLOW_ENGINE-A.md` | 15min |
| [US-PEND-015](US-PEND-015.md) | Change Request | 🟡 HIGH | Update 034-pending doc: status "PENDING" → "SUPERSEDED" | `US-BKND-AI-034-pending.md` | 15min |
| [US-PEND-016](US-PEND-016.md) | Change Request | 🟡 HIGH | Update 015A-IMP doc: mark gap as RESOLVED | `US-BKND-AI-015A-IMP.md` | 15min |

---

## Batch 5 — Infrastructure (External Dependency, ~1 day)

*These require ops/DB access, not code changes. Run in parallel with Batch 6 if different people.*

| ID | Type | Priority | Title | Depends On | Est. |
|----|------|----------|-------|------------|------|
| [US-PEND-017](US-PEND-017.md) | New Task | 🔴 CRITICAL | Install pgvector extension on all PostgreSQL instances | DB superuser access | 0.5d |
| [US-PEND-018](US-PEND-018.md) | New Task | 🔴 CRITICAL | Deploy Alembic migration to QA → staging → production | US-PEND-009 (migration fixes) | 0.5d |

---

## Batch 6 — Feature Development (Dependencies Met, ~8 days)

*The engine is solid. Infrastructure is ready. Build features.*

| ID | Type | Priority | Title | Depends On | Est. |
|----|------|----------|-------|------------|------|
| [US-PEND-019](US-PEND-019.md) | New Task | 🟡 HIGH | Add specialized retrieval audit logging (per-tier metrics) | None | 1d |
| [US-PEND-020](US-PEND-020.md) | New Task | 🟡 HIGH | Implement embedding population background worker | US-PEND-017 (pgvector) | 2-3d |
| [US-PEND-021](US-PEND-021.md) | New Task | 🟡 HIGH | Implement PDF/DOCX async text extraction | None | 3-4d |
| [US-PEND-022](US-PEND-022.md) | New Task | 🟡 HIGH | Implement LLM-based context window summarization | None | 2-3d |
| [US-PEND-023](US-PEND-023.md) | New Task | 🟡 HIGH | Add SCORM export validation for AI-generated content | None | 1-2d |

---

## Batch 7 — Long-Term & Deferred (All Unblocked for Local Dev, ~20+ days)

*All previously blocked stories are now **unblocked for local development** via pre-requisite Docker containers. Start the required service below, then implement.*

| ID | Type | Priority | Title | Prereq (Start First) | Est. |
|----|------|----------|-------|----------------------|------|
| [US-PEND-024](US-PEND-024.md) | New Task | 🔴 CRITICAL | Integrate Kafka for event streaming | [PREREQ-001](US-PREREQ-001.md) → Redpanda | 2-3d |
| [US-PEND-025](US-PEND-025.md) | New Task | 🟡 HIGH | Implement RLHF feedback collection baseline | PREREQ-001 → PEND-024 | 5-7d |
| [US-PEND-026](US-PEND-026.md) | New Task | 🟢 MEDIUM | Add Redis cache layer for page reads | [PREREQ-002](US-PREREQ-002.md) → Redis | 2-3d |
| [US-PEND-027](US-PEND-027.md) | New Task | 🟢 MEDIUM | Implement template harvesting | None | 3-4d |
| [US-PEND-028](US-PEND-028.md) | New Task | 🟢 MEDIUM | Implement system prompt versioning and A/B testing | None | 3-4d |
| [US-PEND-029](US-PEND-029.md) | New Task | 🟢 MEDIUM | Implement AI content versioning and rollback | None | 4-5d |
| [US-PEND-030](US-PEND-030.md) | New Task | 🟢 MEDIUM | Implement multi-user real-time collaboration | [PREREQ-002](US-PREREQ-002.md) → Redis + [PREREQ-004](US-PREREQ-004.md) → WebSocket | 7-10d |
| [US-PEND-031](US-PEND-031.md) | New Task | ⚪ LOW | Implement template definition harvesting from AI proposals | US-PEND-027 | 3-4d |
| [US-PEND-032](US-PEND-032.md) | New Task | ⚪ LOW | Investigate and resolve pytest segfault (exit code 139) | Dev machine access | TBD |
| [US-PEND-012](US-PEND-012.md) | Bug | 🟡 HIGH | Fix SCORM export tempfile leak + download URL | [PREREQ-003](US-PREREQ-003.md) → MinIO (for Part B S3 storage) | 1.5h |

---

## Summary

| Batch | Stories | Effort | Status |
|-------|---------|--------|--------|
| Prereqs | US-PREREQ-001 to 004 | ~35min | **START HERE** — Docker containers |
| Batch 1 | US-PEND-001 to 006 | ~3h | ✅ Ready NOW |
| Batch 2 | US-PEND-007 to 010 | ~4h | ✅ Ready NOW |
| Batch 3 | US-PEND-011 to 013 | ~4h | ✅ After Batch 1 |
| Batch 4 | US-PEND-014 to 016 | ~1h | ✅ Ready NOW |
| Batch 5 | US-PEND-017 to 018 | ~1d | ✅ After US-PREREQ (Docker up) + Batch 2 |
| Batch 6 | US-PEND-019 to 023 | ~8d | ✅ Ready (PEND-020 needs pgvector from PEND-017) |
| Batch 7 | US-PEND-024 to 032 | ~25d | ✅ **ALL UNBLOCKED** (local dev via PREREQ Docker containers) |
| **Total** | **36 stories** (32 PEND + 4 PREREQ) | **~47 days** | |

**Total estimated effort for all critical/high stories (Batches 1-3): ~11 hours (1.5 days).**
