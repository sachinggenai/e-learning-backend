# TemplateEngine Backend — Use Cases & API Mappings (Revised)

This document maps each core functionality requirement to specific APIs, data models, and implementation workflows. Each use case includes the user goal, affected systems, API endpoints, and step-by-step implementation flow.

---

## 1. Author Creates Course with Composable Components

**User Goal:**
Author uploads a course JSON with multiple pages, each page containing multiple components (tabs, MCQ, video, etc.) chosen from 89+ available types. Each component can have per-interaction audio narration and independent completion rules.

**Key APIs:**
- `POST /api/v1/courses` — Create course with new `pages[].components[]` structure
- `POST /api/v1/courses/{courseId}/pages` — Add page to course
- `POST /api/v1/courses/{courseId}/pages/{pageId}/components` — Add component to page
- `GET /api/v1/components/search` — Discover available component types by category/tag
- `GET /api/v1/components/{typeId}` — Fetch component type schema for validation

**Data Models Involved:**
- Request: `CourseExportRequest` → `Course` (Pydantic)
- Response: `Course` with `pages[]` array
- Each page: `Page` model with `layout_config`, `completion_config`, `theme_overrides`
- Each component: `Component` model with `componentType`, `data` (JSON per schema), `audioConfig`, `completionCriteria`

**DB Tables:**
- `courses` — Root course record
- `pages` — One row per page with `page_id`, `course_id`, `order_index`, layout/completion/theme config
- `components` — One row per component with `component_id`, `page_id`, `component_type`, `order_index`, `data` (JSONB), `audio_config`, `completion_criteria`
- `component_types` — Registry of 89 types with JSON schema in `schema_json` column

**Step-by-Step Flow:**
1. Author creates course JSON with structure: `{ courseId, title, author, pages: [{ title, components: [{ componentType: "tabs", data: {...}, audioConfig: {...} }] }] }`
2. Call `POST /courses` with JSON payload
3. Dependency `validate_course_json()` parses and validates using Component Type Registry:
   - Fetch each `component_type` from `component_types` table
   - Validate component `data` against JSON schema stored in `component_types.schema_json`
   - Validate `completionCriteria` references valid audio IDs if `requiredAudioIds` specified
4. `CourseRepository.create()` persists course → returns `courseId`
5. Service creates `PageRecord` for each page → `PageRecord.page_id` (UUID)
6. Service creates `ComponentRecord` for each component → validates against schema, persists `data` JSONB
7. Response includes fully-structured course with generated IDs

**Edge Cases Covered:**
- Backward compatibility: Legacy `templates[]` format auto-converted to `pages[].components[]` via conversion layer in router
- Missing IDs: Server generates `page_id` and `component_id` (UUIDs) if not provided
- Missing layout/completion config: Defaults applied (single-column layout, all-component completion strategy)
- Invalid component type: HTTP 422 with validation error showing allowed types

---

## 2. Author Designs Per-Component Audio Narration

**User Goal:**
Author adds narration audio that plays on specific interactions within a component. E.g., tab "Overview" has narration that plays when tab is selected; "Details" tab has separate narration. Audio can be required for page completion.

**Key APIs:**
- `POST /api/v1/assets/audio` — Upload audio file (returns server-generated `audioId`)
- `POST /api/v1/courses/{courseId}/pages/{pageId}/components` — Create component with `audioConfig`
- `PATCH /api/v1/courses/{courseId}/pages/{pageId}/components/{componentId}` — Update component audio
- `GET /api/v1/courses/{courseId}/narration` — List all audio across course pages
- `DELETE /api/v1/assets/audio/{audioId}` — Remove audio file

**Data Models Involved:**
- `AudioConfig`: `{ enabled: boolean, audioItems: [{audioId, triggerOn, targetInteractionId, requiredForCompletion, duration, label}] }`
- `AudioItem`: Server-generated `audioId` from upload response; trigger types = `["load", "click", "interaction"]`
- Component with audio: `{ componentType: "tabs", data: {...}, audioConfig: {...}, completionCriteria: { type: "audio", requiredAudioIds: ["audioId-uuid1", "audioId-uuid2"] } }`

**DB Tables:**
- `components.audio_config` (JSONB) — Stores audio item array with server-generated audioIds
- `components.completion_criteria` (JSONB) — Can reference `requiredAudioIds[]`
- Media file storage — `/media/files/{courseId}/audio/{filename}`

