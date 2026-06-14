# US-AI-022: Build End-to-End Regression and Release Readiness Tests

**Status:** Draft
**Priority:** MUST (MVP Gate)
**Depends on:** US-AI-014, US-AI-019, US-AI-020, US-AI-021
**Source flows:** Platform Runtime and Operations Flow, Full Course from Uploaded File Flow
**Epic Owner:** Technical Product Owner

---

## 1. Functional Specification

### 1.1 User Story

As a **Release Engineer / QA Lead**, I want a comprehensive, fully automated end-to-end regression test suite that exercises every public API endpoint, every critical business flow (CRUD courses, pages, components, templates, import/export, SCORM packaging, theme resolution, branching, scoring, analytics, social, audio, validation), and every known negative/edge-case path, so that I can certify a release candidate as production-ready with a single `pytest` invocation in under 5 minutes.

### 1.2 Overview

This user story delivers a structured, layered test suite spanning five concentric rings of quality assurance:

1. **Layer 0 -- Unit Tests** (existing, to be catalogued): validate individual functions, validators, and Pydantic models in isolation.
2. **Layer 1 -- Repository Tests**: validate each repository's CRUD operations directly against an in-memory SQLite database without HTTP.
3. **Layer 2 -- API Contract Tests**: validate every REST endpoint's schema, status codes, error shapes, and response fields against the OpenAPI spec.
4. **Layer 3 -- Business Flow Integration Tests**: validate multi-step scenarios (create course -> add pages -> add components -> configure theme -> export SCORM -> verify ZIP) across the full FastAPI stack.
5. **Layer 4 -- Release Readiness Smoke Tests**: validate the live production-like environment (Docker container, PostgreSQL, deployment health checks) before sign-off.

All test artifacts live in `tests/`. Test coverage is measured and gated at >=85% line coverage for the `app/routers/`, `app/services/`, and `app/repositories/` packages individually.

### 1.3 Actors

| Actor | Role |
|---|---|
| QA Engineer | Runs the release readiness suite, triages failures, certifies the release candidate |
| Release Engineer | Configures CI/CD pipeline to gate deployments on test pass; monitors coverage trends |
| Developer | Runs individual layer tests during development; adds tests alongside every new feature |
| CI/CD Pipeline (GitHub Actions) | Executes `pytest --cov=app tests/` on every push to `main`/`develop` and every PR |

### 1.4 Scope: API Map (Complete)

Every route below must have at least one happy-path and one negative-path test. All route definitions are sourced from `app/routers/*.py`.

#### 1.4.1 Courses (`app/routers/courses.py`)

| Method | Route | Happy | Negative |
|---|---|---|---|
| POST | `/api/v1/courses` | 201 with CourseOut | 400 duplicate courseId, 422 missing title |
| GET | `/api/v1/courses` | 200 with `List[CourseOut]` | Empty list when no courses |
| GET | `/api/v1/courses/{courseId}` | 200 with CourseOut + pages[] | 404 non-existent courseId |
| PATCH | `/api/v1/courses/{courseId}` | 200 with updated fields | 422 invalid status, 404 missing course |
| PUT | `/api/v1/courses/{courseId}` | 201 (new) / 200 (update) | 422 missing required fields |
| DELETE | `/api/v1/courses/{courseId}` | 204 No Content | 404 missing course |
| POST | `/api/v1/courses/validate` | 200 with ValidationResult | 422 malformed payload |
| GET | `/api/v1/courses/{courseId}/pages` | 200 with `List[PageDTO]` | 404 missing course |
| POST | `/api/v1/courses/{courseId}/pages/from-template` | 201 with PageFromTemplateResponse | 404 missing template, 404 missing course |
| GET | `/api/v1/courses/templates/available` | 200 with template list | Empty list when none available |

#### 1.4.2 Templates (`app/routers/templates.py`)

| Method | Route | Happy | Negative |
|---|---|---|---|
| GET | `/api/v1/courses/{courseId}/templates` | 200 with `List[TemplateOut]` | 404 missing course |
| POST | `/api/v1/courses/{courseId}/templates` | 201 | 409 duplicate templateId |
| GET | `/api/v1/courses/{courseId}/templates/{templateId}` | 200 | 404 |
| PATCH | `/api/v1/courses/{courseId}/templates/{templateId}` | 200 | 404 |
| DELETE | `/api/v1/courses/{courseId}/templates/{templateId}` | 204 | 404 |
| POST | `/api/v1/courses/{courseId}/templates/reorder` | 200 with reordered list | 422 mismatched ids |

#### 1.4.3 Pages & Components (`app/routers/page_components.py`)

| Method | Route | Happy | Negative |
|---|---|---|---|
| POST | `/api/v1/courses/{courseId}/pages` | 201 with PageDTO | 404 missing course |
| POST | `/api/v1/courses/{courseId}/pages/reorder` | 200 | 422 invalid order |
| GET | `/api/v1/courses/{courseId}/pages/{pageId}` | 200 with PageDTO + components | 404 |
| PATCH | `/api/v1/courses/{courseId}/pages/{pageId}` | 200 | 404 |
| DELETE | `/api/v1/courses/{courseId}/pages/{pageId}` | 204 | 404 |
| POST | `/api/v1/courses/{courseId}/pages/{pageId}/components` | 201 | 404 missing page |
| POST | `/api/v1/courses/{courseId}/pages/{pageId}/components/reorder` | 200 | 422 |
| GET | `/api/v1/courses/{courseId}/pages/{pageId}/components/{componentId}` | 200 | 404 |
| PATCH | `/api/v1/courses/{courseId}/pages/{pageId}/components/{componentId}` | 200 | 404 |
| DELETE | `/api/v1/courses/{courseId}/pages/{pageId}/components/{componentId}` | 204 | 404 |

#### 1.4.4 Export (`app/routers/export.py`)

| Method | Route | Happy | Negative |
|---|---|---|---|
| POST | `/api/v1/export` | 200 StreamingResponse (ZIP) | 422 invalid course JSON |
| POST | `/api/v1/export/validate` | 200 with validation report | 422 |
| POST | `/api/v1/export/scorm/{courseId}` | 200 StreamingResponse (ZIP) | 404, 422 no pages |
| GET | `/api/v1/export/formats` | 200 | N/A |
| GET | `/api/v1/export/status/{exportId}` | 200 | 404 |

#### 1.4.5 Imports (`app/routers/imports.py`)

| Method | Route | Happy | Negative |
|---|---|---|---|
| POST | `/api/v1/imports/analyze` | 200 with ImportAnalysisResponse | 400 non-zip file |
| GET | `/api/v1/imports/jobs/{job_id}` | 200 with ImportStatusResponse | 404 |
| POST | `/api/v1/imports/jobs/{job_id}/commit` | 200 with ImportCommitResponse | 400 non-existent job |
| GET | `/api/v1/imports/jobs/{job_id}/preview` | 200 | 404 |

#### 1.4.6 Health (`app/routers/health.py`)

| Method | Route | Happy | Negative |
|---|---|---|---|
| GET | `/api/v1/health` | 200 with HealthCheckResponse | N/A |
| GET | `/api/v1/health/detailed` | 200 with component details | N/A |
| GET | `/api/v1/health/ready` | 200 | 503 |
| GET | `/api/v1/health/live` | 200 | N/A |

#### 1.4.7 Component Registry (`app/routers/component_registry.py`)

| Method | Route | Happy | Negative |
|---|---|---|---|
| GET | `/api/v1/components` | 200 with paginated type list | Empty list with bad category |
| GET | `/api/v1/components/categories` | 200 | N/A |
| GET | `/api/v1/components/categories/{categoryId}` | 200 | 404 |
| GET | `/api/v1/components/search` | 200 | Empty results for nonsense query |
| GET | `/api/v1/components/{typeId}` | 200 with schema + etag | 404 |

#### 1.4.8 Themes (`app/routers/themes.py`)

