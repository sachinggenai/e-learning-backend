# US-BKND-AI-023: AI Chat Endpoint and LLM Interaction Loop

**Status:** ✅ COMPLETE
**Priority:** MUST
**Sprint:** 5
**Implemented:** 2026-06-15

## Summary

Full LLM interaction loop for the AI chat endpoint. Provides Anthropic API integration with native tool-calling, a mock provider for testing, system prompt construction with course context, streaming SSE support, multi-turn conversation management, and token usage tracking.

## Files Created/Modified

| File | Action | Description |
|---|---|---|
| `app/services/ai/llm_client.py` | NEW | LLM provider abstraction: Anthropic (streaming + non-streaming) and Mock providers. Message conversion, retry logic, error classification. |
| `app/services/ai/chat_orchestrator.py` | MODIFIED | Added `run_llm_loop()`, `_build_system_prompt()`, `_load_course_context()`, `_build_tool_definitions()`. Existing mock mode preserved. |
| `app/routers/ai_chat.py` | MODIFIED | Added `POST /chat/stream` SSE endpoint, `_validate_chat_session` helper, stream field in ChatRequest, token usage + latency in response. |
| `tests/run_chat_endpoint_tests.py` | NEW | 74 tests covering LLMClient, LLMMessage, ToolDef, ChatOrchestrator, mock provider, intent parsing, LLM loop integration. |

## Key Design Decisions

1. **Provider abstraction** — `LLMClient` supports both Anthropic and Mock providers via the same interface. Falls back to mock when API key is not configured.
2. **Existing mock mode preserved** — `process_message()` continues to work for backward compatibility. `run_llm_loop()` is the new production path.
3. **SSE streaming** — `POST /chat/stream` returns Server-Sent Events for real-time progress (tool_call_start, tool_call_result, text_delta, turn_complete).
4. **Tool definitions from registry** — `_build_tool_definitions()` generates JSON Schema tool definitions for 6 tools (list_pages, fetch_page, propose_create/update/delete_page, validate_course).
5. **Course context in system prompt** — Every turn re-fetches course state and includes it in the system prompt (DB-first state).
6. **Token tracking** — Input/output token counts tracked per turn, returned in API response.

## See Also

- [US-AI-023 Full Spec](../US-AI-023_AI_CHAT_ENDPOINT_LLM_INTERACTION_LOOP.md) — Complete functional and technical specification
- [US-BKND-AI-014](../backend-userstories/US-BKND-AI-014_enriched.md) — Simple Chat Edit (predecessor)
- [US-BKND-AI-025](../backend-userstories/US-BKND-AI-025_enriched.md) — Prompt Safety (next dependency)
