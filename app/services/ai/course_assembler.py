"""Course Assembler - US-BKND-AI-030.

Bridges AI-generated content proposals and the existing manual course editor.
Transforms proposal data into PageRecord and ComponentRecord rows, validates
component type compatibility, and ensures editor state compatibility.

Architecture:
    Proposal -> CourseAssembler -> PageRecord/ComponentRecord -> Editor

The assembler ensures AI-generated content is indistinguishable from
manually-authored content in the editor by writing to the same tables.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.page_component import PageRecord, ComponentRecord

logger = logging.getLogger(__name__)


# Template-type to component-type mapping for assembly.
# Maps both canonical BUILTIN_TEMPLATE_TYPES and legacy/AI-generated aliases.
TEMPLATE_TO_COMPONENT = {
    "content-text": "content-text",
    "text-content": "content-text",       # Legacy alias
    "tabs": "tabs",
    "accordion": "accordion",
    "click-reveal": "accordion",          # Legacy → canonical accordion
    "final-assessment": "final-assessment",
}

VALID_COMPONENT_TYPES = {"content-text", "text-content", "tabs", "accordion", "click-reveal", "final-assessment"}


class AssemblyError(Exception):
    """Structured error for course assembly failures."""
    def __init__(self, code: str, message: str, http_status: int = 400):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class CourseAssembler:
    """Transforms AI proposal data into editor-compatible page/component state.

    The assembler is the single convergence point for all AI mutation
    pathways: single page, batch, and file-ingestion all pass through
    the same assembly code path.

    Usage:
        assembler = CourseAssembler(db)
        result = await assembler.assemble_create_page(course_id, page_spec)
    """

    MAX_TITLE_LENGTH = 200

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def assemble_create_page(
        self,
        course_id: str,
        page_spec: Dict[str, Any],
        order_index: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Create a new page with components from AI proposal data.

        Args:
            course_id: Target course ID.
            page_spec: Page specification with title, template_type, components.
            order_index: Position in course (appended to end if None).

        Returns:
            Dict with page_id, title, component_count, component_ids.
        """
        # Validate
        title = (page_spec.get("title") or "Untitled")[:self.MAX_TITLE_LENGTH]
        template_type = page_spec.get("template_type", "content-text")
        components_data = page_spec.get("components", [])

        # Determine order
        if order_index is None:
            from app.repositories.page_component_repo import PageRepository
            repo = PageRepository(self.db)
            existing = await repo.list_by_course(course_id)
            order_index = len(existing)

        # Create page record
        page = PageRecord(
            course_id=course_id,
            title=title,
            order_index=order_index,
            layout={"templateType": template_type},
        )
        self.db.add(page)
        await self.db.flush()  # Get page_id assigned

        # Create component records
        component_ids = []
        for i, comp_data in enumerate(components_data):
            comp_type = comp_data.get("component_type", "content-text")
            comp_type = self._map_component_type(comp_type)

            component = ComponentRecord(
                page_id=page.page_id,
                component_type=comp_type,
                order_index=comp_data.get("order_index", i),
                data=comp_data.get("data", {}),
            )
            self.db.add(component)
            component_ids.append(component.component_id)

        await self.db.commit()

        logger.info(
            "Assembled page: id=%s title=%s components=%d course=%s",
            page.page_id, title, len(component_ids), course_id,
        )

        return {
            "page_id": page.page_id,
            "title": title,
            "template_type": template_type,
            "order_index": order_index,
            "component_count": len(component_ids),
            "component_ids": component_ids,
        }

    async def assemble_update_page(
        self,
        page_id: str,
        page_spec: Dict[str, Any],
        replace_components: bool = True,
    ) -> Dict[str, Any]:
        """Update an existing page and optionally replace its components.

        Args:
            page_id: Target page ID.
            page_spec: New page specification.
            replace_components: If True, delete existing components and recreate.

        Returns:
            Dict with page_id, title, component_count.
        """
        # Fetch existing page
        from app.repositories.page_component_repo import PageRepository
        repo = PageRepository(self.db)
        page = await repo.get(page_id)
        if page is None:
            raise AssemblyError("PAGE_NOT_FOUND", f"Page '{page_id}' not found.", 404)

        # Update title
        if page_spec.get("title"):
            page.title = page_spec["title"][:self.MAX_TITLE_LENGTH]

        # Update layout/template — must reassign full dict for SQLAlchemy JSON mutation tracking
        if page_spec.get("template_type"):
            layout = dict(page.layout or {})
            layout["templateType"] = page_spec["template_type"]
            page.layout = layout

        # Replace components if requested
        components_data = page_spec.get("components", [])
        component_count = len(components_data)

        if replace_components and components_data:
            # Delete existing components
            for comp in list(page.components or []):
                await self.db.delete(comp)

            # Create new components
            for i, comp_data in enumerate(components_data):
                comp_type = self._map_component_type(
                    comp_data.get("component_type", "content-text")
                )
                component = ComponentRecord(
                    page_id=page_id,
                    component_type=comp_type,
                    order_index=comp_data.get("order_index", i),
                    data=comp_data.get("data", {}),
                )
                self.db.add(component)

        await self.db.commit()

        logger.info("Assembled update: page=%s title=%s", page_id, page.title)

        return {
            "page_id": page_id,
            "title": page.title,
            "template_type": page_spec.get("template_type", ""),
            "component_count": component_count,
        }

    async def assemble_delete_page(self, page_id: str) -> Dict[str, Any]:
        """Delete a page and its components.

        Returns deletion confirmation with page metadata for audit.
        """
        from app.repositories.page_component_repo import PageRepository
        repo = PageRepository(self.db)
        page = await repo.get(page_id)
        if page is None:
            raise AssemblyError("PAGE_NOT_FOUND", f"Page '{page_id}' not found.", 404)

        title = page.title
        component_count = len(page.components or [])

        await repo.delete(page)
        await self.db.commit()

        logger.info("Assembled delete: page=%s title=%s", page_id, title)

        return {
            "page_id": page_id,
            "title": title,
            "component_count": component_count,
            "deleted": True,
        }

    async def assemble_batch(
        self,
        course_id: str,
        pages_spec: List[Dict[str, Any]],
        clear_existing: bool = False,
    ) -> Dict[str, Any]:
        """Assemble multiple pages into a course in one operation.

        Args:
            course_id: Target course ID.
            pages_spec: List of page specifications.
            clear_existing: If True, delete all existing pages first.

        Returns:
            Dict with created/modified/deleted page counts.
        """
        if clear_existing:
            from app.repositories.page_component_repo import PageRepository
            repo = PageRepository(self.db)
            existing = await repo.list_by_course(course_id)
            for page in existing:
                await repo.delete(page)

        created = []
        for i, spec in enumerate(pages_spec):
            result = await self.assemble_create_page(course_id, spec, order_index=i)
            created.append(result)

        await self.db.commit()

        return {
            "course_id": course_id,
            "pages_created": len(created),
            "created_page_ids": [p["page_id"] for p in created],
        }

    async def get_editor_state(self, course_id: str) -> Dict[str, Any]:
        """Get the full editor-compatible course state after assembly.

        Returns the same shape as GET /api/v1/courses/{courseId} so the
        frontend editor can render AI-generated content identically to
        manual content.
        """
        from app.repositories.page_component_repo import PageRepository
        repo = PageRepository(self.db)
        pages = await repo.list_by_course(course_id)

        return {
            "course_id": course_id,
            "pages": [
                {
                    "page_id": p.page_id,
                    "title": p.title,
                    "order_index": p.order_index,
                    "layout": p.layout,
                    "template_type": (
                        p.layout.get("templateType", "content-text")
                        if isinstance(p.layout, dict) else "content-text"
                    ),
                    "components": [
                        {
                            "component_id": c.component_id,
                            "component_type": c.component_type,
                            "order_index": c.order_index,
                            "data": c.data,
                        }
                        for c in (p.components or [])
                    ],
                }
                for p in pages
            ],
            "total_pages": len(pages),
        }

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_page_spec(self, page_spec: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Validate a page specification before assembly.

        Returns list of validation issues (empty = valid).
        """
        issues = []

        title = page_spec.get("title", "")
        if not title or not title.strip():
            issues.append({
                "field": "title",
                "message": "Page title is required.",
                "severity": "error",
            })
        if len(title) > self.MAX_TITLE_LENGTH:
            issues.append({
                "field": "title",
                "message": f"Title exceeds {self.MAX_TITLE_LENGTH} characters.",
                "severity": "warning",
            })

        template_type = page_spec.get("template_type", "")
        if template_type and template_type not in TEMPLATE_TO_COMPONENT:
            issues.append({
                "field": "template_type",
                "message": f"Unknown template type: '{template_type}'.",
                "severity": "error",
            })

        for i, comp in enumerate(page_spec.get("components", [])):
            ctype = comp.get("component_type", "")
            if ctype and ctype not in VALID_COMPONENT_TYPES:
                issues.append({
                    "field": f"components[{i}].component_type",
                    "message": f"Unknown component type: '{ctype}'.",
                    "severity": "error",
                })

        return issues

    def _map_component_type(self, comp_type: str) -> str:
        """Map a component type to its canonical DB value."""
        # Normalize through TEMPLATE_TO_COMPONENT first
        mapped = TEMPLATE_TO_COMPONENT.get(comp_type)
        if mapped:
            return mapped
        # Unknown type — reject
        raise AssemblyError(
            "INVALID_COMPONENT_TYPE",
            f"Unknown component type: '{comp_type}'. Valid types: {sorted(VALID_COMPONENT_TYPES)}",
            400,
        )
