"""FastAPI dependency injection points.

This package re-exports authentication, authorization, and tenant
dependencies for use in route handlers.

TODO(AUTH): Update imports when real auth services are built.
"""

from app.dependencies.auth_dependencies import get_current_user, require_admin

__all__ = ["get_current_user", "require_admin"]
