"""
Anthropic LLM Backend — uses the anthropic Python SDK.

Converts the canonical ChatCompletionRequest to Anthropic Messages API format,
calls the Anthropic SDK, and converts the response back to canonical format.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import AsyncIterator, List, Optional

from app.services.ai.mcp_client.message import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionStreamEvent,
    ChatMessage,
    ToolCall,
    Usage,
    Choice,
)
from app.services.ai.mcp_client.types import ProviderHealth
from app.mcp.llm_gateway.backends.base import (
    LLMBackend,
    BackendCapabilities,
)

logger = logging.getLogger(__name__)


class AnthropicBackend(LLMBackend):
    """Anthropic provider via the official anthropic SDK.

    Supports Claude models (Opus, Sonnet, Haiku) and any
    Anthropic-compatible API endpoint (DeepSeek, LiteLLM proxy, etc.)
    via the ANTHROPIC_BASE_URL env var.
    """

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def supported_models(self) -> List[str]:
        return [
            "claude-opus-4-20250514",
            "claude-sonnet-4-20250514",
            "claude-haiku-4-20250514",
            "deepseek-v4-pro[1m]",
            "deepseek-v4-flash",
        ]

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 60,
    ):
        super().__init__()
        self._capabilities = BackendCapabilities(
            streaming=True,
            tool_calling=True,
            structured_output=True,
            max_context_tokens=200000,
            max_output_tokens=4096,
        )
        self.api_key = (
            api_key
            or os.getenv("ANTHROPIC_API_KEY")
            or os.getenv("ANTHROPIC_AUTH_TOKEN", "")
        )
        self.base_url = base_url or os.getenv("ANTHROPIC_BASE_URL", "")
        self.timeout = timeout
        self._sdk_available = False
        try:
            import anthropic  # noqa: F401
            self._sdk_available = True
        except ImportError:
            logger.warning("anthropic SDK not installed — AnthropicBackend unavailable")

    # ── Chat ─────────────────────────────────────────────────

    async def chat(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        if not self._sdk_available:
            return self._sdk_missing_response(request)

        import anthropic

        api_messages, system_prompt = self._convert_messages(request)
        api_tools = self._convert_tools(request)

        client_kwargs: dict = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        client = anthropic.AsyncAnthropic(**client_kwargs)

        kwargs: dict = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": api_messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if api_tools:
            kwargs["tools"] = api_tools

        start = time.time()
        response = await client.messages.create(**kwargs)
        latency = (time.time() - start) * 1000

        return self._parse_anthropic_response(response, request.model, latency)

    # ── Stream ───────────────────────────────────────────────

    async def chat_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[ChatCompletionStreamEvent]:
        if not self._sdk_available:
            yield ChatCompletionStreamEvent.error(
                "anthropic SDK not installed", retryable=False
            )
            return

        import anthropic

        api_messages, system_prompt = self._convert_messages(request)
        api_tools = self._convert_tools(request)

        client_kwargs: dict = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        client = anthropic.AsyncAnthropic(**client_kwargs)

        kwargs: dict = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": api_messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if api_tools:
            kwargs["tools"] = api_tools

        start = time.time()
        total_input = 0
        total_output = 0
        content_parts: List[str] = []

        try:
            async with client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "content_block_start":
                        if hasattr(event.content_block, "name") and event.content_block.name:
                            yield ChatCompletionStreamEvent.tool_call_start(
                                tool_name=event.content_block.name,
                                tool_id=getattr(event.content_block, "id", ""),
                            )

                    elif event.type == "content_block_delta":
                        if hasattr(event, "delta"):
                            delta = event.delta
                            if hasattr(delta, "text") and delta.text:
                                content_parts.append(delta.text)
                                yield ChatCompletionStreamEvent.text_delta(
                                    text=delta.text
                                )
                            elif hasattr(delta, "partial_json") and delta.partial_json:
                                yield ChatCompletionStreamEvent.tool_call_delta(
                                    partial_json=delta.partial_json
                                )

                    elif event.type == "message_delta":
                        if hasattr(event, "usage") and event.usage:
                            total_input = getattr(event.usage, "input_tokens", 0)
                            total_output = getattr(event.usage, "output_tokens", 0)

            latency = (time.time() - start) * 1000
            yield ChatCompletionStreamEvent.done(
                usage=Usage(
                    prompt_tokens=total_input,
                    completion_tokens=total_output,
                    total_tokens=total_input + total_output,
                ),
                model=request.model,
            )

        except anthropic.APIStatusError as e:
            yield ChatCompletionStreamEvent.error(
                f"Anthropic API error {e.status_code}: {e.message}",
                retryable=e.status_code >= 500,
            )
        except Exception as e:
            yield ChatCompletionStreamEvent.error(str(e), retryable=False)

    # ── Health ───────────────────────────────────────────────

    async def health(self) -> ProviderHealth:
        if not self._sdk_available:
            return ProviderHealth.UNHEALTHY
        if not self.api_key:
            return ProviderHealth.DEGRADED
        return ProviderHealth.HEALTHY

    # ── Format Converters ────────────────────────────────────

    def _convert_messages(
        self, request: ChatCompletionRequest
    ) -> tuple:
        """Convert canonical messages → Anthropic format.

        Returns (anthropic_messages, system_prompt).
        """
        anthropic_messages = []
        system_prompt = None

        for msg in request.messages:
            if msg.role == "system":
                system_prompt = msg.content
                continue

            if msg.role == "user":
                if msg.tool_calls:
                    # This shouldn't happen in normal flow
                    anthropic_messages.append({
                        "role": "user",
                        "content": msg.content or "",
                    })
                else:
                    anthropic_messages.append({
                        "role": "user",
                        "content": msg.content or "",
                    })

            elif msg.role == "assistant":
                if msg.tool_calls:
                    content_blocks = []
                    if msg.content:
                        content_blocks.append({
                            "type": "text",
                            "text": msg.content,
                        })
                    for tc in msg.tool_calls:
                        args = tc.function.get("arguments", {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except (json.JSONDecodeError, TypeError):
                                args = {"raw": args}
                        content_blocks.append({
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.function.get("name", ""),
                            "input": args,
                        })
                    anthropic_messages.append({
                        "role": "assistant",
                        "content": content_blocks,
                    })
                else:
                    anthropic_messages.append({
                        "role": "assistant",
                        "content": msg.content or "",
                    })

            elif msg.role == "tool":
                anthropic_messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.tool_call_id or "",
                            "content": msg.content or "",
                        }
                    ],
                })

        return anthropic_messages, system_prompt

    def _convert_tools(
        self, request: ChatCompletionRequest
    ) -> Optional[List[dict]]:
        """Convert canonical tools → Anthropic format."""
        if not request.tools:
            return None
        return [
            {
                "name": tool.get("function", {}).get("name", tool.get("name", "")),
                "description": (
                    tool.get("function", {}).get("description", "")
                    or tool.get("description", "")
                ),
                "input_schema": (
                    tool.get("function", {}).get("parameters", {})
                    or tool.get("parameters", {})
                ),
            }
            for tool in request.tools
        ]

    def _parse_anthropic_response(
        self, response, model: str, latency_ms: float
    ) -> ChatCompletionResponse:
        """Parse Anthropic API response → canonical format."""
        content = ""
        tool_calls = []

        for block in getattr(response, "content", []) or []:
            if hasattr(block, "type"):
                if block.type == "text":
                    content += getattr(block, "text", "")
                elif block.type == "tool_use":
                    tool_calls.append(
                        ToolCall(
                            id=getattr(block, "id", ""),
                            type="function",
                            function={
                                "name": getattr(block, "name", ""),
                                "arguments": json.dumps(
                                    getattr(block, "input", {})
                                ),
                            },
                        )
                    )

        usage = Usage()
        if hasattr(response, "usage"):
            usage = Usage(
                prompt_tokens=getattr(response.usage, "input_tokens", 0),
                completion_tokens=getattr(response.usage, "output_tokens", 0),
                total_tokens=(
                    getattr(response.usage, "input_tokens", 0)
                    + getattr(response.usage, "output_tokens", 0)
                ),
            )

        if tool_calls:
            return ChatCompletionResponse.from_tool_calls(
                tool_calls=tool_calls,
                model=model,
                provider="anthropic",
            )
        # Add usage manually since from_content doesn't take usage
        resp = ChatCompletionResponse.from_content(
            content=content or "[no content]",
            model=model,
            provider="anthropic",
        )
        resp.usage = usage
        resp.latency_ms = latency_ms
        return resp

    def _sdk_missing_response(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        """Fallback when SDK not installed."""
        return ChatCompletionResponse.from_content(
            content=(
                "[AnthropicBackend] The anthropic SDK is not installed. "
                "Install it with: pip install anthropic"
            ),
            model=request.model,
            provider="anthropic",
        )
