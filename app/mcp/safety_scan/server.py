"""safety-scan-mcp server — Phase 3.2.

Standalone FastAPI app wrapping SafetyService behind MCP protocol.
Enables independent deployment of safety models (including future NeMo Guardrails).

Deploy: uvicorn app.mcp.safety_scan.server:app --port 8002
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("safety-scan-mcp")

app = FastAPI(title="safety-scan-mcp", version="1.0.0")


# ── MCP Protocol Schemas ─────────────────────────────────────────

class ToolCallRequest(BaseModel):
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class ToolCallResponse(BaseModel):
    content: List[Dict[str, Any]]
    isError: bool = False


# ── Static tool registry ────────────────────────────────────────

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "scan_input",
        "description": "Scan user input for injection, jailbreak, PII, and policy violations",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "maxLength": 10000},
                "user_id": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "scan_output",
        "description": "Scan AI-generated output for PII leaks, blocked terms, policy violations",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "maxLength": 50000},
                "session_id": {"type": "string"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "health",
        "description": "Health check with safety pattern status",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


# ── Service initialisation ───────────────────────────────────────

def _get_safety_service():
    """Lazy-init the SafetyService."""
    from app.services.ai.safety_service import SafetyService
    return SafetyService(prompt_safety_enabled=True, output_safety_enabled=True)


# ── MCP Endpoints ────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "server": "safety-scan-mcp", "version": "1.0.0"}


@app.get("/tools/list")
async def list_tools():
    return {"tools": TOOLS}


@app.post("/tools/call", response_model=ToolCallResponse)
async def call_tool(request: ToolCallRequest):
    tool_name = request.name
    args = request.arguments

    if tool_name == "health":
        svc = _get_safety_service()
        return ToolCallResponse(content=[{
            "type": "text",
            "text": f"safety-scan-mcp is healthy. "
                    f"Injection patterns: 9, PII patterns: 10. "
                    f"Input safety: {svc.prompt_safety_enabled}, "
                    f"Output safety: {svc.output_safety_enabled}.",
        }])

    if tool_name == "scan_input":
        try:
            svc = _get_safety_service()
            result = svc.scan_input(args.get("text", ""))
            return ToolCallResponse(content=[{
                "type": "text",
                "text": str(result),
            }, {
                "type": "resource",
                "resource": {
                    "allowed": result.allowed,
                    "blocks": result.blocks,
                    "warnings": result.warnings,
                    "sanitized_text": result.sanitized_text,
                },
            }])
        except Exception as exc:
            logger.exception("scan_input failed")
            return ToolCallResponse(content=[{"type": "text", "text": str(exc)}], isError=True)

    if tool_name == "scan_output":
        try:
            svc = _get_safety_service()
            result = svc.scan_output(args.get("text", ""))
            return ToolCallResponse(content=[{
                "type": "text",
                "text": str(result),
            }, {
                "type": "resource",
                "resource": {
                    "allowed": result.allowed,
                    "blocks": result.blocks,
                    "warnings": result.warnings,
                    "sanitized_text": result.sanitized_text,
                },
            }])
        except Exception as exc:
            logger.exception("scan_output failed")
            return ToolCallResponse(content=[{"type": "text", "text": str(exc)}], isError=True)

    raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")
