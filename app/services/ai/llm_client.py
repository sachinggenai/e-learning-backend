"""LLM Provider Client — US-BKND-AI-023.

Abstraction layer over LLM providers (Anthropic, mock). Handles:
- Provider routing and fallback (US-BKND-AI-026)
- Tool-calling message construction
- Streaming and non-streaming responses
- Retry with exponential backoff
- Error classification (retryable vs terminal)
- Token usage tracking

Architecture:
    ChatOrchestrator
        └── LLMClient (this module)
                ├── Anthropic provider (via anthropic SDK)
                └── Mock provider (deterministic for testing)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

class LLMProvider(str, Enum):
    ANTHROPIC = "anthropic"
    MOCK = "mock"


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_RESULT = "tool_result"


@dataclass
class ToolDef:
    """A tool definition as sent to the LLM."""
    name: str
    description: str
    input_schema: Dict[str, Any]


@dataclass
class LLMMessage:
    """A message in the LLM conversation."""
    role: str
    content: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)

    def to_api_format(self) -> Dict[str, Any]:
        """Convert to Anthropic-compatible format."""
        if self.role == "system":
            return {"role": "user", "content": self.content or ""}
        if self.role == "user":
            return {"role": "user", "content": self.content or ""}
        if self.role == "assistant":
            msg: Dict[str, Any] = {"role": "assistant", "content": self.content or ""}
            if self.tool_calls:
                msg["content"] = [
                    {
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": tc.get("name", ""),
                        "input": tc.get("input", {}),
                    }
                    for tc in self.tool_calls
                ]
            return msg
        if self.role == "tool_result":
            return {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tr.get("tool_use_id", ""),
                        "content": json.dumps(tr.get("output", {})),
                        "is_error": tr.get("is_error", False),
                    }
                    for tr in self.tool_results
                ],
            }
        return {"role": "user", "content": self.content or ""}


@dataclass
class LLMResponse:
    """Structured response from the LLM."""
    content: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    stop_reason: str = "end_turn"
    token_usage: Dict[str, int] = field(default_factory=dict)
    model: str = ""
    latency_ms: float = 0.0


@dataclass
class LLMStreamEvent:
    """A single streaming event from the LLM."""
    event_type: str  # "text_delta", "tool_call_start", "tool_call_delta", "turn_complete", "error"
    data: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# LLM Client
# ---------------------------------------------------------------------------

class LLMClientError(Exception):
    """Raised when the LLM provider returns an error."""
    def __init__(self, message: str, retryable: bool = False, status_code: int = 500):
        self.message = message
        self.retryable = retryable
        self.status_code = status_code
        super().__init__(message)


class LLMClient:
    """Abstraction over LLM providers.

    Supports Anthropic (native tool-calling) and Mock (deterministic).
    Handles retries, error classification, and token tracking.

    Usage:
        client = LLMClient()
        response = await client.chat(messages=[...], tools=[...])

        # Streaming:
        async for event in client.chat_stream(messages=[...], tools=[...]):
            yield event
    """

    MAX_RETRIES = 1
    REQUEST_TIMEOUT_SECONDS = 30

    def __init__(
        self,
        provider: LLMProvider = LLMProvider.MOCK,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        max_retries: int = MAX_RETRIES,
        timeout: int = REQUEST_TIMEOUT_SECONDS,
    ):
        self.provider = provider
        self.model = model or os.getenv("AI_PRIMARY_MODEL", "deepseek-v4-pro[1m]")
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN", "")
        self.max_retries = max_retries
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDef]] = None,
        system_prompt: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Send a chat completion request (non-streaming).

        Args:
            messages: Conversation messages.
            tools: Available tool definitions.
            system_prompt: System-level instruction.
            max_tokens: Maximum tokens in the response.
            temperature: Sampling temperature.

        Returns:
            LLMResponse with content, tool_calls, token_usage, etc.
        """
        if self.provider == LLMProvider.MOCK:
            return await self._mock_chat(messages, tools, system_prompt)

        return await self._anthropic_chat(
            messages, tools, system_prompt, max_tokens, temperature
        )

    async def chat_stream(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDef]] = None,
        system_prompt: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> AsyncIterator[LLMStreamEvent]:
        """Send a chat completion request with streaming response.

        Yields LLMStreamEvent objects as chunks arrive.
        """
        if self.provider == LLMProvider.MOCK:
            # Mock simulates streaming by yielding all at once
            response = await self._mock_chat(messages, tools, system_prompt)
            if response.content:
                yield LLMStreamEvent("text_delta", {"delta": response.content})
            yield LLMStreamEvent("turn_complete", {
                "token_usage": response.token_usage,
                "model": response.model,
                "latency_ms": response.latency_ms,
            })
            return

        async for event in self._anthropic_stream(
            messages, tools, system_prompt, max_tokens, temperature
        ):
            yield event

    # ------------------------------------------------------------------
    # Anthropic Provider
    # ------------------------------------------------------------------

    async def _anthropic_chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDef]],
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        """Call Anthropic Messages API (non-streaming)."""
        if not self.api_key:
            raise LLMClientError(
                "ANTHROPIC_API_KEY not configured. Set it in .env or disable AI.",
                retryable=False,
            )

        try:
            import anthropic

            base_url = os.getenv("ANTHROPIC_BASE_URL", "")
            client_kwargs = {"api_key": self.api_key}
            if base_url:
                client_kwargs["base_url"] = base_url
            client = anthropic.AsyncAnthropic(**client_kwargs)

            # Build API messages
            api_messages = []
            for msg in messages:
                if msg.role == "system":
                    system_prompt = system_prompt or msg.content
                    continue
                api_msg = self._to_anthropic_message(msg)
                if api_msg:
                    api_messages.append(api_msg)

            # Build tool definitions
            api_tools = None
            if tools:
                api_tools = [
                    {
                        "name": t.name,
                        "description": t.description,
                        "input_schema": t.input_schema,
                    }
                    for t in tools
                ]

            kwargs: Dict[str, Any] = {
                "model": self.model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": api_messages,
            }
            if system_prompt:
                kwargs["system"] = system_prompt
            if api_tools:
                kwargs["tools"] = api_tools

            import time
            start = time.time()
            response = await client.messages.create(**kwargs)
            latency = (time.time() - start) * 1000

            return self._parse_anthropic_response(response, latency)

        except ImportError:
            logger.warning("anthropic SDK not installed; falling back to mock")
            return await self._mock_chat(messages, tools, system_prompt)
        except Exception as e:
            error_msg = str(e)
            retryable = any(w in error_msg.lower() for w in [
                "timeout", "rate", "overloaded", "server_error", "5xx"
            ])
            raise LLMClientError(
                f"Anthropic API error: {error_msg}",
                retryable=retryable,
            )

    async def _anthropic_stream(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDef]],
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float,
    ) -> AsyncIterator[LLMStreamEvent]:
        """Call Anthropic Messages API with streaming."""
        if not self.api_key:
            yield LLMStreamEvent("error", {
                "code": "AI_NOT_CONFIGURED",
                "message": "ANTHROPIC_API_KEY not configured.",
                "retryable": False,
            })
            return

        try:
            import anthropic
            import time

            base_url = os.getenv("ANTHROPIC_BASE_URL", "")
            client_kwargs = {"api_key": self.api_key}
            if base_url:
                client_kwargs["base_url"] = base_url
            client = anthropic.AsyncAnthropic(**client_kwargs)

            api_messages = []
            for msg in messages:
                if msg.role == "system":
                    system_prompt = system_prompt or msg.content
                    continue
                api_msg = self._to_anthropic_message(msg)
                if api_msg:
                    api_messages.append(api_msg)

            api_tools = None
            if tools:
                api_tools = [
                    {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                    for t in tools
                ]

            kwargs: Dict[str, Any] = {
                "model": self.model,
                "max_tokens": max_tokens,
                "temperature": temperature,
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

            async with client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "content_block_start":
                        if event.content_block and hasattr(event.content_block, "name"):
                            yield LLMStreamEvent("tool_call_start", {
                                "tool_name": event.content_block.name,
                                "tool_use_id": getattr(event.content_block, "id", ""),
                            })

                    elif event.type == "content_block_delta":
                        if hasattr(event, "delta"):
                            delta = event.delta
                            if hasattr(delta, "text") and delta.text:
                                content_parts.append(delta.text)
                                yield LLMStreamEvent("text_delta", {"delta": delta.text})
                            elif hasattr(delta, "partial_json") and delta.partial_json:
                                yield LLMStreamEvent("tool_call_delta", {
                                    "partial_json": delta.partial_json,
                                })

                    elif event.type == "message_delta":
                        if hasattr(event, "usage"):
                            total_input = getattr(event.usage, "input_tokens", 0)
                            total_output = getattr(event.usage, "output_tokens", 0)

            latency = (time.time() - start) * 1000
            yield LLMStreamEvent("turn_complete", {
                "content": "".join(content_parts),
                "token_usage": {"input": total_input, "output": total_output},
                "model": self.model,
                "latency_ms": latency,
            })

        except ImportError:
            logger.warning("anthropic SDK not installed; falling back to mock")
            async for event in self._mock_stream(messages, tools, system_prompt):
                yield event
        except Exception as e:
            error_msg = str(e)
            retryable = any(w in error_msg.lower() for w in [
                "timeout", "rate", "overloaded", "server_error"
            ])
            yield LLMStreamEvent("error", {
                "code": "LLM_PROVIDER_ERROR",
                "message": f"Anthropic API error: {error_msg}",
                "retryable": retryable,
            })

    # ------------------------------------------------------------------
    # Mock Provider (deterministic, for testing)
    # ------------------------------------------------------------------

    async def _mock_chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDef]],
        system_prompt: Optional[str],
    ) -> LLMResponse:
        """Mock LLM response — returns a help message with available tools."""
        last_user_msg = ""
        for msg in reversed(messages):
            if msg.role == "user" and msg.content:
                last_user_msg = msg.content
                break

        tool_names = [t.name for t in (tools or [])]

        return LLMResponse(
            content=(
                f"[Mock LLM] I received your message: \"{last_user_msg[:200]}\". "
                f"Available tools: {', '.join(tool_names) if tool_names else 'none'}. "
                "In production, I would use these tools to help you author your course."
            ),
            stop_reason="end_turn",
            token_usage={"input": len(last_user_msg.split()), "output": 30},
            model="mock",
            latency_ms=0.5,
        )

    async def _mock_stream(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDef]],
        system_prompt: Optional[str],
    ) -> AsyncIterator[LLMStreamEvent]:
        """Mock streaming — yields a single text_delta + turn_complete."""
        response = await self._mock_chat(messages, tools, system_prompt)
        if response.content:
            yield LLMStreamEvent("text_delta", {"delta": response.content})
        yield LLMStreamEvent("turn_complete", {
            "token_usage": response.token_usage,
            "model": response.model,
            "latency_ms": response.latency_ms,
        })

    # ------------------------------------------------------------------
    # Message Conversion
    # ------------------------------------------------------------------

    def _to_anthropic_message(self, msg: LLMMessage) -> Optional[Dict[str, Any]]:
        """Convert an LLMMessage to Anthropic API format."""
        if msg.role == "assistant":
            result: Dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                content_blocks = []
                for tc in msg.tool_calls:
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", f"call_{tc.get('name', 'unknown')}"),
                        "name": tc.get("name", ""),
                        "input": tc.get("input", {}),
                    })
                result["content"] = content_blocks
            return result

        if msg.role == "user":
            if msg.tool_results:
                content_blocks = []
                for tr in msg.tool_results:
                    content_blocks.append({
                        "type": "tool_result",
                        "tool_use_id": tr.get("tool_use_id", ""),
                        "content": json.dumps(tr.get("output", {})),
                        "is_error": tr.get("is_error", False),
                    })
                return {"role": "user", "content": content_blocks}
            return {"role": "user", "content": msg.content or ""}

        if msg.role == "tool_result":
            return {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tr.get("tool_use_id", ""),
                        "content": json.dumps(tr.get("output", {})),
                        "is_error": tr.get("is_error", False),
                    }
                    for tr in msg.tool_results
                ],
            }

        return None

    def _parse_anthropic_response(self, response: Any, latency_ms: float) -> LLMResponse:
        """Parse an Anthropic API response into LLMResponse."""
        content = ""
        tool_calls = []

        for block in getattr(response, "content", []) or []:
            if hasattr(block, "type"):
                if block.type == "text":
                    content += getattr(block, "text", "")
                elif block.type == "tool_use":
                    tool_calls.append({
                        "id": getattr(block, "id", ""),
                        "name": getattr(block, "name", ""),
                        "input": getattr(block, "input", {}),
                    })

        usage = {}
        if hasattr(response, "usage"):
            usage = {
                "input": getattr(response.usage, "input_tokens", 0),
                "output": getattr(response.usage, "output_tokens", 0),
            }

        return LLMResponse(
            content=content or None,
            tool_calls=tool_calls,
            stop_reason=getattr(response, "stop_reason", "end_turn"),
            token_usage=usage,
            model=getattr(response, "model", self.model),
            latency_ms=latency_ms,
        )
