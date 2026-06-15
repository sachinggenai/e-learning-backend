"""Unified Validation Orchestrator — US-BKND-AI-008.

Orchestrates full-course and proposal-scoped validation by running
all configured validators: schema, business rules, course-level structure,
accessibility heuristics, and (future) SCORM export readiness.

Reuses TemplateValidationEngine from AI-005 for per-page schema and
business rule validation. Adds course-level structural validation
and accessibility heuristic checks.

FR-001: Unified validate_course endpoint
FR-002: Schema validation (delegates to TemplateValidationEngine)
FR-003: Page-level business rules (delegates to TemplateValidationEngine)
FR-004: Course-level structural validation (CourseLevelValidator)
FR-006: Accessibility compliance validation (CourseLevelValidator)
"""

from __future__ import annotations

import time
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import List, Dict, Any, Optional, Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.page_component_repo import PageRepository
from app.services.ai.template_contracts import AITemplateContractsService
from app.services.ai.validation_engine import (
    TemplateValidationEngine,
    ValidationResult as SinglePageResult,
)
from app.services.validation.course_validator import (
    CourseLevelValidator,
    CourseValidationIssue,
)

logger = logging.getLogger("ai_authoring")


# ═══════════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════════

class ValidationScope(str, Enum):
    """Scope of validation to run."""
    SCHEMA_ONLY = "schema_only"
    BUSINESS_RULES = "business_rules"
    SCORM_COMPLIANCE = "scorm_compliance"
    ACCESSIBILITY = "accessibility"
    FULL = "full"


class UnifiedValidationMessage(BaseModel):
    """A single validation finding."""
    code: str
    page_id: Optional[str] = None
    field: str = ""
    message: str
    severity: str = "error"  # error, warning, info
    hint: Optional[str] = None


class UnifiedValidationResult(BaseModel):
    """Result of a full-course or proposal validation."""
    is_valid: bool = True
    errors: List[UnifiedValidationMessage] = Field(default_factory=list)
    warnings: List[UnifiedValidationMessage] = Field(default_factory=list)
    info: List[UnifiedValidationMessage] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=lambda: {
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": "1.0.0",
        "pages_checked": 0,
        "duration_ms": 0,
    })


# ═══════════════════════════════════════════════════════════════════
# Unified Validator
# ═══════════════════════════════════════════════════════════════════

