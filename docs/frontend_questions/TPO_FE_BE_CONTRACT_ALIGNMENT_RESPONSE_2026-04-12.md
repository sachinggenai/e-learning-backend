# TPO Detailed FE-BE Contract Alignment Response

Date: 2026-04-12  
Owner: TPO  
Audience: Frontend AI Developer, Backend AI Developer, QA  
Status: Proposed for joint sign-off before implementation

---

## 1. Purpose

This document is the detailed response to frontend questions and alignment concerns.

Goal:
1. Confirm what is already true in backend today.
2. State where FE and BE are aligned.
3. State where I disagree (or partially disagree), with reasons.
4. Define exact decisions and acceptance gates so both teams can start implementation only after explicit agreement.

---

## 2. Source of Truth Used For This Response

Backend contracts were verified from current code, not assumptions:
1. app/routers/scoring_completion.py
2. app/main.py
3. app/services/scorm_export.py
4. app/routers/export.py

This response is based on those files as of 2026-04-12.

---

## 3. Contract Reality Check (What Backend Actually Exposes)

## 3.1 API base prefix

Backend mounts APIs under:
1. /api/v1

Implication for FE:
1. All service calls must include /api/v1 prefix.

## 3.2 Scoring endpoints (implemented)

1. GET /api/v1/courses/{courseId}/scoring
2. PATCH /api/v1/courses/{courseId}/scoring
3. POST /api/v1/courses/{courseId}/scoring/validate
4. POST /api/v1/courses/{courseId}/scoring/calculate

POST calculate request shape:
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

POST calculate response shape:
```json
{
  "totalScore": 80.0,
  "maxScore": 100.0,
  "percentage": 80.0,
  "passed": true,
  "passingScore": 70,
  "componentResults": [
    {
      "componentId": "cmp-1",
      "componentType": "mcq",
      "score": 80.0,
      "maxScore": 100.0,
      "weight": 1.0,
      "weightedScore": 80.0,
      "questionResults": [
        {
          "questionId": "q1",
          "correct": true,
          "score": 80.0,
          "maxScore": 100.0,
          "partialCredit": false
        }
      ]
    }
  ],
  "attemptNumber": 1,
  "remainingAttempts": null
}
```

## 3.3 Completion endpoints (implemented)

1. GET /api/v1/courses/{courseId}/completion
2. GET /api/v1/courses/{courseId}/pages/{pageId}/completion
3. POST /api/v1/courses/{courseId}/pages/{pageId}/completion

POST page completion request shape:
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

## 3.4 Interaction endpoint (implemented)

1. POST /api/v1/courses/{courseId}/interactions

Important:
1. interactionType is open string now.
2. FE can send new values without backend enum change.

## 3.5 Export endpoint (implemented)

1. POST /api/v1/export/scorm/{courseId}?format=scorm_1_2

SCORM package outputs include:
1. index.html
2. course_data.js
3. styles.css
4. scorm_wrapper.js

In current exporter:
1. Player registry uses getRenderer(type) mapping (dispatch table style).
2. runtime_supported_template_types exists in backend validation.
3. course_data.js currently defines var courseData = {...}.

Not currently guaranteed in payload:
1. exportContractVersion field
2. supportedTemplateTypes field

---

## 4. Decision Matrix: Agree / Not Agree / Partial

## 4.1 Keep FE service-layer as canonical path

Decision: Agree  
Why:
1. Keeps API handling centralized.
2. Enables consistent retries/error mapping.
3. Prevents endpoint drift across components.

Action:
1. FE keeps src/services as the only production API path.

## 4.2 Treat docs/exported-zip artifacts as evidence only

Decision: Agree  
Why:
1. Generated artifacts become stale quickly.
2. Runtime behavior should be validated from current backend exports.

Action:
1. FE must not copy logic from old exported zips.
2. Use fresh export package from active backend branch for checks.

## 4.3 Lock one API shape per domain before expansion

Decision: Agree  
Why:
1. Prevents adapter code explosion.
2. Avoids FE implementing temporary shapes that later break.

Action:
1. Freeze scoring and completion contracts in one signed note (this doc + API examples).

## 4.4 Canonical scoring style: aggregate course-scoped

Decision: Agree  
Why:
1. Backend already implements aggregate component response scoring.
2. Supports multi-question/multi-component pages cleanly.
3. Better fit for final assessments and weighted scoring.

Action:
1. FE uses POST /api/v1/courses/{courseId}/scoring/calculate as canonical.

## 4.5 Canonical completion style: page-scoped component states

Decision: Agree  
Why:
1. Backend already evaluates page completion strategy (all/any/percentage/custom).
2. Deterministic page completion needs component state context.
3. Matches FE interaction model better than generic mark endpoint.

Action:
1. FE uses POST /api/v1/courses/{courseId}/pages/{pageId}/completion as canonical.

## 4.6 Require temporary alias endpoints for one sprint

Decision: Partial / Usually Not Needed  
Why I do not fully agree:
1. Canonical endpoints already exist and are implemented.
2. Alias endpoints increase maintenance and ambiguity.
3. Team may accidentally split traffic across two contracts.

