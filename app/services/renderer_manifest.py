"""
Renderer Support Manifest

Machine-readable registry of all 84 active template types and their
export/rendering capabilities. This manifest is the source of truth for:

1. Export validation (backend checks if component can be exported)
2. Renderer resolution (frontend looks up which component to render)
3. Fallback strategies (what to use if component not supported)
4. Capability queries (what can this component do?)

The manifest is organized by category to match the template picker UI
and the database schema.
"""

from app.models.export_contract import (
    RendererManifest,
    RendererManifestEntry,
    RendererCapabilities,
)
from datetime import datetime
from typing import Dict


def _category_presentation() -> Dict[str, RendererManifestEntry]:
    """Presentation & content display components"""
    return {
        "content-text": RendererManifestEntry(
            componentType="content-text",
            displayName="Text Content",
            category="presentation",
            capabilities=RendererCapabilities(
                supportsInteraction=False,
                supportsCustomCss=True,
                supportsRichHtml=True,
                supportsResponsive=True,
            ),
            requiredFields=["content"],
            optionalFields=["subtitle", "title"],
            isExportable=True,
        ),
        "content-media": RendererManifestEntry(
            componentType="content-media",
            displayName="Media Content",
            category="presentation",
            capabilities=RendererCapabilities(
                supportsInteraction=False,
                supportsCustomCss=True,
                supportsResponsive=True,
            ),
            requiredFields=["mediaAssetId"],
            optionalFields=["caption", "altText"],
            isExportable=True,
        ),
        "content-image": RendererManifestEntry(
            componentType="content-image",
            displayName="Image Gallery",
            category="presentation",
            capabilities=RendererCapabilities(
                supportsCustomCss=True,
                supportsResponsive=True,
            ),
            requiredFields=["imageAssetIds"],
            optionalFields=["layout", "captions"],
            isExportable=True,
        ),
        "content-video": RendererManifestEntry(
            componentType="content-video",
            displayName="Video Slide",
            category="presentation",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsCustomCss=True,
                supportsResponsive=True,
            ),
            requiredFields=["videoAssetId"],
            optionalFields=["autoplay", "controls", "caption", "transcript"],
            isExportable=True,
        ),
        "transcript-caption": RendererManifestEntry(
            componentType="transcript-caption",
            displayName="Video Transcript & Captions",
            category="presentation",
            capabilities=RendererCapabilities(
                supportsCustomCss=True,
            ),
            requiredFields=["transcriptText"],
            optionalFields=["captions", "language", "timestamps"],
            isExportable=True,
        ),
        "rich-text-editor": RendererManifestEntry(
            componentType="rich-text-editor",
            displayName="Rich Text Block",
            category="presentation",
            capabilities=RendererCapabilities(
                supportsCustomCss=True,
                supportsRichHtml=True,
            ),
            requiredFields=["htmlContent"],
            optionalFields=["style"],
            isExportable=True,
        ),
        "quotation": RendererManifestEntry(
            componentType="quotation",
            displayName="Quotation",
            category="presentation",
            capabilities=RendererCapabilities(
                supportsCustomCss=True,
            ),
            requiredFields=["quoteText", "author"],
            optionalFields=["source", "emphasis"],
            isExportable=True,
        ),
        "infographic": RendererManifestEntry(
            componentType="infographic",
            displayName="Infographic",
            category="presentation",
            capabilities=RendererCapabilities(
                supportsResponsive=True,
                supportsCustomCss=True,
            ),
            requiredFields=["imageAssetId"],
            optionalFields=["layout", "annotations"],
            isExportable=True,
        ),
    }


