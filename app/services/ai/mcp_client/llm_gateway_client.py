"""
LLM Gateway MCP Client — high-level interface for LLM operations.

Discovers LLM Gateway tools, caches them, and provides
chat() and chat_stream() methods that call the gateway.

Handles graceful degradation when the gateway is unreachable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx
from app.services.ai.mcp_client.message import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionStreamEvent,
    ChatMessage,
    ToolCall,
    Usage,
    Choice,
)
from app.services.ai.mcp_client.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


class LLMGatewayClient:
    """Client for the LLM Gateway MCP Server.

    Discovers available tools via MCP protocol, caches them,
    and provides high-level chat/stream methods.

    When the gateway is unreachable, returns error responses
    rather than throwing — callers handle this gracefully.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8004",
        api_key: str = "",
        timeout: float = 120.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._is_healthy = False
        self._last_health_check = 0.0

    @property
    def is_healthy(self) -> bool:
        """Is the gateway currently reachable?"""
        return self._is_healthy

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the httpx client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                headers={"Content-Type": "application/json"},
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Health ───────────────────────────────────────────────

    async def check_health(self) -> bool:
        """Check if the gateway is reachable."""
        try:
            client = await self._get_client()
            resp = await client.get(f"{self.base_url}/health")
            self._is_healthy = resp.status_code == 200
            self._last_health_check = time.time()
            return self._is_healthy
        except Exception:
            self._is_healthy = False
            return False

    # ── Chat ─────────────────────────────────────────────────

    async def chat(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        """Send a non-streaming chat completion through the gateway.

        Returns an error response if the gateway is unreachable.
        """
        if not self._is_healthy:
            await self.check_health()
            if not self._is_healthy:
                return ChatCompletionResponse.from_content(
                    content="[LLM Gateway unavailable]",
                    provider="mcp-gateway",
                )

        try:
            client = await self._get_client()

            # Call gateway via OpenAI-compatible endpoint (more efficient than MCP tool call)
            body = request.to_openai_dict()

            resp = await client.post(
                f"{self.base_url}/v1/chat/completions",
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()

            return self._parse_openai_response(data)

        except httpx.HTTPStatusError as e:
            logger.error("Gateway HTTP error %d: %s", e.response.status_code, e)
            return ChatCompletionResponse.from_content(
                content=f"[Gateway error: {e.response.status_code}]",
                provider="mcp-gateway",
            )
        except httpx.RequestError as e:
            logger.error("Gateway request error: %s", e)
            self._is_healthy = False
            return ChatCompletionResponse.from_content(
                content="[LLM Gateway unreachable]",
                provider="mcp-gateway",
            )
        except Exception as e:
            logger.exception("Gateway chat failed")
            return ChatCompletionResponse.from_content(
                content=f"[Gateway error: {str(e)[:200]}]",
                provider="mcp-gateway",
            )

    # ── Stream ───────────────────────────────────────────────

    async def chat_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[ChatCompletionStreamEvent]:
        """Stream a chat completion through the gateway."""
        if not self._is_healthy:
            await self.check_health()

        if not self._is_healthy:
            yield ChatCompletionStreamEvent.error(
                "LLM Gateway unavailable", retryable=True
            )
            return

        try:
            client = await self._get_client()
            body = request.to_openai_dict()

            async with client.stream(
                "POST",
                f"{self.base_url}/tools/call",
                json={
                    "name": "stream_completion",
                    "arguments": {
                        "model": request.model,
                        "messages": [m.to_dict() for m in request.messages],
                        "tools": request.tools,
                        "max_tokens": request.max_tokens,
                        "temperature": request.temperature,
                    },
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    if line.startswith("event: "):
                        event_type = line[7:]
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        try:
                            data = json.loads(data_str)
                            yield ChatCompletionStreamEvent(
                                event_type=event_type or "text_delta",
                                data=data,
                            )
                        except json.JSONDecodeError:
                            continue

        except httpx.RequestError as e:
            self._is_healthy = False
            yield ChatCompletionStreamEvent.error(
                f"Gateway stream error: {e}", retryable=True
            )
        except Exception as e:
            yield ChatCompletionStreamEvent.error(
                f"Gateway stream error: {str(e)[:200]}", retryable=False
            )

    # ── Tool Discovery ──────────────────────────────────────

    async def list_tools(self) -> List[Dict[str, Any]]:
        """Discover available tools from the gateway."""
        try:
            client = await self._get_client()
            resp = await client.get(f"{self.base_url}/tools/list")
            resp.raise_for_status()
            data = resp.json()
            return data.get("tools", [])
        except Exception:
            return []

    async def list_providers(self) -> List[Dict[str, Any]]:
        """List registered LLM providers."""
        try:
            client = await self._get_client()
            resp = await client.post(
                f"{self.base_url}/tools/call",
                json={"name": "list_providers", "arguments": {}},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("content"):
                return json.loads(data["content"][0]["text"])
            return []
        except Exception:
            return []

    # ── Response Parsing ────────────────────────────────────

    def _parse_openai_response(self, data: Dict[str, Any]) -> ChatCompletionResponse:
        """Parse OpenAI-format response from gateway."""
        choices = []
        for c in data.get("choices", []):
            msg = c.get("message", {})
            tool_calls = None
            if msg and msg.get("tool_calls"):
                tool_calls = [
                    ToolCall(
                        id=tc.get("id", ""),
                        type=tc.get("type", "function"),
                        function=tc.get("function", {}),
                    )
                    for tc in msg["tool_calls"]
                ]
            choices.append(
                Choice(
                    index=c.get("index", 0),
                    message=ChatMessage(
                        role=msg.get("role", "assistant"),
                        content=msg.get("content"),
                        tool_calls=tool_calls,
                    ),
                    finish_reason=c.get("finish_reason", "stop"),
                )
            )

        usage = None
        if data.get("usage"):
            usage = Usage(
                prompt_tokens=data["usage"].get("prompt_tokens", 0),
                completion_tokens=data["usage"].get("completion_tokens", 0),
                total_tokens=data["usage"].get("total_tokens", 0),
            )

        return ChatCompletionResponse(
            id=data.get("id", ""),
            model=data.get("model", ""),
            choices=choices,
            usage=usage,
            created=data.get("created", 0),
            provider="mcp-gateway",
        )