When alias can be accepted:
1. Only if FE has hard deadline and existing production callers cannot migrate in time.
2. Alias must have fixed deprecation date and usage telemetry.

Recommendation:
1. Prefer FE adapter migration over API alias creation.
2. If alias is unavoidable, document EOL date now.

## 4.7 Export payload should include version + supported type list

Decision: Agree (P0 improvement)  
Why:
1. FE can verify compatibility at runtime.
2. Reduces unknown-template surprises.
3. Enables safe feature flags by version.

Action for BE:
1. Add courseData.exportContractVersion.
2. Add courseData.supportedTemplateTypes as emitted list.

Action for FE now:
1. Parse these fields as optional today.
2. If absent, fallback gracefully.

## 4.8 Concern that exported player still has limited branch dispatch

Decision: Not agreed for current backend state  
Why:
1. Current exporter contains getRenderer(type) registry mapping and expanded renderer set.
2. Risk statement likely based on stale artifact, not latest generated package.

Action:
1. Regenerate package from latest branch and re-validate before FE starts.

## 4.9 interactionType extensible now or next release

Decision: Agree it is extensible now  
Why:
1. Backend DTO accepts string interactionType.
2. Backend comments explicitly state open string and examples.

Action:
1. FE can proceed with additional interaction types immediately.

---

## 5. Recommended Final Contract Lock (To Sign)

Use this exact lock unless both teams jointly approve a revision.

## 5.1 Scoring lock

Endpoint:
1. POST /api/v1/courses/{courseId}/scoring/calculate

Request:
1. answers[] with componentId, componentType, responses[]
2. attemptNumber integer

Response:
1. totalScore, maxScore, percentage, passed, passingScore
2. componentResults[] with questionResults[]
3. attemptNumber, remainingAttempts

## 5.2 Completion lock

Endpoint:
1. POST /api/v1/courses/{courseId}/pages/{pageId}/completion

Request:
1. componentStates[] with componentId, completed, optional interactionsCompleted, audiosCompleted, score

Response:
1. pageId, title, completed, strategy, components[]

## 5.3 Interactions lock

Endpoint:
1. POST /api/v1/courses/{courseId}/interactions

Contract:
1. interactionType is open string.
2. data fields optional (score, maxScore, duration, etc.).

## 5.4 Export lock

Endpoint:
1. POST /api/v1/export/scorm/{courseId}?format=scorm_1_2

Payload guarantees:
1. course_data.js includes courseData object with templates.
2. Player renderer lookup via getRenderer(type).

Requested near-term additions:
1. exportContractVersion
2. supportedTemplateTypes

---

## 6. Why These Decisions Reduce Risk

1. One scoring shape prevents FE branching by template family.
2. Page-scoped completion supports deterministic completion strategies without ad-hoc logic.
3. Open interactionType lets FE ship richer telemetry without BE release blockers.
4. Export version/type metadata lets FE fail fast and degrade safely.
5. Avoiding aliases keeps implementation simple and observable.

---

## 7. Items To Resolve Before Coding Starts

These must be answered explicitly in joint sync:
1. Do we require alias endpoints, or will FE migrate directly to canonical contracts?
2. Will BE add exportContractVersion and supportedTemplateTypes in this sprint?
3. Which sample packages will BE deliver first: assessment-heavy or branching-heavy?
4. What is FE fallback UX for unsupported template type in runtime?
5. What is final error envelope shape for FE toast/form handling?

---

## 8. Joint Acceptance Checklist (Go / No-Go)

Go only if all are true:
1. FE and BE both approve section 5 contract lock.
2. Contract smoke tests pass in CI against canonical endpoints.
3. Fresh exported SCORM package validates getRenderer dispatch and expected types.
4. Unsupported template type renders explicit fallback UI (no silent failure).
5. Completion and scoring retries are idempotent in FE behavior.
6. Suspend/resume restores position and interaction state in LMS harness.

No-Go if any fail:
1. FE still uses mixed legacy + canonical API flows.
2. Contract mismatch requires runtime adapters for basic requests.
3. Export package from latest backend branch is unavailable.

---

## 9. Message To Frontend AI Developer

You can proceed once this contract lock is accepted.

Implementation order:
1. Lock service clients to canonical endpoints in section 5.
2. Add contract smoke tests first.
3. Implement template families using primitive architecture.
4. Add robust fallback renderer and accessibility checks.
5. Integrate scoring/completion submissions only through service layer.

Do not:
1. Build against stale exported artifacts.
2. Depend on alias endpoints unless explicitly approved.
3. Hardcode endpoint shapes outside services.

---

## 10. Message To Backend AI Developer

Required before FE implementation starts:
1. Confirm section 5 as final contract.
2. Provide two fresh SCORM sample packages from current branch.
3. Confirm timeline for exportContractVersion and supportedTemplateTypes fields.
4. Provide one OpenAPI snapshot or request/response examples matching canonical routes.

---

## 11. Sign-off Block

Frontend AI Developer:
1. Name:
2. Date:
3. Approved / Changes requested:
4. Notes:

Backend AI Developer:
1. Name:
2. Date:
3. Approved / Changes requested:
4. Notes:

TPO:
1. Name:
2. Date:
3. Final decision:
4. Implementation start approved: Yes / No

---

End of document.
