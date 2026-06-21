"""Durable workflow engine package — US-BKND-AI-034.

Importing step modules triggers decorator registration on the shared StepRegistry singleton.
"""
from app.services.workflow.steps import course_generation  # noqa: F401
from app.services.workflow.steps import scorm_export       # noqa: F401
