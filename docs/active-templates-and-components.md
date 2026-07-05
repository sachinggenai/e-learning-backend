# Active Template Definitions & Component Registries

> Generated: 2026-07-06 | Schema Version: 2.0.0
>
> Source tables: `template_definitions`, `component_types`
> All items listed are `is_active = true`

---

## Table of Contents

- [Template Definitions (5)](#template-definitions-5)
- [Component Registries (89 across 17 categories)](#component-registries-89-across-17-categories)
  - [1. Content Presentation (7)](#1-content-presentation-7)
  - [2. Process & Flow (5)](#2-process--flow-5)
  - [3. Interaction (5)](#3-interaction-5)
  - [4. Scenario-Based (4)](#4-scenario-based-4)
  - [5. Assessment (8)](#5-assessment-8)
  - [6. Comparison & Analysis (4)](#6-comparison--analysis-4)
  - [7. Media-Rich (4)](#7-media-rich-4)
  - [8. Microlearning (3)](#8-microlearning-3)
  - [9. Navigation & Structural (5)](#9-navigation--structural-5)
  - [10. Gamification (4)](#10-gamification-4)
  - [11. Compliance & Corporate (5)](#11-compliance--corporate-5)
  - [12. Diagnostic & Adaptive (5)](#12-diagnostic--adaptive-5)
  - [13. Practice & Simulation (5)](#13-practice--simulation-5)
  - [14. Feedback & Reflection (5)](#14-feedback--reflection-5)
  - [15. Social & Collaborative (5)](#15-social--collaborative-5)
  - [16. Accessibility & Support (5)](#16-accessibility--support-5)
  - [17. Analytics & Learning Insight (5)](#17-analytics--learning-insight-5)
- [API Endpoints](#api-endpoints)
- [Database Meta Reference](#database-meta-reference)
- [Architecture Notes](#architecture-notes)

---

## Template Definitions (5)

**Source:** `template_definitions` table (`is_active = true`)
**Seeded via:** `scripts/seed_template_definitions.py`
**API:** `GET /ai/templates` — lists active template contracts for the AI agent
**Model:** `TemplateDefinition` ORM (`app/models/persisted_course.py:112`)

| # | `template_type` | Display Name | SCORM Interaction | Reports Score | Renderer Class | Fields | Pre-requisites |
|---|----------------|-------------|-------------------|---------------|----------------|--------|----------------|
| 1 | `mcq` | Multiple Choice Question | `choice` | Yes | `MCQRenderer` | `questions` (list, required), `content` (text, optional) | Schema must have `questions[]` array with `{id, question, options[{id, text, isCorrect}]}`; min 2 options per question, max 6 |
| 2 | `content-text` | Text Content | `none` | No | `ContentRenderer` | `content` (html, required), `subtitle` (text, optional) | `content` field sanitized as `html` (structurally preserved); `<script>` tags stripped by validator |
| 3 | `content-video` | Video Content | `none` | No | `ContentRenderer` | `content` (text, optional), `videoUrl` (text, **required**), `subtitle` (text, optional) | `videoUrl` must be a valid URI; render template wraps in `<video controls>` with `source` element |
| 4 | `welcome` | Welcome Screen | `none` | No | `ContentRenderer` | `content` (html, required), `subtitle` (text, optional) | Identical schema shape to `content-text` but distinct `render_template_html` CSS class (`welcome-screen`); used for course entry pages |
| 5 | `summary` | Summary Screen | `none` | No | `ContentRenderer` | `content` (html, required), `subtitle` (text, optional) | Identical schema shape to `content-text`; distinct CSS class (`summary-screen`); used for course conclusion pages |

### Template Definition Meta Columns

| Column | Type | Purpose |
|--------|------|---------|
| `id` | Integer PK | Internal autoincrement |
| `template_type` | String(100) UNIQUE | Type key used by AI agent and SCORM exporter (e.g. `mcq`, `content-text`) |
| `display_name` | String(200) | Human-readable label |
| `schema_signature` | String(64) INDEXED | SHA-256 hash of the canonical field schema — used for content/schema mismatch detection |
| `render_template_html` | Text | Jinja2 HTML template with `{{ data.field }}` placeholders rendered at SCORM export |
| `schema_json` | JSON | Full payload: `field_schema`, `render_config`, `sanitize_rules`, `scorm_behavior`, `renderer_class`, `layout_version` |
| `is_active` | Boolean (default `true`) | Master on/off — inactive definitions are excluded from AI proposals and SCORM rendering |
| `created_at` | DateTime | Creation timestamp |
| `updated_at` | DateTime | Last-updated timestamp |

---

## Component Registries (89 across 17 categories)

**Source:** `component_types` table (`is_active = true`)
**Seeded via:** `app/services/seed_component_types.py` (at startup)
**API:** `GET /components?isActive=true` — paginated listing; `GET /components/categories` — grouped counts
**Model:** `ComponentType` ORM (`app/models/component_type.py:17`)

### Component Registry Meta Columns

| Column | Type | Purpose |
|--------|------|---------|
| `type_id` | String(100) UNIQUE | Canonical slug used as `ComponentRecord.component_type` value (e.g. `mcq`, `drag-drop`) |
| `display_name` | String(200) | Human-readable label |
| `description` | Text | One-line explanation of what the component does |
| `category` | String(100) INDEXED | Grouping key — 17 predefined categories |
| `icon` | String(100) | CSS/icon identifier for UI picker |
| `scoring_enabled` | Boolean | Whether the component can produce a score |
| `max_score` | Float nullable | Maximum score when scoring is enabled (typically 100) |
| `scoring_rules` | JSON nullable | Custom scoring logic configuration |
| `completion_capabilities` | JSON list | Enumerated ways this component can satisfy completion: `view`, `interact`, `audio`, `score` |
| `default_completion_type` | String(50) | Default way the LMS marks this component complete (one of the above) |
| `audio_support` | JSON | `{perComponent, perInteraction, interactionPoints[]}` — audio narration capabilities |
| `schema` | JSON | JSON Schema for validating `ComponentRecord.data` |
| `default_data` | JSON | Default data payload when creating a new instance |
| `tags` | JSON list | Search/filter tags |
| `sort_order` | Integer | Order in UI picker within category |
| `is_active` | Boolean (default `true`) | Master on/off — inactive types hidden from UI and API listings |
| `estimated_duration` | Float nullable | Typical learner time in minutes |
| `created_at` | DateTime | Creation timestamp |
| `updated_at` | DateTime | Last-updated timestamp |

---

### 1. Content Presentation (7)

**API:** `GET /components/categories/content-presentation`

| type_id | Display Name | Scoring | Default Completion | Audio Support | Pre-requisites |
|---------|-------------|---------|-------------------|---------------|----------------|
| `tabs` | Tabbed Content | No | `interact` | perComponent + perInteraction (tab) | `data.tabs[]` array with `{id, label, content}`; min 1 tab |
| `accordion` | Accordion | No | `interact` | perComponent + perInteraction (panel) | `data.panels[]` array with `{id, title, content}`; min 1 panel |
| `click-reveal` | Click and Reveal | No | `interact` | perComponent + perInteraction (reveal-item) | Content items with hidden state toggled by click |
| `timeline` | Timeline | No | `view` | perComponent + perInteraction (event) | Chronological event entries with timestamps |
| `image-hotspots` | Image Hotspots | No | `interact` | perComponent + perInteraction (hotspot) | Base image + hotspot coordinate map |
| `layered-content` | Layered Content | No | `interact` | perComponent + perInteraction (layer) | Stacked layers with z-order and visibility toggles |
| `text-with-media` | Text with Media | No | `view` | perComponent only | Rich text block + optional embedded media reference |

---

### 2. Process & Flow (5)

**API:** `GET /components/categories/process-flow`

| type_id | Display Name | Scoring | Default Completion | Audio Support | Pre-requisites |
|---------|-------------|---------|-------------------|---------------|----------------|
| `step-by-step` | Step-by-Step Process | No | `interact` | perComponent + perInteraction (step) | Ordered step list with sequential progression; each step unlockable |
| `cycle-diagram` | Cycle Diagram | No | `view` | perComponent + perInteraction (stage) | Circular stage nodes with connecting edges |
| `flowchart` | Flowchart | No | `view` | none | Directed graph: nodes + edges; static rendering only |
| `process-map` | Process Map | No | `view` | perComponent + perInteraction (node) | 2D spatial layout of process nodes with connections |
| `decision-tree` | Decision Tree | No | `interact` | perComponent + perInteraction (decision) | Branching nodes with conditional paths; user selects path at each decision point |

---

### 3. Interaction (5)

**API:** `GET /components/categories/interaction`

| type_id | Display Name | Scoring | Max Score | Default Completion | Audio Support | Pre-requisites |
|---------|-------------|---------|-----------|-------------------|---------------|----------------|
| `drag-drop` | Drag and Drop | Yes | 100 | `interact` | none | Draggable items + drop zone definitions; scoring rules in `scoring_rules` JSON |
| `flip-cards` | Flip Cards | No | — | `interact` | perComponent + perInteraction (card) | Cards with front/back content; click to flip |
| `slider` | Slider | No | — | `interact` | none | Min/max range, step value, labels; value emitted on interaction |
| `carousel` | Carousel | No | — | `view` | perComponent + perInteraction (slide) | Slide array with navigation controls |
| `clickable-icons` | Clickable Icons | No | — | `interact` | perComponent + perInteraction (icon) | Icon grid; each icon has a content/tooltip revealed on click |

---

### 4. Scenario-Based (4)

**API:** `GET /components/categories/scenario`

| type_id | Display Name | Scoring | Max Score | Default Completion | Audio Support | Pre-requisites |
|---------|-------------|---------|-----------|-------------------|---------------|----------------|
| `scenario` | Scenario | Yes | 100 | `interact` | perComponent + perInteraction (choice) | Scenario narrative + choice points; scoring per choice |
| `branching-scenario` | Branching Scenario | Yes | 100 | `interact` | perComponent + perInteraction (branch) | Directed graph of scenario nodes; branch on each user choice; cumulative scoring |
| `role-play` | Role-Play Simulation | Yes | 100 | `interact` | perComponent + perInteraction (dialogue) | Character definitions + dialogue tree; scoring on decision quality |
| `case-study` | Case Study | No | — | `view` | none | Multi-section analysis document with supporting materials |

---

### 5. Assessment (8)

**API:** `GET /components/categories/assessment`

| type_id | Display Name | Scoring | Max Score | Default Completion | Audio Support | Pre-requisites |
|---------|-------------|---------|-----------|-------------------|---------------|----------------|
| `mcq` | Multiple Choice | Yes | 100 | `score` | none | `data.questions[]` with `{id, question, options[{id, text, isCorrect}], explanation, points}`; min 2 options; `shuffleQuestions`, `shuffleOptions`, `showFeedback` flags |
| `multi-select` | Multiple Select | Yes | 100 | `score` | none | Same as MCQ but >=1 correct options per question; partial credit configurable |
| `true-false` | True / False | Yes | 100 | `score` | none | Statement + boolean answer; supports explanation feedback |
| `fill-blanks` | Fill in the Blanks | Yes | 100 | `score` | none | Text with `___` placeholder tokens; answer key per blank; supports fuzzy matching |
| `matching` | Matching | Yes | 100 | `score` | none | Two-column item lists; learner draws connections; scoring on correct pairs |
| `scenario-question` | Scenario-Based Question | Yes | 100 | `score` | perComponent + perInteraction (scenario-step) | Scenario preamble + embedded questions; context carries across steps |
| `knowledge-check` | Knowledge Check | Yes | 100 | `score` | none | Lightweight quiz; untimed; typically not graded (formative) |
| `final-assessment` | Final Assessment | Yes | 100 | `score` | none | Composite assessment supporting MCQ / multi-select / true-false / fill-in-blank question types; `passingScore` (default 80), `maxAttempts`, `showCorrectAnswers` config; `introText` preamble |

---

### 6. Comparison & Analysis (4)

**API:** `GET /components/categories/comparison`

| type_id | Display Name | Scoring | Completion | Audio | Pre-requisites |
|---------|-------------|---------|------------|-------|----------------|
| `comparison-table` | Comparison Table | No | `view` | none | Column headers + row data; optional highlighting rules |
| `pros-cons` | Pros and Cons | No | `view` | none | Two-column list: pros / cons; each entry has text + optional weight |
| `before-after` | Before and After | No | `view` | none | Split-view: "before" state + "after" state with slider/overlay toggle |
| `matrix-grid` | Matrix / Grid | No | `view` | none | NxM grid; row and column labels; cell content |

---

### 7. Media-Rich (4)

**API:** `GET /components/categories/media-rich`

| type_id | Display Name | Scoring | Completion | Audio | Pre-requisites |
|---------|-------------|---------|------------|-------|----------------|
| `video-slide` | Video-Based Slide | No | `view` | none | Embedded video URL; completion on play-through or view |
| `audio-slide` | Audio-Based Slide | No | `audio` | none | Embedded audio URL; completion on listen-through (satisfies `audio` capability) |
| `animated-explainer` | Animated Explainer | No | `view` | none | Lottie/CSS animation definition + supporting text |
| `infographic` | Infographic | No | `view` | none | SVG/static infographic with optional zoom/pan |

---

### 8. Microlearning (3)

**API:** `GET /components/categories/microlearning`

| type_id | Display Name | Scoring | Completion | Audio | Pre-requisites |
|---------|-------------|---------|------------|-------|----------------|
| `microlearning-cards` | Microlearning Cards | No | `view` | perComponent + perInteraction (card) | Card stack; single concept per card; swipe/tap to advance |
| `flashcards` | Flashcards | No | `interact` | perComponent + perInteraction (card) | Front (prompt) + back (answer); self-assessment toggle (knew/didn't know) |
| `quick-tips` | Quick Tips | No | `view` | none | Bulleted tip list; optional icon per tip |

---

### 9. Navigation & Structural (5)

**API:** `GET /components/categories/navigation`

| type_id | Display Name | Scoring | Completion | Audio | Pre-requisites |
|---------|-------------|---------|------------|-------|----------------|
| `course-menu` | Course Menu | No | (none) | none | Module/section list with links; `completion_capabilities: []` — purely structural |
| `learning-roadmap` | Learning Roadmap | No | `view` | none | Visual roadmap with milestones and completion states |
| `module-overview` | Module Overview | No | `view` | none | Module title, objectives, estimated time, prerequisite badges |
| `summary` | Summary / Key Takeaways | No | `view` | none | Key-point list + optional "next steps" call-to-action |
| `resources-downloads` | Resources & Downloads | No | `view` | none | File list with download links; tracks download interaction |

---

### 10. Gamification (4)

**API:** `GET /components/categories/gamification`

| type_id | Display Name | Scoring | Max Score | Completion | Audio | Pre-requisites |
|---------|-------------|---------|-----------|------------|-------|----------------|
| `quiz-game` | Quiz Game | Yes | 100 | `score` | none | Timed quiz with points, streaks, leaderboard hooks |
| `points-badges` | Points and Badges | No | — | (none) | none | Display-only: earned points + unlocked badges; `completion_capabilities: []` |
| `progress-tracker` | Progress Tracker | No | — | (none) | none | Visual progress bar/ring per module; `completion_capabilities: []` |
| `level-learning` | Level-Based Learning | Yes | 100 | `interact` | none | Gated levels; each level requires previous completion; scoring on level mastery |

---

### 11. Compliance & Corporate (5)

**API:** `GET /components/categories/compliance`

| type_id | Display Name | Scoring | Max Score | Completion | Audio | Pre-requisites |
|---------|-------------|---------|-----------|------------|-------|----------------|
| `policy-acknowledgement` | Policy Acknowledgement | No | — | `interact` | none | Policy text + mandatory checkbox/signature; completion = acknowledged |
| `dos-donts` | Do's and Don'ts | No | — | `view` | none | Two-column format: Do / Don't; each with icon + explanation |
| `code-of-conduct` | Code of Conduct | No | — | `view` | none | Structured ethics/conduct document with section navigation |
| `regulatory-scenario` | Regulatory Scenario | Yes | 100 | `interact` | perComponent + perInteraction (scenario-step) | Compliance scenario with regulatory decision points; scored on correct regulatory action |
| `audit-checklist` | Audit Checklist | No | — | `interact` | none | Interactive checklist items; each item has status (pending/compliant/non-compliant) |

---

### 12. Diagnostic & Adaptive (5)

**API:** `GET /components/categories/diagnostic`

| type_id | Display Name | Scoring | Max Score | Completion | Audio | Pre-requisites |
|---------|-------------|---------|-----------|------------|-------|----------------|
| `pre-assessment` | Pre-Assessment | Yes | 100 | `score` | none | Placement quiz taken before course; determines starting level |
| `diagnostic-quiz` | Diagnostic Quiz | Yes | 100 | `score` | none | In-course diagnostic; identifies knowledge gaps |
| `skill-gap-analysis` | Skill Gap Analysis | No | — | `interact` | none | Self-assessment matrix: current vs required skills |
| `adaptive-path` | Adaptive Learning Path | No | — | `interact` | none | Branching path based on prior assessment results; personalized route |
| `recommendation-card` | Recommendation Card | No | — | `view` | none | Contextual learning recommendation based on gap analysis |

---

### 13. Practice & Simulation (5)

**API:** `GET /components/categories/practice`

| type_id | Display Name | Scoring | Max Score | Completion | Audio | Pre-requisites |
|---------|-------------|---------|-----------|------------|-------|----------------|
| `guided-practice` | Guided Practice | No | — | `interact` | perComponent + perInteraction (step) | Step-by-step walkthrough with hints; no scoring pressure |
| `try-it-simulation` | Try-It Simulation | No | — | `interact` | none | Sandbox environment; learner freely experiments |
| `software-simulation` | Software Simulation | No | — | `interact` | none | Screenshot/interface with click zones; simulates software interaction |
| `sandbox-practice` | Sandbox Practice | No | — | `interact` | none | Free-form practice area; no constraints or scoring |
| `error-identification` | Error Identification | Yes | 100 | `interact` | none | Scenario with embedded errors; learner identifies and explains each |

---

### 14. Feedback & Reflection (5)

**API:** `GET /components/categories/feedback`

| type_id | Display Name | Scoring | Completion | Audio | Pre-requisites |
|---------|-------------|---------|------------|-------|----------------|
| `reflective-question` | Reflective Question | No | `interact` | none | Open-ended prompt; free-text response; optionally shareable |
| `learner-journal` | Learner Journal | No | `interact` | none | Multi-entry journal; date-stamped entries; private to learner |
| `self-assessment` | Self-Assessment | No | `interact` | none | Rubric-based self-rating on competencies |
| `confidence-rating` | Confidence Rating | No | `interact` | none | Likert-scale confidence question; pre/post topic comparison |
| `action-planning` | Action Planning | No | `interact` | none | Goal-setting template: objective, actions, timeline, success criteria |

---

### 15. Social & Collaborative (5)

**API:** `GET /components/categories/social`

| type_id | Display Name | Scoring | Max Score | Completion | Audio | Pre-requisites |
|---------|-------------|---------|-----------|------------|-------|----------------|
| `discussion-prompt` | Discussion Prompt | No | — | `interact` | none | Topic prompt + threaded response area; requires multi-user context |
| `peer-review` | Peer Review | No | — | `interact` | none | Submission + rubric; peer assignment and anonymous review |
| `poll-vote` | Poll / Vote | No | — | `interact` | none | Single/multi-choice poll; real-time results display |
| `team-challenge` | Team Challenge | Yes | 100 | `interact` | none | Group task with team scoring; requires group membership |
| `scenario-debate` | Scenario Debate | No | — | `interact` | none | Position assignment + structured argumentation; requires peer presence |

---

### 16. Accessibility & Support (5)

**API:** `GET /components/categories/accessibility`

| type_id | Display Name | Scoring | Completion | Audio | Pre-requisites |
|---------|-------------|---------|------------|-------|----------------|
| `accessibility-tip` | Accessibility Tip Card | No | `view` | none | WCAG-compliant tip card; keyboard-focusable |
| `keyboard-nav-guide` | Keyboard Navigation Guide | No | `view` | none | Keyboard shortcut reference; scoped to current course context |
| `screen-reader-guide` | Screen Reader Guide | No | `view` | none | Screen-reader usage instructions with ARIA examples |
| `language-selector` | Language Selector | No | (none) | none | Locale dropdown; `completion_capabilities: []` — structural only |
| `transcript-page` | Transcript / Caption Page | No | `view` | none | Full transcript text for video/audio content; searchable |

---

### 17. Analytics & Learning Insight (5)

**API:** `GET /components/categories/analytics`

| type_id | Display Name | Scoring | Completion | Audio | Pre-requisites |
|---------|-------------|---------|------------|-------|----------------|
| `progress-summary` | Learning Progress Summary | No | (none) | none | Aggregated progress data from LMS; `completion_capabilities: []` |
| `performance-dashboard` | Performance Dashboard | No | (none) | none | Charts + metrics from scored assessments; `completion_capabilities: []` |
| `skill-mastery-report` | Skill Mastery Report | No | (none) | none | Radar/bar chart per skill domain; `completion_capabilities: []` |
| `completion-certificate` | Completion Certificate | No | (none) | none | Certificate display with learner name, course, date; `completion_capabilities: []` |
| `manager-review` | Manager Review Page | No | (none) | none | Summary dashboard for L&D managers; `completion_capabilities: []` |

---

## API Endpoints

### Template Definitions

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/ai/templates` | List all active template contracts for AI agent |
| `GET` | `/ai/templates/{type_key}` | Get single template contract detail with schema |

### Component Registry

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/components` | List all component types (paginated, filtered by `isActive`, `category`, `scoringEnabled`) |
| `GET` | `/components/categories` | List 17 categories with component counts |
| `GET` | `/components/categories/{categoryId}` | List types within a specific category |
| `GET` | `/components/search` | Free-text search across display_name, description, type_id + tag filtering |
| `GET` | `/components/{typeId}` | Get full component type detail with schema, etag, schemaVersion |

### Page Components (runtime instances)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET/POST` | `/courses/{courseId}/pages` | List/create pages |
| `GET/PUT/DELETE` | `/courses/{courseId}/pages/{pageId}` | Read/update/delete a page |
| `GET/POST` | `/courses/{courseId}/pages/{pageId}/components` | List/add components to a page |
| `GET/PUT/DELETE` | `/courses/{courseId}/pages/{pageId}/components/{compId}` | Read/update/delete a component instance |

---

## Database Meta Reference

| Table | ORM Model | Key File | Active Column | Seed File | Seed Count |
|-------|-----------|----------|---------------|-----------|------------|
| `template_definitions` | `TemplateDefinition` | `app/models/persisted_course.py:112` | `is_active` (Boolean, default True) | `scripts/seed_template_definitions.py` | 5 |
| `component_types` | `ComponentType` | `app/models/component_type.py:17` | `is_active` (Boolean, default True) | `app/services/seed_component_types.py` | 89 |
| `template_types` | `TemplateType` | `app/models/template_type.py:16` | `is_active` (Boolean, default True) | `app/services/seed_template_types.py` | 7 |
| `templates` | `TemplateRecord` | `app/models/persisted_course.py:62` | _(none)_ | — | per-course instances |
| `components` | `ComponentRecord` | `app/models/page_component.py:77` | _(none)_ | — | per-page instances |
| `pages` | `PageRecord` | `app/models/page_component.py:20` | _(none)_ | — | per-course instances |

### Repositories

| Repository | File | Default Filter |
|------------|------|----------------|
| `TemplateDefinitionRepository` | `app/repositories/template_definition_repo.py` | `list_all()` returns all rows (no active filter) |
| `ComponentTypeRepository` | `app/repositories/component_type_repo.py` | `list()`, `search()`, `get_categories()` all default to `is_active=True` |
| `TemplateTypeRepository` | `app/repositories/template_type_repo.py` | Default `active_only=True` |

### Startup Seeding Order

```
1. Create tables (Alembic migrations)
2. Seed component_types (89 items)
3. Seed template_types (7 items)
4. (No startup seed for template_definitions — seeded by alembic migration)
```

---

## Architecture Notes

1. **Templates and components are decoupled registries.** There is no FK or join table linking a `template_type` to specific `component_type` rows. Components are placed onto **pages** (`pages` table), and pages belong to **courses** (`courses` table). Any component can be placed on any page regardless of which template type the page uses.

2. **Two levels of "template" exist:**
   - **Template Types** (`template_types`): UI picker definitions (7 items) — high-level page structures like "Quiz Assessment", "Video Content"
   - **Template Definitions** (`template_definitions`): SCORM rendering contracts (5 items) — low-level HTML templates, field schemas, sanitization rules, renderer classes used by the dynamic SCORM export system

3. **The only template–component linkage at instance level** is `ComponentStyleRecord.template_id` → `templates.id` for per-component style overrides within a specific template instance.

4. **Component instances** (`ComponentRecord`) reference their type via `component_type` string (no FK constraint to `component_types.type_id`). Validation is done at the application layer via `app/utils/validation.py` which checks both `template_definitions` and `component_types` tables.

5. **28 of 89 components are scoring-enabled** (those with `scoring_enabled: true`). The remainder are formative/content/navigation components.

6. **7 components have empty `completion_capabilities`** (`course-menu`, `points-badges`, `progress-tracker`, `language-selector`, `progress-summary`, `performance-dashboard`, `skill-mastery-report`, `completion-certificate`, `manager-review`) — these are display-only and do not directly contribute to course completion tracking.

7. **Audio support** is available on 32 components via `audio_support.perComponent` or `audio_support.perInteraction`, enabling per-element narration in SCORM exports.

---

## Summary Counts

| Registry | Table | Active Items | Categories |
|----------|-------|-------------|------------|
| Template Definitions | `template_definitions` | **5** | — |
| Component Types | `component_types` | **89** | **17** |
| Template Types (UI picker) | `template_types` | **7** | — |
| **Total** | — | **101** | **17** |

| Metric | Count |
|--------|-------|
| Scoring-enabled components | 28 of 89 |
| Components with audio support | 32 of 89 |
| Display-only components (no completion) | 9 of 89 |
| SCORM-reporting template definitions | 1 of 5 (mcq) |
