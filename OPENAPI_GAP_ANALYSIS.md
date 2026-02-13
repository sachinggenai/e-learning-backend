# OpenAPI Specification Gap Analysis

## Executive Summary

The current `openapi-v2.yaml` file has comprehensive **schemas** defined but **severely incomplete endpoint documentation**. The spec defines schemas for dozens of data types but only documents 5 main path groups with ~20 endpoints, while the actual backend implements **60+ endpoints** across 15 routers.

---

## Analysis: Documented vs. Actual Endpoints

### ✅ Currently Documented Paths (5 main)
1. `/health` → 1 endpoint
2. `/courses` → ~10 endpoints (partial)
3. `/components` → ~5 endpoints (registry only)
4. `/themes` → ~8 endpoints (partial)
5. `/export` → ~5 endpoints

**Total Documented: ~22 endpoints**

### ❌ Completely Missing from OpenAPI

The following routers/features are **completely undocumented** despite being fully implemented:

#### 1. **Pages & Page Components** (`page_components.py`)
   - `POST /api/v1/courses/{courseId}/pages` — Create page
   - `GET /api/v1/courses/{courseId}/pages` — List pages
   - `GET /api/v1/courses/{courseId}/pages/{pageId}` — Get page
   - `PATCH /api/v1/courses/{courseId}/pages/{pageId}` — Update page
   - `DELETE /api/v1/courses/{courseId}/pages/{pageId}` — Delete page
   - `POST /api/v1/courses/{courseId}/pages/reorder` — Reorder pages
   - `POST /api/v1/courses/{courseId}/pages/{pageId}/components` — Add component to page
   - `GET /api/v1/courses/{courseId}/pages/{pageId}/components` — List components on page
   - `GET /api/v1/courses/{courseId}/pages/{pageId}/components/{componentId}` — Get component
   - `PATCH /api/v1/courses/{courseId}/pages/{pageId}/components/{componentId}` — Update component
   - `DELETE /api/v1/courses/{courseId}/pages/{pageId}/components/{componentId}` — Delete component
   - `POST /api/v1/courses/{courseId}/pages/{pageId}/components/reorder` — Reorder components
   - **Status: ~13 endpoints MISSING**

#### 2. **Scoring & Completion** (`scoring_completion.py`)
   - `GET /api/v1/courses/{courseId}/scoring` — Get scoring config
   - `PATCH /api/v1/courses/{courseId}/scoring` — Update scoring config
   - `POST /api/v1/courses/{courseId}/scoring/validate` — Validate scoring
   - `POST /api/v1/courses/{courseId}/scoring/calculate` — Calculate score
   - `GET /api/v1/courses/{courseId}/completion` — Get course completion
   - `GET /api/v1/courses/{courseId}/pages/{pageId}/completion` — Get page completion
   - `POST /api/v1/courses/{courseId}/pages/{pageId}/completion` — Update page completion
   - `POST /api/v1/courses/{courseId}/interactions` — Record interaction event
   - `GET /api/v1/courses/{courseId}/interactions` — Get interaction events
   - **Status: ~9 endpoints MISSING**

#### 3. **Audio Management** (`audio.py`)
   - `POST /api/v1/assets/audio` — Upload audio
   - `GET /api/v1/assets/audio/{audioId}` — Get audio metadata
   - `PATCH /api/v1/assets/audio/{audioId}` — Update audio
   - `DELETE /api/v1/assets/audio/{audioId}` — Delete audio
   - `GET /api/v1/courses/{courseId}/narration` — Get course narration info
   - **Status: ~5 endpoints MISSING**

#### 4. **Branching & Adaptive Navigation** (`branching.py`)
   - `GET /api/v1/courses/{courseId}/branches` — List branch rules
   - `POST /api/v1/courses/{courseId}/branches` — Create branch rule
   - `GET /api/v1/courses/{courseId}/branches/{branchId}` — Get branch rule
   - `PATCH /api/v1/courses/{courseId}/branches/{branchId}` — Update branch rule
   - `DELETE /api/v1/courses/{courseId}/branches/{branchId}` — Delete branch rule
   - `POST /api/v1/courses/{courseId}/branches/{branchId}/events` — Record branch event
   - `GET /api/v1/courses/{courseId}/branches/{branchId}/events` — Get branch events
   - **Status: ~7 endpoints MISSING**

#### 5. **Social & Collaborative Features** (`social.py`)
   - **Discussions:**
     - `GET /api/v1/courses/{courseId}/discussions` — List discussions
     - `POST /api/v1/courses/{courseId}/discussions` — Create discussion
     - `GET /api/v1/courses/{courseId}/discussions/{threadId}` — Get discussion thread
     - `POST /api/v1/courses/{courseId}/discussions/{threadId}/replies` — Add reply
   - **Peer Reviews:**
     - `GET /api/v1/courses/{courseId}/peer-reviews` — List submissions
     - `POST /api/v1/courses/{courseId}/peer-reviews` — Submit for review
     - `GET /api/v1/courses/{courseId}/peer-reviews/{submissionId}` — Get submission
     - `POST /api/v1/courses/{courseId}/peer-reviews/{submissionId}/reviews` — Add review
   - **Polls:**
     - `GET /api/v1/courses/{courseId}/polls` — List polls
     - `POST /api/v1/courses/{courseId}/polls` — Create poll
     - `POST /api/v1/courses/{courseId}/polls/{pollId}/votes` — Vote on poll
     - `GET /api/v1/courses/{courseId}/polls/{pollId}/results` — Get poll results
   - **Teams:**
     - `GET /api/v1/courses/{courseId}/teams` — List teams
     - `POST /api/v1/courses/{courseId}/teams` — Create team
     - `GET /api/v1/courses/{courseId}/teams/{teamId}` — Get team
     - `PATCH /api/v1/courses/{courseId}/teams/{teamId}` — Update team
     - `DELETE /api/v1/courses/{courseId}/teams/{teamId}` — Delete team
   - **Status: ~17 endpoints MISSING**

