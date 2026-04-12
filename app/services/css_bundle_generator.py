"""
CSS Bundle Generator

Generates a single, syntactically-valid CSS bundle from:
1. Base SCORM runtime CSS
2. Theme tokens (as CSS variables)
3. Page-level style configurations
4. Component-level custom CSS (scoped)
5. Responsive breakpoints

Output is a single styles.css file ready for inclusion in SCORM ZIP.
No hardcoded component logic, fully registry-driven.
"""

import logging
import re
from typing import Dict, List, Any, Optional, Tuple
from app.models.export_contract import (
    ExportedCourse,
    ThemeToken,
    StyleConfig,
)

logger = logging.getLogger(__name__)


class CSSBundleGenerator:
    """Generates CSS bundles for SCORM export"""

    def __init__(self):
        self.valid_css_properties = self._build_valid_properties_set()

    @staticmethod
    def _build_valid_properties_set() -> set:
        """Build set of valid CSS properties for validation"""
        # Common CSS properties that are exportable
        return {
            # Layout
            "display", "position", "top", "right", "bottom", "left",
            "width", "height", "max-width", "min-width", "max-height", "min-height",
            "flex", "flex-direction", "flex-wrap", "justify-content", "align-items", "gap",
            "grid", "grid-template-columns", "grid-template-rows", "grid-gap",
            
            # Box model
            "margin", "margin-top", "margin-right", "margin-bottom", "margin-left",
            "padding", "padding-top", "padding-right", "padding-bottom", "padding-left",
            "border", "border-top", "border-right", "border-bottom", "border-left",
            "border-width", "border-color", "border-style", "border-radius",
            
            # Background
            "background", "background-color", "background-image", "background-size",
            "background-position", "background-repeat", "background-attachment",
            
            # Text
            "color", "font-family", "font-size", "font-weight", "font-style",
            "line-height", "text-align", "text-decoration", "text-transform",
            "text-indent", "letter-spacing", "word-spacing", "white-space",
            
            # Visibility
            "opacity", "visibility", "overflow", "overflow-x", "overflow-y",
            "z-index", "clip-path",
            
            # Effects
            "box-shadow", "text-shadow", "filter", "transform", "transition",
            "animation",
            
            # Other
            "cursor", "pointer-events", "user-select", "outline", "box-sizing",
        }

    def generate_css_bundle(self, course: ExportedCourse) -> str:
        """
        Generate complete CSS bundle for SCORM export.
        
        Args:
            course: ExportedCourse with all styling data
            
        Returns:
            Complete CSS string ready for export
        """
        logger.info(f"Generating CSS bundle for course {course.courseId}")
        
        css_parts: List[str] = []
        
        # 1. Base SCORM runtime CSS
        css_parts.append(self._generate_base_css())
        
        # 2. CSS variables from theme tokens
        css_parts.append(self._generate_theme_variables(course.themeTokens))
        
        # 3. Course-level styles
        if course.customCss:
            css_parts.append(self._scope_custom_css(course.customCss, ".scorm-course"))
        
        # 4. Page and component level styles
        css_parts.extend(self._generate_page_component_css(course))
        
        # 5. Responsive utilities
        css_parts.append(self._generate_responsive_css())
        
        # Combine all parts
        full_css = "\n\n".join(css_parts)
        
        # Validate syntax
        if not self._validate_css_syntax(full_css):
            logger.warning(f"CSS bundle for course {course.courseId} may have syntax issues")
        
        return full_css

    @staticmethod
    def _generate_base_css() -> str:
        """Generate base SCORM runtime CSS"""
        return """
/* ── SCORM Export Runtime Base Styles ────────────────────────────────────── */

* {
    box-sizing: border-box;
}

html, body {
    margin: 0;
    padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    font-size: 16px;
    line-height: 1.5;
    color: #333;
}

body {
    background-color: #fff;
}

.scorm-course {
    width: 100%;
    max-width: 1200px;
    margin: 0 auto;
    padding: 20px;
}

.scorm-page {
    margin-bottom: 40px;
}

.page-title {
    font-size: 2rem;
    font-weight: 600;
    margin-bottom: 20px;
    color: inherit;
}

.page-content {
    display: flex;
    flex-direction: column;
    gap: 20px;
}

.scorm-component {
    margin-bottom: 20px;
}

.component-title {
    font-size: 1.25rem;
    font-weight: 600;
    margin-bottom: 12px;
}

/* ── Utility Classes ───────────────────────────────────────────────────────── */

.text-center {
    text-align: center;
}

.text-left {
    text-align: left;
}

.text-right {
    text-align: right;
}

.mt-0 { margin-top: 0; }
.mt-1 { margin-top: 4px; }
.mt-2 { margin-top: 8px; }
.mt-3 { margin-top: 12px; }
.mt-4 { margin-top: 16px; }
.mt-5 { margin-top: 20px; }

.mb-0 { margin-bottom: 0; }
.mb-1 { margin-bottom: 4px; }
.mb-2 { margin-bottom: 8px; }
.mb-3 { margin-bottom: 12px; }
.mb-4 { margin-bottom: 16px; }
.mb-5 { margin-bottom: 20px; }

.p-1 { padding: 4px; }
.p-2 { padding: 8px; }
.p-3 { padding: 12px; }
.p-4 { padding: 16px; }
.p-5 { padding: 20px; }

.hidden {
    display: none !important;
}

.visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border-width: 0;
}
"""

    @staticmethod
    def _generate_theme_variables(theme_tokens: Dict[str, ThemeToken]) -> str:
        """Generate CSS variables from theme tokens"""
        if not theme_tokens:
            return "/* No theme tokens */\n"
        
        css_lines = ["/* ── Theme Tokens (CSS Variables) ──────────────────────────────────────── */\n"]
        css_lines.append(":root {")
        
        for token_name, token in theme_tokens.items():
            # Sanitize token name for CSS variable
            safe_name = token_name.replace(" ", "-").lower()
            css_lines.append(f"  --{safe_name}: {token.value};")
        
        css_lines.append("}\n")
        
        return "\n".join(css_lines)

    def _generate_page_component_css(self, course: ExportedCourse) -> List[str]:
        """Generate CSS for all pages and components"""
        css_parts: List[str] = []
        
        css_parts.append("/* ── Page & Component Styles ──────────────────────────────────────────── */\n")
        
        for page in course.pages:
            # Page-level CSS
            page_selector = f'[data-page="{page.pageId}"]'
            
            if page.styleConfig:
                page_css = self._generate_style_config_css(page.styleConfig, page_selector)
                if page_css:
                    css_parts.append(page_css)
            
            if page.customCss:
                scoped_css = self._scope_custom_css(page.customCss, page_selector)
                css_parts.append(scoped_css)
            
            # Component-level CSS
            for component in page.components:
                component_selector = f'[data-component="{component.componentId}"]'
                
                if component.styleConfig:
                    comp_css = self._generate_style_config_css(
                        component.styleConfig, component_selector
                    )
                    if comp_css:
                        css_parts.append(comp_css)
                
                if component.customCss:
                    scoped_css = self._scope_custom_css(component.customCss, component_selector)
                    css_parts.append(scoped_css)
        
        return css_parts

    def _generate_style_config_css(self, style_config: StyleConfig, selector: str) -> str:
        """Generate CSS from StyleConfig object"""
        if not style_config:
            return ""
        
        css_lines = []
        css_lines.append(f"{selector} {{")
        
        # Layout variant
        if style_config.layoutVariant:
            layout_class = f".layout-{style_config.layoutVariant}"
            css_lines.append(f"  /* Layout variant: {style_config.layoutVariant} */")
        
        # Spacing
        if style_config.spacing:
            css_lines.extend(self._dict_to_css_properties(style_config.spacing, indent=2))
        
        # Typography
        if style_config.typography:
            css_lines.extend(self._dict_to_css_properties(style_config.typography, indent=2))
        
        # Colors
        if style_config.colors:
            css_lines.extend(self._dict_to_css_properties(style_config.colors, indent=2))
        
        # Borders
        if style_config.borders:
            css_lines.extend(self._dict_to_css_properties(style_config.borders, indent=2))
        
        # Shadows
        if style_config.shadows:
            css_lines.extend(self._dict_to_css_properties(style_config.shadows, indent=2))
        
        # Visibility
        if style_config.visibility:
            for key, value in style_config.visibility.items():
                display = "block" if value else "none"
                css_lines.append(f"  /* {key}: {value} */")
        
        css_lines.append("}")
        
        # Responsive breakpoints
        if style_config.responsiveBreakpoints:
            for breakpoint, breakpoint_style in style_config.responsiveBreakpoints.items():
                css_lines.extend(
                    self._generate_responsive_block(selector, breakpoint, breakpoint_style)
                )
        
        return "\n".join(css_lines)

    @staticmethod
    def _dict_to_css_properties(style_dict: Dict[str, Any], indent: int = 0) -> List[str]:
        """Convert dict to CSS property lines"""
        lines = []
        indent_str = " " * indent
        
        for key, value in style_dict.items():
            if value is None or value == "":
                continue
            
            # Convert camelCase to kebab-case
            css_key = re.sub(r'(?<!^)(?=[A-Z])', '-', key).lower()
            
            # Ensure value has proper units if needed
            if isinstance(value, (int, float)) and css_key not in ["opacity", "z-index"]:
                value = f"{value}px"
            
            lines.append(f"{indent_str}{css_key}: {value};")
        
        return lines

    @staticmethod
    def _scope_custom_css(custom_css: str, selector: str) -> str:
        """Scope custom CSS to a selector"""
        # Simple scoping: wrap in the selector
        # This is not perfect but prevents global pollution
        
        # Extract rules from custom CSS
        rules = re.split(r'}\s*', custom_css.strip())
        
        scoped_lines = []
        for rule in rules:
            if not rule.strip():
                continue
            
            # Check if rule is already scoped
            if "{" in rule:
                parts = rule.split("{", 1)
                sel = parts[0].strip()
                content = parts[1].strip()
                
                # Scope selector
                if sel.startswith("@"):  # Media queries, etc.
                    scoped_lines.append(f"{rule}}} ")
                else:
                    # Scope to parent
                    scoped_selector = f"{selector} {sel}"
                    scoped_lines.append(f"{scoped_selector} {{ {content} }}")
            else:
                # Just content, wrap in selector
                scoped_lines.append(f"{selector} {{ {rule} }}")
        
        return "\n".join(scoped_lines)

    @staticmethod
    def _generate_responsive_css() -> str:
        """Generate responsive utility CSS"""
        return """
/* ── Responsive Breakpoints ────────────────────────────────────────────────── */

@media (max-width: 768px) {
    .scorm-course {
        padding: 12px;
    }

    .page-title {
        font-size: 1.5rem;
    }

    .component-title {
        font-size: 1.1rem;
    }
}

@media (max-width: 480px) {
    .scorm-course {
        padding: 8px;
    }

    .page-title {
        font-size: 1.25rem;
    }

    .component-title {
        font-size: 1rem;
    }
}

/* ── Accessibility ────────────────────────────────────────────────────────── */

@media (prefers-reduced-motion: reduce) {
    *,
    *::before,
    *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
    }
}

@media (prefers-color-scheme: dark) {
    body {
        background-color: #1a1a1a;
        color: #e0e0e0;
    }

    .scorm-course {
        background-color: #0d0d0d;
    }
}
"""

    @staticmethod
    def _generate_responsive_block(
        selector: str, breakpoint: str, breakpoint_style: Dict[str, Any]
    ) -> List[str]:
        """Generate responsive media query block"""
        lines = []
        
        # Map breakpoint names to widths
        breakpoint_map = {
            "mobile": "(max-width: 480px)",
            "tablet": "(max-width: 768px)",
            "desktop": "(min-width: 769px)",
            "large": "(min-width: 1024px)",
        }
        
        media_width = breakpoint_map.get(breakpoint, breakpoint)
        
        lines.append(f"\n@media {media_width} {{")
        lines.append(f"  {selector} {{")
        
        # Add properties
        for key, value in breakpoint_style.items():
            css_key = re.sub(r'(?<!^)(?=[A-Z])', '-', key).lower()
            if isinstance(value, (int, float)):
                value = f"{value}px"
            lines.append(f"    {css_key}: {value};")
        
        lines.append("  }")
        lines.append("}")
        
        return lines

    @staticmethod
    def _validate_css_syntax(css_content: str) -> bool:
        """Basic CSS syntax validation"""
        # Check for matching braces
        open_count = css_content.count("{")
        close_count = css_content.count("}")
        
        if open_count != close_count:
            logger.warning(f"CSS brace mismatch: {open_count} open, {close_count} close")
            return False
        
        # Check for common issues
        if "{{" in css_content:
            logger.warning("CSS contains double opening braces {{")
            return False
        
        if "}}" in css_content:
            logger.warning("CSS contains double closing braces }}")
            return False
        
        return True


def generate_css_bundle(course: ExportedCourse) -> str:
    """
    Convenience function to generate CSS bundle.
    
    Args:
        course: ExportedCourse with all styling data
        
    Returns:
        Complete CSS string for export
    """
    generator = CSSBundleGenerator()
    return generator.generate_css_bundle(course)
