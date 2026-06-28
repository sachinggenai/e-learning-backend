"""
Ollama LLM Backend — direct HTTP calls to Ollama Chat API.

Replaces local_proxy.py by speaking Ollama's native API directly.
No translation proxy needed — canonical format → Ollama /api/chat.

Supports:
- Non-streaming chat completion
- Streaming (SSE via newline-delimited JSON)
- Tool calling via Ollama's OpenAI-compatible function calling
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
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
from app.services.ai.mcp_client.types import ProviderHealth
from app.mcp.llm_gateway.backends.base import (
    LLMBackend,
    BackendCapabilities,
)

logger = logging.getLogger(__name__)

# Default Ollama endpoint
DEFAULT_OLLAMA_URL = "http://localhost:11434"

# Model tier affinity
PLANNER_MODELS = ["phi3:mini", "gemma2:2b", "llama3.2:3b"]
GENERATOR_MODELS = ["qwen2.5:7b", "llama3.1:8b", "mistral:7b", "qwen2.5:14b"]


class OllamaBackend(LLMBackend):
    """Ollama provider — direct HTTP to Ollama server.

    Speaks Ollama's native Chat API. No proxy, no SDK —
    just httpx + JSON.

    Usage:
        backend = OllamaBackend(base_url="http://localhost:11434")
        response = await backend.chat(request)
    """

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def supported_models(self) -> List[str]:
        """Ollama-native model names — no cloud aliases needed.

        The MCP Gateway's ProviderRegistry resolves model names
        to backends. OllamaBackend handles its native models.
        """
        return PLANNER_MODELS + GENERATOR_MODELS

    def __init__(
        self,
        base_url: str = "",
        chat_model: str = "",
        timeout: float = 120.0,
    ):
        super().__init__()
        self._capabilities = BackendCapabilities(
            streaming=True,
            tool_calling=True,
            structured_output=False,
            max_context_tokens=4096,
            max_output_tokens=4096,
        )
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_URL)).rstrip("/")
        self.chat_model = chat_model or os.getenv("OLLAMA_CHAT_MODEL", "qwen2.5:7b")
        self.timeout = timeout

        # Auto-detect available models on startup
        self._available_models: List[str] = []

    # ── Chat ─────────────────────────────────────────────────

    async def chat(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        """Send non-streaming chat to Ollama."""
        ollama_body = self._build_ollama_request(request, stream=False)

        start = time.time()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/api/chat",
                json=ollama_body,
            )
            resp.raise_for_status()
            data = resp.json()
        latency = (time.time() - start) * 1000

        return self._parse_ollama_response(data, request.model, latency)

    # ── Stream ───────────────────────────────────────────────

    async def chat_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[ChatCompletionStreamEvent]:
        """Stream chat from Ollama.

        Ollama streams newline-delimited JSON chunks:
        {"message": {"content": "Hi"}, "done": false}
        {"message": {"content": " there"}, "done": false}
        {"message": {}, "done": true, "eval_count": 10, ...}
        """
        ollama_body = self._build_ollama_request(request, stream=True)

        accumulated_content = ""
        tool_call_started = False

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/api/chat",
                    json=ollama_body,
                ) as response:
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        if chunk.get("done", False):
                            # Final chunk — emit remaining text then done
                            message = chunk.get("message", {})
                            final_content = message.get("content", "")

                            # Emit any remaining delta
                            if final_content and len(final_content) > len(accumulated_content):
                                delta = final_content[len(accumulated_content):]
                                yield ChatCompletionStreamEvent.text_delta(text=delta)

                            # Yield complete
                            eval_count = chunk.get("eval_count", 0)
                            prompt_count = chunk.get("prompt_eval_count", 0)
                            yield ChatCompletionStreamEvent.done(
                                usage=Usage(
                                    prompt_tokens=prompt_count or 0,
                                    completion_tokens=eval_count or 0,
                                    total_tokens=(prompt_count or 0) + (eval_count or 0),
                                ),
                                model=request.model,
                            )
                            break

                        else:
                            # Intermediate chunk
                            message = chunk.get("message", {})
                            delta_text = message.get("content", "")

                            if delta_text:
                                new_text = delta_text[len(accumulated_content):]
                                if new_text:
                                    yield ChatCompletionStreamEvent.text_delta(text=new_text)
                                accumulated_content = delta_text

                            # Check for tool calls in intermediate chunks
                            tool_calls = message.get("tool_calls")
                            if tool_calls and not tool_call_started:
                                tool_call_started = True
                                for tc in tool_calls:
                                    func = tc.get("function", {})
                                    yield ChatCompletionStreamEvent.tool_call_start(
                                        tool_name=func.get("name", ""),
                                        tool_id=tc.get("id", ""),
                                    )
                                    yield ChatCompletionStreamEvent.tool_call_delta(
                                        partial_json=json.dumps(func.get("arguments", {}))
                                    )

        except httpx.HTTPStatusError as e:
            yield ChatCompletionStreamEvent.error(
                f"Ollama HTTP {e.response.status_code}: {e.response.text[:300]}",
                retryable=e.response.status_code >= 500,
            )
        except httpx.RequestError as e:
            yield ChatCompletionStreamEvent.error(
                f"Ollama unreachable: {e}", retryable=True
            )
        except Exception as e:
            yield ChatCompletionStreamEvent.error(
                str(e)[:300], retryable=False
            )

    # ── Health ───────────────────────────────────────────────

    async def health(self) -> ProviderHealth:
        """Check if Ollama is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/version")
                if resp.status_code == 200:
                    data = resp.json()
                    logger.debug("Ollama healthy: version %s", data.get("version"))
                    return ProviderHealth.HEALTHY
        except Exception:
            pass
        return ProviderHealth.UNHEALTHY

    async def refresh_models(self) -> List[str]:
        """Query Ollama for installed models."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    self._available_models = [
                        m.get("name", "") for m in data.get("models", [])
                    ]
                    return self._available_models
        except Exception:
            pass
        return self._available_models

    # ── Helpers ──────────────────────────────────────────────

    def _build_ollama_request(
        self, request: ChatCompletionRequest, stream: bool = False
    ) -> Dict[str, Any]:
        """Build Ollama Chat API request body from canonical format."""
        ollama_messages = []
        for msg in request.messages:
            ollama_msg: Dict[str, Any] = {"role": msg.role}

            # Handle content
            if msg.content is not None:
                ollama_msg["content"] = msg.content
            elif msg.tool_calls:
                # Assistant message with only tool calls
                ollama_msg["content"] = ""
                # Actually, Ollama expects tool_calls in the message directly
                # We'll handle this below

            # Handle tool calls in assistant messages
            if msg.tool_calls:
                ollama_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": tc.function,
                    }
                    for tc in msg.tool_calls
                ]

            # Handle tool result messages
            if msg.tool_call_id:
                ollama_msg["tool_call_id"] = msg.tool_call_id

            ollama_messages.append(ollama_msg)

        body: Dict[str, Any] = {
            "model": self._resolve_model(request.model),
            "messages": ollama_messages,
            "stream": stream,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            },
        }

        # Add tools if provided
        if request.tools:
            body["tools"] = request.tools
            if request.tool_choice:
                body["tool_choice"] = request.tool_choice

        return body

    def _resolve_model(self, requested: str) -> str:
        """Resolve a model name to an available Ollama model.

        If the requested model is not directly available, maps
        tier-conventional names to installed models.
        """
        # Direct match
        if not self._available_models:
            return requested

        if requested in self._available_models:
            return requested

        # Map Anthropic/cloud names to Ollama models
        mapping = {
            "deepseek-v4-pro[1m]": "qwen2.5:7b",
            "deepseek-v4-flash": "phi3:mini",
            "claude-sonnet-4-20250514": "qwen2.5:7b",
            "claude-haiku-4-20250514": "phi3:mini",
            "claude-opus-4-20250514": "qwen2.5:7b",
        }

        mapped = mapping.get(requested)
        if mapped and mapped in self._available_models:
            return mapped

        # Fall back to available models by tier
        for model in self._available_models:
            if "qwen" in model or "7b" in model:
                return model

        return self._available_models[0] if self._available_models else requested

    def _parse_ollama_response(
        self, data: Dict[str, Any], model: str, latency_ms: float
    ) -> ChatCompletionResponse:
        """Parse Ollama response → canonical format."""
        message = data.get("message", {})
        content = message.get("content", "")
        tool_calls_raw = message.get("tool_calls") or []

        # Convert tool calls to canonical format
        tool_calls = []
        for tc in tool_calls_raw:
            func = tc.get("function", {})
            args = func.get("arguments", {})
            if isinstance(args, dict):
                args = json.dumps(args)
            tool_calls.append(
                ToolCall(
                    id=tc.get("id", f"call_{uuid.uuid4().hex[:8]}"),
                    type="function",
                    function={
                        "name": func.get("name", ""),
                        "arguments": args,
                    },
                )
            )

        if tool_calls:
            resp = ChatCompletionResponse.from_tool_calls(
                tool_calls=tool_calls,
                model=model,
                provider="ollama",
            )
        else:
            resp = ChatCompletionResponse.from_content(
                content=content or "[no content]",
                model=model,
                provider="ollama",
            )

        # Add usage
        eval_count = data.get("eval_count", 0)
        prompt_count = data.get("prompt_eval_count", 0)
        resp.usage = Usage(
            prompt_tokens=prompt_count or 0,
            completion_tokens=eval_count or 0,
            total_tokens=(prompt_count or 0) + (eval_count or 0),
        )
        resp.latency_ms = latency_ms
        return resp
