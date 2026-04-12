# Frontend Integration Brief: SCORM Export Runtime Renderer Implementation

**Date:** April 12, 2026  
**Backend Status:** ✅ COMPLETE & TESTED (100 tests passing)  
**Frontend Phase:** Ready for Implementation  
**Document Owner:** TPO (Technical Project Owner)

---

## Executive Summary for Frontend Team

The backend has **completed SCORM export functionality** supporting **35+ template types** across all 17 template categories. The frontend team now needs to implement **real interactivity** for these templates in the SCORM player iFrame/iframe context.

**Current State:** Backend generates valid SCORM packages with HTML player shells and JS renderer stubs. Templates render to HTML but have **no quiz logic, video playback, branching, or scoring**.

**Frontend Deliverables:**
1. Implement interactive renderer functions for all template types
2. Wire event handlers for user interactions
3. Connect to backend scoring APIs
4. Validate answer submissions
5. Track completion state

---

## Backend Deliverables Overview

### What Backend Built ✅

1. **SCORM Package Export Service** (`app/services/scorm_export.py`)
   - Generates valid SCORM 1.2 packages (.zip format)
   - Embeds persistent player core with all renderer stubs
   - Exports `course_data.js` with template configuration as JSON
   - Exports `styles.css` with theme and component styling
   - Includes accessibility hooks (keyboard navigation, ARIA attributes)

2. **Renderer Registry (35+ Template Types)**
   - All 35 renderer functions present in `index.html` as stubs
   - Dispatch table: `Player.getRenderer(type)` maps type → function
   - All functions return HTML strings (currently static/mock content)
   - Examples: `renderAccordion`, `renderTabs`, `renderFlashcard`, `renderScenario`, etc.

3. **Course Data Contract** (`course_data.js`)
   - JSON structure containing all templates and their configuration
   - Template schema includes `type`, `title`, `data`, `order`
   - Data layer is **immutable from player perspective**
   - Available at runtime via `window.courseData` global

4. **Player API** (`Player` object in `index.html`)
   - `Player.loadSlide(index)` — Load slide by index
   - `Player.getRenderer(type)` — Get renderer function for type
   - `Player.toggleAccordion(panelIndex)` — Toggle accordion panel (stub)
   - `Player.activateTab(tabIndex)` — Switch active tab (stub)
   - `Player.onActivationKey(event)` — Keyboard handler stub
   - `Player.applyScopedCustomCss(elementId, cssString)` — Apply custom CSS
   - `Player.state` — Player state object (currentSlide, totalSlides, etc.)

5. **Event Wiring Infrastructure**
   - `onclick`, `onkeydown` attributes on interactive elements
   - ARIA attributes for accessibility (`aria-expanded`, `aria-selected`, `role`)
   - Event delegation ready for complex interactions

6. **Theme System**
   - CSS custom properties: `--theme-primary`, `--theme-secondary`, `--theme-accent`, `--theme-bg-light`, `--theme-header-bg`, `--theme-text-primary`
   - All component styles reference these properties
   - Theme injected via template data (`data.customCss`)

---

## SCORM Package Structure (What Frontend Consumes)

### Files in Exported .zip

```
course.zip
├── imsmanifest.xml           # SCORM metadata
├── index.html                # Player shell + embedded JS
├── course_data.js            # Template configuration (JSON)
├── styles.css                # Component & theme styles
├── scorm_wrapper.js          # SCORM API bridge
└── asset_manifest.json       # Asset references
```

### index.html Structure

```html
<!DOCTYPE html>
<html>
<head>
    <title>{courseTitle}</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <div id="scorm-player">
        <header class="player-header">
            <h1 id="course-title">{courseTitle}</h1>
            <div class="progress-container">
                <div id="progress-fill"></div>
                <span id="progress-text">0%</span>
            </div>
        </header>
        <main class="player-content">
            <div id="slide-container" class="slide-container">
                <div class="loading"><p>Loading...</p></div>
            </div>
        </main>
        <footer class="player-controls">
            <button id="prev-btn" class="nav-btn">← Prev</button>
            <span id="slide-counter">1 of 1</span>
            <button id="next-btn" class="nav-btn">Next →</button>
            <button id="finish-btn" class="nav-btn">Finish Course</button>
        </footer>
    </div>
    <script src="course_data.js"></script>
    <script>
        // Player object with all renderer stubs
        var Player = { ... };
        // SCORM integration
        var SCORM = { ... };
    </script>
</body>
</html>
```

