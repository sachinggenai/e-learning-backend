"""
DEPRECATED — Replaced by OllamaBackend in LLM Gateway.

This proxy translated Anthropic Messages API → Ollama Chat API.
It is superseded by the MCP architecture:

  App → LLMClient → MCP Gateway (:8004) → OllamaBackend → Ollama (:11434)

The OllamaBackend in app/mcp/llm_gateway/backends/ollama_backend.py
speaks Ollama's native API directly — no translation proxy needed.

Kept for reference only. Do not use in production.
Last used: 2026-06-29 (Phase 1-2 of MCP migration)
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
import uvicorn

# ── Config ────────────────────────────────────────────────
OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
PROXY_PORT = int(os.getenv("PROXY_PORT", "4000"))

# Model mapping: Anthropic → Ollama model names
MODEL_MAP = {
    "deepseek-v4-pro[1m]": "qwen2.5:7b",
    "deepseek-v4-flash": "phi3:mini",
    "claude-sonnet-4-20250514": "qwen2.5:7b",
    "claude-haiku-4-20250514": "phi3:mini",
    "claude-opus-4-20250514": "qwen2.5:7b",
}

app = FastAPI(title="Local LLM Proxy", version="2.0.0")


# ── Helpers ────────────────────────────────────────────────


def map_model(anthropic_model: str) -> str:
    """Map Anthropic model name → Ollama model name."""
    return MODEL_MAP.get(anthropic_model, "qwen2.5:7b")


def convert_anthropic_to_ollama(
    messages: List[Dict[str, Any]],
    system_prompt: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Convert Anthropic Messages → Ollama Chat request body.

    Returns the full Ollama request dict (without stream/model/options).
    """
    ollama_messages: List[Dict[str, Any]] = []

    if system_prompt:
        ollama_messages.append({"role": "system", "content": system_prompt})

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if isinstance(content, list):
            text_parts: List[str] = []
            tool_calls: List[Dict[str, Any]] = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        tool_calls.append({
                            "id": block.get("id", ""),
                            "name": block.get("name", ""),
                            "input": block.get("input", {}),
                        })
                    elif block.get("type") == "tool_result":
                        text_parts.append(
                            f"[Tool Result id={block.get('tool_use_id', '')}: "
                            f"{json.dumps(block.get('content', ''))}]"
                        )
                elif isinstance(block, str):
                    text_parts.append(block)

            if tool_calls and not text_parts:
                # Assistant message with only tool calls — pass as text
                for tc in tool_calls:
                    text_parts.append(
                        f"[Tool Call: {tc['name']} "
                        f"args={json.dumps(tc['input'])}]"
                    )
            # Only add if there's content
            if text_parts:
                ollama_messages.append({
                    "role": role,
                    "content": "\n".join(text_parts),
                })
        else:
            ollama_messages.append({"role": role, "content": str(content)})

    # Convert tools to Ollama format
    ollama_tools = None
    if tools:
        ollama_tools = []
        for tool in tools:
            ollama_tools.append({
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {}),
                },
            })

    result: Dict[str, Any] = {"messages": ollama_messages}
    if ollama_tools:
        result["tools"] = ollama_tools
    return result


def ollama_to_anthropic_response(
    ollama_resp: Dict[str, Any],
    model_name: str,
) -> Dict[str, Any]:
    """Convert a completed Ollama response → Anthropic Messages format."""
    message = ollama_resp.get("message", {})
    content = message.get("content", "")
    tool_calls = message.get("tool_calls") or []

    anthropic_content: List[Dict[str, Any]] = []

    # Try to parse tool calls from the text content (Ollama often embeds them)
    if not tool_calls and ("<tool_call>" in content or '"name"' in content):
        try:
            # Attempt to extract JSON from the content
            import re
            json_match = re.search(r'\{[^{}]*"name"\s*:\s*"[^"]+"[^{}]*\}', content)
            if json_match:
                parsed = json.loads(json_match.group(0))
                if "name" in parsed:
                    tool_calls = [{
                        "function": {
                            "name": parsed.get("name", ""),
                            "arguments": parsed.get("arguments", parsed.get("input", parsed)),
                        }
                    }]
        except (json.JSONDecodeError, AttributeError):
            pass

    if tool_calls:
        for tc in tool_calls:
            func = tc.get("function", {})
            tool_id = tc.get("id", f"toolu_{uuid.uuid4().hex[:12]}")
            args = func.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (json.JSONDecodeError, TypeError):
                    args = {"raw": args}
            anthropic_content.append({
                "type": "tool_use",
                "id": tool_id,
                "name": func.get("name", ""),
                "input": args,
            })

    if content and not anthropic_content:
        anthropic_content.append({"type": "text", "text": content})
    elif content and anthropic_content:
        # Prepend text before tool calls
        anthropic_content.insert(0, {"type": "text", "text": content})

    if not anthropic_content:
        anthropic_content.append({"type": "text", "text": ""})

    usage = ollama_resp.get("eval_count", 0)
    prompt_tokens = ollama_resp.get("prompt_eval_count", 0)

    return {
        "id": f"msg_{uuid.uuid4().hex[:16]}",
        "type": "message",
        "role": "assistant",
        "content": anthropic_content,
        "model": model_name,
        "stop_reason": ollama_resp.get("done_reason", "end_turn"),
        "stop_sequence": None,
        "usage": {
            "input_tokens": prompt_tokens or 0,
            "output_tokens": usage or 0,
        },
    }


