# US-PEND-022: LLM-Based Context Window Summarization — DESIGN GAPS RESOLVED

| Field | Value |
|-------|-------|
| **Type** | 🆕 New Task (Feature) |
| **Priority** | 🟡 HIGH |
| **Batch** | 6 — Feature Development |
| **Depends On** | None |
| **Estimated Effort** | 2-3 days |
| **Target File** | `app/services/ai/context_manager.py` |

---

## User Story

**As a** user in a long AI chat session (~30+ turns),
**I want** the AI to remember the important context from earlier in our conversation,
**So that** I don't have to repeat myself and the AI's responses stay coherent across the full session.

---

## Current State (Code Verified 2026-06-21)

- `context_manager.py` — 3 pruning strategies: `sliding_window`, `priority`, `summarize`
- `summarize` strategy (line 260) is truncation-based, NOT LLM-based
- After ~20 turns, older context is simply dropped
- Line 10 comment: `# summarize: truncation-based summarization (basic)`

---

## 🔧 Open-Source Tooling

**No new libraries needed.** Uses existing `LLMClient` + `LLMMessage` (already in project).

---

## Design Decisions (Resolved)

The original doc left 3 design questions open. Here are the answers:

| Decision | Answer | Rationale |
|----------|--------|-----------|
| **When to trigger summarization?** | When `estimate_tokens(messages) > max_tokens * 0.70` (70% threshold). This leaves 30% headroom for the LLM response. | Prevents unnecessary cost (don't summarize when under budget). Triggers early enough that the summary stays small. |
| **How to detect unchanged turns?** | Hash the list of turn IDs + turn timestamps. `hashlib.sha256("|".join(f"{t.id}:{t.created_at}" for t in turns)).hexdigest()`. | Turn IDs are stable; timestamps detect edits. If hash matches cached hash, skip summarization. |
| **Which model for summarization?** | Directly use `LLMClient(model="claude-haiku-4-5")` — NOT `ModelTierRouter`. | `ModelTierRouter.classify_task()` classifies task types (Planner vs Generator), not model selection. For summarization, Haiku is always the right choice (cheap, fast, good at summarization). |

---

## Enriched Implementation

### Add to `ContextManager.__init__`:

```python
def __init__(self, max_tokens: int = 8000, reserve_output_tokens: int = 4096):
    # ... existing code ...
    self._summarize_threshold = 0.70     # Summarize at 70% of max_tokens
    self._summary_cache: Dict[str, str] = {}  # hash → summary
```

### Add `_llm_summarize()` method:

```python
import hashlib
from app.services.ai.llm_client import LLMClient, LLMMessage

async def _llm_summarize(self, turns: list) -> str:
    """Summarize older conversation turns using Haiku (cheap model).

    Trigger: called when estimate_tokens(messages) > max_tokens * 0.70.
    Cache: skips summarization if turns haven't changed since last call.
    """
    # Build cache key from turn IDs + timestamps
    cache_key = hashlib.sha256(
        "|".join(
            f"{getattr(t, 'id', i)}:{getattr(t, 'created_at', '')}"
            for i, t in enumerate(turns)
        ).encode()
    ).hexdigest()

    if cache_key in self._summary_cache:
        return self._summary_cache[cache_key]

    # Build summarization prompt
    turn_texts = []
    for t in turns:
        content = getattr(t, 'content', '') or ''
        role = getattr(t, 'role', 'user')
        turn_texts.append(f"[{role}]: {content[:500]}")  # Truncate long turns

    prompt = (
        "Summarize the following conversation between an AI and a course author. "
        "Preserve: key decisions made, course structure choices, user preferences, "
        "and any tool outputs that were referenced later. Be concise.\n\n"
        + "\n".join(turn_texts)
    )

    llm = LLMClient(model="claude-haiku-4-5")
    response = await llm.chat(
        messages=[LLMMessage(role="user", content=prompt)],
        max_tokens=500,
        temperature=0.2,  # Low temp for factual summarization
    )

    summary = response.content or ""
    self._summary_cache[cache_key] = summary
    return summary
```

### Modify `summarize` strategy (around line 260):

```python
# In prune() — when strategy == "summarize":
if strategy == "summarize":
    middle_start = 1  # Keep system message (index 0)
    middle_end = len(messages) - 1  # Keep last user message

    if middle_end - middle_start <= 2:
        return messages  # Too few turns to summarize

    middle_turns = messages[middle_start:middle_end]
    summary_text = await self._llm_summarize(middle_turns)

    # Replace middle turns with a single summary message
    return [
        messages[0],  # System prompt
        LLMMessage(role="user", content=f"[Prior conversation summary]: {summary_text}"),
        messages[-1],  # Last user message
    ]
```

---

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | Session with 30+ turns stays coherent | Token budget not exceeded; older decisions preserved in summary |
| AC-2 | Token count stays within model limits | `estimate_tokens()` < `max_tokens` after pruning |
| AC-3 | Summarization uses Haiku (cheap) | Check `LLMClient(model="claude-haiku-4-5")` in source |
| AC-4 | Summary cache avoids redundant LLM calls | Same turns → second call returns cached summary (log shows no API call) |
| AC-5 | Summarization triggers at 70% budget | Only called when `estimate_tokens > max_tokens * 0.70` |

---

## Validation

```bash
python tests/run_context_pruning_tests.py
```