def _category_navigation() -> Dict[str, RendererManifestEntry]:
    """Navigation & layout components"""
    return {
        "tabs": RendererManifestEntry(
            componentType="tabs",
            displayName="Tabbed Content",
            category="navigation",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsCustomCss=True,
                supportsResponsive=True,
            ),
            requiredFields=["tabs"],
            optionalFields=["defaultTab", "style"],
            isExportable=True,
        ),
        "accordion": RendererManifestEntry(
            componentType="accordion",
            displayName="Accordion / Collapsible Sections",
            category="navigation",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsCustomCss=True,
                supportsResponsive=True,
            ),
            requiredFields=["panels"],
            optionalFields=["allowMultiple", "defaultExpanded"],
            isExportable=True,
        ),
        "course-menu": RendererManifestEntry(
            componentType="course-menu",
            displayName="Course Menu / Navigation",
            category="navigation",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsCustomCss=True,
            ),
            requiredFields=["menuItems"],
            optionalFields=["layout", "searchable"],
            isExportable=True,
        ),
        "breadcrumb": RendererManifestEntry(
            componentType="breadcrumb",
            displayName="Breadcrumb Navigation",
            category="navigation",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsCustomCss=True,
            ),
            requiredFields=["paths"],
            optionalFields=[],
            isExportable=True,
        ),
        "stepper": RendererManifestEntry(
            componentType="stepper",
            displayName="Step-by-Step Process",
            category="navigation",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsCustomCss=True,
            ),
            requiredFields=["steps"],
            optionalFields=["orientation", "editable"],
            isExportable=True,
        ),
        "sidebar-navigation": RendererManifestEntry(
            componentType="sidebar-navigation",
            displayName="Sidebar Menu",
            category="navigation",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsCustomCss=True,
            ),
            requiredFields=["items"],
            optionalFields=["collapsible", "activeIndicator"],
            isExportable=True,
        ),
        "timeline": RendererManifestEntry(
            componentType="timeline",
            displayName="Timeline / Event History",
            category="navigation",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsCustomCss=True,
                supportsResponsive=True,
            ),
            requiredFields=["events"],
            optionalFields=["orientation", "interactive"],
            isExportable=True,
        ),
    }


def _category_assessment() -> Dict[str, RendererManifestEntry]:
    """Assessment & question components"""
    return {
        "mcq": RendererManifestEntry(
            componentType="mcq",
            displayName="Multiple Choice Question",
            category="assessment",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsScoring=True,
                supportsCustomCss=True,
            ),
            requiredFields=["questions", "options"],
            optionalFields=["feedback", "passScore"],
            isExportable=True,
        ),
        "multiple-select": RendererManifestEntry(
            componentType="multiple-select",
            displayName="Multiple Select Question",
            category="assessment",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsScoring=True,
                supportsCustomCss=True,
            ),
            requiredFields=["questions", "options"],
            optionalFields=["feedback", "minSelect", "maxSelect"],
            isExportable=True,
        ),
        "true-false": RendererManifestEntry(
            componentType="true-false",
            displayName="True/False Question",
            category="assessment",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsScoring=True,
                supportsCustomCss=True,
            ),
            requiredFields=["questions", "correctAnswer"],
            optionalFields=["feedback", "explanation"],
            isExportable=True,
        ),
        "matching": RendererManifestEntry(
            componentType="matching",
            displayName="Matching Question",
            category="assessment",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsScoring=True,
                supportsCustomCss=True,
            ),
            requiredFields=["leftItems", "rightItems"],
            optionalFields=["feedback"],
            isExportable=True,
        ),
        "drag-and-drop": RendererManifestEntry(
            componentType="drag-and-drop",
            displayName="Drag & Drop Practice",
            category="assessment",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsScoring=True,
                supportsCustomCss=True,
            ),
            requiredFields=["dragItems", "dropZones"],
            optionalFields=["feedback", "snapToGrid"],
            isExportable=True,
        ),
        "fill-in-blank": RendererManifestEntry(
            componentType="fill-in-blank",
            displayName="Fill in the Blank",
            category="assessment",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsScoring=True,
                supportsCustomCss=True,
            ),
            requiredFields=["question", "correctAnswers"],
            optionalFields=["feedback", "caseSensitive"],
            isExportable=True,
        ),
        "hotspot": RendererManifestEntry(
            componentType="hotspot",
            displayName="Image Hotspots",
            category="assessment",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsScoring=True,
                supportsCustomCss=True,
            ),
            requiredFields=["imageAssetId", "hotspots"],
            optionalFields=["feedback"],
            isExportable=True,
        ),
        "image-hotspots": RendererManifestEntry(
            componentType="image-hotspots",
            displayName="Interactive Image Map",
            category="assessment",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsScoring=True,
                supportsCustomCss=True,
            ),
            requiredFields=["imageAssetId", "hotspots"],
            optionalFields=["tooltip"],
            isExportable=True,
        ),
    }


