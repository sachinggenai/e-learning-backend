# US-BKND-AI-PR05 — Mock User & Organization Resolver

**Priority:** MUST (PRE-REQUISITE)
**Story Points:** 2
**Sprint:** 0 (Foundation)
**Depends On:** US-BKND-AI-PR01, US-BKND-AI-PR03
**Unlocks:** ALL AI stories that reference user profiles or organization settings

---

## 1. Functional Specification

### 1.1 User Story

As a **Backend Engineer building AI features**, I want mock resolvers that return user profiles and organization metadata from mock data stores, so that AI features can display user names, validate organization settings, and populate audit log details without real user/org services.

### 1.2 Functional Requirements

**FR-1: User Profile Resolution**
`get_user_profile(user_id)` MUST return a mock `UserProfile` with `display_name`, `email`, `avatar_url`, `role`, and `organization_id`.

**FR-2: Organization Settings Resolution**
`get_organization_settings(org_id)` MUST return mock `OrganizationSettings` with AI feature flags, rate limits, cost caps, and allowed models.

**FR-3: Organization Member List**
`list_organization_members(org_id)` MUST return a list of mock users in the organization. Used for collaboration features (US-AI-047).

**FR-4: Bulk User Resolution**
`resolve_users(user_ids: list[str])` MUST return a dict of `user_id -> UserProfile`. `# TODO(USER):` for real user service batch resolution.

**FR-5: Mock Data Consistency**
Repeated calls with the same `user_id` or `org_id` MUST return consistent mock data (deterministic from the ID).

---

## 2. Technical Specification

### 2.1 `app/services/ai/mock_user_org_resolver.py`

```python
"""
Mock User & Organization Resolver

TODO(USER): Replace with real user service (identity provider / directory).
TODO(TENANT): Replace with real organization service (tenant registry).

Production will integrate with:
- Identity Provider (Auth0, Okta, Azure AD) for user profiles
- Tenant Registry Service for organization settings and billing
- Organization Membership Service for member lists
"""

import hashlib
from typing import Dict, List, Optional
from app.models.user_context import UserContext, UserRole

# Deterministic mock data seeded from UUIDs
def _mock_name(user_id: str) -> str:
    """Generate a deterministic mock display name from a user ID."""
    names = ["Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Quinn", "Avery"]
    idx = int(hashlib.md5(user_id.encode()).hexdigest(), 16) % len(names)
    return f"{names[idx]} (Mock User {user_id[:8]})"


async def get_user_profile(user_id: str) -> dict:
    """Resolve a mock user profile.

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
        "ai_allowed_models": ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"],
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
        {"user_id": f"user-{i:04d}", "display_name": f"Mock User {i}", "role": "instructor"}
        for i in range(1, 6)
    ]


async def resolve_users(user_ids: List[str]) -> Dict[str, dict]:
    """Batch-resolve user profiles.

    TODO(USER): Batch API call to identity provider.
    """
    result = {}
    for uid in user_ids:
        result[uid] = await get_user_profile(uid)
    return result
```

---

## 6. Validation & Testing

- TC-PR05-01: `get_user_profile()` returns deterministic mock data for a given user_id
- TC-PR05-02: Same user_id returns same display_name on repeated calls
- TC-PR05-03: `get_organization_settings()` returns AI feature flags
- TC-PR05-04: `list_organization_members()` returns 5 mock users
- TC-PR05-05: `resolve_users()` batch resolves 3 user_ids correctly

---

## 7. Definition of Done

- [ ] `mock_user_org_resolver.py` implemented with all 4 functions
- [ ] Deterministic mock data from user_id/org_id seeds
- [ ] All functions have `# TODO(USER):` and `# TODO(TENANT):` comments
- [ ] Unit tests pass (5 scenarios)
- [ ] Integration test: AI session creation uses resolver to populate audit fields
- [ ] Code reviewed

---

## 8. Tasks

| Task ID | Description | Owner | Est. | Depends On |
|---|---|---|---|---|
| PR05-T1 | Create `app/services/ai/mock_user_org_resolver.py` with all 4 functions | Backend | 1.5h | PR01-T1, PR03-T1 |
| PR05-T2 | Write 5 unit tests for user/org resolution | Backend | 1h | PR05-T1 |
| PR05-T3 | Integration test: resolver used in session creation flow | Backend | 0.5h | PR05-T1 |
| PR05-T4 | Code review | Lead | 0.5h | PR05-T2 |

---

---