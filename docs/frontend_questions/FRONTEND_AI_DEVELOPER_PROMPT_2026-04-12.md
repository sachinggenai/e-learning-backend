# Frontend AI Developer: SCORM Runtime Integration Brief

**From:** TPO (Technical Project Owner)  
**Date:** April 12, 2026  
**Re:** SCORM Export Runtime Integration – Contract Lock & Implementation Ready  
**Status:** Awaiting Front-End & Backend AI Developer Joint Sign-Off

---

## Context

Backend has completed all SCORM export infrastructure:
- ✅ Renderer registry expanded to 35+ template types
- ✅ Runtime type gate (runtime_supported_template_types) defined
- ✅ API contracts implemented (scoring, completion, interactions, export)
- ✅ All test suites green (100 tests passing)
- ✅ Documentation complete

Frontend now needs to implement interactive renderers that consume this backend runtime.

**Before you start coding, you must read and agree to the contract documents provided.**

---

## Documents You Must Read (In This Order)

### 1. **FRONTEND_INTEGRATION_BRIEF_2026-04-12.md**
   - What: Overview of what backend built and what frontend needs to implement
   - Why: Understand the architecture, data contracts, and API expectations
   - Read time: ~20 minutes
   - Location: `/docs/FRONTEND_INTEGRATION_BRIEF_2026-04-12.md`

### 2. **TPO_FE_BE_CONTRACT_ALIGNMENT_RESPONSE_2026-04-12.md**
   - What: Point-by-point alignment decisions with reasoning
   - Why: Understand what's agreed, where FE/BE align, and what isn't negotiable
   - Read time: ~25 minutes
   - Location: `/docs/frontend_questions/TPO_FE_BE_CONTRACT_ALIGNMENT_RESPONSE_2026-04-12.md`
   - Critical: This is the official contract lock. Do not deviate without written approval.

### 3. **SCORM_EXPORT_EXPANSION_2026-04-12.md**
   - What: Deep technical details of what backend implemented
   - Why: Reference for understanding renderer patterns, CSS structure, test patterns
   - Read time: On-demand reference (not required pre-coding, but useful)
   - Location: `/docs/SCORM_EXPORT_EXPANSION_2026-04-12.md`

---

## What You Need To Do Now

### Step 1: Review Contract Lock (Today)
1. Read document #2 (TPO_FE_BE_CONTRACT_ALIGNMENT_RESPONSE_2026-04-12.md).
2. Pay special attention to section 5: "Recommended Final Contract Lock".
3. Note section 7: "Items To Resolve Before Coding Starts" — these must be answered in your team sync.
4. Review section 8: "Joint Acceptance Checklist" — these are your go/no-go gates.

### Step 2: Sync With Backend AI Developer (This Week)
1. Schedule 30-minute joint sync with backend AI developer and TPO.
2. Bring questions from section 7 of the alignment document.
3. Jointly confirm or revise the contract lock in section 5.
4. Get answers to:
   - Do we require alias endpoints or migrate directly to canonical?
   - Will backend add exportContractVersion & supportedTemplateTypes this sprint?
   - Which sample packages will be delivered first?
   - What is FE fallback UX for unsupported template?
   - What is final error envelope shape?

### Step 3: Get Sign-Off (End of Sync)
1. Use section 11 of the alignment document: "Sign-off Block".
2. All three parties sign with name + date + approval/changes requested.
3. If changes are requested, iterate (don't code until resolved).
4. Once signed, implementation is unblocked.

### Step 4: Implement (Only After Sign-Off)
1. Read FRONTEND_INTEGRATION_BRIEF_2026-04-12.md fully.
2. Use SCORM_EXPORT_EXPANSION_2026-04-12.md as technical reference.
3. Follow the implementation order in section 9 of the alignment doc.
4. Build only against canonical API contracts locked in section 5.

---

## Key Contract Points You Must Understand

### Scoring API
```
POST /api/v1/courses/{courseId}/scoring/calculate
```
- Input: Multiple components with answers
- Output: Total score + component breakdown + question results
- Canonical (only) endpoint

### Completion API
```
POST /api/v1/courses/{courseId}/pages/{pageId}/completion
```
- Input: Component states (completed flags, interactions, scores)
- Output: Page completion result (strategy applied)
- Canonical (only) endpoint

### Interactions API
```
POST /api/v1/courses/{courseId}/interactions
```
- interactionType is open string (no enum)
- FE can send new types without backend changes
- Use for telemetry + analytics

### Export Package
```
POST /api/v1/export/scorm/{courseId}?format=scorm_1_2
```
- Output: ZIP with index.html, course_data.js, styles.css
- Player uses getRenderer(type) dispatch table
- Supported types validated before export

---

## Red Flags (Do NOT Do These)

1. **Do NOT build against stale exported artifacts.**
   - Always regenerate from current backend branch.

2. **Do NOT create multiple service paths to the same endpoint.**
   - Service layer is canonical — one httpClient, one contract shape.

3. **Do NOT depend on alias endpoints.**
   - Only if explicitly approved in joint sign-off with rationale.

4. **Do NOT hardcode endpoint shapes outside services.**
   - All API contracts live in src/services/*.

5. **Do NOT let unsupported template types fail silently.**
   - Always render explicit fallback UI + log.

6. **Do NOT assume export payload version/feature support.**
   - Parse as optional; test with `?? null` or `?? []`.

---

## Success Criteria

You can start implementation only if:
1. ✅ You have read both brief documents.
2. ✅ Frontend + Backend AI Developers + TPO have signed off section 11.
3. ✅ Answers to section 7 questions are documented.
4. ✅ All section 8 go/no-go criteria are understood.
5. ✅ Your service layer matches contract lock in section 5 exactly.

---

## Timeline

- **This week:** Review docs + sync + sign-off.
- **Week 1-2:** MVP (accordion, tabs, MCQ, progress).
- **Week 3-4:** Phase 2 (flashcard, scenario, video).
- **Week 5-6:** Phase 3 (polish, accessibility, perf, tests).

---

## Questions?

Before you code, you should have zero questions. If you do:
1. Re-read the relevant section of the alignment doc.
2. Ask in the joint sync (do not code around blockers).
3. Get written approval for any deviation from contract lock.

---

## What Happens Next

1. **You read this prompt + 2 documents** → ~45 minutes.
2. **You have questions** → Add them to section 7 template.
3. **You sync with backend** → 30 minutes, jointly confirm contract.
4. **You sign section 11** → Lock in place.
5. **You implement** → Only then.

**Do not open an IDE until step 5.**

---

Good luck. Contract-first development prevents rework.

—TPO

---

## Attached Documents Reference

All documents are in your project repo:

```
e-learning-backend/
├── docs/
│   ├── FRONTEND_INTEGRATION_BRIEF_2026-04-12.md
│   ├── SCORM_EXPORT_EXPANSION_2026-04-12.md
│   └── frontend_questions/
│       ├── TPO_FRONTEND_BACKEND_ALIGNMENT_PLAN_2026-04-12.md
│       └── TPO_FE_BE_CONTRACT_ALIGNMENT_RESPONSE_2026-04-12.md
```
