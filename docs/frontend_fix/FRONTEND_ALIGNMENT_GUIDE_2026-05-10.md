# Frontend Alignment Guide for Assessment and API Contract

Date: 2026-05-10
Audience: Frontend developer (including AI coding agent)
Goal: Align frontend behavior with completed backend assessment fixes so both sides are stable in authoring, runtime, scoring, and completion.

## 1) What changed in backend and why frontend must update

Backend now enforces and/or supports the following:

- Final assessment is now first-class and validated.
- Runtime supports canonical assessment types and aliases for export.
- MCQ and Multiple Select use explicit submit flow (not instant answer-on-click).
- Fill in blank writes interaction/scoring evidence to SCORM runtime state.
- Final assessment writes mastery score and pass/fail status for SCORM.
- Finish flow blocks completion when required assessment work is missing or final assessment is failed.
- API scoring/completion endpoints expect consistent request shapes and return structured validation envelopes.

If frontend still follows old assumptions, users will see mismatched behavior (for example instant-submit vs submit button, or type naming mismatch).

## 2) Component type mapping and canonicalization

Use these rules in frontend state normalization and renderer selection:

- Preferred canonical runtime types:
  - mcq
  - multiple-select
  - true-false
  - fill-in-blank
  - final-assessment

- Alias compatibility to accept from older content:
  - multi-select maps to multiple-select
  - fill-blanks maps to fill-in-blank

Frontend action:

- Keep a single normalizeComponentType helper used by:
  - authoring preview renderer
  - learner runtime renderer
  - scoring payload builder
- Apply normalization before switch-case rendering and before telemetry/scoring payload generation.

## 3) Authoring contract for Final Assessment

Frontend authoring UI must produce this data shape for type final-assessment:

- Top-level fields:
  - introText: optional string
  - passingScore: integer 0 to 100 (default 80)
  - maxAttempts: integer >= 1 (default 1)
  - shuffleQuestions: boolean (default false)
  - shuffleOptions: boolean (default false)
  - showCorrectAnswers: boolean (default true)
  - questions: array, minimum 1

- Per question required fields:
  - id: string
  - type: one of mcq, true-false, fill-in-blank
  - question: non-empty string

- Per question conditional requirements:
  - If type is mcq:
    - options required, minimum 2
    - at least one option with isCorrect true
  - If type is true-false:
    - correctAnswer required, boolean
    - options may be omitted (runtime can fallback to True/False choices)
  - If type is fill-in-blank:
    - correctAnswers required, non-empty array of accepted strings

Authoring validation should mirror backend to fail fast before save/publish.

## 4) Learner UI behavior updates required

### 4.1 MCQ

- Do not auto-grade on option click.
- Keep option selection local until user presses Submit Answer.
- On submit:
  - lock options
  - show feedback
  - emit scoring/interaction event

### 4.2 Multiple Select

- Checkbox multi-select with explicit Submit Answer button.
- Require at least one selection before submit.
- On submit:
  - evaluate exact match against correct set
  - lock all checkboxes
  - show feedback
  - emit scoring/interaction event

### 4.3 True/False

- Build choices from question.options when present.
- If options missing, synthesize True and False using correctAnswer.
- Keep behavior consistent with MCQ submission pattern in your runtime.

### 4.4 Fill in Blank

- Require non-empty input for check/submit.
- On check/submit:
  - compare against correctAnswers with intended case-sensitivity setting
  - show feedback
  - emit scoring/interaction event

### 4.5 Final Assessment screen

- Render mixed question types in one assessment.
- Require all questions answered before submission.
- On submit:
  - compute score percentage
  - compare score with passingScore
  - show score, passingScore, pass/fail status
  - disable submit for current attempt policy
- Store local submission state so revisit shows previous submission result.

### 4.6 Finish button gating

- Block course finish when:
  - any required assessment slide unanswered
  - any final-assessment submission exists but is failed
- Allow finish when all required assessments are complete and final-assessment passed (if present).

## 5) API contract updates frontend must follow

Base prefix: /api/v1

### 5.1 Create component

Endpoint:
- POST /courses/{courseId}/pages/{pageId}/components

