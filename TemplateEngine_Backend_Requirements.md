# Template Engine - Backend Requirements Specification
**Version**: 2.0 | **Date**: February 2026 | **Status**: Final Draft

---

## 1. Executive Summary

This document specifies backend API and data model requirements to support the new Template Engine architecture. The system evolves from 5 fixed template types to a **composable component-based authoring platform** with 100+ component types across 17 categories, per-interaction audio, page completion tracking, weighted scoring, full theming (layout + color system), and SCORM 1.2/2004 export.

### 1.1 Key Architectural Shifts
| From (Current) | To (New) |
|---|---|
| 5 hardcoded template types | 100+ component types via DB-driven registry |
| One `type` + `data` per page | Multiple components per page (`Page → Component[]`) |
| No audio metadata | Per-interaction audio items with completion tracking |
| No completion tracking | Per-component → per-page → per-course completion engine |
| No scoring engine | Weighted scoring with per-quiz-type rules |
| `ThemeType` = 4 string tokens | Full design system: Layout System + Color/Style System |
| `templates[]` flat array | `pages[].components[]` composable hierarchy |
| In-memory page storage | All data persisted to DB |

---

## 2. Current State Analysis

### 2.1 Existing API Endpoints
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/courses` | POST/PATCH | Create/update course |
| `/api/v1/courses/{id}` | GET/DELETE | Retrieve/delete course |
| `/api/v1/courses/{id}/pages` | GET | List pages (IN-MEMORY — not persisted) |
| `/api/v1/courses/{id}/pages/from-template` | POST | Create page from template type |
| `/api/v1/courses/templates/available` | GET | List template types from DB |
| `/api/v1/courses/validate` | POST | Inline validation |
| `/api/v1/courses/{course_id}/templates` | CRUD | Normalized template records |
| `/api/v1/export` | POST | SCORM export from raw JSON |
| `/api/v1/export/scorm/{course_id}` | POST | SCORM export from DB course |
| `/api/v1/export/validate` | POST | Schema validation |
| `/api/v1/media/upload` | POST | Media file upload |
| `/api/v1/media/files/{path}` | GET | Serve media file |
| `/api/v1/templates/enhanced/*` | GET | Enhanced templates (MOCK — hardcoded in-memory data) |
| `/api/v1/health` | GET | Health check |

### 2.2 Current Data Model Limitations
- Templates are flat: one `type` + `data` object per template
- No component composition (multiple components per page)
- No audio/media playback metadata per interaction point
- No completion criteria per template or per component
- No scoring configuration or scoring engine
- Theme stored as string token (`"default"`) but never applied as CSS
- Pages stored in-memory dict (`COURSE_PAGES`), lost on restart
- Enhanced templates router uses 4,245 lines of hardcoded mock data
- Two separate `Base = declarative_base()` instances (migration risk)
- `BUILTIN_TEMPLATE_TYPES` limited to 5: `welcome`, `content-video`, `mcq`, `content-text`, `summary`
- Export router has brittle hardcoded type mappings (`video→content-video`, `quiz→mcq`)

### 2.3 Current DB Tables
| Table | Model | Purpose |
|-------|-------|---------|
| `courses` | `CourseRecord` | Course metadata + `json_data` blob |
| `templates` | `TemplateRecord` | Normalized course templates (FK → courses) |
| `template_definitions` | `TemplateDefinition` | Dynamic SCORM rendering definitions |
| `template_types` | `TemplateType` | Template type catalog for picker UI |
| `import_jobs` | `ImportJob` | SCORM import job tracking |
| `global_templates` | `GlobalTemplate` | Shared templates across courses |

---

## 3. Infrastructure Prerequisites

These must be completed **before** any feature work begins.

### 3.1 Unify ORM Base
**Problem:** `app/models/persisted_course.py` and `app/models/template_type.py` each declare their own `Base = declarative_base()`. This prevents cross-table ForeignKeys and causes Alembic to miss tables.

**Action:** Create `app/models/base.py` with a single shared `Base`. Update all ORM model files to import from it.

```python
# app/models/base.py
from sqlalchemy.orm import declarative_base
Base = declarative_base()
```

### 3.2 Persist Pages to DB
**Problem:** `app/routers/courses.py` stores pages in `COURSE_PAGES = {}` (in-memory dict), lost on restart.

**Action:** Create `PageRecord` ORM model (see §4.2) and replace in-memory dict with DB persistence via `PageRepository`.

### 3.3 Replace Mock Enhanced Templates
**Problem:** `app/routers/enhanced_templates.py` is 4,245 lines of hardcoded mock data with no DB integration.

**Action:** Replace with the Component Type Registry API (§5.1) backed by the `component_types` DB table (§4.4).

### 3.4 Remove Hardcoded Type Mappings
**Problem:** `app/routers/export.py` has brittle manual type remapping (`video→content-video`, `quiz→mcq`, `correct→isCorrect`).

**Action:** Use consistent component type names throughout. Migration script converts legacy data to canonical names.

---

## 4. New Data Models

### 4.1 Component Schema
Each component represents one interactive/content element on a page. Multiple components compose a page.

```json
{
  "componentId": "string (UUID)",
  "componentType": "string (from Component Type Registry)",
  "order": "integer (0-based)",
  "data": "object (type-specific, validated against registry schema — see §6)",
  "audioConfig": {
    "enabled": "boolean",
    "audioItems": [
      {
        "audioId": "string (UUID)",
        "audioUrl": "string (URL to media storage)",
        "triggerOn": "enum (load | click | interaction)",
        "targetInteractionId": "string | null (e.g. 'tab-2', 'accordion-panel-3')",
        "autoplay": "boolean (default false)",
        "requiredForCompletion": "boolean (default false)",
        "duration": "number (seconds, extracted from file metadata)",
        "label": "string | null (display name for narration list)"
      }
    ]
  },
  "completionCriteria": {
    "type": "enum (view | interact | audio | score | custom)",
    "threshold": "number | null (0-100, for score type)",
    "requiredInteractions": "string[] | null (interaction IDs that must be completed)",
    "requiredAudioIds": "string[] | null (audioIds that must be listened to)"
  },
  "styling": {
    "themeOverrides": "ThemeOverrides | null (see §4.5)",
    "layoutPosition": "string | null (grid area name from page layout)"
  }
}
```

**Key design notes:**
- `audioConfig.audioItems[]` is an **array** — each tab, accordion panel, hotspot, etc. can have its own audio file(s)
- `triggerOn: "interaction"` + `targetInteractionId: "tab-2"` means audio plays when user clicks the 2nd tab
- `completionCriteria.requiredAudioIds` lists which audio items must be listened to for completion
- `data` is validated against the JSON Schema stored in the Component Type Registry for the given `componentType`

### 4.2 Page Schema
Each page is a container of components with its own completion rules, layout, and theme.

```json
{
  "pageId": "string (UUID)",
  "title": "string (max 200)",
  "order": "integer (0-based, sequential)",
  "components": "Component[] (see §4.1)",
  "pageCompletion": {
    "enabled": "boolean (default true)",
    "strategy": "enum (all | any | percentage | custom)",
    "requiredComponents": "string[] | null (componentIds, used with 'custom' strategy)",
    "completionThreshold": "number (0-100, used with 'percentage' strategy)"
  },
  "layout": {
    "preset": "enum (single-column | two-column | three-column | sidebar-left | sidebar-right | grid-2x2 | hero-content | full-width) | null",
    "customGrid": {
      "columns": "integer (1-4)",
      "rows": "string (CSS grid-template-rows, e.g. 'auto 1fr auto')",
      "areas": "string[][] (CSS grid-template-areas, e.g. [['header','header'],['sidebar','main']])",
      "gap": "string (CSS gap, e.g. '16px')"
    },
    "spacing": "enum (compact | normal | spacious)",
    "componentPlacements": [
      {
        "componentId": "string",
        "gridArea": "string (area name from customGrid.areas)",
        "span": "integer | null (column span for preset layouts)"
      }
    ]
  },
  "theme": {
    "inheritCourse": "boolean (default true)",
    "overrides": "ThemeOverrides | null (see §4.5)"
  }
}
```

**Page Completion Algorithm** (see §8 for full logic):
| Strategy | Rule |
|----------|------|
| `all` | Every component with `completionCriteria` must be completed |
| `any` | At least one component must be completed |
| `percentage` | ≥ `completionThreshold`% of components completed |
| `custom` | Only components listed in `requiredComponents` must be completed |

### 4.3 Course Schema (Updated Root)
The `Course` root model changes from `templates[]` to `pages[].components[]`.

```json
{
  "courseId": "string (UUID or slug, regex ^[a-zA-Z0-9_-]+$)",
  "title": "string (max 200)",
  "author": "string (max 100)",
  "language": "string (ISO 639-1)",
  "description": "string | null (max 1000)",
  "version": "string (semver)",
  "pages": "Page[] (see §4.2, replaces templates[])",
  "assets": "Asset[]",
  "navigation": {
    "allowSkip": "boolean",
    "showProgress": "boolean",
    "linearProgression": "boolean"
  },
  "settings": {
    "themeId": "string | null (FK to themes table)",
    "autoplay": "boolean",
    "duration": "number | null (estimated minutes)"
  },
  "scoring": "ScoringConfig | null (see §4.7)",
  "createdAt": "datetime",
  "updatedAt": "datetime"
}
```

**Backward compatibility:** When the API receives old-format `templates[]` without `pages[]`, auto-convert each template to a page with one component (see §11).

### 4.4 Component Type Registry Schema
Stored in DB table `component_types`. Each row defines one component type with its validation schema, capabilities, and defaults.

```json
{
  "typeId": "string (unique slug, e.g. 'tabs', 'mcq', 'accordion')",
  "category": "string (from category enum — see §6)",
  "displayName": "string (human-readable, e.g. 'Tabbed Content')",
  "description": "string (what this component does)",
  "icon": "string (icon name or URL)",
  "thumbnail": "string | null (preview image URL)",
  "schema": "JSONSchema (validates the component's 'data' field — see §6)",
  "defaultData": "object (starter data when component is added to a page)",
  "completionCapabilities": ["view", "interact", "audio", "score"],
  "defaultCompletionType": "string (one of completionCapabilities)",
  "scoringEnabled": "boolean",
  "maxScore": "number | null (max possible score for scoring-enabled types)",
  "scoringRules": "ScoringRuleSet | null (see §9.2)",
  "audioSupport": {
    "perComponent": "boolean (can have component-level audio)",
    "perInteraction": "boolean (can have audio per tab/panel/item)",
    "interactionPoints": "string[] | null (e.g. ['tab', 'panel', 'hotspot'])"
  },
  "tags": "string[] (searchable tags)",
  "estimatedDuration": "number | null (minutes)",
  "isActive": "boolean (soft disable)",
  "sortOrder": "integer (display order within category)",
  "createdAt": "datetime",
  "updatedAt": "datetime"
}
```

### 4.5 Design System — Layout + Theme (Separated)

The design system has **two distinct parts**:

#### 4.5.1 Layout System
Controls **where** components are placed on the page. Stored as part of `Page.layout`.

```json
{
  "preset": "enum | null (see §4.2 presets)",
  "customGrid": "GridDefinition | null",
  "spacing": "enum (compact | normal | spacious)",
  "componentPlacements": "ComponentPlacement[]"
}
```

Layout presets define CSS grid structures:
| Preset | Grid | Description |
|--------|------|-------------|
| `single-column` | 1 column, N rows | Default, components stacked vertically |
| `two-column` | 2 equal columns | Side-by-side components |
| `three-column` | 3 equal columns | Three-way split |
| `sidebar-left` | 1fr 3fr | Narrow left, wide right |
| `sidebar-right` | 3fr 1fr | Wide left, narrow right |
| `grid-2x2` | 2×2 grid | Four quadrants |
| `hero-content` | Full-width hero + content below | Media hero with content |
| `full-width` | 1 column, no max-width | Edge-to-edge |

#### 4.5.2 Color/Style System (Theme)
Controls **how** everything looks — colors, fonts, component styling. Stored in `themes` table, applied at course or page level with cascading overrides.

```json
{
  "themeId": "string (UUID)",
  "name": "string (e.g. 'Corporate Blue', 'Dark Mode')",
  "isPreset": "boolean (built-in vs user-created)",
  "colors": {
    "primary": "string (#hex)",
    "secondary": "string (#hex)",
    "background": "string (#hex)",
    "surface": "string (#hex)",
    "text": "string (#hex)",
    "textSecondary": "string (#hex)",
    "accent": "string (#hex)",
    "error": "string (#hex)",
    "success": "string (#hex)",
    "warning": "string (#hex)",
    "info": "string (#hex)",
    "border": "string (#hex)"
  },
  "typography": {
    "fontFamily": "string (e.g. 'Inter, sans-serif')",
    "headingFont": "string | null (separate font for headings)",
    "baseFontSize": "number (px, e.g. 16)",
    "headingSizes": {
      "h1": "number (px, e.g. 32)",
      "h2": "number (px, e.g. 24)",
      "h3": "number (px, e.g. 20)",
      "h4": "number (px, e.g. 18)"
    },
    "lineHeight": "number (e.g. 1.6)",
    "fontWeight": {
      "normal": "number (e.g. 400)",
      "medium": "number (e.g. 500)",
      "bold": "number (e.g. 700)"
    }
  },
  "componentStyles": {
    "button": {
      "borderRadius": "number (px)",
      "padding": "string (CSS padding)",
      "fontWeight": "number",
      "textTransform": "enum (none | uppercase | capitalize)"
    },
    "card": {
      "borderRadius": "number (px)",
      "shadow": "string (CSS box-shadow)",
      "borderWidth": "number (px)",
      "padding": "string"
    },
    "tabs": {
      "style": "enum (underline | pill | boxed)",
      "activeColor": "string (#hex) | null",
      "borderRadius": "number | null"
    },
    "accordion": {
      "style": "enum (bordered | minimal | card)",
      "iconPosition": "enum (left | right)",
      "spacing": "number (px)"
    },
    "input": {
      "borderRadius": "number (px)",
      "borderColor": "string (#hex)",
      "focusColor": "string (#hex)"
    },
    "progressBar": {
      "height": "number (px)",
      "borderRadius": "number (px)",
      "fillColor": "string (#hex) | null"
    }
  },
  "createdAt": "datetime",
  "updatedAt": "datetime"
}
```

**Theme Override (partial):** At page or component level, any subset of theme properties can be overridden:
```json
{
  "colors": { "primary": "#FF5722" },
  "typography": { "baseFontSize": 18 },
  "componentStyles": { "button": { "borderRadius": 24 } }
}
```

**Theme Inheritance Chain:** Course Theme → Page Theme Override → Component Styling Override.
The backend CSS generation service merges these layers during SCORM export.

### 4.6 Audio Item Schema
Audio items are embedded within `Component.audioConfig.audioItems[]`. Audio files themselves are managed via the existing media upload system (`/api/v1/media/upload`).

```json
{
  "audioId": "string (UUID)",
  "audioUrl": "string (URL, from media upload response)",
  "triggerOn": "enum (load | click | interaction)",
  "targetInteractionId": "string | null",
  "autoplay": "boolean (default false)",
  "requiredForCompletion": "boolean (default false)",
  "duration": "number (seconds, auto-extracted or manually set)",
  "label": "string | null (display name, e.g. 'Tab 1 Narration')",
  "transcript": "string | null (for accessibility)"
}
```

**Trigger behaviors:**
| `triggerOn` | `targetInteractionId` | Behavior |
|-------------|----------------------|----------|
| `load` | null | Audio plays when component renders |
| `click` | null | Audio plays when user clicks a play button on the component |
| `interaction` | `"tab-2"` | Audio plays when user clicks Tab 2 |
| `interaction` | `"accordion-panel-1"` | Audio plays when user opens Accordion Panel 1 |
| `interaction` | `"hotspot-3"` | Audio plays when user clicks Hotspot 3 |

### 4.7 Scoring Schema
```json
{
  "scoringId": "string (UUID)",
  "courseId": "string",
  "config": {
    "passingScore": "number (0-100, percentage)",
    "maxAttempts": "number | null (null = unlimited)",
    "attemptScoring": "enum (best | last | average)",
    "showCorrectAnswers": "boolean",
    "showScoreAfterQuestion": "boolean",
    "showScoreAfterPage": "boolean",
    "weightedScoring": "boolean (if false, all scorable components weighted equally)",
    "allowPartialCredit": "boolean (default true)"
  },
  "componentScores": [
    {
      "componentId": "string (UUID)",
      "componentType": "string (for validation — must be a scoringEnabled type)",
      "weight": "number (0-1, sum of all weights must equal 1.0 when weightedScoring=true)",
      "maxPoints": "number (max raw score for this component)"
    }
  ],
  "scormReporting": {
    "enabled": "boolean",
    "version": "enum (1.2 | 2004)",
    "reportScore": "boolean (set cmi.core.score)",
    "reportCompletion": "boolean (set cmi.core.lesson_status)",
    "reportInteractions": "boolean (set cmi.interactions for each question)",
    "objectives": [
      {
        "objectiveId": "string",
        "componentIds": "string[] (components that contribute to this objective)",
        "description": "string",
        "passingScore": "number (0-100)"
      }
    ]
  }
}
```

### 4.8 Interaction Event Schema
When an interaction is recorded (if the backend tracks learner progress — see §8.3):

```json
{
  "eventId": "string (UUID, server-generated)",
  "courseId": "string",
  "pageId": "string",
  "componentId": "string",
  "interactionType": "enum (view | click | submit | audio-play | audio-complete | drag-drop | select | input | navigation)",
  "data": {
    "interactionId": "string | null (e.g. 'tab-2')",
    "value": "any (response value, e.g. selected option ID)",
    "score": "number | null (raw score if scorable)",
    "maxScore": "number | null",
    "isCorrect": "boolean | null",
    "duration": "number | null (seconds spent)"
  },
  "timestamp": "datetime (ISO 8601)",
  "completed": "boolean (did this interaction satisfy a completion criterion)"
}
```

**Note:** For SCORM-exported courses, interaction tracking happens **client-side** via the SCORM wrapper JS writing to `cmi.interactions` and `cmi.suspend_data`. The backend endpoints in §5.4 are for **preview mode** and non-SCORM deployments. The backend must generate the SCORM wrapper JS that implements this tracking client-side.

---

## 5. API Endpoints

### 5.1 Component Registry API

| Endpoint | Method | Purpose | Response |
|----------|--------|---------|----------|
| `/api/v1/components` | GET | List all component types | `ComponentTypeList` |
| `/api/v1/components/{typeId}` | GET | Get single component type definition | `ComponentType` |
| `/api/v1/components/categories` | GET | List all categories with counts | `CategoryList` |
| `/api/v1/components/categories/{categoryId}` | GET | List types in a category | `ComponentTypeList` |
| `/api/v1/components/search` | GET | Search types by query, tags, category | `ComponentTypeList` |

**Query parameters for `GET /components`:**
- `category` (string, optional) — filter by category
- `scoringEnabled` (boolean, optional) — filter scorable types
- `isActive` (boolean, optional, default true) — include disabled types
- `page` (integer, default 1), `limit` (integer, default 50)

**Response: `ComponentTypeList`**
```json
{
  "items": [
    {
      "typeId": "tabs",
      "category": "content-presentation",
      "displayName": "Tabbed Content",
      "description": "Content organized in switchable tabs",
      "icon": "tabs-icon",
      "thumbnail": "https://...",
      "completionCapabilities": ["view", "interact", "audio"],
      "scoringEnabled": false,
      "audioSupport": { "perComponent": true, "perInteraction": true, "interactionPoints": ["tab"] },
      "tags": ["content", "interactive", "organization"],
      "estimatedDuration": 5
    }
  ],
  "total": 102,
  "page": 1,
  "limit": 50
}
```

**Response: `CategoryList`**
```json
{
  "categories": [
    {
      "categoryId": "content-presentation",
      "displayName": "Content Presentation",
      "description": "Templates for presenting content (tabs, accordions, timelines)",
      "icon": "layout-icon",
      "componentCount": 7,
      "sortOrder": 1
    }
  ]
}
```

### 5.2 Page & Component CRUD API

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/courses/{courseId}/pages` | GET | List all pages (ordered) |
| `/api/v1/courses/{courseId}/pages` | POST | Create page (with optional components) |
| `/api/v1/courses/{courseId}/pages/{pageId}` | GET | Get page with components |
| `/api/v1/courses/{courseId}/pages/{pageId}` | PATCH | Update page metadata/layout/theme |
| `/api/v1/courses/{courseId}/pages/{pageId}` | DELETE | Delete page and its components |
| `/api/v1/courses/{courseId}/pages/reorder` | POST | Reorder pages |
| `/api/v1/courses/{courseId}/pages/{pageId}/components` | GET | List page components |
| `/api/v1/courses/{courseId}/pages/{pageId}/components` | POST | Add component to page |
| `/api/v1/courses/{courseId}/pages/{pageId}/components/{componentId}` | GET | Get single component |
| `/api/v1/courses/{courseId}/pages/{pageId}/components/{componentId}` | PATCH | Update component |
| `/api/v1/courses/{courseId}/pages/{pageId}/components/{componentId}` | DELETE | Remove component |
| `/api/v1/courses/{courseId}/pages/{pageId}/components/reorder` | POST | Reorder components |

**Request: `POST /pages/{pageId}/components`**
```json
{
  "componentType": "tabs",
  "data": {
    "tabs": [
      { "id": "tab-1", "label": "Overview", "content": "<p>Content here</p>" },
      { "id": "tab-2", "label": "Details", "content": "<p>More content</p>" }
    ]
  },
  "audioConfig": {
    "enabled": true,
    "audioItems": [
      {
        "audioUrl": "/media/files/course-1/audio/tab1-narration.mp3",
        "triggerOn": "interaction",
        "targetInteractionId": "tab-1",
        "requiredForCompletion": true,
        "duration": 45,
        "label": "Overview Narration"
      }
    ]
  },
  "completionCriteria": {
    "type": "audio",
    "requiredAudioIds": ["auto-generated-after-creation"]
  }
}
```

**Response: Created Component**
```json
{
  "componentId": "uuid-generated",
  "componentType": "tabs",
  "order": 0,
  "data": { "..." },
  "audioConfig": { "..." },
  "completionCriteria": { "..." },
  "styling": null,
  "createdAt": "2026-02-08T10:00:00Z",
  "updatedAt": "2026-02-08T10:00:00Z"
}
```

### 5.3 Theme API

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/themes` | GET | List all themes (presets + custom) |
| `/api/v1/themes` | POST | Create custom theme |
| `/api/v1/themes/{themeId}` | GET | Get theme details |
| `/api/v1/themes/{themeId}` | PATCH | Update custom theme |
| `/api/v1/themes/{themeId}` | DELETE | Delete custom theme (presets cannot be deleted) |
| `/api/v1/themes/presets` | GET | List built-in preset themes |
| `/api/v1/courses/{courseId}/theme` | GET | Get resolved course theme |
| `/api/v1/courses/{courseId}/theme` | PATCH | Set course theme / overrides |
| `/api/v1/courses/{courseId}/pages/{pageId}/theme` | GET | Get resolved page theme (with inheritance) |
| `/api/v1/courses/{courseId}/pages/{pageId}/theme` | PATCH | Set page theme overrides |

**Response: `GET /courses/{courseId}/pages/{pageId}/theme`** (resolved with inheritance):
```json
{
  "resolved": {
    "colors": { "primary": "#1976D2", "secondary": "#FF9800", "...": "..." },
    "typography": { "fontFamily": "Inter, sans-serif", "baseFontSize": 16, "...": "..." },
    "componentStyles": { "button": { "borderRadius": 8 }, "...": "..." }
  },
  "inheritedFrom": "course",
  "overrides": { "colors": { "primary": "#FF5722" } },
  "courseThemeId": "uuid",
  "courseThemeName": "Corporate Blue"
}
```

### 5.4 Scoring & Completion API

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/courses/{courseId}/scoring` | GET | Get scoring configuration |
| `/api/v1/courses/{courseId}/scoring` | PATCH | Update scoring configuration |
| `/api/v1/courses/{courseId}/scoring/validate` | POST | Validate scoring config (weights sum to 1.0, etc.) |
| `/api/v1/courses/{courseId}/scoring/calculate` | POST | Calculate score from submitted answers |
| `/api/v1/courses/{courseId}/completion` | GET | Get course completion status |
| `/api/v1/courses/{courseId}/pages/{pageId}/completion` | GET | Get page completion status |
| `/api/v1/courses/{courseId}/pages/{pageId}/completion` | POST | Record page completion event |
| `/api/v1/courses/{courseId}/interactions` | POST | Record component interaction event |

**Request: `POST /scoring/calculate`**
```json
{
  "answers": [
    {
      "componentId": "uuid",
      "componentType": "mcq",
      "responses": [
        { "questionId": "q1", "selectedOptionIds": ["opt-b"] },
        { "questionId": "q2", "selectedOptionIds": ["opt-a", "opt-c"] }
      ]
    }
  ],
  "attemptNumber": 1
}
```

**Response: Score Calculation**
```json
{
  "totalScore": 75.0,
  "maxScore": 100.0,
  "percentage": 75.0,
  "passed": true,
  "passingScore": 70.0,
  "componentResults": [
    {
      "componentId": "uuid",
      "componentType": "mcq",
      "score": 15.0,
      "maxScore": 20.0,
      "weight": 0.5,
      "weightedScore": 37.5,
      "questionResults": [
        { "questionId": "q1", "correct": true, "score": 10, "maxScore": 10 },
        { "questionId": "q2", "correct": false, "score": 5, "maxScore": 10, "partialCredit": true }
      ]
    }
  ],
  "attemptNumber": 1,
  "remainingAttempts": 2
}
```

**Response: `GET /completion`**
```json
{
  "courseId": "uuid",
  "status": "in-progress",
  "overallProgress": 60.0,
  "pages": [
    {
      "pageId": "uuid",
      "title": "Introduction",
      "completed": true,
      "strategy": "all",
      "components": [
        { "componentId": "uuid", "completed": true, "completionType": "view" },
        { "componentId": "uuid", "completed": true, "completionType": "audio", "audioProgress": { "listened": 3, "required": 3 } }
      ]
    },
    {
      "pageId": "uuid",
      "title": "Assessment",
      "completed": false,
      "strategy": "all",
      "components": [
        { "componentId": "uuid", "completed": false, "completionType": "score", "threshold": 70 }
      ]
    }
  ]
}
```

### 5.5 Audio Management API

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/assets/audio` | POST | Upload audio file (extends existing `/media/upload`) |
| `/api/v1/assets/audio/{audioId}` | GET | Get audio file metadata |
| `/api/v1/assets/audio/{audioId}` | PATCH | Update audio metadata (label, transcript) |
| `/api/v1/assets/audio/{audioId}` | DELETE | Delete audio file |
| `/api/v1/courses/{courseId}/narration` | GET | List all audio items across all pages/components |

**Response: `GET /courses/{courseId}/narration`**
```json
{
  "courseId": "uuid",
  "totalAudioItems": 12,
  "totalDuration": 845,
  "pages": [
    {
      "pageId": "uuid",
      "pageTitle": "Introduction",
      "audioItems": [
        {
          "audioId": "uuid",
          "componentId": "uuid",
          "componentType": "tabs",
          "targetInteractionId": "tab-1",
          "label": "Tab 1 Narration",
          "audioUrl": "/media/files/...",
          "duration": 45,
          "requiredForCompletion": true
        }
      ]
    }
  ]
}
```

### 5.6 Existing Endpoint Changes

| Endpoint | Change |
|----------|--------|
| `POST /courses` | Accept both legacy `templates[]` and new `pages[].components[]` format |
| `PATCH /courses/{id}` | Accept `pages[]` updates; `settings.themeId` replaces `settings.theme` string |
| `GET /courses/{id}` | Response includes `pages[].components[]` structure |
| `POST /export` | Handle component-based courses; multi-component page rendering |
| `POST /export/scorm/{id}` | Remove hardcoded type mappings; use component registry |
| `POST /export/validate` | Validate component types, audio refs, scoring config |
| `POST /courses/validate` | Schema-driven validation via Component Type Registry instead of hardcoded rules |

---

## 6. Component Type Catalog

### 6.1 Category Definitions

| # | Category ID | Display Name | Description | Component Count |
|---|-------------|-------------|-------------|-----------------|
| 1 | `content-presentation` | Content Presentation | Display content with interactive layouts | 7 |
| 2 | `process-flow` | Process & Flow | Visualize processes, sequences, decisions | 5 |
| 3 | `interaction` | Interaction | User-driven interactive elements | 5 |
| 4 | `scenario` | Scenario-Based | Real-world scenario learning | 4 |
| 5 | `assessment` | Assessment | Graded evaluation components | 8 |
| 6 | `comparison` | Comparison & Analysis | Compare, contrast, analyze | 4 |
| 7 | `media-rich` | Media-Rich | Video, audio, animation-based | 4 |
| 8 | `microlearning` | Microlearning | Bite-sized learning chunks | 3 |
| 9 | `navigation` | Navigation & Structural | Course structure and navigation | 5 |
| 10 | `gamification` | Gamification | Game mechanics for engagement | 4 |
| 11 | `compliance` | Compliance & Corporate | Regulatory and policy content | 5 |
| 12 | `diagnostic` | Diagnostic & Adaptive | Personalized learning paths | 5 |
| 13 | `practice` | Practice & Simulation | Hands-on practice without scoring pressure | 5 |
| 14 | `feedback` | Feedback & Reflection | Self-assessment and reflection | 5 |
| 15 | `social` | Social & Collaborative | Multi-user interaction and collaboration | 5 |
| 16 | `accessibility` | Accessibility & Support | Compliance and accessibility aids | 5 |
| 17 | `analytics` | Analytics & Learning Insight | Progress tracking and reporting | 5 |

### 6.2 Complete Component Type Registry

#### Content Presentation (`content-presentation`)
| typeId | Display Name | Scoring | Completion | Audio Per-Interaction | Interaction Points |
|--------|-------------|---------|------------|----------------------|-------------------|
| `tabs` | Tabbed Content | No | view, interact, audio | Yes | tab |
| `accordion` | Accordion | No | view, interact, audio | Yes | panel |
| `click-reveal` | Click and Reveal | No | interact | Yes | reveal-item |
| `timeline` | Timeline | No | view, interact | Yes | event |
| `image-hotspots` | Image Hotspots | No | interact | Yes | hotspot |
| `layered-content` | Layered Content | No | interact | Yes | layer |
| `text-with-media` | Text with Media | No | view, audio | No | — |

#### Process & Flow (`process-flow`)
| typeId | Display Name | Scoring | Completion | Audio Per-Interaction | Interaction Points |
|--------|-------------|---------|------------|----------------------|-------------------|
| `step-by-step` | Step-by-Step Process | No | interact | Yes | step |
| `cycle-diagram` | Cycle Diagram | No | view, interact | Yes | stage |
| `flowchart` | Flowchart | No | view | No | — |
| `process-map` | Process Map | No | view, interact | Yes | node |
| `decision-tree` | Decision Tree | No | interact | Yes | decision |

#### Interaction (`interaction`)
| typeId | Display Name | Scoring | Completion | Audio Per-Interaction | Interaction Points |
|--------|-------------|---------|------------|----------------------|-------------------|
| `drag-drop` | Drag and Drop | Optional | interact, score | No | — |
| `flip-cards` | Flip Cards | No | interact | Yes | card |
| `slider` | Slider | No | interact | No | — |
| `carousel` | Carousel | No | view, interact | Yes | slide |
| `clickable-icons` | Clickable Icons | No | interact | Yes | icon |

#### Scenario-Based (`scenario`)
| typeId | Display Name | Scoring | Completion | Audio Per-Interaction | Interaction Points |
|--------|-------------|---------|------------|----------------------|-------------------|
| `scenario` | Scenario | Optional | interact, score | Yes | choice |
| `branching-scenario` | Branching Scenario | Optional | interact, score | Yes | branch |
| `role-play` | Role-Play Simulation | Optional | interact | Yes | dialogue |
| `case-study` | Case Study | No | view, interact | No | — |

#### Assessment (`assessment`)
| typeId | Display Name | Scoring | Completion | Audio Per-Interaction | Interaction Points |
|--------|-------------|---------|------------|----------------------|-------------------|
| `mcq` | Multiple Choice | Yes | score | No | — |
| `multi-select` | Multiple Select | Yes | score | No | — |
| `true-false` | True / False | Yes | score | No | — |
| `fill-blanks` | Fill in the Blanks | Yes | score | No | — |
| `matching` | Matching | Yes | score | No | — |
| `scenario-question` | Scenario-Based Question | Yes | score | Yes | scenario-step |
| `knowledge-check` | Knowledge Check | Yes | score | No | — |
| `final-assessment` | Final Assessment | Yes | score | No | — |

#### Comparison & Analysis (`comparison`)
| typeId | Display Name | Scoring | Completion | Audio Per-Interaction | Interaction Points |
|--------|-------------|---------|------------|----------------------|-------------------|
| `comparison-table` | Comparison Table | No | view | No | — |
| `pros-cons` | Pros and Cons | No | view | No | — |
| `before-after` | Before and After | No | view, interact | No | — |
| `matrix-grid` | Matrix / Grid | No | view | No | — |

#### Media-Rich (`media-rich`)
| typeId | Display Name | Scoring | Completion | Audio Per-Interaction | Interaction Points |
|--------|-------------|---------|------------|----------------------|-------------------|
| `video-slide` | Video-Based Slide | No | view, audio | No | — |
| `audio-slide` | Audio-Based Slide | No | audio | No | — |
| `animated-explainer` | Animated Explainer | No | view | No | — |
| `infographic` | Infographic | No | view | No | — |

#### Microlearning (`microlearning`)
| typeId | Display Name | Scoring | Completion | Audio Per-Interaction | Interaction Points |
|--------|-------------|---------|------------|----------------------|-------------------|
| `microlearning-cards` | Microlearning Cards | No | view, interact | Yes | card |
| `flashcards` | Flashcards | No | interact | Yes | card |
| `quick-tips` | Quick Tips | No | view | No | — |

#### Navigation & Structural (`navigation`)
| typeId | Display Name | Scoring | Completion | Audio Per-Interaction | Interaction Points |
|--------|-------------|---------|------------|----------------------|-------------------|
| `course-menu` | Course Menu | No | — | No | — |
| `learning-roadmap` | Learning Roadmap | No | view | No | — |
| `module-overview` | Module Overview | No | view | No | — |
| `summary` | Summary / Key Takeaways | No | view | No | — |
| `resources-downloads` | Resources & Downloads | No | view | No | — |

#### Gamification (`gamification`)
| typeId | Display Name | Scoring | Completion | Audio Per-Interaction | Interaction Points |
|--------|-------------|---------|------------|----------------------|-------------------|
| `quiz-game` | Quiz Game | Yes | score | No | — |
| `points-badges` | Points and Badges | No | — | No | — |
| `progress-tracker` | Progress Tracker | No | — | No | — |
| `level-learning` | Level-Based Learning | Optional | interact, score | No | — |

#### Compliance & Corporate (`compliance`)
| typeId | Display Name | Scoring | Completion | Audio Per-Interaction | Interaction Points |
|--------|-------------|---------|------------|----------------------|-------------------|
| `policy-acknowledgement` | Policy Acknowledgement | No | interact | No | — |
| `dos-donts` | Do's and Don'ts | No | view | No | — |
| `code-of-conduct` | Code of Conduct | No | view, interact | No | — |
| `regulatory-scenario` | Regulatory Scenario | Optional | interact, score | Yes | scenario-step |
| `audit-checklist` | Audit Checklist | No | interact | No | — |

#### Diagnostic & Adaptive (`diagnostic`)
| typeId | Display Name | Scoring | Completion | Audio Per-Interaction | Interaction Points |
|--------|-------------|---------|------------|----------------------|-------------------|
| `pre-assessment` | Pre-Assessment | Yes | score | No | — |
| `diagnostic-quiz` | Diagnostic Quiz | Yes | score | No | — |
| `skill-gap-analysis` | Skill Gap Analysis | No | interact | No | — |
| `adaptive-path` | Adaptive Learning Path | No | interact | No | — |
| `recommendation-card` | Recommendation Card | No | view | No | — |

#### Practice & Simulation (`practice`)
| typeId | Display Name | Scoring | Completion | Audio Per-Interaction | Interaction Points |
|--------|-------------|---------|------------|----------------------|-------------------|
| `guided-practice` | Guided Practice | No | interact | Yes | step |
| `try-it-simulation` | Try-It Simulation | No | interact | No | — |
| `software-simulation` | Software Simulation | No | interact | No | — |
| `sandbox-practice` | Sandbox Practice | No | interact | No | — |
| `error-identification` | Error Identification | Optional | interact, score | No | — |

#### Feedback & Reflection (`feedback`)
| typeId | Display Name | Scoring | Completion | Audio Per-Interaction | Interaction Points |
|--------|-------------|---------|------------|----------------------|-------------------|
| `reflective-question` | Reflective Question | No | interact | No | — |
| `learner-journal` | Learner Journal | No | interact | No | — |
| `self-assessment` | Self-Assessment | No | interact | No | — |
| `confidence-rating` | Confidence Rating | No | interact | No | — |
| `action-planning` | Action Planning | No | interact | No | — |

#### Social & Collaborative (`social`)
| typeId | Display Name | Scoring | Completion | Audio Per-Interaction | Interaction Points |
|--------|-------------|---------|------------|----------------------|-------------------|
| `discussion-prompt` | Discussion Prompt | No | interact | No | — |
| `peer-review` | Peer Review | No | interact | No | — |
| `poll-vote` | Poll / Vote | No | interact | No | — |
| `team-challenge` | Team Challenge | Optional | interact | No | — |
| `scenario-debate` | Scenario Debate | No | interact | No | — |

#### Accessibility & Support (`accessibility`)
| typeId | Display Name | Scoring | Completion | Audio Per-Interaction | Interaction Points |
|--------|-------------|---------|------------|----------------------|-------------------|
| `accessibility-tip` | Accessibility Tip Card | No | view | No | — |
| `keyboard-nav-guide` | Keyboard Navigation Guide | No | view | No | — |
| `screen-reader-guide` | Screen Reader Guide | No | view, audio | No | — |
| `language-selector` | Language Selector | No | — | No | — |
| `transcript-page` | Transcript / Caption Page | No | view | No | — |

#### Analytics & Learning Insight (`analytics`)
| typeId | Display Name | Scoring | Completion | Audio Per-Interaction | Interaction Points |
|--------|-------------|---------|------------|----------------------|-------------------|
| `progress-summary` | Learning Progress Summary | No | — | No | — |
| `performance-dashboard` | Performance Dashboard | No | — | No | — |
| `skill-mastery-report` | Skill Mastery Report | No | — | No | — |
| `completion-certificate` | Completion Certificate | No | — | No | — |
| `manager-review` | Manager Review Page | No | — | No | — |

**Total: 89 component types across 17 categories.**

### 6.3 Per-Component Data Schemas (Key Examples)

Each component type's `data` field is validated against its JSON Schema stored in the Component Type Registry. Below are schemas for the most common/complex types.

#### `tabs` (Tabbed Content)
```json
{
  "type": "object",
  "required": ["tabs"],
  "properties": {
    "tabs": {
      "type": "array",
      "minItems": 2,
      "maxItems": 10,
      "items": {
        "type": "object",
        "required": ["id", "label", "content"],
        "properties": {
          "id": { "type": "string", "description": "Used as targetInteractionId for audio" },
          "label": { "type": "string", "maxLength": 100 },
          "content": { "type": "string", "description": "HTML content" },
          "icon": { "type": "string" },
          "mediaUrl": { "type": "string", "format": "uri" }
        }
      }
    },
    "defaultTab": { "type": "integer", "default": 0 },
    "tabStyle": { "type": "string", "enum": ["horizontal", "vertical", "pills"] }
  }
}
```

#### `accordion` (Accordion)
```json
{
  "type": "object",
  "required": ["panels"],
  "properties": {
    "panels": {
      "type": "array",
      "minItems": 1,
      "maxItems": 20,
      "items": {
        "type": "object",
        "required": ["id", "title", "content"],
        "properties": {
          "id": { "type": "string" },
          "title": { "type": "string", "maxLength": 200 },
          "content": { "type": "string" },
          "icon": { "type": "string" },
          "defaultOpen": { "type": "boolean", "default": false }
        }
      }
    },
    "allowMultiOpen": { "type": "boolean", "default": false }
  }
}
```

#### `mcq` (Multiple Choice Question)
```json
{
  "type": "object",
  "required": ["questions"],
  "properties": {
    "instructions": { "type": "string" },
    "questions": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["id", "question", "options"],
        "properties": {
          "id": { "type": "string" },
          "question": { "type": "string", "minLength": 1 },
          "options": {
            "type": "array",
            "minItems": 2,
            "maxItems": 6,
            "items": {
              "type": "object",
              "required": ["id", "text", "isCorrect"],
              "properties": {
                "id": { "type": "string" },
                "text": { "type": "string", "minLength": 1 },
                "isCorrect": { "type": "boolean" }
              }
            }
          },
          "feedback": {
            "type": "object",
            "properties": {
              "correct": { "type": "string" },
              "incorrect": { "type": "string" }
            }
          },
          "points": { "type": "number", "default": 10 }
        }
      }
    },
    "randomizeQuestions": { "type": "boolean", "default": false },
    "randomizeOptions": { "type": "boolean", "default": false },
    "showFeedback": { "type": "boolean", "default": true }
  }
}
```

#### `multi-select` (Multiple Select)
```json
{
  "type": "object",
  "required": ["questions"],
  "properties": {
    "questions": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["id", "question", "options"],
        "properties": {
          "id": { "type": "string" },
          "question": { "type": "string" },
          "options": {
            "type": "array",
            "minItems": 2,
            "items": {
              "type": "object",
              "required": ["id", "text", "isCorrect"],
              "properties": {
                "id": { "type": "string" },
                "text": { "type": "string" },
                "isCorrect": { "type": "boolean" }
              }
            }
          },
          "minSelections": { "type": "integer", "default": 1 },
          "maxSelections": { "type": "integer" },
          "feedback": { "type": "object" },
          "points": { "type": "number", "default": 10 },
          "partialCreditMode": { "type": "string", "enum": ["proportional", "all-or-nothing"], "default": "proportional" }
        }
      }
    }
  }
}
```

#### `fill-blanks` (Fill in the Blanks)
```json
{
  "type": "object",
  "required": ["questions"],
  "properties": {
    "questions": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["id", "text", "blanks"],
        "properties": {
          "id": { "type": "string" },
          "text": { "type": "string", "description": "Text with {{blank_id}} placeholders" },
          "blanks": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["id", "acceptedAnswers"],
              "properties": {
                "id": { "type": "string" },
                "acceptedAnswers": { "type": "array", "items": { "type": "string" } },
                "caseSensitive": { "type": "boolean", "default": false },
                "useRegex": { "type": "boolean", "default": false }
              }
            }
          },
          "points": { "type": "number", "default": 10 }
        }
      }
    }
  }
}
```

#### `matching` (Matching)
```json
{
  "type": "object",
  "required": ["questions"],
  "properties": {
    "questions": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["id", "pairs"],
        "properties": {
          "id": { "type": "string" },
          "instruction": { "type": "string" },
          "pairs": {
            "type": "array",
            "minItems": 2,
            "items": {
              "type": "object",
              "required": ["id", "left", "right"],
              "properties": {
                "id": { "type": "string" },
                "left": { "type": "string" },
                "right": { "type": "string" }
              }
            }
          },
          "distractors": { "type": "array", "items": { "type": "string" } },
          "points": { "type": "number", "default": 10 },
          "partialCreditMode": { "type": "string", "enum": ["per-pair", "all-or-nothing"], "default": "per-pair" }
        }
      }
    }
  }
}
```

#### `drag-drop` (Drag and Drop)
```json
{
  "type": "object",
  "required": ["items", "dropZones"],
  "properties": {
    "instruction": { "type": "string" },
    "items": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "content", "correctZoneId"],
        "properties": {
          "id": { "type": "string" },
          "content": { "type": "string" },
          "imageUrl": { "type": "string", "format": "uri" },
          "correctZoneId": { "type": "string" }
        }
      }
    },
    "dropZones": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "label"],
        "properties": {
          "id": { "type": "string" },
          "label": { "type": "string" },
          "maxItems": { "type": "integer" }
        }
      }
    },
    "points": { "type": "number", "default": 10 },
    "partialCreditMode": { "type": "string", "enum": ["per-item", "all-or-nothing"], "default": "per-item" }
  }
}
```

#### `image-hotspots` (Image Hotspots)
```json
{
  "type": "object",
  "required": ["imageUrl", "hotspots"],
  "properties": {
    "imageUrl": { "type": "string", "format": "uri" },
    "imageAlt": { "type": "string" },
    "hotspots": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["id", "x", "y", "content"],
        "properties": {
          "id": { "type": "string" },
          "x": { "type": "number", "description": "% from left (0-100)" },
          "y": { "type": "number", "description": "% from top (0-100)" },
          "content": { "type": "string", "description": "HTML popup content" },
          "title": { "type": "string" },
          "icon": { "type": "string" }
        }
      }
    }
  }
}
```

#### `branching-scenario` (Branching Scenario)
```json
{
  "type": "object",
  "required": ["startNodeId", "nodes"],
  "properties": {
    "title": { "type": "string" },
    "startNodeId": { "type": "string" },
    "nodes": {
      "type": "array",
      "minItems": 2,
      "items": {
        "type": "object",
        "required": ["id", "type"],
        "properties": {
          "id": { "type": "string" },
          "type": { "type": "string", "enum": ["content", "question", "result"] },
          "content": { "type": "string" },
          "imageUrl": { "type": "string", "format": "uri" },
          "choices": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["id", "text", "nextNodeId"],
              "properties": {
                "id": { "type": "string" },
                "text": { "type": "string" },
                "nextNodeId": { "type": "string" },
                "points": { "type": "number" },
                "feedback": { "type": "string" }
              }
            }
          },
          "isEndNode": { "type": "boolean", "default": false },
          "score": { "type": "number" }
        }
      }
    }
  }
}
```

> **Note:** Schemas for remaining types follow similar patterns. All schemas are stored in the `component_types.schema` column and loaded into the Component Type Registry at startup.

---

## 7. New Database Tables & Migrations

### 7.1 Prerequisite Migration: Unify Base
```
alembic revision --autogenerate -m "unify_declarative_base"
```
- Move all models to import from `app.models.base.Base`
- No schema change, just import refactor

### 7.2 New Tables

#### `component_types` (replaces/extends `template_types`)
```sql
CREATE TABLE component_types (
    id SERIAL PRIMARY KEY,
    type_id VARCHAR(100) UNIQUE NOT NULL,     -- slug e.g. 'tabs'
    category VARCHAR(100) NOT NULL,           -- e.g. 'content-presentation'
    display_name VARCHAR(200) NOT NULL,
    description TEXT,
    icon VARCHAR(200),
    thumbnail VARCHAR(500),
    schema_json JSONB NOT NULL,               -- JSON Schema for data validation
    default_data JSONB NOT NULL DEFAULT '{}',
    completion_capabilities JSONB NOT NULL DEFAULT '["view"]',
    default_completion_type VARCHAR(50) DEFAULT 'view',
    scoring_enabled BOOLEAN DEFAULT FALSE,
    max_score NUMERIC,
    scoring_rules JSONB,                      -- per-quiz-type scoring config
    audio_support JSONB DEFAULT '{"perComponent":false,"perInteraction":false}',
    tags JSONB DEFAULT '[]',
    estimated_duration INTEGER,               -- minutes
    is_active BOOLEAN DEFAULT TRUE,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_component_types_category ON component_types(category);
CREATE INDEX idx_component_types_active ON component_types(is_active);
```

#### `pages` (replaces in-memory `COURSE_PAGES`)
```sql
CREATE TABLE pages (
    id SERIAL PRIMARY KEY,
    page_id VARCHAR(64) UNIQUE NOT NULL,      -- UUID
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    title VARCHAR(200) NOT NULL,
    order_index INTEGER NOT NULL,
    completion_config JSONB DEFAULT '{"enabled":true,"strategy":"all"}',
    layout_config JSONB DEFAULT '{"preset":"single-column","spacing":"normal"}',
    theme_overrides JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_pages_course_id ON pages(course_id);
CREATE INDEX idx_pages_order ON pages(course_id, order_index);
```

#### `components`
```sql
CREATE TABLE components (
    id SERIAL PRIMARY KEY,
    component_id VARCHAR(64) UNIQUE NOT NULL,  -- UUID
    page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    component_type VARCHAR(100) NOT NULL,      -- FK logically to component_types.type_id
    order_index INTEGER NOT NULL,
    data JSONB NOT NULL DEFAULT '{}',
    audio_config JSONB DEFAULT '{"enabled":false,"audioItems":[]}',
    completion_criteria JSONB DEFAULT '{"type":"view"}',
    styling JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_components_page_id ON components(page_id);
CREATE INDEX idx_components_type ON components(component_type);
CREATE INDEX idx_components_order ON components(page_id, order_index);
```

#### `themes`
```sql
CREATE TABLE themes (
    id SERIAL PRIMARY KEY,
    theme_id VARCHAR(64) UNIQUE NOT NULL,      -- UUID
    name VARCHAR(200) NOT NULL,
    is_preset BOOLEAN DEFAULT FALSE,
    colors JSONB NOT NULL,
    typography JSONB NOT NULL,
    component_styles JSONB NOT NULL DEFAULT '{}',
    created_by VARCHAR(200),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

#### `course_scoring`
```sql
CREATE TABLE course_scoring (
    id SERIAL PRIMARY KEY,
    scoring_id VARCHAR(64) UNIQUE NOT NULL,    -- UUID
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    config JSONB NOT NULL,
    component_scores JSONB NOT NULL DEFAULT '[]',
    scorm_reporting JSONB NOT NULL DEFAULT '{"enabled":true,"version":"1.2"}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_course_scoring_course ON course_scoring(course_id);
```

### 7.3 Altered Tables

#### `courses` — add theme reference
```sql
ALTER TABLE courses ADD COLUMN theme_id VARCHAR(64) REFERENCES themes(theme_id);
```

### 7.4 Migration Order
1. `unify_declarative_base` — import refactor only
2. `add_themes_table` — themes table (no FKs from other new tables)
3. `add_component_types_table` — component type registry
4. `add_pages_table` — pages with FK to courses
5. `add_components_table` — components with FK to pages
6. `add_course_scoring_table` — scoring config with FK to courses
7. `alter_courses_add_theme` — add theme_id to courses
8. `seed_component_types` — insert all 89 component type definitions
9. `seed_preset_themes` — insert default/dark/light/corporate preset themes
10. `migrate_templates_to_pages` — data migration: convert existing `TemplateRecord` rows to `PageRecord` + `ComponentRecord`

---

## 8. Completion Tracking Engine

### 8.1 Per-Component Completion Rules

| Completion Type | Rule | Example |
|----------------|------|---------|
| `view` | Component has been rendered / scrolled into view | Text content, infographic |
| `interact` | All `requiredInteractions` have been performed (clicks, reveals, tab switches) | Tabs: all tabs clicked. Accordion: all panels opened |
| `audio` | All audio items in `requiredAudioIds` have been listened to (≥90% of duration) | Tab narration: all tab audios played |
| `score` | Score ≥ `threshold`% on the component | MCQ: score ≥ 70% |
| `custom` | All entries in `requiredInteractions` AND `requiredAudioIds` satisfied | Combined: view all tabs AND listen to audio |

### 8.2 Page Completion Aggregation Algorithm

```
function isPageComplete(page):
    if not page.pageCompletion.enabled:
        return true  // always complete

    completableComponents = page.components.filter(c => c.completionCriteria exists)

    switch page.pageCompletion.strategy:
        case "all":
            return completableComponents.every(c => isComponentComplete(c))

        case "any":
            return completableComponents.some(c => isComponentComplete(c))

        case "percentage":
            completedCount = completableComponents.filter(c => isComponentComplete(c)).length
            percentage = (completedCount / completableComponents.length) * 100
            return percentage >= page.pageCompletion.completionThreshold

        case "custom":
            required = page.pageCompletion.requiredComponents  // componentId list
            return required.every(id => isComponentComplete(findComponent(id)))
```

### 8.3 Course Completion
Course is complete when **all pages with `pageCompletion.enabled = true`** are complete.

SCORM mapping:
- `cmi.core.lesson_status` = `"completed"` when course complete, `"incomplete"` otherwise
- If scoring is enabled: `cmi.core.lesson_status` = `"passed"` if score ≥ passingScore, `"failed"` otherwise
- `cmi.core.score.raw` = total weighted score
- `cmi.core.score.max` = max possible score
- `cmi.core.score.min` = 0

### 8.4 Tracking Mode
- **SCORM export:** All tracking happens **client-side** in the SCORM wrapper JS. The wrapper writes to `cmi.interactions`, `cmi.suspend_data` (stores JSON state), and `cmi.core.*` fields. The backend generates this JS.
- **Preview mode / non-SCORM:** The `POST /interactions` endpoint records events server-side. State stored in a session table or returned to the client for local storage.

---

## 9. Scoring Engine

### 9.1 Score Calculation Flow

```
function calculateCourseScore(course, answers):
    scoringConfig = course.scoring.config
    componentScores = course.scoring.componentScores
    results = []

    for each answer in answers:
        componentDef = ComponentTypeRegistry.get(answer.componentType)
        rules = componentDef.scoringRules
        rawScore = calculateComponentScore(answer, rules)
        maxScore = componentScores.find(c => c.componentId == answer.componentId).maxPoints
        weight = componentScores.find(c => c.componentId == answer.componentId).weight
        results.push({ componentId, rawScore, maxScore, weight, weightedScore: (rawScore/maxScore) * weight * 100 })

    totalPercentage = sum(results.map(r => r.weightedScore))
    passed = totalPercentage >= scoringConfig.passingScore
    return { totalPercentage, passed, results }
```

### 9.2 Per-Quiz-Type Scoring Rules

| Component Type | Scoring Rule | Partial Credit |
|---------------|-------------|----------------|
| `mcq` | 1 correct answer per question. Full points if correct, 0 if wrong | No |
| `multi-select` | Multiple correct answers. **Proportional**: `(correct_selected - incorrect_selected) / total_correct * points`, min 0. **All-or-nothing**: full points only if exact match | Configurable via `partialCreditMode` |
| `true-false` | Same as MCQ (binary correct/incorrect) | No |
| `fill-blanks` | Per-blank evaluation. Match against `acceptedAnswers[]` (case-insensitive by default, optional regex). Points = `(correct_blanks / total_blanks) * points` | Yes (proportional) |
| `matching` | **Per-pair**: `(correct_pairs / total_pairs) * points`. **All-or-nothing**: full points only if all pairs correct | Configurable via `partialCreditMode` |
| `drag-drop` | **Per-item**: `(correctly_placed / total_items) * points`. **All-or-nothing**: full points only if all items correct | Configurable via `partialCreditMode` |
| `scenario-question` | Points based on selected choice. Each choice node has a `points` value | Varies by scenario design |
| `branching-scenario` | Cumulative points from path. Sum of `points` on each choice node taken | Yes (path-dependent) |
| `knowledge-check` | Same as MCQ but typically ungraded. Scoring optional | No |
| `final-assessment` | Container type: sums scores from embedded questions (MCQ, multi-select, etc.) | Depends on question types |
| `quiz-game` | Points per correct answer + time bonuses (optional) | Configurable |
| `pre-assessment` / `diagnostic-quiz` | Same as MCQ. Results used for adaptive path recommendations, not pass/fail | No |

### 9.3 Attempt Management
- `maxAttempts`: null = unlimited, N = max N attempts
- `attemptScoring`:
  - `best` — highest score across all attempts is reported
  - `last` — most recent attempt score is reported
  - `average` — average of all attempt scores is reported
- SCORM: Only the reported score (per `attemptScoring`) is written to `cmi.core.score`

### 9.4 SCORM Interaction Reporting
For each scorable component, generate `cmi.interactions.N`:
| Component Type | `cmi.interactions.N.type` | `cmi.interactions.N.student_response` format |
|---------------|--------------------------|----------------------------------------------|
| `mcq` | `choice` | `"opt-b"` (selected option ID) |
| `multi-select` | `choice` | `"opt-a,opt-c"` (comma-separated) |
| `true-false` | `true-false` | `"true"` or `"false"` |
| `fill-blanks` | `fill-in` | `"answer text"` |
| `matching` | `matching` | `"left1[.]right1[,]left2[.]right2"` |
| `drag-drop` | `performance` | `"item1[.]zone1[,]item2[.]zone2"` |

---

## 10. SCORM Export Changes

### 10.1 Multi-Component Page Rendering
Each page in the SCORM HTML must render all its components in the layout grid:

```html
<div class="page" data-page-id="uuid" style="display: grid; grid-template-areas: ...">
  <div class="component" data-component-id="uuid" data-type="tabs" style="grid-area: main">
    <!-- Tabs component HTML rendered by registry template -->
  </div>
  <div class="component" data-component-id="uuid" data-type="accordion" style="grid-area: sidebar">
    <!-- Accordion component HTML -->
  </div>
</div>
```

### 10.2 Theme CSS Injection
The SCORM export service must generate a `theme.css` file from the resolved theme:

```
function generateThemeCSS(theme):
    css = ":root {"
    for colorName, colorValue in theme.colors:
        css += f"  --color-{colorName}: {colorValue};\n"
    for typoProp, typoValue in theme.typography:
        css += f"  --typography-{typoProp}: {typoValue};\n"
    css += "}\n"
    // ... component-specific styles
    return css
```

Include in SCORM package: `<link rel="stylesheet" href="theme.css">`

### 10.3 Audio Player in SCORM
The SCORM wrapper JS must include an audio player that:
1. Loads `audioConfig.audioItems[]` for each component
2. Plays audio on the specified `triggerOn` event
3. Tracks audio completion (≥90% listened = complete)
4. Stores audio state in `cmi.suspend_data` JSON
5. Fires completion check when `requiredForCompletion` audio items are done

### 10.4 Completion Tracking in SCORM Wrapper
```javascript
// Generated SCORM wrapper includes:
const completionState = JSON.parse(LMSGetValue("cmi.suspend_data") || "{}");

function onComponentInteraction(componentId, interactionId) {
    completionState[componentId] = completionState[componentId] || { interactions: [], audios: [] };
    completionState[componentId].interactions.push(interactionId);
    checkPageCompletion(currentPageId);
    LMSSetValue("cmi.suspend_data", JSON.stringify(completionState));
}

function checkPageCompletion(pageId) {
    // Implements §8.2 algorithm client-side
    // When page complete, check if ALL pages complete → set cmi.core.lesson_status
}
```

---

## 11. Migration Strategy

### 11.1 Data Migration: Templates → Pages + Components
For each existing `TemplateRecord`:
```
for each course in CourseRecord:
    for each template in course.json_data["templates"]:
        page = PageRecord(
            page_id = generate_uuid(),
            course_id = course.id,
            title = template["title"],
            order_index = template["order"],
            completion_config = {"enabled": true, "strategy": "all"},
            layout_config = {"preset": "single-column", "spacing": "normal"}
        )
        component = ComponentRecord(
            component_id = generate_uuid(),
            page_id = page.id,
            component_type = normalize_type(template["type"]),  # video→video-slide, quiz→mcq, etc.
            order_index = 0,  # single component per migrated page
            data = template["data"]
        )
```

### 11.2 Type Normalization Map
| Old Type | New Component Type |
|----------|-------------------|
| `welcome` | `text-with-media` |
| `content-text` | `text-with-media` |
| `content-video` | `video-slide` |
| `mcq` | `mcq` |
| `summary` | `summary` |
| `video` | `video-slide` |
| `quiz` | `mcq` |
| `content-image` | `text-with-media` |
| `interactive` | `click-reveal` |

### 11.3 API Backward Compatibility
During the transition period, `POST /courses` accepts **both formats**:

```python
# In course router:
if "templates" in request_body and "pages" not in request_body:
    # Legacy format — auto-convert
    pages = convert_templates_to_pages(request_body["templates"])
    request_body["pages"] = pages
    del request_body["templates"]
```

The `GET /courses/{id}` response always returns the new `pages[].components[]` format.

**Conversion behavior (current backend):**
- Legacy `templates[]` payloads are accepted and validated for export without auto-generating DB `pages` records.
- Page/component IDs are generated server-side (UUIDs) only when using `POST /courses/{courseId}/pages` and component endpoints.
- If not provided, `page.layout`, `page.theme`, and `page.pageCompletion` remain `null`; completion strategy defaults to `all` at read time.
- If not provided, `component.audioConfig`, `component.completionCriteria`, and `component.styling` remain `null`.

### 11.4 SCORM Export Compatibility
Existing SCORM export continues to work:
- `POST /export` (raw JSON) — accepts legacy `templates[]` format, auto-converts
- `POST /export/scorm/{id}` — reads from new `pages` + `components` tables
- Remove all hardcoded type mappings from `export.py`

---

## 12. New Backend Files

### 12.1 Models
| File | Purpose |
|------|---------|
| `app/models/base.py` | **Single shared `Base = declarative_base()`** |
| `app/models/component.py` | Pydantic models: `Component`, `AudioConfig`, `AudioItem`, `CompletionCriteria`, `ComponentStyling` |
| `app/models/page.py` | Pydantic models: `Page`, `PageCompletion`, `PageLayout`, `ComponentPlacement` |
| `app/models/theme.py` | Pydantic models: `Theme`, `ThemeColors`, `ThemeTypography`, `ThemeComponentStyles`, `ThemeOverrides` |
| `app/models/scoring.py` | Pydantic models: `ScoringConfig`, `ComponentScore`, `ScormReporting`, `ScormObjective` |
| `app/models/interaction.py` | Pydantic models: `InteractionEvent`, `InteractionData` |
| `app/models/component_type.py` | Pydantic model: `ComponentTypeDefinition`, `AudioSupportConfig`, `ScoringRuleSet` |
| `app/models/persisted_course.py` | **Update**: `PageRecord`, `ComponentRecord`, `ThemeRecord`, `CourseScoringRecord` ORM models (import from `base.py`) |
| `app/models/template_type.py` | **Update**: import `Base` from `base.py` instead of local `declarative_base()` |
| `app/models/course.py` | **Update**: `Course.pages` replaces `Course.templates`; `CourseSettings.themeId` replaces `theme` string |

### 12.2 Repositories
| File | Purpose |
|------|---------|
| `app/repositories/page_repo.py` | CRUD for `PageRecord` |
| `app/repositories/component_repo.py` | CRUD for `ComponentRecord` (including reorder, bulk-insert) |
| `app/repositories/component_type_repo.py` | CRUD for component type registry (`component_types` table) |
| `app/repositories/theme_repo.py` | CRUD for `ThemeRecord` (presets + custom) |
| `app/repositories/scoring_repo.py` | CRUD for `CourseScoringRecord` |

### 12.3 Services
| File | Purpose |
|------|---------|
| `app/services/completion_engine.py` | Component completion checking, page aggregation (§8 algorithm) |
| `app/services/scoring_engine.py` | Score calculation, per-type rules, attempt management (§9 algorithm) |
| `app/services/theme_service.py` | Theme resolution (inheritance chain), CSS generation for SCORM |
| `app/services/component_validator.py` | Validate component `data` against JSON Schema from registry |
| `app/services/scorm_export.py` | **Update**: multi-component rendering, theme CSS, audio player, completion tracking JS |

### 12.4 Routers
| File | Purpose |
|------|---------|
| `app/routers/components.py` | Component Type Registry API (§5.1) |
| `app/routers/page_components.py` | Page & Component CRUD API (§5.2) |
| `app/routers/themes.py` | Theme API (§5.3) |
| `app/routers/scoring.py` | Scoring & Completion API (§5.4) |
| `app/routers/audio.py` | Audio Management API (§5.5) |
| `app/routers/courses.py` | **Update**: accept pages[], remove in-memory `COURSE_PAGES` |
| `app/routers/export.py` | **Update**: remove hardcoded type mappings |
| `app/main.py` | **Update**: register 5 new routers |

### 12.5 Migrations
| File | Purpose |
|------|---------|
| `alembic/versions/YYYYMMDD_0001_unify_base.py` | Import refactor |
| `alembic/versions/YYYYMMDD_0002_add_themes.py` | `themes` table |
| `alembic/versions/YYYYMMDD_0003_add_component_types.py` | `component_types` table |
| `alembic/versions/YYYYMMDD_0004_add_pages.py` | `pages` table |
| `alembic/versions/YYYYMMDD_0005_add_components.py` | `components` table |
| `alembic/versions/YYYYMMDD_0006_add_scoring.py` | `course_scoring` table |
| `alembic/versions/YYYYMMDD_0007_alter_courses.py` | Add `theme_id` to courses |
| `alembic/versions/YYYYMMDD_0008_seed_component_types.py` | Insert 89 component type definitions |
| `alembic/versions/YYYYMMDD_0009_seed_themes.py` | Insert preset themes |
| `alembic/versions/YYYYMMDD_0010_migrate_templates.py` | Convert `TemplateRecord` → `PageRecord` + `ComponentRecord` |

---

## 13. Scoped Out (Future Phases)

The following features from the expanded template list require additional infrastructure beyond this specification. They are **acknowledged but deferred**:

| Feature | Why Deferred | Prerequisites |
|---------|-------------|---------------|
| **Adaptive Learning Path** | Requires learner profile storage, recommendation engine | User/learner identity system |
| **Peer Review / Discussion Prompt** | Requires multi-user interaction (real-time or async) | User identity, WebSocket or polling backend |
| **Poll / Vote** | Requires result aggregation across users | User identity, real-time updates |
| **Team Challenge** | Requires team/group management | User groups, permissions |
| **Scenario Debate** | Requires multi-user turn-based interaction | User identity, session management |
| **Completion Certificate** | Requires PDF generation or certificate template rendering | PDF library (e.g. ReportLab/WeasyPrint) |
| **Performance Dashboard** | Requires analytics event aggregation + reporting | Analytics pipeline, time-series storage |
| **Skill Mastery Report** | Requires cross-course skill taxonomy | Skill ontology, learner progress aggregation |
| **Manager Review Page** | Requires role-based access | User roles, permissions system |

**Component types for these features are registered in the Component Type Registry** (§6.2) with their schemas and default data, so authoring is possible immediately. The runtime behavior (real-time collaboration, analytics, certificates) will be implemented when the prerequisite infrastructure is built.

---

## 14. Implementation Order

| Phase | Scope | Priority |
|-------|-------|----------|
| **Phase 0** | Infrastructure: Unify `Base`, persist pages, remove mock data, remove hardcoded type mappings | **P0 — Blocker** |
| **Phase 1** | Component Type Registry: DB table, seed data, API endpoints | **P0** |
| **Phase 2** | Page + Component models: ORM, repos, CRUD API, schema-driven validation | **P0** |
| **Phase 3** | Theme System: Layout + Color/Style, DB, API, CSS generation | **P1** |
| **Phase 4** | Audio System: Per-interaction audio, narration listing | **P1** |
| **Phase 5** | Completion Engine: Per-component tracking, page aggregation | **P1** |
| **Phase 6** | Scoring Engine: Per-type rules, score calculation, attempt management | **P1** |
| **Phase 7** | SCORM Export Upgrade: Multi-component rendering, theme CSS, audio player, completion/scoring JS | **P1** |
| **Phase 8** | Migration: Template → Page + Component data migration, backward-compat API | **P1** |
| **Phase 9** | Test Suite: Full coverage for all new APIs and engines | **P1** |
| **Phase 10** | Advanced Features: Adaptive, social, analytics (see §13) | **P2** |
