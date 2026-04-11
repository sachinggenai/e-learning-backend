# SCORM

## Purpose

Generate SCORM 1.2-compatible packages from validated course data.

## Critical Rules

- Build `courseData` as an object with metadata and template array.
- Respect script load order in generated player assets.
- Sanitize dynamic content before embedding in HTML/JS.
- Keep package/template counts and asset size within operational limits.

## Main Implementation

- Export service: `app/services/scorm_export.py`
- Template registry: `app/services/scorm/registries/template_registry.py`
