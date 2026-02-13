from __future__ import annotations
import logging
import os
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.routers import (
    courses,
    templates,
    export,
    imports,
    health,
    media,
    enhanced_templates,
    component_registry,
    page_components,
    themes,
    scoring_completion,
    audio,
    branching,
    social,
    analytics,
)

logger = logging.getLogger(__name__)


def _get_allowed_origins() -> List[str]:
    """Parse CORS origins from env or default to permissive wildcard."""
    raw = os.getenv("CORS_ORIGINS")
    if raw:
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        return origins or ["*"]
    return ["*"]


_ALLOWED_ORIGINS = _get_allowed_origins()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle hook."""
    # ── Startup ──────────────────────────────
    try:
        from app.db.config import engine, SessionLocal
        from app.models.base import Base

        # Import all ORM models so Base.metadata knows about them
        import app.models.persisted_course  # noqa: F401
        import app.models.page_component  # noqa: F401
        import app.models.component_type  # noqa: F401
        import app.models.scoring  # noqa: F401
        import app.models.theme  # noqa: F401
        import app.models.branching  # noqa: F401
        import app.models.social  # noqa: F401
        import app.models.interaction_event  # noqa: F401

        # Create tables that don't exist yet (non-destructive)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Seed component types
        from app.services.seed_component_types import seed_component_types
        async with SessionLocal() as session:
            count = await seed_component_types(session)
            logger.info("Seeded %d component types", count)
    except Exception:
        logger.exception("Error during startup seeding — continuing anyway")

    yield
    # ── Shutdown (nothing needed) ────────────


app = FastAPI(
    title="eLearning Backend API",
    version=os.getenv("APP_VERSION", "1.0.0"),
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    lifespan=lifespan,
)

# Enable CORS for frontend access and tests expecting CORS headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    errors = []
    for err in exc.errors():
        loc = err.get("loc", [])
        field = ".".join(str(p) for p in loc if p not in ("body",)) if loc else "body"
        errors.append({
            "field": field or "body",
            "message": err.get("msg", "Validation error"),
        })
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Validation failed",
            "errors": errors,
        },
    )


@app.middleware("http")
async def ensure_cors_header(request, call_next):
    """Add a permissive CORS header when Starlette does not set one."""
    response = await call_next(request)
    if "access-control-allow-origin" not in response.headers:
        response.headers["access-control-allow-origin"] = (
            "*" if "*" in _ALLOWED_ORIGINS else ",".join(_ALLOWED_ORIGINS)
        )
    return response

# Namespace all routes under /api/v1
api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(courses.router)
api_router.include_router(templates.router)
api_router.include_router(export.router)
api_router.include_router(imports.router)
api_router.include_router(media.router)
api_router.include_router(enhanced_templates.router)
api_router.include_router(component_registry.router)
api_router.include_router(page_components.router)
api_router.include_router(themes.router)
api_router.include_router(scoring_completion.router)
api_router.include_router(audio.router)
api_router.include_router(branching.router)
api_router.include_router(social.router)
api_router.include_router(analytics.router)
app.include_router(api_router)


@app.get("/")
async def root():
    return {"status": "ok", "message": "eLearning backend is running"}
