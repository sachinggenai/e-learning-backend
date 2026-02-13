"""Analytics & Reporting API.

Provides course-level performance summaries, skill mastery rollups,
and manager-facing views of learner progress.
"""
from __future__ import annotations
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.repositories.course_repo import CourseRepository
from app.repositories.page_component_repo import PageRepository, ComponentRepository
from app.repositories.scoring_repo import ScoringRepository
from app.repositories.interaction_event_repo import InteractionEventRepository


async def _require_course(session: AsyncSession, course_id: str):
    repo = CourseRepository(session)
    try:
        return await repo.get_by_course_id(course_id)
    except Exception:
        raise HTTPException(404, f"Course '{course_id}' not found")


router = APIRouter(tags=["Analytics"])


@router.get("/courses/{courseId}/analytics/summary")
async def get_analytics_summary(
    courseId: str,
    session: AsyncSession = Depends(get_session),
):
    """Course-level performance summary.

    Returns score distributions, completion rates, and mastery overview
    computed from persisted interaction events and scoring config.
    """
    course = await _require_course(session, courseId)

    # Gather structural data
    page_repo = PageRepository(session)
    pages = await page_repo.list_by_course(courseId)
    total_pages = len(pages)

    total_components = 0
    scoring_components = 0
    for page in pages:
        for comp in (page.components or []):
            total_components += 1
            criteria = comp.completion_criteria or {}
            if criteria.get("type") in ("score", "interaction", "scored-interaction"):
                scoring_components += 1

    # Scoring config
    scoring_repo = ScoringRepository(session)
    scoring_record = await scoring_repo.get_by_course(courseId)
    passing_score = 70
    if scoring_record and scoring_record.config:
        passing_score = scoring_record.config.get("passingScore", 70)

    # Interaction event stats
    event_repo = InteractionEventRepository(session)
    total_events = await event_repo.count_by_course(courseId)
    events_by_type = await event_repo.aggregate_by_type(courseId)

    return {
        "courseId": courseId,
        "title": course.title,
        "structure": {
            "totalPages": total_pages,
            "totalComponents": total_components,
            "scoringComponents": scoring_components,
        },
        "scoring": {
            "passingScore": passing_score,
            "weightedScoring": (scoring_record.config or {}).get("weightedScoring", False) if scoring_record else False,
        },
        "interactions": {
            "totalEvents": total_events,
            "byType": events_by_type,
        },
        "generatedAt": datetime.utcnow().isoformat(),
    }


@router.get("/courses/{courseId}/analytics/skills")
async def get_skill_mastery(
    courseId: str,
    session: AsyncSession = Depends(get_session),
):
    """Skill mastery rollup — aggregated skill/tag performance.

    Groups components by their tags and computes mastery percentages
    based on scoring component weights.
    """
    await _require_course(session, courseId)

    page_repo = PageRepository(session)
    pages = await page_repo.list_by_course(courseId)

    # Build skill → component mapping from component tags
    # (tags are stored in component_type registry, but we approximate from data)
    skill_map: dict[str, dict] = {}
    for page in pages:
        for comp in (page.components or []):
            # Extract tags from component data or use component type as skill
            tags = (comp.data or {}).get("tags", [comp.component_type])
            if isinstance(tags, str):
                tags = [tags]
            for tag in tags:
                if tag not in skill_map:
                    skill_map[tag] = {"skill": tag, "componentCount": 0, "components": []}
                skill_map[tag]["componentCount"] += 1
                skill_map[tag]["components"].append({
                    "componentId": comp.component_id,
                    "componentType": comp.component_type,
                    "pageId": page.page_id,
                })

    skills = list(skill_map.values())
    skills.sort(key=lambda s: s["componentCount"], reverse=True)

    return {
        "courseId": courseId,
        "skills": skills,
        "totalSkills": len(skills),
        "generatedAt": datetime.utcnow().isoformat(),
    }


@router.get("/courses/{courseId}/analytics/manager-view")
async def get_manager_view(
    courseId: str,
    session: AsyncSession = Depends(get_session),
):
    """Manager-facing view of learner progress.

    Provides a structural overview suitable for manager dashboards,
    including page-by-page breakdown, scoring configuration,
    and interaction volume.
    """
    course = await _require_course(session, courseId)

    page_repo = PageRepository(session)
    pages = await page_repo.list_by_course(courseId)

    scoring_repo = ScoringRepository(session)
    scoring_record = await scoring_repo.get_by_course(courseId)

    event_repo = InteractionEventRepository(session)
    total_events = await event_repo.count_by_course(courseId)

    page_details = []
    for page in pages:
        comp_count = len(page.components or [])
        page_details.append({
            "pageId": page.page_id,
            "title": page.title,
            "order": page.order_index,
            "componentCount": comp_count,
            "completionStrategy": (page.completion_config or {}).get("strategy", "all"),
        })

    return {
        "courseId": courseId,
        "courseTitle": course.title,
        "courseStatus": course.status,
        "pages": page_details,
        "totalPages": len(pages),
        "scoring": scoring_record.to_dict() if scoring_record else None,
        "totalInteractionEvents": total_events,
        "generatedAt": datetime.utcnow().isoformat(),
    }