**Step-by-Step Flow:**
1. Author uploads audio via `POST /assets/audio` → server returns `{ audioId: "generated-uuid", audioUrl: "/media/files/.../narration.mp3", format: "mp3", duration: 45 }`
2. Author creates component with `audioConfig` (uses `audioId` from upload response):
   ```json
   {
     "componentType": "tabs",
     "data": { "tabs": [{ "id": "tab-1", "label": "Overview" }, { "id": "tab-2", "label": "Details" }] },
     "audioConfig": {
       "enabled": true,
       "audioItems": [
         { "audioId": "generated-uuid-1", "triggerOn": "interaction", "targetInteractionId": "tab-1", "requiredForCompletion": true, "duration": 45, "label": "Overview Narration" },
         { "audioId": "generated-uuid-2", "triggerOn": "interaction", "targetInteractionId": "tab-2", "requiredForCompletion": true, "duration": 32, "label": "Details Narration" }
       ]
     },
     "completionCriteria": { "type": "audio", "requiredAudioIds": ["generated-uuid-1", "generated-uuid-2"] }
   }
   ```
3. `POST /pages/{pageId}/components` validates audio refs exist, persists to `components.audio_config`
4. Author calls `GET /courses/{courseId}/narration` to review all narration across course
5. SCORM export generates player JS that:
   - Loads audio on `triggerOn` event (e.g., when tab is clicked)
   - Tracks completion when audio played to ≥90%
   - Stores state in `cmi.suspend_data` JSON

**Edge Cases Covered:**
- Audio not required: `requiredForCompletion: false` → component completes via other means (view, score, etc.)
- Multiple audio per interaction point: All audioItems for a target play in sequence
- Audio duration tracking: Server validates `duration` field; completion verified client-side (≥90% listened)

---

## 3. Author Enables Scoring Across Multiple Assessment Components

**User Goal:**
Author configures weighted scoring across course: MCQ worth 40%, drag-drop worth 30%, scenario worth 30%. Learner needs 70% to pass. Partial credit allowed for multi-select and matching. Score per attempt tracked (best/last/average).

**Key APIs:**
- `PATCH /api/v1/courses/{courseId}/scoring` — Update course scoring config
- `POST /api/v1/courses/{courseId}/scoring/calculate` — Calculate score from submitted answers
- `POST /api/v1/courses/{courseId}/scoring/validate` — Validate scoring config (weights sum to 1.0)
- `GET /api/v1/courses/{courseId}/scoring` — Fetch current scoring config
- `PATCH /api/v1/courses/{courseId}/pages/{pageId}/components/{componentId}` — Update component scoring rules

**Data Models Involved:**
- `ScoringConfig`: `{ passingScore: 70, maxAttempts: 3, attemptScoring: "best", showCorrectAnswers: true, weightedScoring: true, allowPartialCredit: true }`
- `ComponentScore`: `{ componentId, componentType: "mcq", weight: 0.4, maxPoints: 100 }`
- Response: Includes `componentResults[]` with per-question `questionResults` per spec §9.4

**DB Tables:**
- `course_scoring` — Stores course-level config + component weights
- `components` — Each scorable component validates against `component_types.scoringRules`

**Step-by-Step Flow:**
1. Author calls `PATCH /courses/{courseId}/scoring` with weighted config
2. Service validates: weights sum to 1.0, component types scorable per registry
3. Repository persists to `course_scoring` table
4. Learner submits answers: `POST /scoring/calculate` with responses
5. Scoring engine applies per-type rules:
   - MCQ: Binary — correct option → 100%, else 0%
   - Drag-drop with `partialCreditMode: "per-item"`: `(correctly_placed / total_items) * maxPoints`
   - Multi-select proportional: `(correct_selected - incorrect_selected) / total_correct * points` per spec §9.2
   - Scenario: Sum of choice node points along selected path
6. Weighted aggregation: `totalScore = sum(componentScore * weight)`
7. Response includes:
   ```json
   {
     "totalScore": 75.0,
     "percentage": 75.0,
     "passed": true,
     "passingScore": 70,
     "componentResults": [
       {
         "componentId": "comp-mcq-1",
         "score": 100,
         "weight": 0.4,
         "weightedScore": 40,
         "questionResults": [
           { "questionId": "q1", "correct": true, "score": 10 },
           { "questionId": "q2", "correct": true, "score": 10 }
         ]
       }
     ],
     "attemptNumber": 1,
     "remainingAttempts": 2
   }
   ```
