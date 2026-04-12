"""Theme API — CRUD for themes, course/page theme resolution.

Endpoints:
  GET/POST         /themes
  GET              /themes/presets
  GET/PATCH/DELETE /themes/{themeId}
  GET/PATCH        /courses/{courseId}/theme
  GET/PATCH        /courses/{courseId}/pages/{pageId}/theme
"""
from __future__ import annotations
from typing import Optional
from copy import deepcopy

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.repositories.theme_repo import ThemeRepository
from app.repositories.course_repo import CourseRepository
from app.repositories.page_component_repo import PageRepository
from app.models.theme import ThemeRecord


# ── Preset Themes ────────────────────────────

DEFAULT_THEMES = [
    {
        "name": "Default Light",
        "colors": {
            "primary": "#1976D2",
            "secondary": "#424242",
            "background": "#FFFFFF",
            "surface": "#F5F5F5",
            "text": "#212121",
            "textSecondary": "#757575",
            "accent": "#FF4081",
            "error": "#D32F2F",
            "success": "#388E3C",
            "warning": "#F57C00",
            "info": "#1976D2",
            "border": "#E0E0E0",
        },
        "typography": {
            "fontFamily": "Inter, system-ui, sans-serif",
            "headingFont": "Inter, system-ui, sans-serif",
            "baseFontSize": 16,
            "headingSizes": {"h1": 32, "h2": 24, "h3": 20, "h4": 18},
            "lineHeight": 1.6,
            "fontWeight": {"normal": 400, "medium": 500, "bold": 700},
        },
        "componentStyles": {
            "button": {"borderRadius": 8, "padding": "10px 24px", "fontWeight": 600, "textTransform": "none"},
            "card": {"borderRadius": 12, "shadow": "0 2px 8px rgba(0,0,0,0.1)", "borderWidth": 0, "padding": "24px"},
        },
    },
    {
        "name": "Dark Mode",
        "colors": {
            "primary": "#90CAF9",
            "secondary": "#B0BEC5",
            "background": "#121212",
            "surface": "#1E1E1E",
            "text": "#FFFFFF",
            "textSecondary": "#B0BEC5",
            "accent": "#FF80AB",
            "error": "#EF5350",
            "success": "#66BB6A",
            "warning": "#FFA726",
            "info": "#42A5F5",
            "border": "#333333",
        },
        "typography": {
            "fontFamily": "Inter, system-ui, sans-serif",
            "headingFont": "Inter, system-ui, sans-serif",
            "baseFontSize": 16,
            "headingSizes": {"h1": 32, "h2": 24, "h3": 20, "h4": 18},
            "lineHeight": 1.6,
            "fontWeight": {"normal": 400, "medium": 500, "bold": 700},
        },
        "componentStyles": {
            "button": {"borderRadius": 8, "padding": "10px 24px", "fontWeight": 600, "textTransform": "none"},
            "card": {"borderRadius": 12, "shadow": "0 2px 8px rgba(0,0,0,0.3)", "borderWidth": 1, "padding": "24px"},
        },
    },
    {
        "name": "Corporate Blue",
        "colors": {
            "primary": "#0D47A1",
            "secondary": "#37474F",
            "background": "#FAFAFA",
            "surface": "#FFFFFF",
            "text": "#263238",
            "textSecondary": "#546E7A",
            "accent": "#FF6F00",
            "error": "#C62828",
            "success": "#2E7D32",
            "warning": "#EF6C00",
            "info": "#0277BD",
            "border": "#CFD8DC",
        },
        "typography": {
            "fontFamily": "Roboto, Arial, sans-serif",
            "headingFont": "Roboto Slab, serif",
            "baseFontSize": 15,
            "headingSizes": {"h1": 30, "h2": 24, "h3": 20, "h4": 17},
            "lineHeight": 1.5,
            "fontWeight": {"normal": 400, "medium": 500, "bold": 700},
        },
        "componentStyles": {
            "button": {"borderRadius": 4, "padding": "10px 20px", "fontWeight": 500, "textTransform": "uppercase"},
            "card": {"borderRadius": 4, "shadow": "0 1px 4px rgba(0,0,0,0.12)", "borderWidth": 1, "padding": "20px"},
        },
    },
]


