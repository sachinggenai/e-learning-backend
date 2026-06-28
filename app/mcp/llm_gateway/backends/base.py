"""
Abstract LLM Backend — defines the interface all providers must implement.

Every LLMBackend converts between the canonical format (OpenAI Chat)
and the provider-specific API protocol. This ensures all backends
are interchangeable from the caller's perspective.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Dict, List, Optional

from app.services.ai.mcp_client.message import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionStreamEvent,
)
from app.services.ai.mcp_client.types import ProviderHealth


@dataclass
class BackendCapabilities:
    """What a backend supports."""
    streaming: bool = False
    tool_calling: bool = False
    structured_output: bool = False
    vision: bool = False
    max_context_tokens: int = 4096
    max_output_tokens: int = 4096


class LLMBackend(ABC):
    """Abstract interface for an LLM provider backend.

    Each backend translates between the canonical format and
    the provider-specific protocol. Subclasses only need to
    implement chat() and chat_stream(); the rest is optional
    with sensible defaults.
    """

    def __init__(self):
        self._capabilities = BackendCapabilities()

    # ── Identity ────────────────────────────────────────────

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique provider identifier: 'anthropic', 'openai', 'ollama', etc."""
        ...

    @property
    def supported_models(self) -> List[str]:
        """List of model IDs this backend can handle."""
        return []

    @property
    def capabilities(self) -> BackendCapabilities:
        """What this backend supports."""
        return self._capabilities

    @property
    def supports_tool_calling(self) -> bool:
        return self._capabilities.tool_calling

    @property
    def supports_streaming(self) -> bool:
        return self._capabilities.streaming

    # ── Core Methods ─────────────────────────────────────────

    @abstractmethod
    async def chat(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        """Send a non-streaming chat completion request.

        Args:
            request: Canonical chat request.

        Returns:
            Canonical chat response with content or tool calls.

        Raises:
            BackendError: On provider failure.
        """
        ...

    @abstractmethod
    async def chat_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[ChatCompletionStreamEvent]:
        """Send a streaming chat completion request.

        Yields canonical stream events (text_delta, tool_call_start,
        tool_call_delta, done, error) until the stream completes.
        """
        ...

    # ── Optional Methods ─────────────────────────────────────

    async def health(self) -> ProviderHealth:
        """Check if the backend is healthy.

        Default: attempt a minimal API call. Override for custom checks.
        """
        try:
            test_req = ChatCompletionRequest(
                model=self.supported_models[0] if self.supported_models else "default",
                messages=[],
                max_tokens=1,
            )
            # Some backends need at least one message
            from app.services.ai.mcp_client.message import ChatMessage
            test_req.messages = [ChatMessage.user("ping")]
            await self.chat(test_req)
            return ProviderHealth.HEALTHY
        except Exception:
            return ProviderHealth.DEGRADED

    def validate_request(self, request: ChatCompletionRequest) -> Optional[str]:
        """Validate a request before sending. Returns error message or None."""
        if not request.model:
            return "model is required"
        if not request.messages:
            return "at least one message is required"
        if request.max_tokens < 1:
            return "max_tokens must be >= 1"
        if not (0.0 <= request.temperature <= 2.0):
            return "temperature must be between 0.0 and 2.0"
        return None

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(provider={self.provider_name})"
