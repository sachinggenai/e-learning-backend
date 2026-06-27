"""template-registry-mcp server — Phase 3.3.

Standalone FastAPI app wrapping AITemplateContractsService behind MCP protocol.
Enables independent template updates without main app restart.

Deploy: uvicorn app.mcp.template_registry.server:app --port 8003
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("template-registry-mcp")

app = FastAPI(title="template-registry-mcp", version="1.0.0")


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
        "name": "list_templates",
        "description": "List all available template types with descriptions and use-cases",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filter": {"type": "string", "description": "Optional filter by category"},
            },
        },
    },
    {
        "name": "get_template_schema",
        "description": "Get the full JSON Schema for a specific template type",
        "inputSchema": {
            "type": "object",
            "properties": {
                "type_key": {"type": "string", "description": "Template type key (e.g., 'content-text', 'tabs')"},
            },
            "required": ["type_key"],
        },
    },
    {
        "name": "validate_against_template",
        "description": "Validate page data against a template's JSON Schema",
        "inputSchema": {
            "type": "object",
            "properties": {
                "type_key": {"type": "string"},
                "data": {"type": "object"},
            },
            "required": ["type_key", "data"],
        },
    },
    {
        "name": "search_templates",
        "description": "Semantic/keyword search for template discovery",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "health",
        "description": "Health check with template count",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


# ── Service initialisation ───────────────────────────────────────

def _get_contracts_service():
    """Lazy-init the AITemplateContractsService."""
    from app.services.ai.template_contracts import AITemplateContractsService
    return AITemplateContractsService()


# ── MCP Endpoints ────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "server": "template-registry-mcp", "version": "1.0.0"}


@app.get("/tools/list")
async def list_tools():
    return {"tools": TOOLS}


@app.post("/tools/call", response_model=ToolCallResponse)
async def call_tool(request: ToolCallRequest):
    tool_name = request.name
    args = request.arguments

    if tool_name == "health":
        try:
            svc = _get_contracts_service()
            contracts = await svc.list_contracts()
            return ToolCallResponse(content=[{
                "type": "text",
                "text": f"template-registry-mcp is healthy. {len(contracts)} template types registered.",
            }])
        except Exception as exc:
            return ToolCallResponse(content=[{"type": "text", "text": str(exc)}], isError=True)

    if tool_name == "list_templates":
        try:
            svc = _get_contracts_service()
            contracts = await svc.list_contracts()
            if args.get("filter"):
                contracts = [c for c in contracts if args["filter"].lower() in str(c).lower()]
            return ToolCallResponse(content=[{
                "type": "resource",
                "resource": {"templates": contracts, "count": len(contracts)},
            }])
        except Exception as exc:
            return ToolCallResponse(content=[{"type": "text", "text": str(exc)}], isError=True)

    if tool_name == "get_template_schema":
        try:
            svc = _get_contracts_service()
            schema = await svc.get_contract(args["type_key"])
            return ToolCallResponse(content=[{
                "type": "resource",
                "resource": {"type_key": args["type_key"], "schema": schema},
            }])
        except Exception as exc:
            return ToolCallResponse(content=[{"type": "text", "text": str(exc)}], isError=True)

    if tool_name == "validate_against_template":
        try:
            import jsonschema
            svc = _get_contracts_service()
            schema = await svc.get_contract(args["type_key"])
            if not schema:
                return ToolCallResponse(
                    content=[{"type": "text", "text": f"Unknown template type: {args['type_key']}"}],
                    isError=True,
                )
            jsonschema.validate(args["data"], schema.get("schema_json", {}))
            return ToolCallResponse(content=[{"type": "text", "text": "Validation passed."}])
        except Exception as exc:
            return ToolCallResponse(
                content=[{"type": "text", "text": f"Validation failed: {exc}"}],
                isError=True,
            )

    if tool_name == "search_templates":
        try:
            svc = _get_contracts_service()
            contracts = await svc.list_contracts()
            query = args.get("query", "").lower()
            scored = []
            for c in contracts:
                name = str(c.get("type_key", "")).lower()
                desc = str(c.get("description", "")).lower()
                score = sum(1 for w in query.split() if w in name or w in desc)
                if score > 0:
                    scored.append({**c, "_relevance": score})
            scored.sort(key=lambda x: x.get("_relevance", 0), reverse=True)
            max_results = args.get("max_results", 5)
            return ToolCallResponse(content=[{
                "type": "resource",
                "resource": {"results": scored[:max_results], "query": query},
            }])
        except Exception as exc:
            return ToolCallResponse(content=[{"type": "text", "text": str(exc)}], isError=True)

    raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")
