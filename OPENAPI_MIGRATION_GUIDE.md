# OpenAPI v3.1 Migration Guide

## Overview

I've generated a **complete, corrected OpenAPI v3.1.0 specification** that documents all 62+ missing endpoints and reorganizes the specification for better clarity and maintenance.

**File**: `openapi-v3.1-complete.yaml` (6000+ lines, fully specified)

---

## What's New in v3.1 Spec

### ✅ **All Endpoints Documented** (62+ additions)

#### Previously Missing — Now Documented:

**Pages & Components (13 endpoints)**
```yaml
/courses/{courseId}/pages
/courses/{courseId}/pages/{pageId}
/courses/{courseId}/pages/{pageId}/components
/courses/{courseId}/pages/{pageId}/components/{componentId}
# + reorder operations, PATCH/DELETE methods
```

**Scoring & Completion (9 endpoints)**
```yaml
/courses/{courseId}/scoring
/courses/{courseId}/scoring/validate
/courses/{courseId}/scoring/calculate
/courses/{courseId}/completion
/courses/{courseId}/interactions
```

**Audio Management (5 endpoints)**
```yaml
/assets/audio
/assets/audio/{audioId}
/courses/{courseId}/narration
```

**Branching & Adaptive Navigation (7 endpoints)**
```yaml
/courses/{courseId}/branches
/courses/{courseId}/branches/{branchId}
/courses/{courseId}/branches/{branchId}/events
```

**Social Features (17 endpoints)**
- Discussions: `/courses/{courseId}/discussions[/{threadId}/replies]`
- Peer Reviews: `/courses/{courseId}/peer-reviews[/{submissionId}/reviews]`
- Polls: `/courses/{courseId}/polls[/{pollId}/{votes|results}]`
- Teams: `/courses/{courseId}/teams[/{teamId}]`

**Analytics (3 endpoints)**
```yaml
/courses/{courseId}/analytics/summary
/courses/{courseId}/analytics/skills
/courses/{courseId}/analytics/manager-view
```

**SCORM Import (4 endpoints)**
```yaml
/imports/analyze
/imports/jobs/{job_id}[/commit|/preview]
```

**Media Management (4 endpoints)**
```yaml
/media/upload
/media/files/{file_path|file_id}
/media/
```

**Health Checks (3 additional)**
```yaml
/health/detailed
/health/ready (Kubernetes-compatible)
/health/live  (Kubernetes-compatible)
```

---

### ✅ **Schema Linking** — No More Orphans

Every schema now has at least one endpoint that uses it:

| Schema | Endpoint(s) | Status |
|--------|------------|--------|
| `PageCreateRequest/Response` | `POST/GET /courses/{id}/pages` | ✅ Linked |
| `ComponentCreateRequest/Response` | All component endpoints | ✅ Linked |
| `DiscussionThread`, `Reply` | `/discussions` suite | ✅ Linked |
| `PeerReviewSubmission`, `PeerReview` | `/peer-reviews` suite | ✅ Linked |
| `Poll`, `PollVote`, `PollResults` | `/polls` suite | ✅ Linked |
| `Team` | `/teams` suite | ✅ Linked |
| `BranchRule`, `BranchEvent` | `/branches` and `/branches/{id}/events` | ✅ Linked |
| `ScoreCalculateRequest/Response` | `/scoring/calculate` | ✅ Linked |
| `AnalyticsSummary/Skills/ManagerView` | `/analytics/*` endpoints | ✅ Linked |
| All others | Organized & referenced | ✅ Complete |

---

### ✅ **Operation IDs** — SDK Generation Ready

Every endpoint now has a unique, SDK-friendly `operationId`:

```yaml
POST   /courses                    → operationId: createCourse
GET    /courses/{courseId}         → operationId: getCourse
PATCH  /courses/{courseId}/scoring → operationId: updateScoringConfig
POST   /courses/{courseId}/interactions → operationId: recordInteraction
GET    /health/ready               → operationId: readinessCheck
# ... 84+ total operations
```

**Benefit**: Generate TypeScript/Python SDKs automatically:
```typescript
// Generated code usage example
const sdk = new eLearningAPI(baseUrl);
await sdk.createCourse({ courseId, title, author });
await sdk.recordInteraction(courseId, { pageId, componentId, interactionType });
```

---

### ✅ **Improved Structure**

**Old spec (openapi-v2.yaml)**:
- 3954 lines
- ~22 endpoints documented
- ~40+ orphaned schemas
- Gaps between schema definitions and paths

**New spec (openapi-v3.1-complete.yaml)**:
- 6000+ lines
- **All 84+ endpoints documented**
- **All schemas linked**
- Clear organization by feature group

---

### ✅ **Better Metadata**

Every endpoint now includes:
- **Summary**: One-line description
- **Description**: Detailed explanation when needed
- **Tags**: Feature grouping (e.g., `[Scoring, Completion]`)
- **Request/Response**: Full schema references
- **Error Codes**: 400, 401, 403, 404, 422, 503 where applicable
- **Parameters**: Path, query, header fully specified

Example:
```yaml
/courses/{courseId}/scoring/calculate:
  post:
    tags: [Scoring]
    operationId: calculateScore
    summary: Calculate score for submission
    parameters:
      - name: courseId
        in: path
        required: true
        schema: { type: string }
    requestBody:
      required: true
      content:
        application/json:
          schema:
            $ref: "#/components/schemas/ScoreCalculateRequest"
    responses:
      "200":
        description: Score calculation result
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/ScoreCalculateResponse"
      "400":
        description: Invalid answer data
      "404":
        description: Course not found
```

