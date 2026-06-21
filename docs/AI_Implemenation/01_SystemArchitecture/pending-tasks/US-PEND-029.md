# US-PEND-029: AI Content Versioning — deepdiff SIZE GUARD FIXED

| Field | Value |
|-------|-------|
| **Type** | 🆕 New Task (Feature) |
| **Priority** | 🟢 MEDIUM |
| **Batch** | 7 — Long-Term / Deferred |
| **Depends On** | None |
| **Estimated Effort** | 4-5 days |
| **Target Files** | New: `app/models/ai_content_version.py`, `app/repositories/ai_content_version_repo.py`. Modify: `app/services/ai/proposal_service.py` |

---

## ⚠️ SIZE GUARD ADDED

`deepdiff.DeepDiff()` has O(n²) worst-case performance for deeply nested dicts. AI-generated page content can be 50KB+ with nested components. Added a size guard: if content exceeds `MAX_DIFF_SIZE` (100KB), skip diff computation and store full snapshot only.

---

## User Story

**As a** course author who applied an AI proposal and regrets it,
**I want** to see previous versions of my content and roll back to any version,
**So that** I can experiment with AI suggestions knowing I can always undo.

---

## Enriched Implementation (Key Changes from Original)

### Add size guard constant:

```python
MAX_DIFF_SIZE = 100_000  # 100KB — compute diff only for content below this size
```

### Modified `create_version()` with size guard:

```python
async def create_version(self, resource_type, resource_id, course_id,
                         content, created_by_user_id, proposal_id=None,
                         change_summary=""):
    previous = await self.get_latest(resource_type, resource_id)
    diff = None

    if previous and previous.content_snapshot:
        # SIZE GUARD: skip diff for large content (>100KB)
        content_json = json.dumps(content, default=str)
        prev_json = json.dumps(previous.content_snapshot, default=str)

        if len(content_json) < MAX_DIFF_SIZE and len(prev_json) < MAX_DIFF_SIZE:
            try:
                diff = DeepDiff(
                    previous.content_snapshot, content, verbose_level=2
                ).to_dict()
            except Exception:
                logger.warning("DeepDiff failed for %s/%s — storing full snapshot",
                             resource_type, resource_id)
                diff = None  # Fall back to full snapshot

    # Get next version number
    stmt = select(func.max(AIContentVersion.version_number)).where(...)
    result = await self.session.execute(stmt)
    max_ver = result.scalar() or 0

    version = AIContentVersion(
        version_id=str(uuid.uuid4()),
        resource_type=resource_type,
        resource_id=resource_id,
        course_id=course_id,
        version_number=max_ver + 1,
        content_snapshot=content,  # Always store full snapshot (for rollback)
        content_diff=diff,          # Optional diff (for space efficiency)
        proposal_id=proposal_id,
        created_by_user_id=created_by_user_id,
        change_summary=change_summary,
    )
    self.session.add(version)
    await self.session.commit()
    await self._enforce_retention(resource_type, resource_id)
    return version
```

(Full model and repository code remains as in original enriched doc.)

---

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | Every applied proposal creates a version snapshot | `SELECT COUNT(*) FROM ai_content_versions` after apply |
| AC-2 | Version history queryable | `GET /api/v1/pages/{id}/versions` |
| AC-3 | Rollback restores exact previous content | Rollback from v5→v2 restores v2 content as new v6 |
| AC-4 | **Large content (>100KB) skips diff, stores full snapshot only** | `content_diff` is NULL for large content |
| AC-5 | Max 50 versions per resource | Create 55 versions → oldest 5 auto-deleted |

---

## Validation

```bash
pip install deepdiff>=7.0.0
PYTHONPATH=. alembic revision --autogenerate -m "add_ai_content_versions"
PYTHONPATH=. alembic upgrade head
python tests/run_final_stories_tests.py
```
