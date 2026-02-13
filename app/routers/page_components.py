"""Page & Component CRUD API.

Endpoints:
  GET/POST         /courses/{courseId}/pages
  POST             /courses/{courseId}/pages/reorder
  GET/PATCH/DELETE /courses/{courseId}/pages/{pageId}
  GET/POST         /courses/{courseId}/pages/{pageId}/components
  POST             /courses/{courseId}/pages/{pageId}/components/reorder
  GET/PATCH/DELETE /courses/{courseId}/pages/{pageId}/components/{componentId}
"""
from __future__ import annotations
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.repositories.page_component_repo import PageRepository, ComponentRepository
from app.repositories.course_repo import CourseRepository
from app.models.page_component import PageRecord, ComponentRecord


# ── Request/Response DTOs ────────────────────

class ComponentCreateDTO(BaseModel):
    componentType: str
    data: dict = Field(default_factory=dict)
    audioConfig: Optional[dict] = None
    completionCriteria: Optional[dict] = None
    styling: Optional[dict] = None


class ComponentUpdateDTO(BaseModel):
    data: Optional[dict] = None
    audioConfig: Optional[dict] = None
    completionCriteria: Optional[dict] = None
    styling: Optional[dict] = None


class PageCreateDTO(BaseModel):
    title: str = Field(..., max_length=200)
    components: Optional[List[ComponentCreateDTO]] = None
    pageCompletion: Optional[dict] = None
    layout: Optional[dict] = None
    theme: Optional[dict] = None


