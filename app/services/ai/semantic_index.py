"""Unified Semantic Index — Phase 2.8.

Extends the RAG retrieval system beyond course similarity to include:
    - Template schemas (from template_contracts.py)
    - Component type registry (from component_registry)
    - API tool schemas (from tool definitions)
    - Course examples (existing SimilarCourseService)

Provides a single entry-point for all context retrieval needs during
course generation, planning, and content creation.

Architecture:
    UnifiedSemanticIndex
        ├── SimilarCourseService (existing, 3-tier: pgvector → fulltext → keyword)
        ├── TemplateSchemaIndex (new: keyword + semantic search for templates)
        ├── ComponentRegistryIndex (new: component type lookup)
        └── APIToolSchemaIndex (new: tool capability lookup)

Usage:
    index = UnifiedSemanticIndex(db)
    context = await index.retrieve(
        query="course about python programming",
        include=["similar_courses", "templates", "components"],
        session_id=session_id,
        user_id=user_id,
    )
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("ai_authoring")


class UnifiedSemanticIndex:
    """Unified semantic index for all context retrieval during course generation.

    Combines course similarity, template schemas, component types, and API
    tool schemas into a single queryable interface.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Public API ─────────────────────────────────────────────────

    async def retrieve(
        self,
        query: str,
        session_id: str,
        user_id: str = "",
        include: Optional[List[str]] = None,
        max_results: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Retrieve relevant context from all configured indices.

        Args:
            query: Natural language query
            session_id: Active AI session
            user_id: Authenticated user
            include: List of indices to query: ["similar_courses", "templates", "components", "tools"]
            max_results: Max results per index
            filters: Optional filters (template_types, etc.)

        Returns:
            {similar_courses: [...], templates: [...], components: [...], tools: [...]}
        """
        include = include or ["similar_courses", "templates", "components"]
        results: Dict[str, Any] = {}

        # Parallel retrieval across indices
        import asyncio

        tasks = []

        if "similar_courses" in include:
            tasks.append(self._retrieve_similar_courses(query, session_id, user_id, max_results, filters))
        else:
            tasks.append(asyncio.sleep(0))  # placeholder

        if "templates" in include:
            tasks.append(self._retrieve_templates(query, max_results))
        else:
            tasks.append(asyncio.sleep(0))

        if "components" in include:
            tasks.append(self._retrieve_components(query, max_results))
        else:
            tasks.append(asyncio.sleep(0))

        if "tools" in include:
            tasks.append(self._retrieve_tools(query, max_results))
        else:
            tasks.append(asyncio.sleep(0))

        gathered = await asyncio.gather(*tasks, return_exceptions=True)

        idx = 0
        if "similar_courses" in include:
            results["similar_courses"] = gathered[idx] if not isinstance(gathered[idx], Exception) else []
            idx += 1
        if "templates" in include:
            results["templates"] = gathered[idx] if not isinstance(gathered[idx], Exception) else []
            idx += 1
        if "components" in include:
            results["components"] = gathered[idx] if not isinstance(gathered[idx], Exception) else []
            idx += 1
        if "tools" in include:
            results["tools"] = gathered[idx] if not isinstance(gathered[idx], Exception) else []

        return results

    # ── Individual retrievers ─────────────────────────────────────

    async def _retrieve_similar_courses(
        self,
        query: str,
        session_id: str,
        user_id: str,
        max_results: int,
        filters: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Retrieve similar courses via the existing 3-tier pipeline."""
        try:
            from app.services.ai.similar_course_service import (
                SimilarCourseService, FeatureDisabledError,
            )
            svc = SimilarCourseService(self.db)
            result = await svc.query_similar_courses(
                session_id=session_id,
                query=query,
                max_results=max_results,
                filters=filters,
                user_id=user_id,
            )
            return result.get("courses", [])
        except FeatureDisabledError:
            logger.info("Similar course retrieval disabled")
            return []
        except Exception as exc:
            logger.warning("Similar course retrieval failed: %s", exc)
            return []

    async def _retrieve_templates(
        self, query: str, max_results: int
    ) -> List[Dict[str, Any]]:
        """Retrieve relevant template schemas based on query.

        Uses keyword matching against template descriptions and use-cases.
        """
        try:
            from app.services.ai.template_contracts import AITemplateContractsService
            svc = AITemplateContractsService()
            all_templates = await svc.list_contracts()

            # Score templates by keyword relevance
            query_lower = query.lower()
            scored = []
            for t in all_templates:
                name = (t.get("type_key") or "").lower()
                desc = (t.get("description") or "").lower()
                # Simple keyword relevance score
                score = 0
                query_words = query_lower.split()
                for word in query_words:
                    if word in name:
                        score += 3
                    if word in desc:
                        score += 1
                if score > 0:
                    scored.append({**t, "_relevance": score})

            scored.sort(key=lambda x: x.get("_relevance", 0), reverse=True)
            return scored[:max_results]
        except Exception as exc:
            logger.warning("Template retrieval failed: %s", exc)
            return []

    async def _retrieve_components(
        self, query: str, max_results: int
    ) -> List[Dict[str, Any]]:
        """Retrieve relevant component types from the registry."""
        try:
            from app.models.component_type import ComponentType
            from sqlalchemy import select

            q = select(ComponentType).limit(max_results * 3)
            result = await self.db.execute(q)
            rows = result.scalars().all()

            # Score by keyword relevance
            query_lower = query.lower()
            scored = []
            for row in rows:
                name = (getattr(row, 'component_type', '') or '').lower()
                desc = (getattr(row, 'description', '') or '').lower()
                score = 0
                for word in query_lower.split():
                    if word in name:
                        score += 3
                    if word in desc:
                        score += 1
                if score > 0:
                    scored.append({
                        "component_type": getattr(row, 'component_type', ''),
                        "description": getattr(row, 'description', ''),
                        "schema_hint": getattr(row, 'schema_hint', None),
                        "_relevance": score,
                    })

            scored.sort(key=lambda x: x.get("_relevance", 0), reverse=True)
            return scored[:max_results]
        except Exception as exc:
            logger.warning("Component retrieval failed: %s", exc)
            return []

    async def _retrieve_tools(
        self, query: str, max_results: int
    ) -> List[Dict[str, Any]]:
        """Retrieve relevant API tool schemas for the query."""
        # Tool schemas are static — return the relevant subset
        tools = [
            {
                "name": "list_pages",
                "description": "List all pages in the current course with titles and types",
                "category": "read",
            },
            {
                "name": "fetch_page",
                "description": "Fetch full content and components of a specific page",
                "category": "read",
            },
            {
                "name": "propose_create_page",
                "description": "Propose creating a new page (no immediate mutation)",
                "category": "write",
            },
            {
                "name": "propose_update_page",
                "description": "Propose updating an existing page",
                "category": "write",
            },
            {
                "name": "propose_delete_page",
                "description": "Propose deleting a page (requires confirmation)",
                "category": "delete",
            },
            {
                "name": "validate_course",
                "description": "Validate course for schema, business rules, and accessibility",
                "category": "validate",
            },
            {
                "name": "query_similar_courses",
                "description": "Search for similar courses within the organization",
                "category": "search",
            },
        ]

        query_lower = query.lower()
        scored = []
        for t in tools:
            score = 0
            for word in query_lower.split():
                if word in t["name"].lower():
                    score += 3
                if word in t["description"].lower():
                    score += 1
                if word in t["category"]:
                    score += 2
            if score > 0:
                scored.append({**t, "_relevance": score})

        scored.sort(key=lambda x: x.get("_relevance", 0), reverse=True)
        return scored[:max_results]
