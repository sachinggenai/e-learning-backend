"""Helpers for consistent error responses."""
from __future__ import annotations
from typing import Iterable

from fastapi.responses import JSONResponse


def validation_error(detail: str, errors: Iterable[dict], status_code: int = 422) -> JSONResponse:
    """Return a ValidationErrorResponse-shaped payload.

    Expected schema: {"detail": str, "errors": [{"field": str, "message": str}]}
    """
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": detail,
            "errors": list(errors),
        },
    )
