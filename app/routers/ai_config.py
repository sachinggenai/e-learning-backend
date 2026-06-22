"""AI Configuration router.

Exposes AI feature status for frontend consumption.
"""

from fastapi import APIRouter

from app.services.ai.config import get_ai_config

router = APIRouter(prefix="/ai", tags=["AI - Configuration"])


@router.get("/feature-status")
async def get_ai_feature_status():
    """Return current AI feature status for frontend consumption.

    The frontend calls this at boot time to decide whether to show
    the "Build with AI" button and AI chat panel.

    Response is always 200 (even when AI is disabled) so the frontend
    can gracefully handle the disabled state.
    """
    config = get_ai_config()

    if not config.ai_authoring_enabled:
        return {
            "aiAuthoringEnabled": False,
            "aiStatus": "unavailable",
            "activeModel": None,
            "fallbackModel": None,
            "rateLimits": None,
        }

    try:
        primary = config.get_primary_model()
        fallback = config.get_fallback_model()
    except ValueError:
        # Model config is invalid — AI is degraded
        return {
            "aiAuthoringEnabled": True,
            "aiStatus": "degraded",
            "activeModel": None,
            "fallbackModel": None,
            "rateLimits": {
                "callsPerHour": config.rate_limit_calls_per_hour,
                "callsPerDay": config.rate_limit_calls_per_day,
            },
        }

    return {
        "aiAuthoringEnabled": True,
        "aiStatus": config.ai_status.value,
        "activeModel": {
            "id": primary.id,
            "provider": primary.provider,
            "tier": primary.tier.value,
        },
        "fallbackModel": {
            "id": fallback.id,
            "provider": fallback.provider,
            "tier": fallback.tier.value,
        },
        "rateLimits": {
            "callsPerHour": config.rate_limit_calls_per_hour,
            "callsPerDay": config.rate_limit_calls_per_day,
        },
    }