| Method | Route | Happy | Negative |
|---|---|---|---|
| GET | `/api/v1/themes` | 200 | N/A |
| POST | `/api/v1/themes` | 201 | 422 invalid payload |
| GET | `/api/v1/themes/presets` | 200 with defaults | N/A |
| GET | `/api/v1/themes/{themeId}` | 200 | 404 |
| PATCH | `/api/v1/themes/{themeId}` | 200 | 404 |
| DELETE | `/api/v1/themes/{themeId}` | 204 | 404 |
| GET | `/api/v1/courses/{courseId}/theme` | 200 | 404 |
| PATCH | `/api/v1/courses/{courseId}/theme` | 200 | 404 |
| GET | `/api/v1/courses/{courseId}/pages/{pageId}/theme` | 200 | 404 |
| PATCH | `/api/v1/courses/{courseId}/pages/{pageId}/theme` | 200 | 404 |

#### 1.4.9 Scoring & Completion (`app/routers/scoring_completion.py`)

| Method | Route | Happy | Negative |
|---|---|---|---|
| GET | `/api/v1/courses/{courseId}/scoring` | 200 | 404 |
| PATCH | `/api/v1/courses/{courseId}/scoring` | 200 | 404 |
| POST | `/api/v1/courses/{courseId}/scoring/validate` | 200 | 404 |
| POST | `/api/v1/courses/{courseId}/scoring/calculate` | 200 with score | 404, 422 wrong answer shape |
| GET | `/api/v1/courses/{courseId}/completion` | 200 | 404 |
| GET | `/api/v1/courses/{courseId}/pages/{pageId}/completion` | 200 | 404 |
| POST | `/api/v1/courses/{courseId}/pages/{pageId}/completion` | 200 | 404 |
| POST | `/api/v1/courses/{courseId}/interactions` | 200 | 404 |

#### 1.4.10 Branching (`app/routers/branching.py`)

| Method | Route | Happy | Negative |
|---|---|---|---|
| GET | `/api/v1/courses/{courseId}/branches` | 200 | 404 |
| POST | `/api/v1/courses/{courseId}/branches` | 201 | 422 |
| GET | `/api/v1/courses/{courseId}/branches/{branchId}` | 200 | 404 |
| PATCH | `/api/v1/courses/{courseId}/branches/{branchId}` | 200 | 404 |
| DELETE | `/api/v1/courses/{courseId}/branches/{branchId}` | 204 | 404 |
| POST | `/api/v1/courses/{courseId}/branches/{branchId}/events` | 201 | 404 |
| GET | `/api/v1/courses/{courseId}/branches/{branchId}/events` | 200 | 404 |

#### 1.4.11 Analytics (`app/routers/analytics.py`)

| Method | Route | Happy | Negative |
|---|---|---|---|
| GET | `/api/v1/courses/{courseId}/analytics/summary` | 200 | 404 |
| GET | `/api/v1/courses/{courseId}/analytics/skills` | 200 | 404 |
| GET | `/api/v1/courses/{courseId}/analytics/manager-view` | 200 | 404 |

#### 1.4.12 Social (`app/routers/social.py`)

| Method | Route | Happy | Negative |
|---|---|---|---|
| POST | `/api/v1/courses/{courseId}/discussions` | 201 | 422 |
| GET | `/api/v1/courses/{courseId}/discussions` | 200 | 404 |
| GET | `/api/v1/courses/{courseId}/discussions/{threadId}` | 200 | 404 |
| PATCH | `/api/v1/courses/{courseId}/discussions/{threadId}` | 200 | 404 |
| DELETE | `/api/v1/courses/{courseId}/discussions/{threadId}` | 204 | 404 |
| POST | `/api/v1/courses/{courseId}/discussions/{threadId}/replies` | 201 | 404 |
| GET | `/api/v1/courses/{courseId}/discussions/{threadId}/replies` | 200 | 404 |
| POST | `/api/v1/courses/{courseId}/reviews` | 201 | 422 |
| GET | `/api/v1/courses/{courseId}/reviews` | 200 | 404 |
| POST | `/api/v1/courses/{courseId}/polls` | 201 | 422 |
| POST | `/api/v1/courses/{courseId}/polls/{pollId}/vote` | 200 | 404 duplicate vote |
| GET | `/api/v1/courses/{courseId}/polls/{pollId}/results` | 200 | 404 |
| POST | `/api/v1/courses/{courseId}/challenges` | 201 | 422 |
| GET | `/api/v1/courses/{courseId}/challenges/{challengeId}/leaderboard` | 200 | 404 |

#### 1.4.13 Media (`app/routers/media.py`)

| Method | Route | Happy | Negative |
|---|---|---|---|
| POST | `/api/v1/media/upload` | 201 with file metadata | 413 oversized, 415 unsupported type |
| GET | `/api/v1/media/files/{fileId}` | 200 FileResponse | 404 |
| DELETE | `/api/v1/media/files/{fileId}` | 204 | 404 |

#### 1.4.14 Audio (`app/routers/audio.py`)

| Method | Route | Happy | Negative |
|---|---|---|---|
| POST | `/api/v1/assets/audio` | 201 | 415 bad mime, 413 oversized |
| GET | `/api/v1/assets/audio/{audioId}` | 200 | 404 |
| PATCH | `/api/v1/assets/audio/{audioId}` | 200 | 404 |
| DELETE | `/api/v1/assets/audio/{audioId}` | 204 | 404 |
| GET | `/api/v1/courses/{courseId}/narration` | 200 | 404 |

### 1.5 Critical Business Flows (Multi-Step Integration Tests)

Each flow is a single test function producing a pass/fail result. Each asserts HTTP status codes, response body shapes, and post-condition database state.

**Flow F1: Full Course CRUD + SCORM Export**
1. POST `/api/v1/courses` with minimal payload -> 201, courseId returned.
2. POST `/api/v1/courses/{courseId}/pages` with title -> 201, pageId returned.
3. POST `/api/v1/courses/{courseId}/pages/{pageId}/components` with `componentType: "content-text"` -> 201, componentId returned.
4. POST `/api/v1/courses/{courseId}/pages/{pageId}/components` with `componentType: "mcq"`, questions -> 201.
5. GET `/api/v1/courses/{courseId}` -> 200, verify `pages[].components[].componentType`.
6. POST `/api/v1/export/scorm/{courseId}` -> 200, verify `Content-Type: application/zip`, verify ZIP contains `imsmanifest.xml` and `index.html`.
7. PATCH `/api/v1/courses/{courseId}` with title update -> 200, verify title changed.
8. DELETE `/api/v1/courses/{courseId}` -> 204.
9. GET `/api/v1/courses/{courseId}` -> 404 (confirm deletion).

**Flow F2: Template Register, Validate, and Render**
1. GET `/api/v1/components` -> 200, verify paginated type list.
2. GET `/api/v1/components/categories` -> 200, verify category metadata.
3. GET `/api/v1/components/{typeId}` for a known type -> 200, verify `schema`, `schemaVersion`, `etag`.
4. POST `/api/v1/courses/{courseId}/templates` with valid payload -> 201.
5. GET `/api/v1/courses/{courseId}/templates` -> 200, verify list includes the new template.
6. PATCH `/api/v1/courses/{courseId}/templates/{templateId}` -> 200, verify update.
7. POST `/api/v1/courses/{courseId}/templates/reorder` -> 200, verify order changed.
8. DELETE `/api/v1/courses/{courseId}/templates/{templateId}` -> 204.

**Flow F3: Theme Cascade Resolution**
1. POST `/api/v1/themes` with custom theme -> 201, themeId returned.
2. PATCH `/api/v1/courses/{courseId}/theme` to set `themeId` + overrides -> 200.
3. GET `/api/v1/courses/{courseId}/theme` -> 200, verify merged theme (preset base + overrides).
4. PATCH `/api/v1/courses/{courseId}/pages/{pageId}/theme` with page-level overrides -> 200.
5. GET `/api/v1/courses/{courseId}/pages/{pageId}/theme` -> 200, verify page-level merge.
6. POST `/api/v1/export/scorm/{courseId}` -> 200, verify ZIP contains CSS with resolved theme tokens.

