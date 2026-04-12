"""
Canonical Export Data Builder

Transforms course data from database/API into ExportedCourse format.
Registry-driven with zero hardcoded template logic.

Responsibilities:
1. Load course, pages, components from database/input
2. Load persisted theme tokens and style configs
3. Load custom CSS (course, page, component level)
4. Load asset references
5. Build canonical ExportedCourse object

The builder respects the export contract schema exactly,
so output is ready for validation and SCORM packaging.
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
from app.models.export_contract import (
    ExportedCourse,
    ExportedPage,
    ExportedComponent,
    ThemeToken,
    StyleConfig,
    InteractionConfig,
    AccessibilityConfig,
    AssetReference,
)
from app.services.renderer_manifest import get_renderer_manifest

logger = logging.getLogger(__name__)


class ExportDataBuilder:
    """Builds canonical export payload from course data"""

    def __init__(self):
        self.manifest = get_renderer_manifest()

    def build_exported_course(
        self,
        course_data: Dict[str, Any],
        theme_json: Optional[Dict[str, Any]] = None,
        custom_css: Optional[str] = None,
    ) -> ExportedCourse:
        """
        Build canonical ExportedCourse from course data.
        
        Args:
            course_data: Course JSON data with pages/components
            theme_json: Course-level theme tokens/config from database
            custom_css: Course-level custom CSS from database
            
        Returns:
            ExportedCourse ready for validation and packaging
        """
        course_id = course_data.get("courseId", "unknown")
        logger.info(f"Building export data for course {course_id}")

        # Extract basic course info
        title = course_data.get("title", "Untitled Course")
        description = course_data.get("description")
        language = course_data.get("language", "en")

        # Build theme tokens
        theme_tokens = self._build_theme_tokens(theme_json)

        # Build pages
        pages_data = course_data.get("pages", [])
        pages = []
        for page_data in pages_data:
            page = self._build_exported_page(page_data, course_data)
            pages.append(page)

        # Build asset references
        assets = self._build_asset_references(course_data.get("assets", []))

        # Build navigation and completion settings
        nav_settings = course_data.get("navigationSettings", {})
        completion_settings = course_data.get("completionSettings", {})

        # Create exported course
        exported_course = ExportedCourse(
            courseId=course_id,
            title=title,
            description=description,
            language=language,
            themeTokens=theme_tokens,
            customCss=custom_css,
            navigationSettings=nav_settings if nav_settings else None,
            completionSettings=completion_settings if completion_settings else None,
            pages=pages,
            assets=assets,
            exportedAt=datetime.utcnow(),
            exportedBy="backend-export-service",
            supportedComponentTypes=self.manifest.get_supported_types(),
        )

        return exported_course

    def _build_theme_tokens(self, theme_json: Optional[Dict[str, Any]]) -> Dict[str, ThemeToken]:
        """Build theme tokens from persisted theme data"""
        theme_tokens: Dict[str, ThemeToken] = {}

        if not theme_json:
            return theme_tokens

        # Theme JSON structure: can be various formats
        # Try to extract color, typography, spacing tokens
        
        # If it has a "tokens" key
        if "tokens" in theme_json:
            for token_key, token_value in theme_json["tokens"].items():
                theme_tokens[token_key] = ThemeToken(
                    name=token_key,
                    value=str(token_value),
                    category=self._infer_token_category(token_key),
                )

        # If it has direct color keys
        if "colors" in theme_json:
            colors = theme_json["colors"]
            if isinstance(colors, dict):
                for color_key, color_value in colors.items():
                    token_name = f"color-{color_key}"
                    theme_tokens[token_name] = ThemeToken(
                        name=token_name,
                        value=str(color_value),
                        category="color",
                    )

        # If it has typography keys
        if "typography" in theme_json:
            typography = theme_json["typography"]
            if isinstance(typography, dict):
                for typo_key, typo_value in typography.items():
                    token_name = f"typography-{typo_key}"
                    theme_tokens[token_name] = ThemeToken(
                        name=token_name,
                        value=str(typo_value),
                        category="typography",
                    )

        # If it has spacing keys
        if "spacing" in theme_json:
            spacing = theme_json["spacing"]
            if isinstance(spacing, dict):
                for space_key, space_value in spacing.items():
                    token_name = f"spacing-{space_key}"
                    theme_tokens[token_name] = ThemeToken(
                        name=token_name,
                        value=str(space_value),
                        category="spacing",
                    )

        return theme_tokens

    @staticmethod
    def _infer_token_category(token_key: str) -> str:
        """Infer token category from key name"""
        key_lower = token_key.lower()
        
        if any(x in key_lower for x in ["color", "bg", "text"]):
            return "color"
        elif any(x in key_lower for x in ["font", "size", "weight", "typo"]):
            return "typography"
        elif any(x in key_lower for x in ["pad", "margin", "gap", "space"]):
            return "spacing"
        elif any(x in key_lower for x in ["border", "line", "stroke"]):
            return "border"
        elif any(x in key_lower for x in ["shadow", "blur"]):
            return "shadow"
        elif any(x in key_lower for x in ["radius", "round"]):
            return "radius"
        else:
            return "color"  # Default

    def _build_exported_page(
        self, page_data: Dict[str, Any], course_data: Dict[str, Any]
    ) -> ExportedPage:
        """Build ExportedPage from page JSON"""
        page_id = page_data.get("pageId", "unknown")
        title = page_data.get("title", "Untitled Page")
        order = page_data.get("order", 0)

        # Get page-level style config
        style_config = page_data.get("styleConfig")
        custom_css = page_data.get("customCss")

        # Build components
        components_data = page_data.get("components", [])
        components = []
        for component_data in components_data:
            component = self._build_exported_component(component_data, page_id)
            components.append(component)

        # Create exported page
        exported_page = ExportedPage(
            pageId=page_id,
            title=title,
            order=order,
            layoutConfig=page_data.get("layoutConfig"),
            styleConfig=self._build_style_config(style_config),
            customCss=custom_css,
            components=components,
        )

        return exported_page

    def _build_exported_component(
        self, component_data: Dict[str, Any], page_id: str
    ) -> ExportedComponent:
        """Build ExportedComponent from component JSON"""
        
        component_id = component_data.get("componentId", "unknown")
        component_type = component_data.get("componentType", "content-text")
        title = component_data.get("title", "")
        order = component_data.get("order", 0)
        data = component_data.get("data", {})

        # Build style config
        style_config = component_data.get("styleConfig")
        
        # Build interaction config
        interaction_config = component_data.get("interactionConfig")
        
        # Build accessibility config
        accessibility_config = component_data.get("accessibilityConfig")

        # Get custom CSS
        custom_css = component_data.get("customCss")

        # Build asset references
        asset_refs = self._build_asset_references(
            component_data.get("assetRefs", [])
        )

        # Create exported component
        exported_component = ExportedComponent(
            componentId=component_id,
            componentType=component_type,
            pageId=page_id,
            title=title,
            order=order,
            data=data,
            styleConfig=self._build_style_config(style_config),
            customCss=custom_css,
            interactionConfig=self._build_interaction_config(interaction_config),
            accessibilityConfig=self._build_accessibility_config(accessibility_config),
            assetRefs=asset_refs if asset_refs else None,
            exportMetadata=component_data.get("exportMetadata", {}),
        )

        return exported_component

    @staticmethod
    def _build_style_config(style_data: Optional[Dict[str, Any]]) -> Optional[StyleConfig]:
        """Build StyleConfig from style data"""
        if not style_data or not isinstance(style_data, dict):
            return None

        return StyleConfig(
            layoutVariant=style_data.get("layoutVariant"),
            spacing=style_data.get("spacing"),
            typography=style_data.get("typography"),
            colors=style_data.get("colors"),
            borders=style_data.get("borders"),
            shadows=style_data.get("shadows"),
            visibility=style_data.get("visibility"),
            responsiveBreakpoints=style_data.get("responsiveBreakpoints"),
        )

    @staticmethod
    def _build_interaction_config(
        interaction_data: Optional[Dict[str, Any]],
    ) -> Optional[InteractionConfig]:
        """Build InteractionConfig from interaction data"""
        if not interaction_data or not isinstance(interaction_data, dict):
            return None

        return InteractionConfig(
            isInteractive=interaction_data.get("isInteractive", True),
            clickBehavior=interaction_data.get("clickBehavior"),
            allowMultiselect=interaction_data.get("allowMultiselect"),
            revealStrategy=interaction_data.get("revealStrategy"),
            feedbackConfig=interaction_data.get("feedbackConfig"),
            navigationConfig=interaction_data.get("navigationConfig"),
            branchingConfig=interaction_data.get("branchingConfig"),
        )

    @staticmethod
    def _build_accessibility_config(
        accessibility_data: Optional[Dict[str, Any]],
    ) -> Optional[AccessibilityConfig]:
        """Build AccessibilityConfig from accessibility data"""
        if not accessibility_data or not isinstance(accessibility_data, dict):
            return None

        return AccessibilityConfig(
            ariaLabel=accessibility_data.get("ariaLabel"),
            ariaDescribedBy=accessibility_data.get("ariaDescribedBy"),
            role=accessibility_data.get("role"),
            altText=accessibility_data.get("altText"),
            keyboardShortcuts=accessibility_data.get("keyboardShortcuts"),
            focusOrder=accessibility_data.get("focusOrder"),
        )

    @staticmethod
    def _build_asset_references(assets_data: List[Any]) -> Optional[List[AssetReference]]:
        """Build AssetReference list from assets data"""
        if not assets_data or not isinstance(assets_data, list):
            return None

        asset_refs: List[AssetReference] = []
        
        for asset in assets_data:
            if not isinstance(asset, dict):
                logger.warning(f"Asset is not a dict: {asset}")
                continue

            asset_id = asset.get("assetId")
            filename = asset.get("filename")
            mime_type = asset.get("mimeType")
            size = asset.get("size", 0)
            asset_type = asset.get("assetType", "other")

            if not asset_id or not filename:
                logger.warning(f"Asset missing required fields: {asset}")
                continue

            asset_ref = AssetReference(
                assetId=asset_id,
                filename=filename,
                mimeType=mime_type,
                size=int(size) if size else 0,
                assetType=asset_type,
            )
            asset_refs.append(asset_ref)

        return asset_refs if asset_refs else None


def build_exported_course(
    course_data: Dict[str, Any],
    theme_json: Optional[Dict[str, Any]] = None,
    custom_css: Optional[str] = None,
) -> ExportedCourse:
    """
    Convenience function to build ExportedCourse.
    
    Args:
        course_data: Course JSON with pages and components
        theme_json: Optional theme tokens from database
        custom_css: Optional course-level custom CSS
        
    Returns:
        ExportedCourse ready for validation and export
    """
    builder = ExportDataBuilder()
    return builder.build_exported_course(course_data, theme_json, custom_css)
