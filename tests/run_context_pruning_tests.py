"""Standalone test runner for US-BKND-AI-028 - Context Pruning.

Tests ContextManager: token counting, sliding_window, priority, summarize
strategies, budget checking, edge cases.
"""
from app.services.ai.context_manager import (
    ContextManager, count_tokens, count_message_tokens,
    DEFAULT_MAX_CONTEXT_TOKENS, DEFAULT_RESERVE_OUTPUT_TOKENS,
)

passed = 0
failed = 0
failures = []


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        failures.append((name, detail))
        print(f"  FAIL: {name} -- {detail}")


def main():
    global passed, failed

    # ===============================================================
    # Token Counting
    # ===============================================================
    print("=== Token Counting ===")
    check("count_tokens empty", count_tokens("") == 0)
    check("count_tokens None-like", count_tokens(None) == 0)
    t = count_tokens("hello world")
    check("count_tokens positive", t > 0)
    t_long = count_tokens("hello world " * 100)
    check("count_tokens scales", t_long > t)

    msg = {"role": "user", "content": "Hello, how are you?"}
    t = count_message_tokens(msg)
    check("message tokens includes overhead", t > count_tokens("Hello, how are you?"))

    msg_tools = {"role": "assistant", "content": "", "tool_calls": [
        {"name": "list_pages", "input": {"session_id": "abc"}, "output": {"pages": []}},
    ]}
    t = count_message_tokens(msg_tools)
    check("tool calls add tokens", t > 4)

    # ===============================================================
    # ContextManager Initialization
    # ===============================================================
    print("\n=== Initialization ===")
    mgr = ContextManager()
    check("default max tokens", mgr.max_context_tokens == 8000)
    check("default reserve", mgr.reserve_output_tokens == 4096)
    check("available tokens", mgr.get_available_tokens() == 3904)

    mgr2 = ContextManager(max_context_tokens=16000, reserve_output_tokens=4096)
    check("custom max", mgr2.max_context_tokens == 16000)
    check("custom available", mgr2.get_available_tokens() == 11904)

    mgr3 = ContextManager(strategy="priority")
    check("strategy set", mgr3.strategy == "priority")

    # ===============================================================
    # No Pruning Needed (fits within budget)
    # ===============================================================
    print("\n=== No Pruning ===")
    short_msgs = [
        {"role": "system", "content": "You are an AI assistant."},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi! How can I help?"},
    ]
    pruned, info = mgr.prune(short_msgs)
    check("no pruning when fits", len(pruned) == 3)
    check("messages_removed is 0", info["messages_removed"] == 0)

    # ===============================================================
    # Sliding Window Pruning
    # ===============================================================
    print("\n=== Sliding Window ===")
    mgr_sw = ContextManager(max_context_tokens=100, reserve_output_tokens=50, strategy="sliding_window")

    many_msgs = []
    for i in range(50):
        many_msgs.append({"role": "user", "content": f"Message {i} " + "x" * 50})
        many_msgs.append({"role": "assistant", "content": f"Response {i} " + "y" * 80})

    pruned, info = mgr_sw.prune(many_msgs)
    check("sliding_window prunes", len(pruned) < len(many_msgs))
    check("messages removed > 0", info["messages_removed"] > 0)
    check("keeps last message", pruned[-1]["content"] == many_msgs[-1]["content"])
    check("last message is newest", "Response 49" in pruned[-1]["content"])

    # Verify no empty content causes issues
    pruned, info = mgr_sw.prune([{"role": "user", "content": ""}])
    check("handles empty content", len(pruned) == 1)

    # ===============================================================
    # Priority-Based Pruning
    # ===============================================================
    print("\n=== Priority Pruning ===")
    mgr_pri = ContextManager(max_context_tokens=100, reserve_output_tokens=60, strategy="priority")

    priority_msgs = [
        {"role": "system", "content": "You are an AI assistant."},
        {"role": "user", "content": "Show me my pages"},
        {"role": "assistant", "content": "Here are your pages: ...", "tool_calls": [
            {"name": "list_pages", "input": {}, "output": {"pages": [1,2,3]}},
        ]},
        {"role": "user", "content": "Create a welcome page"},
        {"role": "assistant", "content": "I've created a proposal for the page.", "tool_calls": [
            {"name": "propose_create_page", "input": {"title": "Welcome"}, "output": {"proposal_id": "p1"}},
        ]},
        {"role": "user", "content": "What's the weather?"},  # low priority
        {"role": "assistant", "content": "I don't know."},  # short, low priority
    ]

    pruned, info = mgr_pri.prune(priority_msgs)
    check("priority prunes low priority first", len(pruned) < len(priority_msgs))
    check("system message preserved", any(m["role"] == "system" for m in pruned))
    check("tool messages preserved", any(
        m.get("tool_calls") for m in pruned
    ))

    # ===============================================================
    # Summary Pruning
    # ===============================================================
    print("\n=== Summary Pruning ===")
    mgr_sum = ContextManager(max_context_tokens=100, reserve_output_tokens=60, strategy="summarize")

    sum_msgs = [
        {"role": "system", "content": "You are an AI assistant."},
        {"role": "user", "content": "Question 1 about pages"},
        {"role": "assistant", "content": "Answer 1 about pages"},
        {"role": "user", "content": "Question 2 about templates"},
        {"role": "assistant", "content": "Answer 2 about templates with lots of details " + "x" * 200},
        {"role": "user", "content": "Question 3 about scoring"},
        {"role": "assistant", "content": "Answer 3 " + "y" * 150},
        {"role": "user", "content": "Latest question"},
        {"role": "assistant", "content": "Latest answer"},
    ]

    pruned, info = mgr_sum.prune(sum_msgs)
    check("summary prunes messages", len(pruned) < len(sum_msgs))
    check("keeps first message", pruned[0]["content"] == sum_msgs[0]["content"])
    check("has summary placeholder", any(
        "pruned" in m.get("content", "").lower() or "earlier" in m.get("content", "").lower()
        for m in pruned
    ))
    check("keeps last messages", pruned[-1]["content"] == sum_msgs[-1]["content"])

    # ===============================================================
    # Token Estimation
    # ===============================================================
    print("\n=== Token Estimation ===")
    msgs = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
    ]
    total = mgr.estimate_tokens(msgs, system_prompt="You are helpful.")
    check("estimate is positive", total > 0)
    check("estimate includes system prompt", total > count_tokens("Hello") + count_tokens("Hi there"))

    # ===============================================================
    # Budget Check
    # ===============================================================
    print("\n=== Budget Check ===")
    tiny_mgr = ContextManager(max_context_tokens=50, reserve_output_tokens=20)
    large_msgs = [{"role": "user", "content": "x" * 200}]
    check("would exceed", tiny_mgr.would_exceed_budget(large_msgs))
    check("fits budget", not mgr.would_exceed_budget(short_msgs))

    # ===============================================================
    # Edge Cases
    # ===============================================================
    print("\n=== Edge Cases ===")
    pruned, info = mgr.prune([])
    check("empty messages", len(pruned) == 0)

    check("min_keep respected", mgr.min_keep_messages == 2)

    large_single = [{"role": "user", "content": "x" * 10000}]
    pruned, info = mgr_sw.prune(large_single)
    check("min_keep preserves messages even over budget", len(pruned) == 1)

    print(f"\n{'='*60}")
    print(f"RESULTS: {passed} passed, {failed} failed")
    if failures:
        print("FAILURES:")
        for name, detail in failures:
            print(f"  - {name}: {detail}")
    print(f"{'='*60}")
    return failed == 0


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
