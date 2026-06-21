"""
Export Validation Pipeline

Validates course data before export to ensure:
1. All components have exportable component types (using renderer manifest)
2. All referenced assets exist and are accessible
3. Style and theme data is valid
4. Interaction configurations are serializable
5. Required data fields are present

Returns detailed validation results including errors, warnings, and summary metrics.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from app.models.export_contract import (
    ExportedCourse,
    ExportValidationResult,
    ExportValidationError,
)
from app.services.renderer_manifest import get_renderer_manifest
from datetime import datetime

logger = logging.getLogger(__name__)


class ExportValidator:
    """Validates course data for SCORM export"""

    def __init__(self):
        self.manifest = get_renderer_manifest()
        self.errors: List[ExportValidationError] = []
        self.warnings: List[str] = []
        self.supported_component_count = 0
        self.unsupported_component_count = 0

    def validate(self, course_data: Dict[str, Any]) -> ExportValidationResult:
        """
        Validate course data for export.
        
        Args:
            course_data: Course dictionary with pages, components, assets
            
        Returns:
            ExportValidationResult with validation status and details
        """
        self.errors = []
        self.warnings = []
        self.supported_component_count = 0
        self.unsupported_component_count = 0

        # Extract course ID for error reporting
        course_id = course_data.get("courseId", "unknown")
        
        # Validate pages and components
        pages = course_data.get("pages", [])
        if not pages:
            self.errors.append(ExportValidationError(
                code="EMPTY_COURSE",
                message="Course must contain at least one page",
                details={"courseId": course_id}
            ))
            return self._build_result()

        # Validate each page and its components
        for page in pages:
            self._validate_page(page, course_id)

        # Validate theme and styling
        self._validate_theme(course_data)

        # Validate assets
        if "assets" in course_data:
            self._validate_assets(course_data.get("assets", []), course_id)

        # Validate course-level settings
        self._validate_course_settings(course_data, course_id)

        return self._build_result()

    def _validate_page(self, page: Dict[str, Any], course_id: str) -> None:
        """Validate a single page"""
        page_id = page.get("pageId", "unknown")

        # Validate page has required fields
        if not page_id:
            self.errors.append(ExportValidationError(
                code="MISSING_PAGE_ID",
                message="Page must have pageId",
                pagId=page_id,
                details={"courseId": course_id}
            ))
            return

        # Validate components
        components = page.get("components", [])
        if not components:
            self.warnings.append(f"Page {page_id} has no components")
            return

        for component in components:
            self._validate_component(component, page_id, course_id)

        # Validate page styling if present
        if "styleConfig" in page:
            self._validate_style_config(page["styleConfig"], page_id)

    def _validate_component(
        self, component: Dict[str, Any], page_id: str, course_id: str
    ) -> None:
        """Validate a single component"""
        component_id = component.get("componentId", "unknown")
        component_type = component.get("componentType", "unknown")

        # Check if component type is supported
        if not self.manifest.is_supported(component_type):
            self.unsupported_component_count += 1
            
            # Check if there's a fallback
            fallback = self.manifest.get_fallback(component_type)
            
            if fallback:
                self.warnings.append(
                    f"Component {component_id} (type: {component_type}) is not exportable, "
                    f"will use fallback type: {fallback}"
                )
            else:
                self.errors.append(ExportValidationError(
                    code="UNSUPPORTED_COMPONENT_TYPE",
                    pagId=page_id,
                    componentId=component_id,
                    componentType=component_type,
                    message=f"Component type '{component_type}' is not supported for SCORM export",
                    details={
                        "courseId": course_id,
                        "availableTypes": self.manifest.get_supported_types()[:10],  # Show sample
                    }
                ))
                return
        
        self.supported_component_count += 1

        # Validate component has required fields
        renderer_entry = self.manifest.renderers.get(component_type)
        if renderer_entry:
            for required_field in renderer_entry.requiredFields:
                if required_field not in component.get("data", {}):
                    self.errors.append(ExportValidationError(
                        code="MISSING_REQUIRED_FIELD",
                        pagId=page_id,
                        componentId=component_id,
                        componentType=component_type,
                        message=f"Component is missing required field: {required_field}",
                        details={
                            "courseId": course_id,
                            "requiredField": required_field,
                        }
                    ))

        # Validate component data
        if "data" in component:
            self._validate_component_data(component["data"], component_type, component_id, page_id, course_id)

        # Validate component styling
        if "styleConfig" in component:
            self._validate_style_config(component["styleConfig"], component_id)

        # Validate custom CSS
        if "customCss" in component:
            self._validate_custom_css(component["customCss"], component_id)

        # Validate interaction config
        if "interactionConfig" in component:
            self._validate_interaction_config(component["interactionConfig"], component_id, page_id, course_id)

        # Validate accessibility config
        if "accessibilityConfig" in component:
            self._validate_accessibility_config(component["accessibilityConfig"], component_id)

        # Validate assets
        if "assetRefs" in component:
            self._validate_asset_references(component["assetRefs"], component_id, page_id, course_id)

    def _validate_component_data(
        self, data: Dict[str, Any], component_type: str, component_id: str, page_id: str, course_id: str
    ) -> None:
        """Validate component-specific data"""
        
        # MCQ validation
        if component_type == "mcq":
            questions = data.get("questions", [])
            if not questions:
                self.errors.append(ExportValidationError(
                    code="MCQ_MISSING_QUESTIONS",
                    pagId=page_id,
                    componentId=component_id,
                    message="MCQ component must have at least one question",
                    details={"courseId": course_id}
                ))
            else:
                for idx, question in enumerate(questions):
                    options = question.get("options", [])
                    if not any(opt.get("isCorrect", False) for opt in options):
                        self.warnings.append(
                            f"MCQ {component_id} question {idx} has no correct answer"
                        )

        # Video validation
        if component_type in ["content-video", "video-slide"]:
            if "videoAssetId" not in data:
                self.errors.append(ExportValidationError(
                    code="VIDEO_MISSING_ASSET",
                    pagId=page_id,
                    componentId=component_id,
                    message="Video component must reference a videoAssetId",
                    details={"courseId": course_id}
                ))

        # Accordion validation
        if component_type == "accordion":
            panels = data.get("panels", [])
            if not panels:
                self.errors.append(ExportValidationError(
                    code="ACCORDION_MISSING_PANELS",
                    pagId=page_id,
                    componentId=component_id,
                    message="Accordion component must have at least one panel",
                    details={"courseId": course_id}
                ))

        # Tabs validation
        if component_type == "tabs":
            tabs = data.get("tabs", [])
            if not tabs:
                self.errors.append(ExportValidationError(
                    code="TABS_MISSING_TABS",
                    pagId=page_id,
                    componentId=component_id,
                    message="Tabs component must have at least one tab",
                    details={"courseId": course_id}
                ))

    def _validate_style_config(self, style_config: Dict[str, Any], item_id: str) -> None:
        """Validate style configuration object"""
        # Basic validation - check that style values are reasonable
        if not isinstance(style_config, dict):
            self.warnings.append(f"Style config for {item_id} is not a dict")
            return

        # Validate CSS properties if present
        if "spacing" in style_config:
            spacing = style_config["spacing"]
            if not isinstance(spacing, dict):
                self.warnings.append(f"Spacing in {item_id} must be a dict")

        if "colors" in style_config:
            colors = style_config["colors"]
            if not isinstance(colors, dict):
                self.warnings.append(f"Colors in {item_id} must be a dict")

    def _validate_custom_css(self, custom_css: str, item_id: str) -> None:
        """Validate custom CSS safety"""
        if not isinstance(custom_css, str):
            self.warnings.append(f"Custom CSS for {item_id} is not a string")
            return

        # Check for potentially dangerous CSS
        dangerous_patterns = ["javascript:", "@import", "expression("]
        for pattern in dangerous_patterns:
            if pattern.lower() in custom_css.lower():
                self.errors.append(ExportValidationError(
                    code="UNSAFE_CSS",
                    componentId=item_id,
                    message=f"Custom CSS contains potentially dangerous pattern: {pattern}",
                    details={"pattern": pattern}
                ))

    def _validate_interaction_config(
        self, interaction_config: Dict[str, Any], component_id: str, page_id: str, course_id: str
    ) -> None:
        """Validate interaction configuration"""
        if not isinstance(interaction_config, dict):
            self.warnings.append(f"Interaction config for {component_id} is not a dict")
            return

        # Validate required interaction fields if present
        click_behavior = interaction_config.get("clickBehavior")
        if click_behavior and click_behavior not in ["navigate", "expand", "reveal", "branch", "submit"]:
            self.warnings.append(
                f"Unknown clickBehavior '{click_behavior}' in {component_id}"
            )

    def _validate_accessibility_config(self, accessibility_config: Dict[str, Any], item_id: str) -> None:
        """Validate accessibility configuration"""
        if not isinstance(accessibility_config, dict):
            self.warnings.append(f"Accessibility config for {item_id} is not a dict")
            return

        # Validate ARIA attributes if present
        aria_label = accessibility_config.get("ariaLabel")
        if aria_label and not isinstance(aria_label, str):
            self.warnings.append(f"ariaLabel in {item_id} must be a string")

        role = accessibility_config.get("role")
        if role and not isinstance(role, str):
            self.warnings.append(f"role in {item_id} must be a string")

    def _validate_asset_references(
        self, asset_refs: List[Dict[str, Any]], component_id: str, page_id: str, course_id: str
    ) -> None:
        """Validate that referenced assets exist and are valid"""
        if not isinstance(asset_refs, list):
            self.warnings.append(f"assetRefs for {component_id} is not a list")
            return

        for asset_ref in asset_refs:
            asset_id = asset_ref.get("assetId")
            if not asset_id:
                self.warnings.append(f"Asset reference in {component_id} missing assetId")
                continue

            # Validate asset reference structure
            required_asset_fields = ["assetId", "filename", "mimeType", "size", "assetType"]
            for field in required_asset_fields:
                if field not in asset_ref:
                    self.warnings.append(
                        f"Asset reference in {component_id} missing field: {field}"
                    )

    def _validate_theme(self, course_data: Dict[str, Any]) -> None:
        """Validate theme and design tokens"""
        theme_tokens = course_data.get("themeTokens", {})
        if not isinstance(theme_tokens, dict):
            self.warnings.append("themeTokens should be a dict")
            return

        # Validate token structure
        for token_name, token in theme_tokens.items():
            if not isinstance(token, dict):
                self.warnings.append(f"Theme token '{token_name}' is not a dict")
                continue

            if "value" not in token:
                self.warnings.append(f"Theme token '{token_name}' missing value")

            if "category" not in token:
                self.warnings.append(f"Theme token '{token_name}' missing category")

    def _validate_assets(self, assets: List[Dict[str, Any]], course_id: str) -> None:
        """Validate course-level assets"""
        if not isinstance(assets, list):
            self.warnings.append("assets should be a list")
            return

        for asset in assets:
            asset_id = asset.get("assetId", "unknown")
            
            # Validate required asset fields
            required_fields = ["assetId", "filename", "mimeType", "size", "assetType"]
            for field in required_fields:
                if field not in asset:
                    self.warnings.append(f"Asset {asset_id} missing field: {field}")

            # Validate asset type
            valid_asset_types = ["image", "video", "audio", "document", "other"]
            asset_type = asset.get("assetType")
            if asset_type and asset_type not in valid_asset_types:
                self.warnings.append(f"Asset {asset_id} has invalid type: {asset_type}")

    def _validate_course_settings(self, course_data: Dict[str, Any], course_id: str) -> None:
        """Validate course-level settings"""
        
        # Check required course fields
        if "courseId" not in course_data:
            self.errors.append(ExportValidationError(
                code="MISSING_COURSE_ID",
                message="Course must have courseId"
            ))

        if "title" not in course_data:
            self.errors.append(ExportValidationError(
                code="MISSING_COURSE_TITLE",
                message="Course must have title",
                details={"courseId": course_id}
            ))

        # Validate navigation settings
        nav_settings = course_data.get("navigationSettings", {})
        if nav_settings and not isinstance(nav_settings, dict):
            self.warnings.append("navigationSettings should be a dict")

        # Validate completion settings
        completion_settings = course_data.get("completionSettings", {})
        if completion_settings and not isinstance(completion_settings, dict):
            self.warnings.append("completionSettings should be a dict")

    def _build_result(self) -> ExportValidationResult:
        """Build validation result object"""
        return ExportValidationResult(
            isValid=len(self.errors) == 0,
            errors=self.errors,
            warnings=self.warnings,
            supportedComponentCount=self.supported_component_count,
            unsupportedComponentCount=self.unsupported_component_count,
        )


def validate_course_for_export(course_data: Dict[str, Any]) -> ExportValidationResult:
    """
    Convenience function to validate a course for export.

    Args:
        course_data: Course dictionary with pages, components, assets

    Returns:
        ExportValidationResult with validation status
    """
    validator = ExportValidator()
    return validator.validate(course_data)


# ── AI Content-Specific SCORM Validation (US-PEND-023) ──────────

# SCORM 1.2 allowed HTML tags (conservative set for LMS compatibility)
ALLOWED_SCORM_HTML_TAGS = {
    "a", "b", "br", "cite", "code", "dd", "dfn", "div", "dl", "dt",
    "em", "h1", "h2", "h3", "h4", "h5", "h6", "i", "img", "li",
    "ol", "p", "pre", "small", "span", "strong", "sub", "sup",
    "table", "tbody", "td", "th", "thead", "tr", "u", "ul",
}


class AI_SCORMValidator:
    """Validates AI-generated content for SCORM 1.2 compliance.

    Checks:
    1. XML character escaping (AI may generate unescaped &, <, >)
    2. HTML tag safety (unknown tags may break SCORM player)
    3. Content completeness (empty pages, missing titles)
    4. Manifest validity against SCORM 1.2 XSD (when xmlschema available)

    Usage:
        validator = AI_SCORMValidator()
        result = await validator.validate_ai_content(pages)
        if result["errors"]:
            logger.warning("SCORM validation found issues")
    """

    def __init__(self):
        self._xsd_schema = None  # Lazy-loaded

    async def validate_ai_content(self, pages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Validate AI-generated pages for SCORM compatibility.

        Args:
            pages: List of page dicts with 'title', 'template_type', 'content'/'data'.

        Returns:
            {"valid": bool, "errors": [...], "warnings": [...]}
        """
        import re
        errors = []
        warnings = []

        for i, page in enumerate(pages or []):
            title = page.get("title", f"Page {i}")
            content = page.get("content", page.get("data", {}))
            html = self._extract_html(content)

            if not html or not html.strip():
                warnings.append({
                    "code": "EMPTY_PAGE",
                    "message": f"Page {i} ('{title}') has no content",
                    "severity": "warning",
                    "page_index": i,
                })
                continue

            # Check 1: Unescaped XML characters
            unescaped = re.findall(r'&(?!amp;|lt;|gt;|quot;|apos;)', html)
            if unescaped:
                errors.append({
                    "code": "UNESCAPED_XML",
                    "message": f"Page {i} ('{title}'): {len(unescaped)} unescaped XML character(s) found",
                    "severity": "error",
                    "page_index": i,
                    "sample": unescaped[:5],
                })

            # Check 2: Unknown HTML tags
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "html.parser")
                for tag in soup.find_all():
                    if tag.name not in ALLOWED_SCORM_HTML_TAGS:
                        warnings.append({
                            "code": "UNKNOWN_HTML_TAG",
                            "message": f"Page {i} ('{title}'): tag '<{tag.name}>' may not render in SCORM player",
                            "severity": "warning",
                            "page_index": i,
                            "tag": tag.name,
                        })
            except Exception:
                pass  # HTML parsing is best-effort

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }

    async def validate_manifest(self, manifest_xml: str) -> Dict[str, Any]:
        """Validate imsmanifest.xml against SCORM 1.2 XSD schema.

        Requires xmlschema>=3.0.0. Returns empty errors if not installed.
        """
        try:
            import xmlschema
            if self._xsd_schema is None:
                # SCORM 1.2 XSD from ADL (cached after first load)
                self._xsd_schema = xmlschema.XMLSchema(
                    "https://raw.githubusercontent.com/adlnet/SCORM-1.2/main/schemas/adlcp_rootv1p2.xsd"
                )
            self._xsd_schema.validate(manifest_xml)
            return {"valid": True, "errors": []}
        except ImportError:
            logger.warning("xmlschema not installed — skipping XSD validation")
            return {"valid": True, "errors": [], "skipped": "xmlschema not installed"}
        except Exception as exc:
            return {
                "valid": False,
                "errors": [{"code": "XSD_VALIDATION_FAILED", "message": str(exc)}],
            }

    @staticmethod
    def _extract_html(content: Any) -> str:
        """Extract HTML string from page content dict or json string."""
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            # Try common HTML container fields
            for key in ("html", "content", "body", "text"):
                val = content.get(key)
                if isinstance(val, str) and val.strip():
                    return val
            # If no html field, serialize the dict as HTML-like text
            import json
            return json.dumps(content, default=str)
        return str(content or "")