def _category_scenario() -> Dict[str, RendererManifestEntry]:
    """Scenario & branching components"""
    return {
        "scenario": RendererManifestEntry(
            componentType="scenario",
            displayName="Scenario / Case Study",
            category="scenario",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsBranching=True,
                supportsCustomCss=True,
            ),
            requiredFields=["scenarioText", "options"],
            optionalFields=["feedback", "branching"],
            isExportable=True,
        ),
        "branching-scenario": RendererManifestEntry(
            componentType="branching-scenario",
            displayName="Branching Scenario",
            category="scenario",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsBranching=True,
                supportsCustomCss=True,
            ),
            requiredFields=["branches", "outcomes"],
            optionalFields=["scoring"],
            isExportable=True,
        ),
        "decision-tree": RendererManifestEntry(
            componentType="decision-tree",
            displayName="Decision Tree",
            category="scenario",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsBranching=True,
                supportsCustomCss=True,
            ),
            requiredFields=["nodes", "edges"],
            optionalFields=["feedback"],
            isExportable=True,
        ),
        "role-play": RendererManifestEntry(
            componentType="role-play",
            displayName="Role Play Simulation",
            category="scenario",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsBranching=True,
                supportsCustomCss=True,
            ),
            requiredFields=["scenario", "roles", "dialogue"],
            optionalFields=["scoring"],
            isExportable=True,
        ),
    }


def _category_knowledge_check() -> Dict[str, RendererManifestEntry]:
    """Knowledge check & review components"""
    return {
        "quiz": RendererManifestEntry(
            componentType="quiz",
            displayName="Quiz",
            category="knowledge-check",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsScoring=True,
                supportsCustomCss=True,
            ),
            requiredFields=["questions"],
            optionalFields=["timeLimit", "showResults"],
            isExportable=True,
        ),
        "flashcard": RendererManifestEntry(
            componentType="flashcard",
            displayName="Flashcard / Flip Card",
            category="knowledge-check",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsCustomCss=True,
            ),
            requiredFields=["cards"],
            optionalFields=["animation"],
            isExportable=True,
        ),
        "key-takeaways": RendererManifestEntry(
            componentType="key-takeaways",
            displayName="Key Takeaways",
            category="knowledge-check",
            capabilities=RendererCapabilities(
                supportsCustomCss=True,
            ),
            requiredFields=["takeaways"],
            optionalFields=["layout"],
            isExportable=True,
        ),
        "summary-takeaways": RendererManifestEntry(
            componentType="summary-takeaways",
            displayName="Summary / Takeaway Box",
            category="knowledge-check",
            capabilities=RendererCapabilities(
                supportsCustomCss=True,
            ),
            requiredFields=["content"],
            optionalFields=["icon", "emphasis"],
            isExportable=True,
        ),
        "learning-objectives": RendererManifestEntry(
            componentType="learning-objectives",
            displayName="Learning Objectives",
            category="knowledge-check",
            capabilities=RendererCapabilities(
                supportsCustomCss=True,
            ),
            requiredFields=["objectives"],
            optionalFields=["layout"],
            isExportable=True,
        ),
    }


