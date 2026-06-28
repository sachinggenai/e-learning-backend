"""
Canonical message format for LLM provider interchange.

Uses the OpenAI Chat Completions format as the canonical standard,
since it is the industry norm and supported by litellm, openai SDK,
Ollama, and most other providers.

All LLMBackend implementations convert to/from this format internally.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional


# ── Request Types ────────────────────────────────────────────


@dataclass
class ToolCall:
    """A tool/function call from the LLM."""
    id: str
    type: str = "function"
    function: Dict[str, Any] = field(default_factory=dict)
    # function = {"name": "...", "arguments": "..."}


@dataclass
class ChatMessage:
    """A single message in the conversation."""
    role: str  # "system" | "user" | "assistant" | "tool"
    content: Optional[str] = None
    name: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to OpenAI API dict format."""
        d: Dict[str, Any] = {"role": self.role}
        if self.content is not None:
            d["content"] = self.content
        if self.name:
            d["name"] = self.name
        if self.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": tc.function,
                }
                for tc in self.tool_calls
            ]
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        return d

    @classmethod
    def system(cls, content: str) -> "ChatMessage":
        """Factory: system message."""
        return cls(role="system", content=content)

    @classmethod
    def user(cls, content: str) -> "ChatMessage":
        """Factory: user message."""
        return cls(role="user", content=content)

    @classmethod
    def assistant(
        cls,
        content: Optional[str] = None,
        tool_calls: Optional[List[ToolCall]] = None,
    ) -> "ChatMessage":
        """Factory: assistant message."""
        return cls(role="assistant", content=content, tool_calls=tool_calls)

    @classmethod
    def tool(cls, tool_call_id: str, content: str) -> "ChatMessage":
        """Factory: tool result message."""
        return cls(role="tool", content=content, tool_call_id=tool_call_id)


# ── Request ──────────────────────────────────────────────────


@dataclass
class ChatCompletionRequest:
    """Provider-agnostic chat completion request."""
    model: str
    messages: List[ChatMessage] = field(default_factory=list)
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[str] = None  # "auto" | "none" | "required" | specific
    max_tokens: int = 4096
    temperature: float = 0.7
    top_p: float = 1.0
    stream: bool = False
    stop: Optional[List[str]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_openai_dict(self) -> Dict[str, Any]:
        """Convert to OpenAI-compatible API request dict."""
        d: Dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_dict() for m in self.messages],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "stream": self.stream,
        }
        if self.tools:
            d["tools"] = self.tools
        if self.tool_choice:
            d["tool_choice"] = self.tool_choice
        if self.stop:
            d["stop"] = self.stop
        return d

    @property
    def user_message_count(self) -> int:
        """Count user messages (for token estimation)."""
        return sum(1 for m in self.messages if m.role == "user")


# ── Response Types ────────────────────────────────────────────


@dataclass
class Choice:
    """A single completion choice."""
    index: int = 0
    message: Optional[ChatMessage] = None
    finish_reason: str = "stop"  # "stop" | "length" | "tool_calls" | "error"
    delta: Optional[Dict[str, Any]] = None  # For streaming chunks


@dataclass
class Usage:
    """Token usage information."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ChatCompletionResponse:
    """Provider-agnostic chat completion response."""
    id: str = field(default_factory=lambda: f"chatcmpl_{uuid.uuid4().hex[:12]}")
    model: str = ""
    choices: List[Choice] = field(default_factory=list)
    usage: Optional[Usage] = None
    created: int = field(default_factory=lambda: int(time.time()))
    provider: str = ""  # Which provider handled this request
    latency_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_content(
        cls,
        content: str,
        model: str = "",
        provider: str = "",
    ) -> "ChatCompletionResponse":
        """Factory: simple text response."""
        return cls(
            model=model,
            provider=provider,
            choices=[
                Choice(
                    index=0,
                    message=ChatMessage(role="assistant", content=content),
                    finish_reason="stop",
                )
            ],
        )

    @classmethod
    def from_tool_calls(
        cls,
        tool_calls: List[ToolCall],
        model: str = "",
        provider: str = "",
    ) -> "ChatCompletionResponse":
        """Factory: tool call response."""
        return cls(
            model=model,
            provider=provider,
            choices=[
                Choice(
                    index=0,
                    message=ChatMessage(
                        role="assistant",
                        content=None,
                        tool_calls=tool_calls,
                    ),
                    finish_reason="tool_calls",
                )
            ],
        )

    @property
    def content(self) -> Optional[str]:
        """Convenience: get text content from first choice."""
        if self.choices and self.choices[0].message:
            return self.choices[0].message.content
        return None

    @property
    def tool_calls(self) -> List[ToolCall]:
        """Convenience: get tool calls from first choice."""
        if self.choices and self.choices[0].message and self.choices[0].message.tool_calls:
            return self.choices[0].message.tool_calls
        return []

    @property
    def finish_reason(self) -> str:
        """Convenience: get finish reason from first choice."""
        if self.choices:
            return self.choices[0].finish_reason
        return "stop"


# ── Streaming Types ───────────────────────────────────────────


@dataclass
class ChatCompletionStreamEvent:
    """A single streaming event from a provider backend."""
    event_type: str  # "text_delta" | "tool_call_delta" | "tool_call_start" | "done" | "error"
    data: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def text_delta(cls, text: str) -> "ChatCompletionStreamEvent":
        """Factory: text delta event."""
        return cls(event_type="text_delta", data={"text": text})

    @classmethod
    def tool_call_start(cls, tool_name: str, tool_id: str = "") -> "ChatCompletionStreamEvent":
        """Factory: tool call start event."""
        return cls(
            event_type="tool_call_start",
            data={"tool_name": tool_name, "tool_id": tool_id},
        )

    @classmethod
    def tool_call_delta(cls, partial_json: str) -> "ChatCompletionStreamEvent":
        """Factory: tool call argument delta."""
        return cls(
            event_type="tool_call_delta",
            data={"partial_json": partial_json},
        )

    @classmethod
    def done(cls, usage: Optional[Usage] = None, model: str = "") -> "ChatCompletionStreamEvent":
        """Factory: stream complete event."""
        data: Dict[str, Any] = {"model": model}
        if usage:
            data["usage"] = {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            }
        return cls(event_type="done", data=data)

    @classmethod
    def error(cls, message: str, retryable: bool = False) -> "ChatCompletionStreamEvent":
        """Factory: error event."""
        return cls(
            event_type="error",
            data={"message": message, "retryable": retryable},
        )
