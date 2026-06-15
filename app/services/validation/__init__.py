"""
Unified Validation Pipeline — US-BKND-AI-008.

Package providing course-level structural validation, accessibility checks,
and a unified orchestrator that runs all validators across all pages
in a course.

Reuses:
- TemplateValidationEngine (AI-005) for per-page schema + business rules
- PageRepository for loading course pages
- AISessionRepository for session validation

Implemented:
    US-BKND-AI-008: Course-level structural validation and unified orchestrator
    US-BKND-AI-008: Accessibility heuristic checks (alt-text, titles, headings)

Future:
    US-BKND-AI-035: Full WCAG 2.1 AA accessibility compliance
    Export readiness checks (SCORM integration)
"""

from app.services.validation.course_validator import (
    CourseLevelValidator,
    CourseValidationIssue,
)
from app.services.validation.unified_validator import (
    UnifiedValidator,
    UnifiedValidationResult,
    UnifiedValidationMessage,
    ValidationScope,
)

__all__ = [
    "CourseLevelValidator",
    "CourseValidationIssue",
    "UnifiedValidator",
    "UnifiedValidationResult",
    "UnifiedValidationMessage",
    "ValidationScope",
]
