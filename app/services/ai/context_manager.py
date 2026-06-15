"""Context Window Manager - US-BKND-AI-028.

Manages LLM context window limits through token counting, message pruning,
and conversation summarization. Ensures the conversation stays within
model context limits while preserving critical information.

Strategies:
- sliding_window: Keep last N messages, drop oldest
- priority: Drop low-priority messages first, keep system + proposals
- summarize: Replace pruned messages with a summary placeholder

Usage:
    mgr = ContextManager(max_tokens=8000)
    pruned = mgr.prune(messages, system_prompt=sys_prompt)
"""

from __future__ import annotations

import logging
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Token estimation: ~4 chars per token for English text (GPT tokenizer baseline)
CHARS_PER_TOKEN = 4
# Default max context window in tokens
DEFAULT_MAX_CONTEXT_TOKENS = 8000
# Reserve tokens for the response
DEFAULT_RESERVE_OUTPUT_TOKENS = 4096
# Minimum messages to keep regardless of token count
MIN_KEEP_MESSAGES = 2


def count_tokens(text: str) -> int:
    """Estimate token count for a string.

    Uses character-based approximation (~4 chars/token for English).
    Falls back to word-based if tiktoken not available.
    """
    if not text:
        return 0
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        pass
    # Simple approximation: ~4 characters per token
    return max(1, len(text) // CHARS_PER_TOKEN)


def count_message_tokens(message: Dict[str, Any]) -> int:
    """Estimate token count for a message dict."""
    content = message.get("content", "") or ""
    tokens = count_tokens(content)

    # Add overhead for role + formatting (~4 tokens per message)
    tokens += 4

    # Add tool call tokens
    for tc in message.get("tool_calls", []) or []:
        if isinstance(tc, dict):
            tokens += count_tokens(str(tc.get("input", "")))
            tokens += count_tokens(str(tc.get("output", "")))

    # Add tool result tokens
    for tr in message.get("tool_results", []) or []:
        if isinstance(tr, dict):
            tokens += count_tokens(str(tr.get("output", "")))

    return tokens


class ContextManager:
    """Manages LLM context window through pruning and summarization.

    Ensures the total token count of messages + system prompt + tool defs
    stays within the configured max_context_tokens, reserving space for
    the model's response.
    """

    def __init__(
        self,
        max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
        reserve_output_tokens: int = DEFAULT_RESERVE_OUTPUT_TOKENS,
        strategy: str = "sliding_window",
        min_keep_messages: int = MIN_KEEP_MESSAGES,
    ):
        self.max_context_tokens = max_context_tokens
        self.reserve_output_tokens = reserve_output_tokens
        self.strategy = strategy  # "sliding_window" | "priority" | "summarize"
        self.min_keep_messages = min_keep_messages

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_available_tokens(self) -> int:
        """Return the token budget available for messages."""
        return self.max_context_tokens - self.reserve_output_tokens

    def prune(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        tool_definitions: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Prune messages to fit within the token budget.

        Args:
            messages: List of message dicts (role, content, tool_calls, etc.)
            system_prompt: System prompt (always preserved first)
            tool_definitions: Tool definitions (tokens reserved)

        Returns:
            (pruned_messages, pruning_info) where pruning_info has:
                - original_tokens: int
                - pruned_tokens: int
                - messages_removed: int
                - strategy: str
        """
        available = self.get_available_tokens()

        # Reserve tokens for system prompt
        system_tokens = count_tokens(system_prompt or "")
        available -= system_tokens

        # Reserve tokens for tool definitions
        tool_tokens = 0
        if tool_definitions:
            for td in tool_definitions:
                tool_tokens += count_tokens(str(td))
        available -= tool_tokens

        # Count total tokens in messages
        total_tokens = sum(count_message_tokens(m) for m in messages)
        info = {
            "original_tokens": total_tokens + system_tokens + tool_tokens,
            "pruned_tokens": 0,
            "messages_removed": 0,
            "strategy": self.strategy,
            "available_budget": available,
        }

        # If within budget, no pruning needed
        if total_tokens <= available:
            info["pruned_tokens"] = total_tokens + system_tokens + tool_tokens
            return messages, info

        # Prune based on strategy
        if self.strategy == "sliding_window":
            pruned = self._prune_sliding_window(messages, available)
        elif self.strategy == "priority":
            pruned = self._prune_priority(messages, available)
        elif self.strategy == "summarize":
            pruned = self._prune_with_summary(messages, available)
        else:
            pruned = self._prune_sliding_window(messages, available)

        removed = len(messages) - len(pruned)
        pruned_tokens = sum(count_message_tokens(m) for m in pruned)
        info["pruned_tokens"] = pruned_tokens + system_tokens + tool_tokens
        info["messages_removed"] = removed

        if removed > 0:
            logger.info(
                "Context pruned: %d messages removed (%d -> %d tokens)",
                removed, total_tokens, pruned_tokens,
            )

        return pruned, info

    # ------------------------------------------------------------------
    # Pruning Strategies
    # ------------------------------------------------------------------

    def _prune_sliding_window(
        self, messages: List[Dict[str, Any]], token_budget: int
    ) -> List[Dict[str, Any]]:
        """Keep the most recent messages that fit within the budget.

        Always preserves system messages and the last user message.
        Drops oldest messages first.
        """
        if len(messages) <= self.min_keep_messages:
            return messages

        # Always keep the last message (current user prompt)
        last_msg = messages[-1]
        remaining = messages[:-1]

        # Keep system messages at the start
        system_msgs = [m for m in remaining if m.get("role") == "system"]
        other_msgs = [m for m in remaining if m.get("role") != "system"]

        # Start with system messages + last message
        kept = list(system_msgs)
        budget_used = sum(count_message_tokens(m) for m in kept)
        budget_used += count_message_tokens(last_msg)

        # Add most recent messages first (reverse order)
        for msg in reversed(other_msgs):
            msg_tokens = count_message_tokens(msg)
            if budget_used + msg_tokens <= token_budget:
                kept.append(msg)
                budget_used += msg_tokens
            else:
                break

        # Return in chronological order (system first, then oldest surviving, then last)
        kept.sort(key=lambda m: other_msgs.index(m) if m in other_msgs else -1)
        kept.append(last_msg)
        return kept

    def _prune_priority(
        self, messages: List[Dict[str, Any]], token_budget: int
    ) -> List[Dict[str, Any]]:
        """Prune by message priority: system > proposals > user > assistant.

        Messages containing proposals, errors, or confirmations get higher
        priority than generic assistant responses.
        """
        def priority(msg: Dict[str, Any]) -> int:
            role = msg.get("role", "")
            content = msg.get("content", "") or ""

            if role == "system":
                return 100
            if msg.get("tool_calls") or msg.get("tool_results"):
                return 90  # Tool interactions are high value
            if "proposal" in content.lower() or "propose" in content.lower():
                return 80
            if "error" in content.lower() or "invalid" in content.lower():
                return 70
            if role == "user":
                return 50
            if role == "assistant":
                # Assistant messages with substantive content > short ones
                if len(content) > 200:
                    return 40
                return 20
            return 10

        # Sort by priority (descending) then recency (descending within same priority)
        indexed = list(enumerate(messages))
        indexed.sort(key=lambda x: (priority(x[1]), x[0]), reverse=True)

        kept_indices = []
        budget_used = 0
        for idx, msg in indexed:
            msg_tokens = count_message_tokens(msg)
            if budget_used + msg_tokens <= token_budget or len(kept_indices) < self.min_keep_messages:
                kept_indices.append(idx)
                budget_used += msg_tokens

        # Return in chronological order
        result = [m for i, m in enumerate(messages) if i in kept_indices]
        return result

    def _prune_with_summary(
        self, messages: List[Dict[str, Any]], token_budget: int
    ) -> List[Dict[str, Any]]:
        """Replace pruned messages with a summary placeholder.

        Keeps the first N messages and last M messages, replacing
        the middle section with a summary message.
        """
        if len(messages) <= self.min_keep_messages + 2:
            return messages

        # Keep first message (often system/context) and last min_keep messages
        first_msg = messages[0]
        last_msgs = messages[-self.min_keep_messages:]

        # The middle section (to be summarized/removed)
        middle = messages[1:-self.min_keep_messages]

        # Build summary of removed messages
        removed_count = len(middle)
        user_msgs = [m for m in middle if m.get("role") == "user"]
        assistant_msgs = [m for m in middle if m.get("role") == "assistant"]

        summary_content = (
            f"[Earlier conversation: {removed_count} messages removed to stay "
            f"within context limits. {len(user_msgs)} user questions and "
            f"{len(assistant_msgs)} assistant responses were pruned. "
            f"Key topics discussed: "
            + ", ".join(
                (m.get("content") or "")[:80] for m in user_msgs[:3]
            )
            + "]"
        )

        summary_msg = {
            "role": "system",
            "content": summary_content,
        }

        return [first_msg, summary_msg] + last_msgs

    # ------------------------------------------------------------------
    # Token Estimation
    # ------------------------------------------------------------------

    def estimate_tokens(self, messages: List[Dict[str, Any]],
                        system_prompt: str = "",
                        tool_definitions: Optional[List[Dict[str, Any]]] = None) -> int:
        """Estimate total token count for a message set."""
        total = count_tokens(system_prompt)
        for msg in messages:
            total += count_message_tokens(msg)
        if tool_definitions:
            for td in tool_definitions:
                total += count_tokens(str(td))
        return total

    def would_exceed_budget(
        self, messages: List[Dict[str, Any]],
        system_prompt: str = "",
        additional_tokens: int = 0,
    ) -> bool:
        """Check if adding tokens would exceed the budget."""
        current = self.estimate_tokens(messages, system_prompt)
        return (current + additional_tokens) > self.get_available_tokens()