**Flow F4: Scoring, Completion, and Analytics**
1. POST `/api/v1/courses/{courseId}/scoring/calculate` with correct answers -> 200, verify score > 0.
2. POST `/api/v1/courses/{courseId}/scoring/calculate` with all wrong answers -> 200, verify score = 0.
3. POST `/api/v1/courses/{courseId}/pages/{pageId}/completion` with `completed: true` -> 200.
4. GET `/api/v1/courses/{courseId}/analytics/summary` -> 200, verify metrics include scores/completion.
5. GET `/api/v1/courses/{courseId}/analytics/skills` -> 200, verify skill breakdowns.
6. GET `/api/v1/courses/{courseId}/analytics/manager-view` -> 200, verify aggregate view.

**Flow F5: Branching Rules with Events**
1. POST `/api/v1/courses/{courseId}/branches` with conditions and target -> 201, branchId.
2. GET `/api/v1/courses/{courseId}/branches` -> 200, verify list includes branch.
3. PATCH `/api/v1/courses/{courseId}/branches/{branchId}` to adjust priority -> 200.
4. POST `/api/v1/courses/{courseId}/branches/{branchId}/events` with learner decision -> 201.
5. GET `/api/v1/courses/{courseId}/branches/{branchId}/events` -> 200, verify event logged.
6. DELETE `/api/v1/courses/{courseId}/branches/{branchId}` -> 204.

**Flow F6: Import Analyze -> Preview -> Commit**
1. Prepare minimal valid SCORM ZIP with imsmanifest.xml and course_data.js.
2. POST `/api/v1/imports/analyze` with multipart file upload -> 200, jobId returned.
3. GET `/api/v1/imports/jobs/{job_id}` -> 200, verify status = "completed", course_data present.
4. POST `/api/v1/imports/jobs/{job_id}/commit` -> 200, verify course_id set, status = "committed".

**Flow F7: Social Features (Discussion, Poll, Review)**
1. POST `/api/v1/courses/{courseId}/discussions` -> 201, threadId.
2. POST `/api/v1/courses/{courseId}/discussions/{threadId}/replies` -> 201, replyId.
3. POST `/api/v1/courses/{courseId}/polls` with options -> 201, pollId.
4. POST `/api/v1/courses/{courseId}/polls/{pollId}/vote` with valid option -> 200.
5. POST `/api/v1/courses/{courseId}/reviews` -> 201, reviewId.
6. GET `/api/v1/courses/{courseId}/discussions` -> 200, verify thread list.
7. GET `/api/v1/courses/{courseId}/polls/{pollId}/results` -> 200, verify tally.

### 1.6 Negative and Edge-Case Test Matrix

Each scenario must assert both the status code AND the structured error response shape (code, field, message keys).

| Test ID | Scenario | Expected Status | Error Shape Assertion |
|---|---|---|---|
| NEG-001 | POST course with duplicate courseId | 400 | `detail` contains "courseId already exists" |
| NEG-002 | POST course with empty title | 422 | `errors[].code == "REQUEST_VALIDATION_ERROR"` |
| NEG-003 | POST course with 600-char description | 422 | validation on `description` field |
| NEG-004 | GET non-existent course | 404 | `detail == "Course not found"` |
| NEG-005 | DELETE non-existent course | 404 | `detail == "Course not found"` |
| NEG-006 | PATCH course with invalid status `"archived"` | 422 | pattern mismatch on status field |
| NEG-007 | POST export with non-sequential template orders (0,2) | 422 | error mentions "sequential" or "contiguous" |
| NEG-008 | POST export with empty template array | 422 | `detail` contains "at least one page" |
| NEG-009 | POST export with no payload | 422 | `errors[].code == "REQUEST_VALIDATION_ERROR"` |
| NEG-010 | POST export/validate with bad courseId | 422 | structured error detail array |
| NEG-011 | POST imports/analyze with non-zip file | 400 | `detail` contains "must be a ZIP archive" |
| NEG-012 | GET import job with non-existent job_id | 404 | `detail == "Job not found"` |
| NEG-013 | POST commit with non-existent job_id | 400 | error detail present |
| NEG-014 | POST page on non-existent course | 404 | `detail == "Course not found"` |
| NEG-015 | DELETE non-existent component | 404 | `detail == "Component not found"` |
| NEG-016 | POST theme with missing required color fields | 422 | validation error structure |
| NEG-017 | POST score calculate with empty answers list | 422 | error on `answers` minimum length |
| NEG-018 | POST branch with missing sourcePageId | 422 | validation error structure |
| NEG-019 | POST media upload with 100MB file | 413 | detail mentions "too large" |
| NEG-020 | POST audio with unsupported mime type | 415 | detail mentions "Unsupported audio format" |
| NEG-021 | POST social poll with duplicate vote | 409 | detail mentions already voted |
| NEG-022 | GET health/detailed when DB unreachable | 503 | status = "degraded" |
| NEG-023 | POST export/scorm/{courseId} for empty course | 422 | errors array with code "COURSE_NO_PAGES" |
| NEG-024 | POST export/scorm/{courseId} for non-existent course | 404 | detail contains "not found" |
| NEG-025 | POST upsert a course then verify idempotency | 200 (update) | same courseId, same response shape |

### 1.7 Data Seed Requirements

Each test module must be self-seeding. The conftest provides:
- `test_client` -- pre-configured FastAPI TestClient with in-memory SQLite DB override.
- `sample_course_data` -- minimal valid course payload dict.
- `sample_course_json` -- JSON string of `sample_course_data`.

Test modules needing non-trivial DB state must define their own `@pytest.fixture(scope="module")` producing an `async with AsyncClient(...)` client connected to a module-scoped SQLite database. The fixture pattern from `tests/test_scorm_export_persisted.py` (lines 36-51) is canonical.

---

## 2. Technical Specification

### 2.1 Test Architecture

```
tests/
  conftest.py                  # Shared fixtures: test_client, sample_course_data, etc.
  test_health.py               # Health endpoint unit tests (existing, expand)
  test_courses_api.py          # Courses CRUD API tests (existing, expand)
  test_courses_negative.py     # Courses negative tests (existing, expand)
  test_templates_api.py        # Templates API tests (existing, expand)
  test_templates_negative.py   # Templates negative tests (existing, expand)
  test_page_components_api.py  # Pages + Components API tests (existing, expand)
  test_export.py               # Export endpoint tests (existing, expand)
  test_export_negative.py      # Export negative tests (existing, expand)
  test_export_runtime_smoke.py # SCORM runtime content smoke tests (existing, expand)
  test_scorm_export_persisted.py # Persisted course SCORM export (existing, expand)
  test_scorm_export_assets.py  # Asset packaging tests (existing)
  test_scorm_theme_export.py   # Theme cascade export tests (existing)
  test_import_strategies.py    # Import strategy tests (existing)
  test_import_discovery.py     # Import discovery tests (existing)
  test_import_harvest.py       # Import harvest tests (existing)
  test_branching.py            # Branching CRUD + events API tests (existing, expand)
  test_scoring_completion_api.py # Scoring + completion API tests (existing, expand)
  test_analytics.py            # Analytics summary tests (existing, expand)
  test_social.py               # Social features tests (existing)
  test_media_upload.py         # Media upload tests (existing)
  test_themes_api.py           # NEW -- Theme CRUD + cascade resolution tests
  test_audio_api.py            # NEW -- Audio upload + narration tests
  test_component_registry_api.py # Component registry tests (existing, expand)
  test_security_services.py    # Security sanitization tests (existing)
  test_renderer_registry.py    # Renderer registry tests (existing)

  flows/
    test_flow_full_crud_export.py  # Flow F1
    test_flow_templates.py         # Flow F2
    test_flow_theme_cascade.py     # Flow F3
    test_flow_scoring_analytics.py # Flow F4
    test_flow_branching.py         # Flow F5
    test_flow_import.py            # Flow F6
    test_flow_social.py            # Flow F7

  release/
    test_release_readiness.py  # Layer 4 smoke tests (Docker, PostgreSQL, health)

  __init__.py
```

### 2.2 Database Fixture Pattern

All API-level tests that exercise the full FastAPI stack (routers -> repositories -> ORM) use the **module-scoped SQLite pattern** defined in `conftest.py` (lines 29-81). This pattern:

1. Creates a `NamedTemporaryFile`-backed SQLite database at module scope.
2. Creates an async engine with `check_same_thread=False` and `NullPool`.
3. Creates all tables via `Base.metadata.create_all` before the first test.
4. Overrides the `get_session` FastAPI dependency with a session factory bound to the test engine.
5. Cleans up the temp DB file and clears dependency overrides after the module completes.

For tests that need an async HTTP client, use the `httpx.AsyncClient` with `ASGITransport`:

```python
@pytest.fixture(scope="module")
async def test_app():
    engine = create_async_engine("sqlite+aiosqlite:///./test_foo.db", future=True, poolclass=NullPool)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async def _override_session():
        async with session_factory() as session:
            yield session
    real_app.dependency_overrides[get_session] = _override_session
    yield real_app
    real_app.dependency_overrides.clear()
    await engine.dispose()

@pytest.mark.asyncio
async def test_something(test_app: FastAPI):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/v1/courses", json={...})
        assert r.status_code == 201
```

### 2.3 Test Discovery and Naming Conventions

| Convention | Rule |
|---|---|
| Test file name | `test_<module>.py` or `test_flow_<name>.py` |
| Test class name | `Test<ModuleName>` (e.g., `TestCoursesAPI`, `TestBranching`) |
| Test function name | `test_<scenario>_<variant>` (e.g., `test_create_course_success`, `test_create_course_duplicate_id`) |
| Negative test marker | Function name contains `_error_` or `_negative_` or describes the error condition |
| Multi-step flow marker | File placed under `tests/flows/` |
| Release readiness marker | File placed under `tests/release/` and marked `@pytest.mark.slow` |
| Async test marker | Use `@pytest.mark.asyncio` (auto-detected via `asyncio_mode = auto` in `pytest.ini`) |

### 2.4 Response Shape Assertions

Every API test must verify the response shape against the OpenAPI schema. The canonical assertions are:

```python
def assert_health_response(data: dict):
    assert "status" in data
    assert "version" in data
    assert "environment" in data
    assert "timestamp" in data
    assert "uptime" in data
    assert data["status"] == "healthy"
    assert isinstance(data["version"], str)
    assert isinstance(data["uptime"], (int, float))

def assert_course_out(data: dict):
    assert "id" in data
    assert "courseId" in data
    assert "title" in data
    assert "status" in data
    assert "createdAt" in data
    assert "updatedAt" in data
    assert "data" in data
    assert isinstance(data["id"], int)
    assert isinstance(data["courseId"], str)
    assert len(data["courseId"]) > 0

def assert_error_response(data: dict, expected_status: int):
    if expected_status == 422:
        assert "detail" in data
        assert "errors" in data
        for err in data["errors"]:
            assert "code" in err
            assert "field" in err
            assert "message" in err
    elif expected_status == 404:
        assert "detail" in data

def assert_zip_response(response):
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "content-disposition" in response.headers
    assert "attachment" in response.headers["content-disposition"]
    content = response.content
    assert len(content) > 0
    import zipfile, io
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        assert "imsmanifest.xml" in zf.namelist()
        assert "index.html" in zf.namelist()
```

### 2.5 Pytest Configuration (`pytest.ini`)

```ini
[pytest]
asyncio_mode = auto
filterwarnings =
    ignore::pytest.PytestUnknownMarkWarning
markers =
    slow: marks tests as slow (e.g., Docker, PostgreSQL, full export)
    integration: marks multi-step flow tests
    release: marks release readiness smoke tests
    unit: marks pure unit tests (no DB, no HTTP)
```

Add to `conftest.py`:

```python
def pytest_configure(config):
    config.addinivalue_line("markers", "slow: slow tests (excluded from quick runs)")
    config.addinivalue_line("markers", "integration: multi-step flow tests")
    config.addinivalue_line("markers", "release: release readiness smoke tests")
    config.addinivalue_line("markers", "unit: pure unit tests (no DB/HTTP)")
```

### 2.6 CI/CD Integration (`.github/workflows/ci-cd.yml`)

The existing CI/CD pipeline must be augmented with:

```yaml
jobs:
  test:
    steps:
      # ... existing checkout, setup, install, lint ...

      - name: Run unit tests (fast)
        run: pytest -m "unit" --cov=app --cov-report=term --timeout=30
        env:
          DATABASE_URL: sqlite+aiosqlite:///./test_fast.db

      - name: Run integration tests
        run: pytest -m "integration" --cov=app --cov-report=term --cov-append --timeout=120
        env:
          DATABASE_URL: sqlite+aiosqlite:///./test_integration.db

      - name: Run full suite with coverage report
        run: pytest --cov=app --cov-report=xml --cov-report=term --timeout=300
        env:
          DATABASE_URL: sqlite+aiosqlite:///./test_full.db

      - name: Enforce coverage thresholds
        run: |
          coverage report --fail-under=85
          coverage xml

      - name: Run slow/release tests (PostgreSQL)
        if: github.ref == 'refs/heads/main'
        run: pytest -m "release" --timeout=300
        env:
          DATABASE_URL: postgresql+asyncpg://test_user:test_password@localhost:5432/test_db
          ENVIRONMENT: test
```

Add `pytest-timeout` to `requirements-dev.txt`:
```
pytest-timeout>=2.3.0
```

### 2.7 Coverage Thresholds

Coverage enforcement is configured in `.coveragerc`:

```ini
[run]
source = app
omit = */migrations/*,*/__pycache__/*,test_*,*_test.py

[report]
exclude_lines =
    pragma: no cover
    @overload
    raise NotImplementedError
    if __name__ == "__main__":
    pass

# Per-package thresholds
[coverage:report:app/routers/]
fail_under = 90

[coverage:report:app/services/]
fail_under = 85

[coverage:report:app/repositories/]
fail_under = 90

[coverage:report:app/models/]
fail_under = 80
```

### 2.8 Service-Specific Test Contracts

#### SCORM Export Service (`app/services/scorm_export.py`)

Test the following methods directly (unit tests, no HTTP):

- `generate_scorm_package(course, theme_bundle=None)` -- returns BytesIO ZIP:
  - Verify ZIP contains `imsmanifest.xml` with correct XML structure.
  - Verify ZIP contains `index.html` with `<html><body>...</body></html>`.
  - Verify ZIP contains `course_data.js` with serialized course JSON.
  - Verify ZIP contains media assets when `includeMedia=True`.
  - Verify ZIP contains `style.css` with resolved theme tokens when `theme_bundle` provided.
  - Verify `imsmanifest.xml` contains `<resource>` elements for each template.
  - Verify files over 50KB are present in full (not truncated).

- `validate_for_export(course)` -- returns dict `{"valid": bool, "errors": [str], "warnings": [str]}`:
  - Empty template list -> `valid=False`.
  - Unknown template type -> `valid=False`, error mentions "runtime".
  - All built-in types -> `valid=True`.

- `estimate_package_size(course)` -- returns int (bytes):
  - Returns > 0 for any valid course.
  - Larger course (more templates) returns larger estimate.

- `_create_content_html(package_dir, course)` -- writes `index.html`:
  - HTML contains `data-action="submit-mcq"` for MCQ components.
  - HTML contains `data-action="submit-final-assessment"` for final assessment.
  - HTML contains `finalAssessmentSubmissions` and `failedFinalAssessments` JS variables.
  - HTML contains `SCORM.setValue('cmi.core.lesson_status', ...)` for SCORM bridge.

#### Theme Resolution (`app/routers/export.py` lines 635-706)

Test `_resolve_theme_bundle()` directly:

- No theme configured -> returns `_FALLBACK_THEME`.
- Theme preset exists -> merges preset + course overrides.
- Page-level `theme_config.overrides` present -> included in `pageOverrides`.
- Component-level styling present -> included in `componentOverrides`.

#### Template Mapping (`app/routers/export.py` lines 492-600)

Test `_map_template_record()` directly:

- `content-text` template -> maps correctly with `content`.
- `content-video` template -> raises `PersistedCourseExportValidationError` when missing `videoUrl`.
- `mcq` template -> normalizes question options with `correct`/`isCorrect` fallback.
- `tabs`/`accordion` templates -> preserves `tabs`/`panels` arrays.
- `final-assessment` template -> synthesizes `content` from `introText`.
- `text-with-media` template -> preserves `body`, `mediaUrl`, `mediaType`, `mediaPosition`.

#### Course Validation (`app/routers/courses.py` lines 465-751)

Test `validate_course` endpoint:

- Valid course with `welcome` page and valid title -> `valid=True`.
- Missing `courseId` -> `valid=False`, error id starts with "missing-".
- Empty pages array -> `valid=False`, error id "pages-empty".
- MCQ page without question -> `valid=False`, error id "page-0-mcq-no-question".
- MCQ page without options -> `valid=False`, error id "page-0-mcq-insufficient-options".
- Duplicate page ids -> Pydantic model validation catches duplicate orders.
- Export model compat check with invalid `mcq` template -> `valid=False`, error id starts with "export-compat-".

---

## 3. Non-Functional Requirements

### 3.1 Performance

| NFR | Target | Measurement |
|---|---|---|
| Full test suite run time | < 5 minutes on CI (GitHub Actions ubuntu-latest) | `pytest --durations=10` |
| Unit + API contract tests | < 60 seconds | `pytest -m "not slow" --timeout=30` |
| Slow/release tests | < 4 minutes | `pytest -m "slow" --timeout=300` |
| Individual test timeout | < 30 seconds per test | `pytest --timeout=30` |
| Test database creation | < 5 seconds per module | engine creation + schema create_all |

### 3.2 Reliability

| NFR | Target | Enforcement |
|---|---|---|
| Flaky test rate | < 1% across 100 CI runs | `pytest --flaky --max-runs=3 --min-passes=1` |
| Idempotent test execution | Each test passes when run in isolation AND as part of the suite | Module-scoped fixtures that create/reset DB |
| Parallel test execution | Tests within a module can share a fixture | Module-scoped async client |
| Concurrency safety | 10 concurrent requests to the same endpoint | Thread-based concurrent test in `test_health.py` pattern |

### 3.3 Maintainability

| NFR | Target | Mechanism |
|---|---|---|
| Response shape helpers | Shared assertion functions in `conftest.py` | `assert_course_out`, `assert_error_response`, `assert_zip_response` |
| No hardcoded URLs | All routes use router prefixes | Import `router.prefix` or use strings matching the OpenAPI spec |
| Minimal test data duplication | Seed data factories in `conftest.py` | `_seed_course()`, `_seed_page()`, `_seed_component()` helpers |
| Explicit assertions only | No `assert True` or bare `try/except` | Linter rule: `flake8-assert` |

### 3.4 Reporting

| NFR | Target | Tool |
|---|---|---|
| JUnit XML output | CI-readable test results | `pytest --junitxml=test-results.xml` |
| Coverage HTML report | Human-readable coverage details | `pytest --cov-report=html` |
| Coverage XML report | Codecov/GitHub integration | `pytest --cov-report=xml` |
| Slow test identification | Top 10 slowest tests printed | `pytest --durations=10` |
| Failure summary | Traceback + assertion + context | `pytest --tb=short` (default) |
| Allure report | Rich test report with steps | Optional: `pytest --alluredir=allure-results` |

### 3.5 Environment Configuration

```bash
# CI environment variables
DATABASE_URL=sqlite+aiosqlite:///./test.db  # Default; override to PostgreSQL for release tests
ENVIRONMENT=test
EXPORT_HEADERS=0  # Disable feature-flagged headers in tests to avoid non-determinism
SQL_ECHO=false    # Keep test logs clean
APP_VERSION=test
```

### 3.6 Isolation Requirements

- Each test module creates its own temp database file.
- No test module reads or writes another module's DB file.
- The `conftest.py` session-scoped override creates the in-memory DB once and all tests share it.
- Module-scoped fixtures (e.g., `test_app`) override the dependency again for their module.
- After each module completes, dependency overrides are cleared and the engine is disposed.
- No test may depend on state left by a prior test (except session-scoped fixtures).

---

## 4. Current State

### 4.1 Existing Test Coverage (as of June 2026)

| Domain | File(s) | Lines | Coverage Assessment |
|---|---|---|---|
| Health | `test_health.py` | 154 | Good: covers success, format, detailed, CORS, performance, concurrency |
| Courses CRUD | `test_courses_api.py` | 116 | Good: CRUD flow + duplicate detection |
| Courses Negative | `test_courses_negative.py` | 59 | Good: duplicate, missing title, invalid status, 404s |
| Templates | `test_templates_api.py` | 76 | Adequate: CRUD + reorder |
| Templates Negative | `test_templates_negative.py` | 68 | Good: duplicate, missing fields |
| Pages & Components | `test_page_components_api.py` | 102 | Adequate: CRUD but missing component reorder tests |
| Export | `test_export.py` | 451 | Good: success, invalid JSON, missing fields, validation |
| Export Negative | `test_export_negative.py` | 60 | Adequate: JSON structure, validate, non-sequential order |
| Export Runtime Smoke | `test_export_runtime_smoke.py` | 233 | Good: template validation, submit actions, finish gate |
| Export Persisted | `test_scorm_export_persisted.py` | 341 | Good: upsert, export persisted, page, component seeding |
| Export Assets | `test_scorm_export_assets.py` | 280 | Good: asset packaging, dedup, integrity |
| Export Theme | `test_scorm_theme_export.py` | 709 | Good: theme cascade, fallback, page/component overrides |
| Export Migration | `test_export_migration.py` | 53 | Adequate: migration tests |
| Export Validator | `test_export_validator.py` | 138 | Good: validation contracts |
| Export Warnings | `test_export_warnings_header.py` | 53 | Adequate: header feature flag |
| Import Strategies | `test_import_strategies.py` | 141 | Good: SCORM 1.2, JSON, edge cases |
| Import Discovery | `test_import_discovery.py` | 146 | Good: discovery flow |
| Import Harvest | `test_import_harvest.py` | 80 | Adequate: harvest flow |
| Branching | `test_branching.py` | 207 | Good: CRUD + events + validation |
| Scoring & Completion | `test_scoring_completion_api.py` | 350 | Good: calculate, validate, completion, interactions |
| Analytics | `test_analytics.py` | 100 | Adequate: summary |
| Analytics Learners | `test_analytics_learners.py` | 114 | Adequate: learner-specific |
| Social | `test_social.py` | 418 | Good: discussions, polls, reviews, challenges |
| Media Upload | `test_media_upload.py` | 83 | Adequate: upload, file type validation |
| Component Registry | `test_component_registry_api.py` | 39 | Weak: only basic list, no categories/search/typeId |
| Component Registry Errors | `test_component_registry_errors.py` | 79 | Adequate: 404, validation |
| Course Phase 3 | `test_course_phase3.py` | 218 | Good: phase 3 features |
| Course Updated At | `test_course_updated_at.py` | 72 | Good: timestamp tracking |
| Course Validate | `test_course_validate_api.py` | 67 | Good: template-based validation |
| Security Services | `test_security_services.py` | 174 | Good: HTML/JS/CSS sanitization |
| Renderer Registry | `test_renderer_registry.py` | 523 | Good: dynamic rendering |
| SCORM JS Sanitization | `test_scorm_js_sanitization.py` | 120 | Good: JS sanitizer |
| Final Assessment | `test_final_assessment_contract.py` | 72 | Good: contract validation |
| Accordion Preview | `test_accordion_preview_parity.py` | 224 | Good: preview parity |

**Total: 6,233 lines across 33 test files.**

### 4.2 Coverage Gaps

| Gap | Domain | Impact | Priority |
|---|---|---|---|
| No theme API tests | `app/routers/themes.py` (10 endpoints) | Theme CRUD untested | HIGH |
| No audio API tests | `app/routers/audio.py` (5 endpoints) | Audio upload untested | HIGH |
| Weak component registry tests | `test_component_registry_api.py` (39 lines) | categories, search, typeId untested | MEDIUM |
| No multi-step flow tests | `tests/flows/` does not exist | Cross-endpoint workflows untested | HIGH |
| No release readiness tests | `tests/release/` does not exist | Docker, PostgreSQL, deployment untested | HIGH |
| Coverage threshold not enforced | CI pipeline | Coverage can regress | HIGH |
| No pytest timeout | `pytest.ini` | Tests could hang indefinitely | MEDIUM |
| No JUnit XML output in CI | `.github/workflows/ci-cd.yml` | Test reports not parsed | MEDIUM |
| No flaky test detection | CI pipeline | Flaky tests hide regressions | LOW |

