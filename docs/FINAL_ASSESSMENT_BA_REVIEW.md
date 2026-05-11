# Final Assessment — Business Analysis & TPO Review
**Date:** 2025-08  
**Reviewer Role:** Business Analyst / Technical Product Owner  
**Scope:** Full end-to-end analysis of the `final-assessment` component across the backend codebase  
**Status:** ⚠️ INCOMPLETE — Registered but not functional

---

## Executive Summary

The `final-assessment` component type is **registered in the seed data** and appears as an available component to authoring users, but it is **entirely non-functional in the SCORM runtime**. Every layer of the export pipeline — alias resolution, data transformation, JavaScript rendering, SCORM scoring, and pass/fail completion — either **ignores or falls through** the `final-assessment` type. A learner who encounters a `final-assessment` slide in an exported SCORM package will see a generic "Unknown slide type: final-assessment" message.

This is a **critical gap** between what the authoring tool promises and what the learner runtime delivers.

---

## Section 1 — Component Registration  
**File:** `app/services/seed_component_types.py` · **Line:** ~53

### What is there

```python
{
  "type_id": "final-assessment",
  "display_name": "Final Assessment",
  "category": "assessment",
  "icon": "award",
  "scoring_enabled": True,
  "max_score": 100,
  "completion_capabilities": ["score"],
  "default_completion_type": "score",
  "audio_support": {"perComponent": False, "perInteraction": False},
  "tags": ["quiz", "final", "assessment"],
  "sort_order": 47
}
```

### Line-by-line Findings

| Field | Value | Finding |
|---|---|---|
| `type_id` | `"final-assessment"` | ✅ Correct identifier; used as the lookup key throughout the system |
| `display_name` | `"Final Assessment"` | ✅ Clear user-facing label |
| `category` | `"assessment"` | ✅ Correct category placement |
| `icon` | `"award"` | ✅ Semantically appropriate |
| `scoring_enabled` | `True` | ✅ Correct intent — this component must produce a score |
| `max_score` | `100` | ✅ Standard 0–100 percentage scale |
| `completion_capabilities` | `["score"]` | ✅ Signals that completion is gated on score, not just visit |
| `default_completion_type` | `"score"` | ✅ Correct |
| `audio_support.perComponent` | `False` | ✅ No per-component audio needed for a test |
| `audio_support.perInteraction` | `False` | ⚠️ **Gap**: For a multi-question final assessment, per-interaction audio (question read-aloud) is a common accessibility requirement (WCAG 2.1 AA). This field should be revisited if accessibility compliance is a requirement. |
| `tags` | `["quiz", "final", "assessment"]` | ✅ Appropriate discovery tags |
| `sort_order` | `47` | ✅ Late in the ordering, appropriate for an end-of-course component |
| **`schema`** | ❌ **MISSING** | **Critical gap.** Every other fully-implemented assessment type (`mcq`, etc.) has a JSON schema defining required fields (`questions`, `options`, `isCorrect`, `passingScore`, etc.). Without a schema, the authoring tool has no data contract to validate against and can produce any arbitrary payload — which will be silently accepted by Pydantic (`extra="allow"`) and then silently fail at render time. |
| **`passingScore`** | ❌ **MISSING** | **Critical gap.** There is no default passing threshold defined. A final assessment has no meaning without a pass/fail boundary. The MCQ type also lacks this, but it is a single-question knowledge check — a final assessment is an end-of-course gate. |
| **`attempts`** | ❌ **MISSING** | **Gap.** Maximum retake attempts are never defined, leaving LMS retry behaviour undefined. |

### Recommendation

Add the following fields to the `final-assessment` seed entry:

```python
"schema": {
  "type": "object",
  "required": ["questions"],
  "properties": {
    "passingScore": {"type": "integer", "minimum": 0, "maximum": 100, "default": 80},
    "maxAttempts": {"type": "integer", "minimum": 1, "default": 1},
    "shuffleQuestions": {"type": "boolean", "default": False},
    "shuffleOptions": {"type": "boolean", "default": False},
    "showCorrectAnswers": {"type": "boolean", "default": True},
    "introText": {"type": "string"},
    "questions": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["id", "question", "options"],
        "properties": {
          "id": {"type": "string"},
          "question": {"type": "string"},
          "options": {
            "type": "array",
            "minItems": 2,
            "items": {
              "type": "object",
              "required": ["id", "text", "isCorrect"],
              "properties": {
                "id": {"type": "string"},
                "text": {"type": "string"},
                "isCorrect": {"type": "boolean"},
                "feedback": {"type": "string"}
              }
            }
          },
          "explanation": {"type": "string"}
        }
      }
    }
  }
}
```

---

## Section 2 — SCORM Export Pipeline Gaps
**File:** `app/services/scorm_export.py`

The SCORM export pipeline has four distinct stages at which `final-assessment` is either silently dropped or falls through to a no-op.

### Stage 1: `TEMPLATE_TYPE_ALIASES` (lines ~3040–3090)

**What is there:** A dictionary mapping authoring `type_id` strings to canonical runtime renderer keys.

**Finding:** `"final-assessment"` is **NOT listed** in this dictionary.

```python
# Current state — final-assessment is absent
TEMPLATE_TYPE_ALIASES = {
    "video": "content-video",
    "quiz": "mcq",
    "knowledge-check": "quiz",
    # ... 30+ entries ...
    # ❌ "final-assessment" is not here
}
```

**Impact:** The alias resolver `_canonicalize_template_type()` receives `"final-assessment"`, finds no entry, and returns `"final-assessment"` unchanged — a string that does not exist in `runtime_supported_template_types`. The system silently continues rather than raising an error or warning.

**Recommendation:** Add alias mapping:
```python
"final-assessment": "final-assessment",   # self-alias to mark as intentionally supported
```
OR, if `final-assessment` should render using a new dedicated renderer, this alias makes the intent explicit. Alternatively, if the decision is to use the MCQ renderer with multi-question capability, map it to `"mcq"` and handle the N-question logic in the renderer.

---

### Stage 2: `runtime_supported_template_types` (lines ~3095–3120)

**What is there:** A Python `set` acting as a gate — only type strings in this set are considered valid by the export pipeline.

**Finding:** `"final-assessment"` is **NOT in this set**.

```python
self.runtime_supported_template_types = {
    # Assessment
    "mcq", "multiple-select", "true-false", "fill-in-blank",
    "hotspot", "image-hotspots", "matching", "drag-and-drop",
    # ❌ "final-assessment" is NOT here
}
```

**Impact:** The `_canonicalize_template_type()` method loops over `_template_type_candidates()` and returns the first candidate that exists in `runtime_supported_template_types`. Since `"final-assessment"` is absent, the method returns the raw string `"final-assessment"`. Downstream, the JavaScript `getRenderer()` function receives this unknown type string and returns `null`, causing `renderUnknown()` to be called.

**Recommendation:** Add `"final-assessment"` to the set once its renderer is implemented.

---

### Stage 3: `_transform_template_data()` (lines ~1640–2350)

**What is there:** A large conditional block that structurally transforms authoring-side data into the shape each renderer expects (e.g., `accordion → panels[]`, `tabs → tabs[]`).

**Finding:** There is **no `final-assessment` branch** in this method.

**Impact:** Even if the alias and support set gates are fixed, the data payload from the authoring tool is passed as-is to the JavaScript renderer. This is acceptable **only if** the authoring tool produces exactly the shape the renderer expects. Given that there is no schema today (Section 1), there is no guarantee of data shape. A transform handler is needed to normalize the payload:

