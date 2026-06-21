from __future__ import annotations
import logging
import os
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.openapi.utils import get_openapi

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


def _verify_critical_contracts() -> None:
    """Fail fast in logs when critical model/repository contracts drift."""
    from app.models.persisted_course import TemplateDefinition

    required_fields = (
        "template_type",
        "schema_signature",
        "render_template_html",
        "schema_json",
    )
    missing = [name for name in required_fields if not hasattr(TemplateDefinition, name)]
    if missing:
        raise RuntimeError(
            "TemplateDefinition contract mismatch; missing fields: "
            + ", ".join(missing)
        )


def _get_allowed_origins() -> List[str]:
    """Parse CORS origins from env var."""
    raw = os.getenv("CORS_ORIGINS", "")
    return [o.strip() for o in raw.split(",") if o.strip()]


def _get_origin_regex() -> str | None:
    """Return a regex matching all local dev origins when no explicit list given."""
    if os.getenv("CORS_ORIGINS"):
        return None  # explicit list takes precedence
    # Matches any scheme/host/port on localhost or a private LAN IP (192.168.x.x, 10.x.x.x, 172.16-31.x.x)
    return (
        r"https?://(localhost"
        r"|127\.0\.0\.1"
        r"|192\.168\.\d{1,3}\.\d{1,3}"
        r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
        r")(:\d+)?"
    )


_ALLOWED_ORIGINS = _get_allowed_origins()
_ORIGIN_REGEX = _get_origin_regex()


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
        import app.models.ai_models  # noqa: F401 — AI sessions, proposals, audit, etc.
        import app.models.ai_admin_override  # noqa: F401 — admin override audit trail
        import app.models.ai_safety_event  # noqa: F401 — safety events
        import app.models.course_embedding  # noqa: F401 — US-BKND-AI-015 embeddings
        import app.models.workflow  # noqa: F401 — US-BKND-AI-034 workflow engine

        # Create tables that don't exist yet (non-destructive)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Seed component types
        from app.services.seed_component_types import seed_component_types
        async with SessionLocal() as session:
            count = await seed_component_types(session)
            logger.info("Seeded %d component types", count)

        # Seed template types
        from app.services.seed_template_types import seed_template_types
        async with SessionLocal() as session:
            count = await seed_template_types(session)
            logger.info("Seeded %d template types", count)

        # Validate critical in-process contracts at startup.
        _verify_critical_contracts()

        # ── AI Configuration ──────────────────
        # Load AI config (feature flags, model routing, rate limits).
        # This does NOT crash if AI is disabled or misconfigured —
        # AI features degrade gracefully.
        try:
            from app.services.ai.config import load_ai_config
            ai_cfg = load_ai_config()
            if ai_cfg.ai_authoring_enabled:
                logger.info(
                    "AI authoring ENABLED — status: %s", ai_cfg.ai_status.value
                )
            else:
                logger.info("AI authoring DISABLED")

            # ── Workflow Engine (US-BKND-AI-034) ──────────────────
            try:
                from app.utils.feature_flags import is_feature_enabled
                if is_feature_enabled("durable_workflow_engine"):
                    from app.services.workflow.orchestrator import WorkflowOrchestrator
                    import app.services.workflow  # noqa: F401 — trigger step registration
                    orchestrator = WorkflowOrchestrator(
                        worker_id=os.getenv("WORKFLOW_WORKER_ID"),  # None → auto-gen
                        max_concurrency=int(os.getenv("WORKFLOW_MAX_CONCURRENCY", "4")),
                    )
                    app.state.workflow_orchestrator = orchestrator
                    await orchestrator.start()
                    logger.info(
                        "Workflow engine STARTED (worker=%s, concurrency=%d)",
                        orchestrator.worker_id, orchestrator.max_concurrency,
                    )
                else:
                    logger.info("Workflow engine DISABLED (feature flag off)")
            except Exception:
                logger.exception("Workflow engine failed to start — degraded mode")
        except Exception:
            logger.exception(
                "Error loading AI configuration — AI features will be unavailable"
            )
    except Exception:
        logger.exception("Error during startup seeding — continuing anyway")

    yield
    # ── Shutdown ─────────────────────────────
    if hasattr(app.state, 'workflow_orchestrator'):
        orchestrator = app.state.workflow_orchestrator
        await orchestrator.stop()
        logger.info("Workflow engine STOPPED")


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
    allow_origins=_ALLOWED_ORIGINS if _ALLOWED_ORIGINS else [],
    allow_origin_regex=_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── AI Middleware (US-BKND-AI-021) ──────────────────────────────
# Ordered outermost -> innermost: CORS -> RateLimiter -> Telemetry -> App
from app.middleware.ai_rate_limiter import AIRateLimitMiddleware
from app.middleware.ai_telemetry import AITelemetryMiddleware

app.add_middleware(AIRateLimitMiddleware)
app.add_middleware(AITelemetryMiddleware)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    errors = []
    for err in exc.errors():
        loc = err.get("loc", [])
        field = ".".join(str(p) for p in loc if p not in ("body",)) if loc else "body"
        errors.append({
            "code": "REQUEST_VALIDATION_ERROR",
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

# ── AI Routers (conditionally mounted) ────────────────────────
# AI routes are only available when AI_AUTHORING_ENABLED=true.
# When false, they don't appear in OpenAPI schema and return 404.
# Each import is wrapped in try/except so a broken AI router
# never prevents application startup (degraded AI is better than
# a crashed server).
from app.services.ai.config import get_ai_config
_ai_config = get_ai_config()
if _ai_config.ai_authoring_enabled:
    _ai_routers = {
        "ai_config": "ai_config",
        "ai_sessions": "ai_sessions",
        "ai_tools": "ai_tools",
        "ai_chat": "ai_chat",
        "ai_templates": "ai_templates",
        "ai_proposals": "ai_proposals",
        "ai_ingestion": "ai_ingestion",
        "ai_confirmations": "ai_confirmations",
        "ai_admin": "ai_admin",
        "ai_similar_courses": "ai_similar_courses",  # US-BKND-AI-015
        "ai_workflows": "workflows",  # US-BKND-AI-034
    }
    for _name, _module in _ai_routers.items():
        try:
            _imported = __import__(
                f"app.routers.{_module}", fromlist=["router"]
            )
            api_router.include_router(_imported.router)
            logger.info("AI router mounted: %s", _name)
        except Exception:
            logger.exception(
                "Failed to mount AI router '%s' — AI features degraded",
                _name,
            )

app.include_router(api_router)


def _schema_for_model(model):
    """Build an OpenAPI schema fragment for a Pydantic model."""
    if hasattr(model, "model_json_schema"):
        return model.model_json_schema(ref_template="#/components/schemas/{model}")
    return model.schema(ref_template="#/components/schemas/{model}")


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
    )

    from app.models.course import (
        FinalAssessmentData,
        FinalAssessmentQuestion,
        Question,
        QuestionOption,
    )

    components = schema.setdefault("components", {}).setdefault("schemas", {})
    for model in (
        QuestionOption,
        Question,
        FinalAssessmentQuestion,
        FinalAssessmentData,
    ):
        components.setdefault(model.__name__, _schema_for_model(model))

    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi


@app.get("/")
async def root():
    return {"status": "ok", "message": "eLearning backend is running"}