def _category_insight_analytics() -> Dict[str, RendererManifestEntry]:
    """Insight, analytics & visualization components"""
    return {
        "metric": RendererManifestEntry(
            componentType="metric",
            displayName="Metric / KPI Display",
            category="insight-analytics",
            capabilities=RendererCapabilities(
                supportsCustomCss=True,
            ),
            requiredFields=["value", "label"],
            optionalFields=["unit", "trend"],
            isExportable=True,
        ),
        "data-visualization": RendererManifestEntry(
            componentType="data-visualization",
            displayName="Chart / Graph",
            category="insight-analytics",
            capabilities=RendererCapabilities(
                supportsCustomCss=True,
                supportsResponsive=True,
            ),
            requiredFields=["data", "chartType"],
            optionalFields=["labels", "legend"],
            isExportable=True,
        ),
        "progress-tracker": RendererManifestEntry(
            componentType="progress-tracker",
            displayName="Progress Bar / Tracker",
            category="insight-analytics",
            capabilities=RendererCapabilities(
                supportsCustomCss=True,
            ),
            requiredFields=["progress", "total"],
            optionalFields=["label", "animated"],
            isExportable=True,
        ),
        "analytics-view": RendererManifestEntry(
            componentType="analytics-view",
            displayName="Analytics Dashboard",
            category="insight-analytics",
            capabilities=RendererCapabilities(
                supportsCustomCss=True,
                supportsResponsive=True,
            ),
            requiredFields=["widgets"],
            optionalFields=["layout"],
            isExportable=True,
        ),
        "heat-map": RendererManifestEntry(
            componentType="heat-map",
            displayName="Heat Map",
            category="insight-analytics",
            capabilities=RendererCapabilities(
                supportsCustomCss=True,
            ),
            requiredFields=["data"],
            optionalFields=["colorScheme"],
            isExportable=True,
        ),
    }


def _category_interactive_tools() -> Dict[str, RendererManifestEntry]:
    """Interactive tools & widgets"""
    return {
        "calculator": RendererManifestEntry(
            componentType="calculator",
            displayName="Interactive Calculator",
            category="interactive-tools",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsCustomCss=True,
            ),
            requiredFields=["formula"],
            optionalFields=["variables", "decimals"],
            isExportable=True,
        ),
        "form": RendererManifestEntry(
            componentType="form",
            displayName="Survey / Form",
            category="interactive-tools",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsCustomCss=True,
            ),
            requiredFields=["fields"],
            optionalFields=["submitLabel", "validation"],
            isExportable=True,
        ),
        "interactive-tool": RendererManifestEntry(
            componentType="interactive-tool",
            displayName="Custom Interactive Tool",
            category="interactive-tools",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsCustomCss=True,
            ),
            requiredFields=["toolScript"],
            optionalFields=[],
            isExportable=True,
        ),
        "code-snippet": RendererManifestEntry(
            componentType="code-snippet",
            displayName="Code Block / Snippet",
            category="interactive-tools",
            capabilities=RendererCapabilities(
                supportsCustomCss=True,
            ),
            requiredFields=["code"],
            optionalFields=["language", "highlighted"],
            isExportable=True,
        ),
    }


def _category_learning_path() -> Dict[str, RendererManifestEntry]:
    """Learning path & course overview components"""
    return {
        "learning-roadmap": RendererManifestEntry(
            componentType="learning-roadmap",
            displayName="Learning Roadmap",
            category="learning-path",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsCustomCss=True,
                supportsResponsive=True,
            ),
            requiredFields=["path"],
            optionalFields=["checkpoints"],
            isExportable=True,
        ),
        "module-overview": RendererManifestEntry(
            componentType="module-overview",
            displayName="Module Overview",
            category="learning-path",
            capabilities=RendererCapabilities(
                supportsCustomCss=True,
            ),
            requiredFields=["modules"],
            optionalFields=["description"],
            isExportable=True,
        ),
        "course-map": RendererManifestEntry(
            componentType="course-map",
            displayName="Course Map / Structure",
            category="learning-path",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsCustomCss=True,
            ),
            requiredFields=["structure"],
            optionalFields=["interactive"],
            isExportable=True,
        ),
    }


def _category_media_interaction() -> Dict[str, RendererManifestEntry]:
    """Media interaction & engagement components"""
    return {
        "video-slide": RendererManifestEntry(
            componentType="video-slide",
            displayName="Video Slide with Interactions",
            category="media-interaction",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsCustomCss=True,
                supportsResponsive=True,
            ),
            requiredFields=["videoAssetId"],
            optionalFields=["cuepoints", "chapters"],
            isExportable=True,
        ),
        "audio-player": RendererManifestEntry(
            componentType="audio-player",
            displayName="Audio Player",
            category="media-interaction",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsCustomCss=True,
            ),
            requiredFields=["audioAssetId"],
            optionalFields=["transcript", "chapters"],
            isExportable=True,
        ),
        "document-viewer": RendererManifestEntry(
            componentType="document-viewer",
            displayName="Document Viewer / PDF",
            category="media-interaction",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsCustomCss=True,
            ),
            requiredFields=["documentAssetId"],
            optionalFields=["fullscreen"],
            isExportable=True,
        ),
        "carousel": RendererManifestEntry(
            componentType="carousel",
            displayName="Image Carousel / Slider",
            category="media-interaction",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsCustomCss=True,
                supportsResponsive=True,
            ),
            requiredFields=["images"],
            optionalFields=["autoplay", "navigation"],
            isExportable=True,
        ),
    }


