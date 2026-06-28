"""
Mock LLM Backend — deterministic responses for testing and fallback.

Returns predictable responses based on the last user message content.
Zero network calls, zero tokens spent, zero latency.
"""

from __future__ import annotations

from typing import AsyncIterator, List

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


class MockBackend(LLMBackend):
    """Deterministic mock backend — always available, always fast.

    Returns responses based on keyword matching against the last
    user message. Used for testing and as the ultimate fallback
    (Degradation Tier 3).
    """

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def supported_models(self) -> List[str]:
        return ["mock", "mock-planner", "mock-generator"]

    def __init__(self):
        super().__init__()
        self._capabilities = BackendCapabilities(
            streaming=True,
            tool_calling=True,
            structured_output=True,
            max_context_tokens=8192,
            max_output_tokens=4096,
        )

    # ── Chat ─────────────────────────────────────────────────

    async def chat(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        """Return a deterministic mock response."""
        last_user_msg = self._last_user_content(request)
        tool_calls = self._detect_tool_calls(last_user_msg)

        if tool_calls:
            return ChatCompletionResponse.from_tool_calls(
                tool_calls=tool_calls,
                model=request.model,
                provider="mock",
            )

        content = self._generate_mock_content(last_user_msg, request)
        return ChatCompletionResponse(
            model=request.model,
            provider="mock",
            choices=[
                Choice(
                    index=0,
                    message=ChatMessage.assistant(content=content),
                    finish_reason="stop",
                )
            ],
            usage=Usage(
                prompt_tokens=len(last_user_msg.split()),
                completion_tokens=30,
                total_tokens=len(last_user_msg.split()) + 30,
            ),
            latency_ms=0.5,
        )

    # ── Stream ───────────────────────────────────────────────

    async def chat_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[ChatCompletionStreamEvent]:
        """Simulate streaming by yielding the mock response in chunks."""
        last_user_msg = self._last_user_content(request)

        tool_calls = self._detect_tool_calls(last_user_msg)
        if tool_calls:
            for tc in tool_calls:
                yield ChatCompletionStreamEvent.tool_call_start(
                    tool_name=tc.function.get("name", ""),
                    tool_id=tc.id,
                )
                import json
                yield ChatCompletionStreamEvent.tool_call_delta(
                    partial_json=json.dumps(tc.function.get("arguments", {}))
                )
            yield ChatCompletionStreamEvent.done(
                usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                model=request.model,
            )
            return

        content = self._generate_mock_content(last_user_msg, request)
        words = content.split()
        for i, word in enumerate(words):
            chunk = word + (" " if i < len(words) - 1 else "")
            yield ChatCompletionStreamEvent.text_delta(text=chunk)

        yield ChatCompletionStreamEvent.done(
            usage=Usage(
                prompt_tokens=len(last_user_msg.split()),
                completion_tokens=30,
                total_tokens=len(last_user_msg.split()) + 30,
            ),
            model=request.model,
        )

    # ── Health ───────────────────────────────────────────────

    async def health(self) -> ProviderHealth:
        """Mock is always healthy."""
        return ProviderHealth.HEALTHY

    # ── Helpers ──────────────────────────────────────────────

    def _last_user_content(self, request: ChatCompletionRequest) -> str:
        """Extract the last user message."""
        for msg in reversed(request.messages):
            if msg.role == "user" and msg.content:
                return msg.content
        return ""

    def _detect_tool_calls(self, content: str) -> List[ToolCall]:
        """Detect if the message should trigger mock tool calls."""
        lower = content.lower()
        tool_patterns = {
            "list pages": {
                "name": "list_pages",
                "arguments": {"session_id": "mock-session"},
            },
            "fetch page": {
                "name": "fetch_page",
                "arguments": {"session_id": "mock-session", "page_id": "page-1"},
            },
            "create page": {
                "name": "propose_create_page",
                "arguments": {
                    "session_id": "mock-session",
                    "title": "New Page",
                    "template_type": "text-content",
                },
            },
            "update page": {
                "name": "propose_update_page",
                "arguments": {
                    "session_id": "mock-session",
                    "page_id": "page-1",
                },
            },
            "delete page": {
                "name": "propose_delete_page",
                "arguments": {
                    "session_id": "mock-session",
                    "page_id": "page-1",
                },
            },
            "validate": {
                "name": "validate_course",
                "arguments": {"session_id": "mock-session", "scope": "full"},
            },
            "similar": {
                "name": "query_similar_courses",
                "arguments": {"session_id": "mock-session", "query": content},
            },
        }

        for pattern, func in tool_patterns.items():
            if pattern in lower:
                return [
                    ToolCall(
                        id=f"mock_call_{func['name']}",
                        type="function",
                        function={
                            "name": func["name"],
                            "arguments": str(func["arguments"]),
                        },
                    )
                ]
        return []

    def _generate_mock_content(
        self, content: str, request: ChatCompletionRequest
    ) -> str:
        """Generate a deterministic mock response."""
        if not content:
            return "[Mock LLM] I received an empty message. How can I help?"

        lower = content.lower()
        if any(w in lower for w in ("hello", "hi", "hey", "help")):
            return (
                "[Mock LLM] Hello! I'm your AI course authoring assistant. "
                "I can help you list pages, create content, validate courses, "
                "search for similar courses, and manage proposals."
            )
        if "course" in lower:
            return (
                "[Mock LLM] I can help with course authoring! You can ask me "
                "to list pages, create new pages, update existing content, "
                "validate your course structure, or search for similar courses."
            )
        if any(w in lower for w in ("generate", "create", "design")):
            return (
                "[Mock LLM] To create a new page, I'll need a title and a "
                "template type (text-content, tabs, accordion, click-reveal, "
                "or final-assessment). I'll then generate content and create "
                "a proposal for your review."
            )

        return (
            f'[Mock LLM] I received your message: "{content[:200]}". '
            "Available tools: list_pages, fetch_page, query_similar_courses, "
            "propose_create_page, propose_update_page, propose_delete_page, "
            "validate_course. How can I assist with your course?"
        )