```python
# Needed in _transform_template_data()
if t == "final-assessment":
    questions = data.get("questions") or []
    normalized_questions = [
        {
            "id": q.get("id") or f"q_{i}",
            "question": q.get("question") or q.get("text") or "",
            "options": [
                {
                    "id": opt.get("id") or f"q_{i}_o_{j}",
                    "text": opt.get("text") or "",
                    "isCorrect": bool(opt.get("isCorrect") or opt.get("correct") or False),
                    "feedback": opt.get("feedback") or "",
                }
                for j, opt in enumerate(q.get("options") or [])
            ],
            "explanation": q.get("explanation") or "",
        }
        for i, q in enumerate(questions) if isinstance(q, dict)
    ]
    return {
        **data,
        "questions": normalized_questions,
        "passingScore": data.get("passingScore") or 80,
        "shuffleQuestions": bool(data.get("shuffleQuestions") or False),
        "showCorrectAnswers": bool(data.get("showCorrectAnswers") if "showCorrectAnswers" in data else True),
    }
```

---

### Stage 4: `getRenderer()` JavaScript Registry (embedded in `_create_content_html()`)

**What is there:** A JavaScript object literal mapping runtime type strings to render functions.

**Finding:** `"final-assessment"` is **NOT in the registry**. The function returns `null` for this type.

```javascript
getRenderer: function(type) {
    var registry = {
        // Assessment
        'mcq':                   this.renderMCQ,
        'multiple-select':       this.renderMultipleSelect,
        'true-false':            this.renderTrueFalse,
        // ❌ 'final-assessment' is NOT here
    };
    return registry[type] || null;  // returns null → renderUnknown() called
}
```

**Impact:** `renderUnknown()` is called, producing:
```
Unknown slide type: final-assessment
```
This is what learners see in the SCORM package today. This is a **learner-facing failure** with no graceful degradation.

---

## Section 3 — Data Model & Validation Gap
**File:** `app/models/course.py`

### What is there

- `MCQData` Pydantic model with `content: str` and `questions: List[Question]`
- `Question` model: `id`, `question`, `options: List[QuestionOption]`
- `QuestionOption`: `id`, `text`, `isCorrect: bool`
- `TemplateData` uses `extra="allow"` — accepts any fields without validation
- The template validator only performs specific validation for `mcq` and `content-video` types

### Finding

There is **no `FinalAssessmentData` Pydantic model**. When a `final-assessment` template is submitted through the API, it is stored with zero structural validation. Fields like `passingScore`, `shuffleQuestions`, and multi-question structure are never validated.

**Impact:**
- Authoring tool can store malformed payloads silently
- Export pipeline receives structurally unpredictable data
- No server-side guarantee that `questions` is present or non-empty
- No validation that each question has at least one `isCorrect: true` option

### Recommendation

Add a dedicated Pydantic model and register it in the template validator:

```python
class FinalAssessmentData(BaseModel):
    model_config = ConfigDict(extra="allow")
    
    questions: List[Question]
    passingScore: int = Field(default=80, ge=0, le=100)
    maxAttempts: int = Field(default=1, ge=1)
    shuffleQuestions: bool = False
    shuffleOptions: bool = False
    showCorrectAnswers: bool = True
    introText: Optional[str] = None
    
    @model_validator(mode="after")
    def validate_questions(self) -> "FinalAssessmentData":
        for i, q in enumerate(self.questions):
            correct_count = sum(1 for opt in q.options if opt.isCorrect)
            if correct_count == 0:
                raise ValueError(f"Question {i+1} has no correct answer option")
        return self
```

---

## Section 4 — MCQ Architecture Analysis (Single-Question Limitation)

The existing `renderMCQ()` function, which is the closest functional analogue to what a Final Assessment needs, has a **fundamental architectural limitation**:

```javascript
renderMCQ: function(slide, idx) {
    // ...
    var question = slide.data.questions[0];  // ← ALWAYS uses only the first question
    // ...
}
```

And `selectAnswer()` mirrors this:
```javascript
var question = slide.data.questions[0];  // ← ALWAYS evaluates only question[0]
```