def _category_social_collaboration() -> Dict[str, RendererManifestEntry]:
    """Social & collaboration components"""
    return {
        "discussion-forum": RendererManifestEntry(
            componentType="discussion-forum",
            displayName="Discussion Forum",
            category="social-collaboration",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
            ),
            requiredFields=["topics"],
            optionalFields=["moderation"],
            isExportable=False,  # Not typically exported
            fallbackComponent="summary-takeaways",
        ),
        "comment-section": RendererManifestEntry(
            componentType="comment-section",
            displayName="Comments Section",
            category="social-collaboration",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
            ),
            requiredFields=[],
            optionalFields=["moderation"],
            isExportable=False,
            fallbackComponent="content-text",
        ),
        "peer-review": RendererManifestEntry(
            componentType="peer-review",
            displayName="Peer Review Activity",
            category="social-collaboration",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
            ),
            requiredFields=["rubric"],
            optionalFields=["anonymous"],
            isExportable=False,
            fallbackComponent="quiz",
        ),
    }


def _category_accessibility() -> Dict[str, RendererManifestEntry]:
    """Accessibility & assistive components"""
    return {
        "glossary": RendererManifestEntry(
            componentType="glossary",
            displayName="Glossary / Definitions",
            category="accessibility",
            capabilities=RendererCapabilities(
                supportsCustomCss=True,
            ),
            requiredFields=["terms"],
            optionalFields=["searchable"],
            isExportable=True,
        ),
        "footnote": RendererManifestEntry(
            componentType="footnote",
            displayName="Footnote / Annotation",
            category="accessibility",
            capabilities=RendererCapabilities(
                supportsCustomCss=True,
            ),
            requiredFields=["content"],
            optionalFields=[],
            isExportable=True,
        ),
        "caption-assist": RendererManifestEntry(
            componentType="caption-assist",
            displayName="Caption / Audio Description",
            category="accessibility",
            capabilities=RendererCapabilities(
                supportsCustomCss=True,
            ),
            requiredFields=["text"],
            optionalFields=["language"],
            isExportable=True,
        ),
        "text-highlighter": RendererManifestEntry(
            componentType="text-highlighter",
            displayName="Text Highlighter Tool",
            category="accessibility",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsCustomCss=True,
            ),
            requiredFields=["text"],
            optionalFields=["preHighlighted"],
            isExportable=True,
        ),
    }


def _category_engagement() -> Dict[str, RendererManifestEntry]:
    """Engagement & gamification components"""
    return {
        "badge": RendererManifestEntry(
            componentType="badge",
            displayName="Badge / Achievement",
            category="engagement",
            capabilities=RendererCapabilities(
                supportsCustomCss=True,
            ),
            requiredFields=["badgeId"],
            optionalFields=["unlocked"],
            isExportable=True,
        ),
        "leaderboard": RendererManifestEntry(
            componentType="leaderboard",
            displayName="Leaderboard",
            category="engagement",
            capabilities=RendererCapabilities(
                supportsCustomCss=True,
            ),
            requiredFields=["entries"],
            optionalFields=[],
            isExportable=False,  # Dynamic - not typically exported
            fallbackComponent="data-visualization",
        ),
        "point-system": RendererManifestEntry(
            componentType="point-system",
            displayName="Points / Scoring Display",
            category="engagement",
            capabilities=RendererCapabilities(
                supportsCustomCss=True,
            ),
            requiredFields=["points"],
            optionalFields=["label"],
            isExportable=True,
        ),
        "gamification-widget": RendererManifestEntry(
            componentType="gamification-widget",
            displayName="Gamification Widget",
            category="engagement",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsCustomCss=True,
            ),
            requiredFields=["elements"],
            optionalFields=[],
            isExportable=True,
        ),
    }


