# US-PEND-019: Add Specialized Retrieval Audit Logging — FULLY ENRICHED

| Field | Value |
|-------|-------|
| **Type** | 🆕 New Task (Feature) |
| **Priority** | 🟡 HIGH |
| **Batch** | 6 — Feature Development |
| **Depends On** | None |
| **Estimated Effort** | 1 day |
| **Target Files** | `app/services/ai/similar_course_service.py`, `app/services/ai/audit_service.py`, `app/repositories/ai_audit_repo.py` |

---

## User Story

**As a** product manager evaluating AI retrieval quality,
**I want** per-tier metrics in the audit log (which tier was used, result count, latency),
**So that** I can measure whether Tier-1 pgvector search improves quality over Tier-2 keyword fallback.

---

## Current State (Code Verified 2026-06-21)

- `similar_course_service.py:45` — `SimilarCourseService` class with 3-tier retrieval (Tier-1: pgvector, Tier-2: fulltext, Tier-3: keyword)
- `similar_course_service.py:96` — Feature-flagged via `FEATURE_SIMILAR_COURSE_RETRIEVAL`
- `similar_course_service.py:136` — Tier 1: `embedding_provider.embed(query)` + `search_vector`
- `similar_course_service.py:148` — Tier 2: `search_fulltext`
- `similar_course_service.py:159` — Tier 3: `search_keyword`
- **No specialized audit logging exists** — only generic `tool.query_similar_courses` via ToolExecutor
- **No per-tier metrics** — which tier, result count, embedding latency, query hash
- **Audit service exists** at `app/services/ai/audit_service.py` — `AIAuditService` class
- **Audit model exists** at `app/models/ai_models.py:271` — `AIAuditLogRecord`

---

## Enriched Implementation

### Step 1: Add audit action constants

In `app/services/ai/audit_service.py`, add:

```python
# New audit action types for retrieval
ACTION_SIMILAR_COURSE_RETRIEVAL = "similar_course.retrieval"
ACTION_SIMILAR_COURSE_TIER_FALLBACK = "similar_course.tier_fallback"
```

### Step 2: Add `log_retrieval()` method to `AIAuditService`

```python
# In app/services/ai/audit_service.py — AIAuditService class
async def log_retrieval(
    self,
    session_id: str,
    user_id: str,
    query_text: str,
    tier_used: int,            # 1, 2, or 3
    result_count: int,
    tier1_latency_ms: float = 0.0,
    tier2_latency_ms: float = 0.0,
    tier3_latency_ms: float = 0.0,
    embedding_model: str = "",
    query_hash: str = "",
    fallback_reason: str = "",
) -> None:
    """Log a retrieval event with per-tier metrics."""
    import hashlib
    if not query_hash:
        query_hash = hashlib.sha256(query_text.encode()).hexdigest()[:16]

    await self._log(
        action=ACTION_SIMILAR_COURSE_RETRIEVAL,
        session_id=session_id,
        user_id=user_id,
        details={
            "tier_used": tier_used,
            "result_count": result_count,
            "query_hash": query_hash,
            "embedding_model": embedding_model,
            "latency": {
                "tier1_ms": tier1_latency_ms,
                "tier2_ms": tier2_latency_ms,
                "tier3_ms": tier3_latency_ms,
            },
            "fallback_reason": fallback_reason,
        },
    )
```

### Step 3: Modify `SimilarCourseService.find_similar()` to log per-tier

In `app/services/ai/similar_course_service.py`, after each retrieval attempt:

```python
# In SimilarCourseService.find_similar() — after Tier 1 attempt:
import time

tier_used = 0
tier1_ms = 0.0
tier2_ms = 0.0
tier3_ms = 0.0

# Tier 1: Vector search
t0 = time.perf_counter()
if _pgvector_available():
    try:
        vector = self.embedding_provider.embed(query)
        results = await self.repo.search_vector(vector, limit=limit)
        tier1_ms = (time.perf_counter() - t0) * 1000
        if results:
            tier_used = 1
    except Exception as e:
        logger.warning("Tier-1 failed: %s", e)

# Tier 2: Full-text
if tier_used == 0:
    t0 = time.perf_counter()
    results = await self.repo.search_fulltext(query, limit=limit)
    tier2_ms = (time.perf_counter() - t0) * 1000
    if results:
        tier_used = 2

# Tier 3: Keyword fallback
if tier_used == 0:
    t0 = time.perf_counter()
    results = await self.repo.search_keyword(query, limit=limit)
    tier3_ms = (time.perf_counter() - t0) * 1000
    tier_used = 3

# ── AUDIT: Log retrieval event ─────────────────────
await self.audit.log_retrieval(
    session_id=session_id,
    user_id=user_id,
    query_text=query,
    tier_used=tier_used,
    result_count=len(results),
    tier1_latency_ms=tier1_ms,
    tier2_latency_ms=tier2_ms,
    tier3_latency_ms=tier3_ms,
    embedding_model=self.embedding_provider.model_name if tier_used == 1 else "",
    fallback_reason="no_results" if tier_used > 1 else "",
)
```

---

## 🔧 Open-Source Tooling

**No new libraries needed.** Uses only:
- `hashlib` (Python stdlib) — SHA-256 query hashing
- `time.perf_counter()` (Python stdlib) — high-resolution latency measurement
- Existing `AIAuditService` — already wired with DB session

---

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | Each retrieval produces an audit log entry with `tier_used` field | Query `ai_audit_log` for `action='similar_course.retrieval'` |
| AC-2 | Admin audit endpoint filters by retrieval action type | `GET /api/v1/admin/ai/audit?action=similar_course.retrieval` |
| AC-3 | Tier 1, 2, and 3 clearly distinguishable | `tier_used` ∈ {1, 2, 3} |
| AC-4 | Timing data recorded in milliseconds | `latency.tier1_ms`, `tier2_ms`, `tier3_ms` |
| AC-5 | Query hash enables dedup analysis | `query_hash` is SHA-256 prefix |

---

## Validation

```bash
# 1. Verify new audit action constants exist
grep -n "ACTION_SIMILAR_COURSE" app/services/ai/audit_service.py

# 2. Verify log_retrieval method exists
grep -n "log_retrieval" app/services/ai/audit_service.py

# 3. Verify timing in similar_course_service.py
grep -n "perf_counter\|tier.*_ms\|log_retrieval" app/services/ai/similar_course_service.py

# 4. Run existing tests
python tests/run_similar_course_tests.py
```
