# US-BKND-AI-028: Context Pruning and Token Optimization

**Status:** ✅ COMPLETE
**Priority:** SHOULD
**Sprint:** 5
**Implemented:** 2026-06-15

## Summary

Context window manager with token counting, three pruning strategies (sliding window, priority-based, summarization), budget checking, and integration with the LLM chat orchestrator. Ensures conversations stay within model context limits while preserving critical information.

## Files Created/Modified

| File | Action | Description |
|---|---|---|
| `app/services/ai/context_manager.py` | NEW | ContextManager class with token counting, 3 pruning strategies, budget checking |
| `app/services/ai/chat_orchestrator.py` | MODIFIED | Integrated context pruning in run_llm_loop() before LLM calls |
| `.env.example` | MODIFIED | Added AI_MAX_CONTEXT_TOKENS, AI_RESERVE_OUTPUT_TOKENS, AI_CONTEXT_PRUNING_STRATEGY, AI_MIN_KEEP_MESSAGES |
| `tests/run_context_pruning_tests.py` | NEW | 33 tests covering token counting, all strategies, edge cases |

## Three Pruning Strategies

| Strategy | Behavior | Best For |
|---|---|---|
| sliding_window | Keep most recent N messages, drop oldest | General use |
| priority | Keep system > proposals > user > short assistant | Tool-heavy conversations |
| summarize | Replace pruned middle with summary placeholder | Long conversations needing context |

## Key Design Decisions

1. **Token estimation** — Character-based (~4 chars/token) with optional tiktoken for accuracy
2. **Output token reserve** — Always reserves tokens for the model's response (default 4096)
3. **min_keep_messages** — Guarantees at least N messages survive pruning (default 2)
4. **Non-destructive** — Pruning only removes from the message list, never modifies original messages
5. **Chronological ordering** — Messages returned in correct time order regardless of strategy

## See Also

- [US-BKND-AI-023](US-BKND-AI-023_enriched.md) — AI Chat Endpoint (integrates context pruning)
