"""
Export Payload Contract Models

Defines the canonical data contract for SCORM export.
This schema is used by both backend export pipeline and frontend SCORM runtime.
All exported components must conform to this contract for registry-driven rendering.

Key principles:
1. Single canonical shape for all 84 template types
2. All render-relevant data must be present: styling, theming, interactions
3. No data transformation on export — preserve as-is from database
4. Frontend runtime uses this same contract for rendering
5. Validation ensures only exportable-supported components are included
"""

from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field
from datetime import datetime


# ── Theme and Style Contracts ──────────────────────────────────────────────

class ThemeToken(BaseModel):
    """A single design token (color, spacing, typography, etc.)"""
    name: str = Field(..., description="Token name, e.g., 'primary-color', 'spacing-md'")
    value: str = Field(..., description="Token value, e.g., '#003366', '16px'")
    category: Literal["color", "spacing", "typography", "border", "shadow", "radius"] = Field(
        ..., description="Token category for organization"
    )


class StyleConfig(BaseModel):
    """Component or page-level style configuration"""
    layoutVariant: Optional[str] = Field(None, description="Layout variant name, e.g., 'card', 'grid', 'grid-3col'")
    spacing: Optional[Dict[str, str]] = Field(None, description="Spacing overrides: {'padding': '20px', 'margin': '10px 0'}")
    typography: Optional[Dict[str, str]] = Field(None, description="Typography overrides: {'fontSize': '18px', 'fontWeight': 'bold'}")
    colors: Optional[Dict[str, str]] = Field(None, description="Color overrides: {'background': '#f5f5f5', 'text': '#333'}")
    borders: Optional[Dict[str, str]] = Field(None, description="Border config: {'width': '1px', 'color': '#ccc', 'radius': '4px'}")
    shadows: Optional[Dict[str, str]] = Field(None, description="Shadow config: {'box': '0 2px 4px rgba(0,0,0,0.1)'}")
    visibility: Optional[Dict[str, bool]] = Field(None, description="Visibility toggles: {'showTitle': True, 'showCode': False}")
    responsiveBreakpoints: Optional[Dict[str, Dict[str, Any]]] = Field(
        None, description="Responsive overrides by breakpoint: {'mobile': {...}, 'tablet': {...}}"
    )


class InteractionConfig(BaseModel):
    """Interaction and behavioral configuration for components"""
    isInteractive: bool = Field(default=True, description="Whether component responds to user interaction")
    clickBehavior: Optional[Literal["navigate", "expand", "reveal", "branch", "submit"]] = Field(
        None, description="Primary click behavior"
    )
    allowMultiselect: Optional[bool] = Field(None, description="For choice-based interactions, allow multi-select")
    revealStrategy: Optional[Literal["all", "progressive", "on-demand"]] = Field(
        None, description="Content reveal strategy"
    )
    feedbackConfig: Optional[Dict[str, Any]] = Field(None, description="Feedback for correct/incorrect answers")
    navigationConfig: Optional[Dict[str, Any]] = Field(None, description="Navigation overrides")
    branchingConfig: Optional[Dict[str, Any]] = Field(None, description="Branching logic if applicable")


class AccessibilityConfig(BaseModel):
    """Accessibility configuration"""
    ariaLabel: Optional[str] = Field(None, description="ARIA label for screen readers")
    ariaDescribedBy: Optional[str] = Field(None, description="ARIA described-by for long descriptions")
    role: Optional[str] = Field(None, description="ARIA role override")
    altText: Optional[str] = Field(None, description="Alt text for images")
    keyboardShortcuts: Optional[Dict[str, str]] = Field(None, description="Custom keyboard shortcuts")
    focusOrder: Optional[int] = Field(None, description="Custom focus order")


class AssetReference(BaseModel):
    """Reference to an exported asset"""
    assetId: str = Field(..., description="Unique asset identifier")
    filename: str = Field(..., description="Filename in export ZIP")
    mimeType: str = Field(..., description="MIME type")
    size: int = Field(..., description="File size in bytes")
    assetType: Literal["image", "video", "audio", "document", "other"] = Field(..., description="Asset category")


# ── Component and Page Contracts ───────────────────────────────────────────

class ExportedComponent(BaseModel):
    """Canonical export contract for a single component"""
    
    # Core identification
    componentId: str = Field(..., description="Unique component ID within course")
    componentType: str = Field(..., description="Template type ID, e.g., 'accordion', 'tabs', 'mcq'")
    pageId: str = Field(..., description="Page ID this component belongs to")
    
    # Metadata
    title: str = Field(..., description="Display title")
    order: int = Field(..., ge=0, description="Display order on page")
    
    # Content data (schema varies by componentType)
    data: Dict[str, Any] = Field(..., description="Component-specific content data")
    
    # Styling and theming
    styleConfig: Optional[StyleConfig] = Field(None, description="Component-level style overrides")
    customCss: Optional[str] = Field(None, description="Component-scoped custom CSS")
    
    # Interactions
    interactionConfig: Optional[InteractionConfig] = Field(None, description="Interaction settings")
    
    # Accessibility
    accessibilityConfig: Optional[AccessibilityConfig] = Field(None, description="Accessibility settings")
    
    # Assets
    assetRefs: Optional[List[AssetReference]] = Field(None, description="References to assets used in this component")
    
    # Metadata for export runtime
    exportMetadata: Optional[Dict[str, Any]] = Field(None, description="Runtime-relevant metadata")


