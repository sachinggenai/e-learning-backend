"""content-writer-mcp server — Phase 3.1.

Standalone FastAPI app wrapping AGT-07 Content Generator Agent behind MCP protocol.

Deploy: uvicorn app.mcp.content_writer.server:app --port 8001
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("content-writer-mcp")

app = FastAPI(title="content-writer-mcp", version="1.0.0")


# ── MCP Protocol Schemas ─────────────────────────────────────────

class ToolDef(BaseModel):
    name: str
    description: str
    inputSchema: Dict[str, Any] = Field(default_factory=dict)


class ToolCallRequest(BaseModel):
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class ToolCallResponse(BaseModel):
    content: List[Dict[str, Any]]
    isError: bool = False


# ── Static tool registry ────────────────────────────────────────

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "generate_page_content",
        "description": "Generate full educational content for a single e-learning page using LLM",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page_plan": {"type": "object", "description": "Page plan with title, learning_objective, source_content"},
                "template_type": {"type": "string", "enum": ["content-text", "tabs", "accordion", "click-reveal", "final-assessment"]},
                "rag_context": {"type": "array", "description": "Similar course examples for tone/style reference"},
                "course_context": {"type": "object", "description": "Course-level context: title, audience, tone"},
                "page_index": {"type": "integer"},
                "total_pages": {"type": "integer"},
            },
            "required": ["page_plan", "template_type", "course_context"],
        },
    },
    {
        "name": "health",
        "description": "Health check with model availability and rate limit status",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


# ── Service initialisation ───────────────────────────────────────

def _get_generator():
    """Lazy-init the ContentGeneratorAgent."""
    from app.services.ai.agents.content_generator_agent import ContentGeneratorAgent
    from app.services.ai.llm_client import LLMClient
    return ContentGeneratorAgent(llm_client=LLMClient())


# ── MCP Endpoints ────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "server": "content-writer-mcp", "version": "1.0.0"}


@app.get("/tools/list")
async def list_tools():
    """MCP: List available tools."""
    return {"tools": TOOLS}


@app.post("/tools/call", response_model=ToolCallResponse)
async def call_tool(request: ToolCallRequest):
    """MCP: Call a tool."""
    tool_name = request.name
    args = request.arguments

    if tool_name == "health":
        return ToolCallResponse(content=[{
            "type": "text",
            "text": "content-writer-mcp is healthy. Model: LLM via AGT-07 Content Generator Agent.",
        }])

    if tool_name == "generate_page_content":
        try:
            agent = _get_generator()
            result = await agent.generate_page(
                page_plan=args.get("page_plan", {}),
                template_assignment={"template_type": args.get("template_type", "content-text")},
                rag_context=args.get("rag_context", []),
                course_context=args.get("course_context", {}),
                page_index=args.get("page_index", 0),
                total_pages=args.get("total_pages", 1),
            )
            return ToolCallResponse(content=[{
                "type": "text",
                "text": str(result),
            }, {
                "type": "resource",
                "resource": {"json": result},
            }])
        except Exception as exc:
            logger.exception("generate_page_content failed")
            return ToolCallResponse(
                content=[{"type": "text", "text": str(exc)}],
                isError=True,
            )

    raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")