**Impact for Final Assessment:**
- A final assessment typically has 5–20 questions
- The current renderer would silently discard questions 2–N
- The learner would only answer 1 question, score would be based on 1 question
- `finishCourse()` only checks `mcq` type slides for unanswered questions:
  ```javascript
  if (t.type === 'mcq' && this.state.quizAnswers[i] === undefined) { ... }
  // ❌ Does NOT check 'final-assessment' type at all
  ```

This means even a `final-assessment` slide (if it somehow rendered) would not be validated for completeness before the "Finish" button is activated.

---

## Section 5 — Scoring & Completion Model

### SCORM Scoring (scorm_wrapper.js embedded JS)

The `calculateScore()` function in the SCORM wrapper computes a score based on all recorded quiz answers:
```javascript
calculateScore: function() {
    var total = Object.keys(this.sessionData.answers).length;
    var correct = Object.values(this.sessionData.answers)
                        .filter(function(a) { return a.correct; }).length;
    return total > 0 ? Math.round((correct / total) * 100) : 0;
}
```

**Finding:** This logic is question-count based (% correct across all MCQ slides). This is **not appropriate for a Final Assessment** because:

1. The score should be computed only from Final Assessment questions, not all quiz interactions in the course
2. The `passingScore` threshold is never consulted — there is no pass/fail determination
3. `SCORM.setCourseComplete()` sets status to `"completed"` regardless of score
4. `cmi.core.score.raw` is reported, but `cmi.core.mastery_score` (the SCORM 1.2 field that LMSes use for automatic pass/fail gating) is **never set**

### Pass/Fail Logic

**There is no pass/fail logic anywhere in the codebase.** The `finishCourse()` function:
1. Marks all slides completed
2. Calls `SCORM.setCourseComplete()` → always sets `lesson_status = "completed"`
3. Calls `SCORM.calculateScore()` → reports raw score
4. Shows an alert with the score

**A learner who scores 20% on a Final Assessment is reported to the LMS as "completed"** with a score of 20. The LMS may have its own mastery threshold configured, but the SCO never sets `cmi.core.mastery_score` to tell the LMS what the passing bar is.

---

## Section 6 — Missing JavaScript Renderer

No `renderFinalAssessment()` function exists. The complete implementation would need:

1. **Multi-question pagination or all-on-one-page display** with question navigation
2. **Per-question answer capture** across all N questions, not just `questions[0]`
3. **Question shuffle** (if `shuffleQuestions: true`)
4. **Option shuffle** (if `shuffleOptions: true`)
5. **"Submit Assessment" button** (separate from the course Next/Prev navigation)
6. **Locked navigation** while assessment is in progress (prevent skipping)
7. **Results screen** showing: score achieved, passing score, pass/fail status, per-question review (if `showCorrectAnswers: true`)
8. **SCORM mastery reporting**: `cmi.core.mastery_score = passingScore`, `cmi.core.lesson_status = score >= passingScore ? "passed" : "failed"`
9. **Answer persistence** via `cmi.suspend_data` so a learner can resume a partially completed assessment

---

## Section 7 — Consolidated Gap Matrix

| Layer | File | Status | Gap |
|---|---|---|---|
| Component Registration | `seed_component_types.py:53` | ⚠️ Partial | Missing `schema`, `passingScore`, `maxAttempts` fields |
| Pydantic Validation | `app/models/course.py` | ❌ Missing | No `FinalAssessmentData` model |
| SCORM Alias Mapping | `scorm_export.py:~3040` | ❌ Missing | Not in `TEMPLATE_TYPE_ALIASES` |
| Runtime Support Gate | `scorm_export.py:~3095` | ❌ Missing | Not in `runtime_supported_template_types` |
| Data Transform | `scorm_export.py:_transform_template_data()` | ❌ Missing | No `final-assessment` handler |
| JS Renderer Registration | Embedded JS `getRenderer()` | ❌ Missing | Not in registry → `renderUnknown()` |
| JS Renderer Implementation | Embedded JS | ❌ Missing | `renderFinalAssessment()` does not exist |
| Multi-question Support | Embedded JS `selectAnswer()` | ❌ Missing | Only `questions[0]` evaluated |
| Finish Gate | Embedded JS `finishCourse()` | ❌ Missing | Does not check `final-assessment` type |
| SCORM Pass/Fail | `scorm_wrapper.js` embedded | ❌ Missing | `cmi.core.mastery_score` never set |
| SCORM Status | `scorm_wrapper.js` embedded | ❌ Missing | Always `"completed"`, never `"passed"`/`"failed"` |

