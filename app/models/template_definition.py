"""
Template Definition Models for Dynamic Template System - DEPRECATED

IMPORTANT: This module is kept for backward compatibility only.
All template definitions are now in app.models.persisted_course.TemplateDefinition

DO NOT define tables here as they conflict with persisted_course.py
"""
import warnings

# Issue deprecation warning
warnings.warn(
    "app.models.template_definition is deprecated. Use app.models.persisted_course.TemplateDefinition instead.",
    DeprecationWarning,
    stacklevel=2
)

# For backward compatibility, create an alias to the new location
# This avoids the "Table already defined" error
from app.models.persisted_course import TemplateDefinition as TemplateDefinitionRecord  # noqa

__all__ = ["TemplateDefinitionRecord"]