### 4.3 Existing Test Infrastructure

- **Framework**: `pytest` 8.x with `pytest-asyncio` for async support.
- **HTTP Client**: `httpx.AsyncClient` with `ASGITransport` (async) and `fastapi.testclient.TestClient` (sync).
- **Database**: In-memory SQLite via `aiosqlite` for isolation; PostgreSQL via `asyncpg` in CI.
- **Fixture Pattern**: Session-scoped DB creation + module-scoped override (in `conftest.py`).
- **CI**: GitHub Actions with Postgres service container, `pytest --cov=app`, Codecov upload.
- **Coverage**: `pytest-cov` with XML output; no threshold enforcement yet.

---

## 5. Expansion Points

### 5.1 Parallel Test Execution

When the test suite grows beyond 10,000 lines, enable parallel execution with `pytest-xdist`:

```bash
pip install pytest-xdist
pytest -n auto --dist loadscope
```

This requires that all module-scoped fixtures are truly isolated (no shared files, no global state). The existing `conftest.py` pattern already supports this.

### 5.2 PostgreSQL CI Matrix

Add a CI matrix to test against multiple PostgreSQL versions:

```yaml
strategy:
  matrix:
    pg-version: [15, 16]
services:
  postgres:
    image: postgres:${{ matrix.pg-version }}
```

### 5.3 Property-Based Testing

For validation logic (Pydantic models, export validation, scoring), add `hypothesis` property-based tests:

```python
from hypothesis import given, strategies as st

@given(st.text(min_size=1, max_size=200))
def test_course_title_accepts_valid_strings(title):
    course = Course(courseId="test", title=title, templates=[])
    assert course.title == title
```

### 5.4 Snapshot Testing

For export ZIP output, add snapshot testing with `pytest-snapshot`:

```python
def test_export_zip_snapshot(snapshot, test_client, sample_course_json):
    response = test_client.post("/api/v1/export", json={"course": sample_course_json})
    snapshot.assert_match(response.content, "export_output.zip")
```

### 5.5 Contract Testing with OpenAPI

Add automatic contract validation using `openapi-core` or `schemathesis`:

```python
from schemathesis import from_path

schema = from_path("openapi-v3.1-complete.yaml")

@schema.parametrize()
def test_api_contract(request, case):
    response = case.call()
    case.validate_response(response)
```

### 5.6 Load Testing

Add a `tests/load/` directory with locust scenarios for performance regression detection:

```python
from locust import HttpUser, task

class ExportUser(HttpUser):
    @task
    def export_course(self):
        self.client.post("/api/v1/export", json={"course": self.course_json})
```

### 5.7 Mutation Testing

Add mutation testing with `mutmut` to validate test quality (not just coverage):

```bash
pip install mutmut
mutmut run --paths-to-mutate app/routers/
mutmut results
```

### 5.8 Test Data Factories

Replace inline dict construction with `factory_boy` factories for cleaner test data:

```python
class CourseFactory(factory.Factory):
    class Meta:
        model = dict
    courseId = factory.Sequence(lambda n: f"course-{n:04d}")
    title = factory.Faker("sentence", nb_words=4)
    templates = []

class MCQComponentFactory(factory.Factory):
    class Meta:
        model = dict
    componentType = "mcq"
    order = 0
    data = {"questions": [{"id": "q1", "question": "Test?", "options": [{"id": "a", "text": "A", "isCorrect": True}]}]}
```

---

## 6. Validation

### 6.1 Test Plan

| Phase | Activities | Artifacts | Sign-Off |
|---|---|---|---|
| 1. Audit | Catalogue existing tests per domain; identify gaps | Current State Report (Section 4) | QA Lead |
| 2. Scaffold | Create missing test files; add pytest-timeout; add pytest markers | `tests/flows/`, `tests/release/` | Dev Lead |
| 3. Write Unit Tests | Repository tests for each repository; service method tests | Individual test functions in existing files | Dev Lead |
| 4. Write API Tests | One test per endpoint (happy + negative); response shape assertions | Expanded test files per domain | QA Lead |
| 5. Write Flow Tests | F1-F7 multi-step flows | `tests/flows/test_flow_*.py` | QA Lead |
| 6. Write Release Tests | Docker container health, PostgreSQL connectivity, full export | `tests/release/test_release_readiness.py` | DevOps Lead |
| 7. Configure CI | Coverage thresholds, junitxml, pytest-timeout, parallel markers | `.github/workflows/ci-cd.yml`, `.coveragerc` | DevOps Lead |
| 8. Baseline Run | Run full suite 10 times; measure flakiness; tune timeouts | CI runs with `--durations=10` output | QA Lead |
| 9. Gate Enforcement | Block PRs that fail coverage threshold or introduce test failures | GitHub branch protection rules | TPO |

### 6.2 Validation Scenarios (Pre-Merge Checklist)

Every PR must pass these checks before merging:

```
CHECKLIST:
[ ] Run `pytest -m "not slow" --timeout=30` -- all pass
[ ] Run `pytest --cov=app --cov-report=term` -- coverage >= 85%
[ ] Run `flake8 app/ --count --select=E9,F63,F7,F82 --show-source --statistics` -- 0 errors
[ ] For new features: at least 1 happy-path test + 1 negative-path test per new endpoint
[ ] For bug fixes: test that reproduces the bug added before the fix
```

### 6.3 Release Readiness Checklist

Before tagging a release candidate:

```
RELEASE READINESS:
[ ] `pytest -m "release"` all pass against staging PostgreSQL
[ ] `pytest --timeout=300` entire suite passes 3 consecutive CI runs
[ ] Coverage report: overall >= 85%, routers >= 90%, services >= 85%, repositories >= 90%
[ ] JUnit XML test report archived
[ ] Top-10 slowest tests identified and reviewed for optimization
[ ] No flaky tests (each test passes 100% of 10 runs)
[ ] Docker image builds and health check returns 200
[ ] SCORM export produces valid ZIP with correct manifest
```

### 6.4 Test Execution Modes

Different execution modes for different scenarios:

```bash
# Quick check (pre-commit hook)
pytest -m "not slow and not integration" --timeout=15 -x

# Full dev suite (before pushing)
pytest -m "not slow" --timeout=30 --cov=app --cov-report=term

# CI full suite
pytest --timeout=300 --cov=app --cov-report=xml --junitxml=test-results.xml --durations=10

# Release suite (staging)
DATABASE_URL=postgresql+asyncpg://... pytest -m "release" --timeout=300

# Flaky check
pytest --count=10 --timeout=30 -x tests/test_something.py
```

---

## 7. Definition of Done

### 7.1 Must-Have (MVP Gate)

- [ ] Every endpoint in Section 1.4 has at least one passing happy-path test.
- [ ] Every endpoint in Section 1.4 has at least one passing negative-path test.
- [ ] All 25 NEG-xxx negative tests from Section 1.6 exist and pass.
- [ ] Flows F1-F7 from Section 1.5 exist and pass.
- [ ] New test files created for themes (`tests/test_themes_api.py`) and audio (`tests/test_audio_api.py`).
- [ ] Weak component registry tests expanded to cover categories, search, and typeId.
- [ ] Release readiness smoke test (`tests/release/test_release_readiness.py`) exists.
- [ ] `pytest-timeout` added to `requirements-dev.txt` and configured in `pytest.ini`.
- [ ] Coverage thresholds enforced in CI at >=85% overall.
- [ ] JUnit XML test report output configured in CI.
- [ ] All existing 6,233 lines of tests continue to pass (no regressions).
- [ ] `pytest.ini` updated with `slow`, `integration`, `release`, `unit` markers.
- [ ] `.coveragerc` file created with per-package thresholds.

