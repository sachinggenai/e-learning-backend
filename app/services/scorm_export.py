"""
SCORM Export Service
Implements SCORM package generation with Dynamic Template Runtime System.
Uses data-driven sanitization and validation - NO HARDCODED TEMPLATE LOGIC.
"""

import json
import zipfile
import tempfile
import os
import shutil
import re
import mimetypes
import html
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from io import BytesIO
# import aiofiles  # Reserved for future async file operations
import logging

try:
    from bs4 import BeautifulSoup
    HAS_BEAUTIFULSOUP = True
except ImportError:
    HAS_BEAUTIFULSOUP = False
    print("Warning: BeautifulSoup not available. HTML sanitization will be limited.")

from ..models.course import Course, Template, BUILTIN_TEMPLATE_TYPES
from .scorm.sanitizers import DynamicSanitizer
from .scorm.registries import registry
from ..db.config import get_session
from ..repositories.template_type_repo import (
    TemplateTypeRepository,
    TemplateTypeNotFoundError,
)
from .asset_packager import AssetPackager, PackagedAsset

logger = logging.getLogger(__name__)


def _ensure_dict(data: Any) -> Dict[str, Any]:
    """
    Convert various data types to dictionary.
    Handles Pydantic models, dataclasses, and plain objects.
    
    Args:
        data: Data to convert (dict, Pydantic model, dataclass, or object)
        
    Returns:
        Dictionary representation of the data
        
    Raises:
        ValueError: If data cannot be converted to dictionary
    """
    # If already a dict, return as-is
    if isinstance(data, dict):
        return data
    
    # If Pydantic v2 model
    if hasattr(data, 'model_dump') and callable(getattr(data, 'model_dump')):
        try:
            return data.model_dump()
        except Exception as e:
            logger.warning(f"Failed to convert Pydantic v2 model to dict: {e}")

    # If Pydantic v1 model
    if hasattr(data, 'dict') and callable(getattr(data, 'dict')):
        try:
            return data.dict()
        except Exception as e:
            logger.warning(f"Failed to convert Pydantic model to dict: {e}")
    
    # If dataclass
    if hasattr(data, '__dataclass_fields__'):
        try:
            from dataclasses import asdict
            return asdict(data)
        except Exception as e:
            logger.warning(f"Failed to convert dataclass to dict: {e}")
    
    # If object with __dict__
    if hasattr(data, '__dict__') and not isinstance(data, type):
        try:
            return vars(data)
        except Exception as e:
            logger.warning(f"Failed to convert object to dict: {e}")
    
    # If still not dict, raise error
    raise ValueError(
        f"Cannot convert data of type {type(data).__name__} to dictionary. "
        f"Expected dict, Pydantic model, dataclass, or object with __dict__."
    )


