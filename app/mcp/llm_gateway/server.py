"""
LLM Gateway MCP Server — Phase 1.

Standalone FastAPI app that provides provider-agnostic LLM access
via MCP protocol. Discovers registered backends and routes requests.

Deploy: PYTHONPATH=. uvicorn app.mcp.llm_gateway.server:app --port 8004
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

from app.services.ai.mcp_client.message import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionStreamEvent,
    ChatMessage,
    ToolCall,
    Usage,
)
from app.services.ai.mcp_client.types import ProviderInfo, ProviderHealth
from app.mcp.llm_gateway.backends.base import LLMBackend
from app.mcp.llm_gateway.backends.mock_backend import MockBackend
from app.mcp.llm_gateway.backends.anthropic_backend import AnthropicBackend
from app.mcp.llm_gateway.backends.ollama_backend import OllamaBackend
from app.mcp.llm_gateway.provider_registry import ProviderRegistry
from app.mcp.llm_gateway.config import load_gateway_config

logger = logging.getLogger("llm-gateway-mcp")

# ── App ─────────────────────────────────────────────────────────

app = FastAPI(title="llm-gateway-mcp", version="1.0.0")

# Global registry — initialized at startup
_registry: ProviderRegistry = ProviderRegistry()
_gateway_config = load_gateway_config()


def _init_registry():
    """Initialize the provider registry from configuration."""
    global _registry
    enabled = {
        p.strip()
        for p in _gateway_config.enabled_providers.split(",")
        if p.strip()
    }

    if "mock" in enabled or "all" in enabled:
        _registry.register(MockBackend())
        logger.info("Registered MockBackend")

    if "anthropic" in enabled or "all" in enabled:
        backend = AnthropicBackend(
            api_key=_gateway_config.anthropic_api_key or None,
            base_url=_gateway_config.anthropic_base_url or None,
        )
        _registry.register(backend)
        logger.info(
            "Registered AnthropicBackend (base_url=%s)",
            _gateway_config.anthropic_base_url or "default",
        )

    if "ollama" in enabled or "all" in enabled:
        try:
            ollama = OllamaBackend(
                base_url=_gateway_config.ollama_base_url or "http://localhost:11434",
            )
            _registry.register(ollama)
            logger.info("Registered OllamaBackend (base_url=%s, models=%s)",
                        ollama.base_url, ollama.supported_models)
        except Exception:
            logger.exception("Failed to register OllamaBackend")

    logger.info(
        "Provider registry initialized with %d backends: %s",
        len(_registry.list_backends()),
        list(_registry.list_models().keys()),
    )


# ── MCP Protocol Schemas ──────────────────────────────────────────


class ToolDef(BaseModel):
    name: str
    description: str
    inputSchema: Dict[str, Any] = Field(default_factory=dict)


class ToolCallRequest(BaseModel):
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class ToolCallResponse(BaseModel):
    content: List[Dict[str, Any]] = Field(default_factory=list)
    isError: bool = False


class ProviderInfoResponse(BaseModel):
    name: str
    supported_models: List[str] = Field(default_factory=list)
    supports_tool_calling: bool = False
    supports_streaming: bool = False
    health: str = "unknown"


# ── SSE Helpers ───────────────────────────────────────────────────


def _sse_event(event_type: str, data: Dict[str, Any]) -> str:
    """Build an SSE event string."""
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_tool_response(
    request: ChatCompletionRequest,
) -> AsyncIterator[str]:
    """Stream a chat completion via SSE."""
    provider_name, backend = _registry.resolve_model(
        request.model,
        preferred_provider=_gateway_config.default_provider,
    )
    if not backend:
        yield _sse_event("error", {
            "code": "NO_PROVIDER",
            "message": f"No backend found for model '{request.model}'",
        })
        return

    try:
        async for event in backend.chat_stream(request):
            yield _sse_event(event.event_type, event.data)
    except Exception as e:
        yield _sse_event("error", {
            "code": "STREAM_ERROR",
            "message": str(e),
        })


# ── MCP Endpoints ─────────────────────────────────────────────────


@app.get("/health")
async def health():
    """Health check with provider status."""
    provider_status = {}
    for info in _registry.list_provider_infos():
        provider_status[info.name] = {
            "health": info.health.value,
            "models": info.supported_models,
        }

    return {
        "status": "ok",
        "server": "llm-gateway-mcp",
        "version": "1.0.0",
        "providers": provider_status,
    }


@app.get("/tools/list")
async def list_tools():
    """List available MCP tools."""
    tools = [
        ToolDef(
            name="chat_completion",
            description="Send a chat completion request to an LLM provider. "
            "Returns a response with text content or tool calls.",
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "Model ID to use",
                    },
                    "messages": {
                        "type": "array",
                        "description": "Conversation messages in OpenAI format",
                    },
                    "tools": {
                        "type": "array",
                        "description": "Available tool definitions",
                    },
                    "max_tokens": {
                        "type": "integer",
                        "description": "Maximum tokens in the response",
                        "default": 4096,
                    },
                    "temperature": {
                        "type": "number",
                        "description": "Sampling temperature (0.0-2.0)",
                        "default": 0.7,
                    },
                    "stream": {
                        "type": "boolean",
                        "description": "Whether to stream the response",
                        "default": False,
                    },
                },
                "required": ["model", "messages"],
            },
        ),
        ToolDef(
            name="stream_completion",
            description="Stream a chat completion request via SSE. "
            "Returns real-time token-by-token events.",
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {"type": "string"},
                    "messages": {"type": "array"},
                    "tools": {"type": "array"},
                    "max_tokens": {"type": "integer", "default": 4096},
                    "temperature": {"type": "number", "default": 0.7},
                },
                "required": ["model", "messages"],
            },
        ),
        ToolDef(
            name="list_providers",
            description="List all registered LLM providers and their models.",
            inputSchema={"type": "object", "properties": {}},
        ),
        ToolDef(
            name="register_provider",
            description="Register a new LLM provider backend at runtime.",
            inputSchema={
                "type": "object",
                "properties": {
                    "provider_name": {"type": "string"},
                    "provider_type": {"type": "string"},
                    "config": {"type": "object"},
                },
            },
        ),
    ]
    return {"tools": [t.model_dump() for t in tools]}


@app.post("/tools/call")
async def call_tool(body: ToolCallRequest):
    """Execute an MCP tool call."""
    tool_name = body.name
    args = body.arguments

    if tool_name == "chat_completion":
        return await _handle_chat_completion(args)

    if tool_name == "stream_completion":
        return await _handle_stream_completion(args)

    if tool_name == "list_providers":
        return await _handle_list_providers()

    if tool_name == "register_provider":
        return await _handle_register_provider(args)

    raise HTTPException(
        status_code=404,
        detail=f"Unknown tool: {tool_name}",
    )


# ── Tool Handlers ─────────────────────────────────────────────────


async def _handle_chat_completion(args: Dict[str, Any]) -> ToolCallResponse:
    """Execute chat_completion tool."""
    try:
        # Build canonical request
        messages = [
            ChatMessage(
                role=m.get("role", "user"),
                content=m.get("content"),
                name=m.get("name"),
                tool_call_id=m.get("tool_call_id"),
                tool_calls=(
                    [
                        ToolCall(
                            id=tc.get("id", ""),
                            type=tc.get("type", "function"),
                            function=tc.get("function", {}),
                        )
                        for tc in m.get("tool_calls", [])
                    ]
                    if m.get("tool_calls")
                    else None
                ),
            )
            for m in args.get("messages", [])
        ]

        request = ChatCompletionRequest(
            model=args.get("model", ""),
            messages=messages,
            tools=args.get("tools"),
            tool_choice=args.get("tool_choice"),
            max_tokens=args.get("max_tokens", 4096),
            temperature=args.get("temperature", 0.7),
            stream=False,
        )

        # Resolve backend
        provider_name, backend = _registry.resolve_model(
            request.model,
            preferred_provider=_gateway_config.default_provider,
        )
        if not backend:
            return ToolCallResponse(
                content=[
                    {"type": "text", "text": f"No backend for model '{request.model}'"}
                ],
                isError=True,
            )

        # Call backend
        response = await backend.chat(request)

        # Update health
        _registry.update_health(backend.provider_name, ProviderHealth.HEALTHY)

        # Build response content
        result = {
            "id": response.id,
            "model": response.model,
            "provider": response.provider,
            "choices": [
                {
                    "index": c.index,
                    "message": c.message.to_dict() if c.message else None,
                    "finish_reason": c.finish_reason,
                }
                for c in response.choices
            ],
        }
        if response.usage:
            result["usage"] = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return ToolCallResponse(content=[{"type": "text", "text": json.dumps(result)}])

    except Exception as e:
        logger.exception("chat_completion failed")
        return ToolCallResponse(
            content=[{"type": "text", "text": f"Error: {e}"}],
            isError=True,
        )


async def _handle_stream_completion(args: Dict[str, Any]) -> StreamingResponse:
    """Stream a chat completion via SSE."""
    messages = [
        ChatMessage(
            role=m.get("role", "user"),
            content=m.get("content"),
        )
        for m in args.get("messages", [])
    ]

    request = ChatCompletionRequest(
        model=args.get("model", ""),
        messages=messages,
        tools=args.get("tools"),
        max_tokens=args.get("max_tokens", 4096),
        temperature=args.get("temperature", 0.7),
        stream=True,
    )

    return StreamingResponse(
        _stream_tool_response(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


async def _handle_list_providers() -> ToolCallResponse:
    """List all registered providers."""
    infos = _registry.list_provider_infos()
    result = [
        {
            "name": info.name,
            "supported_models": info.supported_models,
            "supports_tool_calling": info.supports_tool_calling,
            "supports_streaming": info.supports_streaming,
            "health": info.health.value,
            "tier_affinity": info.tier_affinity,
        }
        for info in infos
    ]
    return ToolCallResponse(
        content=[{"type": "text", "text": json.dumps(result, indent=2)}]
    )


async def _handle_register_provider(args: Dict[str, Any]) -> ToolCallResponse:
    """Register a new provider at runtime."""
    provider_type = args.get("provider_type", "")
    provider_name = args.get("provider_name", provider_type)
    config = args.get("config", {})

    if provider_type == "anthropic":
        backend = AnthropicBackend(
            api_key=config.get("api_key", ""),
            base_url=config.get("base_url", ""),
        )
    elif provider_type == "mock":
        backend = MockBackend()
    elif provider_type == "ollama":
        backend = OllamaBackend(
            base_url=config.get("base_url", "http://localhost:11434"),
            chat_model=config.get("chat_model", "qwen2.5:7b"),
        )
    else:
        return ToolCallResponse(
            content=[{
                "type": "text",
                "text": f"Unknown provider type: {provider_type}. Supported: anthropic, mock, ollama",
            }],
            isError=True,
        )

    _registry.register(backend)
    return ToolCallResponse(
        content=[{
            "type": "text",
            "text": f"Provider '{provider_name}' registered successfully with {len(backend.supported_models)} models",
        }]
    )


# ── Direct API Endpoints (non-MCP, for convenience) ───────────────


@app.post("/v1/chat/completions")
async def openai_chat_completions(request: Request):
    """OpenAI-compatible endpoint for direct integration."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    try:
        # Parse as canonical request
        messages = [
            ChatMessage(
                role=m.get("role", "user"),
                content=m.get("content"),
                name=m.get("name"),
                tool_call_id=m.get("tool_call_id"),
                tool_calls=(
                    [
                        ToolCall(
                            id=tc.get("id", ""),
                            function=tc.get("function", {}),
                        )
                        for tc in m.get("tool_calls", [])
                    ]
                    if m.get("tool_calls")
                    else None
                ),
            )
            for m in body.get("messages", [])
        ]

        request_obj = ChatCompletionRequest(
            model=body.get("model", ""),
            messages=messages,
            tools=body.get("tools"),
            tool_choice=body.get("tool_choice"),
            max_tokens=body.get("max_tokens", 4096),
            temperature=body.get("temperature", 0.7),
            top_p=body.get("top_p", 1.0),
            stream=body.get("stream", False),
            stop=body.get("stop"),
        )

        # Handle streaming
        if request_obj.stream:
            return StreamingResponse(
                _stream_tool_response(request_obj),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
            )

        # Non-streaming
        provider_name, backend = _registry.resolve_model(
            request_obj.model,
            preferred_provider=_gateway_config.default_provider,
        )
        if not backend:
            raise HTTPException(
                status_code=503,
                detail=f"No backend for model '{request_obj.model}'",
            )

        response = await backend.chat(request_obj)
        _registry.update_health(backend.provider_name, ProviderHealth.HEALTHY)

        result = {
            "id": response.id,
            "object": "chat.completion",
            "created": response.created,
            "model": response.model,
            "choices": [
                {
                    "index": c.index,
                    "message": c.message.to_dict() if c.message else None,
                    "finish_reason": c.finish_reason,
                }
                for c in response.choices
            ],
        }
        if response.usage:
            result["usage"] = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return JSONResponse(content=result)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("chat/completions failed")
        raise HTTPException(status_code=500, detail=str(e))


# ── Startup ──────────────────────────────────────────────────────


@app.on_event("startup")
async def startup_event():
    """Initialize provider registry on startup."""
    _init_registry()
    # Check health of all backends
    await _registry.check_all_health_async()
    logger.info("LLM Gateway MCP Server ready on port %d", _gateway_config.port)


# ── Main entrypoint ──────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    _init_registry()
    uvicorn.run(
        app,
        host=_gateway_config.host,
        port=_gateway_config.port,
        log_level=_gateway_config.log_level,
    )
