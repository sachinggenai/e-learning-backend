"""Migration utilities for moving legacy export payloads to canonical export format."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Tuple


@dataclass
class MigrationReport:
    """Structured report for a single migration run."""

    migrated: bool
    course_id: str
    source_version: str
    target_version: str
    migrated_at: str
    warnings: List[str]
    changes: List[str]


class ExportMigrationService:
    """Backfill and normalize legacy course payloads for new export contract."""

    TARGET_VERSION = "1.0"

    def migrate_course_payload(self, payload: Dict[str, Any]) -> Tuple[Dict[str, Any], MigrationReport]:
        """Migrate legacy payloads into canonical export-ready shape."""
        course = dict(payload or {})
        course_id = str(course.get("courseId", "unknown"))
        warnings: List[str] = []
        changes: List[str] = []

        source_version = str(course.get("exportVersion", "legacy"))

        # Normalize pages/components from legacy templates array.
        if "pages" not in course and "templates" in course:
            templates = course.get("templates") or []
            pages: List[Dict[str, Any]] = []

            for index, template in enumerate(templates):
                template_id = str(template.get("id", f"legacy-{index}"))
                template_type = str(template.get("type", "content-text"))
                template_title = str(template.get("title", f"Slide {index + 1}"))
                template_order = int(template.get("order", index))
                template_data = template.get("data") or {}

                page_id = str(template.get("pageId") or f"page-{template_order + 1}")
                component_id = f"cmp-{template_id}"

                pages.append(
                    {
                        "pageId": page_id,
                        "title": template_title,
                        "order": template_order,
                        "layoutConfig": {},
                        "styleConfig": {},
                        "customCss": None,
                        "components": [
                            {
                                "componentId": component_id,
                                "componentType": template_type,
                                "pageId": page_id,
                                "title": template_title,
                                "order": 0,
                                "data": template_data,
                                "styleConfig": {},
                                "customCss": None,
                                "interactionConfig": None,
                                "accessibilityConfig": None,
                                "assetRefs": [],
                                "exportMetadata": {"migratedFromTemplateId": template_id},
                            }
                        ],
                    }
                )

            course["pages"] = sorted(pages, key=lambda p: int(p.get("order", 0)))
            changes.append("Converted legacy templates[] into pages[].components[]")

        # Ensure top-level export keys exist.
        if "themeTokens" not in course:
            course["themeTokens"] = {}
            changes.append("Initialized themeTokens with empty object")

        if "customCss" not in course:
            course["customCss"] = None
            changes.append("Initialized course-level customCss")

        if "assets" not in course:
            course["assets"] = []
            changes.append("Initialized assets with empty list")

        if "supportedComponentTypes" not in course:
            course["supportedComponentTypes"] = []
            warnings.append("supportedComponentTypes missing; should be populated during export build")

        course["exportVersion"] = self.TARGET_VERSION
        course["migratedAt"] = datetime.utcnow().isoformat()

        if source_version != self.TARGET_VERSION:
            changes.append(f"Upgraded exportVersion from {source_version} to {self.TARGET_VERSION}")

        report = MigrationReport(
            migrated=True,
            course_id=course_id,
            source_version=source_version,
            target_version=self.TARGET_VERSION,
            migrated_at=course["migratedAt"],
            warnings=warnings,
            changes=changes,
        )

        return course, report

    def assess_migration_risk(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Assess migration risk to help phased rollout decisions."""
        templates = payload.get("templates") or []
        pages = payload.get("pages") or []

        component_count = 0
        if pages:
            component_count = sum(len(p.get("components") or []) for p in pages)
        elif templates:
            component_count = len(templates)

        risk_level = "low"
        reasons: List[str] = []

        if component_count > 100:
            risk_level = "high"
            reasons.append("Large course with >100 components")
        elif component_count > 40:
            risk_level = "medium"
            reasons.append("Medium course with >40 components")

        if payload.get("customCss"):
            reasons.append("Contains custom CSS; visual parity checks recommended")
            if risk_level == "low":
                risk_level = "medium"

        if payload.get("templates") and not payload.get("pages"):
            reasons.append("Legacy templates-only payload requires structure migration")
            if risk_level == "low":
                risk_level = "medium"

        return {
            "riskLevel": risk_level,
            "componentCount": component_count,
            "hasLegacyTemplates": bool(payload.get("templates") and not payload.get("pages")),
            "reasons": reasons,
        }


def migrate_legacy_export_payload(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], MigrationReport]:
    """Convenience wrapper for payload migration."""
    service = ExportMigrationService()
    return service.migrate_course_payload(payload)