#### 6. **Analytics** (`analytics.py`)
   - `GET /api/v1/courses/{courseId}/analytics/summary` — Get analytics summary
   - `GET /api/v1/courses/{courseId}/analytics/skills` — Get skills breakdown
   - `GET /api/v1/courses/{courseId}/analytics/manager-view` — Get manager analytics view
   - **Status: ~3 endpoints MISSING**

#### 7. **SCORM Import/Migration** (`imports.py`)
   - `POST /api/v1/imports/analyze` — Analyze SCORM package
   - `GET /api/v1/imports/jobs/{job_id}` — Get import job status
   - `POST /api/v1/imports/jobs/{job_id}/commit` — Commit import
   - `GET /api/v1/imports/jobs/{job_id}/preview` — Preview import
   - **Status: ~4 endpoints MISSING**

#### 8. **Enhanced Template System** (`enhanced_templates.py`)
   - `GET /api/v1/templates/enhanced/categories` — Get template categories
   - **Status: ~1 endpoint partially documented**

#### 9. **Legacy Templates** (`templates.py`)
   - Routed under `/api/v1/courses/{course_id}/templates`
   - Multiple CRUD operations for legacy template support
   - **Status: ~6 endpoints MISSING**

#### 10. **Media Management** (`media.py`)
   - `POST /api/v1/media/upload` — Upload media file
   - `GET /api/v1/media/files/{file_path}` — Serve media file
   - `DELETE /api/v1/media/files/{file_id}` — Delete media file
   - `GET /api/v1/media/` — List media files
   - **Status: ~4 endpoints MISSING**

#### 11. **Health Checks** (`health.py`)
   - Only documents 1 of 4 endpoints:
   - `GET /health/detailed` — Missing
   - `GET /health/ready` — Missing
   - `GET /health/live` — Missing
   - **Status: ~3 endpoints MISSING**

---

## Schemas: Present but Orphaned

The OpenAPI spec defines **comprehensive schemas** for many features:

✅ **Present but not linked to endpoints:**
- `PageCreateRequest`, `PageUpdateRequest`, `PageResponse`
- `ComponentCreateRequest`, `ComponentUpdateRequest`, `ComponentResponse`
- `DiscussionThread`, `DiscussionReply`, `PeerReview`, `Poll`, `Team`
- `BranchRule`, `BranchEvent`
- `AudioAsset`, `InteractionEvent`
- `ScoringConfig`, `ComponentScoreConfig`
- `AnalyticsSummary`, `AnalyticsSkills`
- `CourseNarrationResponse`

These schemas exist but have **no corresponding endpoint documentation**, making the OpenAPI spec misleading (it suggests features are documented when they aren't).

---

## Count Summary

| Category | Count | Status |
|----------|-------|--------|
| Documented Endpoints | ~22 | ✅ Exist |
| Missing Endpoints | ~62 | ❌ Not in OpenAPI |
| Schemas Defined | ~120 | ✅ Exist |
| Schemas Orphaned (no endpoints) | ~40+ | ⚠️ Misleading |
| **Total Implementation Gap** | **~65-75%** | **CRITICAL** |

---

## Root Causes

1. **Partial Spec Maintenance**: The schema section was updated during late-phase development but endpoint docs were never added.
2. **No Automation**: OpenAPI doesn't auto-generate from FastAPI introspection; it requires manual maintenance.
3. **Multiple Router Prefixes**: Endpoints spread across 15 routers with varying prefixes makes bulk updates complex.
4. **Legacy vs. New Architecture**: Mix of old template system, new page/component system, and new features (branching, social) complicates documentation.

---

## Recommendations

### Phase 1 (Critical)
1. **Document all implemented endpoints** with proper request/response schemas
2. **Link orphaned schemas** to actual endpoints
3. **Add missing operation IDs** (`operationId` in OpenAPI for client SDK generation)
4. **Include parameter validation** (path params, query params, headers)

### Phase 2 (Recommended)
5. **Add examples** for each endpoint (request/response bodies)
6. **Document error responses** (400, 401, 403, 404, 500 codes)
7. **Add security schemes** for auth endpoints
8. **Versioning strategy** (document breaking changes explicitly)

### Phase 3 (Best Practice)
9. **Setup FastAPI OpenAPI auto-gen** where possible (reduce manual maintenance)
10. **Generate client SDKs** from corrected spec
11. **Add webhook/event documentation** for async operations
12. **Create API versioning** strategy document

---

## File References

- **Current OpenAPI**: `openapi-v2.yaml` (0-3954 lines, incomplete)
- **Main App**: `app/main.py` (15 routers included)
- **Routers Directory**: `app/routers/` (15 router files)
- **Models**: `app/models/` (Pydantic + ORM models)

---

## Next Steps

1. Extract all endpoint signatures from routers
2. Map each endpoint to appropriate schema
3. Generate corrected OpenAPI v3.1.0 spec (replacing v2.0)
4. Add comprehensive examples and error documentation
5. Validate with Swagger/ReDoc