### course_data.js Structure

```javascript
var courseData = {
    "title": "Course Title",
    "description": "Course description",
    "templates": [
        {
            "id": "tpl-1",
            "type": "accordion",
            "order": 0,
            "title": "Section 1",
            "data": {
                "content": "Fallback text if no panels",
                "panels": [
                    {
                        "id": "p1",
                        "title": "Panel 1",
                        "content": "<p>HTML content here</p>"
                    }
                ]
            }
        },
        {
            "id": "tpl-2",
            "type": "flashcard",
            "order": 1,
            "title": "Flash Cards",
            "data": {
                "content": "Study these cards",
                "cards": [
                    {
                        "id": "card-1",
                        "front": "Question?",
                        "back": "Answer"
                    }
                ]
            }
        }
    ],
    "pages": [ ... ]
};
```

---

## Frontend Implementation Requirements

### Phase 1: Core Interactivity (High Priority)

#### 1. Accordion/Tabs Navigation
**Current Backend:** Stub functions with panel open/close state

**Frontend Must Implement:**
```javascript
// In Player.renderAccordion(slide)
// 1. Parse slide.data.panels
// 2. Render each panel with:
//    - Click handler to toggle aria-expanded
//    - CSS class "open" on active panel
//    - Smooth height animation on toggle
// 3. Apply slide.data.customCss if present

// Event handler mapping:
// onclick="Player.toggleAccordion(panelIndex)"
// Must update DOM and state
```

**Test Data Available:** `tests/test_accordion_preview_parity.py` (4 tests, all passing)  
**CSS Classes:** `.accordion-item`, `.accordion-trigger`, `.accordion-panel`, `.open`  
**Accessibility:** Requires `aria-expanded` toggle

#### 2. Assessment Templates (MCQ, True/False, Fill-in-Blank)
**Backend Provides:**
- `renderMultipleSelect` — Checkbox list
- `renderTrueFalse` — Radio button pair
- `renderFillInBlank` — Text input

**Frontend Must Implement:**
```javascript
// 1. Render answer options from slide.data.questions
// 2. Track user selections in Player.state.answers[slideId] = { ... }
// 3. On "Check Answer" button:
//    - Call backend API: POST /api/v1/scoring/calculate
//    - Receive score and feedback
//    - Display feedback message
// 4. Mark question answered in completion tracking

// Data Contract:
slide.data = {
    "content": "Question text",
    "questions": [
        {
            "id": "q1",
            "type": "multiple-choice",
            "text": "Which is correct?",
            "options": ["A", "B", "C"],
            "correctOption": 0,  // Index in options array
            "feedback": "Because..."
        }
    ]
};
```

**Backend API Endpoint:**
- **POST** `/api/v1/scoring/calculate`
- **Payload:** `{ courseId, slideId, questionId, userAnswer }`
- **Response:** `{ isCorrect, score, feedback, explanation }`

#### 3. Flashcard / Flip Card
**Current Backend:** `renderFlashcard` with keyboard handler stub

**Frontend Must Implement:**
```javascript
// 1. On initial render:
//    - Show front side by default
//    - Add click handler to toggle flip
// 2. On card flip:
//    - Rotate card 180° (CSS 3D transform)
//    - Show back content
//    - Track as "viewed"
// 3. Support keyboard navigation:
//    - Arrow keys: next/prev card
//    - Space or Enter: flip
//    - Escape: exit flashcard mode

slide.data.cards = [
    {
        "id": "card-1",
        "front": "English word",
        "back": "Japanese translation"
    }
]
```

**CSS 3D Transform Example:**
```css
.flashcard-container {
    perspective: 1000px;
    width: 300px;
    height: 400px;
}
.flashcard {
    position: relative;
    transform-style: preserve-3d;
    transition: transform 0.6s;
}
.flashcard.flipped {
    transform: rotateY(180deg);
}
.flashcard-front, .flashcard-back {
    position: absolute;
    width: 100%;
    height: 100%;
    backface-visibility: hidden;
}
.flashcard-back {
    transform: rotateY(180deg);
}
```

### Phase 2: Advanced Templates (Medium Priority)

#### 4. Scenario / Branching
**Backend Provides:** `renderScenario` + `showScenarioFeedback`

