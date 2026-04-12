# TPO Frontend-Backend Alignment Plan (SCORM Runtime)

**Date:** 2026-04-12  
**Owner:** TPO  
**Audience:** Frontend Team, Backend AI Developer, QA  
**Status:** Action Required (Contract Alignment + Execution Plan)

---

## 1. Executive Decision Summary

Backend progress is strong and the frontend runtime foundation is ready, but integration should proceed only after **contract lock** on scoring/completion and exported player API.

### Go-forward decision
1. Keep frontend on **service-layer architecture** (`src/services/*`) as canonical API path.
2. Treat generated files under `docs/exported-zip/` as **artifact evidence only**, not implementation source.
3. Align backend and frontend on one API shape per domain before expanding interactive templates.
4. Continue renderer rollout using the **primitive-based generic model** from the template matrix.

---

## 2. Frontend Status Shared to Backend

### Completed on Frontend
1. Canonical export runtime module exists under `src/export-runtime/` with typed contracts and registry dispatch.
2. 18 template types are implemented and tested (Wave 1 + Wave 2).
3. Theme variables, interaction binding (tabs/accordion/click-reveal), and document builder are implemented.
4. Current verification:
   - Type-check passes.
   - Runtime tests pass (11 total in export-runtime test suites).

### Frontend architecture position
1. Canonical runtime rendering path: `src/export-runtime/*`.
2. API integration path: `src/services/*` via shared `httpClient`.
3. Legacy path still present (`src/services/api.ts`, `src/context/CourseContext.tsx`) and should be deprecated from production flows.

---

## 3. Critical Contract Alignment Required (Backend + Frontend)

## 3.1 Scoring API

### Current frontend contract
- Endpoint: `POST /courses/{courseId}/scoring/calculate`
- Payload shape:
```json
{
  "answers": [
    {
      "componentId": "cmp-1",
      "componentType": "mcq",
      "responses": [
        { "questionId": "q1", "selectedOptionIds": ["opt-2"] }
      ]
    }
  ],
  "attemptNumber": 1
}
```

### Backend brief contract (attached doc)
- Endpoint: `POST /api/v1/scoring/calculate`
- Payload shape:
```json
{
  "courseId": "course-001",
  "slideId": "tpl-1",
  "questionId": "q1",
  "userAnswer": "option-A"
}
```

### Recommendation to backend
Adopt and freeze **course-scoped aggregate scoring** (`/courses/{courseId}/scoring/calculate`) because it scales to multi-component pages and final assessments. If slide-level scoring is still needed, provide it as a compatibility alias.

---

## 3.2 Completion API

### Current frontend contract
- Endpoint: `POST /courses/{courseId}/pages/{pageId}/completion`
- Payload shape:
```json
{
  "componentStates": [
    {
      "componentId": "cmp-1",
      "completed": true,
      "interactionsCompleted": ["tab-1"],
      "audiosCompleted": [],
      "score": 100
    }
  ]
}
```

### Backend brief contract (attached doc)
- Endpoint: `POST /api/v1/completion/mark`
- Payload shape:
```json
{
  "courseId": "course-001",
  "slideId": "tpl-1",
  "status": "completed",
  "timeSpent": 45,
  "answers": { "q1": "option-B" }
}
```

### Recommendation to backend
Keep page-scoped completion endpoint as canonical for deterministic rules (`all/any/percentage/custom`). Optional alias `/completion/mark` can map internally to page completion service.

---

## 3.3 Exported Player Runtime Contract

### Risk observed
Attached backend brief claims `Player.getRenderer(type)` registry for 35+ types. Current exported artifact in repo still shows limited direct dispatch in `index.html` (content/tabs/mcq style branch logic).

### Recommendation to backend
Freeze player runtime contract with versioning:
1. `window.courseData.exportContractVersion` (example: `2026-04-12.1`).
2. `window.courseData.supportedTemplateTypes[]` list emitted per package.
3. `Player.getRenderer(type)` mandatory API for all generated packages.

---

## 4. Generic & Robust Frontend Template Strategy (All Categories)

Use a **primitive-first renderer framework** (already defined in matrix) so 84 template types do not become 84 one-off implementations.

