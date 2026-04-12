# Final Response to Backend AI Developer (TPO)

**Date:** 2026-04-12  
**From:** Frontend TPO  
**To:** Backend AI Developer  
**Status:** Approved with targeted action items

---

## 1. TPO Decision

We reviewed your alignment response and accept the proposed canonical contracts. Frontend implementation can proceed under the contract lock below, with a few mandatory backend follow-ups.

---

## 2. Contract Lock Confirmed

### 2.1 Scoring (Canonical)
Use:
- `POST /api/v1/courses/{courseId}/scoring/calculate`

Request model:
- `answers[]` (componentId, componentType, responses[])
- optional `attemptNumber`

Response model:
- `totalScore`, `maxScore`, `percentage`, `passed`, `passingScore`
- `componentResults[]`, `questionResults[]`
- `attemptNumber`, `remainingAttempts`

### 2.2 Completion (Canonical)
Use:
- `POST /api/v1/courses/{courseId}/pages/{pageId}/completion`

Request model:
- `componentStates[]` with optional interaction/audio/score detail

Response model:
- `pageId`, `title`, `completed`, `strategy`, `components[]`

### 2.3 Interactions
Use:
- `POST /api/v1/courses/{courseId}/interactions`

Decision:
- `interactionType` is open string and can be extended without API enum release.

### 2.4 Export
Use:
- `POST /api/v1/export/scorm/{courseId}?format=scorm_1_2`

Expected generated assets:
- `index.html`, `course_data.js`, `styles.css`, `scorm_wrapper.js`

---

## 3. Backend Follow-Ups Required (Mandatory)

### P0 (must complete now)
1. Provide one fresh generated SCORM package from latest backend branch proving current renderer dispatch behavior.
2. Confirm `Player.getRenderer(type)` is present and used as canonical dispatch in generated output.
3. Publish signed contract examples (request/response) for scoring + completion + interactions + export.

### P1 (next sprint target)
4. Add `courseData.exportContractVersion` to generated `course_data.js`.
5. Add `courseData.supportedTemplateTypes[]` to generated `course_data.js`.
6. Normalize error envelope shape across scoring/completion/export endpoints.

### P2 (stability hardening)
7. Publish per-template JSON schema versioning policy.
8. Add idempotency strategy guidance for scoring/completion retries.

---

## 4. Position on Alias Endpoints

We agree with your stance that aliases are usually unnecessary if canonical routes are stable and FE migration is immediate.

Decision:
1. Default: no alias endpoints.
2. Exception: only if migration blocker appears, with fixed expiry and usage telemetry.

---

## 5. Frontend Commitments (for Backend Visibility)

Frontend commits to:
1. Use service-layer only as canonical integration path.
2. Remove production reliance on legacy API paths.
3. Add contract smoke tests before broad template expansion.
4. Continue primitive-based runtime rollout for generic, robust support across template families.
5. Keep explicit fallback renderer behavior for unsupported template types.

---

## 6. Joint Go/No-Go Gates

Go only when all are true:
1. Both teams sign this contract lock.
2. Canonical endpoint tests pass in CI.
3. Fresh package from latest backend validates expected dispatch and template support.
4. Completion + scoring integration runs end-to-end with retry-safe behavior.
5. Suspend/resume behavior validated in LMS harness.

No-Go if any fail:
1. Contract ambiguity persists.
2. Generated package does not match claimed runtime contract.
3. FE must branch logic per endpoint variant.

---

## 7. Immediate Backend Response Requested

Please reply with:
1. Confirmation that Section 2 is final and release-canonical.
2. Delivery path to fresh sample packages (assessment-heavy + branching-heavy preferred).
3. ETA for `exportContractVersion` and `supportedTemplateTypes[]` fields.
4. Final error envelope example to be consumed by FE toast/form handlers.

---

## 8. Sign-Off

Backend AI Developer:
- Approved / Changes requested:
- Notes:

Frontend AI Developer:
- Approved / Changes requested:
- Notes:

TPO:
- Final status: Approved with actions
- Implementation start allowed: Yes (after P0 confirmations)

---

End of response.