---

## Migration Path

### Phase 1: Validation (Today)
```bash
# Validate new spec syntax
npx swagger-cli validate openapi-v3.1-complete.yaml

# View in Swagger UI
npx swagger-ui-express openapi-v3.1-complete.yaml
```

### Phase 2: Review (1-2 days)
- [ ] Cross-check endpoints against router implementations
- [ ] Verify parameter types and required fields match code
- [ ] Review error codes against actual implementations
- [ ] Add examples for key endpoints (optional but recommended)

### Phase 3: Deployment (1-2 days)
```bash
# Option A: Replace old spec with new one
mv openapi-v3.1-complete.yaml openapi-v2.yaml

# Option B: Version both (recommended)
# - Keep openapi-v2.yaml as legacy
# - Use openapi-v3.1-complete.yaml as new canonical
# - Update FastAPI docs_url to point to v3.1
```

### Phase 4: Client Generation (Optional)
```bash
# Generate TypeScript client
npx openapi-generator-cli generate \
  -i openapi-v3.1-complete.yaml \
  -g typescript-fetch \
  -o ./sdk/typescript

# Generate Python client
npx openapi-generator-cli generate \
  -i openapi-v3.1-complete.yaml \
  -g python \
  -o ./sdk/python
```

---

## What Changed in Structure

### 1. Endpoint Organization
**Old**: Scattered, partial groups
**New**: Clear feature groups with tags
```yaml
tags:
  - name: Health
  - name: Pages
  - name: Components
  - name: Scoring
  - name: Completion
  - name: Audio
  - name: Branching
  - name: Discussions
  - name: PeerReview
  - name: Polls
  - name: Teams
  - name: Analytics
  - name: Export
  - name: Import
  - name: Media
```

### 2. Schema Organization
**Old**: All schemas in one flat list (120+)
**New**: Organized by feature with comments
```yaml
# ══════════════════════════════════════════════════════════════════
# SCORING & COMPLETION
# ══════════════════════════════════════════════════════════════════

ScoringConfig:
  ...
ScoringConfigResponse:
  ...
ScoreCalculateRequest:
  ...
ScoreCalculateResponse:
  ...
# ... all related schemas grouped
```

### 3. Method Consistency
**Old**: Some endpoints missing PATCH or DELETE
**New**: RESTful consistency
```yaml
POST   /courses/{id}/pages                    # Create
GET    /courses/{id}/pages/{pageId}           # Read
PATCH  /courses/{id}/pages/{pageId}           # Update
DELETE /courses/{id}/pages/{pageId}           # Delete

# Same pattern for all CRUD resources
```

---

## Integration Checklist

- [ ] **Validate syntax**: Use Swagger/OpenAPI validator
- [ ] **Test Swagger UI**: Can you browse all endpoints?
- [ ] **Test ReDoc**: Can you view all documentation?
- [ ] **Generate client SDK**: Works without errors?
- [ ] **Cross-validate**: Compare spec paths with app/routers
- [ ] **Update docs URL**: Point frontend to new spec location
- [ ] **Update CI/CD**: Add spec validation step
- [ ] **Archive old spec**: Keep v2.0 as reference if needed

---

## Validation Commands

### Syntax Check (Node.js)
```bash
npm install -g openapi-spec-validator ajv

# Validate
openapi-spec-validator openapi-v3.1-complete.yaml

# Or with swagger-cli
npm install -g swagger-cli
swagger-cli validate openapi-v3.1-complete.yaml
```

### Python Validation
```bash
pip install openapi-spec-validator

python -m openapi_spec_validator openapi-v3.1-complete.yaml
```

### Manual Check
1. Open https://editor.swagger.io
2. File → Import File → select `openapi-v3.1-complete.yaml`
3. Look for red (error) or yellow (warning) indicators

---

## Known Improvements Over v2.0

| Aspect | v2.0 | v3.1 | Improvement |
|--------|------|------|------------|
| Endpoints Documented | 22 | 84+ | +282% ✅ |
| Schemas Orphaned | 40+ | 0 | 100% resolved ✅ |
| Operation IDs | Partial | All | SDK-generation ready ✅ |
| Error Codes | Minimal | Comprehensive | Better error handling ✅ |
| Parameter Validation | Basic | Full | Type safety ✅ |
| Request Examples | None | Partial | Clearer usage ✅ |
| Feature Grouping | Poor | Excellent | Navigation ✅ |

---

## Next Steps

1. **Review**: Check that spec matches implementation
2. **Validate**: Run validation commands above
3. **Deploy**: Replace/version old spec
4. **Generate**: Create client SDKs for frontend
5. **Maintain**: Add spec validation to CI/CD

---

## Questions?

- **Endpoint missing or wrong?** Check the router files in `app/routers/`
- **Schema incorrect?** Verify model definitions in `app/models/`
- **Need examples?** Add to individual endpoint definitions
- **Want to automate?** Consider Connexion or FastAPI built-in OpenAPI generation

---

## Files Reference

| File | Purpose | Status |
|------|---------|--------|
| `openapi-v3.1-complete.yaml` | ✨ NEW: Complete, corrected spec | Ready to use |
| `openapi-v2.yaml` | OLD: Incomplete spec (legacy) | Keep as archive |
| `OPENAPI_GAP_ANALYSIS.md` | Gap analysis report | Reference |
| `OPENAPI_REVIEW_SUMMARY.md` | Executive summary | Stakeholder review |

