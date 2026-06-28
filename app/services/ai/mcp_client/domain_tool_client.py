"""
Domain Tool MCP Client — calls domain tool MCP servers.

Handles tool execution for the 7 ChatOrchestrator tools
(list_pages, fetch_page, query_similar_courses, propose_*,
validate_course, etc.) via MCP protocol.

Auto-falls back to in-process ToolExecutor when domain
tool servers are unreachable.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class DomainToolClient:
    """Client for domain tool MCP servers.

    Provides tool discovery and execution. When servers are
    unreachable, returns error responses — callers fall back
    to in-process execution.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8005",
        timeout: float = 60.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._is_healthy = False
        self._cached_tools: List[Dict[str, Any]] = []

    @property
    def is_healthy(self) -> bool:
        return self._is_healthy

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Health ───────────────────────────────────────────────

    async def check_health(self) -> bool:
        """Check domain tool server health."""
        try:
            client = await self._get_client()
            resp = await client.get(f"{self.base_url}/health")
            self._is_healthy = resp.status_code == 200
            return self._is_healthy
        except Exception:
            self._is_healthy = False
            return False

    # ── Tool Discovery ──────────────────────────────────────

    async def list_tools(self) -> List[Dict[str, Any]]:
        """Discover available domain tools."""
        try:
            client = await self._get_client()
            resp = await client.get(f"{self.base_url}/tools/list")
            resp.raise_for_status()
            data = resp.json()
            self._cached_tools = data.get("tools", [])
            return self._cached_tools
        except Exception as e:
            logger.warning("Failed to discover domain tools: %s", e)
            return self._cached_tools  # Return cached

    async def get_tool(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a specific tool definition."""
        tools = await self.list_tools()
        for tool in tools:
            if tool.get("name") == name:
                return tool
        return None

    # ── Tool Execution ──────────────────────────────────────

    async def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a tool via the domain tool MCP server.

        Returns:
            {"success": bool, "result": Any, "error": str}
        """
        if not self._is_healthy:
            await self.check_health()
            if not self._is_healthy:
                return {
                    "success": False,
                    "error": "Domain tool server unavailable",
                    "result": None,
                }

        try:
            client = await self._get_client()
            resp = await client.post(
                f"{self.base_url}/tools/call",
                json={"name": name, "arguments": arguments},
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("isError"):
                content = data.get("content", [{}])
                error_text = content[0].get("text", "Unknown error") if content else "Unknown error"
                return {"success": False, "error": error_text, "result": None}

            return {
                "success": True,
                "result": data.get("content", data),
                "error": None,
            }

        except httpx.HTTPStatusError as e:
            logger.error("Domain tool HTTP %d: %s", e.response.status_code, e)
            return {
                "success": False,
                "error": f"HTTP {e.response.status_code}",
                "result": None,
            }
        except httpx.RequestError as e:
            logger.error("Domain tool request error: %s", e)
            self._is_healthy = False
            return {
                "success": False,
                "error": "Domain tool server unreachable",
                "result": None,
            }
        except Exception as e:
            logger.exception("Domain tool call failed: %s", name)
            return {
                "success": False,
                "error": str(e)[:500],
                "result": None,
            }

    # ── High-Level Tool Methods ─────────────────────────────

    async def list_pages(self, session_id: str) -> Dict[str, Any]:
        """List pages in a course session."""
        return await self.call_tool("list_pages", {"session_id": session_id})

    async def fetch_page(self, session_id: str, page_id: str) -> Dict[str, Any]:
        """Fetch a specific page."""
        return await self.call_tool("fetch_page", {
            "session_id": session_id,
            "page_id": page_id,
        })

    async def query_similar_courses(
        self, session_id: str, query: str, max_results: int = 20
    ) -> Dict[str, Any]:
        """Query similar courses."""
        return await self.call_tool("query_similar_courses", {
            "session_id": session_id,
            "query": query,
            "max_results": max_results,
        })

    async def propose_create_page(
        self,
        session_id: str,
        title: str,
        template_type: str,
        content: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Propose creating a new page."""
        return await self.call_tool("propose_create_page", {
            "session_id": session_id,
            "title": title,
            "template_type": template_type,
            "content": content or {},
        })

    async def propose_update_page(
        self, session_id: str, page_id: str, **kwargs
    ) -> Dict[str, Any]:
        """Propose updating a page."""
        return await self.call_tool("propose_update_page", {
            "session_id": session_id,
            "page_id": page_id,
            **kwargs,
        })

    async def propose_delete_page(
        self, session_id: str, page_id: str
    ) -> Dict[str, Any]:
        """Propose deleting a page."""
        return await self.call_tool("propose_delete_page", {
            "session_id": session_id,
            "page_id": page_id,
        })

    async def validate_course(
        self, session_id: str, scope: str = "full"
    ) -> Dict[str, Any]:
        """Validate a course."""
        return await self.call_tool("validate_course", {
            "session_id": session_id,
            "scope": scope,
        })

    async def apply_proposal(
        self, session_id: str, proposal_id: str
    ) -> Dict[str, Any]:
        """Apply a proposal."""
        return await self.call_tool("apply_page_proposal", {
            "session_id": session_id,
            "proposal_id": proposal_id,
        })