# ── SSE Streaming Helpers ──────────────────────────────────


def _build_sse_event(
    event_type: str,
    data: Dict[str, Any],
) -> str:
    """Build an Anthropic-format SSE event string."""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"


async def stream_anthropic_response(
    ollama_url: str,
    ollama_body: Dict[str, Any],
    model_name: str,
    request_model: str,
) -> AsyncIterator[str]:
    """Stream Ollama chat → Anthropic SSE events.

    Yields SSE event strings in correct Anthropic SDK order:
    message_start → content_block_start → delta* → content_block_stop
    → message_delta → message_stop
    """
    ollama_body["stream"] = True

    msg_id = f"msg_{uuid.uuid4().hex[:16]}"

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream(
                "POST",
                ollama_url,
                json=ollama_body,
            ) as response:
                response.raise_for_status()

                # 1. message_start — MUST come before any content_block events
                yield _build_sse_event("message_start", {
                    "message": {
                        "id": msg_id,
                        "type": "message",
                        "role": "assistant",
                        "content": [],
                        "model": request_model,
                    },
                })

                # 2. content_block_start for text
                yield _build_sse_event("content_block_start", {
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                })

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if chunk.get("done", False):
                        # 3. content_block_stop
                        yield _build_sse_event("content_block_stop", {"index": 0})

                        # 4. message_delta — Anthropic SDK expects both input/output tokens
                        eval_count = chunk.get("eval_count", 0)
                        prompt_count = chunk.get("prompt_eval_count", 0)
                        message_delta: Dict[str, Any] = {
                            "delta": {
                                "stop_reason": chunk.get("done_reason", "end_turn"),
                                "stop_sequence": None,
                            },
                            "usage": {
                                "input_tokens": prompt_count or 0,
                                "output_tokens": eval_count or 0,
                            },
                        }

                        yield _build_sse_event("message_delta", message_delta)

                        # 5. message_stop
                        yield _build_sse_event("message_stop", {})

                        break
                    else:
                        # Intermediate chunk — Ollama sends non-cumulative content
                        # Each chunk's content IS the delta
                        message = chunk.get("message", {})
                        delta_text = message.get("content", "")

                        if delta_text:
                            yield _build_sse_event("content_block_delta", {
                                "index": 0,
                                "delta": {
                                    "type": "text_delta",
                                    "text": delta_text,
                                },
                            })

    except httpx.HTTPStatusError as e:
        yield _build_sse_event("error", {
            "code": "OLLAMA_ERROR",
            "message": f"Ollama returned {e.response.status_code}: {e.response.text[:500]}",
        })
    except Exception as e:
        yield _build_sse_event("error", {
            "code": "PROXY_ERROR",
            "message": str(e),
        })


# ── Endpoints ───────────────────────────────────────────────


@app.post("/v1/messages")
async def chat_messages(request: Request):
    """Anthropic Messages API — non-streaming endpoint."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    model_name = map_model(body.get("model", "qwen2.5:7b"))
    messages = body.get("messages", [])
    system_prompt = body.get("system")
    max_tokens = body.get("max_tokens", 4096)
    temperature = body.get("temperature", 0.7)
    tools = body.get("tools")
    stream = body.get("stream", False)

    ollama_data = convert_anthropic_to_ollama(messages, system_prompt, tools)

    ollama_body: Dict[str, Any] = {
        "model": model_name,
        "messages": ollama_data["messages"],
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    if ollama_data.get("tools"):
        ollama_body["tools"] = ollama_data["tools"]

    # SSE streaming path
    if stream:
        ollama_body["stream"] = True
        return StreamingResponse(
            stream_anthropic_response(
                f"{OLLAMA_BASE}/api/chat",
                ollama_body,
                model_name,
                body.get("model", model_name),
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Non-streaming path
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{OLLAMA_BASE}/api/chat",
            json=ollama_body,
        )
        resp.raise_for_status()
        result = resp.json()

    return JSONResponse(
        content=ollama_to_anthropic_response(result, model_name)
    )


@app.get("/health")
async def health():
    """Health check — also verifies Ollama connectivity."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{OLLAMA_BASE}/api/version")
            ollama_version = r.json().get("version", "unknown")
    except Exception:
        ollama_version = "unreachable"
    return {
        "status": "ok",
        "ollama_base": OLLAMA_BASE,
        "ollama_version": ollama_version,
    }


# ── Entrypoint ──────────────────────────────────────────────

if __name__ == "__main__":
    print(f"Starting Local LLM Proxy on http://localhost:{PROXY_PORT}")
    print(f"   Ollama backend: {OLLAMA_BASE}")
    print(f"   Model mapping:")
    for ant, oll in MODEL_MAP.items():
        print(f"     {ant} -> {oll}")
    uvicorn.run(app, host="127.0.0.1", port=PROXY_PORT, log_level="info")