8. Attempt tracking per `attemptScoring` mode (best/last/average)

**Edge Cases Covered:**
- Multi-select partial credit modes per spec §9.2 (`proportional` vs `all-or-nothing`)
- Matching partial credit via `partialCreditMode: "per-pair"` or `"all-or-nothing"`
- Unlimited attempts: `maxAttempts: null`
- Attempt scoring modes: Incentivize retry vs. fairness

---

## 4. Learner Completes Course with Multi-Level Completion Rules

**User Goal:**
Learner navigates course. System tracks component completion per criteria (view, interact, audio, score, or custom). Page complete when all/any/X% of components done. Course complete when all enabled pages complete. Real-time progress updates.

**Key APIs:**
- `GET /api/v1/courses/{courseId}/completion` — Get overall course completion status
- `GET /api/v1/courses/{courseId}/pages/{pageId}/completion` — Get page completion status
- `POST /api/v1/courses/{courseId}/pages/{pageId}/completion` — Record page complete event
- `POST /api/v1/courses/{courseId}/interactions` — Record component interaction

**Data Models Involved:**
- `CompletionCriteria` (per component): `{ type: "view|interact|audio|score|custom", threshold: 70, requiredInteractions, requiredAudioIds }`
- `PageCompletion` (per page): `{ enabled, strategy: "all|any|percentage|custom", completionThreshold, requiredComponents }`

**DB Tables:**
- `components.completion_criteria` (JSONB)
- `pages.completion_config` (JSONB)
- Session/in-memory cache for learner progress tracking

**Step-by-Step Flow:**

**Completion Algorithm (per spec §8.2):**
```
function isPageComplete(page):
  if not page.completion_config.enabled:
    return true
  else:
    switch page.completion_config.strategy:
      "all": return ALL components complete
      "any": return ANY component complete
      "percentage": return (completed / total) >= threshold
      "custom": return ALL requiredComponents[] complete
```

**Event Recording:**
1. Learner views page → `POST /interactions`: `{ pageId, componentId, interactionType: "view" }`
2. Service marks component complete if `completionCriteria.type == "view"`
3. Learner clicks tab → `POST /interactions`: `{ componentId, interactionType: "click", data: { interactionId: "tab-1" } }`
4. Service checks if all `requiredInteractions` satisfied
5. Learner plays audio → tracked to 90% listened = complete
6. All events trigger `checkPageCompletion()` → `checkCourseCompletion()`

**Completion Status Query:**
```json
GET /courses/{courseId}/completion
{
  "courseId": "c-1",
  "status": "in-progress",
  "overallProgress": 65.0,
  "pages": [
    {
      "pageId": "p-1",
      "title": "Introduction",
      "completed": true,
      "strategy": "all",
      "components": [
        { "componentId": "comp-1", "completed": true, "completionType": "view" }
      ]
    }
  ]
}
```

**SCORM Integration:**
- `cmi.core.lesson_status = "completed"` when all pages complete
- If scoring: `"passed"` (score ≥ threshold) or `"failed"`

**Edge Cases Covered:**
- Disabled pages skipped in completion check
- Mixed strategies per page (some "all", others "percentage")
- Audio ≥90% listened requirement
- Score threshold separate from attempt number
- Custom component selection via `requiredComponents[]`

---

## 5. Author Customizes Course Theme (Colors, Typography, Component Styles)

**User Goal:**
Author selects preset theme (Light, Dark, Corporate) or creates custom theme with branded colors, font, button styles. Applies to course or overrides per-page.

**Key APIs:**
- `GET /api/v1/themes/presets` — List 5-10 built-in preset themes
- `POST /api/v1/themes` — Create custom theme
- `PATCH /api/v1/courses/{courseId}/theme` — Set course theme
- `PATCH /api/v1/courses/{courseId}/pages/{pageId}/theme` — Set page theme override
- `GET /api/v1/courses/{courseId}/pages/{pageId}/theme` — Get resolved theme with inheritance

**Data Models Involved:**
- `Theme`: `{ themeId, name, isPreset, colors, typography, componentStyles }`
- `ThemeOverrides`: Only changed properties merge with inherited theme