### 7.2 Should-Have (Next Iteration)

- [ ] Property-based tests for Pydantic models (hypothesis).
- [ ] Snapshot tests for SCORM ZIP output.
- [ ] OpenAPI contract tests (schemathesis).
- [ ] Parallel test execution with `pytest-xdist`.
- [ ] Test data factories with `factory_boy`.
- [ ] Flaky test detection and auto-retry.
- [ ] CI matrix for PostgreSQL 15/16.

### 7.3 Could-Have (Stretch)

- [ ] Mutation testing with `mutmut`.
- [ ] Load testing scenarios under `tests/load/`.
- [ ] Allure test reporting.
- [ ] Pre-commit hook running minimal test suite.
- [ ] Performance regression benchmarks for critical flows (export, import, scoring).

### 7.4 Out of Scope

- Frontend E2E tests (Cypress/Playwright) -- covered by separate test infrastructure.
- Performance/load testing infrastructure (separate epic).
- AI-specific tool call tests (covered by US-AI-023, US-AI-024).
- Manual QA test scripts (covered by `E2E_TEST_CASE_TEMPLATES.md`).

---

## 8. Tasks

### Task 1: Audit and Catalogue Existing Tests

**Scope:** Review all 33 existing test files; document which endpoints are covered and which are missing. Produce a coverage matrix.

**Files:**
- `tests/` -- all existing test files

**Acceptance Criteria:**
- Coverage matrix produced as a markdown table mapping every endpoint to its test file(s).
- Coverage gaps documented (Section 4.2).
- Report added to `docs/TESTING_COVERAGE_AUDIT.md`.

**Effort:** 2 days.

---

### Task 2: Create Theme API Tests

**Scope:** Write `tests/test_themes_api.py` covering all 10 theme endpoints from `app/routers/themes.py`.

**Test scenarios:**
- CRUD for themes (POST, GET list, GET by id, PATCH, DELETE).
- GET presets returns default themes.
- GET/PATCH course-level theme returns/updates merged theme.
- GET/PATCH page-level theme returns/updates merged theme.
- 404 on non-existent theme/course/page.
- 422 on invalid theme payload.

**Reference implementation:** `tests/test_courses_api.py` for fixture pattern.

**Acceptance Criteria:**
- 10+ individual test functions.
- Every theme endpoint covered (happy + negative).
- All tests pass under `pytest -m "not slow"`.

**Effort:** 2 days.

---

### Task 3: Create Audio API Tests

**Scope:** Write `tests/test_audio_api.py` covering all 5 audio endpoints from `app/routers/audio.py`.

**Test scenarios:**
- Upload audio (POST) with valid MP3/WAV -> 201.
- Upload audio with unsupported mime type -> 415.
- Upload audio oversized -> 413.
- Get audio metadata -> 200.
- Patch audio metadata (label, transcript, duration) -> 200.
- Delete audio -> 204.
- 404 on non-existent audioId.
- Get course narration -> 200 with page/component audio items.
- Get course narration for non-existent course -> 404.

**Acceptance Criteria:**
- 8+ individual test functions.
- Every audio endpoint covered.
- Upload tests use `BytesIO` to simulate file upload without actual files.

**Effort:** 2 days.

---

### Task 4: Expand Component Registry Tests

**Scope:** Expand `tests/test_component_registry_api.py` to cover categories, search, and typeId retrieval.

**Current tests:** `list_component_types` (39 lines).

**New test scenarios:**
- GET `/api/v1/components/categories` -> 200 with categories list.
- GET `/api/v1/components/categories/{categoryId}` -> 200 with types in category.
- GET `/api/v1/components/categories/{categoryId}` -> 404 for bad category.
- GET `/api/v1/components/search?q=...` -> 200 with filtered results.
- GET `/api/v1/components/search?q=nonexistent` -> 200 with empty list.
- GET `/api/v1/components/{typeId}` -> 200 with schema, schemaVersion, etag.
- GET `/api/v1/components/{typeId}` -> 404 for bad typeId.
- GET `/api/v1/components?category=...` -> 200 with filtered list.
- GET `/api/v1/components?scoringEnabled=true` -> 200 with filtered list.
- GET `/api/v1/components` -> 200 with pagination (page, limit params).

**Acceptance Criteria:**
- 10+ new test functions added to existing file.
- All component registry endpoints covered.

**Effort:** 1 day.

---

### Task 5: Create Multi-Step Flow Tests

**Scope:** Create `tests/flows/` directory with 7 flow test files.

**Files:**
- `tests/flows/test_flow_full_crud_export.py` (F1)
- `tests/flows/test_flow_templates.py` (F2)
- `tests/flows/test_flow_theme_cascade.py` (F3)
- `tests/flows/test_flow_scoring_analytics.py` (F4)
- `tests/flows/test_flow_branching.py` (F5)
- `tests/flows/test_flow_import.py` (F6)
- `tests/flows/test_flow_social.py` (F7)

Each flow uses a module-scoped async fixture (pattern from `tests/test_scorm_export_persisted.py`) and exercises 3-8 sequential API calls, asserting state at each step.

**Acceptance Criteria:**
- 7 files, each with a single `@pytest.mark.integration` test function.
- Each flow exercises the exact sequence in Section 1.5.
- All flows pass under `pytest -m integration`.

**Effort:** 3 days.

---

### Task 6: Create Release Readiness Smoke Tests

**Scope:** Create `tests/release/test_release_readiness.py` with tests that require a production-like environment (PostgreSQL, Docker).

**Test scenarios:**
- Docker container health: build container, start it, hit `GET /api/v1/health` -> 200.
- PostgreSQL connectivity: connect, run simple SELECT, verify response.
- Full SCORM export with PostgreSQL: create course, add component, export, verify ZIP.
- Health readiness probe: `GET /api/v1/health/ready` -> 200.
- Health liveness probe: `GET /api/v1/health/live` -> 200.
- Force 503 readiness: set `ENVIRONMENT=staging` (or mock DB failure), verify degraded status.
- CORS headers present: `GET /api/v1/health` has `access-control-allow-origin`.
- OpenAPI schema accessible: `GET /api/v1/openapi.json` -> 200 with valid OpenAPI schema.

All tests marked `@pytest.mark.release`.

**Acceptance Criteria:**
- 8+ test functions.
- All marked with `@pytest.mark.release`.
- Test file supports `DATABASE_URL` env var for PostgreSQL (falls back to SQLite).
- Documentation in test file header explaining how to run: `DATABASE_URL=postgresql+asyncpg://... pytest -m release`.

**Effort:** 2 days.

---

### Task 7: Configure Coverage Thresholds and CI Enhancements

**Scope:** Create `.coveragerc`, update `pytest.ini`, update `.github/workflows/ci-cd.yml`.

**Files:**
- `.coveragerc` (new) -- per-package coverage thresholds.
- `pytest.ini` (update) -- add markers, timeout config.
- `.github/workflows/ci-cd.yml` (update) -- add coverage enforcement, JUnit, timeout, matrix strategy placeholders.
- `requirements-dev.txt` (update) -- add `pytest-timeout`.

**Configuration details:**
- See Sections 2.5, 2.6, 2.7, 3.4 for exact specifications.

**Acceptance Criteria:**
- CI fails if overall coverage < 85%.
- CI fails if router coverage < 90%.
- CI fails if service coverage < 85%.
- CI fails if repository coverage < 90%.
- CI produces `test-results.xml`, `coverage.xml`, and `coverage/` HTML report.
- CI uses `--timeout=300` for full suite.
- `pytest.ini` recognizes `slow`, `integration`, `release`, `unit` markers.

**Effort:** 1 day.

---

### Task 8: Baseline Performance and Flakiness Runs

**Scope:** Execute the full suite 10 times in CI; measure flakiness; capture slowest tests.

**Activities:**
- Create a CI workflow that runs the full suite 10 times with `--durations=10`.
- Collect pass/fail counts per test.
- Identify tests that fail > 1 time out of 10 = flaky candidate.
- Record top-10 slowest tests.
- Tune individual test timeouts based on observed durations.
- Fix or quarantine flaky tests.

