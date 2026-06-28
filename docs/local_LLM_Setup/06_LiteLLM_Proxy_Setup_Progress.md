# LiteLLM Proxy Setup — Progress Report

> **Date:** 2026-06-29  
> **Branch:** `AI-Architecture-update`  
> **Previous Session:** `4e57945e-afb6-4041-b193-014cc7a448a4` (Jun 28–29)

---

## Task Status Overview

| # | Task | Status | Why It's Necessary |
|---|------|--------|--------------------|
| 1 | Verify Ollama is running and models available | ✅ Completed | Without Ollama running + models loaded, the local LLM stack has no inference engine. Models (qwen2.5:7b, phi3:mini, nomic-embed-text) must be present and the server listening on `:11434`. |
| 2 | Install LiteLLM and dependencies | ✅ Completed | The proxy needs libraries to translate API formats. `litellm` 1.49.7, `openai` 2.44.0, `httpx`, `fastapi`, `uvicorn` are all required for the translation layer. |
| 3 | Create and verify LiteLLM proxy config | ✅ Completed | `D:\litellm_config.yaml` maps Anthropic model names → Ollama models (e.g., `deepseek-v4-pro[1m]` → `ollama/qwen2.5:7b`). Without this, the proxy doesn't know which local model to route to. |
| 4 | Start proxy and verify Anthropic API translation | ✅ Completed | The proxy must translate Anthropic Messages API (`/v1/messages`) → Ollama Chat API (`/api/chat`) and back. Both non-streaming and SSE streaming verified working for GENERATOR and PLANNER tiers. |
| 5 | Update .env for local LLM and test app integration | ⏳ Pending | The `.env` is already configured (`ANTHROPIC_BASE_URL=http://localhost:4000`), but the **end-to-end app → proxy → Ollama** flow hasn't been tested yet. The FastAPI app needs to be started and a real `/api/v1/chat` request sent through. |
| 6 | Test embeddings and tool calling end-to-end | ⏳ Pending | Embeddings (`nomic-embed-text` via Ollama's `/v1/embeddings`) and tool calling (Anthropic `tools[]` → Ollama `functions[]`) are critical for the AI authoring features. Neither has been verified through the full stack yet. |

---

## Why Each Task Matters

### Task 1: Verify Ollama (✅)
**Dependency for everything else.** Ollama is the local inference engine. If it's not running or models aren't loaded, every downstream step fails. This task confirmed:
- Ollama v0.30.11 listening on `localhost:11434`
- GPU detected: RTX 2060, 6 GB VRAM, CUDA 13.0
- 3 models present: qwen2.5:7b (4.7 GB), phi3:mini (2.2 GB), nomic-embed-text (274 MB)

### Task 2: Install Dependencies (✅)
**The proxy layer requires specific packages.** Two approaches were prepared:
- **LiteLLM** (`litellm[proxy]`): Industry-standard LLM proxy with built-in Anthropic → OpenAI translation
- **local_proxy.py**: Custom lightweight proxy (FastAPI + httpx) with full control over translation

Both are available; `local_proxy.py` was chosen because it handles Anthropic SSE streaming events more precisely.

### Task 3: Proxy Config (✅)
**Model mapping is the core routing logic.** The app sends Anthropic model names (`deepseek-v4-pro[1m]`, `deepseek-v4-flash`) but Ollama only knows its own model names. The config maps:
- `deepseek-v4-pro[1m]` → `qwen2.5:7b` (GENERATOR — 7B params, content creation)
- `deepseek-v4-flash` → `phi3:mini` (PLANNER — 3.8B params, fast classification)
- Claude model aliases also mapped for compatibility

### Task 4: Proxy Verification (✅)
**Proves the translation layer works.** Tested 3 endpoints:
| Test | Endpoint | Model | Result |
|------|----------|-------|--------|
| Health | `GET /health` | — | ✅ Ollama v0.30.11 reachable |
| Non-streaming | `POST /v1/messages` | GENERATOR (qwen2.5:7b) | ✅ Full response returned |
| Non-streaming | `POST /v1/messages` | PLANNER (phi3:mini) | ✅ Classification returned |
| SSE Streaming | `POST /v1/messages` (stream:true) | GENERATOR | ✅ SSE events in Anthropic format |

### Task 5: App Integration (⏳)
**The real test.** The proxy works in isolation, but the FastAPI app uses the `anthropic` Python SDK which has its own expectations about response format, error handling, and streaming event types. The app must:
1. Start successfully with `ANTHROPIC_BASE_URL=http://localhost:4000`
2. Accept a chat request at `POST /api/v1/chat`
3. Route through `ChatOrchestrator` → `LLMClient` → Anthropic SDK → proxy → Ollama
4. Return a valid AI response to the client

**Potential issues:** Database must be running (Docker), the app imports many modules that may have side effects, and the Anthropic SDK may send headers/parameters the proxy doesn't handle.

### Task 6: Embeddings & Tool Calling (⏳)
**Critical for AI authoring features.** The e-learning backend uses:
- **Embeddings** for RAG similarity search (course content retrieval). The `.env` already points `EMBEDDING_PROVIDER=openai` with `OPENAI_BASE_URL=http://localhost:11434/v1` (direct to Ollama, bypassing the proxy).
- **Tool calling** for the AI to interact with the course editor (create pages, modify content, etc.). Tools are defined in Anthropic format, converted to Ollama `functions[]` format by the proxy, and the response must be parsed back.

---

## Architecture (What's Been Built)

```
┌──────────────────────────────────────────────────┐
│ E-Learning Backend (FastAPI :8000)                │
│   ANTHROPIC_BASE_URL=http://localhost:4000        │
│   anthropic.AsyncAnthropic SDK                    │
│   app/services/ai/llm_client.py                   │
│   app/services/ai/chat_orchestrator.py            │
└────────────────┬─────────────────────────────────┘
                 │ Anthropic Messages API
                 │ POST /v1/messages
                 │ SSE streaming (stream:true)
                 ▼
┌──────────────────────────────────────────────────┐
│ local_proxy.py (FastAPI :4000)                    │
│   Model mapping: Anthropic names → Ollama names   │
│   Format translation: Messages API → Ollama Chat  │
│   Tool schema conversion                          │
│   SSE event translation                           │
└────────────────┬─────────────────────────────────┘
                 │ Ollama Chat API
                 │ POST /api/chat
                 ▼
┌──────────────────────────────────────────────────┐
│ Ollama Server (localhost:11434)                   │
│   GPU: RTX 2060 (6 GB VRAM)                       │
│   qwen2.5:7b  — GENERATOR (4.7 GB)               │
│   phi3:mini   — PLANNER  (2.2 GB)                 │
│   nomic-embed-text — Embeddings (274 MB, CPU)     │
└──────────────────────────────────────────────────┘

Embeddings path (bypasses proxy):
  App → OPENAI_BASE_URL=http://localhost:11434/v1 → Ollama /v1/embeddings
```

---

## Next Steps

1. **Start Docker + App** — Bring up the full stack and test `POST /api/v1/chat`
2. **Test embeddings** — Verify `nomic-embed-text` via Ollama's OpenAI-compatible `/v1/embeddings`
3. **Test tool calling** — Send a request with `tools[]` and verify Ollama returns tool calls the proxy translates correctly
4. **Update start scripts** — Modify `start-litellm.ps1` or create `start-local-proxy.ps1` to launch the proxy as part of the normal dev workflow
5. **Performance benchmarking** — Measure latency and tokens/sec for GENERATOR vs PLANNER
