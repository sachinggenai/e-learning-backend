# Template Engine - Backend Requirements Specification
**Version**: 1.0 | **Date**: February 2026 | **Status**: Draft

## 1. Executive Summary
This document specifies backend API and data model requirements to support the new Template Engine architecture. The system evolves from 5 fixed template types to a composable component-based authoring platform with 60+ template types, scoring, completion tracking, and theming.

## 2. Current State Analysis
### 2.1 Existing API Endpoints
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/courses` | POST/PATCH | Create/update course |
| `/api/v1/courses/{id}` | GET/DELETE | Retrieve/delete course |
| `/api/v1/export` | POST | SCORM export |
| `/api/v1/export/validate` | POST | Schema validation |
| `/api/v1/health` | GET | Health check |

### 2.2 Current Data Model Limitations
- Templates are flat: one `type` + `data` object per template
- No component composition (multiple components per page)
- No audio/media playback metadata
- No completion criteria per template
- No scoring configuration
- Theme stored but not applied

## 3. New Data Models
### 3.1 Component Schema
```json
{
  "componentId": "string (UUID)",
  "componentType": "string (enum)",
  "order": "integer",
  "data": "object (type-specific)",
  "audioConfig": {
    "enabled": "boolean",
    "audioUrl": "string | null",
    "autoplay": "boolean",
    "requiredForCompletion": "boolean"
  },
  "completionCriteria": {
    "type": "enum (view | interact | audio | score | custom)",
    "threshold": "number | null",
    "interactions": "string[] | null"
  },
  "styling": {
    "themeOverrides": "object | null",
    "layoutPosition": "string | null"
  }
}
```
### 3.2 Page Schema (Updated)
```json
{
  "pageId": "string (UUID)",
  "title": "string",
  "order": "integer",
  "components": "Component[]",
  "pageCompletion": {
    "strategy": "enum (all | any | percentage | custom)",
    "requiredComponents": "string[] | null",
    "completionThreshold": "number (0-100)"
  },
  "layout": {
    "templateId": "string | null",
    "columns": "integer (1-4)",
    "spacing": "enum (compact | normal | spacious)"
  },
  "theme": {
    "inheritCourse": "boolean",
    "overrides": "ThemeOverrides | null"
  }
}
```
### 3.3 Component Type Registry
```json
{
  "typeId": "string",
  "category": "string",
  "displayName": "string",
  "icon": "string",
  "schema": "JSONSchema",
  "defaultData": "object",
  "completionCapabilities": ["view", "interact", "audio", "score"],
  "scoringEnabled": "boolean",
  "maxScore": "number | null"
}
```
### 3.4 Theme Schema
```json
{
  "themeId": "string (UUID)",
  "name": "string",
  "scope": "enum (course | page | component)",
  "layout": {
    "preset": "string | null",
    "customGrid": "GridDefinition | null"
  },
  "colors": {
    "primary": "string (hex)",
    "secondary": "string (hex)",
    "background": "string (hex)",
    "surface": "string (hex)",
    "text": "string (hex)",
    "textSecondary": "string (hex)",
    "accent": "string (hex)",
    "error": "string (hex)",
    "success": "string (hex)"
  },
  "typography": {
    "fontFamily": "string",
    "headingFont": "string | null",
    "baseFontSize": "number (px)",
    "headingSizes": { "h1": "number", "h2": "number", "h3": "number" },
    "lineHeight": "number"
  },
  "components": {
    "button": { "borderRadius": "number", "padding": "string" },
    "card": { "borderRadius": "number", "shadow": "string" },
    "tabs": { "style": "enum (underline | pill | boxed)" },
    "accordion": { "style": "enum (bordered | minimal | card)" }
  }
}
```
### 3.5 Scoring Schema
```json
{
  "scoringId": "string (UUID)",
  "courseId": "string",
  "config": {
    "passingScore": "number (0-100)",
    "maxAttempts": "number | null",
    "showCorrectAnswers": "boolean",
    "showScoreAfterQuestion": "boolean",
    "weightedScoring": "boolean"
  },
  "componentScores": [{
    "componentId": "string",
    "weight": "number (0-1)",
    "maxPoints": "number"
  }],
  "scormReporting": {
    "enabled": "boolean",
    "version": "enum (1.2 | 2004)",
    "objectives": "SCORMObjective[]"
  }
}
```

## 4. New API Endpoints
### 4.1 Component Registry API
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/components` | GET | List all component types with schemas |
| `/api/v1/components/{type}` | GET | Get component type definition |
| `/api/v1/components/categories` | GET | List component categories |

### 4.2 Page Components API
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/courses/{id}/pages/{pageId}/components` | GET | List page components |
| `/api/v1/courses/{id}/pages/{pageId}/components` | POST | Add component to page |
| `/api/v1/courses/{id}/pages/{pageId}/components/{componentId}` | PATCH | Update component |
| `/api/v1/courses/{id}/pages/{pageId}/components/{componentId}` | DELETE | Remove component |
| `/api/v1/courses/{id}/pages/{pageId}/components/reorder` | POST | Reorder components |

### 4.3 Theme API
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/themes` | GET | List available themes |
| `/api/v1/themes` | POST | Create custom theme |
| `/api/v1/themes/{id}` | GET/PATCH/DELETE | Theme CRUD |
| `/api/v1/themes/presets` | GET | List built-in theme presets |
| `/api/v1/courses/{id}/theme` | GET/PATCH | Course theme settings |
| `/api/v1/courses/{id}/pages/{pageId}/theme` | GET/PATCH | Page theme overrides |

### 4.4 Scoring & Completion API
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/courses/{id}/scoring` | GET/PATCH | Scoring configuration |
| `/api/v1/courses/{id}/scoring/calculate` | POST | Calculate course score |
| `/api/v1/courses/{id}/completion` | GET | Get completion status |
| `/api/v1/courses/{id}/pages/{pageId}/completion` | POST | Record page completion |
| `/api/v1/courses/{id}/components/{componentId}/interaction` | POST | Record component interaction |

### 4.5 Audio Management API
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/assets/audio` | POST | Upload audio file |
| `/api/v1/assets/audio/{id}/metadata` | GET/PATCH | Audio metadata (duration, transcript) |
| `/api/v1/courses/{id}/narration` | GET | List all audio across course |

## 5. Component Type Categories
(See full enum in requirements above)

## 6. Completion Tracking Engine
- Completion criteria per component type (view, interact, audio, score, custom)
- Page wrapper logic to aggregate component completions

## 7. Scoring Engine
- Scorable component types, max points, partial credit
- SCORM score reporting (1.2/2004)

## 8. Migration Strategy
- Backward compatibility for existing templates
- Database migration steps

## 9. API Response Examples
(See requirements above for JSON examples)
