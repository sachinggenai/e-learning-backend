"""
FastAPI dependency injection points for authentication and authorization.

This module re-exports mock auth and authZ dependencies. When real auth is
implemented, the import paths will change to point to the real
auth service instead of the mock.

TODO(AUTH): Update imports when real auth is implemented:
    from app.services.auth.dependencies import get_current_user
    from app.services.auth.authorization import require_admin

See: docs/AI_Implemenation/00_User_StoriesUseCases/backend-userstories/US-BKND-AI-PR01_enriched.md
     docs/AI_Implemenation/00_User_StoriesUseCases/backend-userstories/US-BKND-AI-PR02_enriched.md
"""

# TODO(AUTH): Change these imports when real auth is built
# from app.services.auth.dependencies import get_current_user, get_current_admin
from app.services.ai.mock_auth import get_current_user  # noqa: F401
from app.services.ai.mock_authorization import require_admin  # noqa: F401

__all__ = ["get_current_user", "require_admin"]