**Artifacts:**
- `docs/CI_BASELINE_REPORT.md` with pass rates, durations, flaky test list.

**Acceptance Criteria:**
- All tests pass 10/10 times (0% flakiness).
- No individual test exceeds 30 seconds.
- Full suite completes in < 5 minutes.

**Effort:** 3 days.

---

### Task 9: Add Endpoint-Gap Tests (Coverage Completion)

**Scope:** Write missing positive and negative tests for endpoints found during the audit (Task 1) that lack coverage.

**Target endpoints (from gaps analysis):**

From `app/routers/export.py`:
- `GET /export/status/{exportId}` -- test 200 (completed) and 404.
- `GET /export/formats` -- test 200 with format list.

From `app/routers/media.py`:
- `DELETE /media/files/{fileId}` -- test 204 and 404.
- `POST /media/upload` with oversized file -> 413.
- `POST /media/upload` with unsupported type -> 415.

From `app/routers/health.py`:
- `GET /health/ready` -> 503 when DB is mocked as down.

From `app/routers/page_components.py`:
- `POST .../components/reorder` -- test 200 and 422.
- `DELETE component` -- test 204 and 404.

**Acceptance Criteria:**
- Every endpoint with a primary route decorator has at least 1 test.
- Gap count from audit is reduced to 0.

**Effort:** 2 days.

---

### Task 10: Documentation and Developer Onboarding

**Scope:** Update `docs/TESTING.md` and `docs/DEVELOPMENT.md` with testing conventions.

**Content:**
- How to run tests (Section 3.4 conventions).
- How to add tests for a new endpoint.
- How to write a multi-step flow test.
- How to interpret coverage reports.
- How to run release tests locally.
- Markers reference (slow, integration, release, unit).
- Fixture pattern reference.

**Files:**
- `docs/TESTING.md` (rewrite).
- `docs/DEVELOPMENT.md` (append Testing section).

**Acceptance Criteria:**
- `docs/TESTING.md` is a complete reference.
- Developer can add tests for a new endpoint in < 5 minutes after reading.

**Effort:** 1 day.

---

## Effort Summary

| Task | Days | Dependencies |
|---|---|---|
| 1. Audit existing tests | 2 | None |
| 2. Theme API tests | 2 | Task 1 |
| 3. Audio API tests | 2 | Task 1 |
| 4. Expand component registry tests | 1 | Task 1 |
| 5. Multi-step flow tests | 3 | Tasks 2-4 |
| 6. Release readiness smoke tests | 2 | Task 5 |
| 7. Coverage thresholds + CI | 1 | Task 1 |
| 8. Baseline runs + flakiness | 3 | Tasks 2-7 |
| 9. Endpoint-gap tests | 2 | Task 1 |
| 10. Documentation | 1 | Tasks 2-9 |
| **Total** | **19 days** | |

---

## Appendix A: File Manifest

### New Files

| Path | Purpose |
|---|---|
| `tests/test_themes_api.py` | Theme CRUD + cascade resolution tests |
| `tests/test_audio_api.py` | Audio upload + narration tests |
| `tests/flows/__init__.py` | Package init |
| `tests/flows/test_flow_full_crud_export.py` | Flow F1 |
| `tests/flows/test_flow_templates.py` | Flow F2 |
| `tests/flows/test_flow_theme_cascade.py` | Flow F3 |
| `tests/flows/test_flow_scoring_analytics.py` | Flow F4 |
| `tests/flows/test_flow_branching.py` | Flow F5 |
| `tests/flows/test_flow_import.py` | Flow F6 |
| `tests/flows/test_flow_social.py` | Flow F7 |
| `tests/release/__init__.py` | Package init |
| `tests/release/test_release_readiness.py` | Layer 4 smoke tests |
| `.coveragerc` | Per-package coverage thresholds |
| `docs/TESTING_COVERAGE_AUDIT.md` | Task 1 audit report |
| `docs/CI_BASELINE_REPORT.md` | Task 8 baseline report |

### Modified Files

| Path | Change |
|---|---|
| `pytest.ini` | Add markers, timeout |
| `requirements-dev.txt` | Add `pytest-timeout>=2.3.0` |
| `.github/workflows/ci-cd.yml` | Add coverage enforcement, JUnit, timeout, matrix |
| `docs/TESTING.md` | Rewrite with complete reference |
| `docs/DEVELOPMENT.md` | Append Testing section |
| `tests/conftest.py` | Add shared assertion helpers, pytest_configure markers |
| `tests/test_component_registry_api.py` | Expand to 10+ test functions |

---

## Appendix B: Example Test Structure

This appendix provides a canonical example of a properly structured test file.

```python
"""Tests for the Theme API endpoints.

Covers:
  - GET/POST /api/v1/themes
  - GET/PATCH/DELETE /api/v1/themes/{themeId}
  - GET /api/v1/themes/presets
  - GET/PATCH /api/v1/courses/{courseId}/theme
  - GET/PATCH /api/v1/courses/{courseId}/pages/{pageId}/theme
"""
from __future__ import annotations
import os
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool

from app.main import app as real_app
from app.db.config import get_session
from app.models.base import Base
import app.models.persisted_course  # noqa: F401
import app.models.theme  # noqa: F401

TEST_DB_URL = "sqlite+aiosqlite:///./test_themes.db"

if os.path.exists("test_themes.db"):
    os.remove("test_themes.db")


@pytest.fixture(scope="module")
async def test_app():
    engine = create_async_engine(TEST_DB_URL, future=True, poolclass=NullPool)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _override_session():
        async with session_factory() as session:
            yield session

    real_app.dependency_overrides[get_session] = _override_session
    yield real_app

    real_app.dependency_overrides.clear()
    await engine.dispose()


@pytest.fixture(scope="module")
async def seed_course(test_app: FastAPI) -> dict:
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/v1/courses", json={
            "courseId": "theme-test-course",
            "title": "Theme Test Course",
            "description": None,
            "data": {},
        })
        assert r.status_code == 201
        return r.json()


class TestThemeCRUD:
    @pytest.mark.asyncio
    async def test_create_theme(self, test_app: FastAPI):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "name": "Test Theme",
                "colors": {
                    "primary": "#FF0000",
                    "secondary": "#00FF00",
                    "background": "#FFFFFF",
                    "surface": "#F0F0F0",
                    "text": "#000000",
                    "textSecondary": "#666666",
                    "accent": "#FF00FF",
                    "error": "#FF0000",
                    "success": "#00FF00",
                    "warning": "#FFFF00",
                    "info": "#0000FF",
                    "border": "#CCCCCC",
                },
                "typography": {
                    "fontFamily": "Arial, sans-serif",
                    "headingFont": "Arial, sans-serif",
                    "baseFontSize": 16,
                },
            }
            r = await client.post("/api/v1/themes", json=payload)
            assert r.status_code == 201
            data = r.json()
            assert_data_has_keys(data, ["id", "name", "colors", "typography", "createdAt"])
            assert data["name"] == "Test Theme"
            assert data["colors"]["primary"] == "#FF0000"
            return data["id"]

    @pytest.mark.asyncio
    async def test_create_theme_missing_colors(self, test_app: FastAPI):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {"name": "Bad Theme", "colors": {}}
            r = await client.post("/api/v1/themes", json=payload)
            assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_list_themes(self, test_app: FastAPI):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/api/v1/themes")
            assert r.status_code == 200
            data = r.json()
            assert isinstance(data, list)
            assert len(data) >= 1

    @pytest.mark.asyncio
    async def test_get_presets(self, test_app: FastAPI):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/api/v1/themes/presets")
            assert r.status_code == 200
            data = r.json()
            assert isinstance(data, list)
            assert len(data) >= 2  # Default Light + Dark Mode
            for preset in data:
                assert_data_has_keys(preset, ["name", "colors", "typography"])

    @pytest.mark.asyncio
    async def test_get_theme_404(self, test_app: FastAPI):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/api/v1/themes/99999")
            assert r.status_code == 404


def assert_data_has_keys(data: dict, keys: list):
    for key in keys:
        assert key in data, f"Missing key '{key}' in response: {data}"
