"""
LLMClient → MCP adapter — format converters and backward-compat wrapper.

Converts between the existing LLM types (LLMMessage, LLMResponse,
LLMStreamEvent, ToolDef) and the canonical MCP format (ChatMessage,
ChatCompletionRequest, ChatCompletionResponse, ChatCompletionStreamEvent).

This allows llm_client.py to delegate to the MCP Gateway while
preserving its exact public API.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from app.services.ai.llm_client import (
    LLMMessage,
    LLMResponse,
    LLMStreamEvent,
    ToolDef,
)
from app.services.ai.mcp_client.message import (
    ChatMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionStreamEvent,
    ToolCall,
    Choice,
)


# ── LLMMessage → Canonical ───────────────────────────────────


def llm_message_to_canonical(msg: LLMMessage) -> ChatMessage:
    """Convert existing LLMMessage → canonical ChatMessage."""
    tool_calls = None
    if msg.tool_calls:
        tool_calls = [
            ToolCall(
                id=tc.get("id", ""),
                type="function",
                function={
                    "name": tc.get("name", ""),
                    "arguments": json.dumps(tc.get("input", {})),
                },
            )
            for tc in msg.tool_calls
        ]

    tool_call_id = None
    if msg.tool_results:
        # Pick the first tool_use_id for the tool message
        for tr in msg.tool_results:
            tool_call_id = tr.get("tool_use_id", "")
            break

    return ChatMessage(
        role=_map_role(msg.role),
        content=msg.content,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
    )


def llm_messages_to_canonical(
    messages: List[LLMMessage],
    system_prompt: str = "",
) -> List[ChatMessage]:
    """Convert a list of LLMMessage → list of ChatMessage.

    System messages are prepended if system_prompt is provided.
    """
    result = []
    if system_prompt:
        result.append(ChatMessage.system(system_prompt))
    for msg in messages:
        if msg.role == "system":
            # System messages may appear as regular messages
            if not system_prompt:
                result.append(ChatMessage.system(msg.content or ""))
        else:
            result.append(llm_message_to_canonical(msg))
    return result


# ── Tools → Canonical ───────────────────────────────────────


def tools_to_canonical(tools: List[ToolDef]) -> List[Dict[str, Any]]:
    """Convert existing ToolDef list → OpenAI tool format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in tools
    ]


# ── Canonical → LLMResponse ─────────────────────────────────


def canonical_to_llm_response(
    response: ChatCompletionResponse,
    latency_ms: float = 0.0,
) -> LLMResponse:
    """Convert canonical ChatCompletionResponse → existing LLMResponse."""
    content = response.content
    tool_calls = []
    if response.tool_calls:
        tool_calls = [
            {
                "id": tc.id,
                "name": tc.function.get("name", ""),
                "input": _parse_args(tc.function.get("arguments", {})),
            }
            for tc in response.tool_calls
        ]

    usage = {}
    if response.usage:
        usage = {
            "input": response.usage.prompt_tokens,
            "output": response.usage.completion_tokens,
        }

    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        stop_reason=response.finish_reason,
        token_usage=usage,
        model=response.model,
        latency_ms=latency_ms or response.latency_ms,
    )


# ── Canonical Stream → LLMStreamEvent ───────────────────────


def canonical_stream_to_llm_event(
    event: ChatCompletionStreamEvent,
) -> LLMStreamEvent:
    """Convert canonical ChatCompletionStreamEvent → existing LLMStreamEvent."""
    event_map = {
        "text_delta": "text_delta",
        "tool_call_delta": "tool_call_delta",
        "tool_call_start": "tool_call_start",
        "done": "turn_complete",
        "error": "error",
    }
    mapped_type = event_map.get(event.event_type, event.event_type)

    data = dict(event.data)
    if mapped_type == "turn_complete" and "usage" in data:
        data["token_usage"] = {
            "input": data.get("usage", {}).get("prompt_tokens", 0),
            "output": data.get("usage", {}).get("completion_tokens", 0),
        }
    if mapped_type == "error":
        data["message"] = data.get("message", str(data))

    return LLMStreamEvent(event_type=mapped_type, data=data)


# ── Helpers ─────────────────────────────────────────────────


def _map_role(role: str) -> str:
    """Map LLMClient role → canonical role."""
    mapping = {
        "user": "user",
        "assistant": "assistant",
        "system": "system",
        "tool_result": "tool",
    }
    return mapping.get(role, "user")


def _parse_args(args: Any) -> Dict[str, Any]:
    """Parse tool call arguments — may be string or dict."""
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        try:
            return json.loads(args)
        except (json.JSONDecodeError, TypeError):
            return {"raw": args}
    return {}