### 4.1 Shared primitives (must remain stable)
1. rich-text
2. tabs-shell
3. accordion-shell
4. card-grid
5. media-shell
6. resource-list
7. assessment-shell
8. choice-group
9. process-shell
10. node-graph
11. navigation-shell
12. report-shell
13. metric-card
14. scenario-shell
15. interaction-shell
16. accessibility-info
17. feedback-shell
18. gamification-shell

### 4.2 Robustness rules across all templates
1. No renderer should mutate source payload (`courseData` immutable).
2. All interactive state stored in player/runtime state only.
3. All HTML content paths must sanitize unsafe values before injection.
4. All interactions must be keyboard accessible and ARIA-compliant.
5. All score/completion submissions must be idempotent and retry-safe.
6. Unsupported template types must render explicit fallback diagnostics (never silent failure).
7. Renderer output should include machine-readable `data-component-type` attributes for testability.

---

## 5. Backend Recommendations (Actionable)

### Priority P0
1. **Contract lock document** (single source): scoring, completion, export, interaction events.
2. Provide one **fresh generated SCORM package** from current backend branch proving 35+ renderer registry behavior.
3. Add `exportContractVersion` + `supportedTemplateTypes[]` to `course_data.js`.

### Priority P1
4. Keep compatibility aliases for one sprint:
   - `/scoring/calculate` -> `/courses/{courseId}/scoring/calculate`
   - `/completion/mark` -> `/courses/{courseId}/pages/{pageId}/completion`
5. Interaction event type should be open string or include expanded enum (`flip`, `reveal`, `rating`, `acknowledge`, etc.).
6. Return normalized error envelopes across endpoints (field, code, message, details).

### Priority P2
7. Publish canonical JSON schemas for template data per type with schema version.
8. Add server-side idempotency key support for scoring/completion submissions.
9. Expose backend capabilities endpoint:
   - `GET /runtime/capabilities` -> versions, enabled template families, limits.

---

## 6. Frontend Plan Shared to Backend

### Phase A (1 week) - Integration hardening
1. Remove production dependence on legacy `apiService` / `CourseContext` API calls.
2. Complete completion dispatch callsites with real component state snapshots.
3. Add contract smoke tests for scoring/completion/export endpoints.

### Phase B (1-2 weeks) - Template expansion
4. Continue Wave 3 renderers using primitive model (image-hotspots, layered-content, flashcards, transcript-caption, scenario flows).
5. Add interaction handlers for new interactive families (hotspots, branching, drag/drop).
6. Add accessibility parity tests and keyboard interaction tests for each new family.

### Phase C (1 week) - Production readiness
7. End-to-end SCORM run in LMS harness with suspend/resume and completion.
8. Performance validation on heavy media courses.
9. Final release checklist with backend sign-off evidence.

---

## 7. Joint Acceptance Criteria (Go/No-Go)

Release integration is accepted only if all pass:
1. Contract smoke tests are green in CI.
2. Scoring and completion endpoints match frozen schema (no runtime adapters needed).
3. Exported package includes contract version and supported type list.
4. For supported template types, no "unknown"/fallback renderer appears in smoke run.
5. SCORM suspend/resume restores slide index and interaction state.

---

## 8. Open Questions to Backend AI Developer

1. Which scoring contract is final for release: aggregate per course or per-slide single answer?
2. Which completion contract is final: page-scoped component states or generic mark endpoint?
3. Can backend publish schema versioning in export payload this sprint?
4. Is interactionType extensible immediately (open string) or in next release?
5. Can backend provide two sample packages now:
   - assessment-heavy package
   - branching/interactive package

---

## 9. Communication Cadence

1. Daily FE-BE sync: 15 minutes (contract blockers only).
2. Mid-week integration checkpoint: run contract test suite jointly.
3. Weekly TPO gate: demo with evidence (tests + package validation + API logs).

---

## 10. Immediate Next Actions (This Week)

### Backend
1. Respond to section 8 questions with final contract examples.
2. Publish contract lock (OpenAPI snapshot + examples).
3. Deliver fresh generated package proving renderer registry contract.

### Frontend
4. Complete legacy API path deprecation from production routes.
5. Add contract smoke suite for scoring/completion/export.
6. Start Wave 3 primitives with accessibility-first interaction handlers.

---

**TPO Note:** This plan is intentionally generic and robust: template-specific UX can evolve, but contracts, primitives, and compliance gates must stay stable to avoid cross-team regressions.
