# Formal Implementation Execution Plan
## FE-BE SCORM Contract Rollout Plan

Date: 2026-04-12  
Owner: TPO  
Audience: Frontend AI Developer, Backend AI Developer, QA  
Status: Approved for execution

---

## 1. Purpose

This plan operationalizes the signed contract into an execution sequence with owners, dates, deliverables, and go/no-go gates.

Primary outcomes:

1. Deliver Phase 1 MVP by 2026-04-26 without contract drift.
2. Complete backend P0 commitments on schedule.
3. Validate FE-BE integration end-to-end before broad template expansion.

---

## 2. Scope

### In Scope

1. Canonical endpoint integration.
2. Export metadata contract updates.
3. Sample package delivery and validation.
4. FE runtime implementation across Phase 1 to Phase 3.
5. QA contract, runtime, and LMS validation.

### Out of Scope

1. New alias endpoint creation unless approved via blocker exception.
2. Non-canonical API experimentation in production paths.
3. Post-MVP enhancement requests outside timeline.

---

## 3. Contract Baseline (Frozen)

Canonical endpoints:

1. POST /api/v1/courses/{courseId}/scoring/calculate
2. POST /api/v1/courses/{courseId}/pages/{pageId}/completion
3. POST /api/v1/courses/{courseId}/interactions
4. POST /api/v1/export/scorm/{courseId}?format=scorm_1_2

Contract rules:

1. FE service-layer path is canonical integration layer.
2. No alias endpoints by default.
3. Unsupported template types must render explicit fallback UI.
4. Integration must remain idempotent and retry-safe.

---

## 4. Workstreams and Owners

1. Backend Workstream
   Owner: Backend AI Developer
2. Frontend Workstream
   Owner: Frontend AI Developer
3. QA Workstream
   Owner: QA Lead
4. Governance Workstream
   Owner: TPO

---

## 5. Milestone Timeline

### Milestone A: Contract Activation
Window: 2026-04-12 to 2026-04-14

Deliverables:

1. Three-way sign-off complete.
2. FE smoke test skeleton committed.
3. Backend P0 development branch active.

Exit criteria:

1. Contract acknowledged by FE/BE/TPO.
2. Canonical endpoint routing locked in FE services.

### Milestone B: P0 Delivery + MVP Integration
Window: 2026-04-15 to 2026-04-26

Backend deliverables:

1. exportContractVersion in course_data.js by 2026-04-15.
2. supportedTemplateTypes[] in course_data.js by 2026-04-15.
3. Two fresh sample packages by 2026-04-19.

Frontend deliverables:

1. Phase 1 MVP components complete by 2026-04-26.
2. Contract smoke tests passing against canonical endpoints.
3. Fallback renderer behavior verified.

Exit criteria:

1. Sample packages validated successfully.
2. MVP staging build accepted.

### Milestone C: Stabilization + Extended Content
Window: 2026-04-26 to 2026-05-10

Backend deliverables:

1. Normalized error envelope across scoring/completion/export by 2026-04-22 (carried into this cycle for FE adoption).

Frontend deliverables:

1. Flashcard, scenario, video/media, and data-table support.
2. FE adapter aligned to normalized error envelope.
3. Accessibility regression checks for interactive templates.

Exit criteria:

1. Extended component suite functional.
2. Error handling stable across canonical APIs.

### Milestone D: Release Hardening
Window: 2026-05-10 to 2026-05-24

Deliverables:

1. LMS suspend/resume validation complete.
2. Cross-browser compatibility verified.
3. Performance baseline and remediation complete.
4. Release candidate approved for production.

Exit criteria:

1. Go-live checklist complete.
2. Final TPO release approval granted.

---

## 6. Detailed Task Plan

### 6.1 Backend Task Plan

1. Add exportContractVersion field to generated course_data.js.
2. Add supportedTemplateTypes[] emission based on runtime-supported registry.
3. Generate assessment-heavy sample package from latest backend branch.
4. Generate branching-heavy sample package from latest backend branch.
5. Standardize error envelope shape for scoring/completion/export.
6. Publish canonical request/response examples aligned to production behavior.

### 6.2 Frontend Task Plan

1. Ensure all scoring/completion/interaction/export calls route through service layer.
2. Remove production dependency on legacy API pathways.
3. Implement MVP component set for Phase 1.
4. Add explicit unsupported-template fallback renderer.
5. Add and pass contract smoke tests.
6. Implement retry-safe request handling and idempotent state transitions.

### 6.3 QA Task Plan

1. Validate canonical endpoint contract responses.
2. Validate export package structure and runtime dispatch behavior.
3. Verify fallback behavior for unsupported templates.
4. Validate suspend/resume behavior in LMS harness.
5. Execute accessibility checks on keyboard and ARIA interaction flows.

### 6.4 Governance Task Plan

1. Run daily blocker sync during Milestone B.
2. Run weekly checkpoint for milestone gate decisions.
3. Maintain decision log for any contract exceptions.
4. Enforce no-go if required gates fail.

---

## 7. Go/No-Go Gates

Go only if all conditions are true:

1. Canonical endpoint smoke tests are green.
2. Backend P0 payload fields are present in generated exports.
3. Fresh sample packages are delivered and validated.
4. Player.getRenderer(type) dispatch behavior is confirmed in generated package.
5. Three-way sign-off is complete.

No-Go if any condition is false:

1. Missing P0 field delivery by target date.
2. Missing sample package artifacts by target date.
3. FE requires endpoint branching for baseline flows.
4. Unsupported template types fail without fallback UI.

---

## 8. Risk Register and Mitigation

1. Risk: Sample package delivery delay.
   Mitigation: FE develops using canonical mocks; BE provides interim package ETA updates.

2. Risk: Error envelope mismatch during transition.
   Mitigation: FE adapter temporarily supports old and new envelope until cutoff.

3. Risk: Template type drift between export and runtime support.
   Mitigation: Enforce supportedTemplateTypes[] validation and fallback telemetry.

4. Risk: LMS runtime behavior variance.
   Mitigation: Early LMS harness run and regression replay before release hardening.

---

## 9. Communication and Governance Cadence

1. Daily sync (15 min): FE-BE blocker triage.
2. Mid-week checkpoint: contract smoke suite review.
3. Weekly TPO gate: evidence review and milestone decision.
4. Escalation SLA: critical blocker response within 4 business hours.

---

## 10. Definition of Done

Implementation is complete when:

1. Phase 1 to Phase 3 deliverables are complete.
2. Canonical contracts are honored without runtime adapters.
3. Export metadata fields and sample package evidence are validated.
4. Accessibility and LMS suspend/resume checks pass.
5. Release candidate receives TPO approval.

---

## 11. Sign-Off Block

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
4. Execution start approved: Yes / No

---

End of plan.