**DB Tables:**
- `themes` — Preset + custom theme definitions with JSONB
- `courses.theme_id` (FK) — Course default theme
- `pages.theme_overrides` (JSONB) — Page-level overrides

**Step-by-Step Flow:**
1. Author selects preset: `PATCH /courses/{courseId}/theme`: `{ "themeId": "preset-dark" }`
2. Or creates custom: `POST /themes`: `{ name, colors, typography, componentStyles }`
3. Page override: `PATCH /pages/{pageId}/theme`: `{ overrides: { colors: { primary: "#2196F3" } } }`
4. Resolve theme: `GET /pages/{pageId}/theme` retrieves inherited chain (preset → course → page)
5. SCORM export generates `theme.css` from resolved theme with CSS variables
6. Component HTML uses variables: `<button style="background: var(--color-primary)">Click</button>`

**Edge Cases Covered:**
- Incomplete override inherits from course theme
- Preset immutability (`isPreset: true` cannot delete)
- CSS nesting and variant selectors (button:hover, button:disabled)

---

## 6. Author Manages Component Type Registry (Browse, Enable/Disable, Custom Types)

**User Goal:**
Admin views 89 built-in component types organized by 17 categories. Searches by tag or category. Disables type (mark inactive) without deleting. Can create custom types.

**Key APIs:**
- `GET /api/v1/components` — List types (paginated, filterable)
- `GET /api/v1/components/{typeId}` — Get type schema
- `GET /api/v1/components/categories` — List categories with counts
- `GET /api/v1/components/categories/{categoryId}` — Types in category
- `GET /api/v1/components/search` — Search by query, tags, scoringEnabled
- `PATCH /api/v1/components/{typeId}` — Update type (disable, update schema)

**Data Models Involved:**
- `ComponentType`: All 89 types with schemas, scoring rules, audio support flags
- Per spec §6.1: 17 categories (content-presentation, assessment, interaction, etc.)

**DB Tables:**
- `component_types` — 89 seeded types + custom types; `is_active` flag

**Step-by-Step Flow:**
1. List all: `GET /components?page=1&limit=50`
2. Filter by category: `GET /components/categories/assessment`
3. Search: `GET /components/search?query=interactive&scoringEnabled=true`
4. Get schema: `GET /components/mcq` returns full schema for validation
5. Disable type: `PATCH /components/mcq { "isActive": false }`
6. Existing components using disabled type still render; new components cannot use it

**Edge Cases Covered:**
- Active/inactive filtering on authoring endpoints
- Immutable built-in types (seeded)
- Deep schema validation for complex types

---

## 7. Author Builds Course with Responsive Page Layouts

**User Goal:**
Author creates pages with different layout presets (single-column, two-column, sidebar-left/right, three-column grid). Components positioned in layout. Layout adapts to mobile (stacks).

**Key APIs:**
- `POST /api/v1/courses/{courseId}/pages` — Create page with `layoutConfig: { preset, spacing }`
- `PATCH /api/v1/courses/{courseId}/pages/{pageId}` — Update page layout
- `POST /api/v1/courses/{courseId}/pages/{pageId}/components` — Add component (flows in document order)

**Data Models Involved:**
- `PageLayout`: `{ preset: "single-column|two-column|sidebar-left|sidebar-right|three-column-grid", spacing: "compact|normal|loose" }`

**DB Tables:**
- `pages.layout_config` (JSONB)

**Step-by-Step Flow:**
1. Author creates page: `POST /pages { title, layoutConfig: { preset: "two-column", spacing: "normal" } }`
2. Adds components in order (order_index 0, 1, 2...)
3. SCORM export generates grid CSS from preset
4. Components render in order within grid
5. Media queries for mobile: stacks components on small screens

**Edge Cases Covered:**
- Layout changes reflow but keep component order
- Spacing variants (compact/normal/loose)

---

## 8. Export Course to SCORM 1.2 Package with Full Feature Support

**User Goal:**
Author exports course as ZIP for LMS upload. Includes multi-component HTML pages, theme CSS, audio player, completion tracking JS, scoring integration.

**Key APIs:**
- `POST /api/v1/courses/{courseId}/export` — Trigger export, returns ZIP file
- `POST /api/v1/courses/export/validate` — Pre-validate without generating ZIP
- `GET /api/v1/courses/{courseId}/export/status` — Check progress (for large courses)