class SCORMExportService:
    """Service for generating SCORM packages from course data"""

    TEMPLATE_TYPE_ALIASES = {
        # Pure aliases (no data transform required)
        "video": "content-video",
        "content_text": "content-text",
        "quiz": "mcq",
        "multi-select": "multiple-select",
        "final-assessment": "final-assessment",
        "step-by-step": "stepper",
        "flashcards": "flashcard",
        "flip-cards": "flashcard",
        "quiz-game": "quiz",
        "video-slide": "content-video",
        "text-with-media": "content-media",
        "fill-blanks": "fill-in-blank",
        "role-play-simulation": "role-play",
        "knowledge-check": "quiz",
        # Accordion-family (structural transform applied)
        "click-reveal": "accordion",
        "layered-content": "accordion",
        "case-study": "accordion",
        "code-of-conduct": "accordion",
        "screen-reader-guide": "accordion",
        "clickable-icons": "accordion",
        # Tabs-family (structural transform applied)
        "before-after": "tabs",
        "dos-donts": "tabs",
        "scenario-debate": "tabs",
        # Stepper-family (structural transform applied)
        "animated-explainer": "stepper",
        "guided-practice": "stepper",
        "software-simulation": "stepper",
        # Timeline-family (structural transform applied)
        "cycle-diagram": "timeline",
        # Data-visualization-family (structural transform applied)
        "comparison-table": "data-visualization",
        "keyboard-nav-guide": "data-visualization",
        "matrix-grid": "data-visualization",
        "skill-gap-analysis": "data-visualization",
        "skill-mastery-report": "data-visualization",
        # Key-takeaways-family (structural transform applied)
        "audit-checklist": "key-takeaways",
        "quick-tips": "key-takeaways",
        # Flashcard-family (structural transform applied)
        "microlearning-cards": "flashcard",
        # Module-overview-family (structural transform applied)
        "recommendation-card": "module-overview",
        # Scenario-family (structural transform applied)
        "scenario-question": "scenario",
        "regulatory-scenario": "scenario",
    }

    def __init__(self):
        self.scorm_version = "1.2"
        self.export_contract_version = "2026-04-12.1"
        self.package_identifier = None
        self.media_resources = {}
        self.resource_dependencies = {}
        self.packaged_assets: List[PackagedAsset] = []
        self.asset_manifest: Dict[str, Any] = {}
        # Current canonical runtime supports these slide/template types.
        # Expand/remove this gate when frontend runtime is fully registry-driven.
        self.runtime_supported_template_types = {
            # Content / Presentation
            "content-text", "content", "rich-text-editor", "content-media",
            "content-image", "content-video", "transcript-caption",
            "infographic", "quotation",
            # Navigation / Layout
            "tabs", "accordion", "stepper", "timeline",
            "course-menu", "breadcrumb", "sidebar-navigation",
            # Assessment
            "mcq", "multiple-select", "true-false", "fill-in-blank",
            "hotspot", "image-hotspots", "matching", "drag-and-drop",
            "final-assessment",
            # Knowledge Check
            "key-takeaways", "summary-takeaways", "learning-objectives",
            "flashcard", "quiz",
            # Scenario
            "scenario", "branching-scenario", "decision-tree", "role-play",
            # Data & Analytics
            "metric", "data-visualization", "progress-tracker",
            "analytics-view", "heat-map",
            # Interactive Tools
            "code-snippet", "calculator", "form", "interactive-tool",
            # Learning Path
            "learning-roadmap", "module-overview", "course-map",
        }

    def _template_type_candidates(self, type_key: str) -> List[str]:
        """Return normalized candidates for a template type identifier."""
        raw = (type_key or "").strip()
        if not raw:
            return []

        lower = raw.lower()
        dash = lower.replace("_", "-")
        under = lower.replace("-", "_")

        alias_values = (
            self.TEMPLATE_TYPE_ALIASES.get(lower),
            self.TEMPLATE_TYPE_ALIASES.get(dash),
            self.TEMPLATE_TYPE_ALIASES.get(under),
        )

        out: List[str] = []
        for candidate in (raw, lower, dash, under, *alias_values):
            if candidate and candidate not in out:
                out.append(candidate)
        return out

    def _canonicalize_template_type(self, type_key: str) -> str:
        """Map authoring template IDs to the runtime template IDs used in export."""
        candidates = self._template_type_candidates(type_key)
        for candidate in candidates:
            if candidate in self.runtime_supported_template_types:
                return candidate
        return (type_key or "").strip().lower().replace("_", "-")

    def _transform_template_data(
        self,
        authoring_type: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Remap authoring template data fields to the field shapes expected by
        the SCORM runtime renderers.  Only types with a structural transform
        registered in TEMPLATE_TYPE_ALIASES are handled here; everything else
        is returned unchanged.  All transforms are purely additive/renames —
        the original keys are preserved alongside the new ones so the runtime
        can fall back gracefully if a source field is missing.
        """
        if not data:
            return data or {}

        t = (authoring_type or "").strip().lower().replace("_", "-")

        # ── Accordion-family ───────────────────────────────────────────────
        # Runtime expects: data.panels = [{title, body}]

        if t in ("click-reveal", "layered-content"):
            source_key = "items" if t == "click-reveal" else "layers"
            items = data.get(source_key) or data.get("items") or data.get("sections") or []
            panels = [
                {
                    "title": item.get("label") or item.get("title") or f"Section {i + 1}",
                    "body": item.get("content") or item.get("body") or "",
                }
                for i, item in enumerate(items) if isinstance(item, dict)
            ]
            return {**data, "panels": panels}

        if t in ("case-study", "code-of-conduct"):
            items = data.get("sections") or data.get("items") or []
            panels = [
                {
                    "title": item.get("title") or item.get("heading") or f"Section {i + 1}",
                    "body": item.get("content") or item.get("body") or "",
                }
                for i, item in enumerate(items) if isinstance(item, dict)
            ]
            return {**data, "panels": panels}

        if t == "screen-reader-guide":
            items = data.get("sections") or data.get("items") or []
            panels = [
                {
                    "title": item.get("heading") or item.get("title") or f"Section {i + 1}",
                    "body": item.get("content") or item.get("body") or "",
                }
                for i, item in enumerate(items) if isinstance(item, dict)
            ]
            return {**data, "panels": panels}

        if t == "clickable-icons":
            items = data.get("icons") or data.get("items") or []
            panels = [
                {
                    "title": item.get("label") or item.get("title") or f"Item {i + 1}",
                    "body": (
                        item.get("content") or item.get("description")
                        or item.get("body") or ""
                    ),
                }
                for i, item in enumerate(items) if isinstance(item, dict)
            ]
            return {**data, "panels": panels}

        # ── Tabs-family ────────────────────────────────────────────────────
        # Runtime expects: data.tabs = [{id, title, body}]

        if t == "before-after":
            tabs = [
                {
                    "id": "before",
                    "title": data.get("beforeLabel") or "Before",
                    "body": data.get("beforeContent") or data.get("before") or "",
                },
                {
                    "id": "after",
                    "title": data.get("afterLabel") or "After",
                    "body": data.get("afterContent") or data.get("after") or "",
                },
            ]
            return {**data, "tabs": tabs}

        if t == "dos-donts":
            def _items_to_html(items: Any) -> str:
                if not items:
                    return ""
                if isinstance(items, list):
                    li = "".join(
                        f"<li>{item.get('text', item) if isinstance(item, dict) else item}</li>"
                        for item in items
                    )
                    return f"<ul>{li}</ul>"
                return str(items)

            tabs = [
                {
                    "id": "dos",
                    "title": "Do",
                    "body": _items_to_html(data.get("dos") or []),
                },
                {
                    "id": "donts",
                    "title": "Don't",
                    "body": _items_to_html(
                        data.get("donts") or data.get("don'ts") or []
                    ),
                },
            ]
            return {**data, "tabs": tabs}

        if t == "scenario-debate":
            def _side(raw: Any, default_label: str):
                if isinstance(raw, dict):
                    label = raw.get("label") or raw.get("title") or default_label
                    body = (
                        raw.get("content") or raw.get("arguments")
                        or raw.get("body") or ""
                    )
                else:
                    label, body = default_label, str(raw or "")
                return label, body

            side_a_raw = data.get("sideA") or data.get("side_a") or {}
            side_b_raw = data.get("sideB") or data.get("side_b") or {}
            a_label, a_body = _side(side_a_raw, "Side A")
            b_label, b_body = _side(side_b_raw, "Side B")
            tabs = [
                {"id": "side-a", "title": a_label, "body": a_body},
                {"id": "side-b", "title": b_label, "body": b_body},
            ]
            return {**data, "tabs": tabs}

        # ── Stepper-family ─────────────────────────────────────────────────
        # Runtime expects: data.steps = [{title, description}]

        if t == "animated-explainer":
            items = (
                data.get("frames") or data.get("steps")
                or data.get("slides") or []
            )
            steps = [
                {
                    "title": item.get("title") or item.get("label") or f"Step {i + 1}",
                    "description": (
                        item.get("description") or item.get("content")
                        or item.get("text") or ""
                    ),
                }
                for i, item in enumerate(items) if isinstance(item, dict)
            ]
            return {**data, "steps": steps}

        if t == "guided-practice":
            items = data.get("steps") or data.get("tasks") or []
            steps = [
                {
                    "title": item.get("title") or item.get("label") or f"Step {i + 1}",
                    "description": " ".join(
                        filter(None, [
                            item.get("instruction") or item.get("content") or "",
                            ("Hint: " + item["hint"]) if item.get("hint") else "",
                        ])
                    ),
                }
                for i, item in enumerate(items) if isinstance(item, dict)
            ]
            return {**data, "steps": steps}

        if t == "software-simulation":
            items = (
                data.get("phases") or data.get("steps")
                or data.get("actions") or []
            )
            steps = [
                {
                    "title": (
                        item.get("title") or item.get("type") or f"Step {i + 1}"
                    ),
                    "description": (
                        item.get("content") or item.get("description")
                        or item.get("instruction") or ""
                    ),
                }
                for i, item in enumerate(items) if isinstance(item, dict)
            ]
            return {**data, "steps": steps}

        # ── Timeline-family ────────────────────────────────────────────────
        # Runtime expects: data.events = [{label, title, description}]

        if t == "cycle-diagram":
            items = (
                data.get("stages") or data.get("phases")
                or data.get("steps") or []
            )
            events = [
                {
                    "label": item.get("label") or item.get("name") or f"Stage {i + 1}",
                    "title": item.get("title") or item.get("label") or f"Stage {i + 1}",
                    "description": item.get("description") or item.get("content") or "",
                }
                for i, item in enumerate(items) if isinstance(item, dict)
            ]
            return {**data, "events": events}

        # ── Key-takeaways-family ───────────────────────────────────────────
        # Runtime expects: data.takeaways = [str | {text}]

        if t == "audit-checklist":
            items = data.get("items") or data.get("checks") or []
            takeaways = [
                (item.get("text") or item.get("label") or item.get("title") or str(item))
                if isinstance(item, dict) else str(item)
                for item in items
            ]
            return {**data, "takeaways": takeaways}

        if t == "quick-tips":
            items = data.get("tips") or data.get("items") or []
            takeaways = [
                (item.get("text") or item.get("tip") or item.get("title") or str(item))
                if isinstance(item, dict) else str(item)
                for item in items
            ]
            return {**data, "takeaways": takeaways}

        # ── Data-visualization-family ──────────────────────────────────────
        # Runtime expects: data.headers = [str], data.rows = [[str]]

        if t == "comparison-table":
            columns = data.get("columns") or []
            headers = [
                (col.get("header") or col.get("title") or col.get("label") or str(col))
                if isinstance(col, dict) else str(col)
                for col in columns
            ]
            source_rows = data.get("rows") or []
            rows = [
                list(
                    row.get("cells") if isinstance(row, dict) and "cells" in row
                    else (row.values() if isinstance(row, dict) else row)
                )
                for row in source_rows
            ]
            return {**data, "headers": headers, "rows": rows}

        if t == "keyboard-nav-guide":
            items = data.get("shortcuts") or data.get("bindings") or []
            headers = ["Keys", "Action"]
            rows = [
                [
                    item.get("keys") or item.get("key") or "",
                    item.get("action") or item.get("description") or "",
                ]
                for item in items if isinstance(item, dict)
            ]
            return {**data, "headers": headers, "rows": rows}

        if t == "matrix-grid":
            row_headers = data.get("rowHeaders") or data.get("row_headers") or []
            col_headers = (
                data.get("columnHeaders") or data.get("col_headers")
                or data.get("columns") or []
            )
            cells = data.get("cells") or []
            headers = [""] + [str(h) for h in col_headers]
            rows = []
            for i, rh in enumerate(row_headers):
                row_cells = cells[i] if i < len(cells) else []
                rows.append(
                    [str(rh)] + (list(row_cells) if isinstance(row_cells, list) else [str(row_cells)])
                )
            return {**data, "headers": headers, "rows": rows}

        if t in ("skill-gap-analysis", "skill-mastery-report"):
            items = data.get("skills") or data.get("items") or []
            if not items:
                return data
            first = items[0] if isinstance(items[0], dict) else {}
            headers = list(first.keys()) if isinstance(first, dict) else ["Skill"]
            rows = [
                [item.get(k, "") for k in headers] if isinstance(item, dict) else [str(item)]
                for item in items
            ]
            return {**data, "headers": headers, "rows": rows}

        # ── Flashcard-family ───────────────────────────────────────────────
        # Runtime expects: data.cards = [{front, back}]

        if t == "microlearning-cards":
            items = data.get("cards") or data.get("slides") or []
            cards = [
                {
                    "front": (
                        item.get("title") or item.get("question")
                        or item.get("front") or f"Card {i + 1}"
                    ),
                    "back": (
                        item.get("body") or item.get("answer")
                        or item.get("back") or item.get("description") or ""
                    ),
                }
                for i, item in enumerate(items) if isinstance(item, dict)
            ]
            return {**data, "cards": cards}

        # ── Module-overview-family ─────────────────────────────────────────
        # Runtime expects: data.modules = [{title, description}]

        if t == "recommendation-card":
            items = data.get("recommendations") or data.get("items") or []
            modules = [
                {
                    "title": item.get("title") or item.get("name") or f"Item {i + 1}",
                    "description": (
                        item.get("description") or item.get("body")
                        or item.get("summary") or ""
                    ),
                }
                for i, item in enumerate(items) if isinstance(item, dict)
            ]
            return {**data, "modules": modules}

        # ── Scenario-family ────────────────────────────────────────────────
        # Runtime expects: data.scenarioText, data.options = [{text, feedback}]

        if t == "scenario-question":
            scenario_text = (
                data.get("scenario") or data.get("scenarioText")
                or data.get("content") or ""
            )
            question_text = data.get("question") or ""
            combined = (
                f"{scenario_text}\n\n{question_text}".strip()
                if question_text else scenario_text
            )
            return {**data, "scenarioText": combined}

        if t == "regulatory-scenario":
            decisions = data.get("decisions") or []
            options: List[Any] = []
            scenario_text = (
                data.get("scenarioText") or data.get("scenario")
                or data.get("content") or ""
            )
            if decisions and isinstance(decisions[0], dict):
                options = decisions[0].get("options") or []
                if not scenario_text:
                    scenario_text = (
                        decisions[0].get("situation")
                        or decisions[0].get("scenario") or ""
                    )
            return {**data, "scenarioText": scenario_text, "options": options}

        # ── Text-with-media ────────────────────────────────────────────────
        # Runtime expects: data.body (HTML), data.mediaUrl, data.mediaType,
        #                  data.mediaPosition

        if t in ("text-with-media", "content-media"):
            import re as _re
            _url_re = _re.compile(r'^https?://', _re.IGNORECASE)

            # Resolve body (rich HTML text) — prefer explicit body field;
            # fall back to content only when it is NOT a bare URL.
            raw_body = (
                data.get("body")
                or data.get("text")
                or data.get("description")
                or ""
            )
            raw_content = data.get("content") or ""
            if not raw_body and raw_content and not _url_re.match(str(raw_content).strip()):
                raw_body = raw_content

            # Resolve media URL — prefer explicit mediaUrl / imageUrl / videoUrl;
            # fall back to content when it looks like a URL.
            raw_media = (
                data.get("mediaUrl")
                or data.get("imageUrl")
                or data.get("videoUrl")
                or data.get("src")
                or data.get("url")
                or ""
            )
            if not raw_media and raw_content and _url_re.match(str(raw_content).strip()):
                raw_media = raw_content

            media_type = (
                data.get("mediaType")
                or ("video" if data.get("videoUrl") else "image")
            )
            media_position = data.get("mediaPosition") or data.get("layout") or "right"

            return {
                **data,
                "body": raw_body,
                "mediaUrl": raw_media,
                "mediaType": media_type,
                "mediaPosition": media_position,
            }

        return data

    async def generate_scorm_package(self, course: Course, include_assets: bool = True,
                                     theme_bundle: Optional[Dict[str, Any]] = None) -> BytesIO:
        """
        Generate a complete SCORM package as a ZIP file
        
        Args:
            course: Course data to export
            include_assets: Whether to include asset files in package
            theme_bundle: Resolved theme cascade (courseTheme, pageOverrides, componentOverrides)
            
        Returns:
            BytesIO: ZIP file content as bytes
        """
        logger.info(f"Generating SCORM package for course: {course.courseId}")
        
        # Production hardening: Validate course before processing
        validation_result = await self.validate_for_export(course)
        if not validation_result.get("valid", False):
            error_msg = "; ".join(validation_result.get("errors", []))
            raise ValueError(f"Course validation failed: {error_msg}")
        
        # Production hardening: Check size limits
        size_estimate = self.estimate_package_size(course)
        max_size_mb = 50  # 50MB limit for SCORM packages
        if size_estimate.get("total_estimated_mb", 0) > max_size_mb:
            raise ValueError(
                f"Estimated package size ({size_estimate['total_estimated_mb']}MB) "
                f"exceeds maximum limit of {max_size_mb}MB. "
                f"Consider reducing content or optimizing assets."
            )
        
        # Production hardening: Template count limits
        max_templates = 100
        if len(course.templates) > max_templates:
            raise ValueError(
                f"Course has {len(course.templates)} templates, "
                f"exceeding maximum of {max_templates}"
            )
        
        # Production hardening: Asset count limits
        max_assets = 200
        if len(course.assets) > max_assets:
            raise ValueError(
                f"Course has {len(course.assets)} assets, "
                f"exceeding maximum of {max_assets}"
            )
        
        try:
            # Create temporary directory for package assembly
            with tempfile.TemporaryDirectory() as temp_dir:
                package_dir = Path(temp_dir) / "scorm_package"
                package_dir.mkdir()
                
                # Generate package identifier
                self.package_identifier = f"course_{course.courseId}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

                # Reset per-export state
                self.packaged_assets = []
                self.asset_manifest = {}

                # Deterministic asset packaging is done before manifest generation
                # so imsmanifest.xml references exported package paths, not source names.
                if include_assets and course.assets:
                    logger.info("Packaging assets deterministically")
                    self.asset_manifest = await self._package_assets(package_dir, course.assets)
                
                # Create SCORM structure
                logger.info("Creating SCORM manifest")
                await self._create_imsmanifest(package_dir, course)
                logger.info("Creating course data")
                await self._create_course_data_js(package_dir, course)
                logger.info("Creating content HTML")
                await self._create_content_html(package_dir, course, theme_bundle=theme_bundle)
                logger.info("Creating SCORM wrapper")
                await self._create_scorm_wrapper(package_dir, course)

                # Remove stale legacy runtime files to keep one canonical runtime.
                self._remove_legacy_runtime_files(package_dir)
                
                # Production hardening: Validate final package structure
                await self._validate_package_structure(package_dir)
                
                # Create ZIP package
                logger.info("Creating ZIP package")
                zip_buffer = BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                    self._add_directory_to_zip(zip_file, package_dir, "")
                
                # Production hardening: Final size check
                final_size_mb = len(zip_buffer.getvalue()) / (1024 * 1024)
                if final_size_mb > max_size_mb:
                    raise ValueError(
                        f"Final package size ({final_size_mb:.1f}MB) "
                        f"exceeds maximum limit of {max_size_mb}MB"
                    )
                
                zip_buffer.seek(0)
                logger.info("SCORM package generated successfully")
                return zip_buffer
                
        except Exception as error:
            logger.error(f"Failed to generate SCORM package: {str(error)}", exc_info=True)
            raise Exception(f"Failed to generate SCORM package: {str(error)}")
    
    async def _create_imsmanifest(self, package_dir: Path, course: Course) -> None:
        """Create the imsmanifest.xml file required by SCORM"""
        try:
            # Validate inputs
            if not package_dir or not package_dir.exists():
                raise ValueError(f"Invalid package directory: {package_dir}")
            if not course or not hasattr(course, 'courseId'):
                raise ValueError("Invalid course object provided")

            manifest_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="{self.package_identifier}" version="1" 
          xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2"
          xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
          xsi:schemaLocation="http://www.imsproject.org/xsd/imscp_rootv1p1p2 imscp_rootv1p1p2.xsd
                              http://www.imsglobal.org/xsd/imsmd_rootv1p2p1 imsmd_rootv1p2p1.xsd
                              http://www.adlnet.org/xsd/adlcp_rootv1p2 adlcp_rootv1p2.xsd">

    <metadata>
        <schema>ADL SCORM</schema>
        <schemaversion>{self.scorm_version}</schemaversion>
        <lom xmlns="http://www.imsglobal.org/xsd/imsmd_rootv1p2p1">
            <general>
                <identifier>
                    <catalog>URI</catalog>
                    <entry>{course.courseId}</entry>
                </identifier>
                <title>
                    <langstring xml:lang="en">{self._escape_xml(course.title)}</langstring>
                </title>
                <description>
                    <langstring xml:lang="en">{self._escape_xml(course.description)}</langstring>
                </description>
                <language>en</language>
            </general>
            <lifeCycle>
                <version>
                    <langstring xml:lang="en">{course.version}</langstring>
                </version>
                <contribute>
                    <role>
                        <source>LOMv1.0</source>
                        <value>Author</value>
                    </role>
                    <entity>{self._escape_xml(course.author)}</entity>
                    <date>
                        <dateTime>{course.createdAt.isoformat()}</dateTime>
                    </date>
                </contribute>
            </lifeCycle>
        </lom>
    </metadata>

    <organizations default="default_org">
        <organization identifier="default_org">
            <title>{self._escape_xml(course.title)}</title>
            {self._generate_items_xml(course)}
        </organization>
    </organizations>

    <resources>
        <resource identifier="resource_1" type="webcontent" adlcp:scormtype="sco" href="index.html">
            <file href="index.html"/>
            <file href="scorm_wrapper.js"/>
            <file href="course_data.js"/>
            <file href="styles.css"/>
            {'<file href="asset_manifest.json"/>' if self.asset_manifest else ''}
            {self._generate_asset_files_xml(course.assets) if course.assets else ""}
        </resource>
    </resources>

</manifest>"""

            manifest_path = package_dir / "imsmanifest.xml"
            with open(manifest_path, 'w', encoding='utf-8') as f:
                f.write(manifest_xml)

            logger.info("✓ SCORM manifest created successfully")

        except Exception as e:
            logger.error(f"Failed to create SCORM manifest: {e}")
            raise Exception(f"Manifest creation failed: {str(e)}")
    
    def _generate_items_xml(self, course: Course) -> str:
        """
        Generate pure SCORM 1.2 organization items XML.
        
        Pure SCORM 1.2 approach:
        - Single SCO (resource_1) referenced by all items
        - No SCORM 2004 sequencing elements
        - JavaScript-based completion tracking via objectives
        - Free navigation without manifest-based constraints
        """
        # FIX: Use single item for SPA architecture to avoid LMS aggregation issues
        # This ensures the LMS tracks the entire course as a single SCO
        return f"""
            <item identifier="item_course_full" identifierref="resource_1" isvisible="true">
                <title>{self._escape_xml(course.title)}</title>
            </item>"""

    def _generate_asset_files_xml(self, assets: List[Any]) -> str:
        """Generate file references for assets"""
        files_xml = ""

        if self.packaged_assets:
            for packaged in sorted(self.packaged_assets, key=lambda a: a.package_path):
                files_xml += f'\n            <file href="{packaged.package_path}"/>'
            return files_xml

        # Fallback for compatibility if assets were not pre-packaged.
        for asset in assets:
            filename = os.path.basename(asset.path)
            files_xml += f'\n            <file href="assets/{filename}"/>'

        return files_xml
    
    async def _create_course_data_js(
        self, package_dir: Path, course: Course
    ) -> None:
        """
        FIX #1 & #3: Create properly structured course data JavaScript
        
        Ensures:
        - courseData is object with templates property (not array-only)
        - Includes all course metadata
        - Safe for early player initialization
        - Proper JSON serialization
        """
        try:
            # Validate inputs
            if not package_dir or not package_dir.exists():
                raise ValueError(f"Invalid package directory: {package_dir}")
            if not course or not hasattr(course, 'templates'):
                raise ValueError("Invalid course object or missing templates")

            # Transform templates to safe format using dynamic sanitization
            templates_data = []
            for template in course.templates:
                try:
                    # Use dynamic sanitization based on template type
                    sanitized_data = await self._sanitize_data_dynamic(
                        template.type,
                        template.data
                    )
                    
                    runtime_template_type = self._canonicalize_template_type(
                        template.type
                    )

                    # Apply structural data transform when authoring type maps
                    # to a different runtime renderer (e.g. case-study → accordion)
                    authoring_type = (
                        (template.type or "").strip().lower().replace("_", "-")
                    )
                    if authoring_type != runtime_template_type:
                        sanitized_data = self._transform_template_data(
                            authoring_type, sanitized_data
                        )

                    safe_template = {
                        'id': template.id,
                        'type': runtime_template_type,
                        'order': template.order,
                        'title': self._sanitize_text(template.title),
                        'data': sanitized_data,
                        'pageId': getattr(template, 'pageId', None),
                    }
                    templates_data.append(safe_template)
                except Exception as e:
                    logger.warning(
                        f"Failed to process template {template.id}: {e}"
                    )
                    # Continue with other templates

            # Create complete course object (not just array)
            course_data = {
                'courseId': course.courseId,
                'exportContractVersion': self.export_contract_version,
                'title': self._sanitize_text(course.title),
                'author': self._sanitize_text(course.author),
                'version': course.version,
                'language': course.language or 'en',
                'supportedTemplateTypes': sorted(
                    self.runtime_supported_template_types
                ),
                'templates': templates_data,
                'totalSlides': len(templates_data),
                'createdAt': (
                    course.createdAt.isoformat()
                    if course.createdAt else None
                )
            }

            # Generate JavaScript with proper escaping
            course_data_js = (
                "// ============================================\n"
                "// COURSE DATA - Generated by eLearning Platform\n"
                f"// SCORM Package: {self._escape_js_string(course.title)}\n"
                f"// Generated: {datetime.now().isoformat()}\n"
                "// ============================================\n\n"
                "// Define courseData as a global variable\n"
                "// This will be safely initialized by the player\n"
                f"var courseData = {json.dumps(course_data, indent=2, ensure_ascii=False)};\n\n"
                "// Validation check\n"
                "if (typeof courseData !== 'object' || "
                "!courseData.templates) {\n"
                "    console.error('ERROR: courseData not properly loaded');\n"
                "    console.error('courseData type:', typeof courseData);\n"
                "    console.error('courseData value:', courseData);\n"
                "    throw new Error('Course data initialization failed');\n"
                "}\n\n"
                "console.log('✓ Course data loaded successfully');\n"
                "console.log('  Slides:', courseData.templates.length);\n"
                "console.log('  Title:', courseData.title);\n"
            )

            data_path = package_dir / "course_data.js"
            with open(data_path, 'w', encoding='utf-8') as f:
                f.write(course_data_js)

            logger.info("✓ Course data JavaScript created successfully")

        except Exception as e:
            logger.error(f"Failed to create course data JavaScript: {e}")
            raise Exception(f"Course data creation failed: {str(e)}")

    # ── Theme CSS Generation ─────────────────────────────────────────────

    _HEX_RE = re.compile(r'^#(?:[0-9a-fA-F]{3,4}){1,2}$')
    _SAFE_FONT_RE = re.compile(
        r"^[\w\s,'\".-]+$"
    )

    def _sanitize_css_value(self, value: str) -> Optional[str]:
        """Validate a CSS property value to prevent injection."""
        if not isinstance(value, str):
            return None
        value = value.strip()
        if not value or len(value) > 200:
            return None
        # Block semicolons, braces, url(), expression(), @import, etc.
        dangerous = re.compile(r'[;{}]|url\s*\(|expression\s*\(|@import|javascript:', re.I)
        if dangerous.search(value):
            return None
        return value

    def _sanitize_color(self, value: str) -> Optional[str]:
        """Accept only valid hex colours."""
        if isinstance(value, str) and self._HEX_RE.match(value.strip()):
            return value.strip()
        return None

    def _generate_theme_css(self, theme_bundle: Optional[Dict[str, Any]]) -> str:
        """
        Generate CSS custom properties from a resolved theme bundle.

        Returns a CSS string with :root variables plus optional
        per-page and per-component scoped overrides.
        """
        if not theme_bundle:
            return ""

        lines: List[str] = []

        # --- Course-level :root variables ---
        course_theme = theme_bundle.get("courseTheme", {})
        colors = course_theme.get("colors", {})
        typo = course_theme.get("typography", {})

        root_vars: List[str] = []
        color_map = {
            "primary": "--theme-primary",
            "secondary": "--theme-secondary",
            "accent": "--theme-accent",
            "background": "--theme-background",
            "surface": "--theme-surface",
            "text": "--theme-text",
            "textSecondary": "--theme-text-secondary",
            "border": "--theme-border",
            "success": "--theme-success",
            "warning": "--theme-warning",
            "error": "--theme-error",
            "info": "--theme-info",
        }
        for key, var_name in color_map.items():
            val = self._sanitize_color(colors.get(key, ""))
            if val:
                root_vars.append(f"  {var_name}: {val};")

        # Typography
        font_family = self._sanitize_css_value(str(typo.get("fontFamily", "")))
        if font_family and self._SAFE_FONT_RE.match(font_family):
            root_vars.append(f"  --theme-font-family: {font_family};")
        heading_font = self._sanitize_css_value(str(typo.get("headingFont", "")))
        if heading_font and self._SAFE_FONT_RE.match(heading_font):
            root_vars.append(f"  --theme-heading-font: {heading_font};")
        base_size = typo.get("baseFontSize")
        if isinstance(base_size, (int, float)) and 8 <= base_size <= 32:
            root_vars.append(f"  --theme-base-font-size: {int(base_size)}px;")

        if root_vars:
            lines.append(":root {")
            lines.extend(root_vars)
            lines.append("}")

        # --- Per-page overrides ---
        page_overrides = theme_bundle.get("pageOverrides", {})
        for page_id, overrides in page_overrides.items():
            page_vars = self._override_vars(overrides)
            if page_vars:
                safe_id = re.sub(r'[^a-zA-Z0-9_-]', '', str(page_id))
                lines.append(f'[data-page="{safe_id}"] {{')
                lines.extend(page_vars)
                lines.append("}")

        # --- Per-component overrides ---
        comp_overrides = theme_bundle.get("componentOverrides", {})
        for comp_id, overrides in comp_overrides.items():
            comp_vars = self._override_vars(overrides)
            if comp_vars:
                safe_id = re.sub(r'[^a-zA-Z0-9_-]', '', str(comp_id))
                lines.append(f'[data-component="{safe_id}"] {{')
                lines.extend(comp_vars)
                lines.append("}")

        return "\n".join(lines) + "\n" if lines else ""

    def _override_vars(self, overrides: dict) -> List[str]:
        """Convert a partial override dict into CSS variable assignments."""
        vars_list: List[str] = []
        color_map = {
            "primary": "--theme-primary", "secondary": "--theme-secondary",
            "accent": "--theme-accent", "background": "--theme-background",
            "surface": "--theme-surface", "text": "--theme-text",
            "textSecondary": "--theme-text-secondary", "border": "--theme-border",
            "success": "--theme-success", "warning": "--theme-warning",
            "error": "--theme-error", "info": "--theme-info",
        }
        # Could be flat { "primary": "#..." } or nested { "colors": { "primary": "#..." } }
        colors = overrides.get("colors", overrides) if isinstance(overrides, dict) else {}
        if isinstance(colors, dict):
            for key, var_name in color_map.items():
                val = self._sanitize_color(colors.get(key, ""))
                if val:
                    vars_list.append(f"  {var_name}: {val};")
        return vars_list

    # ── Content HTML + CSS ───────────────────────────────────────────────

    async def _create_content_html(
        self, package_dir: Path, course: Course,
        theme_bundle: Optional[Dict[str, Any]] = None,
    ) -> None:
        """FIX #1 & #2: Unified player with proper script loading"""
        try:
            # Validate inputs
            if not package_dir or not package_dir.exists():
                raise ValueError(f"Invalid package directory: {package_dir}")
            if not course or not hasattr(course, 'templates'):
                raise ValueError("Invalid course object or missing templates")

            num_pages = len(course.templates)
            if num_pages == 0:
                raise ValueError("Course must have at least one template")

            # FIX #8: Comprehensive template validation before rendering
            await self._validate_templates_for_scorm(course.templates)

            course_title_safe = self._escape_html(course.title)

            html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <title>{course_title_safe}</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <div id="scorm-player">
        <header class="player-header">
            <h1 id="course-title">{course_title_safe}</h1>
            <div class="progress-container">
                <div class="progress-bar">
                    <div id="progress-fill" class="progress-fill"></div>
                </div>
                <span id="progress-text" class="progress-text">0%</span>
            </div>
        </header>

        <main class="player-content">
            <div id="slide-container" class="slide-container">
                <div class="loading"><p>Loading...</p></div>
            </div>
        </main>

        <footer class="player-controls">
            <button id="prev-btn" class="nav-btn" disabled>← Prev</button>
            <span id="slide-counter">1 of {num_pages}</span>
            <button id="next-btn" class="nav-btn">Next →</button>
            <button id="finish-btn" class="finish-btn" style="display:none;">
                Finish
            </button>
        </footer>
    </div>

    <!-- Scripts in correct order with defer -->
    <script src="scorm_wrapper.js" defer></script>
    <script src="course_data.js" defer></script>

    <script defer>
    // ============================================
    // PRODUCTION-GRADE PLAYER INITIALIZATION
    // ============================================

    var Player = {{
        state: {{
            currentSlide: 0,
            totalSlides: {num_pages},
            courseData: null,
            initialized: false,
            quizAnswers: {{}},
            finalAssessmentSubmissions: {{}},
            scormReady: false,
            scopedStyleEl: null
        }},

        // FIX: Promise-based initialization with timeout
        init: async function() {{
            console.log('Player: Starting initialization...');

            try {{
                // Wait for courseData with 5-second timeout
                await this.waitForCourseData(5000);

                // Validate courseData structure
                if (!this.validateCourseData()) {{
                    throw new Error('Invalid course data structure');
                }}

                // Initialize SCORM and restore progress
                this.state.scormReady = SCORM.initialize();
                var savedSlide = SCORM.restoreProgress(this.state.totalSlides);
                this.state.currentSlide = Math.min(savedSlide, this.state.totalSlides - 1);

                // DEBUG: Check objectives after initialization
                console.log('DEBUG: Checking objectives after initialization...');
                var objectivesAfterInit = SCORM.getAllObjectivesStatus(this.state.totalSlides);
                console.log('DEBUG: Objectives after init:', objectivesAfterInit);

                // Load first slide
                this.loadSlide(this.state.currentSlide);
                this.updateNavigation();
                this.updateProgress();

                this.state.initialized = true;
                console.log('✓ Player initialized successfully');
                return true;

            }} catch (error) {{
                console.error('❌ Player initialization failed:', error);
                this.showError('Failed to load course: ' + error.message);
                return false;
            }}
        }},

        // FIX: Wait for courseData to be available
        waitForCourseData: function(timeoutMs) {{
            return new Promise((resolve, reject) => {{
                var startTime = Date.now();

                var checkData = () => {{
                    if (typeof courseData !== 'undefined' && courseData.templates) {{
                        console.log('✓ courseData ready, slides:', courseData.templates.length);
                        resolve();
                    }} else if (Date.now() - startTime > timeoutMs) {{
                        reject(new Error('Timeout waiting for course data'));
                    }} else {{
                        setTimeout(checkData, 100);  // Check every 100ms
                    }}
                }};

                checkData();
            }});
        }},

        // FIX: Comprehensive data validation
        validateCourseData: function() {{
            if (!courseData || typeof courseData !== 'object') {{
                console.error('courseData is not an object:', courseData);
                return false;
            }}

            if (!courseData.templates || !Array.isArray(courseData.templates)) {{
                console.error('courseData.templates missing or not array:', courseData.templates);
                return false;
            }}

            if (courseData.templates.length === 0) {{
                console.error('No templates in courseData');
                return false;
            }}

            this.state.totalSlides = courseData.templates.length;
            this.state.courseData = courseData;
            return true;
        }},

        // FIX: Error boundaries in loadSlide
        loadSlide: function(index) {{
            try {{
                console.log('Loading slide:', index + 1, 'of', this.state.totalSlides);

                if (index < 0 || index >= this.state.totalSlides) {{
                    throw new Error('Invalid slide index: ' + index);
                }}

                var slide = this.state.courseData.templates[index];
                if (!slide) {{
                    throw new Error('Slide ' + index + ' not found in course data');
                }}

                var content = '';
                try {{
                    var renderer = this.getRenderer(slide.type);
                    if (!renderer) {{
                        content = this.renderUnknown(slide);
                    }} else {{
                        content = renderer.call(this, slide, index);
                    }}
                }} catch (renderError) {{
                    console.error('Render error for slide', index, ':', renderError);
                    content = '<div class="slide error"><p>Failed to render slide: ' +
                             this.sanitize(renderError.message) + '</p></div>';
                }}

                var container = document.getElementById('slide-container');
                if (!container) {{
                    throw new Error('Slide container element not found');
                }}

                container.innerHTML = content;

                // Apply scoping data attributes for theme override CSS
                if (slide.pageId) {{
                    container.setAttribute('data-page', slide.pageId);
                }}
                if (slide.id) {{
                    container.setAttribute('data-component', slide.id);
                }}

                this.applyScopedCustomCss(slide);

                this.state.currentSlide = index;

                // Mark as viewed and save progress (but don't mark as completed here)
                if (this.state.scormReady) {{
                    SCORM.saveProgress(index, this.state.totalSlides);
                }}

                this.updateNavigation();
                this.updateProgress();

                console.log('✓ Slide loaded successfully');

            }} catch (error) {{
                console.error('❌ loadSlide failed:', error);
                this.showError('Error loading slide: ' + error.message);
            }}
        }},

        getRenderer: function(type) {{
            var registry = {{
                // Content / Presentation
                'content-text':          this.renderContent,
                'content':               this.renderContent,
                'rich-text-editor':      this.renderRichText,
                'content-media':         this.renderTextWithMedia,
                'content-image':         this.renderImage,
                'content-video':         this.renderVideo,
                'transcript-caption':    this.renderContent,
                'infographic':           this.renderImage,
                'quotation':             this.renderQuotation,
                // Navigation / Layout
                'tabs':                  this.renderTabs,
                'accordion':             this.renderAccordion,
                'stepper':               this.renderStepper,
                'timeline':              this.renderTimeline,
                'course-menu':           this.renderModuleOverview,
                'breadcrumb':            this.renderContent,
                'sidebar-navigation':    this.renderModuleOverview,
                // Assessment
                'mcq':                   this.renderMCQ,
                'multiple-select':       this.renderMultipleSelect,
                'true-false':            this.renderTrueFalse,
                'fill-in-blank':         this.renderFillInBlank,
                'final-assessment':      this.renderFinalAssessment,
                'hotspot':               this.renderHotspot,
                'image-hotspots':        this.renderHotspot,
                'matching':              this.renderContent,
                'drag-and-drop':         this.renderContent,
                // Knowledge Check
                'key-takeaways':         this.renderKeyTakeaways,
                'summary-takeaways':     this.renderKeyTakeaways,
                'learning-objectives':   this.renderLearningObjectives,
                'flashcard':             this.renderFlashcard,
                'quiz':                  this.renderMCQ,
                // Scenario
                'scenario':              this.renderScenario,
                'branching-scenario':    this.renderScenario,
                'decision-tree':         this.renderScenario,
                'role-play':             this.renderScenario,
                // Data & Analytics
                'metric':                this.renderMetric,
                'data-visualization':    this.renderDataTable,
                'progress-tracker':      this.renderProgressTracker,
                'analytics-view':        this.renderDataTable,
                'heat-map':              this.renderDataTable,
                // Interactive Tools
                'code-snippet':          this.renderCodeSnippet,
                'calculator':            this.renderContent,
                'form':                  this.renderContent,
                'interactive-tool':      this.renderContent,
                // Learning Path
                'learning-roadmap':      this.renderTimeline,
                'module-overview':       this.renderModuleOverview,
                'course-map':            this.renderModuleOverview,
            }};
            return registry[type] || null;
        }},

        renderUnknown: function(slide) {{
            return '<div class="slide"><p>Unknown slide type: ' +
                   this.sanitize(slide.type || 'undefined') + '</p></div>';
        }},

        renderContent: function(slide) {{
            try {{
                var data = slide.data || {{}};
                var title = this.sanitize(slide.title || 'Untitled');
                var body = this.renderRichHTML(data.content || '');
                return '<div class="template content-template">' +
                       '<h2 class="content-title">' + title + '</h2>' +
                       '<div class="content-body">' + body + '</div>' +
                       '</div>';
            }} catch (error) {{
                console.error('renderContent error:', error);
                return '<div class="template error">' +
                       '<p>Content rendering failed</p></div>';
            }}
        }},

        renderTabs: function(slide) {{
            try {{
                var data = slide.data || {{}};
                var title = this.sanitize(slide.title || 'Tabs');
                var tabs = Array.isArray(data.tabs) ? data.tabs : [];

                if (tabs.length === 0) {{
                          var fallbackBody = this.renderRichHTML(data.content || '');
                    return '<div class="template tabs-template">' +
                           '<h2 class="content-title">' + title + '</h2>' +
                           '<div class="content-body">' + fallbackBody + '</div>' +
                           '</div>';
                }}

                var navHtml = '';
                var panelHtml = '';
                for (var i = 0; i < tabs.length; i++) {{
                    var tab = tabs[i] || {{}};
                    var tabId = this.sanitize(tab.id || ('tab-' + i));
                    var tabTitle = this.sanitize(tab.title || ('Tab ' + (i + 1)));
                    var tabBody = this.renderRichHTML(tab.body || tab.content || '');
                    var activeClass = i === 0 ? ' active' : '';
                    navHtml += '<button class="tabs-nav-btn' + activeClass + '" ' +
                               'type="button" role="tab" ' +
                               'aria-selected="' + (i === 0 ? 'true' : 'false') + '" ' +
                               'aria-controls="tabs-panel-' + tabId + '" ' +
                               'data-action="activate-tab" data-index="' + i + '">' +
                               tabTitle + '</button>';
                    panelHtml += '<div class="tabs-panel' + activeClass + '" ' +
                                                                 'id="tabs-panel-' + tabId + '" role="tabpanel">' +
                                 '<div class="content-body">' + tabBody + '</div>' +
                                 '</div>';
                }}

                return '<div class="template tabs-template">' +
                       '<h2 class="content-title">' + title + '</h2>' +
                       '<div class="tabs-nav">' + navHtml + '</div>' +
                       '<div class="tabs-panels">' + panelHtml + '</div>' +
                       '</div>';
            }} catch (error) {{
                console.error('renderTabs error:', error);
                return '<div class="template error">' +
                       '<p>Tabs rendering failed</p></div>';
            }}
        }},

        renderAccordion: function(slide) {{
            try {{
                var data = slide.data || {{}};
                var title = this.sanitize(slide.title || 'Accordion');
                var panels = Array.isArray(data.panels) ? data.panels : [];

                if (panels.length === 0) {{
                    var fallbackBody = this.renderRichHTML(data.content || '');
                    return '<div class="template accordion-template">' +
                           '<h2 class="content-title">' + title + '</h2>' +
                           '<div class="content-body">' + fallbackBody + '</div>' +
                           '</div>';
                }}

                var panelsHtml = '';
                for (var i = 0; i < panels.length; i++) {{
                    var panel = panels[i] || {{}};
                    var panelTitle = this.sanitize(panel.title || ('Section ' + (i + 1)));
                    var panelBody = this.renderRichHTML(panel.body || panel.content || '');
                    var expanded = i === 0 ? 'true' : 'false';
                    var openClass = i === 0 ? ' open' : '';

                    panelsHtml += '<div class="accordion-item' + openClass + '">' +
                                  '<button type="button" class="accordion-trigger" ' +
                                  'aria-expanded="' + expanded + '" ' +
                                  'data-action="toggle-accordion" data-index="' + i + '">' +
                                  panelTitle + '</button>' +
                                  '<div class="accordion-panel">' +
                                  '<div class="content-body">' + panelBody + '</div>' +
                                  '</div>' +
                                  '</div>';
                }}

                return '<div class="template accordion-template">' +
                       '<h2 class="content-title">' + title + '</h2>' +
                       '<div class="accordion-list">' + panelsHtml + '</div>' +
                       '</div>';
            }} catch (error) {{
                console.error('renderAccordion error:', error);
                return '<div class="template error"><p>Accordion rendering failed</p></div>';
            }}
        }},

        // ──────────────────────────────────────────────────────────────
        // EXTENDED RENDERER REGISTRY
        // ──────────────────────────────────────────────────────────────

        renderRichText: function(slide) {{
            try {{
                var data = slide.data || {{}};
                var body = this.renderRichHTML(data.htmlContent || data.content || '');
                return '<div class="template rich-text-template">' +
                       '<div class="content-body">' + body + '</div>' +
                       '</div>';
            }} catch (e) {{ return '<div class="template error"><p>Rich text render failed</p></div>'; }}
        }},

        renderQuotation: function(slide) {{
            try {{
                var data = slide.data || {{}};
                var quote = this.sanitize(data.quoteText || data.quote || '');
                var author = this.sanitize(data.author || '');
                var source = this.sanitize(data.source || '');
                var attribution = author + (source ? ' — ' + source : '');
                return '<div class="template quotation-template">' +
                       '<figure role="figure">' +
                       '<blockquote class="quotation-text">' + quote + '</blockquote>' +
                       (attribution ? '<figcaption class="quotation-attribution">— ' + attribution + '</figcaption>' : '') +
                       '</figure>' +
                       '</div>';
            }} catch (e) {{ return '<div class="template error"><p>Quotation render failed</p></div>'; }}
        }},

        renderKeyTakeaways: function(slide) {{
            try {{
                var data = slide.data || {{}};
                var title = this.sanitize(slide.title || 'Key Takeaways');
                var items = Array.isArray(data.takeaways) ? data.takeaways :
                            Array.isArray(data.items) ? data.items : [];
                var content = this.renderRichHTML(data.content || '');
                var listHtml = items.map(function(item) {{
                    var text = typeof item === 'string' ? item : (item.text || item.title || '');
                    return '<li class="takeaway-item">' + this.sanitize(text) + '</li>';
                }}.bind(this)).join('');
                return '<div class="template takeaways-template" role="region" aria-label="' + title + '">' +
                       '<h2 class="content-title">' + title + '</h2>' +
                       (content ? '<div class="content-body">' + content + '</div>' : '') +
                       (listHtml ? '<ul class="takeaways-list">' + listHtml + '</ul>' : '') +
                       '</div>';
            }} catch (e) {{ return '<div class="template error"><p>Takeaways render failed</p></div>'; }}
        }},

        renderLearningObjectives: function(slide) {{
            try {{
                var data = slide.data || {{}};
                var title = this.sanitize(slide.title || 'Learning Objectives');
                var objectives = Array.isArray(data.objectives) ? data.objectives : [];
                var listHtml = objectives.map(function(obj, i) {{
                    var text = typeof obj === 'string' ? obj : (obj.text || obj.title || obj.description || '');
                    return '<li class="objective-item">' +
                           '<span class="objective-number" aria-hidden="true">' + (i + 1) + '</span> ' +
                           this.sanitize(text) + '</li>';
                }}.bind(this)).join('');
                return '<div class="template objectives-template" role="region" aria-label="' + title + '">' +
                       '<h2 class="content-title">' + title + '</h2>' +
                       (listHtml ? '<ol class="objectives-list">' + listHtml + '</ol>' :
                        '<p class="content-body">' + this.renderRichHTML(data.content || '') + '</p>') +
                       '</div>';
            }} catch (e) {{ return '<div class="template error"><p>Objectives render failed</p></div>'; }}
        }},

        renderTextWithMedia: function(slide) {{
            try {{
                var data = slide.data || {{}};
                var title = this.sanitize(slide.title || '');
                var body = this.renderRichHTML(data.body || data.content || '');
                var mediaUrl = data.mediaUrl || '';
                var mediaType = (data.mediaType || 'image').toLowerCase();
                var position = (data.mediaPosition || 'right').toLowerCase();

                var mediaHtml = '';
                if (mediaUrl && (mediaType === 'image' || mediaType === 'video')) {{
                    if (mediaType === 'video') {{
                        mediaHtml = '<div class="twm-media">' +
                            '<video src="' + this.sanitize(mediaUrl) + '" controls class="content-video"></video>' +
                            '</div>';
                    }} else {{
                        mediaHtml = '<div class="twm-media">' +
                            '<img src="' + this.sanitize(mediaUrl) + '" alt="' + this.sanitize(slide.title || '') + '" class="content-image">' +
                            '</div>';
                    }}
                }}

                var textHtml = body ? '<div class="twm-text content-body">' + body + '</div>' : '';

                var layoutClass = 'twm-layout-' + position;
                var innerHtml;
                if (!mediaHtml) {{
                    innerHtml = textHtml;
                }} else if (position === 'top') {{
                    innerHtml = mediaHtml + textHtml;
                }} else if (position === 'bottom') {{
                    innerHtml = textHtml + mediaHtml;
                }} else if (position === 'left') {{
                    innerHtml = '<div class="twm-row ' + layoutClass + '">' + mediaHtml + textHtml + '</div>';
                }} else {{
                    innerHtml = '<div class="twm-row ' + layoutClass + '">' + textHtml + mediaHtml + '</div>';
                }}

                return '<div class="template text-with-media-template">' +
                    (title ? '<h2 class="content-title">' + title + '</h2>' : '') +
                    innerHtml +
                    '</div>';
            }} catch (e) {{
                console.error('renderTextWithMedia error:', e);
                return '<div class="template error"><p>Text with media render failed</p></div>';
            }}
        }},

        renderImage: function(slide) {{
            try {{
                var data = slide.data || {{}};
                var title = this.sanitize(slide.title || '');
                var caption = this.sanitize(data.caption || data.altText || '');
                var alt = this.sanitize(data.altText || data.caption || title || 'Course image');
                var imgSrc = data.src || data.url || '';
                if (!imgSrc && data.mediaAssetId) {{
                    imgSrc = 'assets/' + this.sanitize(String(data.mediaAssetId));
                }}
                var imgHtml = imgSrc
                    ? '<img src="' + this.sanitize(imgSrc) + '" alt="' + alt + '" class="content-image">'
                    : '<div class="image-placeholder" role="img" aria-label="' + alt + '">[Image: ' + alt + ']</div>';
                return '<div class="template image-template">' +
                       (title ? '<h2 class="content-title">' + title + '</h2>' : '') +
                       '<figure class="image-figure">' +
                       imgHtml +
                       (caption ? '<figcaption class="image-caption">' + caption + '</figcaption>' : '') +
                       '</figure>' +
                       '</div>';
            }} catch (e) {{ return '<div class="template error"><p>Image render failed</p></div>'; }}
        }},

        renderVideo: function(slide) {{
            try {{
                var data = slide.data || {{}};
                var title = this.sanitize(slide.title || '');
                var caption = this.sanitize(data.caption || '');
                var transcript = this.renderRichHTML(data.transcript || '');
                var videoSrc = data.src || data.url || '';
                if (!videoSrc && data.videoAssetId) {{
                    videoSrc = 'assets/' + this.sanitize(String(data.videoAssetId));
                }}
                var videoHtml = videoSrc
                    ? '<video src="' + this.sanitize(videoSrc) + '" controls class="content-video"' +
                      (data.autoplay ? ' autoplay muted' : '') + '>' +
                      'Your browser does not support video.</video>'
                    : '<div class="video-placeholder" role="img" aria-label="Video">[Video placeholder]</div>';
                return '<div class="template video-template">' +
                       (title ? '<h2 class="content-title">' + title + '</h2>' : '') +
                       '<div class="video-container">' + videoHtml + '</div>' +
                       (caption ? '<p class="video-caption">' + caption + '</p>' : '') +
                       (transcript ? '<details class="video-transcript"><summary>Transcript</summary>' +
                                     '<div class="transcript-body">' + transcript + '</div></details>' : '') +
                       '</div>';
            }} catch (e) {{ return '<div class="template error"><p>Video render failed</p></div>'; }}
        }},

        renderCodeSnippet: function(slide) {{
            try {{
                var data = slide.data || {{}};
                var title = this.sanitize(slide.title || '');
                var code = data.code || '';
                var lang = this.sanitize(data.language || 'text');
                var escCode = code.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
                return '<div class="template code-template">' +
                       (title ? '<h2 class="content-title">' + title + '</h2>' : '') +
                       '<div class="code-container">' +
                       '<div class="code-lang-badge">' + lang + '</div>' +
                       '<pre class="code-block" tabindex="0"><code class="lang-' + lang + '">' +
                       escCode + '</code></pre></div></div>';
            }} catch (e) {{ return '<div class="template error"><p>Code snippet render failed</p></div>'; }}
        }},

        renderMultipleSelect: function(slide, idx) {{
            try {{
                if (!slide.data || !slide.data.questions || !slide.data.questions.length) {{
                    return '<div class="template"><p>No questions available</p></div>';
                }}
                var question = slide.data.questions[0];
                var safeQ = this.sanitize(question.question || 'Question');
                var previousAnswers = this.state.quizAnswers[idx];
                var hasSubmitted = Array.isArray(previousAnswers);
                var optionsHTML = '';
                if (Array.isArray(question.options)) {{
                    question.options.forEach(function(opt, i) {{
                        var safeText = this.sanitize(opt.text || ('Option ' + (i + 1)));
                        var checked = hasSubmitted && previousAnswers.indexOf(i) >= 0;
                        optionsHTML += '<label class="mcq-option">' +
                                       '<input type="checkbox" name="multi_' + idx + '" value="' + i + '" data-slide-idx="' + idx + '" data-option-idx="' + i + '"' + (checked ? ' checked' : '') + (hasSubmitted ? ' disabled' : '') + '>' +
                                       '<span class="option-text">' + safeText + '</span></label>';
                    }}.bind(this));
                }}

                var feedbackHtml = '';
                if (hasSubmitted) {{
                    var expected = (question.options || []).reduce(function(acc, option, optionIdx) {{
                        if (option && (option.isCorrect === true || option.isCorrect === 'true')) acc.push(optionIdx);
                        return acc;
                    }}, []);
                    var normalizedSelected = previousAnswers.slice().sort().join(',');
                    var normalizedExpected = expected.slice().sort().join(',');
                    var correct = normalizedSelected === normalizedExpected;
                    feedbackHtml = '<p class="' + (correct ? 'ok' : 'err') + '">' +
                        (correct ? '✓ Correct!' : '✗ Incorrect') + '</p>';
                }}

                return '<div class="template mcq-template multiple-select-template">' +
                       '<p class="mcq-hint">Select all that apply</p>' +
                       '<h2 class="mcq-question">' + safeQ + '</h2>' +
                       '<div class="mcq-options">' + optionsHTML + '</div>' +
                       '<button type="button" class="submit-btn" data-action="submit-multiple-select" data-slide-idx="' + idx + '"' + (hasSubmitted ? ' disabled' : '') + '>Submit Answer</button>' +
                       '<div id="feedback-' + idx + '" class="mcq-feedback">' + feedbackHtml + '</div>' +
                       '</div>';
            }} catch (e) {{ return '<div class="template error"><p>Multiple select render failed</p></div>'; }}
        }},

        submitMultipleSelect: function(slideIdx) {{
            try {{
                var slide = this.state.courseData.templates[slideIdx];
                if (!slide || !slide.data || !slide.data.questions || !slide.data.questions.length) {{
                    return;
                }}

                var question = slide.data.questions[0];
                var options = Array.isArray(question.options) ? question.options : [];
                if (!options.length) return;

                var selectedNodes = document.querySelectorAll('input[name="multi_' + slideIdx + '"]:checked');
                var selected = [];
                selectedNodes.forEach(function(node) {{
                    selected.push(Number(node.value || 0));
                }});

                if (!selected.length) {{
                    alert('Please select at least one option before submitting.');
                    return;
                }}

                var expected = options.reduce(function(acc, option, optionIdx) {{
                    if (option && (option.isCorrect === true || option.isCorrect === 'true')) acc.push(optionIdx);
                    return acc;
                }}, []);

                var normalizedSelected = selected.slice().sort().join(',');
                var normalizedExpected = expected.slice().sort().join(',');
                var correct = normalizedSelected === normalizedExpected;

                this.state.quizAnswers[slideIdx] = selected;

                if (this.state.scormReady) {{
                    SCORM.recordQuizAnswer('ms_' + slideIdx, normalizedSelected, correct, options);
                }}

                var feedback = document.getElementById('feedback-' + slideIdx);
                if (feedback) {{
                    feedback.innerHTML = '<p class="' + (correct ? 'ok' : 'err') + '">' +
                        (correct ? '✓ Correct!' : '✗ Incorrect') + '</p>';
                }}

                var submitBtn = document.querySelector('button[data-action="submit-multiple-select"][data-slide-idx="' + slideIdx + '"]');
                if (submitBtn) submitBtn.disabled = true;

                var controls = document.querySelectorAll('input[name="multi_' + slideIdx + '"]');
                controls.forEach(function(control) {{
                    control.disabled = true;
                }});
            }} catch (error) {{
                console.error('submitMultipleSelect error:', error);
            }}
        }},

        renderTrueFalse: function(slide, idx) {{
            try {{
                if (!slide.data || !slide.data.questions || !slide.data.questions.length) {{
                    return '<div class="template"><p>No questions available</p></div>';
                }}
                var question = slide.data.questions[0];
                var safeQ = this.sanitize(question.question || question.statement || 'Statement');
                var answeredIndex = this.state.quizAnswers[idx];
                var options = Array.isArray(question.options) ? question.options : [];
                if (!options.length) {{
                    options = [
                        {{'text': 'True', 'isCorrect': question.correctAnswer === true || question.correctAnswer === 'true'}},
                        {{'text': 'False', 'isCorrect': question.correctAnswer === false || question.correctAnswer === 'false'}}
                    ];
                }}
                var optHtml = '';
                options.forEach(function(opt, i) {{
                    var isSelected = answeredIndex === i;
                    var selectedClass = isSelected ? ' selected' : '';
                    optHtml += '<label class="mcq-option' + selectedClass + '">' +
                               '<input type="radio" name="tf_' + idx + '" value="' + i + '"' +
                               (isSelected ? ' checked' : '') +
                               ' data-change-action="select-answer" data-slide-idx="' + idx + '" data-option-idx="' + i + '">' +
                               '<span class="option-text">' + opt.text + '</span></label>';
                }}.bind(this));
                return '<div class="template mcq-template true-false-template">' +
                       '<h2 class="mcq-question">' + safeQ + '</h2>' +
                       '<div class="mcq-options">' + optHtml + '</div>' +
                       '<div id="feedback-' + idx + '" class="mcq-feedback"></div>' +
                       '</div>';
            }} catch (e) {{ return '<div class="template error"><p>True/False render failed</p></div>'; }}
        }},

        renderFillInBlank: function(slide, idx) {{
            try {{
                var data = slide.data || {{}};
                var question = this.sanitize(data.question || data.content || '');
                return '<div class="template fill-blank-template">' +
                       '<h2 class="content-title">' + this.sanitize(slide.title || 'Fill in the Blank') + '</h2>' +
                       '<p class="mcq-question">' + question + '</p>' +
                       '<div class="fill-blank-input">' +
                       '<input type="text" class="blank-input" placeholder="Type your answer..." ' +
                       'aria-label="Answer" id="fib-input-' + idx + '">' +
                       '<button type="button" class="submit-btn" ' +
                       'data-action="check-fill-blank" data-slide-idx="' + idx + '">' +
                       'Check Answer</button></div>' +
                       '<div id="feedback-' + idx + '" class="mcq-feedback"></div>' +
                       '</div>';
            }} catch (e) {{ return '<div class="template error"><p>Fill-in-blank render failed</p></div>'; }}
        }},

        checkFillBlank: function(idx) {{
            try {{
                var input = document.getElementById('fib-input-' + idx);
                var fb = document.getElementById('feedback-' + idx);
                if (!input || !fb) return;
                var slide = this.state.courseData.templates[idx];
                var answers = (slide && slide.data && slide.data.correctAnswers) || [];
                var val = (input.value || '').trim().toLowerCase();
                var correct = answers.some(function(a) {{
                    var s = typeof a === 'string' ? a : (a.text || '');
                    var caseSensitive = slide.data && slide.data.caseSensitive;
                    return caseSensitive ? s === input.value.trim() : s.toLowerCase() === val;
                }});
                this.state.quizAnswers[idx] = val;

                if (this.state.scormReady) {{
                    SCORM.recordQuizAnswer('fib_' + idx, val, correct, []);
                }}

                fb.innerHTML = '<p class="' + (correct ? 'ok' : 'err') + '">' +
                               (correct ? '✓ Correct!' : '✗ Incorrect') + '</p>';
            }} catch (e) {{ console.error('checkFillBlank error:', e); }}
        }},

        renderFinalAssessment: function(slide, idx) {{
            try {{
                var data = slide.data || {{}};
                var title = this.sanitize(slide.title || 'Final Assessment');
                var intro = this.renderRichHTML(data.introText || data.content || '');
                var questions = Array.isArray(data.questions) ? data.questions : [];
                var submission = this.state.finalAssessmentSubmissions[idx];

                if (!questions.length) {{
                    return '<div class="template final-assessment-template">' +
                           '<h2 class="content-title">' + title + '</h2>' +
                           '<p>No questions configured for this final assessment.</p>' +
                           '</div>';
                }}

                var questionsHtml = questions.map(function(question, qIdx) {{
                    var qType = (question.type || 'mcq').toLowerCase();
                    var qText = this.sanitize(question.question || ('Question ' + (qIdx + 1)));
                    var response = submission && submission.answers ? submission.answers[qIdx] : null;
                    var inputHtml = '';

                    if (qType === 'fill-in-blank') {{
                        var priorValue = response && response.raw ? String(response.raw) : '';
                        inputHtml = '<input type="text" class="blank-input final-assessment-input" ' +
                            'id="fa-input-' + idx + '-' + qIdx + '" ' +
                            'value="' + this.sanitize(priorValue) + '" ' +
                            'placeholder="Type your answer...">';
                    }} else {{
                        var options = Array.isArray(question.options) ? question.options : [];
                        if (qType === 'true-false' && !options.length) {{
                            options = [
                                {{'id': 'true', 'text': 'True', 'isCorrect': question.correctAnswer === true || question.correctAnswer === 'true'}},
                                {{'id': 'false', 'text': 'False', 'isCorrect': question.correctAnswer === false || question.correctAnswer === 'false'}},
                            ];
                        }}

                        inputHtml = options.map(function(option, oIdx) {{
                            var selected = response && response.selectedIndex === oIdx;
                            return '<label class="mcq-option">' +
                                '<input type="radio" name="fa-' + idx + '-' + qIdx + '" value="' + oIdx + '"' +
                                (selected ? ' checked' : '') + '>' +
                                '<span class="option-text">' + this.sanitize(option.text || ('Option ' + (oIdx + 1))) + '</span>' +
                                '</label>';
                        }}.bind(this)).join('');
                    }}

                    return '<section class="final-assessment-question" data-qidx="' + qIdx + '">' +
                           '<h3 class="final-assessment-question-title">' + (qIdx + 1) + '. ' + qText + '</h3>' +
                           '<div class="final-assessment-question-input">' + inputHtml + '</div>' +
                           '</section>';
                }}.bind(this)).join('');

                var resultHtml = submission
                    ? '<div id="fa-result-' + idx + '" class="final-assessment-result">' +
                      '<p><strong>Score:</strong> ' + this.sanitize(String(submission.score)) + '% (' +
                      this.sanitize(String(submission.correct)) + '/' + this.sanitize(String(submission.total)) + ')</p>' +
                      '<p><strong>Passing Score:</strong> ' + this.sanitize(String(submission.passingScore)) + '%</p>' +
                      '<p><strong>Status:</strong> ' + this.sanitize(submission.passed ? 'Passed' : 'Not Passed') + '</p>' +
                      '</div>'
                    : '<div id="fa-result-' + idx + '" class="final-assessment-result"></div>';

                var disabled = submission ? ' disabled' : '';
                return '<div class="template final-assessment-template">' +
                       '<h2 class="content-title">' + title + '</h2>' +
                       (intro ? '<div class="content-body">' + intro + '</div>' : '') +
                       '<div class="final-assessment-questions">' + questionsHtml + '</div>' +
                       '<button type="button" class="submit-btn final-assessment-submit" data-action="submit-final-assessment" data-slide-idx="' + idx + '"' + disabled + '>Submit Assessment</button>' +
                       resultHtml +
                       '</div>';
            }} catch (e) {{
                console.error('renderFinalAssessment error:', e);
                return '<div class="template error"><p>Final assessment render failed</p></div>';
            }}
        }},

        submitFinalAssessment: function(slideIdx) {{
            try {{
                var slide = this.state.courseData.templates[slideIdx];
                if (!slide || !slide.data) return;

                var questions = Array.isArray(slide.data.questions) ? slide.data.questions : [];
                if (!questions.length) return;

                var answers = {{}};
                var correct = 0;
                var total = questions.length;
                var unanswered = [];

                for (var qIdx = 0; qIdx < questions.length; qIdx++) {{
                    var question = questions[qIdx] || {{}};
                    var qType = (question.type || 'mcq').toLowerCase();
                    var isCorrect = false;

                    if (qType === 'fill-in-blank') {{
                        var inputEl = document.getElementById('fa-input-' + slideIdx + '-' + qIdx);
                        var raw = inputEl && inputEl.value ? String(inputEl.value).trim() : '';
                        if (!raw) {{
                            unanswered.push(qIdx + 1);
                            continue;
                        }}

                        var accepted = Array.isArray(question.correctAnswers) ? question.correctAnswers : [];
                        var normalizedRaw = raw.toLowerCase();
                        isCorrect = accepted.some(function(answer) {{
                            return String(answer || '').trim().toLowerCase() === normalizedRaw;
                        }});

                        answers[qIdx] = {{raw: raw, correct: isCorrect}};
                        if (this.state.scormReady) {{
                            SCORM.recordQuizAnswer('fa_' + slideIdx + '_' + qIdx, normalizedRaw, isCorrect, []);
                        }}
                    }} else {{
                        var selected = document.querySelector('input[name="fa-' + slideIdx + '-' + qIdx + '"]:checked');
                        if (!selected) {{
                            unanswered.push(qIdx + 1);
                            continue;
                        }}

                        var selectedIdx = Number(selected.value || 0);
                        var options = Array.isArray(question.options) ? question.options : [];
                        if (qType === 'true-false' && !options.length) {{
                            options = [
                                {{'id': 'true', 'text': 'True', 'isCorrect': question.correctAnswer === true || question.correctAnswer === 'true'}},
                                {{'id': 'false', 'text': 'False', 'isCorrect': question.correctAnswer === false || question.correctAnswer === 'false'}},
                            ];
                        }}

                        var option = options[selectedIdx] || {{}};
                        isCorrect = option.isCorrect === true || option.isCorrect === 'true';
                        answers[qIdx] = {{selectedIndex: selectedIdx, correct: isCorrect}};

                        if (this.state.scormReady) {{
                            SCORM.recordQuizAnswer('fa_' + slideIdx + '_' + qIdx, selectedIdx, isCorrect, options);
                        }}
                    }}

                    if (isCorrect) correct++;
                }}

                if (unanswered.length) {{
                    alert('Please answer all final assessment questions before submitting. Missing: ' + unanswered.join(', '));
                    return;
                }}

                var score = Math.round((correct / total) * 100);
                var passingScore = Number(slide.data.passingScore || 80);
                var passed = score >= passingScore;

                this.state.finalAssessmentSubmissions[slideIdx] = {{
                    answers: answers,
                    correct: correct,
                    total: total,
                    score: score,
                    passingScore: passingScore,
                    passed: passed,
                }};

                if (this.state.scormReady) {{
                    SCORM.setValue('cmi.core.mastery_score', String(passingScore));
                    SCORM.setValue('cmi.core.score.raw', String(score));
                    SCORM.setValue('cmi.core.score.min', '0');
                    SCORM.setValue('cmi.core.score.max', '100');
                    SCORM.setValue('cmi.core.lesson_status', passed ? 'passed' : 'failed');
                    SCORM.commit();
                }}

                var result = document.getElementById('fa-result-' + slideIdx);
                if (result) {{
                    result.innerHTML = '<p><strong>Score:</strong> ' + this.sanitize(String(score)) + '% (' +
                        this.sanitize(String(correct)) + '/' + this.sanitize(String(total)) + ')</p>' +
                        '<p><strong>Passing Score:</strong> ' + this.sanitize(String(passingScore)) + '%</p>' +
                        '<p><strong>Status:</strong> ' + this.sanitize(passed ? 'Passed' : 'Not Passed') + '</p>';
                }}

                var submitBtn = document.querySelector('button[data-action="submit-final-assessment"][data-slide-idx="' + slideIdx + '"]');
                if (submitBtn) submitBtn.disabled = true;

                var container = document.getElementById('slide-container');
                if (container) {{
                    var controls = container.querySelectorAll('.final-assessment-template input');
                    controls.forEach(function(control) {{
                        control.disabled = true;
                    }});
                }}
            }} catch (e) {{
                console.error('submitFinalAssessment error:', e);
            }}
        }},

        renderFlashcard: function(slide) {{
            try {{
                var data = slide.data || {{}};
                var title = this.sanitize(slide.title || 'Flashcards');
                var cards = Array.isArray(data.cards) ? data.cards : [];
                if (cards.length === 0) {{
                    return '<div class="template"><p>No flashcards available</p></div>';
                }}
                var cardsHtml = cards.map(function(card, i) {{
                    var front = this.renderRichHTML(card.front || card.question || '');
                    var back = this.renderRichHTML(card.back || card.answer || '');
                          return '<div class="flashcard" id="fc-' + i + '" ' +
                              'role="button" tabindex="0" aria-pressed="false" ' +
                              'data-action="flip-card">' +
                           '<div class="flashcard-inner">' +
                           '<div class="flashcard-front"><div class="fc-label">Question</div>' + front + '</div>' +
                           '<div class="flashcard-back"><div class="fc-label">Answer</div>' + back + '</div>' +
                           '</div></div>';
                }}.bind(this)).join('');
                return '<div class="template flashcard-template">' +
                       '<h2 class="content-title">' + title + '</h2>' +
                       '<p class="fc-hint">Click or press Enter to flip each card</p>' +
                       '<div class="flashcards-grid">' + cardsHtml + '</div>' +
                       '</div>';
            }} catch (e) {{ return '<div class="template error"><p>Flashcard render failed</p></div>'; }}
        }},

        renderStepper: function(slide) {{
            try {{
                var data = slide.data || {{}};
                var title = this.sanitize(slide.title || 'Steps');
                var steps = Array.isArray(data.steps) ? data.steps : [];
                if (steps.length === 0) {{
                    return '<div class="template content-template">' +
                           '<h2 class="content-title">' + title + '</h2>' +
                           '<div class="content-body">' + this.renderRichHTML(data.content || '') + '</div></div>';
                }}
                var stepsHtml = steps.map(function(step, i) {{
                    var stepTitle = this.sanitize(step.title || step.label || ('Step ' + (i + 1)));
                    var stepBody = this.renderRichHTML(step.content || step.description || '');
                    return '<li class="stepper-item" role="listitem">' +
                           '<div class="stepper-number" aria-hidden="true">' + (i + 1) + '</div>' +
                           '<div class="stepper-content">' +
                           '<h3 class="stepper-title">' + stepTitle + '</h3>' +
                           (stepBody ? '<div class="stepper-body">' + stepBody + '</div>' : '') +
                           '</div></li>';
                }}.bind(this)).join('');
                return '<div class="template stepper-template">' +
                       '<h2 class="content-title">' + title + '</h2>' +
                       '<ol class="stepper-list" role="list">' + stepsHtml + '</ol>' +
                       '</div>';
            }} catch (e) {{ return '<div class="template error"><p>Stepper render failed</p></div>'; }}
        }},

        renderTimeline: function(slide) {{
            try {{
                var data = slide.data || {{}};
                var title = this.sanitize(slide.title || 'Timeline');
                var events = Array.isArray(data.events) ? data.events :
                             Array.isArray(data.items) ? data.items : [];
                if (events.length === 0) {{
                    return '<div class="template content-template">' +
                           '<h2 class="content-title">' + title + '</h2>' +
                           '<div class="content-body">' + this.renderRichHTML(data.content || '') + '</div></div>';
                }}
                var eventsHtml = events.map(function(evt) {{
                    var label = this.sanitize(evt.date || evt.label || evt.time || '');
                    var evtTitle = this.sanitize(evt.title || evt.name || '');
                    var desc = this.renderRichHTML(evt.description || evt.content || '');
                    return '<li class="timeline-event" role="listitem">' +
                           (label ? '<div class="timeline-label">' + label + '</div>' : '') +
                           '<div class="timeline-dot" aria-hidden="true"></div>' +
                           '<div class="timeline-content">' +
                           (evtTitle ? '<h3 class="timeline-title">' + evtTitle + '</h3>' : '') +
                           (desc ? '<div class="timeline-body">' + desc + '</div>' : '') +
                           '</div></li>';
                }}.bind(this)).join('');
                return '<div class="template timeline-template">' +
                       '<h2 class="content-title">' + title + '</h2>' +
                       '<ul class="timeline-list" role="list">' + eventsHtml + '</ul>' +
                       '</div>';
            }} catch (e) {{ return '<div class="template error"><p>Timeline render failed</p></div>'; }}
        }},

        renderMetric: function(slide) {{
            try {{
                var data = slide.data || {{}};
                var title = this.sanitize(slide.title || '');
                var metrics = Array.isArray(data.metrics) ? data.metrics :
                              [{{value: data.value, label: data.label, unit: data.unit, trend: data.trend}}];
                var metricsHtml = metrics.filter(function(m) {{ return m && m.label; }}).map(function(m) {{
                    var val = this.sanitize(String(m.value || '0'));
                    var unit = this.sanitize(m.unit || '');
                    var lbl = this.sanitize(m.label || '');
                    var trend = m.trend ? ' (' + this.sanitize(String(m.trend)) + ')' : '';
                    return '<div class="metric-card" role="figure" aria-label="' + lbl + '">' +
                           '<div class="metric-value">' + val + (unit ? '<span class="metric-unit">' + unit + '</span>' : '') + '</div>' +
                           '<div class="metric-label">' + lbl + trend + '</div>' +
                           '</div>';
                }}.bind(this)).join('');
                return '<div class="template metric-template">' +
                       (title ? '<h2 class="content-title">' + title + '</h2>' : '') +
                       '<div class="metrics-grid">' + metricsHtml + '</div>' +
                       '</div>';
            }} catch (e) {{ return '<div class="template error"><p>Metric render failed</p></div>'; }}
        }},

        renderProgressTracker: function(slide) {{
            try {{
                var data = slide.data || {{}};
                var title = this.sanitize(slide.title || data.label || 'Progress');
                var pct = Math.min(100, Math.max(0, Number(data.progress) || 0));
                var total = Number(data.total) || 100;
                var current = Number(data.current || data.progress) || 0;
                var label = this.sanitize(data.label || title);
                return '<div class="template progress-template">' +
                       '<h2 class="content-title">' + title + '</h2>' +
                       '<div class="prog-container" role="progressbar" ' +
                       'aria-valuenow="' + current + '" aria-valuemin="0" aria-valuemax="' + total + '" ' +
                       'aria-label="' + label + '">' +
                       '<div class="prog-bar"><div class="prog-fill" style="width:' + pct + '%"></div></div>' +
                       '<div class="prog-label">' + pct + '%' + (data.label ? ' — ' + label : '') + '</div>' +
                       '</div></div>';
            }} catch (e) {{ return '<div class="template error"><p>Progress tracker render failed</p></div>'; }}
        }},

        renderScenario: function(slide) {{
            try {{
                var data = slide.data || {{}};
                var title = this.sanitize(slide.title || 'Scenario');
                var text = this.renderRichHTML(data.scenarioText || data.content || '');
                var options = Array.isArray(data.options) ? data.options : [];
                var optHtml = options.map(function(opt, i) {{
                    var optText = typeof opt === 'string' ? opt : (opt.text || opt.label || '');
                    var feedback = typeof opt === 'object' ? (opt.feedback || '') : '';
                          return '<li class="scenario-option">' +
                              '<button type="button" class="scenario-btn" data-action="show-scenario-feedback" ' +
                              'data-feedback="' + this.sanitizeAttr(feedback) + '">' +
                              this.sanitize(optText) + '</button>' +
                              '</li>';
                }}.bind(this)).join('');
                return '<div class="template scenario-template">' +
                       '<h2 class="content-title">' + title + '</h2>' +
                       '<div class="scenario-text">' + text + '</div>' +
                       (optHtml ? '<ul class="scenario-options" role="list">' + optHtml + '</ul>' : '') +
                       '<div class="scenario-feedback" role="status" aria-live="polite"></div>' +
                       '</div>';
            }} catch (e) {{ return '<div class="template error"><p>Scenario render failed</p></div>'; }}
        }},

        showScenarioFeedback: function(btn, feedback) {{
            try {{
                if (!btn) return;
                var container = btn.closest('.scenario-template') || btn.parentElement;
                if (!container) return;
                var fb = container.querySelector('.scenario-feedback');
                if (fb && feedback) {{
                    fb.innerHTML = '<p class="scenario-fb-text">' + this.sanitize(feedback) + '</p>';
                }}
                var allBtns = container.querySelectorAll('.scenario-btn');
                allBtns.forEach(function(b) {{ b.setAttribute('aria-pressed', 'false'); }});
                btn.setAttribute('aria-pressed', 'true');
            }} catch (e) {{ console.error('showScenarioFeedback error:', e); }}
        }},

        renderDataTable: function(slide) {{
            try {{
                var data = slide.data || {{}};
                var title = this.sanitize(slide.title || '');
                var rows = Array.isArray(data.rows) ? data.rows :
                           (Array.isArray(data.data) ? data.data : []);
                var headers = Array.isArray(data.headers) ? data.headers :
                              (Array.isArray(data.columns) ? data.columns : []);
                if (rows.length === 0) {{
                    return '<div class="template content-template">' +
                           (title ? '<h2 class="content-title">' + title + '</h2>' : '') +
                           '<div class="content-body">' + this.renderRichHTML(data.content || '[Chart/Data]') + '</div>' +
                           '</div>';
                }}
                var theadHtml = '';
                if (headers.length > 0) {{
                    theadHtml = '<thead><tr>' +
                        headers.map(function(h) {{ return '<th scope="col">' + this.sanitize(String(h)) + '</th>'; }}.bind(this)).join('') +
                        '</tr></thead>';
                }}
                var tbodyHtml = '<tbody>' + rows.map(function(row) {{
                    var cells = Array.isArray(row) ? row : Object.values(row || {{}});
                    return '<tr>' + cells.map(function(c) {{
                        return '<td>' + this.sanitize(String(c == null ? '' : c)) + '</td>';
                    }}.bind(this)).join('') + '</tr>';
                }}.bind(this)).join('') + '</tbody>';
                return '<div class="template datatable-template">' +
                       (title ? '<h2 class="content-title">' + title + '</h2>' : '') +
                       '<div class="table-container" role="region" aria-label="Data table" tabindex="0">' +
                       '<table class="data-table">' + theadHtml + tbodyHtml + '</table>' +
                       '</div></div>';
            }} catch (e) {{ return '<div class="template error"><p>Data visualization render failed</p></div>'; }}
        }},

        renderHotspot: function(slide) {{
            try {{
                var data = slide.data || {{}};
                var title = this.sanitize(slide.title || '');
                var hotspots = Array.isArray(data.hotspots) ? data.hotspots : [];
                var imgSrc = data.src || data.url || '';
                if (!imgSrc && data.imageAssetId) {{
                    imgSrc = 'assets/' + this.sanitize(String(data.imageAssetId));
                }}
                var hsList = hotspots.map(function(hs) {{
                    var label = this.sanitize(hs.label || hs.title || 'Hotspot');
                    var desc = this.renderRichHTML(hs.description || hs.content || '');
                    return '<li class="hotspot-item"><strong>' + label + '</strong>' +
                           (desc ? ': <span>' + desc + '</span>' : '') + '</li>';
                }}.bind(this)).join('');
                return '<div class="template hotspot-template">' +
                       (title ? '<h2 class="content-title">' + title + '</h2>' : '') +
                       (imgSrc ? '<figure class="hotspot-image-figure"><img src="' + this.sanitize(imgSrc) +
                                 '" alt="' + (this.sanitize(data.altText || title || 'Interactive image')) + '" class="content-image"></figure>' : '') +
                       (hsList ? '<ul class="hotspot-list" role="list">' + hsList + '</ul>' : '') +
                       '</div>';
            }} catch (e) {{ return '<div class="template error"><p>Hotspot render failed</p></div>'; }}
        }},

        renderModuleOverview: function(slide) {{
            try {{
                var data = slide.data || {{}};
                var title = this.sanitize(slide.title || 'Module Overview');
                var desc = this.renderRichHTML(data.description || data.content || '');
                var modules = Array.isArray(data.modules) ? data.modules : [];
                var modHtml = modules.map(function(mod) {{
                    var modTitle = this.sanitize(mod.title || mod.name || '');
                    var modDesc = this.sanitize(mod.description || '');
                    return '<li class="module-item" role="listitem">' +
                           '<div class="module-title">' + modTitle + '</div>' +
                           (modDesc ? '<div class="module-desc">' + modDesc + '</div>' : '') +
                           '</li>';
                }}.bind(this)).join('');
                return '<div class="template module-overview-template" role="region" aria-label="' + title + '">' +
                       '<h2 class="content-title">' + title + '</h2>' +
                       (desc ? '<div class="content-body">' + desc + '</div>' : '') +
                       (modHtml ? '<ul class="modules-list" role="list">' + modHtml + '</ul>' : '') +
                       '</div>';
            }} catch (e) {{ return '<div class="template error"><p>Module overview render failed</p></div>'; }}
        }},

        // ──────────────────────────────────────────────────────────────

        toggleAccordion: function(panelIndex) {{
            try {{
                var container = document.getElementById('slide-container');
                if (!container) return;
                var items = container.querySelectorAll('.accordion-item');
                items.forEach(function(item, idx) {{
                    var trigger = item.querySelector('.accordion-trigger');
                    var shouldOpen = idx === panelIndex ? !item.classList.contains('open') : false;
                    if (shouldOpen) {{
                        item.classList.add('open');
                    }} else {{
                        item.classList.remove('open');
                    }}
                    if (trigger) {{
                        trigger.setAttribute('aria-expanded', shouldOpen ? 'true' : 'false');
                    }}
                }});
            }} catch (error) {{
                console.error('toggleAccordion error:', error);
            }}
        }},

        dispatchAction: function(el) {{
            if (!el) return;
            var action = el.getAttribute('data-action');
            if (!action) return;

            if (action === 'activate-tab') {{
                this.activateTab(Number(el.getAttribute('data-index') || 0));
                return;
            }}

            if (action === 'toggle-accordion') {{
                this.toggleAccordion(Number(el.getAttribute('data-index') || 0));
                return;
            }}

            if (action === 'submit-mcq') {{
                this.submitMCQAnswer(Number(el.getAttribute('data-slide-idx') || 0));
                return;
            }}

            if (action === 'submit-multiple-select') {{
                this.submitMultipleSelect(Number(el.getAttribute('data-slide-idx') || 0));
                return;
            }}

            if (action === 'check-fill-blank') {{
                this.checkFillBlank(Number(el.getAttribute('data-slide-idx') || 0));
                return;
            }}

            if (action === 'submit-final-assessment') {{
                this.submitFinalAssessment(Number(el.getAttribute('data-slide-idx') || 0));
                return;
            }}

            if (action === 'flip-card') {{
                el.classList.toggle('flipped');
                el.setAttribute('aria-pressed', el.classList.contains('flipped').toString());
                return;
            }}

            if (action === 'show-scenario-feedback') {{
                this.showScenarioFeedback(el, el.getAttribute('data-feedback') || '');
            }}
        }},

        activateTab: function(tabIndex) {{
            try {{
                var container = document.getElementById('slide-container');
                if (!container) return;

                var navBtns = container.querySelectorAll('.tabs-nav-btn');
                var panels = container.querySelectorAll('.tabs-panel');

                navBtns.forEach(function(btn, idx) {{
                    if (idx === tabIndex) {{
                        btn.classList.add('active');
                        btn.setAttribute('aria-selected', 'true');
                    }} else {{
                        btn.classList.remove('active');
                        btn.setAttribute('aria-selected', 'false');
                    }}
                }});

                panels.forEach(function(panel, idx) {{
                    if (idx === tabIndex) {{
                        panel.classList.add('active');
                    }} else {{
                        panel.classList.remove('active');
                    }}
                }});
            }} catch (error) {{
                console.error('activateTab error:', error);
            }}
        }},

        renderMCQ: function(slide, idx) {{
            try {{
                if (!slide.data || !slide.data.questions ||
                    slide.data.questions.length === 0) {{
                    return '<div class="template"><p>No questions available</p></div>';
                }}

                var question = slide.data.questions[0];
                if (!question) {{
                    return '<div class="template"><p>Invalid question data</p></div>';
                }}

                var safeQuestion = this.sanitize(question.question || 'Question');
                var answeredIndex = this.state.quizAnswers[idx];
                var hasSubmitted = typeof answeredIndex === 'number';

                var optionsHTML = '';
                if (question.options && Array.isArray(question.options)) {{
                    for (var i = 0; i < question.options.length; i++) {{
                        var option = question.options[i];
                        if (!option) continue;

                        var safeText = this.sanitize(option.text ||
                                                   'Option ' + (i + 1));
                        var isSelected = answeredIndex === i;
                        var checked = isSelected ? ' checked' : '';
                        var selectedClass = isSelected ? ' selected' : '';

                        optionsHTML += '<label class="mcq-option' + selectedClass +
                                     '">' +
                                     '<input type="radio" name="answer_' + idx +
                                     '" value="' + i +
                                     '"' + checked + (hasSubmitted ? ' disabled' : '') + '>' +
                                     '<span class="option-text">' + safeText +
                                     '</span>' +
                                     '</label>';
                    }}
                }}

                var feedbackHtml = '';
                if (hasSubmitted && question.options && question.options[answeredIndex]) {{
                    var selectedOption = question.options[answeredIndex];
                    var wasCorrect = selectedOption && (selectedOption.isCorrect === true || selectedOption.isCorrect === 'true');
                    feedbackHtml = '<p class="' + (wasCorrect ? 'ok' : 'err') + '">' +
                        (wasCorrect ? '✓ Correct!' : '✗ Incorrect') + '</p>';
                }}

                return '<div class="template mcq-template">' +
                       '<h2 class="mcq-question">' + safeQuestion + '</h2>' +
                       '<div class="mcq-options">' + optionsHTML + '</div>' +
                       '<button type="button" class="submit-btn" data-action="submit-mcq" data-slide-idx="' + idx + '"' + (hasSubmitted ? ' disabled' : '') + '>Submit Answer</button>' +
                       '<div id="feedback-' + idx + '" class="mcq-feedback">' +
                       feedbackHtml +
                       '</div>' +
                       '</div>';

            }} catch (error) {{
                console.error('❌ renderMCQ failed:', error);
                return '<div class="template error">' +
                       '<p>Failed to render question</p></div>';
            }}
        }},

        submitMCQAnswer: function(slideIdx) {{
            try {{
                var slide = this.state.courseData.templates[slideIdx];
                if (!slide || !slide.data || !slide.data.questions || !slide.data.questions.length) {{
                    return;
                }}

                var question = slide.data.questions[0];
                if (!question || !Array.isArray(question.options) || !question.options.length) {{
                    return;
                }}

                var selected = document.querySelector('input[name="answer_' + slideIdx + '"]:checked');
                if (!selected) {{
                    alert('Please select an answer before submitting.');
                    return;
                }}

                var optIdx = Number(selected.value || 0);
                var option = question.options[optIdx];
                if (!option) return;

                var correct = option.isCorrect === true || option.isCorrect === 'true';
                this.state.quizAnswers[slideIdx] = optIdx;

                if (this.state.scormReady) {{
                    SCORM.recordQuizAnswer('q_' + slideIdx, optIdx, correct, question.options);
                }}

                var fb = document.getElementById('feedback-' + slideIdx);
                if (fb) {{
                    fb.innerHTML = '<p class="' + (correct ? 'ok' : 'err') + '">' +
                        (correct ? '✓ Correct!' : '✗ Incorrect') + '</p>';
                }}

                var submitBtn = document.querySelector('button[data-action="submit-mcq"][data-slide-idx="' + slideIdx + '"]');
                if (submitBtn) submitBtn.disabled = true;

                var radioInputs = document.querySelectorAll('input[name="answer_' + slideIdx + '"]');
                radioInputs.forEach(function(input) {{
                    input.disabled = true;
                }});
            }} catch (error) {{
                console.error('submitMCQAnswer error:', error);
            }}
        }},

        selectAnswer: function(slideIdx, optIdx) {{
            try {{
                console.log('=== MCQ DEBUG: selectAnswer called ===');
                console.log('Slide index:', slideIdx, 'Option index:', optIdx);
                
                var slide = this.state.courseData.templates[slideIdx];
                if (!slide) {{
                    console.error('MCQ DEBUG: Slide not found at index', slideIdx);
                    return;
                }}
                console.log('Slide type:', slide.type, 'Title:', slide.title);
                
                if (!slide.data || !slide.data.questions) {{
                    console.error('MCQ DEBUG: Invalid slide data for slide', slideIdx, 'data:', slide.data);
                    return;
                }}

                var question = slide.data.questions[0];
                if (!question) {{
                    console.error('MCQ DEBUG: No question found in slide', slideIdx);
                    return;
                }}
                console.log('Question text:', question.question);
                
                var questionOptions = Array.isArray(question.options) ? question.options : [];
                if (slide.type === 'true-false' && !questionOptions.length) {{
                    questionOptions = [
                        {{'text': 'True', 'isCorrect': question.correctAnswer === true || question.correctAnswer === 'true'}},
                        {{'text': 'False', 'isCorrect': question.correctAnswer === false || question.correctAnswer === 'false'}},
                    ];
                }}

                if (!questionOptions.length) {{
                    console.error('MCQ DEBUG: No options found for question in slide', slideIdx);
                    return;
                }}
                console.log('Total options:', questionOptions.length);

                var option = questionOptions[optIdx];
                if (!option) {{
                    console.error('MCQ DEBUG: Option not found at index', optIdx, 'for slide', slideIdx);
                    return;
                }}
                console.log('Selected option text:', option.text);
                console.log('Raw option.isCorrect value:', option.isCorrect, 'Type:', typeof option.isCorrect);

                // Robust boolean checking for isCorrect
                var correct = false;
                if (typeof option.isCorrect === 'boolean') {{
                    correct = option.isCorrect;
                    console.log('MCQ DEBUG: isCorrect is boolean, value:', correct);
                }} else if (typeof option.isCorrect === 'string') {{
                    correct = option.isCorrect.toLowerCase() === 'true';
                    console.log('MCQ DEBUG: isCorrect is string, converted to:', correct);
                }} else {{
                    console.warn('MCQ DEBUG: Unexpected isCorrect type:', typeof option.isCorrect, 'value:', option.isCorrect);
                    correct = Boolean(option.isCorrect);
                    console.log('MCQ DEBUG: Forced boolean conversion result:', correct);
                }}

                console.log('MCQ DEBUG: Final correctness determination:', correct);
                console.log('MCQ DEBUG: Recording answer in state...');
                
                this.state.quizAnswers[slideIdx] = optIdx;
                console.log('MCQ DEBUG: Answer recorded in state.quizAnswers[' + slideIdx + '] =', optIdx);

                // Record in SCORM
                if (this.state.scormReady) {{
                    console.log('MCQ DEBUG: SCORM is ready, recording quiz answer...');
                    SCORM.recordQuizAnswer(
                        'q_' + slideIdx,
                        optIdx,
                        correct,
                        questionOptions
                    );
                    console.log('MCQ DEBUG: SCORM recording completed');
                }} else {{
                    console.warn('MCQ DEBUG: SCORM not ready, skipping SCORM recording');
                }}

                var fb = document.getElementById('feedback-' + slideIdx);
                if (fb) {{
                    var feedbackText = correct ? '✓ Correct!' : '✗ Incorrect';
                    fb.innerHTML = '<p class="' + (correct ? 'ok' : 'err') + '">' + feedbackText + '</p>';
                    console.log('MCQ DEBUG: Updated feedback element for slide', slideIdx, 'to:', feedbackText);
                }} else {{
                    console.warn('MCQ DEBUG: Feedback element not found for slide', slideIdx);
                }}

                console.log('=== MCQ DEBUG: selectAnswer completed successfully ===');

            }} catch (error) {{
                console.error('MCQ DEBUG: selectAnswer error:', error);
                console.error('MCQ DEBUG: Error stack:', error.stack);
            }}
        }},

        sanitize: function(text) {{
            if (!text) return '';
            var div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }},

        sanitizeAttr: function(text) {{
            return this.sanitize(text)
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }},

        renderRichHTML: function(value) {{
            if (!value) return '';
            var raw = String(value);
            var parser = new DOMParser();
            var doc = parser.parseFromString('<div>' + raw + '</div>', 'text/html');
            var root = doc.body.firstElementChild;
            if (!root) return this.sanitize(raw);

            var blocked = root.querySelectorAll('script,style,iframe,object,embed,link,meta');
            blocked.forEach(function(node) {{ node.remove(); }});

            var all = root.querySelectorAll('*');
            all.forEach(function(node) {{
                var attrs = Array.from(node.attributes || []);
                attrs.forEach(function(attr) {{
                    var name = String(attr.name || '').toLowerCase();
                    var val = String(attr.value || '');
                    if (name.startsWith('on')) {{
                        node.removeAttribute(attr.name);
                        return;
                    }}
                    if ((name === 'href' || name === 'src') && /^\s*javascript:/i.test(val)) {{
                        node.removeAttribute(attr.name);
                    }}
                }});
            }});

            return root.innerHTML;
        }},

        applyScopedCustomCss: function(slide) {{
            try {{
                if (this.state.scopedStyleEl && this.state.scopedStyleEl.parentNode) {{
                    this.state.scopedStyleEl.parentNode.removeChild(this.state.scopedStyleEl);
                    this.state.scopedStyleEl = null;
                }}

                var cssText = '';
                if (slide && typeof slide.customCss === 'string') {{
                    cssText = slide.customCss;
                }} else if (slide && slide.data && typeof slide.data.customCss === 'string') {{
                    cssText = slide.data.customCss;
                }}

                if (!cssText || !slide || !slide.id) return;

                var scopedCss = this.scopeCssToComponent(cssText, slide.id);
                if (!scopedCss) return;

                var styleEl = document.createElement('style');
                styleEl.type = 'text/css';
                styleEl.setAttribute('data-runtime-scoped-css', slide.id);
                styleEl.appendChild(document.createTextNode(scopedCss));
                document.head.appendChild(styleEl);
                this.state.scopedStyleEl = styleEl;
            }} catch (error) {{
                console.error('applyScopedCustomCss error:', error);
            }}
        }},

        scopeCssToComponent: function(cssText, componentId) {{
            try {{
                var raw = String(cssText || '');
                if (!raw.trim()) return '';

                var safeComponentId = String(componentId || '').replace(/[^a-zA-Z0-9_-]/g, '');
                if (!safeComponentId) return '';

                var scope = '[data-component="' + safeComponentId + '"]';
                var blocks = raw.split('}}');
                var out = [];

                for (var i = 0; i < blocks.length; i++) {{
                    var block = blocks[i].trim();
                    if (!block) continue;
                    var parts = block.split('{{');
                    if (parts.length < 2) continue;
                    var selector = parts[0].trim();
                    var body = parts.slice(1).join('{{').trim();
                    if (!selector || !body) continue;

                    if (selector.charAt(0) === '@') {{
                        out.push(selector + '{{' + body + '}}');
                    }} else {{
                        out.push(scope + ' ' + selector + ' {{' + body + '}}');
                    }}
                }}

                return out.join('\\n');
            }} catch (error) {{
                console.error('scopeCssToComponent error:', error);
                return '';
            }}
        }},

        updateNavigation: function() {{
            try {{
                var prev = document.getElementById('prev-btn');
                var next = document.getElementById('next-btn');
                var fin = document.getElementById('finish-btn');

                if (prev) prev.disabled = this.state.currentSlide === 0;

                if (this.state.currentSlide === this.state.totalSlides - 1) {{
                    if (next) next.style.display = 'none';
                    if (fin) fin.style.display = 'inline-block';
                }} else {{
                    if (next) next.style.display = 'inline-block';
                    if (fin) fin.style.display = 'none';
                }}

                var cnt = document.getElementById('slide-counter');
                if (cnt) {{
                    cnt.textContent = (this.state.currentSlide + 1) + ' of ' + this.state.totalSlides;
                }}

            }} catch (error) {{
                console.error('updateNavigation error:', error);
            }}
        }},

        updateProgress: function() {{
            try {{
                var progressFill = document.getElementById('progress-fill');
                var progressText = document.getElementById('progress-text');

                if (!progressFill || !progressText) return;

                var pct = Math.round(((this.state.currentSlide + 1) / this.state.totalSlides) * 100);
                progressFill.style.width = pct + '%';
                progressText.textContent = pct + '%';

            }} catch (error) {{
                console.error('updateProgress error:', error);
            }}
        }},

        finishCourse: function() {{
            try {{
                console.log('=== COURSE COMPLETION DEBUG: finishCourse called ===');
                
                // 1. Validate all questions answered
                var unanswered = [];
                var failedFinalAssessments = [];
                var hasFinalAssessment = false;
                if (this.state.courseData && this.state.courseData.templates) {{
                    this.state.courseData.templates.forEach((t, i) => {{
                        if (t.type === 'mcq' || t.type === 'true-false') {{
                            if (typeof this.state.quizAnswers[i] !== 'number') {{
                                unanswered.push(i + 1);
                            }}
                        }}

                        if (t.type === 'multiple-select') {{
                            if (!Array.isArray(this.state.quizAnswers[i])) {{
                                unanswered.push(i + 1);
                            }}
                        }}

                        if (t.type === 'fill-in-blank') {{
                            if (typeof this.state.quizAnswers[i] !== 'string' || !this.state.quizAnswers[i].trim()) {{
                                unanswered.push(i + 1);
                            }}
                        }}

                        if (t.type === 'final-assessment') {{
                            hasFinalAssessment = true;
                            var submission = this.state.finalAssessmentSubmissions[i];
                            if (!submission) {{
                                unanswered.push(i + 1);
                            }} else if (!submission.passed) {{
                                failedFinalAssessments.push(i + 1);
                            }}
                        }}
                    }});
                }}
                
                if (unanswered.length > 0) {{
                    alert('Please answer all questions before finishing. Unanswered slides: ' + unanswered.join(', '));
                    return;
                }}

                if (failedFinalAssessments.length > 0) {{
                    alert('Final assessment not passed on slides: ' + failedFinalAssessments.join(', ') + '. Please retake before finishing.');
                    return;
                }}

                // 2. Mark all slides as completed
                console.log('Marking all slides as completed...');
                for (var i = 0; i < this.state.totalSlides; i++) {{
                    if (this.state.scormReady) {{
                        SCORM.markSlideComplete(i, this.state.totalSlides);
                    }}
                }}
                
                // 3. Set Course Complete
                if (this.state.scormReady) {{
                    if (!hasFinalAssessment) {{
                        console.log('Setting course status to completed...');
                        SCORM.setCourseComplete();
                    }} else {{
                        console.log('Final assessment present, preserving submitted pass/fail SCORM status');
                        SCORM.commit();
                    }}
                    
                    var score = SCORM.calculateScore();
                    alert('Course Complete! Score: ' + score + '%');
                    
                    // 4. Terminate SCORM session
                    console.log('Terminating SCORM session...');
                    SCORM.terminate();
                }} else {{
                    alert('Course completed (local only)');
                }}
                
                // 5. Close Window
                try {{
                    window.close();
                    if (window.parent && window.parent !== window) {{
                        window.parent.close();
                    }}
                    if (window.top && window.top !== window) {{
                        window.top.close();
                    }}
                }} catch (e) {{
                    console.warn('Could not close window:', e);
                }}
                
            }} catch (error) {{
                console.error('COMPLETION DEBUG: finishCourse error:', error);
                alert('Course completed (with errors)');
            }}
        }},

        showError: function(msg) {{
            try {{
                var container = document.getElementById('slide-container');
                if (container) {{
                    container.innerHTML = '<div class="error">' + this.sanitize(msg) + '</div>';
                }}
            }} catch (error) {{
                console.error('showError failed:', error);
            }}
        }}
    }};

    // FIX: Async initialization on page load
    window.addEventListener('load', async function() {{
        console.log('Page loaded, starting player initialization...');
        await Player.init();
    }});

    // FIX: Event handlers with error boundaries
    document.addEventListener('DOMContentLoaded', function() {{
        try {{
            var prevBtn = document.getElementById('prev-btn');
            var nextBtn = document.getElementById('next-btn');
            var finishBtn = document.getElementById('finish-btn');

            document.addEventListener('click', function(event) {{
                var actionEl = event.target && event.target.closest
                    ? event.target.closest('[data-action]')
                    : null;
                if (!actionEl) return;
                Player.dispatchAction(actionEl);
            }});

            document.addEventListener('keydown', function(event) {{
                var key = event && event.key ? event.key : '';
                if (key !== 'Enter' && key !== ' ') return;
                var actionEl = event.target && event.target.closest
                    ? event.target.closest('[data-action]')
                    : null;
                if (!actionEl) return;
                event.preventDefault();
                Player.dispatchAction(actionEl);
            }});

            document.addEventListener('change', function(event) {{
                var el = event.target;
                if (!el || !el.getAttribute) return;
                var action = el.getAttribute('data-change-action');
                if (action !== 'select-answer') return;
                var slideIdx = Number(el.getAttribute('data-slide-idx') || 0);
                var optionIdx = Number(el.getAttribute('data-option-idx') || 0);
                Player.selectAnswer(slideIdx, optionIdx);
            }});

            if (prevBtn) {{
                prevBtn.onclick = function() {{
                    if (Player.state.currentSlide > 0) {{
                        Player.loadSlide(Player.state.currentSlide - 1);
                    }}
                }};
            }}

            if (nextBtn) {{
                nextBtn.onclick = function() {{
                    console.log('DEBUG: Next button clicked, current slide:', Player.state.currentSlide);
                    if (Player.state.currentSlide < Player.state.totalSlides - 1) {{
                        // Mark current slide as completed before navigating
                        if (Player.state.scormReady) {{
                            console.log('DEBUG: SCORM ready, marking slide complete');
                            console.log('DEBUG: Objectives before marking:', SCORM.getAllObjectivesStatus(Player.state.totalSlides));
                            SCORM.markSlideComplete(Player.state.currentSlide, Player.state.totalSlides);
                            console.log('Marked current slide', Player.state.currentSlide, 'as completed');
                            console.log('DEBUG: Objectives after marking:', SCORM.getAllObjectivesStatus(Player.state.totalSlides));
                        }} else {{
                            console.log('DEBUG: SCORM not ready, skipping objective marking');
                        }}
                        Player.loadSlide(Player.state.currentSlide + 1);
                        console.log('DEBUG: Navigated to slide:', Player.state.currentSlide + 1);
                    }}
                }};
            }}

            if (finishBtn) {{
                finishBtn.onclick = function() {{
                    Player.finishCourse();
                }};
            }}

        }} catch (error) {{
            console.error('Event handler setup failed:', error);
        }}
    }});
    </script>
</body>
</html>"""

            self._assert_no_inline_event_handlers(html_content)

            html_path = package_dir / "index.html"
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)

            # Create comprehensive styles — tokenized with CSS custom properties
            styles_css = """body { font-family: var(--theme-font-family, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif);
    margin: 0; padding: 0; background: var(--theme-surface, #f5f5f5); }
#scorm-player { max-width: 1200px; margin: 0 auto; background: var(--theme-background, white);
    min-height: 100vh; display: flex; flex-direction: column; }
.player-header { background: linear-gradient(135deg, var(--theme-primary, #667eea), var(--theme-secondary, #764ba2));
    color: white; padding: 2rem; text-align: center; }
.player-header h1 { margin: 0 0 1rem 0; font-size: 2rem;
    font-family: var(--theme-heading-font, var(--theme-font-family, inherit)); }
.progress-container { display: flex; align-items: center; gap: 1rem; }
.progress-bar { flex: 1; background: rgba(255,255,255,0.2);
    border-radius: 10px; height: 10px; overflow: hidden; }
.progress-fill { background: var(--theme-success, #10b981); height: 100%;
    transition: width 0.3s; width: 0%; }
.progress-text { min-width: 40px; }
.player-content { flex: 1; padding: 2rem; }
.template { max-width: 100%; margin: 0 auto; line-height: 1.6; }
.template h2 { color: var(--theme-text, #333); font-size: 1.8rem;
    border-bottom: 3px solid var(--theme-primary, #667eea); }
.mcq-template { background: var(--theme-surface, #f8f9fa); padding: 2rem; border-radius: 12px;
    margin: 2rem 0; }
.mcq-question { color: var(--theme-text, #2d3748); font-size: 1.5rem; margin-bottom: 1.5rem; }
.mcq-options { display: flex; flex-direction: column; gap: 1rem; }
.mcq-option { display: flex; align-items: center; background: var(--theme-background, white);
    padding: 1rem; border-radius: 8px; cursor: pointer; border: 2px solid var(--theme-border, #e2e8f0);
    transition: all 0.2s; }
.mcq-option:hover { border-color: var(--theme-primary, #667eea); background: var(--theme-surface, #f7fafc); }
.mcq-option.selected { border-color: var(--theme-success, #10b981); background: #f0fff4; }
.mcq-option input[type="radio"] { margin-right: 0.75rem; accent-color: var(--theme-primary, #667eea); }
.option-text { flex: 1; font-size: 1.1rem; color: var(--theme-text, #212121); }
.mcq-feedback { margin-top: 1.5rem; padding: 1rem; border-radius: 8px;
    font-weight: bold; }
.mcq-feedback .ok { color: #155724; background: #d4edda; border: 1px solid #c3e6cb; }
.mcq-feedback .err { color: #721c24; background: #f8d7da; border: 1px solid #f5c6cb; }
.content-template { background: var(--theme-background, white); padding: 2rem; border-radius: 12px;
    margin: 2rem 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
.content-title { color: var(--theme-text, #2d3748); font-size: 1.8rem; margin-bottom: 1.5rem;
    border-bottom: 3px solid var(--theme-primary, #667eea); padding-bottom: 0.5rem; }
.content-body { font-size: 1.1rem; line-height: 1.7; color: var(--theme-text, #212121); }
.content-body p { margin-bottom: 1rem; }
.content-body ul, .content-body ol { margin: 1rem 0; padding-left: 2rem; }
.content-body li { margin-bottom: 0.5rem; }
.content-body strong { font-weight: 600; color: var(--theme-text, #2d3748); }
.content-body em { font-style: italic; color: var(--theme-text-secondary, #4a5568); }
.tabs-template { background: var(--theme-background, white); padding: 2rem; border-radius: 12px;
    margin: 2rem 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
.tabs-nav { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1rem; }
.tabs-nav-btn { padding: 0.5rem 0.75rem; border: 1px solid var(--theme-border, #e2e8f0);
    background: var(--theme-surface, #f8f9fa); color: var(--theme-text, #212121); border-radius: 6px;
    cursor: pointer; }
.tabs-nav-btn.active { background: var(--theme-primary, #667eea); color: #fff;
    border-color: var(--theme-primary, #667eea); }
.tabs-panel { display: none; border: 1px solid var(--theme-border, #e2e8f0);
    background: var(--theme-background, #fff); border-radius: 8px; padding: 1rem; }
.tabs-panel.active { display: block; }
.accordion-template { background: var(--theme-background, white); padding: 2rem; border-radius: 12px;
    margin: 2rem 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
.accordion-list { display: flex; flex-direction: column; gap: 0.75rem; }
.accordion-item { border: 1px solid var(--theme-border, #e2e8f0); border-radius: 8px;
    background: var(--theme-surface, #f8f9fa); overflow: hidden; }
.accordion-trigger { width: 100%; text-align: left; padding: 0.9rem 1rem;
    border: none; background: transparent; color: var(--theme-text, #212121);
    font-weight: 600; cursor: pointer; }
.accordion-item.open .accordion-trigger { color: var(--theme-primary, #667eea); }
.accordion-panel { display: none; padding: 0 1rem 1rem 1rem; }
.accordion-item.open .accordion-panel { display: block; }

/* === Extended renderer styles === */
/* Quotation */
.quotation-template { padding: 2rem; background: var(--theme-surface, #f8f9fa); border-radius: 12px; }
.quotation-text { font-size: 1.4rem; font-style: italic; color: var(--theme-text, #212121);
    border-left: 4px solid var(--theme-primary, #667eea); padding-left: 1.5rem; margin: 0 0 1rem 0; }
.quotation-attribution { color: var(--theme-text-secondary, #4a5568); font-weight: 600; }
/* Takeaways / Key Points */
.takeaways-template { background: var(--theme-background, white); padding: 2rem; border-radius: 12px; }
.takeaways-list { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 0.75rem; }
.takeaway-item { padding: 0.75rem 1rem; background: var(--theme-surface, #f0f9ff);
    border-left: 4px solid var(--theme-accent, #38bdf8); border-radius: 0 8px 8px 0;
    color: var(--theme-text, #212121); }
/* Learning Objectives */
.objectives-template { background: var(--theme-background, white); padding: 2rem; border-radius: 12px; }
.objectives-list { list-style: none; padding: 0; counter-reset: obj-counter; display: flex; flex-direction: column; gap: 0.75rem; }
.objective-item { display: flex; align-items: flex-start; gap: 0.75rem; padding: 0.75rem;
    background: var(--theme-surface, #f8f9fa); border-radius: 8px; }
.objective-number { min-width: 2rem; min-height: 2rem; display: flex; align-items: center; justify-content: center;
    background: var(--theme-primary, #667eea); color: white; border-radius: 50%; font-weight: 700; font-size: 0.9rem; }
/* Images and video */
.image-template, .video-template { background: var(--theme-background, white); padding: 2rem; border-radius: 12px; }
.text-with-media-template { background: var(--theme-background, white); padding: 2rem; border-radius: 12px; }
.twm-row { display: flex; gap: 2rem; align-items: flex-start; }
.twm-layout-left .twm-media, .twm-layout-right .twm-media { flex: 0 0 45%; }
.twm-layout-left .twm-text, .twm-layout-right .twm-text { flex: 1; }
.twm-media img, .twm-media video { width: 100%; height: auto; border-radius: 8px; display: block; }
.twm-text { line-height: 1.7; }
@media (max-width: 640px) { .twm-row { flex-direction: column; } }
.image-figure, .video-container { margin: 0 0 1rem 0; }
.content-image { max-width: 100%; height: auto; border-radius: 8px; display: block; margin: 0 auto; }
.image-caption, .video-caption { color: var(--theme-text-secondary, #4a5568); text-align: center;
    font-size: 0.9rem; margin-top: 0.5rem; }
.content-video { max-width: 100%; border-radius: 8px; display: block; }
.image-placeholder { background: var(--theme-surface, #f8f9fa); border: 2px dashed var(--theme-border, #e2e8f0);
    min-height: 120px; display: flex; align-items: center; justify-content: center;
    color: var(--theme-text-secondary, #4a5568); border-radius: 8px; padding: 2rem; }
.video-placeholder { background: var(--theme-surface, #111); min-height: 200px; border-radius: 8px;
    display: flex; align-items: center; justify-content: center; color: #ccc; }
.video-transcript { margin-top: 1rem; border: 1px solid var(--theme-border, #e2e8f0); border-radius: 8px; }
.video-transcript summary { padding: 0.75rem; cursor: pointer; font-weight: 600; color: var(--theme-primary, #667eea); }
.transcript-body { padding: 1rem; border-top: 1px solid var(--theme-border, #e2e8f0); }
/* Code Snippet */
.code-template { background: var(--theme-background, white); padding: 2rem; border-radius: 12px; }
.code-container { position: relative; margin-top: 0.5rem; }
.code-lang-badge { position: absolute; top: 0.5rem; right: 0.75rem; font-size: 0.75rem;
    color: var(--theme-text-secondary, #999); font-family: monospace; }
.code-block { background: #1e1e1e; color: #d4d4d4; padding: 1.5rem 1rem; border-radius: 8px;
    overflow-x: auto; font-family: 'Courier New', Courier, monospace; font-size: 0.9rem;
    line-height: 1.6; margin: 0; white-space: pre; }
/* Stepper */
.stepper-template { background: var(--theme-background, white); padding: 2rem; border-radius: 12px; }
.stepper-list { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 0; }
.stepper-item { display: flex; gap: 1.25rem; align-items: flex-start; padding: 0 0 1.5rem 0;
    position: relative; }
.stepper-item:not(:last-child)::before { content: ''; position: absolute;
    left: 1.1rem; top: 2.5rem; width: 2px; height: calc(100% - 2.5rem);
    background: var(--theme-primary, #667eea); opacity: 0.3; }
.stepper-number { min-width: 2.25rem; min-height: 2.25rem; display: flex; align-items: center;
    justify-content: center; background: var(--theme-primary, #667eea); color: white;
    border-radius: 50%; font-weight: 700; font-size: 0.9rem; flex-shrink: 0; }
.stepper-content { flex: 1; }
.stepper-title { margin: 0 0 0.5rem 0; font-size: 1.1rem; color: var(--theme-text, #212121); }
.stepper-body { color: var(--theme-text-secondary, #4a5568); }
/* Timeline */
.timeline-template { background: var(--theme-background, white); padding: 2rem; border-radius: 12px; }
.timeline-list { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 0; position: relative; }
.timeline-list::before { content: ''; position: absolute; left: 5.5rem; top: 0; bottom: 0;
    width: 2px; background: var(--theme-primary, #667eea); opacity: 0.2; }
.timeline-event { display: flex; gap: 1rem; align-items: flex-start; padding: 0 0 1.5rem 0; }
.timeline-label { min-width: 5rem; text-align: right; font-size: 0.85rem; font-weight: 600;
    color: var(--theme-primary, #667eea); padding-top: 0.25rem; }
.timeline-dot { min-width: 1rem; min-height: 1rem; background: var(--theme-primary, #667eea);
    border-radius: 50%; border: 3px solid var(--theme-background, white);
    box-shadow: 0 0 0 2px var(--theme-primary, #667eea); margin-top: 0.35rem; flex-shrink: 0; }
.timeline-content { flex: 1; padding-bottom: 0.25rem; }
.timeline-title { margin: 0 0 0.4rem 0; font-size: 1.05rem; }
/* Metric / KPI */
.metric-template { background: var(--theme-background, white); padding: 2rem; border-radius: 12px; }
.metrics-grid { display: flex; flex-wrap: wrap; gap: 1.25rem; margin-top: 1rem; }
.metric-card { flex: 1; min-width: 160px; padding: 1.5rem; text-align: center;
    background: var(--theme-surface, #f8f9fa); border-radius: 12px;
    border: 1px solid var(--theme-border, #e2e8f0); }
.metric-value { font-size: 2.5rem; font-weight: 800; color: var(--theme-primary, #667eea); line-height: 1; }
.metric-unit { font-size: 1.2rem; font-weight: 400; margin-left: 0.25rem; }
.metric-label { margin-top: 0.5rem; color: var(--theme-text-secondary, #4a5568); font-size: 0.9rem; }
/* Progress Tracker */
.progress-template { background: var(--theme-background, white); padding: 2rem; border-radius: 12px; }
.prog-container { margin-top: 1rem; }
.prog-bar { height: 1.25rem; background: var(--theme-surface, #e2e8f0); border-radius: 99px; overflow: hidden; }
.prog-fill { height: 100%; background: var(--theme-success, #10b981); border-radius: 99px; transition: width 0.4s; }
.prog-label { margin-top: 0.5rem; color: var(--theme-text-secondary, #4a5568); font-size: 0.9rem; }
/* Flashcard */
.flashcard-template { background: var(--theme-background, white); padding: 2rem; border-radius: 12px; }
.fc-hint { color: var(--theme-text-secondary, #4a5568); font-size: 0.9rem; margin-bottom: 1rem; }
.flashcards-grid { display: flex; flex-wrap: wrap; gap: 1.25rem; }
.flashcard { flex: 1; min-width: 220px; min-height: 160px; perspective: 1000px;
    cursor: pointer; border-radius: 12px; }
.flashcard-inner { width: 100%; height: 100%; position: relative; min-height: 160px;
    transition: transform 0.5s; transform-style: preserve-3d; }
.flashcard.flipped .flashcard-inner { transform: rotateY(180deg); }
.flashcard-front, .flashcard-back { position: absolute; width: 100%; height: 100%;
    backface-visibility: hidden; border-radius: 12px; padding: 1.5rem;
    border: 1px solid var(--theme-border, #e2e8f0); display: flex; flex-direction: column; gap: 0.5rem; }
.flashcard-front { background: var(--theme-surface, #f8f9fa); }
.flashcard-back { background: var(--theme-primary, #667eea); color: white; transform: rotateY(180deg); }
.fc-label { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.1em; opacity: 0.6; font-weight: 700; }
/* Scenario */
.scenario-template { background: var(--theme-background, white); padding: 2rem; border-radius: 12px; }
.scenario-text { color: var(--theme-text, #212121); line-height: 1.7; margin-bottom: 1.5rem; }
.scenario-options { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 0.75rem; }
.scenario-btn { width: 100%; text-align: left; padding: 0.9rem 1.25rem;
    border: 2px solid var(--theme-border, #e2e8f0); border-radius: 8px; background: var(--theme-surface, #f8f9fa);
    color: var(--theme-text, #212121); cursor: pointer; transition: all 0.2s; }
.scenario-btn:hover, .scenario-btn[aria-pressed="true"] { border-color: var(--theme-primary, #667eea);
    background: color-mix(in srgb, var(--theme-primary, #667eea) 10%, transparent); }
.scenario-fb-text { padding: 0.75rem; background: var(--theme-surface, #f0f9ff);
    border-radius: 8px; border-left: 4px solid var(--theme-primary, #667eea); }
/* Multiple Select / True-False / Fill-in-Blank */
.mcq-hint { color: var(--theme-primary, #667eea); font-size: 0.9rem; font-weight: 600; margin-bottom: 0.5rem; }
.fill-blank-input { display: flex; gap: 0.75rem; align-items: center; margin-top: 1rem; flex-wrap: wrap; }
.blank-input { flex: 1; min-width: 200px; padding: 0.6rem 0.9rem;
    border: 1px solid var(--theme-border, #e2e8f0); border-radius: 6px; font-size: 1rem; }
.submit-btn { padding: 0.6rem 1.25rem; background: var(--theme-primary, #667eea); color: white;
    border: none; border-radius: 6px; cursor: pointer; font-size: 1rem; }
.submit-btn:hover { opacity: 0.9; }
.final-assessment-template { background: var(--theme-background, white); padding: 2rem; border-radius: 12px; }
.final-assessment-questions { display: flex; flex-direction: column; gap: 1rem; margin-top: 1rem; }
.final-assessment-question { border: 1px solid var(--theme-border, #e2e8f0); border-radius: 8px;
    background: var(--theme-surface, #f8f9fa); padding: 1rem; }
.final-assessment-question-title { margin: 0 0 0.75rem 0; color: var(--theme-text, #212121); }
.final-assessment-question-input { display: flex; flex-direction: column; gap: 0.6rem; }
.final-assessment-submit { margin-top: 1rem; }
.final-assessment-result { margin-top: 1rem; padding: 0.9rem; border-radius: 8px;
    background: var(--theme-surface, #f8f9fa); border: 1px solid var(--theme-border, #e2e8f0); }
/* Hotspot / Image with callouts */
.hotspot-template { background: var(--theme-background, white); padding: 2rem; border-radius: 12px; }
.hotspot-image-figure { margin: 0 0 1rem 0; }
.hotspot-list { list-style: disc; padding-left: 1.5rem; display: flex; flex-direction: column; gap: 0.5rem; }
.hotspot-item { color: var(--theme-text, #212121); }
/* Data Table */
.datatable-template { background: var(--theme-background, white); padding: 2rem; border-radius: 12px; }
.table-container { overflow-x: auto; margin-top: 1rem; border-radius: 8px;
    border: 1px solid var(--theme-border, #e2e8f0); }
.data-table { width: 100%; border-collapse: collapse; font-size: 0.95rem; }
.data-table th { background: var(--theme-surface, #f8f9fa); padding: 0.75rem 1rem;
    text-align: left; font-weight: 600; border-bottom: 2px solid var(--theme-border, #e2e8f0);
    color: var(--theme-text, #212121); }
.data-table td { padding: 0.75rem 1rem; border-bottom: 1px solid var(--theme-border, #e2e8f0);
    color: var(--theme-text, #212121); }
.data-table tr:last-child td { border-bottom: none; }
.data-table tr:nth-child(even) td { background: var(--theme-surface, #f8f9fa); }
/* Module Overview */
.module-overview-template { background: var(--theme-background, white); padding: 2rem; border-radius: 12px; }
.modules-list { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 0.75rem; margin-top: 1rem; }
.module-item { padding: 1rem; background: var(--theme-surface, #f8f9fa);
    border-radius: 8px; border: 1px solid var(--theme-border, #e2e8f0); }
.module-title { font-weight: 600; color: var(--theme-text, #212121); }
.module-desc { color: var(--theme-text-secondary, #4a5568); font-size: 0.9rem; margin-top: 0.35rem; }

.player-controls { background: var(--theme-surface, #f8f9fa); padding: 1.5rem 2rem;
    display: flex; justify-content: space-between; align-items: center; }
.nav-btn, .finish-btn { padding: 0.75rem 1.5rem; border: 2px solid var(--theme-primary, #667eea);
    background: var(--theme-background, white); color: var(--theme-primary, #667eea); border-radius: 6px; cursor: pointer;
    font-size: 1rem; font-weight: 500; transition: all 0.2s; }
.nav-btn:hover, .finish-btn:hover { background: var(--theme-primary, #667eea); color: white; }
.nav-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.finish-btn { background: var(--theme-success, #10b981); border-color: var(--theme-success, #10b981); color: white; }
.finish-btn:hover { background: var(--theme-success, #059669); }
.slide-counter { font-weight: 500; color: var(--theme-text-secondary, #4a5568); }
.error { background: #fed7d7; color: var(--theme-error, #c53030); padding: 1rem; border-radius: 6px;
    border: 1px solid #feb2b2; }
@media (max-width: 768px) {
    .player-header { padding: 1rem; }
    .player-header h1 { font-size: 1.5rem; }
    .player-content { padding: 1rem; }
    .mcq-template, .content-template, .tabs-template, .accordion-template { padding: 1rem; margin: 1rem 0; }
    .mcq-question { font-size: 1.3rem; }
    .content-title { font-size: 1.5rem; }
    .player-controls { padding: 1rem; flex-direction: column; gap: 1rem; }
    .nav-btn, .finish-btn { padding: 0.5rem 1rem; font-size: 0.9rem; }
}
@media (max-width: 480px) {
    .mcq-options { gap: 0.5rem; }
    .mcq-option { padding: 0.75rem; }
    .option-text { font-size: 1rem; }
    .progress-container { flex-direction: column; gap: 0.5rem; }
    .progress-text { min-width: auto; }
}"""

            # Prepend theme-generated CSS custom properties
            theme_css = self._generate_theme_css(theme_bundle)

            styles_path = package_dir / "styles.css"
            with open(styles_path, 'w', encoding='utf-8') as f:
                if theme_css:
                    f.write("/* === Theme: resolved from course settings === */\n")
                    f.write(theme_css)
                    f.write("\n/* === Base player styles === */\n")
                f.write(styles_css)

            logger.info("✓ Content HTML and styles created successfully")

        except Exception as e:
            logger.error(f"Failed to create content HTML: {e}")
            raise Exception(f"Content HTML creation failed: {str(e)}")
    
    async def _create_scorm_wrapper(self, package_dir: Path,
                                   course: Course) -> None:
        """FIX #2 & #4: Production-grade SCORM wrapper"""
        try:
            # Validate inputs
            if not package_dir or not package_dir.exists():
                raise ValueError(f"Invalid package directory: {package_dir}")
            if not course:
                raise ValueError("Invalid course object")

            scorm_js = """// SCORM 1.2 API WRAPPER - Production with Mock API Fallback
var SCORM = {
    version: "1.2",
    initialized: false,
    sessionData: {
        answers: {}, 
        visitedSlides: [], // Track visited slides locally
        startTime: null
    },

    initialize: function() {
        if (this.initialized) return true; // Prevent double initialization
        
        try {
            var API = this.getAPI();
            if (!API) {
                console.log('No LMS API found, using Mock API for testing');
                this.mockMode = true;
                this.mockStorage = this.getMockStorage();
                this.sessionData.startTime = new Date();
                this.initialized = true;
                console.log('✓ Mock SCORM initialized');
                return true;
            }

            var r = API.LMSInitialize("");
            if (r !== "true") return false;
            
            // CRITICAL FIX: Only set to 'incomplete' if no status exists yet
            var currentStatus = API.LMSGetValue("cmi.core.lesson_status");
            if (!currentStatus || currentStatus === "" || currentStatus === "not attempted") {
                API.LMSSetValue("cmi.core.lesson_status", "incomplete");
                console.log('✓ SCORM initialized - status set to incomplete');
            } else {
                console.log('✓ SCORM initialized - preserving existing status:', currentStatus);
            }

            // RESTORE SESSION DATA (Quiz Answers & Visited Slides) from suspend_data
            var suspendData = API.LMSGetValue("cmi.suspend_data");
            if (suspendData && suspendData !== "") {
                try {
                    var parsed = JSON.parse(suspendData);
                    if (parsed) {
                        if (parsed.answers) this.sessionData.answers = parsed.answers;
                        if (parsed.visitedSlides) this.sessionData.visitedSlides = parsed.visitedSlides;
                        console.log('✓ Restored session data. Visited:', this.sessionData.visitedSlides.length);
                    }
                } catch (e) {
                    console.warn('Failed to parse suspend_data:', e);
                }
            }
            
            this.sessionData.startTime = new Date();
            this.initialized = true;
            return true;
        } catch (e) {
            console.error('SCORM init:', e);
            return false;
        }
    },

    getAPI: function() {
        var win = window;
        var maxRetries = 10;
        var retryDelay = 100;  // 100ms delay between retries
        
        for (var attempt = 0; attempt < maxRetries; attempt++) {
            // Check current window
            if (win.API != null) return win.API;
            
            // Check parent windows
            while (win.API == null && win.parent != win) {
                win = win.parent;
                if (win.API != null) return win.API;
            }
            
            // Check opener window
            if (win.API == null && win.opener) {
                win = win.opener;
                if (win.API != null) return win.API;
            }
            
            // Wait before retrying
            if (attempt < maxRetries - 1) {
                var start = Date.now();
                while (Date.now() - start < retryDelay) {
                    // Busy wait for delay
                }
            }
        }
        
        return null;
    },

    getMockStorage: function() {
        try {
            var stored = localStorage.getItem('scorm_mock_data');
            return stored ? JSON.parse(stored) : {
                'cmi.core.lesson_status': 'incomplete',
                'cmi.core.score.raw': '0',
                'cmi.core.score.max': '100',
                'cmi.core.lesson_location': '0'
            };
        } catch (e) {
            console.warn('localStorage not available, using memory storage');
            return {
                'cmi.core.lesson_status': 'incomplete',
                'cmi.core.score.raw': '0',
                'cmi.core.score.max': '100',
                'cmi.core.lesson_location': '0'
            };
        }
    },

    saveMockData: function() {
        if (this.mockStorage && typeof localStorage !== 'undefined') {
            try {
                localStorage.setItem('scorm_mock_data', JSON.stringify(this.mockStorage));
            } catch (e) {
                console.warn('Failed to save mock data:', e);
            }
        }
    },

    setValue: function(p, v) {
        try {
            console.log('SCORM setValue:', p, '=', v);
            if (this.mockMode) {
                if (this.mockStorage) {
                    this.mockStorage[p] = v;
                    this.saveMockData();
                }
                console.log('Mock setValue success');
                return true;
            }

            var API = this.getAPI();
            if (!API) {
                console.error('SCORM setValue failed: API not found');
                return false;
            }
            var result = API.LMSSetValue(p, v);
            console.log('SCORM LMSSetValue result:', result);
            if (result !== "true") {
                var err = API.LMSGetLastError();
                var errString = API.LMSGetErrorString(err);
                var diagnostic = API.LMSGetDiagnostic(err);
                console.error('SCORM setValue error:', err, errString, diagnostic);
            }
            return result === "true";
        } catch (e) {
            console.error('setValue exception:', e);
            return false;
        }
    },

    getValue: function(p) {
        try {
            console.log('SCORM getValue:', p);
            if (this.mockMode) {
                var value = this.mockStorage ? this.mockStorage[p] : "";
                console.log('Mock getValue result:', value);
                return value || "";
            }

            var API = this.getAPI();
            if (!API) {
                console.error('SCORM getValue failed: API not found');
                return "";
            }
            var value = API.LMSGetValue(p);
            console.log('SCORM LMSGetValue result:', value);
            var err = API.LMSGetLastError();
            if (err !== "0") {
                 var errString = API.LMSGetErrorString(err);
                 console.error('SCORM getValue error:', err, errString);
            }
            return value || "";
        } catch (e) {
            console.error('getValue exception:', e);
            return "";
        }
    },

    commit: function() {
        try {
            console.log('SCORM commit called');
            if (this.mockMode) {
                this.saveMockData();
                console.log('Mock commit success');
                return true;
            }

            var API = this.getAPI();
            if (!API) {
                console.error('SCORM commit failed: API not found');
                return false;
            }
            var result = API.LMSCommit("");
            console.log('SCORM LMSCommit result:', result);
            if (result !== "true") {
                var err = API.LMSGetLastError();
                console.error('SCORM commit error:', err, API.LMSGetErrorString(err));
            }
            return result === "true";
        } catch (e) {
            console.error('commit exception:', e);
            return false;
        }
    },

    recordAnswer: function(qId, selIdx, correct) {
        this.sessionData.answers[qId] = {selected: selIdx, correct: correct};
        if (this.initialized) {
            this.setValue('cmi.interactions.0.id', qId);
            this.setValue('cmi.interactions.0.type', 'choice');
            this.setValue('cmi.interactions.0.student_response', selIdx);
            this.commit();
        }
    },

    // FIX: Add missing SCORM methods for LMS compatibility
    markSlideComplete: function(slideIdx, totalSlides) {
        if (this.initialized) {
            // 1. Update Local State
            if (this.sessionData.visitedSlides.indexOf(slideIdx) === -1) {
                this.sessionData.visitedSlides.push(slideIdx);
                this.saveSessionData(); // Persist immediately
                console.log('Marked slide', slideIdx, 'visited. Total visited:', this.sessionData.visitedSlides.length);
            }

            // 2. Try to update LMS Objectives (Best Effort)
            // We do this for LMSs that support it, but we don't rely on it for logic
            var objId = 'obj_' + slideIdx;
            this.setValue('cmi.objectives.' + slideIdx + '.id', objId);
            this.setValue('cmi.objectives.' + slideIdx + '.status', 'completed');
            this.setValue('cmi.objectives.' + slideIdx + '.score.raw', '100');
            this.setValue('cmi.objectives.' + slideIdx + '.score.max', '100');
            
            // 3. Check Completion based on LOCAL state
            if (totalSlides) {
                this.checkCourseCompletion(totalSlides);
            }
            
            this.commit();
        }
    },

    checkCourseCompletion: function(totalSlides) {
        if (!this.initialized) return;
        
        console.log('Checking completion. Visited:', this.sessionData.visitedSlides.length, '/', totalSlides);
        
        // ROBUST CHECK: Use local visitedSlides count
        if (this.sessionData.visitedSlides.length >= totalSlides) {
            console.log('All slides visited (local check) - marking course complete');
            this.setCourseComplete();
        } else {
            console.log('Course not yet complete. Missing slides.');
        }
    },

    recordQuizAnswer: function(qId, selIdx, correct, options) {
        if (this.initialized) {
            // Get next interaction index (track in session)
            if (!this.sessionData.interactionCount) {
                this.sessionData.interactionCount = 0;
            }
            var interactionIdx = this.sessionData.interactionCount++;
            
            // Record interaction details with correct index
            var prefix = 'cmi.interactions.' + interactionIdx;
            this.setValue(prefix + '.id', qId);
            this.setValue(prefix + '.type', 'choice');
            this.setValue(prefix + '.student_response', selIdx.toString());
            this.setValue(prefix + '.result', correct ? 'correct' : 'wrong');
            this.setValue(prefix + '.weighting', '1');
            // REMOVED: latency is NOT required in SCORM 1.2, causes errors
            
            // Set correct responses - use index 0 for correct answer pattern
            if (options && options.length > 0) {
                for (var i = 0; i < options.length; i++) {
                    if (options[i] && options[i].isCorrect) {
                        // Use .0. not .3. for the first correct response
                        this.setValue(prefix + '.correct_responses.0.pattern', i.toString());
                        break; // Only need first correct answer
                    }
                }
            }
            
            this.commit();
            
            // Also store in sessionData for score calculation
            this.sessionData.answers[qId] = {selected: selIdx, correct: correct};
            this.saveSessionData(); // Persist to suspend_data
            
            console.log('Recorded quiz answer:', qId, 'idx:', interactionIdx, 'selected:', selIdx, 'correct:', correct);
            
            // Update score immediately
            this.submitScore();
        }
    },

    calculateScore: function() {
        var correct = 0, total = 0;
        
        // Count quiz answers from sessionData (recorded during quiz interactions)
        for (var qId in this.sessionData.answers) {
            total++;
            if (this.sessionData.answers[qId].correct) correct++;
        }
        
        // If no answers in sessionData, try to get from SCORM API
        if (total === 0 && this.initialized) {
            // Try to get quiz results from SCORM interactions
            // SCORM 1.2 doesn't have a direct way to query all interactions,
            // so we'll rely on the sessionData that's populated during quiz interactions
            console.log('No quiz answers found in sessionData for scoring');
        }
        
        var score = total === 0 ? 0 : Math.round((correct / total) * 100);
        console.log('Score calculation: correct=' + correct + ', total=' + total + ', score=' + score + '%');
        return score;
    },

    submitScore: function() {
        var score = this.calculateScore();
        if (this.initialized) {
            this.setValue('cmi.core.score.raw', score);
            this.setValue('cmi.core.score.min', '0');
            this.setValue('cmi.core.score.max', '100');
            this.commit();
            console.log('Score submitted:', score);
        }
        return score;
    },

    saveProgress: function(slideIdx) {
        if (this.initialized) {
            this.setValue('cmi.core.lesson_location', slideIdx);
            this.commit();
        }
    },

    restoreProgress: function(totalSlides) {
        if (!this.initialized) return 0;
        
        var saved = this.getValue('cmi.core.lesson_location');
        var slideIndex = saved && !isNaN(saved) ? parseInt(saved) : 0;
        
        console.log('Restoring progress: saved slide index =', slideIndex, 'total slides =', totalSlides);
        
        // Mark all slides up to the saved position as completed
        // This ensures that on revisit, previously viewed slides show as completed
        if (totalSlides && totalSlides > 0) {
            for (var i = 0; i <= slideIndex && i < totalSlides; i++) {
                this.markSlideComplete(i, totalSlides);
                console.log('Marked previously viewed slide', i, 'as completed');
            }
        }
        
        return slideIndex;
    },

    setCourseComplete: function() {
        console.log('setCourseComplete called');
        if (this.initialized) {
            this.submitScore();
            // Mark all objectives as completed before setting course complete
            // Only update objectives that actually exist (have IDs)
            for (var i = 0; i < 10; i++) {
                var objId = this.getValue('cmi.objectives.' + i + '.id');
                if (objId && objId !== '') {
                    console.log('Forcing completion for objective', i, 'id:', objId);
                    this.setValue('cmi.objectives.' + i + '.status', 'completed');
                    this.setValue('cmi.objectives.' + i + '.score.raw', '100');
                    this.setValue('cmi.objectives.' + i + '.score.max', '100');
                    // REMOVED: score.scaled is NOT valid in SCORM 1.2
                } else {
                    break; // No more objectives
                }
            }
            console.log('Setting cmi.core.lesson_status to completed');
            this.setValue('cmi.core.lesson_status', 'completed');
            this.setValue('cmi.core.score.min', '0'); // Ensure min score is set
            var commitResult = this.commit();
            console.log('setCourseComplete commit result:', commitResult);
        } else {
            console.warn('setCourseComplete called but SCORM not initialized');
        }
    },

    // Helper to format time as HHHH:MM:SS.SS for SCORM 1.2
    formatTime: function(ms) {
        var h = Math.floor(ms / 3600000);
        var m = Math.floor((ms % 3600000) / 60000);
        var s = Math.floor(((ms % 3600000) % 60000) / 1000);
        var cs = Math.floor((((ms % 3600000) % 60000) % 1000) / 10);
        
        if (h < 10) h = "0" + h;
        if (m < 10) m = "0" + m;
        if (s < 10) s = "0" + s;
        if (cs < 10) cs = "0" + cs;
        
        return h + ":" + m + ":" + s + "." + cs;
    },

    terminate: function() {
        try {
            // SCORM 1.2 Requirement: Set session time and exit status before finishing
            if (this.initialized && this.sessionData.startTime) {
                var endTime = new Date();
                var totalTime = endTime - this.sessionData.startTime;
                this.setValue("cmi.core.session_time", this.formatTime(totalTime));
                
                // Set exit to 'suspend' to ensure lesson_location (bookmarking) is preserved
                this.setValue("cmi.core.exit", "suspend");
            }

            if (this.mockMode) {
                this.saveMockData();
                console.log('Mock SCORM terminated');
            } else {
                var API = this.getAPI();
                if (API) API.LMSFinish("");
            }
            this.initialized = false;
        } catch (e) {
            console.error('terminate error:', e);
        }
    },

    // Enhanced debugging methods
    getDebugInfo: function() {
        return {
            initialized: this.initialized,
            mockMode: this.mockMode,
            sessionData: this.sessionData,
            mockStorage: this.mockStorage,
            apiAvailable: !!this.getAPI()
        };
    },

    // DEBUG: Check current objective status
    getObjectiveStatus: function(slideIdx) {
        if (!this.initialized) return 'not_initialized';
        
        var objId = 'obj_' + slideIdx;
        var status = this.getValue('cmi.objectives.' + slideIdx + '.status');
        var id = this.getValue('cmi.objectives.' + slideIdx + '.id');
        
        console.log('DEBUG: Objective', slideIdx, '- ID:', id, 'Status:', status);
        return {id: id, status: status, expectedId: objId};
    },

    // DEBUG: Check all objectives status
    getAllObjectivesStatus: function(totalSlides) {
        if (!this.initialized) return [];
        
        var objectives = [];
        for (var i = 0; i < totalSlides; i++) {
            objectives.push(this.getObjectiveStatus(i));
        }
        return objectives;
    },

    // DEBUG: Force refresh of objective data (for testing)
    refreshObjectives: function(totalSlides) {
        if (!this.initialized) return false;
        
        console.log('DEBUG: Refreshing objectives for', totalSlides, 'slides');
        for (var i = 0; i < totalSlides; i++) {
            var objId = 'obj_' + i;
            var currentId = this.getValue('cmi.objectives.' + i + '.id');
            var currentStatus = this.getValue('cmi.objectives.' + i + '.status');
            
            console.log('DEBUG: Slide', i, '- Current ID:', currentId, 'Expected ID:', objId, 'Status:', currentStatus);
            
            // Re-set the objective data if needed
            if (currentId !== objId) {
                console.log('DEBUG: Re-setting objective ID for slide', i);
                this.setValue('cmi.objectives.' + i + '.id', objId);
            }
            
            // Ensure status is set
            if (currentStatus !== 'completed') {
                console.log('DEBUG: Re-setting objective status for slide', i, 'to completed');
                this.setValue('cmi.objectives.' + i + '.status', 'completed');
                this.setValue('cmi.objectives.' + i + '.score.raw', '100');
                this.setValue('cmi.objectives.' + i + '.score.max', '100');
            }
        }
        
        this.commit();
        console.log('DEBUG: Objectives refreshed and committed');
        return true;
    },

    // Helper to persist session data
    saveSessionData: function() {
        if (this.initialized) {
            try {
                var dataStr = JSON.stringify({
                    answers: this.sessionData.answers,
                    visitedSlides: this.sessionData.visitedSlides
                });
                this.setValue("cmi.suspend_data", dataStr);
            } catch (e) {
                console.error('Failed to save session data:', e);
            }
        }
    },
};
window.addEventListener('load', () => SCORM.initialize());
window.addEventListener('unload', () => SCORM.terminate());
console.log('✓ SCORM wrapper with Mock API loaded');
"""

            scorm_path = package_dir / "scorm_wrapper.js"
            with open(scorm_path, 'w', encoding='utf-8') as f:
                f.write(scorm_js)

            logger.info("✓ SCORM wrapper created successfully")

        except Exception as e:
            logger.error(f"Failed to create SCORM wrapper: {e}")
            raise Exception(f"SCORM wrapper creation failed: {str(e)}")

    def _resolve_asset_source_path(self, raw_path: str) -> Path:
        """Resolve an asset path into a concrete local filesystem path."""
        if not raw_path:
            raise ValueError("Asset path is empty")

        media_root = Path("media").resolve()

        # Absolute path support (must stay under workspace/media).
        if os.path.isabs(raw_path):
            candidate = Path(raw_path).resolve()
            if candidate.exists():
                return candidate

        # API URL format from media endpoints.
        api_prefix = "/api/v1/media/files/"
        if raw_path.startswith(api_prefix):
            relative = raw_path[len(api_prefix):].lstrip("/")
            candidate = (media_root / relative).resolve()
            if str(candidate).startswith(str(media_root)) and candidate.exists():
                return candidate

        # Relative media path stored by upload response.
        relative_candidate = (media_root / raw_path.lstrip("/")).resolve()
        if (
            str(relative_candidate).startswith(str(media_root))
            and relative_candidate.exists()
        ):
            return relative_candidate

        # Last resort: relative to current workspace.
        workspace_candidate = Path(raw_path).expanduser().resolve()
        if workspace_candidate.exists():
            return workspace_candidate

        raise FileNotFoundError(f"Asset file not found for path '{raw_path}'")
    
    async def _copy_assets(self, package_dir: Path, assets: List[Any]) -> None:
        """Copy real asset files into the package and fail on invalid assets."""
        try:
            # Validate inputs
            if not package_dir or not package_dir.exists():
                raise ValueError(f"Invalid package directory: {package_dir}")
            if not assets:
                logger.info("No assets to copy")
                return

            assets_dir = package_dir / "assets"
            assets_dir.mkdir(exist_ok=True)

            copied_count = 0
            seen_target_names = set()
            copy_errors = []
            for index, asset in enumerate(assets):
                try:
                    if not hasattr(asset, "path"):
                        raise ValueError(
                            f"Asset at index {index} is missing 'path'"
                        )

                    source_path = self._resolve_asset_source_path(asset.path)
                    filename = os.path.basename(source_path.name)
                    if not filename:
                        raise ValueError(
                            f"Asset path '{asset.path}' has no filename"
                        )

                    if filename in seen_target_names:
                        raise ValueError(
                            f"Duplicate asset filename '{filename}' in package"
                        )
                    seen_target_names.add(filename)

                    target_path = assets_dir / filename
                    shutil.copy2(source_path, target_path)
                    copied_count += 1

                except Exception as e:
                    asset_name = getattr(asset, "name", f"asset_{index}")
                    copy_errors.append(f"{asset_name}: {e}")

            if copy_errors:
                raise ValueError(
                    "Asset copy failed: " + "; ".join(copy_errors)
                )

            logger.info(f"✓ Copied {copied_count} asset files")

        except Exception as e:
            logger.error(f"Failed to copy assets: {e}")
            raise Exception(f"Asset copying failed: {str(e)}")

    async def _package_assets(self, package_dir: Path, assets: List[Any]) -> Dict[str, Any]:
        """Package assets deterministically and write asset_manifest.json."""
        try:
            if not package_dir or not package_dir.exists():
                raise ValueError(f"Invalid package directory: {package_dir}")
            if not assets:
                return {}

            packager = AssetPackager(self._resolve_asset_source_path)
            self.packaged_assets = packager.package_assets(package_dir, assets)
            manifest = packager.write_asset_manifest(package_dir, self.packaged_assets)

            logger.info(
                "✓ Packaged %s assets and wrote asset_manifest.json",
                len(self.packaged_assets),
            )
            return manifest
        except Exception as e:
            logger.error(f"Failed to package assets deterministically: {e}")
            raise Exception(f"Asset packaging failed: {str(e)}")

    def _remove_legacy_runtime_files(self, package_dir: Path) -> None:
        """Remove stale runtime artifacts so ZIP ships one canonical runtime set."""
        legacy_files = [
            "index_legacy.html",
            "player.js",
            "runtime.js",
            "course_data_legacy.js",
            "styles_legacy.css",
            "styles_v2.css",
            "course_data_v2.js",
        ]

        removed = 0
        for filename in legacy_files:
            candidate = package_dir / filename
            if candidate.exists() and candidate.is_file():
                candidate.unlink()
                removed += 1

        # Remove legacy runtime directory if present.
        legacy_dir = package_dir / "runtime"
        if legacy_dir.exists() and legacy_dir.is_dir():
            shutil.rmtree(legacy_dir)
            removed += 1

        if removed:
            logger.info("Removed %s stale runtime artifacts", removed)
    
    async def _validate_package_structure(self, package_dir: Path) -> None:
        """
        Validate the structure of the generated package
        """
        required_files = ['imsmanifest.xml', 'course_data.js', 'index.html', 'scorm_wrapper.js']
        for filename in required_files:
            if not (package_dir / filename).exists():
                raise ValueError(f"Missing required file: {filename}")

    def _add_directory_to_zip(self, zip_file: zipfile.ZipFile, dir_path: Path, arc_name: str) -> None:
        """Recursively add directory contents to ZIP file"""
        for item in dir_path.iterdir():
            item_arc_name = f"{arc_name}/{item.name}" if arc_name else item.name
            
            if item.is_file():
                zip_file.write(item, item_arc_name)
            elif item.is_dir():
                self._add_directory_to_zip(zip_file, item, item_arc_name)
    
    def _escape_xml(self, text: str) -> str:
        """Escape special characters for XML"""
        if not text:
            return ""
        
        return (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\"", "&quot;")
                .replace("'", "&#x27;"))
    
    def _escape_html(self, text: str) -> str:
        """Escape special characters for HTML"""
        if not text:
            return ""
        
        return (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\"", "&quot;")
                .replace("'", "&#x27;"))
    
    def _escape_js_string(self, text: str) -> str:
        """
        FIX #7: Escape string for safe insertion into JavaScript
        """
        if not text:
            return ""
        
        return (text
                .replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("'", "\\'")
                .replace("\n", "\\n")
                .replace("\r", "\\r"))

    def _assert_no_inline_event_handlers(self, html_content: str) -> None:
        """Architecture guard: block inline JS event handlers in generated HTML."""
        if not html_content:
            return

        # Inline on* handlers make quote nesting fragile and unsafe.
        if re.search(r"\son[a-z]+\s*=", html_content, flags=re.IGNORECASE):
            raise ValueError(
                "Generated index.html contains inline event handlers. "
                "Use data-action + delegated listeners instead."
            )
    
    def _sanitize_text(self, text: Any) -> str:
        """
        FIX #7: Sanitize text for safe display
        Removes potentially dangerous patterns
        """
        if not text:
            return ""
        
        text_str = str(text)
        # Remove potentially dangerous patterns
        text_str = re.sub(
            r'<script[^>]*>.*?</script>',
            '',
            text_str,
            flags=re.IGNORECASE | re.DOTALL
        )
        text_str = re.sub(r'on\w+\s*=', '', text_str, flags=re.IGNORECASE)
        
        return html.escape(text_str)

    async def _exists_in_template_type_catalog(self, type_key: str) -> bool:
        """
        Fallback presence check for environments where template_definitions
        are not seeded yet but template_types is populated.
        """
        candidates = self._template_type_candidates(type_key)

        # Always accept built-in types defined by the course schema.
        if any(c in BUILTIN_TEMPLATE_TYPES for c in candidates):
            return True

        try:
            async for session in get_session():
                repo = TemplateTypeRepository(session)
                for candidate in candidates:
                    try:
                        await repo.get_by_template_id(candidate)
                        return True
                    except TemplateTypeNotFoundError:
                        continue
                return False
        except Exception as exc:
            logger.warning(
                "Template type catalog fallback failed for '%s': %s",
                type_key,
                exc,
            )
        return False

    async def _validate_templates_for_scorm(self, templates: List) -> None:
        """
        Dynamic template validation using template definitions.
        NO HARDCODED TEMPLATE LOGIC - Uses template registry.
        
        Validates that all templates have required fields based on their
        registered definition before attempting to render them in SCORM player.
        
        Args:
            templates: List of template objects to validate
            
        Raises:
            ValueError: If any template fails validation
        """
        if not templates:
            raise ValueError("No templates provided for validation")
        
        validation_errors = []
        
        for i, template in enumerate(templates):
            try:
                # Check required template attributes
                if not hasattr(template, 'type') or not template.type:
                    validation_errors.append(
                        f"Template {i+1}: Missing or empty 'type' field"
                    )
                    continue
                
                if not hasattr(template, 'title'):
                    validation_errors.append(
                        f"Template {i+1}: Missing 'title' field"
                    )
                    continue
                
                # Check if template type is registered in dynamic definitions.
                # If missing, fall back to template_types catalog so export
                # remains functional in partially migrated environments.
                definition = None
                canonical_template_type = self._canonicalize_template_type(
                    template.type
                )

                if await registry.exists(template.type):
                    definition = await registry.get(template.type)
                elif canonical_template_type != template.type and await registry.exists(
                    canonical_template_type
                ):
                    definition = await registry.get(canonical_template_type)
                else:
                    fallback_exists = await self._exists_in_template_type_catalog(
                        template.type
                    )
                    if not fallback_exists:
                        validation_errors.append(
                            f"Template {i+1} ({template.title}): "
                            f"Type '{template.type}' not registered"
                        )
                        continue
                    logger.warning(
                        "Template '%s' validated via template_types fallback; "
                        "template_definitions row is missing",
                        template.type,
                    )
                
                # Validate data exists
                if not hasattr(template, 'data') or not template.data:
                    validation_errors.append(
                        f"Template {i+1} ({template.title}): "
                        "Missing or empty data"
                    )
                    continue
                
                # Convert to dict
                try:
                    template_data = (
                        _ensure_dict(template.data)
                        if not isinstance(template.data, dict)
                        else template.data
                    )
                except ValueError as e:
                    validation_errors.append(
                        f"Template {i+1} ({template.title}): "
                        f"Data conversion failed: {str(e)}"
                    )
                    continue
                
                # Validate required fields from definition (when available).
                if definition:
                    for field in definition.field_schema:
                        if field.required and field.name not in template_data:
                            validation_errors.append(
                                f"Template {i+1} ({template.title}): "
                                f"Missing required field '{field.name}'"
                            )
                        
            except Exception as e:
                validation_errors.append(
                    f"Template {i+1}: Validation error - {str(e)}"
                )
        
        if validation_errors:
            error_msg = (
                f"Template validation failed with "
                f"{len(validation_errors)} errors:\n"
                + "\n".join(validation_errors)
            )
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        logger.info(
            f"✓ Template validation passed for {len(templates)} templates"
        )
    
    async def _sanitize_data_dynamic(self, template_type: str, data: Any) -> Dict:
        """
        Dynamic data sanitization using template-specific rules from registry.
        
        This method replaces all hardcoded template type checks with dynamic
        sanitization based on template definitions stored in the database.
        
        Args:
            template_type: Type key of the template (e.g., 'mcq', 'content-text')
            data: The template data to sanitize (dict, Pydantic model, or other)
            
        Returns:
            Sanitized dictionary safe for SCORM package inclusion
        """
        if data is None:
            return {}
        
        # Get template definition from registry
        try:
            definition = await registry.get(template_type)
        except Exception:
            definition = None
        if not definition:
            canonical_template_type = self._canonicalize_template_type(
                template_type
            )
            if canonical_template_type != template_type:
                try:
                    definition = await registry.get(canonical_template_type)
                except Exception:
                    definition = None
        if not definition:
            logger.warning(
                f"No template definition found for type '{template_type}', "
                f"using basic sanitization"
            )
            # Fallback: convert to dict and sanitize fields by content type
            data_dict = _ensure_dict(data) if not isinstance(data, dict) else data
            result = {}
            for k, v in data_dict.items():
                if isinstance(v, str):
                    if self._looks_like_html(v):
                        result[k] = self._sanitize_html_content(v)
                    else:
                        result[k] = self._sanitize_text(v)
                else:
                    result[k] = v
            return result
        
        # Convert data to dict if needed
        data_dict = _ensure_dict(data) if not isinstance(data, dict) else data
        
        # Use DynamicSanitizer with template definition
        sanitizer = DynamicSanitizer()
        sanitized = await sanitizer.sanitize_template_data(
            type_key=template_type,
            data=data_dict
        )
        
        return sanitized
    
    def _looks_like_html(self, text: str) -> bool:
        """
        Check if text content appears to be HTML
        """
        if not text or not isinstance(text, str):
            return False
        
        # Simple heuristic: check for HTML tags
        html_indicators = ['<p>', '<br', '<div', '<span', '<strong', '<em', '<h1', '<h2', '<h3', '<ul', '<ol', '<li']
        text_lower = text.lower().strip()
        
        return any(indicator in text_lower for indicator in html_indicators)
    
    def _sanitize_html_content(self, html_content: str) -> str:
        """
        FIX #4: Advanced HTML sanitization using BeautifulSoup
        Removes dangerous tags and attributes while preserving safe formatting
        
        Args:
            html_content: Raw HTML content to sanitize
            
        Returns:
            Sanitized HTML content safe for display
        """
        if not html_content or not isinstance(html_content, str):
            return ""
        
        # If BeautifulSoup is not available, fall back to basic sanitization
        if not HAS_BEAUTIFULSOUP:
            logger.warning("BeautifulSoup not available, using basic HTML sanitization")
            return self._sanitize_text(html_content)
        
        try:
            # Parse HTML with BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Define allowed tags and their allowed attributes
            allowed_tags = {
                'p', 'br', 'strong', 'b', 'em', 'i', 'u', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                'ul', 'ol', 'li', 'blockquote', 'code', 'pre', 'span', 'div', 'section',
                'table', 'thead', 'tbody', 'tr', 'th', 'td',
                'img', 'a', 'hr'
            }
            
            # Attributes always blocked regardless of tag
            blocked_attrs = {'on', 'onclick', 'onload', 'onerror', 'onmouseover',
                             'onfocus', 'onblur', 'onchange', 'onsubmit'}
            # Attributes always allowed on any tag
            safe_attrs_any = {'class', 'id', 'title', 'style'}
            # Extra per-tag allowances
            allowed_attributes = {
                'img': ['src', 'alt', 'title', 'width', 'height', 'class', 'style'],
                'a': ['href', 'title', 'class', 'style'],
                'th': ['colspan', 'rowspan', 'class', 'style'],
                'td': ['colspan', 'rowspan', 'class', 'style'],
                'table': ['border', 'cellpadding', 'cellspacing', 'class', 'style']
            }
            
            # Remove dangerous tags and attributes
            for tag in soup.find_all():
                # Remove script and style tags entirely
                if tag.name in ['script', 'style', 'iframe', 'object', 'embed']:
                    tag.decompose()
                    continue
                
                # Remove dangerous attributes
                for attr in list(tag.attrs.keys()):
                    attr_lower = attr.lower()
                    if attr_lower.startswith('on') or attr_lower in blocked_attrs:
                        del tag[attr]
                        continue
                    # Block javascript: / vbscript: in href/src
                    if attr_lower in ('href', 'src'):
                        val = str(tag.get(attr, ''))
                        if re.search(r'(javascript|vbscript|data):', val, re.IGNORECASE):
                            del tag[attr]
                            continue
                    # Allow safe_attrs_any on all tags; per-tag extras handled above
                    extra = allowed_attributes.get(tag.name, [])
                    if attr_lower not in safe_attrs_any and attr_lower not in extra:
                        del tag[attr]
                
                # Remove tags that are not in allowed list
                if tag.name not in allowed_tags:
                    tag.unwrap()  # Remove tag but keep content
            
            # Convert back to string and escape any remaining dangerous content
            sanitized = str(soup)
            
            # Additional safety: remove any remaining script-like patterns
            sanitized = re.sub(r'javascript:', '', sanitized, flags=re.IGNORECASE)
            sanitized = re.sub(r'vbscript:', '', sanitized, flags=re.IGNORECASE)
            sanitized = re.sub(r'data:', '', sanitized, flags=re.IGNORECASE)
            
            return sanitized
            
        except Exception as e:
            logger.error(f"HTML sanitization failed: {e}")
            # Fall back to basic text sanitization
            return self._sanitize_text(html_content)
    
    def estimate_package_size(self, course: Course) -> Dict[str, Any]:
        """
        Estimate the size of the generated SCORM package
        
        Args:
            course: Course data to analyze
            
        Returns:
            Dict containing size estimates
        """
        try:
            # Base SCORM structure size (manifest + HTML + JS)
            base_size = 15000  # ~15KB for base files
            
            # Estimate content size based on templates
            content_size = 0
            for template in course.templates:
                # Generic estimation based on data size (no hardcoded types)
                # Convert template data to string for size calculation
                try:
                    data_str = str(_ensure_dict(template.data))
                    content_size += len(data_str)
                except Exception:
                    # Fallback to string conversion
                    content_size += len(str(template.data))
            
            # Estimate asset sizes (placeholder values)
            asset_size = len(course.assets) * 50000  # ~50KB per asset estimate
            
            total_estimated = base_size + content_size + asset_size
            
            return {
                "base_structure_bytes": base_size,
                "content_bytes": content_size,
                "assets_bytes": asset_size,
                "total_estimated_bytes": total_estimated,
                "total_estimated_mb": round(total_estimated / 1024 / 1024, 2),
                "template_count": len(course.templates),
                "asset_count": len(course.assets)
            }
            
        except Exception as e:
            logger.error(f"Size estimation failed: {e}")
            return {"error": str(e), "total_estimated_mb": 0}

    async def validate_for_export(self, course: Course) -> Dict[str, Any]:
        """
        Validate course data before export
        
        Args:
            course: Course data to validate
            
        Returns:
            Dict with validation results
        """
        try:
            # Basic validation
            if not course:
                return {"valid": False, "errors": ["No course data provided"]}
            
            if not course.templates or len(course.templates) == 0:
                return {"valid": False, "errors": ["Course has no templates"]}
            
            # Check for required fields
            if not course.title:
                return {"valid": False, "errors": ["Course title is missing"]}
            
            # Validate templates
            await self._validate_templates_for_scorm(course.templates)

            # Runtime compatibility guard to prevent broken ZIP output.
            runtime_errors = self._validate_runtime_supported_template_types(
                course.templates
            )
            if runtime_errors:
                return {
                    "valid": False,
                    "errors": runtime_errors,
                    "warnings": [
                        "Frontend registry-driven runtime not yet active for these template types"
                    ],
                }
            
            return {
                "valid": True,
                "errors": [],
                "warnings": []
            }
            
        except Exception as e:
            logger.error(f"Validation failed: {e}")
            return {
                "valid": False,
                "errors": [f"Validation failed: {str(e)}"],
                "warnings": []
            }

    def _validate_runtime_supported_template_types(
        self,
        templates: List[Template],
    ) -> List[str]:
        """Ensure all templates are supported by the currently packaged runtime."""
        errors: List[str] = []
        for template in templates:
            template_type = str(getattr(template, "type", "")).strip()
            runtime_template_type = self._canonicalize_template_type(
                template_type
            )
            if runtime_template_type not in self.runtime_supported_template_types:
                errors.append(
                    f"Template '{getattr(template, 'id', 'unknown')}' type '{template_type}' "
                    "is not supported by current export runtime"
                )
        return errors
