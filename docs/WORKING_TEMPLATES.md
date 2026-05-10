# Working Templates After SCORM Export

**Source of truth:** `app/services/scorm_export.py` — `getRenderer()` registry + `TEMPLATE_TYPE_ALIASES` + `runtime_supported_template_types`

Verified April 20, 2026.

---

## ✅ FULLY WORKING — Dedicated Renderer Implemented

### Content / Presentation
| Type | Renderer | Notes |
|---|---|---|
| `content-text` | `renderContent` | Full rich HTML body |
| `content` | `renderContent` | Alias for content-text |
| `rich-text-editor` | `renderRichText` | Renders `data.htmlContent` |
| `content-media` | `renderImage` | Image with caption/alt |
| `content-image` | `renderImage` | Image gallery (single image rendered) |
| `content-video` | `renderVideo` | `<video>` with autoplay, transcript support |
| `infographic` | `renderImage` | Renders as image |
| `quotation` | `renderQuotation` | Blockquote + attribution |

### Navigation / Layout
| Type | Renderer | Notes |
|---|---|---|
| `tabs` | `renderTabs` | Interactive tab switching |
| `accordion` | `renderAccordion` | Interactive expand/collapse |
| `stepper` | `renderStepper` | Numbered step list |
| `timeline` | `renderTimeline` | Event list with date labels |
| `course-menu` | `renderModuleOverview` | Renders module list |
| `sidebar-navigation` | `renderModuleOverview` | Renders as module list |

### Assessment
| Type | Renderer | Notes |
|---|---|---|
| `mcq` | `renderMCQ` | Radio select + feedback + SCORM scoring |
| `quiz` | `renderMCQ` | Same as MCQ |
| `multiple-select` | `renderMultipleSelect` | Checkbox select |
| `true-false` | `renderTrueFalse` | True/False radio + feedback |
| `fill-in-blank` | `renderFillInBlank` | Text input + answer check |
| `hotspot` | `renderHotspot` | Image + hotspot list |
| `image-hotspots` | `renderHotspot` | Same as hotspot |

### Knowledge Check
| Type | Renderer | Notes |
|---|---|---|
| `key-takeaways` | `renderKeyTakeaways` | Bulleted takeaway list |
| `summary-takeaways` | `renderKeyTakeaways` | Same as key-takeaways |
| `learning-objectives` | `renderLearningObjectives` | Numbered objectives list |
| `flashcard` | `renderFlashcard` | Flip card with front/back interaction |

### Scenario
| Type | Renderer | Notes |
|---|---|---|
| `scenario` | `renderScenario` | Scenario text + options + feedback |
| `branching-scenario` | `renderScenario` | Same renderer as scenario |
| `decision-tree` | `renderScenario` | Same renderer as scenario |
| `role-play` | `renderScenario` | Same renderer as scenario |

### Data & Analytics
| Type | Renderer | Notes |
|---|---|---|
| `metric` | `renderMetric` | Value + label + unit + trend |
| `data-visualization` | `renderDataTable` | Renders as HTML table |
| `analytics-view` | `renderDataTable` | Same as data-visualization |
| `heat-map` | `renderDataTable` | Same as data-visualization |
| `progress-tracker` | `renderProgressTracker` | Progress bar with % |

### Interactive Tools
| Type | Renderer | Notes |
|---|---|---|
| `code-snippet` | `renderCodeSnippet` | Syntax-highlighted `<pre><code>` block |

### Learning Path
| Type | Renderer | Notes |
|---|---|---|
| `learning-roadmap` | `renderTimeline` | Rendered as timeline |
| `module-overview` | `renderModuleOverview` | Module list with descriptions |
| `course-map` | `renderModuleOverview` | Same as module-overview |

---

## ⚠️ WORKS VIA FALLBACK — Renders as Content (Limited UI)

These types are in the renderer registry but mapped to a generic renderer.
They export without errors but **do not show their native interaction UI**.

| Type | Fallback Renderer | Missing |
|---|---|---|
| `transcript-caption` | `renderContent` | No synchronized caption UI |
| `breadcrumb` | `renderContent` | No nav links |
| `matching` | `renderContent` | No drag-to-match UI |
| `drag-and-drop` | `renderContent` | No drag UI |
| `calculator` | `renderContent` | No calculation inputs |
| `form` | `renderContent` | No form fields |
| `interactive-tool` | `renderContent` | No custom tool UI |