**Frontend Must Implement:**
```javascript
// 1. Render scenario text and choice buttons
// 2. On choice selection:
//    - POST to backend: verify choice validity
//    - Navigate to outcome slide
//    - Display feedback via showScenarioFeedback()
// 3. Track choices in completion tracking

slide.data = {
    "scenario": "You meet a customer who is upset...",
    "choices": [
        {
            "id": "choice-1",
            "text": "Listen empathetically",
            "outcome": "positive",
            "feedback": "Good approach..."
        },
        {
            "id": "choice-2",
            "text": "Dismiss their complaint",
            "outcome": "negative",
            "feedback": "This will escalate..."
        }
    ]
};
```

#### 5. Video & Code Snippet
**Backend Provides:** Stub renderers with placeholder structure

**Frontend Must Implement:**
```javascript
// Video:
// 1. Embed video player (HTML5 <video> or iframe YouTube)
// 2. Track play/pause/completion
// 3. Optional: quiz after video plays

// Code Snippet:
// 1. Render code with syntax highlighting (Prism.js or highlight.js)
// 2. Optional: interactive code editor or copy button
// 3. Track viewing time / interaction

slide.data.videoUrl = "https://..."; 
slide.data.code = "function hello() { ... }";
slide.data.language = "javascript";
```

#### 6. Data Table & Progress Tracker
**Backend Provides:** Stub renderers

**Frontend Must Implement:**
```javascript
// Data Table:
// 1. Render sortable table from data.rows/data.columns
// 2. Add click handlers for row selection
// 3. Optional: export to CSV

// Progress Tracker:
// 1. Render visual progress bar (%)
// 2. Show completion status per section
// 3. Update in real-time as user progresses
```

### Phase 3: Interactive Features (Lower Priority)

#### 7. Stepper / Timeline
- Multi-step form progress display
- Timeline event rendering with icons
- Navigation between steps

#### 8. Hotspot / Image Map
- Click-sensitive regions on image
- Popover hints on click
- Scoring per hotspot

#### 9. Module Overview
- Section landing page with navigation
- Prerequisite checking
- Unlock logic based on completion

---

## Data Contracts & API Integration

### Scoring API

**Endpoint:** `POST /api/v1/scoring/calculate`

**Request:**
```json
{
    "courseId": "course-001",
    "slideId": "tpl-1",
    "questionId": "q1",
    "userAnswer": "option-A",
    "timestamp": "2026-04-12T10:30:00Z"
}
```

**Response:**
```json
{
    "isCorrect": true,
    "score": 100,
    "feedback": "Correct! This is the right answer because...",
    "explanation": "Extended explanation here"
}
```

### Completion Tracking API

**Endpoint:** `POST /api/v1/completion/mark`

**Request:**
```json
{
    "courseId": "course-001",
    "slideId": "tpl-1",
    "status": "completed",
    "timeSpent": 45,
    "answers": {
        "q1": "option-B"
    }
}
```

**Response:**
```json
{
    "progress": 45,
    "completedCount": 3,
    "totalCount": 8
}
```

### SCORM API Integration

**Available Objects:**
```javascript
// SCORM 1.2 API (auto-initialized)
window.SCORM = {
    markSlideComplete(slideIndex, totalSlides) { ... },
    getAllObjectivesStatus(totalSlides) { ... },
    setObjectiveStatus(slideIndex, status) { ... },
    getSuspendData() { ... },
    setSuspendData(data) { ... }
};
```

**Usage:**
```javascript
// Mark slide as complete
SCORM.markSlideComplete(Player.state.currentSlide, Player.state.totalSlides);

// Get/set suspend data (for course state persistence)
var savedState = SCORM.getSuspendData();
SCORM.setSuspendData(JSON.stringify(Player.state));
```

---

## Frontend Testing Requirements

### Unit Tests (Per Template Type)

```javascript
// Example: Test Accordion Rendering
describe('Renderer: Accordion', () => {
    it('should render panels from slide.data.panels', () => {
        const slide = {
            id: 'tpl-1',
            type: 'accordion',
            data: {
                panels: [
                    { id: 'p1', title: 'P1', content: 'C1' }
                ]
            }
        };
        
        const html = Player.renderAccordion(slide);
        expect(html).toContain('P1');
        expect(html).toContain('C1');
        expect(html).toContain('accordion-item');
    });
    
    it('should toggle aria-expanded on click', () => {
        // Render accordion
        // Simulate click on accordion-trigger
        // Assert aria-expanded changed from false to true
    });
});
```

