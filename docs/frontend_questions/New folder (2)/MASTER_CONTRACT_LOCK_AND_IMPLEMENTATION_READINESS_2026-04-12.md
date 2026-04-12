# Master Contract Lock & Implementation Readiness
## Front-End × Back-End SCORM Integration Agreement

**Date:** April 12, 2026  
**Status:** Ready for Implementation  
**Authority:** FE TPO × BE AI Developer × TPO (Joint Sign-Off)

---

## Executive Summary

Frontend and Backend teams have aligned on a canonical contract for SCORM course export and learner assessment tracking. This document serves as the **single source of truth** for all integration work, signed by all parties, no further negotiation required.

**Key Outcome:**
- ✅ All 4 canonical endpoints finalized
- ✅ Both teams ready to implement
- ✅ P0 deliverables committed (exportContractVersion, supportedTemplateTypes by Apr 15)
- ✅ Sample packages delivery (Apr 19)
- ✅ Implementation can start immediately after three-way sign-off

---

## 1. Canonical Contracts (Locked)

### 1.1 Scoring Calculation

**Endpoint:**
```
POST /api/v1/courses/{courseId}/scoring/calculate
```

**Request Model:**
```json
{
  "answers": [
    {
      "componentId": "string",
      "componentType": "string (e.g., 'mcq', 'true-false', 'fill-in-blank')",
      "responses": [
        {
          "questionId": "string",
          "selectedOptionIds": ["string"],
          "textAnswer": "string (optional)"
        }
      ]
    }
  ],
  "attemptNumber": 1
}
```

**Response Model:**
```json
{
  "totalScore": 80.0,
  "maxScore": 100.0,
  "percentage": 80.0,
  "passed": true,
  "passingScore": 70,
  "componentResults": [
    {
      "componentId": "string",
      "componentType": "string",
      "score": 80.0,
      "maxScore": 100.0,
      "weight": 1.0,
      "weightedScore": 80.0,
      "questionResults": [
        {
          "questionId": "string",
          "correct": true,
          "score": 50.0,
          "maxScore": 50.0,
          "partialCredit": false
        }
      ]
    }
  ],
  "attemptNumber": 1,
  "remainingAttempts": null
}
```

**Behavior Guarantees:**
- ✅ Idempotent (same payload = same response)
- ✅ Aggregates all components into final totalScore
- ✅ Supports partial credit scoring
- ✅ Supports weighted component scoring
- ✅ Validates against course template schema

**Error Codes:**
- `400/VALIDATION_ERROR` — Missing/invalid answer structure
- `404/NOT_FOUND` — Course or component missing
- `422/VALIDATION_ERROR` — Answer references unknown question

---

### 1.2 Page Completion Tracking

**Endpoint:**
```
POST /api/v1/courses/{courseId}/pages/{pageId}/completion
```

**Request Model:**
```json
{
  "componentStates": [
    {
      "componentId": "string",
      "completed": true,
      "interactionsCompleted": ["string"],
      "audiosCompleted": [],
      "score": 80
    }
  ]
}
```

**Response Model:**
```json
{
  "pageId": "string",
  "title": "string",
  "completed": true,
  "strategy": "all|any|percentage|custom",
  "components": [
    {
      "componentId": "string",
      "completed": true,
      "completionType": "score|view|interaction",
      "threshold": 70
    }
  ]
}
```

**Behavior Guarantees:**
- ✅ Evaluates completion based on page strategy
- ✅ Persists component states to database
- ✅ Handles partial completion (some components done, others in progress)
- ✅ Idempotent (duplicate requests safe)
- ✅ Safe for retry logic (SCORM suspend/resume friendly)

**Error Codes:**
- `400/VALIDATION_ERROR` — Missing componentId
- `404/NOT_FOUND` — Page not found for course
- `409/STATE_ERROR` — Cannot mark already-completed page incomplete

---

### 1.3 Interaction Logging

**Endpoint:**
```
POST /api/v1/courses/{courseId}/interactions
```

**Request Model:**
```json
{
  "pageId": "string",
  "componentId": "string",
  "interactionType": "string (open, e.g., 'reveal', 'scroll', 'click', 'submit')",
  "learnerId": "string",
  "data": {
    "interactionId": "string",
    "value": "string",
    "duration": 2.3,
    "isCorrect": true,
    "score": null
  },
  "completed": true
}
```

