"""Component Registry API — browse, search, and inspect component types.

Endpoints:
  GET  /components                         — List all component types
  GET  /components/categories              — List all categories with counts
  GET  /components/categories/{categoryId} — List types in a category
  GET  /components/search                  — Search types by query/tags
  GET  /components/{typeId}                — Get component type definition (with schema, schemaVersion, etag)
"""
from __future__ import annotations
import hashlib
import json
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, Response, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.repositories.component_type_repo import ComponentTypeRepository


def _compute_etag(data: dict) -> str:
    """Compute an ETag from a dict for cache validation."""
    raw = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    return hashlib.md5(raw).hexdigest()


# Schema version for cache invalidation
COMPONENT_SCHEMA_VERSION = "2.0.0"

# Category metadata for display
CATEGORY_META = {
    "content-presentation": {"displayName": "Content Presentation", "description": "Display content with interactive layouts", "icon": "layout", "sortOrder": 1},
    "process-flow": {"displayName": "Process & Flow", "description": "Visualize processes, sequences, decisions", "icon": "git-branch", "sortOrder": 2},
    "interaction": {"displayName": "Interaction", "description": "User-driven interactive elements", "icon": "mouse-pointer", "sortOrder": 3},
    "scenario": {"displayName": "Scenario-Based", "description": "Real-world scenario learning", "icon": "map", "sortOrder": 4},
    "assessment": {"displayName": "Assessment", "description": "Graded evaluation components", "icon": "check-square", "sortOrder": 5},
    "comparison": {"displayName": "Comparison & Analysis", "description": "Compare, contrast, analyze", "icon": "columns", "sortOrder": 6},
    "media-rich": {"displayName": "Media-Rich", "description": "Video, audio, animation-based", "icon": "film", "sortOrder": 7},
    "microlearning": {"displayName": "Microlearning", "description": "Bite-sized learning chunks", "icon": "zap", "sortOrder": 8},
    "navigation": {"displayName": "Navigation & Structural", "description": "Course structure and navigation", "icon": "navigation", "sortOrder": 9},
    "gamification": {"displayName": "Gamification", "description": "Game mechanics for engagement", "icon": "award", "sortOrder": 10},
    "compliance": {"displayName": "Compliance & Corporate", "description": "Regulatory and policy content", "icon": "shield", "sortOrder": 11},
    "diagnostic": {"displayName": "Diagnostic & Adaptive", "description": "Personalized learning paths", "icon": "activity", "sortOrder": 12},
    "practice": {"displayName": "Practice & Simulation", "description": "Hands-on practice without scoring pressure", "icon": "tool", "sortOrder": 13},
    "feedback": {"displayName": "Feedback & Reflection", "description": "Self-assessment and reflection", "icon": "message-circle", "sortOrder": 14},
    "social": {"displayName": "Social & Collaborative", "description": "Multi-user interaction and collaboration", "icon": "users", "sortOrder": 15},
    "accessibility": {"displayName": "Accessibility & Support", "description": "Compliance and accessibility aids", "icon": "eye", "sortOrder": 16},
    "analytics": {"displayName": "Analytics & Learning Insight", "description": "Progress tracking and reporting", "icon": "bar-chart", "sortOrder": 17},
}

router = APIRouter(prefix="/components", tags=["ComponentRegistry"])


@router.get("")
async def list_component_types(
    category: Optional[str] = Query(None),
    scoringEnabled: Optional[bool] = Query(None),
    isActive: Optional[bool] = Query(True),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    repo = ComponentTypeRepository(session)
    items, total = await repo.list(
        category=category,
        scoring_enabled=scoringEnabled,
        is_active=isActive,
        page=page,
        limit=limit,
    )
    return {
        "items": [ct.to_dict() for ct in items],
        "total": total,
        "page": page,
        "limit": limit,
        "schemaVersion": COMPONENT_SCHEMA_VERSION,
    }


@router.get("/categories")
async def list_categories(session: AsyncSession = Depends(get_session)):
    repo = ComponentTypeRepository(session)
    raw = await repo.get_categories()
    categories = []
    for item in raw:
        cat_id = item["categoryId"]
        meta = CATEGORY_META.get(cat_id, {})
        categories.append({
            "categoryId": cat_id,
            "displayName": meta.get("displayName", cat_id),
            "description": meta.get("description", ""),
            "icon": meta.get("icon", "component"),
            "componentCount": item["componentCount"],
            "sortOrder": meta.get("sortOrder", 99),
        })
    categories.sort(key=lambda c: c["sortOrder"])
    return {"categories": categories}


@router.get("/categories/{categoryId}")
async def list_category_components(
    categoryId: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    if categoryId not in CATEGORY_META:
        raise HTTPException(404, f"Category '{categoryId}' not found")
    repo = ComponentTypeRepository(session)
    items, total = await repo.list(category=categoryId, page=page, limit=limit)
    return {
        "items": [ct.to_dict() for ct in items],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/search")
async def search_component_types(
    q: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    tags: Optional[str] = Query(None, description="Comma-separated tags"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    repo = ComponentTypeRepository(session)
    items, total = await repo.search(
        q=q, category=category, tags=tag_list, page=page, limit=limit
    )
    return {
        "items": [ct.to_dict() for ct in items],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/{typeId}")
async def get_component_type(
    typeId: str,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    """Get full component type detail including schema, schemaVersion, and etag.

    Supports conditional requests via If-None-Match for cache efficiency.
    """
    repo = ComponentTypeRepository(session)
    ct = await repo.get_by_type_id(typeId)
    if not ct:
        raise HTTPException(404, f"Component type '{typeId}' not found")

    full = ct.to_dict(full=True)
    full["schemaVersion"] = COMPONENT_SCHEMA_VERSION

    etag = _compute_etag(full)
    full["etag"] = etag

    # Support conditional GET (If-None-Match)
    if_none_match = request.headers.get("if-none-match")
    if if_none_match and if_none_match.strip('"') == etag:
        response.status_code = 304
        return Response(status_code=304, headers={"ETag": f'"{etag}"'})

    response.headers["ETag"] = f'"{etag}"'
    return full