---

## ✅ WORKING VIA ALIASES — Mapped to Working Types

These authoring type names are remapped to a working canonical type via `TEMPLATE_TYPE_ALIASES`. They export and render correctly.

| Alias / Authoring Type | Maps To | Transform Applied |
|---|---|---|
| `video` | `content-video` | None |
| `content_text` | `content-text` | None |
| `video-slide` | `content-video` | None |
| `text-with-media` | `content-media` | None |
| `step-by-step` | `stepper` | None |
| `knowledge-check` | `quiz` → `mcq` | None |
| `quiz-game` | `quiz` → `mcq` | None |
| `flashcards` | `flashcard` | None |
| `flip-cards` | `flashcard` | None |
| `fill-blanks` | `fill-in-blank` | None |
| `role-play-simulation` | `role-play` | None |
| `click-reveal` | `accordion` | `items` → `panels[{title, body}]` |
| `layered-content` | `accordion` | `layers` → `panels[{title, body}]` |
| `case-study` | `accordion` | `sections` → `panels[{title, body}]` |
| `code-of-conduct` | `accordion` | `sections` → `panels[{title, body}]` |
| `screen-reader-guide` | `accordion` | `sections` → `panels[{title, body}]` |
| `clickable-icons` | `accordion` | `icons` → `panels[{title, body}]` |
| `before-after` | `tabs` | `beforeContent/afterContent` → `tabs[{id, title, body}]` |
| `dos-donts` | `tabs` | Structural transform |
| `scenario-debate` | `tabs` | Structural transform |
| `animated-explainer` | `stepper` | Structural transform |
| `guided-practice` | `stepper` | Structural transform |
| `software-simulation` | `stepper` | Structural transform |
| `cycle-diagram` | `timeline` | Structural transform |
| `comparison-table` | `data-visualization` | Structural transform |
| `keyboard-nav-guide` | `data-visualization` | Structural transform |
| `matrix-grid` | `data-visualization` | Structural transform |
| `skill-gap-analysis` | `data-visualization` | Structural transform |
| `skill-mastery-report` | `data-visualization` | Structural transform |
| `audit-checklist` | `key-takeaways` | Structural transform |
| `quick-tips` | `key-takeaways` | Structural transform |
| `microlearning-cards` | `flashcard` | Structural transform |
| `recommendation-card` | `module-overview` | Structural transform |
| `scenario-question` | `scenario` | None |
| `regulatory-scenario` | `scenario` | None |

---

## ❌ NOT WORKING — No Renderer (Shows "Unknown slide type")

These types are registered in the renderer manifest (`renderer_manifest.py`) with `isExportable=True` but have **no entry in the player's `getRenderer()` registry**. They export without ZIP errors but display "Unknown slide type: …" in the SCORM player.

| Type | Category |
|---|---|
| `audio-player` | Media Interaction |
| `document-viewer` | Media Interaction |
| `carousel` | Media Interaction |
| `glossary` | Accessibility |
| `footnote` | Accessibility |
| `caption-assist` | Accessibility |
| `text-highlighter` | Accessibility |
| `badge` | Engagement |
| `point-system` | Engagement |
| `gamification-widget` | Engagement |
| `download-resource` | Resources |
| `resource-library` | Resources |
| `external-link` | Resources |
| `section-header` | Structural |
| `divider` | Structural |
| `spacer` | Structural |
| `container` | Structural |

---

## 🚫 NOT EXPORTABLE — Skipped or Replaced by Fallback

These types are marked `isExportable=False` in the manifest. They are replaced with a fallback component during export.

| Type | Fallback Used | Reason |
|---|---|---|
| `discussion-forum` | `summary-takeaways` | Dynamic/server-side |
| `comment-section` | `content-text` | Dynamic/server-side |
| `peer-review` | `quiz` | Dynamic/server-side |
| `leaderboard` | `data-visualization` | Dynamic/server-side |

---

## Summary

| Status | Count |
|---|---|
| ✅ Fully working (dedicated renderer) | 45 types |
| ⚠️ Works via fallback (limited UI) | 7 types |
| ✅ Working via aliases | 35 aliases |
| ❌ Not working (unknown type in player) | 17 types |
| 🚫 Not exportable | 4 types |