Request body fields:
- componentType: string
- data: object
- completionCriteria: object optional
- audioConfig: object optional
- styling: object optional

Frontend action:
- Send componentType from registry and normalize locally for rendering.
- For assessments, ensure data shape matches section 3 and section 4 rules.

### 5.2 Score calculation endpoint

Endpoint:
- POST /courses/{courseId}/scoring/calculate

Request body:
- answers: array of components
  - componentId: string
  - componentType: string
  - responses: array
    - questionId: string
    - selectedOptionIds: array of string
- attemptNumber: integer

Expected successful response fields:
- totalScore
- maxScore
- percentage
- passed
- passingScore
- componentResults
- attemptNumber
- remainingAttempts

Frontend action:
- Use backend response as source of truth for summary and pass/fail.
- Do not recompute pass/fail differently on frontend.

### 5.3 Page completion write/read

Write endpoint:
- POST /courses/{courseId}/pages/{pageId}/completion

Request body:
- componentStates: array
  - componentId: string
  - completed: boolean
  - interactionsCompleted: array optional
  - audiosCompleted: array optional
  - score: number optional

Read endpoint:
- GET /courses/{courseId}/pages/{pageId}/completion

Course progress endpoint:
- GET /courses/{courseId}/completion

Frontend action:
- After important interactions/submits, post component state updates.
- Use read endpoints to hydrate progress badges and completion bars.

### 5.4 Interaction event endpoint

Endpoint:
- POST /courses/{courseId}/interactions

Request body:
- pageId
- componentId
- interactionType (open string, backend accepts custom values)
- learnerId optional
- completed boolean
- data optional with score, maxScore, isCorrect, duration, value

Frontend action:
- Emit interaction events for submits/checks consistently across assessment components.

## 6) Error handling contract

Backend returns structured error envelopes in detail for 4xx scenarios.

Common examples:
- code: NOT_FOUND
- code: VALIDATION_ERROR
- field: points to invalid path (example answers[].componentId)
- details: extra metadata

Frontend action:
- Build a generic API error parser:
  - Prefer detail.message when available
  - Surface detail.field to form-level errors when possible
  - For NOT_FOUND, show recoverable UX (refresh, navigate back, retry)

## 7) Concrete frontend work plan

### Phase A: Data and API layer

- Add normalizeComponentType helper and apply globally.
- Update scoring payload builder to always send selectedOptionIds as string array.
- Update completion API client to support componentStates shape.
- Standardize API error envelope parser.

### Phase B: Authoring UI

- Add final-assessment editor form with conditional field sets by question type.
- Add inline validation matching backend rules.
- Add type-safe defaults for passingScore, maxAttempts, showCorrectAnswers.

### Phase C: Learner UI

- Refactor MCQ and Multiple Select to explicit submit pattern.
- Add fill-in-blank submit/check state and validation.
- Add final-assessment multi-question submit/result panel.
- Add finish gate checks with clear user messages.

### Phase D: QA automation

- Add tests for:
  - type normalization aliases
  - final-assessment editor validation
  - mcq and multiple-select explicit submit
  - fill-in-blank submit and feedback
  - final-assessment pass/fail + finish gate
  - API error envelope rendering

## 8) Suggested acceptance checklist (frontend + backend integration)

- Create course with final-assessment (mixed mcq, true-false, fill-in-blank) saves successfully.
- Authoring rejects invalid final-assessment shapes before API call.
- Learner MCQ does not score until submit.
- Learner Multiple Select requires submit and disables after submit.
- Fill in blank generates completion/scoring evidence.
- Final assessment computes score and shows pass/fail.
- Finish is blocked when final assessment failed or unanswered required assessments remain.
- Scoring API response matches displayed summary.
- Completion endpoints reflect learner progress correctly after events.
- Error envelope fields are shown in frontend UX without generic unknown failures.

## 9) Handoff note for AI frontend developer

When implementing, prioritize preserving existing UI styles while changing behavior flows. Apply changes behind feature-safe utility functions first (type normalization, API parser), then migrate component UIs one-by-one to reduce regressions.