class UnifiedValidator:
    """Orchestrates the full validation pipeline for a course.

    Runs course-level structural checks, per-page schema + business
    rule validation, and accessibility heuristic checks. Designed
    to be created per-request with injected repositories.

    Usage:
        validator = UnifiedValidator(db)
        result = await validator.validate_course(course_id, scope="full")
        if result.is_valid:
            # proceed
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.page_repo = PageRepository(db)
        self.contracts = AITemplateContractsService(db)
        self.template_engine = TemplateValidationEngine(self.contracts)
        self.course_validator = CourseLevelValidator()

    # ── Public API ──────────────────────────────────────────────

    async def validate_course(
        self,
        course_id: str,
        scope: ValidationScope = ValidationScope.FULL,
    ) -> UnifiedValidationResult:
        """Run unified validation on all pages in a course.

        Args:
            course_id: The course to validate.
            scope: Which validators to run.

        Returns:
            UnifiedValidationResult with errors, warnings, info, and metadata.
        """
        start = time.monotonic()
        errors: List[UnifiedValidationMessage] = []
        warnings: List[UnifiedValidationMessage] = []
        info: List[UnifiedValidationMessage] = []

        # Load all pages for the course
        try:
            pages = await self.page_repo.list_by_course(course_id)
        except Exception:
            logger.exception("Failed to load pages for course %s", course_id[:8])
            return UnifiedValidationResult(
                is_valid=False,
                errors=[
                    UnifiedValidationMessage(
                        code="SERVER_ERROR",
                        field="",
                        message="Failed to load course pages. Please try again.",
                        severity="error",
                    )
                ],
                metadata={
                    "validated_at": datetime.now(timezone.utc).isoformat(),
                    "schema_version": "1.0.0",
                    "pages_checked": 0,
                    "duration_ms": int((time.monotonic() - start) * 1000),
                },
            )

        # Build page dicts for the course-level validator
        page_dicts = []
        for p in pages:
            pdict = {
                "page_id": p.page_id,
                "title": p.title,
                "order": p.order_index,
                "order_index": p.order_index,
                "template_type": self._infer_template_type(p),
                "components": [
                    {
                        "component_id": c.component_id,
                        "component_type": c.component_type,
                        "order": c.order_index,
                        "data": c.data or {},
                        "audio_config": getattr(c, "audio_config", None),
                        "completion_criteria": getattr(c, "completion_criteria", None),
                        "styling": getattr(c, "styling", None),
                    }
                    for c in (p.components or [])
                ],
            }
            page_dicts.append(pdict)

        # ── Course-level structural validation ─────────────────
        if scope in (ValidationScope.FULL, ValidationScope.BUSINESS_RULES):
            structural_issues = self.course_validator.validate_course_structure(
                page_dicts
            )
            for issue in structural_issues:
                msg = self._to_unified_message(issue)
                if issue.severity == "error":
                    errors.append(msg)
                elif issue.severity == "warning":
                    warnings.append(msg)
                else:
                    info.append(msg)

        # ── Per-page schema + business rules ──────────────────
        if scope in (ValidationScope.FULL, ValidationScope.SCHEMA_ONLY,
                     ValidationScope.BUSINESS_RULES):
            for pdict in page_dicts:
                ttype = pdict["template_type"]
                # Build data dict from components for validation
                data = self._extract_page_data(pdict)

                # Map scope
                if scope == ValidationScope.SCHEMA_ONLY:
                    engine_scope: Literal["schema_only", "business_rules", "full"] = "schema_only"
                elif scope == ValidationScope.BUSINESS_RULES:
                    engine_scope = "business_rules"
                else:
                    engine_scope = "full"

                try:
                    result = await self.template_engine.validate(
                        template_type=ttype, data=data, scope=engine_scope
                    )
                except Exception:
                    logger.exception(
                        "Validation failed for page %s (type=%s)",
                        pdict["page_id"][:8], ttype,
                    )
                    errors.append(
                        UnifiedValidationMessage(
                            code="VALIDATION_ENGINE_ERROR",
                            page_id=pdict["page_id"],
                            field="",
                            message=f"Validation engine error for page '{pdict['title']}'.",
                            severity="error",
                        )
                    )
                    continue

                # Map messages
                for msg in result.messages:
                    um = UnifiedValidationMessage(
                        code=msg.code,
                        page_id=pdict.get("page_id"),
                        field=msg.field,
                        message=msg.message,
                        severity=msg.severity,
                        hint=msg.hint,
                    )
                    if msg.severity == "error":
                        errors.append(um)
                    elif msg.severity == "warning":
                        warnings.append(um)
                    else:
                        info.append(um)

        # ── Accessibility validation ───────────────────────────
        if scope in (ValidationScope.FULL, ValidationScope.ACCESSIBILITY):
            accessibility_issues = self.course_validator.validate_accessibility(
                page_dicts
            )
            for issue in accessibility_issues:
                msg = self._to_unified_message(issue)
                # Accessibility issues are always warnings per FR-006
                warnings.append(msg)

        # ── SCORM export readiness (stub) ─────────────────────
        if scope in (ValidationScope.FULL, ValidationScope.SCORM_COMPLIANCE):
            # TODO(US-BKND-AI-008): Integrate with ExportValidator for full SCORM checks.
            # For now, add an info message noting SCORM validation is not yet deep.
            info.append(
                UnifiedValidationMessage(
                    code="SCORM_CHECK_INFO",
                    field="",
                    message=(
                        "SCORM export readiness validation is not yet fully implemented. "
                        "Basic structural checks have been run."
                    ),
                    severity="info",
                    hint="Full SCORM validation will be available in a future release.",
                )
            )

        duration_ms = int((time.monotonic() - start) * 1000)

        return UnifiedValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            info=info,
            metadata={
                "validated_at": datetime.now(timezone.utc).isoformat(),
                "schema_version": "1.0.0",
                "pages_checked": len(pages),
                "duration_ms": duration_ms,
            },
        )

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _extract_page_data(page_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Extract the data payload from a page dict for validation.

        For simple templates (text-content), the data is in the first
        component's data field. For complex templates (tabs, accordion),
        the data is structured at the page level.
        """
        ttype = page_dict.get("template_type", "")
        components = page_dict.get("components", [])

        # For single-component templates, use the component's data
        if ttype == "text-content" and components:
            return components[0].get("data", {})

        # For multi-item templates, build a structured data dict
        if ttype in ("tabs", "accordion", "click-reveal"):
            items = []
            for c in components:
                cdata = c.get("data", {})
                items.append({
                    "title": cdata.get("title", ""),
                    "content": cdata.get("content", ""),
                })
            return {"title": page_dict.get("title", ""), "items": items}

        if ttype == "final-assessment" and components:
            cdata = components[0].get("data", {})
            return {
                "title": page_dict.get("title", ""),
                "passing_score": cdata.get("passingScore", cdata.get("passing_score", 0)),
                "questions": cdata.get("questions", []),
            }

        # Fallback: return first component's data
        if components:
            return components[0].get("data", {})

        return {}

    @staticmethod
    def _infer_template_type(page) -> str:
        """Infer template type from page layout or first component."""
        layout = getattr(page, "layout", None)
        if isinstance(layout, dict):
            ttype = layout.get("templateType") or layout.get("template_type")
            if ttype:
                return ttype

        comps = getattr(page, "components", None)
        if comps and len(comps) > 0:
            return comps[0].component_type

        return "text-content"

    @staticmethod
    def _to_unified_message(issue: CourseValidationIssue) -> UnifiedValidationMessage:
        """Convert a CourseValidationIssue to a UnifiedValidationMessage."""
        return UnifiedValidationMessage(
            code=issue.code,
            page_id=issue.page_id,
            field=issue.field,
            message=issue.message,
            severity=issue.severity,
            hint=issue.hint,
        )
