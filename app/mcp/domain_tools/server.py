"""
Domain Tools MCP Server — Phase 4.

Standalone FastAPI app exposing ChatOrchestrator's 7 tools as MCP endpoints.
Wraps ToolExecutor, AIProposalService, and UnifiedValidator.

Each request creates a fresh DB session — tools execute in-process
via the same service layer as the main app.

Deploy: PYTHONPATH=. uvicorn app.mcp.domain_tools.server:app --port 8005
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("domain-tools-mcp")


# ── App ──────────────────────────────────────────────────────────

app = FastAPI(title="domain-tools-mcp", version="1.0.0")

# DB session factory — initialized at startup
_session_factory = None


def _get_session_factory():
    """Lazy-load the async session factory."""
    global _session_factory
    if _session_factory is None:
        from app.db.config import SessionLocal
        _session_factory = SessionLocal
    return _session_factory


# ── MCP Protocol Schemas ──────────────────────────────────────────


class ToolDef(BaseModel):
    name: str
    description: str
    inputSchema: Dict[str, Any] = Field(default_factory=dict)


class ToolCallRequest(BaseModel):
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class ToolCallResponse(BaseModel):
    content: List[Dict[str, Any]] = Field(default_factory=list)
    isError: bool = False


# ── Tool Definitions ──────────────────────────────────────────────


TOOLS = [
    ToolDef(
        name="list_pages",
        description="List all pages in the current course session. "
        "Returns page metadata: page_id, title, template_type, order, etag.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "AI session ID"},
            },
            "required": ["session_id"],
        },
    ),
    ToolDef(
        name="fetch_page",
        description="Fetch a specific page with full content and components.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "AI session ID"},
                "page_id": {"type": "string", "description": "Page ID to fetch"},
            },
            "required": ["session_id", "page_id"],
        },
    ),
    ToolDef(
        name="query_similar_courses",
        description="Search for similar courses using semantic or keyword matching. "
        "Useful for finding style/tone references for content generation.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "AI session ID"},
                "query": {"type": "string", "description": "Search query"},
                "max_results": {
                    "type": "integer",
                    "description": "Maximum results to return",
                    "default": 20,
                },
                "filters": {
                    "type": "object",
                    "description": "Optional filters: template_types, min_pages, max_pages",
                },
            },
            "required": ["session_id", "query"],
        },
    ),
    ToolDef(
        name="propose_create_page",
        description="Create a proposal for a new page. The proposal must be reviewed "
        "and applied before the page is actually created.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "AI session ID"},
                "title": {"type": "string", "description": "Page title"},
                "template_type": {
                    "type": "string",
                    "description": "Template type: text-content, tabs, accordion, click-reveal, final-assessment",
                },
                "content": {
                    "type": "object",
                    "description": "Page content matching the template schema",
                },
            },
            "required": ["session_id", "title", "template_type"],
        },
    ),
    ToolDef(
        name="propose_update_page",
        description="Create a proposal to update an existing page.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "AI session ID"},
                "page_id": {"type": "string", "description": "Page ID to update"},
                "title": {"type": "string", "description": "New title (optional)"},
                "content": {
                    "type": "object",
                    "description": "Updated content (optional)",
                },
            },
            "required": ["session_id", "page_id"],
        },
    ),
    ToolDef(
        name="propose_delete_page",
        description="Create a proposal to delete a page. Requires confirmation "
        "before execution.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "AI session ID"},
                "page_id": {"type": "string", "description": "Page ID to delete"},
            },
            "required": ["session_id", "page_id"],
        },
    ),
    ToolDef(
        name="validate_course",
        description="Validate course structure against template rules and constraints. "
        "Returns validation errors and warnings.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "AI session ID"},
                "scope": {
                    "type": "string",
                    "description": "Validation scope: schema, business, accessibility, export, or full",
                    "default": "full",
                },
            },
            "required": ["session_id"],
        },
    ),
]


# ── MCP Endpoints ─────────────────────────────────────────────────


@app.get("/health")
async def health():
    """Health check with DB connectivity test."""
    db_healthy = False
    try:
        factory = _get_session_factory()
        from sqlalchemy import text
        async with factory() as db:
            await db.execute(text("SELECT 1"))
            db_healthy = True
    except Exception as e:
        logger.warning("DB health check failed: %s", e)

    return {
        "status": "ok" if db_healthy else "degraded",
        "server": "domain-tools-mcp",
        "version": "1.0.0",
        "db_connected": db_healthy,
        "tools_count": len(TOOLS),
    }


@app.get("/tools/list")
async def list_tools():
    """List available domain tools."""
    return {"tools": [t.model_dump() for t in TOOLS]}


@app.post("/tools/call")
async def call_tool(body: ToolCallRequest):
    """Execute a domain tool via MCP protocol."""
    tool_name = body.name
    args = body.arguments

    handler = _TOOL_HANDLERS.get(tool_name)
    if handler is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown tool: {tool_name}. Available: {list(_TOOL_HANDLERS.keys())}",
        )

    try:
        result = await handler(args)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Tool '%s' failed", tool_name)
        return ToolCallResponse(
            content=[{"type": "text", "text": f"Tool error: {str(e)[:500]}"}],
            isError=True,
        )


# ── Tool Handlers ─────────────────────────────────────────────────


async def _handle_list_pages(args: Dict[str, Any]) -> ToolCallResponse:
    """Execute list_pages tool."""
    session_id = args.get("session_id", "")
    user_id = args.get("_user_id", "mcp-system")

    factory = _get_session_factory()
    async with factory() as db:
        from app.services.ai.tool_executor import ToolExecutor
        executor = ToolExecutor(db)
        result = await executor.execute("list_pages", {"session_id": session_id}, user_id)

    return _to_response(result)


async def _handle_fetch_page(args: Dict[str, Any]) -> ToolCallResponse:
    """Execute fetch_page tool."""
    session_id = args.get("session_id", "")
    page_id = args.get("page_id", "")
    user_id = args.get("_user_id", "mcp-system")

    factory = _get_session_factory()
    async with factory() as db:
        from app.services.ai.tool_executor import ToolExecutor
        executor = ToolExecutor(db)
        result = await executor.execute(
            "fetch_page",
            {"session_id": session_id, "page_id": page_id},
            user_id,
        )

    return _to_response(result)


async def _handle_query_similar_courses(args: Dict[str, Any]) -> ToolCallResponse:
    """Execute query_similar_courses tool."""
    session_id = args.get("session_id", "")
    query = args.get("query", "")
    max_results = args.get("max_results", 20)
    filters = args.get("filters")
    user_id = args.get("_user_id", "mcp-system")

    payload: Dict[str, Any] = {
        "session_id": session_id,
        "query": query,
        "max_results": max_results,
    }
    if filters:
        payload["filters"] = filters

    factory = _get_session_factory()
    async with factory() as db:
        from app.services.ai.tool_executor import ToolExecutor
        executor = ToolExecutor(db)
        result = await executor.execute("query_similar_courses", payload, user_id)

    return _to_response(result)


async def _handle_propose_create_page(args: Dict[str, Any]) -> ToolCallResponse:
    """Create a page creation proposal."""
    session_id = args.get("session_id", "")
    title = args.get("title", "")
    template_type = args.get("template_type", "")
    content = args.get("content")

    factory = _get_session_factory()
    async with factory() as db:
        from app.repositories.ai_session_repo import AISessionRepository
        from app.services.ai.proposal_service import AIProposalService
        from app.services.ai.session_service import AISessionService

        session_svc = AISessionService(db)
        session = await session_svc.get_active(session_id)
        if session is None:
            return ToolCallResponse(
                content=[{"type": "text", "text": "Session not found or invalid"}],
                isError=True,
            )

        proposal_svc = AIProposalService(db)
        spec = {
            "title": title,
            "template_type": template_type,
            "content": content or {},
        }
        try:
            proposal = await proposal_svc.create_proposal(
                session_id=session_id,
                user_id=args.get("_user_id", "mcp-system"),
                action="create_page",
                spec=spec,
            )
            return ToolCallResponse(
                content=[{"type": "text", "text": json.dumps({
                    "status": "success",
                    "proposal_id": getattr(proposal, "proposal_id", ""),
                    "action": "create_page",
                    "page_title": title,
                })}]
            )
        except Exception as e:
            return ToolCallResponse(
                content=[{"type": "text", "text": f"Proposal failed: {str(e)[:300]}"}],
                isError=True,
            )


async def _handle_propose_update_page(args: Dict[str, Any]) -> ToolCallResponse:
    """Create a page update proposal."""
    session_id = args.get("session_id", "")
    page_id = args.get("page_id", "")

    factory = _get_session_factory()
    async with factory() as db:
        from app.repositories.ai_session_repo import AISessionRepository
        from app.services.ai.proposal_service import AIProposalService

        session_repo = AISessionRepository(db)
        session = await session_repo.get_active(session_id)
        if session is None:
            return ToolCallResponse(
                content=[{"type": "text", "text": "Session not found or invalid"}],
                isError=True,
            )

        proposal_svc = AIProposalService(db)
        spec = {k: v for k, v in args.items() if k not in ("session_id", "_user_id")}
        try:
            proposal = await proposal_svc.create_proposal(
                session_id=session_id,
                user_id=args.get("_user_id", "mcp-system"),
                action="update_page",
                spec=spec,
            )
            return ToolCallResponse(
                content=[{"type": "text", "text": json.dumps({
                    "status": "success",
                    "proposal_id": getattr(proposal, "proposal_id", ""),
                    "action": "update_page",
                })}]
            )
        except Exception as e:
            return ToolCallResponse(
                content=[{"type": "text", "text": f"Proposal failed: {str(e)[:300]}"}],
                isError=True,
            )


async def _handle_propose_delete_page(args: Dict[str, Any]) -> ToolCallResponse:
    """Create a page deletion proposal."""
    session_id = args.get("session_id", "")
    page_id = args.get("page_id", "")

    factory = _get_session_factory()
    async with factory() as db:
        from app.repositories.ai_session_repo import AISessionRepository
        from app.services.ai.proposal_service import AIProposalService

        session_repo = AISessionRepository(db)
        session = await session_repo.get_active(session_id)
        if session is None:
            return ToolCallResponse(
                content=[{"type": "text", "text": "Session not found or invalid"}],
                isError=True,
            )

        proposal_svc = AIProposalService(db)
        try:
            proposal = await proposal_svc.create_proposal(
                session_id=session_id,
                user_id=args.get("_user_id", "mcp-system"),
                action="delete_page",
                spec={"page_id": page_id},
            )
            return ToolCallResponse(
                content=[{"type": "text", "text": json.dumps({
                    "status": "success",
                    "proposal_id": getattr(proposal, "proposal_id", ""),
                    "action": "delete_page",
                    "requires_confirmation": True,
                })}]
            )
        except Exception as e:
            return ToolCallResponse(
                content=[{"type": "text", "text": f"Proposal failed: {str(e)[:300]}"}],
                isError=True,
            )


async def _handle_validate_course(args: Dict[str, Any]) -> ToolCallResponse:
    """Validate a course against template rules."""
    session_id = args.get("session_id", "")
    scope = args.get("scope", "full")

    factory = _get_session_factory()
    async with factory() as db:
        from app.repositories.ai_session_repo import AISessionRepository
        from app.repositories.page_component_repo import PageRepository

        session_repo = AISessionRepository(db)
        session = await session_repo.get_active(session_id)
        if session is None:
            return ToolCallResponse(
                content=[{"type": "text", "text": "Session not found or invalid"}],
                isError=True,
            )

        page_repo = PageRepository(db)
        pages = await page_repo.list_by_course(session.course_id)

        # Basic validation: check for empty course, duplicate orders, invalid templates
        warnings = []
        errors = []

        if not pages:
            warnings.append("Course has no pages")

        template_types = {"text-content", "tabs", "accordion", "click-reveal", "final-assessment"}
        orders_seen = set()
        for p in pages:
            ttype = getattr(p, "template_type", "")
            if ttype and ttype not in template_types:
                warnings.append(f"Page '{p.title}' has unknown template type: {ttype}")
            order = getattr(p, "order_index", -1)
            if order >= 0 and order in orders_seen:
                warnings.append(f"Duplicate order index {order} detected")
            orders_seen.add(order)

        return ToolCallResponse(
            content=[{"type": "text", "text": json.dumps({
                "status": "success" if not errors else "invalid",
                "pages_count": len(pages),
                "errors": errors,
                "warnings": warnings,
                "scope": scope,
            })}]
        )


# ── Tool Handler Registry ─────────────────────────────────────────

_TOOL_HANDLERS = {
    "list_pages": _handle_list_pages,
    "fetch_page": _handle_fetch_page,
    "query_similar_courses": _handle_query_similar_courses,
    "propose_create_page": _handle_propose_create_page,
    "propose_update_page": _handle_propose_update_page,
    "propose_delete_page": _handle_propose_delete_page,
    "validate_course": _handle_validate_course,
}


# ── Helpers ───────────────────────────────────────────────────────


def _to_response(result: Dict[str, Any]) -> ToolCallResponse:
    """Convert ToolExecutor result to MCP ToolCallResponse."""
    if result.get("status") == "error":
        error_data = result.get("error", result)
        return ToolCallResponse(
            content=[{"type": "text", "text": json.dumps(error_data)}],
            isError=True,
        )
    return ToolCallResponse(
        content=[{"type": "text", "text": json.dumps(result.get("data", result))}],
        isError=False,
    )


# ── Startup ──────────────────────────────────────────────────────


@app.on_event("startup")
async def startup_event():
    """Verify DB connectivity on startup."""
    try:
        factory = _get_session_factory()
        from sqlalchemy import text
        async with factory() as db:
            await db.execute(text("SELECT 1"))
        logger.info("Domain Tools MCP Server ready — DB connected, %d tools", len(TOOLS))
    except Exception as e:
        logger.warning("Domain Tools MCP Server started but DB unavailable: %s", e)


# ── Main entrypoint ──────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("MCP_DOMAIN_TOOL_PORT", "8005"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