class PageUpdateDTO(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    pageCompletion: Optional[dict] = None
    layout: Optional[dict] = None
    theme: Optional[dict] = None


class ReorderDTO(BaseModel):
    orderedIds: List[str]


# ── Helpers ──────────────────────────────────

async def _require_course(session: AsyncSession, courseId: str):
    repo = CourseRepository(session)
    course = await repo.get_by_course_id(courseId)
    if not course:
        raise HTTPException(404, f"Course '{courseId}' not found")
    return course


async def _require_page(session: AsyncSession, courseId: str, pageId: str):
    await _require_course(session, courseId)
    repo = PageRepository(session)
    page = await repo.get_by_course_and_page(courseId, pageId)
    if not page:
        raise HTTPException(404, f"Page '{pageId}' not found in course '{courseId}'")
    return page


router = APIRouter(tags=["Pages", "Components"])


# ── Page Endpoints ───────────────────────────

@router.get("/courses/{courseId}/pages")
async def list_pages(
    courseId: str,
    session: AsyncSession = Depends(get_session),
):
    await _require_course(session, courseId)
    repo = PageRepository(session)
    pages = await repo.list_by_course(courseId)
    return [p.to_dict() for p in pages]


@router.post("/courses/{courseId}/pages", status_code=201)
async def create_page(
    courseId: str,
    body: PageCreateDTO,
    session: AsyncSession = Depends(get_session),
):
    await _require_course(session, courseId)
    page_repo = PageRepository(session)
    next_order = await page_repo.count_by_course(courseId)

    page = PageRecord(
        course_id=courseId,
        title=body.title,
        order_index=next_order,
        layout=body.layout,
        theme_config=body.theme,
        completion_config=body.pageCompletion,
    )
    page = await page_repo.create(page)

    # Add initial components if provided
    if body.components:
        comp_repo = ComponentRepository(session)
        for idx, comp_dto in enumerate(body.components):
            comp = ComponentRecord(
                page_id=page.page_id,
                component_type=comp_dto.componentType,
                order_index=idx,
                data=comp_dto.data,
                audio_config=comp_dto.audioConfig,
                completion_criteria=comp_dto.completionCriteria,
                styling=comp_dto.styling,
            )
            await comp_repo.create(comp)
        # Refresh to get components
        page = await page_repo.get(page.page_id)

    return page.to_dict()


@router.post("/courses/{courseId}/pages/reorder")
async def reorder_pages(
    courseId: str,
    body: ReorderDTO,
    session: AsyncSession = Depends(get_session),
):
    await _require_course(session, courseId)
    repo = PageRepository(session)
    pages = await repo.reorder(courseId, body.orderedIds)
    return [p.to_dict() for p in pages]


@router.get("/courses/{courseId}/pages/{pageId}")
async def get_page(
    courseId: str,
    pageId: str,
    session: AsyncSession = Depends(get_session),
):
    page = await _require_page(session, courseId, pageId)
    return page.to_dict()


@router.patch("/courses/{courseId}/pages/{pageId}")
async def update_page(
    courseId: str,
    pageId: str,
    body: PageUpdateDTO,
    session: AsyncSession = Depends(get_session),
):
    page = await _require_page(session, courseId, pageId)

    if body.title is not None:
        page.title = body.title
    if body.layout is not None:
        page.layout = body.layout
    if body.theme is not None:
        page.theme_config = body.theme
    if body.pageCompletion is not None:
        page.completion_config = body.pageCompletion

    repo = PageRepository(session)
    page = await repo.update(page)
    return page.to_dict()


@router.delete("/courses/{courseId}/pages/{pageId}", status_code=204)
async def delete_page(
    courseId: str,
    pageId: str,
    session: AsyncSession = Depends(get_session),
):
    page = await _require_page(session, courseId, pageId)
    repo = PageRepository(session)
    await repo.delete(page)


# ── Component Endpoints ─────────────────────

@router.get("/courses/{courseId}/pages/{pageId}/components")
async def list_components(
    courseId: str,
    pageId: str,
    session: AsyncSession = Depends(get_session),
):
    await _require_page(session, courseId, pageId)
    repo = ComponentRepository(session)
    comps = await repo.list_by_page(pageId)
    return [c.to_dict() for c in comps]


@router.post("/courses/{courseId}/pages/{pageId}/components", status_code=201)
async def add_component(
    courseId: str,
    pageId: str,
    body: ComponentCreateDTO,
    session: AsyncSession = Depends(get_session),
):
    await _require_page(session, courseId, pageId)
    comp_repo = ComponentRepository(session)
    next_order = await comp_repo.count_by_page(pageId)

    comp = ComponentRecord(
        page_id=pageId,
        component_type=body.componentType,
        order_index=next_order,
        data=body.data,
        audio_config=body.audioConfig,
        completion_criteria=body.completionCriteria,
        styling=body.styling,
    )
    comp = await comp_repo.create(comp)
    return comp.to_dict()


@router.post("/courses/{courseId}/pages/{pageId}/components/reorder")
async def reorder_components(
    courseId: str,
    pageId: str,
    body: ReorderDTO,
    session: AsyncSession = Depends(get_session),
):
    await _require_page(session, courseId, pageId)
    repo = ComponentRepository(session)
    comps = await repo.reorder(pageId, body.orderedIds)
    return [c.to_dict() for c in comps]


@router.get("/courses/{courseId}/pages/{pageId}/components/{componentId}")
async def get_component(
    courseId: str,
    pageId: str,
    componentId: str,
    session: AsyncSession = Depends(get_session),
):
    await _require_page(session, courseId, pageId)
    repo = ComponentRepository(session)
    comp = await repo.get_by_page_and_component(pageId, componentId)
    if not comp:
        raise HTTPException(404, f"Component '{componentId}' not found")
    return comp.to_dict()


@router.patch("/courses/{courseId}/pages/{pageId}/components/{componentId}")
async def update_component(
    courseId: str,
    pageId: str,
    componentId: str,
    body: ComponentUpdateDTO,
    session: AsyncSession = Depends(get_session),
):
    await _require_page(session, courseId, pageId)
    repo = ComponentRepository(session)
    comp = await repo.get_by_page_and_component(pageId, componentId)
    if not comp:
        raise HTTPException(404, f"Component '{componentId}' not found")

    if body.data is not None:
        comp.data = body.data
    if body.audioConfig is not None:
        comp.audio_config = body.audioConfig
    if body.completionCriteria is not None:
        comp.completion_criteria = body.completionCriteria
    if body.styling is not None:
        comp.styling = body.styling

    comp = await repo.update(comp)
    return comp.to_dict()


@router.delete(
    "/courses/{courseId}/pages/{pageId}/components/{componentId}",
    status_code=204,
)
async def delete_component(
    courseId: str,
    pageId: str,
    componentId: str,
    session: AsyncSession = Depends(get_session),
):
    await _require_page(session, courseId, pageId)
    repo = ComponentRepository(session)
    comp = await repo.get_by_page_and_component(pageId, componentId)
    if not comp:
        raise HTTPException(404, f"Component '{componentId}' not found")
    await repo.delete(comp)
