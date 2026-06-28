# MCP Architecture — Implementation Progress

> **Branch:** `AI-Architecture-update`  
> **Started:** 2026-06-29  
> **Architecture:** MCP (Model Context Protocol) — Provider-Agnostic LLM Gateway

---

## Phase Status Summary

| Phase | Description | Status | Files |
|-------|-------------|--------|-------|
| Phase 1 | Foundation — Canonical format, LLMBackend ABC, ProviderRegistry, Gateway Server | ✅ Complete | 12 new |
| Phase 2 | Integration — MCPClientManager, LLMGatewayClient, llm_client.py refactor | ✅ Complete | 5 new, 2 modified |
| Phase 3 | Provider Expansion — OllamaBackend (direct, no proxy) | ✅ Complete | 1 new, 4 modified |
| Phase 4 | Domain Tools via MCP | ⏳ Pending | — |
| Phase 5 | Cleanup — Deprecate proxy, embeddings, tool calling tests | ⏳ Pending | — |

---

## Phase 1-3: What Was Built

### New Files Created (18 files, ~3,500 lines)

```
app/services/ai/mcp_client/          # MCP Client Layer
├── __init__.py
├── types.py                         # DegradationTier, ProviderHealth, ProviderInfo
├── message.py                       # Canonical: ChatMessage, ChatCompletionRequest/Response
├── llm_gateway_client.py            # HTTP client for LLM Gateway
├── domain_tool_client.py            # HTTP client for domain tool servers
├── mcp_client_manager.py            # Singleton: lifecycle, heartbeat, degradation
├── tool_registry.py                 # Local cache of discovered MCP tools
└── degradation_manager.py           # Circuit breaker + 4-tier fallback

app/services/ai/adapters/            # Backward-compat adapters
├── __init__.py
└── llm_client_adapter.py            # LLMMessage ↔ Canonical converters

app/mcp/llm_gateway/                 # LLM Gateway MCP Server
├── __init__.py
├── server.py                        # FastAPI MCP server (port 8004)
├── provider_registry.py             # Dynamic provider register/unregister/resolve
├── config.py                        # Gateway configuration
└── backends/
    ├── __init__.py
    ├── base.py                      # LLMBackend ABC
    ├── mock_backend.py              # Deterministic mock
    ├── anthropic_backend.py         # Anthropic SDK → canonical
    └── ollama_backend.py            # Direct Ollama HTTP (replaces local_proxy.py)
```

### Files Modified

| File | Changes |
|------|---------|
| `app/services/ai/llm_client.py` | Added `_mcp_chat()`, `_mcp_stream()`, try-MCP-first pattern in `_anthropic_chat/_stream` |
| `app/main.py` | MCPClientManager start/stop in FastAPI lifespan |

---

## Current Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ FastAPI App (:8000)                                          │
│   LLMClient (public API: UNCHANGED)                          │
│     ├── Mock → in-process (UNCHANGED)                        │
│     └── Anthropic → try MCP first, fallback direct SDK       │
│           │                                                  │
│           ▼                                                  │
│   MCPClientManager → LLMGatewayClient                        │
│           │                                                  │
└───────────┼──────────────────────────────────────────────────┘
            │ HTTP
            ▼
┌──────────────────────────────────────────────────────────────┐
│ LLM Gateway MCP Server (:8004)                               │
│   ProviderRegistry                                           │
│     ├── OllamaBackend    → Ollama :11434  (direct, native)   │
│     ├── AnthropicBackend → local_proxy :4000 (fallback)      │
│     └── MockBackend      → deterministic                     │
└──────────────────────────────────────────────────────────────┘
```

---

## Task Status (Post-MCP Migration)

| # | Task | Status |
|---|------|--------|
| 1 | Verify Ollama running + models available | ✅ |
| 2 | Install LiteLLM and dependencies | ✅ |
| 3 | Create proxy config (now replaced by OllamaBackend) | ✅ (legacy) |
| 4 | Start proxy and verify translation (now replaced by Gateway) | ✅ (legacy) |
| 5 | MCP Integration: app via LLMGatewayClient → Gateway → Ollama | ✅ |
| 6 | Test embeddings (nomic-embed-text) and tool calling end-to-end | ⏳ Pending |
| 7 | Canonical message format types | ✅ |
| 8 | LLMBackend ABC + MockBackend + AnthropicBackend | ✅ |
| 9 | ProviderRegistry + Gateway config | ✅ |
| 10 | LLM Gateway MCP Server | ✅ |
| 11 | Verify Phase 1 — Gateway health, Mock + Anthropic chat | ✅ |
| 12 | MCPClientManager — connection lifecycle | ✅ |
| 13 | LLMGatewayClient — MCP client for Gateway | ✅ |
| 14 | DomainToolClient + DegradationManager | ✅ |
| 15 | LLMClientAdapter — backward-compat converters | ✅ |
| 16 | Refactor llm_client.py → MCP Gateway path | ✅ |
| 17 | MCPClientManager → FastAPI lifespan + verify | ✅ |
| 18 | OllamaBackend — direct Ollama HTTP | ✅ |
| 19 | Register OllamaBackend in Gateway + config | ✅ |
| 20 | Test OllamaBackend — PLANNER + GENERATOR + streaming | ✅ |

---

## What the Factory/Strategy Pattern Achieves

```python
# Adding a new LLM provider now requires ONLY:
# 1. Implement LLMBackend ABC
# 2. Register in server.py startup

class NewProviderBackend(LLMBackend):
    @property
    def provider_name(self) -> str:
        return "new_provider"
    
    @property
    def supported_models(self) -> List[str]:
        return ["model-a", "model-b"]
    
    async def chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        # Provider-specific API call → canonical format
        ...
    
    async def chat_stream(self, request: ChatCompletionRequest):
        # Provider-specific streaming → canonical events
        ...

# That's it — everything else (LLMClient, ChatOrchestrator, 
# CourseGenerator, tool calling) works automatically.
```

## Files Pending Deprecation

| File | Replacement |
|------|-------------|
| `local_proxy.py` | `OllamaBackend` in LLM Gateway |
| `start-litellm.ps1` | Gateway startup managed by MCPClientManager |

---

## Task 6 Verification (Completed)

| Test | Path | Result |
|------|------|--------|
| Embeddings (nomic-embed-text) | Ollama `/v1/embeddings` | ✅ 768-dim vectors returned |
| Embeddings (native) | Ollama `/api/embed` | ✅ 768-dim vectors returned |
| Tool calling — Gateway direct | curl → Gateway → OllamaBackend → qwen2.5:7b | ✅ Proper tool_call returned (list_pages) |
| Tool calling — LLMClient | LLMClient → MCP Gateway → OllamaBackend | ✅ ToolDef → Ollama function call → parsed back |
| Multiple tools | 2 tools sent, model selected correct one | ✅ |

### Code Cleanup Applied
- Fixed degradation tier logic — gateway healthy now reports FULL_MCP (not GATEWAY_DOWN)
- Gateway config default updated to include ollama
- OllamaBackend registration error handling improved

## Remaining Work

| Task | Phase | Description |
|------|-------|-------------|
| Deprecate proxy | 5 | Remove `local_proxy.py`, update start scripts |
| Phase 4 | 4 | Domain Tools MCP Server (port 8005) |
| Phase 4 | 4 | ChatOrchestrator → DomainToolClient integration |
| Production hardening | 5 | Config-driven provider selection, graceful startup ordering |