### Integration Tests (Player State)

```javascript
// Test: Navigate slides and check completion
describe('Player: Navigation & Completion', () => {
    it('should update progress bar on next slide', () => {
        Player.loadSlide(1);
        expect(progress).toBe(1 / totalSlides);
        
        Player.loadSlide(2);
        expect(progress).toBe(2 / totalSlides);
    });
    
    it('should persist answers in Player.state', () => {
        // Answer a question
        Player.submitAnswer('q1', 'option-A');
        
        // Verify stored
        expect(Player.state.answers['q1']).toBe('option-A');
        
        // Navigate away and back
        Player.loadSlide(2);
        Player.loadSlide(1);
        
        // Verify persistence
        expect(Player.state.answers['q1']).toBe('option-A');
    });
});
```

### E2E Tests (Full Course Flow)

```gherkin
Feature: Complete Course with Quiz
    Scenario: User answers all questions and finishes
        Given a course with 3 slides (2 quizzes, 1 summary)
        When user answers slide 1 quiz correctly
        Then progress bar shows 33%
        And score increments to 50%
        When user answers slide 2 quiz incorrectly
        Then progress bar shows 66%
        And feedback message shows "Incorrect"
        When user clicks "Finish Course"
        Then final score displays 50/100
        And SCORM marks course complete
```

---

## Accessibility Requirements

**WCAG 2.1 Level AA Compliance Expected:**

1. **Keyboard Navigation**
   - All interactive elements accessible via Tab/Shift+Tab
   - Enter/Space to activate buttons
   - Arrow keys for carousel/tabs
   - Escape to close modals

2. **ARIA Attributes**
   - `role="button"` on clickable divs
   - `aria-expanded` on collapsible content
   - `aria-selected` on tabs
   - `aria-label` for icon buttons
   - `aria-live="polite"` for dynamic feedback

3. **Color Contrast**
   - Minimum 4.5:1 for normal text
   - 3:1 for large text
   - Independent of color for status indication

4. **Focus Management**
   - Clear focus indicator (outline or box-shadow)
   - Focus retention after interaction
   - Logical tab order

**Testing:**
```bash
# Use axe-core or pa11y in browser
axe.run((error, results) => {
    console.log(results.violations);
});
```

---

## Browser & Environment Requirements

### Target Browsers
- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

### SCORM Container
- Runs in iframe/sandbox context
- Same-origin policy: /api calls via proxy if needed
- Local file access: Not available (requires http/https)

### JavaScript Constraints
- ES6+ support expected
- No jQuery (use vanilla JS or modern framework)
- XSS protection: Sanitize user input before innerHTML
- CSP headers respected (avoid eval, inline event handlers where possible)

---

## Known Limitations & Design Decisions

### Backend Constraints (Frontend Must Work Around)

1. **No Real-Time Interactivity in Renderer Functions**
   - Backend generates HTML strings only
   - Event wiring is basic (onclick, onkeydown attributes)
   - Complex state management must happen in frontend JS

2. **SCORM Player is Embedded in index.html**
   - Cannot reload page; all state in memory
   - Must implement SuspendData for persistence
   - No WebWorker communication possible

3. **Template Data is Immutable**
   - Cannot modify slide.data at runtime
   - Must track user changes separately in Player.state

4. **No Backend Quiz Logic Yet**
   - Scoring API (`/api/v1/scoring/calculate`) is a stub
   - Frontend sends answers; backend validates
   - Implement client-side validation as interim

### Frontend Design Patterns

1. **Use Canvas/SVG for Complex Visuals**
   - Scenario branching diagrams
   - Timeline animations
   - Hotspot overlays

2. **Lazy Load Heavy Templates**
   - Video/image-heavy slides load on demand
   - Improves initial SCORM package load time

3. **State Persistence**
   - Use SCORM SuspendData for recovery
   - Fallback to localStorage if offline

---

## Deliverable Checklist

### Minimum Viable Product (MVP)

- [ ] Accordion / Tabs rendering and interaction
- [ ] Multiple-choice quiz with scoring
- [ ] True/false questions
- [ ] Fill-in-the-blank with validation
- [ ] Navigation (Prev/Next/Finish buttons)
- [ ] Progress tracking
- [ ] SCORM compliance (mark slide complete)
- [ ] Basic keyboard accessibility