# ── DTOs ─────────────────────────────────────

class ThemeCreateDTO(BaseModel):
    name: str = Field(..., max_length=200)
    colors: dict
    typography: dict
    componentStyles: Optional[dict] = None


class ThemeUpdateDTO(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    colors: Optional[dict] = None
    typography: Optional[dict] = None
    componentStyles: Optional[dict] = None


class CourseThemeDTO(BaseModel):
    themeId: Optional[str] = None
    overrides: Optional[dict] = None


router = APIRouter(tags=["Themes"])


# ── Theme CRUD ───────────────────────────────

@router.get("/themes")
async def list_themes(
    isPreset: Optional[bool] = Query(None),
    session: AsyncSession = Depends(get_session),
):
    repo = ThemeRepository(session)
    themes = await repo.list(is_preset=isPreset)

    # Seed presets only if the themes table is completely empty
    # (avoids duplicates when seed-data import has already run)
    if not themes:
        all_themes = await repo.list()
        if not all_themes:
            for preset in DEFAULT_THEMES:
                t = ThemeRecord(
                    name=preset["name"],
                    is_preset=True,
                    colors=preset["colors"],
                    typography=preset["typography"],
                    component_styles=preset.get("componentStyles"),
                )
                await repo.create(t)
            themes = await repo.list(is_preset=isPreset)

    return [t.to_dict() for t in themes]


@router.post("/themes", status_code=201)
async def create_theme(
    body: ThemeCreateDTO,
    session: AsyncSession = Depends(get_session),
):
    repo = ThemeRepository(session)
    theme = ThemeRecord(
        name=body.name,
        is_preset=False,
        colors=body.colors,
        typography=body.typography,
        component_styles=body.componentStyles,
    )
    theme = await repo.create(theme)
    return theme.to_dict()


@router.get("/themes/presets")
async def list_preset_themes(session: AsyncSession = Depends(get_session)):
    repo = ThemeRepository(session)
    themes = await repo.list(is_preset=True)

    # Seed presets only if the themes table is completely empty
    if not themes:
        all_themes = await repo.list()
        if not all_themes:
            for preset in DEFAULT_THEMES:
                t = ThemeRecord(
                    name=preset["name"],
                    is_preset=True,
                    colors=preset["colors"],
                    typography=preset["typography"],
                    component_styles=preset.get("componentStyles"),
                )
                await repo.create(t)
            themes = await repo.list(is_preset=True)

    return [t.to_dict() for t in themes]


@router.get("/themes/{themeId}")
async def get_theme(
    themeId: str,
    session: AsyncSession = Depends(get_session),
):
    repo = ThemeRepository(session)
    theme = await repo.get(themeId)
    if not theme:
        raise HTTPException(404, f"Theme '{themeId}' not found")
    return theme.to_dict()


@router.patch("/themes/{themeId}")
async def update_theme(
    themeId: str,
    body: ThemeUpdateDTO,
    session: AsyncSession = Depends(get_session),
):
    repo = ThemeRepository(session)
    theme = await repo.get(themeId)
    if not theme:
        raise HTTPException(404, f"Theme '{themeId}' not found")
    if theme.is_preset:
        raise HTTPException(403, "Cannot modify preset themes")

    if body.name is not None:
        theme.name = body.name
    if body.colors is not None:
        theme.colors = body.colors
    if body.typography is not None:
        theme.typography = body.typography
    if body.componentStyles is not None:
        theme.component_styles = body.componentStyles

    theme = await repo.update(theme)
    return theme.to_dict()


@router.delete("/themes/{themeId}", status_code=204)
async def delete_theme(
    themeId: str,
    session: AsyncSession = Depends(get_session),
):
    repo = ThemeRepository(session)
    theme = await repo.get(themeId)
    if not theme:
        raise HTTPException(404, f"Theme '{themeId}' not found")
    if theme.is_preset:
        raise HTTPException(403, "Cannot delete preset themes")
    await repo.delete(theme)


# ── Course Theme Resolution ─────────────────

def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base."""
    result = deepcopy(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = deepcopy(val)
    return result


@router.get("/courses/{courseId}/theme")
async def get_course_theme(
    courseId: str,
    session: AsyncSession = Depends(get_session),
):
    course_repo = CourseRepository(session)
    course = await course_repo.get_by_course_id(courseId)
    if not course:
        raise HTTPException(404, f"Course '{courseId}' not found")

    # Get course theme settings from json_data
    settings = (course.json_data or {}).get("settings", {})
    theme_id = settings.get("themeId")
    overrides = settings.get("themeOverrides", {})

    theme_repo = ThemeRepository(session)

    if theme_id:
        theme = await theme_repo.get(theme_id)
    else:
        # Fall back to first preset
        presets = await theme_repo.list(is_preset=True)
        theme = presets[0] if presets else None

    if not theme:
        return {"resolved": {}, "inheritedFrom": "preset", "overrides": overrides}

    resolved = {
        "colors": theme.colors,
        "typography": theme.typography,
        "componentStyles": theme.component_styles or {},
    }
    if overrides:
        resolved = _deep_merge(resolved, overrides)

    return {
        "resolved": resolved,
        "inheritedFrom": "course",
        "overrides": overrides,
        "courseThemeId": theme.theme_id,
        "courseThemeName": theme.name,
    }


@router.patch("/courses/{courseId}/theme")
async def set_course_theme(
    courseId: str,
    body: CourseThemeDTO,
    session: AsyncSession = Depends(get_session),
):
    course_repo = CourseRepository(session)
    course = await course_repo.get_by_course_id(courseId)
    if not course:
        raise HTTPException(404, f"Course '{courseId}' not found")

    json_data = dict(course.json_data or {})
    settings = dict(json_data.get("settings", {}))

    if body.themeId is not None:
        settings["themeId"] = body.themeId
    if body.overrides is not None:
        settings["themeOverrides"] = body.overrides

    json_data["settings"] = settings
    course.json_data = json_data
    await course_repo.update_record(course)

    # Return resolved theme
    return await get_course_theme(courseId, session)


@router.get("/courses/{courseId}/pages/{pageId}/theme")
async def get_page_theme(
    courseId: str,
    pageId: str,
    session: AsyncSession = Depends(get_session),
):
    page_repo = PageRepository(session)
    page = await page_repo.get_by_course_and_page(courseId, pageId)
    if not page:
        raise HTTPException(404, f"Page '{pageId}' not found")

    # Start with resolved course theme
    course_theme = await get_course_theme(courseId, session)
    resolved = course_theme.get("resolved", {})

    # Apply page-level overrides
    page_theme_config = page.theme_config or {}
    page_overrides = page_theme_config.get("overrides", {})
    if page_overrides and page_theme_config.get("inheritCourse", True):
        resolved = _deep_merge(resolved, page_overrides)
    elif not page_theme_config.get("inheritCourse", True):
        # Page has its own theme, does not inherit
        resolved = page_overrides or {}

    return {
        "resolved": resolved,
        "inheritedFrom": "page",
        "overrides": page_overrides,
        "courseThemeId": course_theme.get("courseThemeId"),
        "courseThemeName": course_theme.get("courseThemeName"),
    }


@router.patch("/courses/{courseId}/pages/{pageId}/theme")
async def set_page_theme(
    courseId: str,
    pageId: str,
    body: dict,
    session: AsyncSession = Depends(get_session),
):
    page_repo = PageRepository(session)
    page = await page_repo.get_by_course_and_page(courseId, pageId)
    if not page:
        raise HTTPException(404, f"Page '{pageId}' not found")

    page.theme_config = body
    await page_repo.update(page)
    return await get_page_theme(courseId, pageId, session)
