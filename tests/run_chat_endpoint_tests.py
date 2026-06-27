"""Standalone test runner for US-BKND-AI-023 — AI Chat Endpoint and LLM Loop.

Tests LLMClient, ChatOrchestrator, tool definitions, message conversion,
streaming events, system prompt construction, and mock provider behavior.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ai.llm_client import (
    LLMClient, LLMProvider, LLMMessage, ToolDef, LLMResponse, LLMStreamEvent,
    LLMClientError,
)
from app.services.ai.chat_orchestrator import ChatOrchestrator

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


async def main():
    global passed, failed

    # ═══════════════════════════════════════════════════════════════
    # LLMClient Tests
    # ═══════════════════════════════════════════════════════════════
    print("=== LLMClient Tests ===")

    # 1. Mock provider is default
    client = LLMClient()
    check("default provider is MOCK", client.provider == LLMProvider.MOCK)

    # 2. Anthropic provider can be set
    client2 = LLMClient(provider=LLMProvider.ANTHROPIC, api_key="test-key")
    check("anthropic provider settable", client2.provider == LLMProvider.ANTHROPIC)

    # 3. Mock chat returns structured response
    messages = [LLMMessage(role="user", content="Hello, list my pages")]
    response = await client.chat(messages)
    check("mock chat returns content", response.content is not None)
    check("mock chat has stop_reason", response.stop_reason == "end_turn")
    check("mock chat has token_usage", isinstance(response.token_usage, dict))
    check("mock chat model is 'mock'", response.model == "mock")

    # 4. Mock chat includes user message in response
    check("mock echoes user message", "Hello" in response.content)

    # 5. Mock stream yields events
    events = []
    async for event in client.chat_stream(messages):
        events.append(event)
    check("mock stream yields events", len(events) >= 2)
    check("mock stream has text_delta", any(e.event_type == "text_delta" for e in events))
    check("mock stream has turn_complete", any(e.event_type == "turn_complete" for e in events))

    # 6. LLMClientError
    e = LLMClientError("test error", retryable=True, status_code=429)
    check("LLMClientError message", e.message == "test error")
    check("LLMClientError retryable", e.retryable is True)
    check("LLMClientError status_code", e.status_code == 429)

    # ═══════════════════════════════════════════════════════════════
    # LLMMessage Tests
    # ═══════════════════════════════════════════════════════════════
    print("\n=== LLMMessage Tests ===")

    # 7. User message
    msg = LLMMessage(role="user", content="Hello")
    api_fmt = msg.to_api_format()
    check("user message role", api_fmt["role"] == "user")
    check("user message content", api_fmt["content"] == "Hello")

    # 8. Assistant message with text
    msg = LLMMessage(role="assistant", content="Hi there!")
    api_fmt = msg.to_api_format()
    check("assistant message role", api_fmt["role"] == "assistant")
    check("assistant message content", api_fmt["content"] == "Hi there!")

    # 9. Assistant message with tool calls
    msg = LLMMessage(
        role="assistant",
        content=None,
        tool_calls=[{"id": "call_1", "name": "list_pages", "input": {}}],
    )
    api_fmt = msg.to_api_format()
    check("assistant with tool calls is list", isinstance(api_fmt.get("content"), list))

    # 10. Tool result message
    msg = LLMMessage(
        role="user",
        content=None,
        tool_results=[{"tool_use_id": "call_1", "output": {"pages": []}, "is_error": False}],
    )
    api_fmt = msg.to_api_format()
    check("tool result has content", "content" in api_fmt, str(api_fmt))
    check("tool result is user role", api_fmt.get("role") == "user", str(api_fmt))

    # 11. System message
    msg = LLMMessage(role="system", content="You are an AI")
    api_fmt = msg.to_api_format()
    check("system message stored", api_fmt["content"] == "You are an AI")

    # ═══════════════════════════════════════════════════════════════
    # ToolDef Tests
    # ═══════════════════════════════════════════════════════════════
    print("\n=== ToolDef Tests ===")

    # 12. ToolDef creation
    td = ToolDef(
        name="list_pages",
        description="List all pages",
        input_schema={"type": "object", "properties": {}, "required": []},
    )
    check("ToolDef name", td.name == "list_pages")
    check("ToolDef description", td.description == "List all pages")
    check("ToolDef schema type", td.input_schema["type"] == "object")

    # ═══════════════════════════════════════════════════════════════
    # ChatOrchestrator Tests
    # ═══════════════════════════════════════════════════════════════
    print("\n=== ChatOrchestrator Tests ===")

    mock_db = AsyncMock()
    orch = ChatOrchestrator(mock_db)

    # 13. Tool definitions
    tool_defs = orch._build_tool_definitions()
    check("builds 7 tool defs", len(tool_defs) == 7)
    tool_names = {td.name for td in tool_defs}
    for expected in ["list_pages", "fetch_page", "query_similar_courses",
                     "propose_create_page", "propose_update_page",
                     "propose_delete_page", "validate_course"]:
        check(f"has {expected}", expected in tool_names)

    # 14. All tools have valid JSON Schema
    for td in tool_defs:
        check(f"{td.name} has type:object", td.input_schema.get("type") == "object")
        check(f"{td.name} has properties", "properties" in td.input_schema)
        check(f"{td.name} has required", "required" in td.input_schema)

    # 15. System prompt
    ctx = {
        "title": "Test Course",
        "page_count": 3,
        "status": "draft",
        "pages": [
            {"title": "Intro", "template_type": "text-content"},
            {"title": "Lesson 1", "template_type": "accordion"},
            {"title": "Quiz", "template_type": "final-assessment"},
        ],
        "template_types": ["text-content", "accordion", "final-assessment"],
    }
    prompt = orch._build_system_prompt(ctx)
    check("system prompt has course title", "Test Course" in prompt)
    check("system prompt has page count", "3 total" in prompt)
    check("system prompt has template types", "text-content" in prompt)
    check("system prompt has rules", "NEVER mutate data directly" in prompt)

    # 16. Empty context handling
    empty_ctx = {"title": "", "page_count": 0, "pages": [], "status": "draft", "template_types": []}
    prompt2 = orch._build_system_prompt(empty_ctx)
    check("handles empty context", "IMPORTANT RULES" in prompt2)

    # 17. Intent parsing (mock mode)
    intent = orch._parse_intent("list pages in my course")
    check("list pages intent", intent["intent"] == "list_pages")

    intent = orch._parse_intent("create a new page called Welcome")
    check("create page intent", intent["intent"] == "create_page")

    intent = orch._parse_intent("delete the assessment page")
    check("delete page intent", intent["intent"] == "delete_page")

    intent = orch._parse_intent("update page one with new content")
    check("update page intent", intent["intent"] == "update_page")

    intent = orch._parse_intent("validate my course for issues")
    check("validate intent", intent["intent"] == "validate_course")

    intent = orch._parse_intent("random text that doesn't match anything")
    check("default to help intent", intent["intent"] == "help")

    # 18. Build response
    resp = orch._build_response("list pages", {"intent": "list_pages"}, [], [])
    check("build_response handles empty pages", isinstance(resp, str) and len(resp) > 10)

    resp = orch._build_response("create a page", {"intent": "create_page"},
                                [{"result": {}}], [
                                    {"diff": {"after": {"title": "New Page"}},
                                     "validation_status": "valid"}
                                ])
    check("build_response for create", "New Page" in resp)

    # 19. extract create params
    title, ttype, data = orch._extract_create_params("create a page called Introduction to Python with tabs")
    check("extracts title", title != "New Page")
    check("detects tabs", ttype == "tabs")

    # ═══════════════════════════════════════════════════════════════
    # Integration: Full LLM Loop (Mock)
    # ═══════════════════════════════════════════════════════════════
    print("\n=== LLM Loop Integration Tests ===")

    # 20. run_llm_loop with mock provider
    result = await orch.run_llm_loop(
        session_id="sess_001",
        user_id="user_001",
        prompt="List all pages in my course",
        course_id="course_001",
        max_tool_rounds=3,
    )
    check("run_llm_loop returns content", result.get("content") is not None)
    check("run_llm_loop has role", result.get("role") == "assistant")
    check("run_llm_loop has tool_calls", isinstance(result.get("tool_calls"), list))
    check("run_llm_loop has proposals", isinstance(result.get("proposals"), list))
    check("run_llm_loop has token_usage", "token_usage" in result)
    check("run_llm_loop has latency_ms", "latency_ms" in result)

    # 21. run_llm_loop with conversation history
    result2 = await orch.run_llm_loop(
        session_id="sess_001",
        user_id="user_001",
        prompt="Create a welcome page",
        course_id="course_001",
        conversation_history=[
            {"role": "user", "content": "Show me my pages"},
            {"role": "assistant", "content": "You have 3 pages: Intro, Lesson 1, Quiz."},
        ],
        max_tool_rounds=3,
    )
    check("run_llm_loop with history works", result2.get("content") is not None)

    # 22. process_message backward compatibility
    result3 = await orch.process_message(
        session_id="sess_001",
        user_id="user_001",
        prompt="list pages",
        course_id="course_001",
    )
    check("process_message returns content", "content" in result3)
    check("process_message returns role", result3.get("role") == "assistant")
    check("process_message returns proposals", "proposals" in result3)

    # ===============================================================
    # Real SSE Streaming Tests (FIX-1 / G-11)
    # ===============================================================
    print("\n=== Real SSE Streaming (G-11 fix) ===")

    # 23. chat_stream produces real text_delta events via mock provider
    mock_client = LLMClient(provider=LLMProvider.MOCK)
    stream_events = []
    async for event in mock_client.chat_stream(
        messages=[LLMMessage(role="user", content="Hello")],
    ):
        stream_events.append(event)
    text_deltas = [e for e in stream_events if e.event_type == "text_delta"]
    turn_completes = [e for e in stream_events if e.event_type == "turn_complete"]
    check("G11-FIX-01a: text_delta events produced", len(text_deltas) > 0)
    check("G11-FIX-01b: turn_complete event produced", len(turn_completes) > 0)
    check("G11-FIX-01c: delta has content", "delta" in text_deltas[0].data)
    check("G11-FIX-01d: turn_complete has token_usage",
          "token_usage" in turn_completes[0].data)

    # 24. process_message_stream yields SSE-formatted events
    orch2 = ChatOrchestrator(AsyncMock())
    sse_events = []
    async for event_str in orch2.process_message_stream(
        session_id="sse-test-001",
        user_id="u-001",
        prompt="Hello from streaming test",
    ):
        sse_events.append(event_str)
    token_events = [e for e in sse_events if "event: token" in e]
    check("G11-FIX-02a: SSE token events produced", len(token_events) > 0)
    check("G11-FIX-02b: token event contains data:",
          "data:" in token_events[0])
    # Verify JSON payload is valid
    for te in token_events:
        data_line = te.split("data: ", 1)[1].strip()
        payload = __import__('json').loads(data_line)
        check("G11-FIX-02c: payload has content key", "content" in payload)

    # 25. complete event emitted at end of stream
    complete_events = [e for e in sse_events if "event: complete" in e]
    check("G11-FIX-03: complete event emitted at stream end", len(complete_events) > 0)

    print(f"\n{'='*60}")
    print(f"RESULTS: {passed} passed, {failed} failed")
    if failures:
        print("FAILURES:")
        for name, detail in failures:
            print(f"  - {name}: {detail}")
    print(f"{'='*60}")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
