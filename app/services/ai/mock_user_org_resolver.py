"""Mock User & Organization Resolver.

Provides mock user profiles and organization settings for AI features
to display names, validate org config, and populate audit log details.

TODO(USER): Replace with real user service (identity provider / directory).
TODO(TENANT): Replace with real organization service (tenant registry).

Production will integrate with:
- Identity Provider (Auth0, Okta, Azure AD) for user profiles
- Tenant Registry Service for organization settings and billing
- Organization Membership Service for member lists

See: docs/AI_Implemenation/00_User_StoriesUseCases/backend-userstories/US-BKND-AI-PR05_enriched.md
"""

import hashlib
from typing import Dict, List, Optional

# Deterministic mock name list seeded from UUIDs
_MOCK_NAMES = ["Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Quinn", "Avery"]


def _mock_name(user_id: str) -> str:
    """Generate a deterministic mock display name from a user ID."""
    idx = int(hashlib.md5(user_id.encode()).hexdigest(), 16) % len(_MOCK_NAMES)
    return f"{_MOCK_NAMES[idx]} (Mock User {user_id[:8]})"


async def get_user_profile(user_id: str) -> dict:
    """Resolve a mock user profile.

    Returns deterministic mock data based on user_id.

    TODO(USER): Call identity provider API: GET /users/{user_id}
    Returns real display_name, email, avatar_url, department, etc.
    """
    return {
        "user_id": user_id,
        "display_name": _mock_name(user_id),
        "email": f"mock.user.{user_id[:8]}@example.com",
        "avatar_url": None,
        "role": "instructor",
        "organization_id": "00000000-0000-0000-0000-000000000100",
    }


async def get_organization_settings(org_id: str) -> dict:
    """Resolve mock organization settings.

    Returns deterministic mock settings based on org_id.

    TODO(TENANT): Call tenant registry API: GET /tenants/{org_id}/settings
    Returns real feature flags, rate limits, billing tier, allowed models.
    """
    return {
        "organization_id": org_id,
        "name": f"Mock Organization {org_id[:8]}",
        "ai_authoring_enabled": True,
        "ai_rate_limit_calls_per_hour": 100,
        "ai_rate_limit_calls_per_day": 500,
        "ai_monthly_cost_cap_usd": 500.0,
        "ai_allowed_models": [
            "claude-sonnet-4-20250514",
            "claude-haiku-4-20250514",
        ],
        "max_courses_per_org": 1000,
        "max_pages_per_course": 100,
        "scorm_export_enabled": True,
    }


async def list_organization_members(org_id: str) -> List[dict]:
    """Return mock organization member list.

    TODO(USER): Query organization membership service.
    Returns real users with roles within the organization.
    """
    return [
        {
            "user_id": f"user-{i:04d}",
            "display_name": f"Mock User {i}",
            "role": "instructor",
            "email": f"mock.user{i}@example.com",
        }
        for i in range(1, 6)
    ]


async def resolve_users(user_ids: List[str]) -> Dict[str, dict]:
    """Batch-resolve user profiles.

    TODO(USER): Batch API call to identity provider for efficiency.
    """
    result = {}
    for uid in user_ids:
        result[uid] = await get_user_profile(uid)
    return result