**Data Models & Services:**
- Input: Full course structure (pages, components, theme, scoring, audio)
- Services: completion_engine, scoring_engine, theme_service, scorm_export
- Output: ZIP with imsmanifest.xml, multi-component pages, theme.css, scorm_wrapper.js

**Step-by-Step Flow:**
1. Validate: `POST /courses/{courseId}/export/validate`
   - All component types exist, `is_active=true`
   - All component data validates against schema
   - All audio IDs reference existing files
   - Scoring config valid (weights sum to 1.0)
2. Generate export: `POST /courses/{courseId}/export`
3. Service generates:
   - **imsmanifest.xml**: SCO structure
   - **course_data.js**: Full course structure JSON
   - **theme.css**: CSS variables from resolved theme
   - **scorm_wrapper.js**: SCORM API bridge + audio player + completion tracking
   - **pages/*.html**: Multi-component HTML per page
   - **media/**: Audio, video, images
4. Response: `{ fileSize, downloadUrl, expiresAt, warning }`

**SCORM Wrapper JS Features:**
- Audio playback on interaction, tracks ≥90% listened
- Completion algorithm client-side (§8.2)
- Score submission + SCORM reporting (per spec §9.4)
- Interaction type mappings: MCQ → `cmi.interactions.N.type: "choice"`, fill-blanks → `"fill-in"`, matching → `"matching"`, etc.

**Edge Cases Covered:**
- **File size limit: 50MB** (error HTTP 413 if exceeded)
- Missing media: Warning returned, placeholder included
- Legacy template format: Auto-converted before export
- No scoring: Export valid, `cmi.core.score` not written
- Multiple audio per interaction: Play in sequence
- SCORM interaction reporting per spec §9.4 (critical)

---

## 9. Preview Mode Interaction Tracking & Real-Time Progress

**User Goal:**
In preview mode (non-SCORM), learner submits answers, completes pages. Backend records interaction events. Author views analytics showing learner progress, per-question performance, time spent.

**Key APIs:**
- `POST /api/v1/courses/{courseId}/interactions` — Record component interaction
- `GET /api/v1/courses/{courseId}/completion` — Get aggregated completion status
- `POST /api/v1/courses/{courseId}/pages/{pageId}/completion` — Explicitly mark page done
- `POST /api/v1/courses/{courseId}/scoring/calculate` — Calculate score

**Data Models:**
- `InteractionEvent`: `{ eventId, courseId, pageId, componentId, interactionType, data, timestamp, completed }`

**DB Tables:**
- In-memory cache (Phase 1) keyed by `courseId:sessionId`
- Interaction_events table (Phase 2) for persistence

**Step-by-Step Flow:**

**Session Management:**
- Session ID in **cookie (sessionId)** or **JWT token** (learner claim)
- Backend validates on each request
- In-memory cache stores events; lost on server restart
- Session lifetime: 24h default, expires on inactivity or explicit end
- Multi-browser tabs: Each tab gets separate session (progress not shared)
- Session recovery: Upon reload, restored from cache if exists

**Event Recording:**
1. Learner clicks tab → `POST /interactions`
2. Backend records event, checks completion criteria
3. Fires `checkPageCompletion()` → `checkCourseCompletion()`
4. Returns updated completion status

**Completion Status Query:**
- `GET /courses/{courseId}/completion` returns aggregated state

**Preview Session End:**
- Explicit: `POST /sessions/{sessionId}/end`
- Automatic: 24h inactivity
- Author can export interaction log (CSV with timestamps, scores, interactions)

**Edge Cases Covered:**
- Out-of-order interactions: Learner skips to page 3, returns to page 1 — both tracked
- Audio completion before finish: Tracked on return
- Stale sessions: Expire after 24h, new session on next load
- Score optional: Component can complete via view alone

---

## 10. Content Author Validates Course JSON Before Upload

**User Goal:**
Author validates course JSON locally. Calls validation endpoint to check schema errors, missing fields, invalid component types. Receives detailed error report.

**Key APIs:** *(Custom extension, not in formal spec §5)*
- `POST /api/v1/courses/validate` — Validate course JSON without creating record
- `POST /api/v1/components/validate` — Validate single component against type schema

**Data Models:**
- Input: Course JSON or component JSON
- Output: `{ valid: boolean, errors: [{type, loc, msg}], warnings: [...] }`

**Step-by-Step Flow:**
1. Author calls `POST /courses/validate` with JSON payload
2. Validator performs two-phase validation:
   - **Phase 1 (Structural)**: Pydantic Course model validation
   - **Phase 2 (Business Rules)**: Component type registry lookup, schema validation, audio/scoring validation
3. Response includes all errors + warnings in single result
4. Author fixes issues, re-validates until `valid: true`
5. Author calls `POST /courses` to create

**Edge Cases Covered:**
- Multiple errors reported at once (not early stop)
- Deep nested error paths provided
- Type mismatch errors with allowed values
- Warnings for missing media but valid course

---

## 11. Admin Migrates Courses from Legacy Format (Templates → Pages+Components)

**User Goal:**
System admin runs data migration to convert existing courses from old `templates[]` format to new `pages[].components[]` structure. Each template becomes one page with one component. Types normalized (video → video-slide, quiz → mcq, etc.).

**Key APIs:**
- `POST /api/v1/admin/migrate/courses` — Trigger migration for all or specific courses
- `GET /api/v1/admin/migrate/status` — Check migration progress
- `POST /api/v1/admin/migrate/rollback` — Rollback to previous state (if needed)

**Data Models:**
- Migration config: `{ courseIds: [], dryRun: boolean }`
- Response: `{ migratedCount, skippedCount, errors: [...] }`

**DB Tables:**
- All tables (courses, templates, pages, components)

**Step-by-Step Flow (per spec §11):**
1. Admin calls `POST /admin/migrate/courses { dryRun: true }` to preview
2. For each course:
   - For each template in course.json_data["templates"]:
     - Create PageRecord: `{ page_id: uuid, course_id, title: template.title, order_index: template.order }`
     - Create ComponentRecord: `{ component_id: uuid, page_id, component_type: normalize(template.type), order_index: 0, data: template.data }`
3. Type normalization (per spec §11.2):
   - `welcome` → `text-with-media`
   - `content-text` → `text-with-media`
   - `content-video` → `video-slide`
   - `mcq` → `mcq` (unchanged)
   - `summary` → `summary` (unchanged)
   - `video` → `video-slide`
   - `quiz` → `mcq`
   - `content-image` → `text-with-media`
   - `interactive` → `click-reveal`
4. If dryRun=false, commit to DB
5. Response: `{ migratedCount: 45, skippedCount: 2, warnings: [{courseId, reason}] }`

**Backward Compatibility:**
- Legacy `templates[]` payloads still accepted by POST /courses (auto-converted in router)
- GET /courses/{id} always returns new `pages[].components[]` format
- No data lost; templates converted on-demand or batch-migrated

**Edge Cases Covered:**
- Courses with no templates: Skipped
- Legacy template with null data: Preserved as-is
- Type not in normalization map: Logged warning, preserved original type
- Duplicate courseId: Deduplicated before migration

---

## 12. Author Reorders Pages and Components Within Course

**User Goal:**
Author changes the sequence of pages in a course, or reorders components within a page. Changes persist immediately and affect completion tracking/SCORM export.

**Key APIs:**
- `POST /api/v1/courses/{courseId}/pages/reorder` — Bulk reorder pages (per spec §5.2)
- `POST /api/v1/courses/{courseId}/pages/{pageId}/components/reorder` — Bulk reorder components in page

**Data Models:**
- Request: `{ order: [{ entityId, newOrder }] }` or ordered list of IDs
- Response: Updated page/component list with new order_index values

**DB Tables:**
- `pages.order_index` — Updated to reflect new sequence
- `components.order_index` — Updated within page

**Step-by-Step Flow:**
1. Author calls `POST /pages/reorder`:
   ```json
   {
     "order": [
       { "pageId": "p-3", "newOrder": 0 },
       { "pageId": "p-1", "newOrder": 1 },
       { "pageId": "p-2", "newOrder": 2 }
     ]
   }
   ```
2. Service validates all pageIds belong to course
3. Service updates `pages.order_index` for each
4. Returns updated pages list with new order
5. Component reorder similar: `POST /pages/{pageId}/components/reorder`

**SCORM Export Impact:**
- Pages render in new order
- imsmanifest.xml reflects new sequence

**Edge Cases Covered:**
- Non-contiguous order values accepted (internally normalized)
- Gaps in order (0, 2, 5) handled gracefully
- Missing pageId in reorder request: Error 400
- Partial reorder (some pages omitted): Only reordered pages changed

---

## 13. Author/Learner Reads Component Details and Navigation

**User Goal:**
Author previews component content before publishing. Learner views course structure and component descriptions. Both need GET endpoints for component, page, and course metadata.

**Key APIs:**
- `GET /api/v1/courses/{courseId}` — Get full course structure
- `GET /api/v1/courses/{courseId}/pages` — List all pages
- `GET /api/v1/courses/{courseId}/pages/{pageId}` — Get page with components
- `GET /api/v1/courses/{courseId}/pages/{pageId}/components/{componentId}` — Get single component
- `GET /api/v1/courses/{courseId}/pages/{pageId}/components` — List page components

**Data Models:**
- Response: Full nested structure (Course → Pages → Components) with all metadata

**DB Tables:**
- All tables (courses, pages, components, component_types, themes)

**Step-by-Step Flow:**
1. Author calls `GET /courses/c-1` → Full course JSON with all pages/components
2. Learner calls `GET /courses/c-1/pages/p-1` → Page with component list (for TOC display)
3. Author calls `GET /courses/c-1/pages/p-1/components/comp-1` → Single component data + schema for editing
4. Service joins: component data + component_type schema + audio config + completion criteria

**Response Example:**
```json
GET /courses/c-1/pages/p-1/components/comp-1
{
  "componentId": "comp-1",
  "componentType": "tabs",
  "order": 0,
  "data": { "tabs": [...] },
  "audioConfig": { "enabled": true, "audioItems": [...] },
  "completionCriteria": { "type": "audio", "requiredAudioIds": [...] },
  "styling": null,
  "createdAt": "2026-02-08T...",
  "updatedAt": "2026-02-08T..."
}
```

**Edge Cases Covered:**
- Component not found: HTTP 404
- Page not found: HTTP 404
- Unauthorized access: HTTP 403 (if user not course author)
- Large courses: Paginate component lists

---

## Summary of Implementation Roadmap

| # | Use Case | Primary APIs | Key Services | DB Tables | Spec Phase | Phase Status |
|---|----------|-------------|-------------|-----------|-----------|------------|
| 1 | Composable Components | POST /courses, /pages, /components | course_validator, page_repo, component_repo | courses, pages, components | **Phase 0-1** | ✅ Spec defined |
| 2 | Per-Component Audio | POST /assets/audio, GET /narration | audio service, component_validator | components.audio_config, media | **Phase 4** | 🟡 Spec defined, impl Phase 4 |
| 3 | Weighted Scoring | PATCH /scoring, POST /scoring/calculate | scoring_engine, component_type_repo | course_scoring, component_types | **Phase 6** | 🟡 Spec defined, impl Phase 6 |
| 4 | Multi-Level Completion | POST /interactions, GET /completion | completion_engine | interaction_events, pages.completion_config | **Phase 5** | 🟡 Spec defined, impl Phase 5 |
| 5 | Theme Customization | POST /themes, PATCH /courses.theme | theme_service, theme_repo | themes, courses.theme_id, pages.theme_overrides | **Phase 3** | 🟡 Spec defined, impl Phase 3 |
| 6 | Component Registry | GET /components* | component_type_repo | component_types | **Phase 0-1** | ✅ Spec defined |
| 7 | Responsive Layouts | POST /pages, PATCH /pages | scorm_export (CSS) | pages.layout_config | **Phase 3** | 🟡 Spec defined, impl Phase 3 |
| 8 | SCORM Export | POST /export | scorm_export, all services | (all tables) | **Phase 7** | 🟡 Spec defined, impl Phase 7 |
| 9 | Preview Mode Interactions | POST /interactions, GET /completion | completion_engine, scoring_engine | session/memory | **Phase 5** | 🟡 Spec defined, impl Phase 5 |
| 10 | JSON Validation | POST /courses/validate | course_validator | component_types | **Custom** | ✅ Backend impl |
| 11 | Data Migration | POST /admin/migrate | migration service | all tables | **Phase 8** | 🟡 Spec defined, impl Phase 8 |
| 12 | Page/Component Reorder | POST /*/reorder | repo layer | pages, components | **Phase 1-2** | 🟡 Spec defined, impl Phase 1-2 |
| 13 | Read Components | GET /courses/*, GET /pages/* | repo layer | all tables | **Phase 1** | ✅ Spec defined |

---

**End of Use Cases Document (Revised)**