def _category_resources() -> Dict[str, RendererManifestEntry]:
    """Resources & downloadable content"""
    return {
        "download-resource": RendererManifestEntry(
            componentType="download-resource",
            displayName="Downloadable Resource",
            category="resources",
            capabilities=RendererCapabilities(
                supportsCustomCss=True,
            ),
            requiredFields=["assetId"],
            optionalFields=["description"],
            isExportable=True,
        ),
        "resource-library": RendererManifestEntry(
            componentType="resource-library",
            displayName="Resource Library",
            category="resources",
            capabilities=RendererCapabilities(
                supportsInteraction=True,
                supportsCustomCss=True,
            ),
            requiredFields=["resources"],
            optionalFields=["categories", "searchable"],
            isExportable=True,
        ),
        "external-link": RendererManifestEntry(
            componentType="external-link",
            displayName="External Link / Resource",
            category="resources",
            capabilities=RendererCapabilities(
                supportsCustomCss=True,
            ),
            requiredFields=["url"],
            optionalFields=["title", "openNewTab"],
            isExportable=True,
        ),
    }


def _category_structural() -> Dict[str, RendererManifestEntry]:
    """Structural & layout-only components"""
    return {
        "section-header": RendererManifestEntry(
            componentType="section-header",
            displayName="Section Header",
            category="structural",
            capabilities=RendererCapabilities(
                supportsCustomCss=True,
            ),
            requiredFields=["title"],
            optionalFields=["subtitle", "icon"],
            isExportable=True,
        ),
        "divider": RendererManifestEntry(
            componentType="divider",
            displayName="Divider / Separator",
            category="structural",
            capabilities=RendererCapabilities(
                supportsCustomCss=True,
            ),
            requiredFields=[],
            optionalFields=["style"],
            isExportable=True,
        ),
        "spacer": RendererManifestEntry(
            componentType="spacer",
            displayName="Spacer / Vertical Spacing",
            category="structural",
            capabilities=RendererCapabilities(
                supportsCustomCss=True,
            ),
            requiredFields=["height"],
            optionalFields=[],
            isExportable=True,
        ),
        "container": RendererManifestEntry(
            componentType="container",
            displayName="Container / Layout Box",
            category="structural",
            capabilities=RendererCapabilities(
                supportsCustomCss=True,
                supportsResponsive=True,
            ),
            requiredFields=["content"],
            optionalFields=["layout", "style"],
            isExportable=True,
        ),
    }


def build_renderer_manifest() -> RendererManifest:
    """Build complete renderer manifest for all 84 template types"""
    
    all_renderers: Dict[str, RendererManifestEntry] = {}
    
    # Aggregate all categories
    all_renderers.update(_category_presentation())
    all_renderers.update(_category_navigation())
    all_renderers.update(_category_assessment())
    all_renderers.update(_category_scenario())
    all_renderers.update(_category_knowledge_check())
    all_renderers.update(_category_insight_analytics())
    all_renderers.update(_category_interactive_tools())
    all_renderers.update(_category_learning_path())
    all_renderers.update(_category_media_interaction())
    all_renderers.update(_category_social_collaboration())
    all_renderers.update(_category_accessibility())
    all_renderers.update(_category_engagement())
    all_renderers.update(_category_resources())
    all_renderers.update(_category_structural())
    
    return RendererManifest(
        version="1.0",
        lastUpdated=datetime.utcnow(),
        renderers=all_renderers,
    )


# Singleton instance (lazy-loaded)
_MANIFEST_INSTANCE: RendererManifest | None = None


def get_renderer_manifest() -> RendererManifest:
    """Get or build the renderer manifest (lazy singleton pattern)"""
    global _MANIFEST_INSTANCE
    if _MANIFEST_INSTANCE is None:
        _MANIFEST_INSTANCE = build_renderer_manifest()
    return _MANIFEST_INSTANCE


def reload_renderer_manifest() -> RendererManifest:
    """Force rebuild and reload the manifest (useful for testing)"""
    global _MANIFEST_INSTANCE
    _MANIFEST_INSTANCE = build_renderer_manifest()
    return _MANIFEST_INSTANCE
