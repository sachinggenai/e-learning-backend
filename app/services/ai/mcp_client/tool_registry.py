"""
Local cache of MCP tools discovered from MCP servers.

Periodically refreshed from MCP server tool lists.
Provides fast lookup for tool invocation.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.services.ai.mcp_client.types import MCPToolDef


class ToolRegistry:
    """Local cache of MCP tools discovered from servers.

    Thread-safe. Tools are discovered via MCP protocol and cached
    locally for fast lookup during chat orchestration.
    """

    def __init__(self):
        self._tools: Dict[str, MCPToolDef] = {}  # name → tool
        self._server_tools: Dict[str, List[str]] = {}  # server_url → [tool_names]
        self._last_refresh: Dict[str, float] = {}  # server_url → timestamp

    def register_tool(self, tool: MCPToolDef) -> None:
        """Register a single tool."""
        self._tools[tool.name] = tool
        if tool.server_url not in self._server_tools:
            self._server_tools[tool.server_url] = []
        if tool.name not in self._server_tools[tool.server_url]:
            self._server_tools[tool.server_url].append(tool.name)

    def register_tools(self, tools: List[MCPToolDef], server_url: str = "") -> None:
        """Register multiple tools from a server."""
        for tool in tools:
            if not tool.server_url and server_url:
                tool.server_url = server_url
            if not tool.server_name and server_url:
                tool.server_name = server_url
            self.register_tool(tool)
        if server_url:
            self._last_refresh[server_url] = time.time()

    def get_tool(self, name: str) -> Optional[MCPToolDef]:
        """Look up a tool by name."""
        return self._tools.get(name)

    def list_tools(self, server_url: str = "") -> List[MCPToolDef]:
        """List all tools, optionally filtered by server."""
        if server_url:
            names = self._server_tools.get(server_url, [])
            return [self._tools[n] for n in names if n in self._tools]
        return list(self._tools.values())

    def list_tool_names(self) -> List[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def unregister_server(self, server_url: str) -> None:
        """Remove all tools from a server."""
        names = self._server_tools.pop(server_url, [])
        for name in names:
            self._tools.pop(name, None)

    def get_last_refresh(self, server_url: str) -> float:
        """Get the timestamp of the last successful refresh."""
        return self._last_refresh.get(server_url, 0.0)

    def clear(self) -> None:
        """Clear all registered tools."""
        self._tools.clear()
        self._server_tools.clear()
        self._last_refresh.clear()

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