---

## Section 8 — Re-Engineering Recommendations

### Priority 1 — Data Contract (Backend)
1. Add JSON schema to `seed_component_types.py` `final-assessment` entry
2. Create `FinalAssessmentData` Pydantic model with `@model_validator`
3. Register in template validator — validate on authoring API `POST /courses/{id}/templates`

### Priority 2 — Export Pipeline (Python)
4. Add `"final-assessment"` to `TEMPLATE_TYPE_ALIASES` (self-map)
5. Add `"final-assessment"` to `runtime_supported_template_types`
6. Add `final-assessment` branch to `_transform_template_data()` with normalization logic

### Priority 3 — SCORM Runtime (JavaScript)
7. Implement `renderFinalAssessment(slide, idx)` function with:
   - Multi-question display (paginated or scrollable)
   - Per-question radio groups with namespacing: `name="fa_answer_{idx}_{questionIdx}"`
   - "Submit Assessment" button (not the course-level "Finish" button)
   - Results screen after submission
8. Register in `getRenderer()`: `'final-assessment': this.renderFinalAssessment`
9. Implement `submitFinalAssessment(slideIdx)` function:
   - Collect all answers from the assessment slide's questions
   - Calculate score: `(correct / total) * 100`
   - Compare against `passingScore`
   - Set `SCORM.setValue('cmi.core.mastery_score', slide.data.passingScore)`
   - Set `SCORM.setValue('cmi.core.lesson_status', passed ? 'passed' : 'failed')`
   - Display results screen
10. Update `finishCourse()` to gate on `final-assessment` unanswered questions
11. Update `calculateScore()` to optionally scope to `final-assessment` slides only

### Priority 4 — SCORM Mastery Reporting (SCORM Wrapper)
12. In `setCourseComplete()`, check if any `final-assessment` slide exists in `courseData` and use its `passingScore` to set `cmi.core.mastery_score` before setting `lesson_status`

### Priority 5 — Accessibility
13. Revisit `audio_support.perInteraction` in seed data if accessibility/508 compliance requires question read-aloud
14. Ensure the assessment renderer uses `<fieldset>` + `<legend>` for each question group (WCAG requirement for radio button groups)
15. Add `aria-required` and `aria-describedby` to question inputs

---

## Section 9 — Acceptance Criteria for Re-Engineering

The `final-assessment` component can be considered complete when:

- [ ] An author can create a `final-assessment` template with N questions (N ≥ 1) and configure a passing score
- [ ] The authoring API validates the data against the schema and rejects malformed payloads
- [ ] SCORM export includes `final-assessment` slides as functional, rendered content
- [ ] All N questions are presented to the learner (not just question 0)
- [ ] Per-question correct/incorrect feedback is shown after submission
- [ ] The learner's aggregate score is calculated across all N questions
- [ ] `cmi.core.score.raw` reports the aggregate score (0–100)
- [ ] `cmi.core.mastery_score` reports the configured passing score
- [ ] `cmi.core.lesson_status` reports `"passed"` when score ≥ passingScore, `"failed"` otherwise
- [ ] The "Finish" button is disabled until the Final Assessment is submitted
- [ ] A learner who fails cannot be marked as "completed" by the LMS
- [ ] Partial assessment state survives a browser refresh (via `cmi.suspend_data`)

---

*End of Review — All file references verified against live codebase as of analysis date.*
