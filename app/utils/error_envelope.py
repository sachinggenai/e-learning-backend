"""Normalized API error envelope helpers.

Shape:
{
  "code": "ERROR_CODE",
  "field": "field.path",
  "message": "Human-readable message",
  "details": { ... }
}
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException


def build_error(
    code: str,
    message: str,
    field: str = "request",
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code,
        "field": field,
        "message": message,
        "details": details or {},
    }
    return payload


def api_http_exception(
    status_code: int,
    code: str,
    message: str,
    field: str = "request",
    details: Optional[Dict[str, Any]] = None,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=build_error(
            code=code,
            message=message,
            field=field,
            details=details,
        ),
    )
