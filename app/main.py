from __future__ import annotations
import os
from typing import List

from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware

from app.routers import (
    courses,
    templates,
    export,
    imports,
    health,
    media,
    enhanced_templates,
)


def _get_allowed_origins() -> List[str]:
    """Parse CORS origins from env or default to permissive wildcard."""
    raw = os.getenv("CORS_ORIGINS")
    if raw:
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        return origins or ["*"]
    return ["*"]


_ALLOWED_ORIGINS = _get_allowed_origins()


app = FastAPI(
    title="eLearning Backend API",
    version=os.getenv("APP_VERSION", "1.0.0"),
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
)

# Enable CORS for frontend access and tests expecting CORS headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
app.include_router(api_router)


@app.get("/")
async def root():
    return {"status": "ok", "message": "eLearning backend is running"}