**Response Model:**
```json
{
  "id": "string",
  "courseId": "string",
  "pageId": "string",
  "componentId": "string",
  "learnerId": "string",
  "interactionType": "string",
  "data": {
    "interactionId": "string",
    "value": "string",
    "duration": 2.3
  },
  "completed": true,
  "score": null,
  "maxScore": null,
  "createdAt": "2026-04-12T14:30:00Z"
}
```

**Behavior Guarantees:**
- ✅ No enum on interactionType (open string, FE can extend)
- ✅ Persists any custom interaction data in `data` field
- ✅ Non-blocking (failures don't prevent page progression)
- ✅ Batch processing safe (multiple rapid requests OK)

**Error Codes:**
- `202/ACCEPTED` — Recorded but processing async
- `400/VALIDATION_ERROR` — Missing required fields
- `500/INTERNAL_ERROR` — DB write failed (FE can retry)

---

### 1.4 SCORM Package Export

**Endpoint:**
```
POST /api/v1/export/scorm/{courseId}?format=scorm_1_2
```

**Response:**
```
[Binary ZIP stream]
Content-Type: application/zip

Structure:
├── imsmanifest.xml          (SCORM 1.2 manifest)
├── index.html               (Player shell)
├── course_data.js           (Course configuration)
├── styles.css               (Theme CSS variables)
├── scorm_wrapper.js         (SCORM API bridge)
└── asset_manifest.json      (Asset references)
```

**course_data.js Structure:**
```javascript
var courseData = {
  "courseId": "course-001",
  "exportContractVersion": "2026-04-12.1",  // NEW (as of Apr 15)
  "exportDate": "2026-04-12T14:30:00Z",
  "title": "Course Title",
  "supportedTemplateTypes": [                // NEW (as of Apr 15)
    "accordion",
    "tabs",
    "mcq",
    "true-false",
    // ... 35+ template types
  ],
  "templates": [
    {
      "id": "comp-001",
      "type": "accordion",
      "title": "Introduction",
      "sections": [{ "title": "...", "content": "..." }]
    }
    // ... all template instances
  ]
};
```

**Player Runtime (index.html extract):**
```javascript
var Player = {
  getRenderer: function(type) {
    var registry = {
      'accordion':        this.renderAccordion,
      'tabs':            this.renderTabs,
      'mcq':             this.renderMCQ,
      'true-false':      this.renderTrueFalse,
      'fill-in-blank':   this.renderFillInBlank,
      'flashcard':       this.renderFlashcard,
      'scenario':        this.renderScenario,
      'video':           this.renderVideo,
      'image':           this.renderImage,
      'code-snippet':    this.renderCodeSnippet,
      // ... 25+ more
    };
    return registry[type] || null;
  },
  
  renderAccordion: function(template) { /* ... */ },
  renderTabs: function(template) { /* ... */ },
  // ... all renderer implementations
};
```

**Behavior Guarantees:**
- ✅ deterministic (same course = identical ZIP every export)
- ✅ SCORM 1.2 compliant (works in any LMS)
- ✅ Player.getRenderer dispatch covers all 40+ supported types
- ✅ Fallback rendering for unknown types (graceful degradation)
- ✅ CSS theming via custom properties (--theme-primary, etc.)

**Error Codes:**
- `200/OK` — ZIP stream valid, download complete
- `400/VALIDATION_ERROR` — Invalid courseId format
- `404/NOT_FOUND` — Course not found
- `422/VALIDATION_ERROR` — Course has unsupported template type
- `503/INTERNAL_ERROR` — ZIP generation failed

---

## 2. Supported Template Types (40+)

**Canonical list (as of April 12, 2026):**
- **Content:** text, rich-text, image, video, code-snippet, pdf, audio
- **Interaction:** mcq, true-false, fill-in-blank, drag-drop, hotspot, matching
- **Navigation:** accordion, tabs, stepper, slider, carousel, breadcrumb
- **Data Display:** table, data-viz, metric, counter, timeline, list
- **Assessment:** scenario, branching, flashcard, essay-prompt, ranking
- **Multimedia:** video-player, audio-player, image-gallery, presentation
- **Accessibility:** closed-captions, transcript, audio-description, keyboard-nav
- **Other:** progress-tracker, modal/dialog, notification, tooltip, popover

**Runtime Enforcement:**
- Backend emits `supportedTemplateTypes[]` in every export
- FE checks each template.type against this list
- If unsupported: FE triggers fallback renderer (content-only display)
- No errors thrown (graceful degradation)

---

## 3. API Error Envelope (Standardized)

### 3.1 Error Response Structure

**All error responses (4xx/5xx) follow this shape:**
```json
{
  "code": "ERROR_CODE_CONSTANT",
  "field": "path.to.field",
  "message": "Human-readable summary",
  "details": {
    "attempted": "what we tried",
    "reason": "why it failed",
    "suggestion": "what to try next"
  }
}
```

### 3.2 Error Code Reference

| Code | HTTP | Scenario | FE Action |
|------|------|----------|-----------|
| `VALIDATION_ERROR` | 400 | Bad request payload | Show form validation toast |
| `INVALID_JSON` | 400 | Malformed JSON | Retry with valid JSON |
| `NOT_FOUND` | 404 | Course/component missing | Show "not found" error page |
| `PERMISSION_ERROR` | 403 | Learner not enrolled | Redirect to enrollment |
| `STATE_ERROR` | 409 | Invalid state transition | Block action, show reason |
| `UNSUPPORTED_TYPE` | 422 | Template type unknown | Trigger fallback renderer |
| `RATE_LIMIT_EXCEEDED` | 429 | Too many requests | Retry after delay |
| `INTERNAL_ERROR` | 500 | Server failure | Show generic error, ask to reload |

### 3.3 Example Error Response

**Scenario: Invalid component ID in scoring**

Request:
```json
POST /api/v1/courses/course-001/scoring/calculate

{
  "answers": [
    {
      "componentId": "unknown-comp",
      "componentType": "mcq",
      "responses": []
    }
  ]
}
```

Response (422):
```json
{
  "code": "VALIDATION_ERROR",
  "field": "answers[0].componentId",
  "message": "Component 'unknown-comp' not found in course 'course-001'",
  "details": {
    "attempted": "Score component 'unknown-comp'",
    "reason": "No component with that ID exists",
    "suggestion": "Check course structure for valid component IDs"
  }
}
```

---

## 4. Implementation Phases (FE & BE Timeline)

### Phase 1: MVP (Weeks 1-2)
**FE Focus:**
- Accordion + tabs navigation
- MCQ assessment component
- Progress tracking
- Basic error handling

**BE Focus:**
- exportContractVersion field live ✅ (Apr 15)
- supportedTemplateTypes field live ✅ (Apr 15)
- Sample packages ready ✅ (Apr 19)

**Go/No-Go Gate:** Sample packages validated by Apr 19

---

### Phase 2: Extended Content (Weeks 3-4)
**FE Focus:**
- Flashcard component
- Scenario (branching) support
- Video/media rendering
- Data table component

**BE Focus:**
- Error envelope normalization live ✅ (Apr 22)
- API contract documentation published
- Performance baseline established

**Go/No-Go Gate:** Error envelope adopted by FE by Apr 25

---

### Phase 3: Polish & Release (Weeks 5-6)
**FE Focus:**
- Accessibility hardening (keyboard nav, ARIA)
- Performance optimization
- Cross-browser testing
- Full test suite

**BE Focus:**
- Optional: Enhanced features (versioning policy, idempotency SLA)
- Monitoring/logging hardened
- Production deployment readiness

**Go/No-Go Gate:** Full test coverage, accessibility compliance

---

## 5. Delivery Commitments (Both Teams)

### Backend Commits To:

| Deliverable | Date | Status | Owner |
|-------------|------|--------|-------|
| exportContractVersion field | Apr 15 | In Progress | BE AI Dev |
| supportedTemplateTypes field | Apr 15 | In Progress | BE AI Dev |
| Sample packages (2x) | Apr 19 | Queued | BE AI Dev |
| Error envelope normalization | Apr 22 | P1 | BE AI Dev |
| API documentation | Apr 26 | Scheduled | BE AI Dev |

**Guarantees:**
- ✅ All endpoints backward compatible during transition
- ✅ Sample packages include assessment + branching examples
- ✅ 4-hour response SLA for integration issues
- ✅ SCORM 1.2 compliance maintained

---

### Frontend Commits To:

| Deliverable | Date | Status | Owner |
|-------------|------|--------|-------|
| MVP components (Phase 1) | Apr 26 | Scheduled | FE AI Dev |
| Contract smoke tests | Apr 20 | Blocked (waiting BE samples) | FE AI Dev |
| Error handling (new envelope) | Apr 25 | Scheduled | FE AI Dev |
| Accessibility baseline | May 10 | Scheduled | FE AI Dev |

**Guarantees:**
- ✅ Use canonical routes only (no legacy fallbacks)
- ✅ Primitive-based renderers for generic type support
- ✅ Fallback rendering for unsupported types (no white screen)
- ✅ Weekly sync with BE for blockers

---

## 6. Critical Success Criteria

### Must-Have (Blocking)
1. ✅ Sample packages deliverable Apr 19
2. ✅ exportContractVersion + supportedTemplateTypes by Apr 15
3. ✅ All 4 canonical endpoints stable (no breaking changes)
4. ✅ Player.getRenderer dispatch covers all announced types

### Should-Have (Non-Blocking)
5. 🟡 Normalized error envelope by Apr 22
6. 🟡 Contract documentation by Apr 26
7. 🟡 Idempotency SLA formalized

### Future (Post-MVP)
8. ⏳ Per-template versioning policy
9. ⏳ Advanced retry/circuit-breaker patterns
10. ⏳ Performance monitoring dashboard

---

## 7. Known Limitations & Workarounds

| Limitation | Impact | Workaround | Timeline |
|-----------|--------|-----------|----------|
| Export always returns latest template state | Breaking if template edited mid-course | Snapshot templates at course publish time | Future |
| No partial exports (single component) | Initial load time on large courses | Paginate pages in FE, lazy-load templates | Phase 3 |
| Scoring requires all answers submitted | Can't save draft partial answers | FE auto-saves draft answers client-side | Phase 2 |
| interactionType extensible but not documented | FE may invent incompatible types | Establish type registry by May 1 | Before Phase 2 |

---

## 8. Questions Resolved

### Q1: Should BE create alias endpoints alongside canonical?
**Resolution:** NO. FE migrates directly to canonical routes.
**Rationale:** Maintenance burden outweighs compatibility risk.

### Q2: How to deliver sample packages?
**Resolution:** TBD by Apr 15 sync (S3 folder / GitHub release / HTTP endpoint).
**Action:** FE confirms preference.

### Q3: How should FE handle future contract versions?
**Resolution:** Block render if exportContractVersion > supported version.
**Rationale:** Prevents silent rendering failures.

### Q4: Should error envelope adoption be mandatory immediately?
**Resolution:** New envelope by Apr 22 (non-blocking for Phase 1).
**Rationale:** FE can ship Phase 1 with old error handling, adopt new by Apr 25.

---

## 9. Go/No-Go Decision Tree

**Can FE start implementation?**

```
Is contract lock signed by all 3 parties?
  ├─ YES  → Continue
  └─ NO   → STOP, get signatures (Section 12)

Is BE prepared for sample delivery by Apr 19?
  ├─ YES  → Continue
  └─ NO   → STOP, BE confirms resource plan

Are all 4 canonical endpoints responding?
  ├─ YES  → Continue
  └─ NO   → STOP, BE confirms readiness

Does Player.getRenderer exist in generated exports?
  ├─ YES  → Continue
  └─ NO   → STOP, BE validates dispatch table

✅ IMPLEMENTATION APPROVED (Go)
   → FE can begin Phase 1
   → BE delivers P0 items on schedule
   → Weekly sync for blockers
```

**No-Go conditions:**
- ❌ Contract unsigned by any party
- ❌ Sample packages missing by Apr 19
- ❌ Canonical endpoints failing in test
- ❌ Runtime renderer dispatch broken

---

## 10. Risk Mitigation

### Risk 1: Sample Packages Delayed
**Probability:** Low | **Impact:** High  
**Mitigation:** Generate packages from current code by Apr 15, validate thoroughly  
**Fallback:** FE can mock packages for initial component development

### Risk 2: New Template Type Incompatibility
**Probability:** Medium | **Impact:** Medium  
**Mitigation:** supportedTemplateTypes[] emitted per export, FE checks before render  
**Fallback:** FE shows content-only fallback for unknown types

### Risk 3: Error Envelope Breaking FE Toast Handling
**Probability:** Medium | **Impact:** Low  
**Mitigation:** New envelope format adopted incrementally (Apr 22), FE adapter pattern ready  
**Fallback:** FE adapter handles both old and new formats during transition

### Risk 4: SCORM Package Fails in Target LMS
**Probability:** Low | **Impact:** High  
**Mitigation:** Validate packages in live LMS before Apr 19 delivery  
**Fallback:** Troubleshoot with LMS team, adjust Player runtime

---

## 11. Three-Way Signature Block

**This contract is locked and ready for implementation upon signature below.**

### Frontend AI Developer / TPO
- [ ] Accept contract lock (Section 1)
- [ ] Accept error envelope (Section 3)
- [ ] Ready to begin Phase 1: **Yes / No**
- Printed Name: ________________________
- Signature: ____________________________
- Date: ______________________

### Backend AI Developer
- [ ] Confirm all commitments (Section 5)
- [ ] Confirm sample delivery Apr 19: **Yes / No**
- [ ] Confirm updates by Apr 15: **Yes / No**
- Printed Name: ________________________
- Signature: ____________________________
- Date: ______________________

### TPO (Project Authority)
- [ ] All parties aligned on contract
- [ ] Implementation may begin: **YES / NO**
- [ ] Next sync: Wednesday, Apr 15 @ 2 PM UTC
- Printed Name: ________________________
- Signature: ____________________________
- Date: ______________________

---

## 12. Document Revision History

| Version | Date | Change | Author |
|---------|------|--------|--------|
| 1.0 (Base) | Apr 12 | Initial contract lock | Both Teams |
| 1.1 | Apr 15 | Field additions confirmed | BE |
| — (Future) | Apr 19 | Sample packages validated | Both |
| — (Future) | Apr 22 | Error envelope live | BE |

---

## 13. Supporting Artifacts (For Reference)

These documents are referenced but not controlling:

1. **SCORM_EXPORT_EXPANSION_2026-04-12.md**
   - Technical deep-dive on renderer architecture
   - For reference during implementation

2. **FRONTEND_INTEGRATION_BRIEF_2026-04-12.md**
   - FE implementation requirements by phase
   - For FE team internal planning

3. **TPO_FE_BE_CONTRACT_ALIGNMENT_RESPONSE_2026-04-12.md**
   - Decision rationale and trade-offs
   - For historical record

4. **BACKEND_AI_DEVELOPER_RESPONSE_TO_FE_FEEDBACK_2026-04-12.md**
   - BE team's commitments and delivery plan
   - For BE team tracking

**This Master Contract Lock (Section 1-11) is the single source of truth.**

---

## 14. Implementation Kickoff Checklist

Before any code is written, confirm:

- [ ] All three signatures on Section 11
- [ ] FE team has copy of this document
- [ ] BE team has copy of this document
- [ ] TPO has assigned QA/testing resources
- [ ] Sample package delivery method decided
- [ ] Weekly sync scheduled (Wednesdays, 2 PM UTC)
- [ ] Issue tracking (Jira/GitHub) ready with sprint boards
- [ ] API documentation link shared
- [ ] Sample packages accessible to FE team

---

## 15. Contact & Escalation

**Weekly Synchronization:**
- **When:** Every Wednesday, 2 PM UTC (starting Apr 15)
- **Duration:** 30 minutes
- **Attendees:** FE AI Dev, BE AI Dev, TPO
- **Agenda:** Phase progress, blockers, questions

**Emergency Escalation (< 4 hours response):**
- **BE AI Developer:** [contact info]
- **FE AI Developer:** [contact info]
- **TPO (Tiebreaker):** [contact info]

**Documentation Issues:**
- Post to: [shared channel/issue tracker]
- Tag: `contract-clarification`
- Resolve within 24 hours

---

## 16. Final Summary

**What is locked?**
- ✅ All 4 canonical endpoints (scoring, completion, interactions, export)
- ✅ Request/response models and validation rules
- ✅ Error envelope structure
- ✅ 40+ supported template types
- ✅ Player.getRenderer dispatch behavior

**What is committed?**
- ✅ BE: exportContractVersion + supportedTemplateTypes by Apr 15
- ✅ BE: Sample packages by Apr 19
- ✅ FE: MVP components (Phase 1) by Apr 26
- ✅ Both: Weekly sync + 4-hour response SLA

**What happens next?**
1. All three parties sign Section 11 ✍️
2. Both teams begin implementation (FE Phase 1, BE P0 items)
3. Weekly sync Wednesday Apr 15 to validate sample packages
4. Continue delivery against timeline

**Ready to proceed?** Get signatures and start building.

---

**Document Status:** FINAL - Ready for Implementation  
**Authority:** Joint FE/BE/TPO  
**Effective Date:** April 12, 2026  
**Next Review:** April 19, 2026 (after sample packages delivered)

---