class ExportedPage(BaseModel):
    """Canonical export contract for a page/slide"""
    
    # Core identification
    pageId: str = Field(..., description="Unique page ID")
    title: str = Field(..., description="Page title")
    order: int = Field(..., ge=0, description="Page order in course")
    
    # Layout and styling
    layoutConfig: Optional[Dict[str, Any]] = Field(None, description="Page layout configuration")
    styleConfig: Optional[StyleConfig] = Field(None, description="Page-level style overrides")
    customCss: Optional[str] = Field(None, description="Page-scoped custom CSS")
    
    # Components on page
    components: List[ExportedComponent] = Field(..., description="All components on this page")


class ExportedCourse(BaseModel):
    """Canonical export contract for the entire course"""
    
    # Core metadata
    courseId: str = Field(..., description="Unique course ID")
    title: str = Field(..., description="Course title")
    description: Optional[str] = Field(None, description="Course description")
    language: str = Field(default="en", description="Course language code")
    
    # Theme and styling
    themeTokens: Dict[str, ThemeToken] = Field(default_factory=dict, description="Design tokens for theme system")
    customCss: Optional[str] = Field(None, description="Course-wide custom CSS")
    
    # Course-level settings
    navigationSettings: Optional[Dict[str, Any]] = Field(None, description="Navigation and UX settings")
    completionSettings: Optional[Dict[str, Any]] = Field(None, description="Completion and scoring settings")
    
    # Pages and content
    pages: List[ExportedPage] = Field(..., min_items=1, description="All pages in course")
    
    # Assets
    assets: Optional[List[AssetReference]] = Field(None, description="All assets used in course")
    
    # Export metadata
    exportVersion: str = Field(default="1.0", description="Export schema version")
    exportedAt: datetime = Field(..., description="When this was exported")
    exportedBy: Optional[str] = Field(None, description="User/system that performed export")
    
    # Renderer capability hints
    supportedComponentTypes: List[str] = Field(
        ..., description="List of componentTypes the runtime can render. Used for validation."
    )


# ── Validation and Helpers ─────────────────────────────────────────────────

class ExportValidationError(BaseModel):
    """Structure for export validation errors"""
    code: str = Field(..., description="Error code, e.g., 'UNSUPPORTED_COMPONENT_TYPE'")
    pagId: Optional[str] = Field(None, description="Page ID if error is page-related")
    componentId: Optional[str] = Field(None, description="Component ID if error is component-related")
    componentType: Optional[str] = Field(None, description="Component type that failed validation")
    message: str = Field(..., description="Human-readable error message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error details")


class ExportValidationResult(BaseModel):
    """Result of export validation"""
    isValid: bool = Field(..., description="Whether export is valid")
    errors: List[ExportValidationError] = Field(default_factory=list, description="List of validation errors")
    warnings: List[str] = Field(default_factory=list, description="List of warnings")
    supportedComponentCount: int = Field(default=0, description="Number of supported components")
    unsupportedComponentCount: int = Field(default=0, description="Number of unsupported components")


# ── Manifest Contract ──────────────────────────────────────────────────────

class RendererCapabilities(BaseModel):
    """Declares what a renderer can do"""
    supportsInteraction: bool = Field(default=False, description="Can handle interactivity")
    supportsBranching: bool = Field(default=False, description="Can handle branching logic")
    supportsScoring: bool = Field(default=False, description="Can compute scores")
    supportsCustomCss: bool = Field(default=False, description="Can apply scoped custom CSS")
    supportsRichHtml: bool = Field(default=False, description="Can render rich HTML content")
    supportsResponsive: bool = Field(default=False, description="Can handle responsive layouts")


class RendererManifestEntry(BaseModel):
    """Entry in the renderer support manifest"""
    componentType: str = Field(..., description="Component type ID, e.g., 'accordion'")
    displayName: str = Field(..., description="Human-readable name")
    category: str = Field(..., description="Category, e.g., 'presentation', 'assessment'")
    capabilities: RendererCapabilities = Field(..., description="What this renderer can do")
    requiredFields: List[str] = Field(default_factory=list, description="Required data fields")
    optionalFields: List[str] = Field(default_factory=list, description="Optional data fields")
    isExportable: bool = Field(default=True, description="Whether this can be exported")
    fallbackComponent: Optional[str] = Field(None, description="Fallback component if not supported")


class RendererManifest(BaseModel):
    """Machine-readable manifest of all supported renderers"""
    version: str = Field(default="1.0", description="Manifest version")
    lastUpdated: datetime = Field(..., description="When manifest was updated")
    renderers: Dict[str, RendererManifestEntry] = Field(..., description="Map of componentType -> capabilities")
    
    def get_supported_types(self) -> List[str]:
        """Get list of exportable component types"""
        return [
            comp_type for comp_type, entry in self.renderers.items()
            if entry.isExportable
        ]
    
    def is_supported(self, component_type: str) -> bool:
        """Check if a component type is supported and exportable"""
        entry = self.renderers.get(component_type)
        return entry is not None and entry.isExportable
    
    def get_fallback(self, component_type: str) -> Optional[str]:
        """Get fallback component for unsupported type"""
        entry = self.renderers.get(component_type)
        return entry.fallbackComponent if entry else None