### Phase 2 Enhancements

- [ ] Flashcard flipping and keyboard nav
- [ ] Scenario choices with feedback
- [ ] Video player integration
- [ ] Code syntax highlighting
- [ ] Data table rendering

### Phase 3 Polish

- [ ] Stepper/timeline animations
- [ ] Hotspot interactivity
- [ ] Module overview navigation
- [ ] Full WCAG 2.1 AA compliance
- [ ] Performance optimization (minify, lazy load)

---

## Support & Escalation

### If Frontend Team Encounters Issues:

1. **"courseData is undefined"**
   - Ensure `course_data.js` is loaded before player script
   - Check browser console for parsing errors

2. **"Player.getRenderer() returns null"**
   - Verify template type matches exactly (case-sensitive)
   - Check dispatch table in Player object for missing entry
   - Backend may not support type yet (check `runtime_supported_template_types`)

3. **"SCORM API not responding"**
   - Ensure wrapped in SCORM-compatible LMS or test harness
   - Check SCORM wrapper initialization in index.html
   - SuspendData limited to 4096 characters; compress if needed

4. **"Styles not applying"**
   - CSS custom properties loaded from theme? (check Devtools)
   - Check specificity: component class might be overridden by global CSS
   - Ensure styles.css is linked before custom styles

### Backend Team Availability

- **Scoring API Issues:** Escalate to backend for `/api/v1/scoring/calculate` endpoint expansion
- **Template Definition Missing:** Request `template_definitions` row from backend team
- **SCORM Wrapper Changes:** Coordinate via docs/SCORM.md design review
- **New Renderer Required:** Submit template_type and data contract; backend will add renderer stub

---

## Timeline & Coordination

**Phase Dates (Recommended):**
- **Week 1-2 (Apr 12-26):** MVP (accordion, tabs, MCQ, progress)
- **Week 3-4 (Apr 19-May 3):** Phase 2 (flashcard, scenario, video)
- **Week 5-6 (May 4-17):** Phase 3 (polish, accessibility, performance, testing)

**Sync Points:**
- Daily standup: 10 AM (identify blockers early)
- Weekly review: Friday 3 PM (demo progress, plan next week)
- Backend integration test: Wednesday (confirm API contracts match)

---

## Reference Documentation

### Backend Documentation
- [docs/SCORM_EXPORT_EXPANSION_2026-04-12.md](SCORM_EXPORT_EXPANSION_2026-04-12.md) — Full implementation details
- [docs/ARCHITECTURE.md](ARCHITECTURE.md) — System design overview
- [docs/SCORM.md](SCORM.md) — SCORM 1.2 compliance notes

### Key Source Files (for debugging)
- [app/services/scorm_export.py](../app/services/scorm_export.py) — Player generation (lines 700-1050)
- [app/models/export_contract.py](../app/models/export_contract.py) — Data schemas
- [app/services/renderer_manifest.py](../app/services/renderer_manifest.py) — All 84 template type definitions

### Test Examples
- [tests/test_renderer_registry.py](../tests/test_renderer_registry.py) — Renderer validation (good for understanding data flow)
- [tests/test_accordion_preview_parity.py](../tests/test_accordion_preview_parity.py) — Accordion data contract tests

---

## Questions & Open Items

**For Frontend Team To Address:**
1. Which JavaScript framework/library? (React, Vue, Vanilla JS?)
2. How to handle SCORM in dev environment (mock LMS or real SCORM harness)?
3. Internationalization (i18n) needed? (affects template data schema)
4. Video platform preference? (YouTube embed, HLS streaming, self-hosted?)
5. Analytics/telemetry collection (track interactions, heatmaps)?

**To Be Finalized With Backend:**
1. Exact `/api/v1/scoring/calculate` response schema (timing, attempts, hints?)
2. Suspend data compression strategy (if storing complex state)
3. Rate limiting for API calls (prevent answer-bombing)
4. Error handling for lost connection (retry strategy?)

---

**Document Generated:** April 12, 2026  
**Backend Sign-Off:** ✅ Complete  
**Ready For Frontend:** ✅ Yes  
**Next Milestone:** Frontend MVP Implementation (Week 1-2)
