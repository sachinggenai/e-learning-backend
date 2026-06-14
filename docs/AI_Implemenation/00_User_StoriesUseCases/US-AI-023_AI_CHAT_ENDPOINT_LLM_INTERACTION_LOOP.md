# US-AI-023: AI Chat Endpoint and LLM Interaction Loop

**Status:** Draft
**Priority:** MUST (MVP)
**Depends on:** US-AI-002 (Feature Flags), US-AI-003 (Isolated AI Module), US-AI-004 (AI Persistence), US-AI-005 (Tool Contracts), US-AI-006 (AI Sessions), US-AI-007 (Page Tools)
**Source flows:** AI Chat Orchestration and LLM Interaction Loop (Flow 14)
**Epic Owner:** Technical Product Owner

---

## 1. Functional Specification

### 1.1 User Story

As an **Author**, I want to send natural-language instructions to an AI assistant through a chat endpoint and receive structured, validated tool-call responses in real-time, so that I can create and modify course content conversationally without manually editing each page.

As an **AI Agent**, I want a deterministic, stateful interaction loop that provides me with the current course state, a scoped set of tools, validation feedback on my proposals, and the ability to retry, so that I can produce valid course content that passes all server-side checks before the user confirms.

### 1.2 Overview

This user story delivers the central AI orchestration layer: the **chat endpoint** and the **LLM interaction loop**. It is the runtime that powers every natural-language authoring interaction in the platform.

The architecture follows a **server-side tool-calling loop** pattern:

1. Frontend sends a user message to `POST /api/v1/ai/chat` with the session ID and message text.
2. The server loads the session, resolves the current course state from the database (not from conversation history), and constructs a system prompt with tool definitions and course context.
3. Messages are sent to the LLM (Claude via Anthropic API, with native tool-calling).
4. The LLM responds with either a text response (shown to the user) or one or more tool calls (e.g., `list_pages`, `fetch_page`, `propose_create_page`, `propose_update_page`).
5. The server executes each tool call in order: validates the input against the tool schema, executes the tool against the database, validates the output, and returns the structured result back to the LLM.
6. The LLM may respond with further tool calls or a final text response.
7. The loop continues until the LLM produces a final text response (a "turn" completes) or a configured max-tool-call limit is reached.
8. The final response (text + any tool call results that produced proposals) is returned to the frontend as a JSON payload or Server-Sent Events (SSE) stream.

**Key design decisions:**

- **DB-first state**: Every turn re-fetches course state from the database. The LLM never holds authoritative state.
- **Server-side tool execution**: Tool schemas are defined in code, not in prompts. The server validates every tool call from the LLM before execution.
- **Propose-before-apply**: Mutation tools (`propose_create_page`, `propose_update_page`, `propose_delete_page`) only create proposals (pending review). No data is mutated until `apply_*` is confirmed by the user.
- **Streaming-ready**: The endpoint returns via SSE so the frontend can show real-time progress (tool calls being executed, validation results, final text).
- **Stateless loop**: Each turn is self-contained in terms of LLM state. Session state (proposals, course ID, user context) is managed server-side in the database.

### 1.3 Actors

| Actor | Role |
|---|---|
| Author (User) | Sends natural-language messages via the chat UI; reviews proposals and confirms/rejects |
| AI Agent (LLM) | Interprets user instructions, selects and invokes tools, generates content |
| ChatOrchestrator (Server) | Manages the LLM interaction loop: prompt construction, tool routing, validation, turn management |
| ToolExecutor (Server) | Routes tool calls to domain services, validates inputs/outputs, returns structured results |
| Session Manager (Server) | Ensures session validity, course scope ownership, expiry enforcement |
| Frontend (Chat UI) | Renders real-time SSE stream, shows tool execution status, displays proposals for user review |

### 1.4 Flow: AI Chat Turn with Tool-Calling Loop

**Precondition:** A valid AI session exists (US-AI-006) scoped to a course that the user owns. The frontend holds a `session_id`, `course_id`, and an `X-Trace-ID` header.

**Phase 0 — Send Message**
1. User types a message in the chat panel: "Create a new welcome page called 'Introduction to Python' with a brief course overview."
2. Frontend calls `POST /api/v1/ai/chat` with body `{session_id, message, stream: true}`.
3. Backend validates the session exists, is not expired, and the user owns the course.
4. Backend generates or reuses a `turn_id` (UUID v4) for this chat turn.
5. Backend returns HTTP 200 with `Content-Type: text/event-stream` (SSE).

**Phase 1 — Load Context & Build Prompt**
1. The `ChatOrchestrator` loads the current course state from the database:
   - `CourseRecord` for the session's course ID.
   - `PageRecord[]` with `ComponentRecord[]` for all pages.
   - Active `ai_proposals` (pending proposals for this session that haven't been applied or expired).
   - Most recent conversation history (last N messages from `ai_session_messages` table for context window management).
2. The orchestrator builds the message array for the LLM:
   - System prompt (from `app/services/ai/system_prompts.py` or DB).
   - Tool definitions (generated from the tool contract registry, US-AI-005).
   - Previous conversation history (last ~20 messages, configurable via `AI_CHAT_CONTEXT_MESSAGE_LIMIT`).
   - The new user message.
3. The orchestrator constructs the tool list from the session's scope:
   - `list_pages`, `fetch_page` — always available.
   - `propose_create_page`, `propose_update_page` — available if course is editable.
   - `propose_delete_page` — available if course is editable.
   - `apply_page_proposal`, `apply_update_proposal`, `confirm_delete_page` — available if there are pending proposals.
   - `query_similar_courses` — available if RAG is configured.
   - `validate_course` — always available.

**Phase 2 — LLM Interaction Loop**
1. The orchestrator sends the messages + tools array to the LLM provider (via `LLMClient`).
2. The LLM responds with a `Message` containing either:
   - **Text content**: The final response for the user.
   - **Tool use blocks**: One or more tool call requests.
3. If the response contains tool use blocks, the orchestrator iterates through each tool call in order:
   a. Extract the tool name and input arguments.
   b. Validate input arguments against the tool's JSON schema (from the tool registry).
   c. Execute the tool via `ToolExecutor`, which:
      - Verifies permission scope (page belongs to session's course).
      - Calls the appropriate domain service (e.g., `PageRepository.list_by_course`).
      - For `propose_*` tools: creates an `ai_proposals` record with status `PENDING_REVIEW`.
      - For `apply_*` tools: verifies the proposal exists and is `PENDING_REVIEW`, checks `user_confirmed`.
      - Returns a structured `ToolResult` with status, data, and optional validation messages.
   d. If tool execution succeeds, package the result as a `tool_result` block.
   e. If tool execution fails validation, package the error as a `tool_result` with `is_error: true`.
   f. Append the result back to the message list and send to the LLM for another iteration.
   g. If the total tool call rounds exceed `AI_CHAT_MAX_TOOL_ROUNDS` (default 10), stop the loop and return a timeout-like message.
4. Each tool call execution and result is streamed to the frontend via SSE events (see Section 1.7).
5. When the LLM produces a final text response (no more tool calls), the turn completes.

**Phase 3 — Persist and Return**
1. The user message and the LLM's final text response are persisted to `ai_session_messages`.
2. Every tool call and its result are persisted in `ai_tool_call_logs` (for audit and debugging).
3. The turn ID, token usage, and latency are recorded in `ai_telemetry_events`.
4. The SSE stream ends with a `[DONE]` event or a final JSON envelope.
5. If `stream: false`, the endpoint returns a single JSON response with the final text and any created proposal IDs.

**Phase 4 — User Actions on Proposals**
1. The frontend renders the final AI text response.
2. If the turn created proposals (via `propose_*` tools), the frontend renders proposal previews (page previews, diffs).
3. The user reviews proposals and either confirms (triggering `apply_*` tool calls in a subsequent turn) or rejects them.
4. Rejected proposals expire or are explicitly cancelled.

### 1.5 SSE Event Stream Contract

When `stream: true`, the endpoint returns a SSE stream with the following event types:

```
event: turn_start
data: {"turn_id": "turn_abc123", "session_id": "sess_xyz", "started_at": "..."}

event: tool_call_start
data: {"tool_call_id": "call_001", "tool_name": "list_pages", "input": {}}

event: tool_call_result
data: {"tool_call_id": "call_001", "tool_name": "list_pages", "status": "success", "output": {"pages": [...]}}

event: tool_call_error
data: {"tool_call_id": "call_002", "tool_name": "propose_create_page", "status": "error", "code": "VALIDATION_ERROR", "message": "...", "retryable": true}

event: text_delta
data: {"delta": "Here is the welcome page I created..."}

event: turn_complete
data: {"turn_id": "turn_abc123", "proposal_ids": ["prop_001", "prop_002"], "token_usage": {"input": 2345, "output": 890}, "latency_ms": 4520}

event: turn_error
data: {"turn_id": "turn_abc123", "code": "LLM_PROVIDER_ERROR", "message": "LLM service temporarily unavailable", "retryable": true}

event: [DONE]
```

### 1.6 Error Conditions

| Condition | HTTP Status | Error Code | Behavior |
|---|---|---|---|
| Session not found or expired | 404 | `SESSION_NOT_FOUND` | Frontend must create a new session |
| Session user mismatch | 403 | `SESSION_USER_MISMATCH` | Security violation; logged |
| Session course mismatch | 403 | `TOOL_PERMISSION_DENIED` | Tool call references page outside session's course |
| AI feature flag disabled | 404 | `FEATURE_NOT_AVAILABLE` | All chat endpoints disabled |
| Message exceeds max length (10000 chars) | 422 | `MESSAGE_TOO_LONG` | Frontend should truncate or warn |
| LLM provider unavailable (after fallback) | 503 | `LLM_PROVIDER_UNAVAILABLE` | Turn marked as failed; retryable |
| LLM timeout (per call) | 503 | `LLM_TIMEOUT` | Configurable via `AI_LLM_TIMEOUT_SECONDS` |
| Tool execution error (server-side) | 500 | `TOOL_EXECUTION_ERROR` | Turn fails; logged with trace ID |
| Max tool rounds exceeded (10) | — | `MAX_TOOL_ROUNDS_EXCEEDED` | Turn terminates; LLM told to summarize |
| Rate limit exceeded | 429 | `RATE_LIMIT_EXCEEDED` | Per-user/per-tenant chat limits |
| Invalid tool call (unknown tool) | — | `UNKNOWN_TOOL` | Returned to LLM as error result |
| Proposal not found for apply | 404 | `PROPOSAL_NOT_FOUND` | Apply fails; proposal may have expired |
| Proposal already applied | 409 | `PROPOSAL_ALREADY_APPLIED` | Idempotent: return existing result |
| Validation error in propose_* | — | `VALIDATION_ERROR` | Returned to LLM for retry |
| Context window limit reached | — | `CONTEXT_WINDOW_LIMIT` | Old messages pruned; summary injected |

---

## 2. Technical Specification

### 2.1 New Database Tables — DDL

**Table: `ai_session_messages`**

```sql
CREATE TABLE ai_session_messages (
    id                  SERIAL PRIMARY KEY,
    message_id          VARCHAR(64) UNIQUE NOT NULL,
    session_id          VARCHAR(64) NOT NULL REFERENCES ai_sessions(session_id) ON DELETE CASCADE,
    turn_id             VARCHAR(64),                          -- groups messages by chat turn
    role                VARCHAR(16) NOT NULL
                        CHECK (role IN ('system', 'user', 'assistant', 'tool_result')),
    
    -- Message content
    content             TEXT,                                  -- text content (for user/assistant)
    tool_calls          JSONB,                                -- [{tool_call_id, tool_name, input}] for assistant
    tool_call_id        VARCHAR(64),                          -- for tool_result messages
    tool_name           VARCHAR(128),                         -- for tool_result messages
    tool_result         JSONB,                                -- for tool_result messages
    
    -- Token tracking
    input_tokens        INTEGER,
    output_tokens       INTEGER,
    
    -- Timestamps
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_asm_session ON ai_session_messages(session_id);
CREATE INDEX idx_asm_turn ON ai_session_messages(session_id, turn_id);
CREATE INDEX idx_asm_created ON ai_session_messages(session_id, created_at);
```

**Table: `ai_tool_call_logs`**

```sql
CREATE TABLE ai_tool_call_logs (
    id                  SERIAL PRIMARY KEY,
    log_id              VARCHAR(64) UNIQUE NOT NULL,
    session_id          VARCHAR(64) NOT NULL REFERENCES ai_sessions(session_id) ON DELETE CASCADE,
    turn_id             VARCHAR(64) NOT NULL,
    tool_call_id        VARCHAR(64) NOT NULL,
    tool_name           VARCHAR(128) NOT NULL,
    
    -- Input/output
    input_args          JSONB NOT NULL,
    output_data         JSONB,
    error_message       TEXT,
    
    -- Status
    status              VARCHAR(16) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'executing', 'success', 'error')),
    retry_count         INTEGER NOT NULL DEFAULT 0,
    
    -- Performance
    execution_duration_ms INTEGER,
    
    -- Timestamps
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_atcl_session ON ai_tool_call_logs(session_id);
CREATE INDEX idx_atcl_turn ON ai_tool_call_logs(turn_id);
CREATE INDEX idx_atcl_tool ON ai_tool_call_logs(tool_name);
```

**Table: `ai_telemetry_events`**

```sql
CREATE TABLE ai_telemetry_events (
    id                  SERIAL PRIMARY KEY,
    event_id            VARCHAR(64) UNIQUE NOT NULL,
    session_id          VARCHAR(64) REFERENCES ai_sessions(session_id) ON DELETE SET NULL,
    turn_id             VARCHAR(64),
    trace_id            VARCHAR(64) NOT NULL,
    
    -- Event classification
    event_type          VARCHAR(64) NOT NULL,
                        -- 'chat_turn_started', 'chat_turn_completed',
                        -- 'tool_call_executed', 'llm_call_started', 'llm_call_completed',
                        -- 'llm_fallback_triggered', 'llm_timeout', 'validation_error',
                        -- 'rate_limit_exceeded', 'context_window_pruned'
    
    -- Payload
    payload             JSONB NOT NULL DEFAULT '{}',
    
    -- Usage & performance
    input_tokens        INTEGER,
    output_tokens       INTEGER,
    latency_ms          INTEGER,
    model_id            VARCHAR(128),
    
    -- Timestamps
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ate_session ON ai_telemetry_events(session_id);
CREATE INDEX idx_ate_trace ON ai_telemetry_events(trace_id);
CREATE INDEX idx_ate_type ON ai_telemetry_events(event_type);
CREATE INDEX idx_ate_created ON ai_telemetry_events(created_at DESC);
```

**Table: `ai_rate_limits`**

```sql
CREATE TABLE ai_rate_limits (
    id                  SERIAL PRIMARY KEY,
    scope               VARCHAR(16) NOT NULL CHECK (scope IN ('user', 'tenant', 'global')),
    scope_id            VARCHAR(128) NOT NULL,              -- user_id or tenant_id
    endpoint            VARCHAR(128) NOT NULL,               -- 'chat', 'tool_execute', 'generate'
    window_start        TIMESTAMPTZ NOT NULL,
    request_count       INTEGER NOT NULL DEFAULT 0,
    
    -- Expire for auto-cleanup
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE (scope, scope_id, endpoint, window_start)
);

CREATE INDEX idx_arl_lookup ON ai_rate_limits(scope, scope_id, endpoint, window_start);
```

### 2.2 SQLAlchemy ORM Models

**New file: `app/models/ai_chat.py`**

```python
"""ORM models for AI chat persistence — session messages, tool call logs, telemetry, rate limits."""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import (
    String, DateTime, JSON, Text, Integer, ForeignKey, BigInteger,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMPTZ

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class AISessionMessageRecord(Base):
    """Persisted message in an AI session conversation."""

    __tablename__ = "ai_session_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_sessions.session_id", ondelete="CASCADE"),
        index=True
    )
    turn_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    role: Mapped[str] = mapped_column(
        String(16), default="user"
    )  # 'system', 'user', 'assistant', 'tool_result'

    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tool_calls: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    tool_call_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    tool_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    tool_result: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "messageId": self.message_id,
            "sessionId": self.session_id,
            "turnId": self.turn_id,
            "role": self.role,
            "content": self.content,
            "toolCalls": self.tool_calls,
            "toolCallId": self.tool_call_id,
            "toolName": self.tool_name,
            "toolResult": self.tool_result,
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class AIToolCallLogRecord(Base):
    """Audit log for every tool call executed during a chat turn."""

    __tablename__ = "ai_tool_call_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    log_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_sessions.session_id", ondelete="CASCADE"),
        index=True
    )
    turn_id: Mapped[str] = mapped_column(String(64), index=True)
    tool_call_id: Mapped[str] = mapped_column(String(64))

    tool_name: Mapped[str] = mapped_column(String(128))
    input_args: Mapped[dict] = mapped_column(JSONB, nullable=False)
    output_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="pending")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    execution_duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "logId": self.log_id,
            "sessionId": self.session_id,
            "turnId": self.turn_id,
            "toolCallId": self.tool_call_id,
            "toolName": self.tool_name,
            "inputArgs": self.input_args,
            "outputData": self.output_data,
            "errorMessage": self.error_message,
            "status": self.status,
            "retryCount": self.retry_count,
            "executionDurationMs": self.execution_duration_ms,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class AITelemetryEventRecord(Base):
    """Telemetry event for observability, billing, and debugging."""

    __tablename__ = "ai_telemetry_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    session_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("ai_sessions.session_id", ondelete="SET NULL"),
        nullable=True, index=True
    )
    turn_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)

    event_type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)

    input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    model_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "eventId": self.event_id,
            "sessionId": self.session_id,
            "turnId": self.turn_id,
            "traceId": self.trace_id,
            "eventType": self.event_type,
            "payload": self.payload,
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "latencyMs": self.latency_ms,
            "modelId": self.model_id,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class AIRateLimitRecord(Base):
    """Rate limit counter for AI endpoint usage."""

    __tablename__ = "ai_rate_limits"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(16))  # 'user', 'tenant', 'global'
    scope_id: Mapped[str] = mapped_column(String(128))
    endpoint: Mapped[str] = mapped_column(String(128))  # 'chat', 'tool_execute', etc.
    window_start: Mapped[datetime] = mapped_column(TIMESTAMPTZ)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, default=datetime.utcnow)

    __table_args__ = (
        # Unique constraint for upsert pattern
        None,
    )
```

### 2.3 Pydantic Request/Response DTOs

**New file: `app/routers/ai_chat_dtos.py`**

```python
"""Pydantic DTOs for the AI Chat API."""
from __future__ import annotations
from typing import Optional, Any
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str = Field(..., description="Active AI session ID")
    message: str = Field(..., min_length=1, max_length=10000, description="User message text")
    stream: bool = Field(default=True, description="Enable SSE streaming response")
    context_refresh: bool = Field(
        default=False,
        description="If true, forces a full course state refresh before the turn"
    )


class ChatResponse(BaseModel):
    turn_id: str
    session_id: str
    reply: Optional[str] = Field(None, description="Final assistant reply text")
    proposals: list[dict] = Field(
        default_factory=list,
        description="Proposals created during this turn (pending review)",
    )
    tool_calls_executed: int = 0
    tool_rounds: int = 0
    token_usage: dict = Field(
        default_factory=lambda: {"input": 0, "output": 0}
    )
    latency_ms: int = 0
    status: str = "completed"  # 'completed', 'max_rounds_exceeded', 'error'


class ChatErrorResponse(BaseModel):
    code: str
    message: str
    retryable: bool = False
    turn_id: Optional[str] = None
    details: dict = Field(default_factory=dict)


class ToolDefinition(BaseModel):
    """A tool definition sent to the LLM."""
    name: str
    description: str
    input_schema: dict
    output_schema: Optional[dict] = None
    idempotent: bool = False


class ToolCallRequest(BaseModel):
    """A tool call invocation from the LLM."""
    tool_call_id: str
    tool_name: str
    input: dict


class ToolCallResult(BaseModel):
    """Result of executing a tool call."""
    tool_call_id: str
    tool_name: str
    status: str  # 'success', 'error'
    output: Optional[Any] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    retryable: bool = False
    execution_duration_ms: int = 0


class ChatContext(BaseModel):
    """Context payload sent to frontend for a chat turn."""
    turn_id: str
    session_status: str  # 'active', 'expiring_soon', 'expired'
    pages_in_course: int = 0
    pending_proposals: int = 0
    token_usage: dict = Field(default_factory=lambda: {"session_total": 0, "turn": {"input": 0, "output": 0}})
    model: str = ""
```

### 2.4 API Contracts

#### POST /api/v1/ai/chat

The central chat endpoint. Accepts a user message and session ID. Returns a JSON response (non-streaming) or SSE stream (streaming).

**Request:**
```json
{
  "session_id": "sess_abc123",
  "message": "Create a new welcome page called 'Introduction to Python' with a brief course overview.",
  "stream": true,
  "context_refresh": false
}
```

**Response 200 (Non-streaming, `stream: false`):**
```json
{
  "turn_id": "turn_xyz789",
  "session_id": "sess_abc123",
  "reply": "I have created a new welcome page 'Introduction to Python' for you. Here is the preview:\n\n**Title:** Introduction to Python\n**Content:** This comprehensive course will introduce you to the Python programming language, covering basic syntax, data structures, and practical exercises.\n\nI also created a proposal for the page. You can review it now and approve it when you are ready.",
  "proposals": [
    {
      "proposal_id": "prop_001",
      "type": "create_page",
      "preview": {
        "pageId": "page_temp_001",
        "title": "Introduction to Python",
        "templateType": "welcome",
        "data": {
          "content": "This comprehensive course will introduce you to the Python programming language...",
          "subtitle": "Begin Your Python Journey",
          "objectives": ["Understand basic Python syntax", "Write your first program", "Learn data types and variables"]
        }
      },
      "validation": {
        "status": "valid",
        "errors": [],
        "warnings": ["Welcome page has no media; consider adding a video or image."]
      }
    }
  ],
  "tool_calls_executed": 3,
  "tool_rounds": 2,
  "token_usage": {"input": 4523, "output": 1205},
  "latency_ms": 8430,
  "status": "completed"
}
```

**Error Responses:**

`404 SESSION_NOT_FOUND`:
```json
{
  "code": "SESSION_NOT_FOUND",
  "message": "Session 'sess_abc123' not found or has expired.",
  "retryable": true
}
```

`503 LLM_PROVIDER_UNAVAILABLE`:
```json
{
  "code": "LLM_PROVIDER_UNAVAILABLE",
  "message": "The AI provider is currently unavailable. Please try again in a few minutes.",
  "retryable": true
}
```

#### GET /api/v1/ai/sessions/{session_id}/messages

Retrieves conversation history for the current session (for context recovery on page reload).

**Response 200:**
```json
{
  "session_id": "sess_abc123",
  "messages": [
    {"messageId": "msg_001", "role": "user", "content": "Create a welcome page...", "createdAt": "..."},
    {"messageId": "msg_002", "role": "assistant", "content": "I have created...", "createdAt": "..."}
  ],
  "total_messages": 24,
  "has_more": false
}
```

#### GET /api/v1/ai/sessions/{session_id}/tokens

Returns token usage for the session (for cost tracking).

**Response 200:**
```json
{
  "session_id": "sess_abc123",
  "total_input_tokens": 45230,
  "total_output_tokens": 12300,
  "total_cost_usd": 0.45,
  "turns_count": 6,
  "tool_calls_count": 18,
  "model": "claude-sonnet-4-20250514",
  "session_started_at": "..."
}
```

### 2.5 Service Signatures

**New file: `app/services/ai/chat_orchestrator.py`**

```python
"""Orchestrates the AI chat interaction loop.

The ChatOrchestrator manages one complete chat turn:
  1. Load session and course state.
  2. Build messages array with context, history, and tool definitions.
  3. Call LLM with native tool-calling.
  4. Process tool calls (validate -> execute -> return results).
  5. Repeat until LLM produces final text or max rounds reached.
  6. Persist messages, tool logs, and telemetry.
  7. Return final response.
"""

from __future__ import annotations
import json
import logging
import os
import time
import uuid
from datetime import datetime
from typing import Any, AsyncGenerator, Callable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ChatOrchestrator:
    """Manages one chat turn, including the LLM interaction loop."""

    DEFAULT_MODEL = os.getenv("AI_CHAT_MODEL", "claude-sonnet-4-20250514")
    FALLBACK_MODEL = os.getenv("AI_CHAT_FALLBACK_MODEL", "claude-haiku-3-5-20241022")
    MAX_TOOL_ROUNDS = int(os.getenv("AI_CHAT_MAX_TOOL_ROUNDS", "10"))
    CONTEXT_MESSAGE_LIMIT = int(os.getenv("AI_CHAT_CONTEXT_MESSAGE_LIMIT", "20"))
    CONTEXT_TOKEN_LIMIT = int(os.getenv("AI_CHAT_CONTEXT_TOKEN_LIMIT", "80000"))
    LLM_TIMEOUT_SECONDS = int(os.getenv("AI_LLM_TIMEOUT_SECONDS", "60"))

    def __init__(
        self,
        db_session: AsyncSession,
        llm_callable: Optional[Callable] = None,
    ):
        self.session = db_session
        self.llm_callable = llm_callable

    async def process_turn(
        self,
        session_id: str,
        user_message: str,
        user_id: str,
        stream: bool = True,
        trace_id: Optional[str] = None,
    ) -> AsyncGenerator[dict, None] | dict:
        """Process a single chat turn.

        Args:
            session_id: Active AI session ID.
            user_message: The user's message text.
            user_id: Authenticated user ID.
            stream: If True, yields SSE events via an async generator.
            trace_id: Correlation ID for observability.

        Returns:
            If stream=False: a ChatResponse dict.
            If stream=True: an async generator yielding SSE event dicts.
        """
        raise NotImplementedError

    async def _load_session_context(self, session_id: str) -> dict:
        """Load session, course state, and recent messages.

        Returns:
            Dict with session, course, pages, proposals, message_history, tools.
        """
        raise NotImplementedError

    async def _build_messages(
        self,
        context: dict,
        user_message: str,
    ) -> tuple[list[dict], list[dict]]:
        """Build messages array and tool definitions for the LLM call.

        Returns:
            (messages: list of dicts with role/content, tools: list of tool definitions)
        """
        raise NotImplementedError

    async def _execute_llm_loop(
        self,
        messages: list[dict],
        tools: list[dict],
        context: dict,
        turn_id: str,
        trace_id: str,
    ) -> AsyncGenerator[dict, None] | dict:
        """Execute the LLM interaction loop.

        Sends messages+tools to LLM, processes tool call responses,
        and loops until the LLM produces a final text response.

        Args:
            messages: Initial messages array (system + history + user).
            tools: Tool definitions for the LLM.
            context: Session context (for permission checks).
            turn_id: Current turn ID.
            trace_id: Correlation trace ID.

        Yields (stream=True) or Returns (stream=False):
            SSE event dicts or final ChatResponse.
        """
        raise NotImplementedError

    async def _execute_tool(
        self,
        tool_name: str,
        tool_input: dict,
        context: dict,
        tool_call_id: str,
        trace_id: str,
    ) -> dict:
        """Execute a single tool call from the LLM.

        Validates input, executes, validates output, and returns
        a ToolResult dict. Logs to ai_tool_call_logs.
        """
        raise NotImplementedError

    async def _call_llm(
        self,
        messages: list[dict],
        tools: list[dict],
        model: Optional[str] = None,
    ) -> dict:
        """Call the LLM provider with messages and tools.

        Attempts primary model first; falls back to FALLBACK_MODEL
        on timeout, rate limit, or connection error.

        Returns:
            Parsed LLM response dict with content and tool_calls.
        """
        raise NotImplementedError

    async def _persist_messages(
        self,
        turn_id: str,
        session_id: str,
        messages: list[dict],
    ) -> None:
        """Persist all messages from the turn to ai_session_messages."""
        raise NotImplementedError

    async def _prune_context_if_needed(
        self,
        session_id: str,
        current_token_count: int,
    ) -> None:
        """Prune old messages if token count exceeds CONTEXT_TOKEN_LIMIT.

        Strategy: Remove oldest user/assistant pairs, keep system prompt
        and most recent messages. If pruning removes substantive context,
        inject a summary message generated from the removed messages.
        """
        raise NotImplementedError

    async def _write_telemetry(
        self,
        event_type: str,
        payload: dict,
        trace_id: str,
        session_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        latency_ms: Optional[int] = None,
        model_id: Optional[str] = None,
    ) -> None:
        """Write a telemetry event to ai_telemetry_events."""
        raise NotImplementedError

    async def _check_rate_limits(
        self,
        user_id: str,
        tenant_id: Optional[str],
    ) -> None:
        """Check and increment rate limits for the user/tenant.

        Raises RateLimitError if exceeded.
        """
        raise NotImplementedError

    def _build_system_prompt(self, context: dict) -> str:
        """Build the system prompt for this session.

        Includes:
          - Base system prompt (from app/services/ai/system_prompts.py or DB).
          - Course context metadata (title, description, page count).
          - Current pending proposals summary.
          - Rules for tool use and proposal lifecycle.
        """
        raise NotImplementedError
```

**New file: `app/services/ai/llm_client.py`**

```python
"""LLM provider client for the AI chat interaction loop.

Supports:
  - Anthropic Claude API (Messages API with native tool calling).
  - Configurable model selection (primary + fallback).
  - Streaming responses.
  - Timeout with configurable seconds.
  - Retry with exponential backoff on transient errors.
  - Telemetry logging for every LLM call.
"""

from __future__ import annotations
import json
import logging
import os
import time
from typing import AsyncGenerator, Optional
import httpx

logger = logging.getLogger(__name__)


class LLMProviderError(Exception):
    """Base error for LLM provider failures."""
    def __init__(self, message: str, status_code: int = 500, retryable: bool = False):
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(message)


class LLMTimeoutError(LLMProviderError):
    def __init__(self, message: str = "LLM provider timed out"):
        super().__init__(message, status_code=504, retryable=True)


class LLMClient:
    """HTTP client for the Anthropic Claude Messages API."""

    API_URL = os.getenv(
        "AI_LLM_API_URL",
        "https://api.anthropic.com/v1/messages"
    )
    API_KEY = os.getenv("AI_LLM_API_KEY", "")
    DEFAULT_MODEL = os.getenv("AI_CHAT_MODEL", "claude-sonnet-4-20250514")
    FALLBACK_MODEL = os.getenv("AI_CHAT_FALLBACK_MODEL", "claude-haiku-3-5-20241022")
    TIMEOUT_SECONDS = int(os.getenv("AI_LLM_TIMEOUT_SECONDS", "60"))
    MAX_RETRIES = int(os.getenv("AI_LLM_MAX_RETRIES", "2"))
    MAX_TOKENS = int(os.getenv("AI_LLM_MAX_TOKENS", "4096"))

    def __init__(self):
        self._client = httpx.AsyncClient(
            timeout=self.TIMEOUT_SECONDS,
            headers={
                "x-api-key": self.API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )

    async def call(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        model: Optional[str] = None,
        stream: bool = False,
        max_tokens: Optional[int] = None,
    ) -> dict:
        """Call the Claude Messages API with optional tool calling.

        Args:
            messages: Array of message objects (role + content).
            tools: Array of tool definitions (name + input_schema).
            model: Model ID override (defaults to DEFAULT_MODEL).
            stream: Enable streaming response.
            max_tokens: Max output tokens (defaults to MAX_TOKENS).

        Returns:
            Parsed API response dict with content blocks.

        Raises:
            LLMProviderError: On non-retryable API errors.
            LLMTimeoutError: On timeout.
        """
        raise NotImplementedError

    async def call_stream(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[dict, None]:
        """Stream response from the Claude Messages API.

        Yields:
            Dicts with event type and data (content_block_start,
            content_block_delta, content_block_stop, message_start,
            message_delta, message_stop).
        """
        raise NotImplementedError

    async def _attempt_call(
        self,
        body: dict,
        attempt: int = 1,
    ) -> dict:
        """Single attempt with error classification."""
        raise NotImplementedError

    async def with_fallback(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        model: Optional[str] = None,
    ) -> dict:
        """Try primary model, fallback to FALLBACK_MODEL on failure.

        Returns:
            Response dict with added 'model_used' and 'fallback_triggered' keys.
        """
        raise NotImplementedError

    async def close(self) -> None:
        await self._client.aclose()
```

**New file: `app/services/ai/tool_executor.py`**

```python
"""Executes tool calls from the LLM against domain services.

Each tool call is validated, permission-scoped, executed, and its
output is returned in a structured format. Tools that create proposals
(propose_*) write to ai_proposals table but never mutate course data.
"""

from __future__ import annotations
import logging
from typing import Any, Callable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ToolExecutionError(Exception):
    def __init__(self, message: str, code: str = "TOOL_EXECUTION_ERROR", retryable: bool = False):
        self.code = code
        self.retryable = retryable
        super().__init__(message)


class PermissionDeniedError(ToolExecutionError):
    def __init__(self, message: str = "Permission denied"):
        super().__init__(message, code="PERMISSION_DENIED", retryable=False)


class ToolExecutor:
    """Routes and executes tool calls from the LLM.

    Tool registry is built from the tool contract definitions in
    US-AI-005 (app/services/ai/tool_registry.py). Each tool has:
      - name, description, input_schema
      - handler: async callable(db_session, session_context, input) -> dict
      - permission_scope: 'course' or 'org'
      - idempotent: bool

    The executor validates input against the schema, calls the handler,
    validates output, and writes a tool call audit log.
    """

    def __init__(self, db_session: AsyncSession):
        self.session = db_session

    async def execute(
        self,
        tool_name: str,
        input_args: dict,
        session_context: dict,
        tool_call_id: str,
    ) -> dict:
        """Execute a tool call.

        Args:
            tool_name: Name of the tool to execute.
            input_args: Input arguments from the LLM.
            session_context: Dict with session_id, course_id, user_id, pages, etc.
            tool_call_id: The LLM's tool call ID for correlation.

        Returns:
            ToolResult dict with status, output/error, execution_duration_ms.

        Raises:
            ToolExecutionError: On execution failure.
            PermissionDeniedError: On scope violation.
        """
        raise NotImplementedError

    def _validate_input(self, tool_name: str, input_args: dict) -> list[str]:
        """Validate input args against the tool schema.

        Returns:
            List of validation error messages (empty if valid).
        """
        raise NotImplementedError

    async def _check_permission(
        self,
        tool_name: str,
        input_args: dict,
        session_context: dict,
    ) -> None:
        """Verify that the tool call is within the session's scope.

        For course-scoped tools: verify page_id/course_id matches session.
        For org-scoped tools: verify user_id matches session.
        Raises PermissionDeniedError on violation.
        """
        raise NotImplementedError

    async def _execute_list_pages(self, input_args: dict, context: dict) -> dict:
        """List all pages in the current course with metadata."""
        raise NotImplementedError

    async def _execute_fetch_page(self, input_args: dict, context: dict) -> dict:
        """Fetch a single page with full component data."""
        raise NotImplementedError

    async def _execute_propose_create_page(self, input_args: dict, context: dict) -> dict:
        """Propose a new page (creates ai_proposals record, no mutation)."""
        raise NotImplementedError

    async def _execute_propose_update_page(self, input_args: dict, context: dict) -> dict:
        """Propose page updates (creates ai_proposals record with diff, no mutation)."""
        raise NotImplementedError

    async def _execute_propose_delete_page(self, input_args: dict, context: dict) -> dict:
        """Propose page deletion (creates ai_proposals record with confirmation token)."""
        raise NotImplementedError

    async def _execute_apply_page_proposal(self, input_args: dict, context: dict) -> dict:
        """Apply a previously proposed page creation."""
        raise NotImplementedError

    async def _execute_apply_update_proposal(self, input_args: dict, context: dict) -> dict:
        """Apply a previously proposed page update."""
        raise NotImplementedError

    async def _execute_confirm_delete_page(self, input_args: dict, context: dict) -> dict:
        """Confirm and execute a previously proposed deletion."""
        raise NotImplementedError

    async def _execute_validate_course(self, input_args: dict, context: dict) -> dict:
        """Validate the full course against all business rules."""
        raise NotImplementedError

    async def _execute_query_similar_courses(self, input_args: dict, context: dict) -> dict:
        """Query RAG store for similar course examples."""
        raise NotImplementedError
```

**New file: `app/services/ai/context_builder.py`**

```python
"""Builds the LLM context: system prompt, tool definitions, and message history.

Handles:
  - Loading and versioning system prompts (from DB or file).
  - Building tool definitions from the tool registry.
  - Constructing the messages array with history, respecting context window limits.
  - Context pruning: removing old messages and injecting summaries.
"""

from __future__ import annotations
from typing import Optional


class ContextBuilder:
    """Builds and manages the LLM message context for a chat turn."""

    SYSTEM_PROMPT_VERSION = "1.0"
    CONTEXT_MESSAGE_LIMIT = 20
    CONTEXT_TOKEN_LIMIT = 80000

    @classmethod
    def build_system_prompt(
        cls,
        course_title: str,
        course_description: str,
        page_count: int,
        pending_proposals: list[dict],
        session_started_at: str,
    ) -> str:
        """Build the system prompt for the LLM.

        Includes course context, proposal lifecycle rules,
        tool usage rules, and behaviour guidelines.
        """
        raise NotImplementedError

    @classmethod
    def build_tool_definitions(cls, context: dict) -> list[dict]:
        """Build tool definitions array for the LLM.

        Returns a subset of available tools based on session context
        (e.g., exclude apply_* tools if no pending proposals).
        """
        raise NotImplementedError

    @classmethod
    def build_messages_array(
        cls,
        system_prompt: str,
        history: list[dict],
        user_message: str,
        max_messages: int = 20,
    ) -> list[dict]:
        """Build the messages array for the LLM call.

        Orders: system prompt -> conversation history (trimmed) -> user message.
        Trims history to max_messages most recent entries.
        """
        raise NotImplementedError

    @classmethod
    def prune_context(
        cls,
        messages: list[dict],
        max_tokens: int = 80000,
    ) -> list[dict]:
        """Prune messages to stay within the context token limit.

        Strategy:
          1. Count tokens in current messages (approximate by char count / 4).
          2. If over limit, remove oldest user/assistant pairs until under limit.
          3. If removal count > 2, insert a summary message placeholder.
          4. Always keep system prompt and most recent user message.
        """
        raise NotImplementedError

    @classmethod
    def build_summary_message(cls, removed_messages: list[dict]) -> dict:
        """Build a summary message from removed conversation history.

        Used when pruning removes substantive context.
        Returns a message dict with role='user' containing a summary.
        """
        raise NotImplementedError

    @classmethod
    def count_tokens(cls, text: str) -> int:
        """Approximate token count for a text string.

        Uses ~4 chars per token as a rough estimate for Claude models.
        For production, use a proper tokenizer (tiktoken or anthropic tokenizer).
        """
        return len(text) // 4
```

### 2.6 Chat Repository

**New file: `app/repositories/ai_chat_repo.py`**

```python
"""Repository for AI chat persistence: messages, tool call logs, telemetry, rate limits."""
from __future__ import annotations
from typing import Optional, Sequence
from datetime import datetime, timedelta

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_chat import (
    AISessionMessageRecord,
    AIToolCallLogRecord,
    AITelemetryEventRecord,
    AIRateLimitRecord,
)


class AISessionMessageRepository:
    """DB access for ai_session_messages."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self, record: AISessionMessageRecord
    ) -> AISessionMessageRecord:
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def bulk_create(
        self, records: list[AISessionMessageRecord]
    ) -> list[AISessionMessageRecord]:
        self.session.add_all(records)
        await self.session.commit()
        for r in records:
            await self.session.refresh(r)
        return records

    async def list_by_session(
        self,
        session_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        role: Optional[str] = None,
    ) -> Sequence[AISessionMessageRecord]:
        q = (
            select(AISessionMessageRecord)
            .where(AISessionMessageRecord.session_id == session_id)
            .order_by(AISessionMessageRecord.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        if role:
            q = q.where(AISessionMessageRecord.role == role)
        return (await self.session.execute(q)).scalars().all()

    async def count_by_session(self, session_id: str) -> int:
        q = (
            select(func.count())
            .select_from(AISessionMessageRecord)
            .where(AISessionMessageRecord.session_id == session_id)
        )
        return (await self.session.execute(q)).scalar() or 0

    async def delete_by_session(self, session_id: str) -> int:
        q = delete(AISessionMessageRecord).where(
            AISessionMessageRecord.session_id == session_id
        )
        result = await self.session.execute(q)
        await self.session.commit()
        return result.rowcount

    async def get_oldest_messages_for_pruning(
        self,
        session_id: str,
        keep_count: int = 10,
    ) -> Sequence[AISessionMessageRecord]:
        """Get the oldest messages that can be pruned."""
        total = await self.count_by_session(session_id)
        if total <= keep_count:
            return []
        offset = keep_count
        q = (
            select(AISessionMessageRecord)
            .where(AISessionMessageRecord.session_id == session_id)
            .order_by(AISessionMessageRecord.created_at.asc())
            .offset(offset)
        )
        return (await self.session.execute(q)).scalars().all()


class AIToolCallLogRepository:
    """DB access for ai_tool_call_logs."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self, record: AIToolCallLogRecord
    ) -> AIToolCallLogRecord:
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def update_status(
        self,
        log_id: str,
        status: str,
        output_data: Optional[dict] = None,
        error_message: Optional[str] = None,
        execution_duration_ms: Optional[int] = None,
    ) -> Optional[AIToolCallLogRecord]:
        # Implementation same pattern as other repos
        raise NotImplementedError

    async def list_by_turn(
        self, turn_id: str
    ) -> Sequence[AIToolCallLogRecord]:
        q = (
            select(AIToolCallLogRecord)
            .where(AIToolCallLogRecord.turn_id == turn_id)
            .order_by(AIToolCallLogRecord.created_at.asc())
        )
        return (await self.session.execute(q)).scalars().all()

    async def list_by_session(
        self, session_id: str, limit: int = 100
    ) -> Sequence[AIToolCallLogRecord]:
        q = (
            select(AIToolCallLogRecord)
            .where(AIToolCallLogRecord.session_id == session_id)
            .order_by(AIToolCallLogRecord.created_at.desc())
            .limit(limit)
        )
        return (await self.session.execute(q)).scalars().all()


class AITelemetryEventRepository:
    """DB access for ai_telemetry_events."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self, record: AITelemetryEventRecord
    ) -> AITelemetryEventRecord:
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def list_by_session(
        self, session_id: str, limit: int = 100
    ) -> Sequence[AITelemetryEventRecord]:
        q = (
            select(AITelemetryEventRecord)
            .where(AITelemetryEventRecord.session_id == session_id)
            .order_by(AITelemetryEventRecord.created_at.desc())
            .limit(limit)
        )
        return (await self.session.execute(q)).scalars().all()

    async def aggregate_token_usage(
        self, session_id: str
    ) -> dict:
        """Return total input/output tokens for a session."""
        q = (
            select(
                func.coalesce(func.sum(AITelemetryEventRecord.input_tokens), 0),
                func.coalesce(func.sum(AITelemetryEventRecord.output_tokens), 0),
            )
            .where(AITelemetryEventRecord.session_id == session_id)
        )
        row = (await self.session.execute(q)).one()
        return {"input_tokens": int(row[0]), "output_tokens": int(row[1])}


class AIRateLimitRepository:
    """DB access for ai_rate_limits."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def increment_and_check(
        self,
        scope: str,
        scope_id: str,
        endpoint: str,
        max_requests: int,
        window_seconds: int = 3600,
    ) -> bool:
        """Increment the rate limit counter and check if it exceeds max.

        Returns:
            True if under limit, False if exceeded.
        """
        raise NotImplementedError

    async def reset_window(
        self,
        scope: str,
        scope_id: str,
        endpoint: str,
    ) -> None:
        """Reset the rate limit window for a scope."""
        raise NotImplementedError
```

### 2.7 API Router

**New file: `app/routers/ai_chat.py`**

```python
"""AI Chat router — the central LLM interaction endpoint.

Endpoints:
  POST   /api/v1/ai/chat                                       — Send message and process turn
  GET    /api/v1/ai/sessions/{session_id}/messages             — Get conversation history
  GET    /api/v1/ai/sessions/{session_id}/tokens               — Get token usage
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.utils.error_envelope import api_http_exception
from app.utils.feature_flags import ai_authoring_enabled

from app.routers.ai_chat_dtos import (
    ChatRequest,
    ChatResponse,
    ChatErrorResponse,
)
from app.services.ai.chat_orchestrator import ChatOrchestrator

router = APIRouter(prefix="/api/v1/ai", tags=["AI Chat"])


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Send a chat message and process an AI interaction turn",
    responses={
        400: {"description": "Validation error"},
        403: {"description": "Session user mismatch"},
        404: {"description": "Session not found"},
        429: {"description": "Rate limit exceeded"},
        503: {"description": "LLM provider unavailable"},
    },
)
async def chat(
    body: ChatRequest,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(ai_authoring_enabled),
    x_trace_id: str = Query("", alias="X-Trace-ID"),
):
    """Send a message to the AI assistant.

    Processes the message through the LLM interaction loop:
      1. Validates the session.
      2. Loads course context and conversation history.
      3. Sends to LLM with tool definitions.
      4. Executes tool calls and returns results to LLM.
      5. Loops until the LLM produces a final response.
      6. Persists messages and telemetry.

    Supports SSE streaming when `stream: true`.
    """
    try:
        orchestrator = ChatOrchestrator(session)
        trace_id = x_trace_id or str(uuid.uuid4())

        if body.stream:
            event_generator = orchestrator.process_turn(
                session_id=body.session_id,
                user_message=body.message,
                user_id="authenticated_user",
                stream=True,
                trace_id=trace_id,
            )
            return StreamingResponse(
                event_generator,
                media_type="text/event-stream",
                headers={
                    "X-Trace-ID": trace_id,
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
            )
        else:
            result = await orchestrator.process_turn(
                session_id=body.session_id,
                user_message=body.message,
                user_id="authenticated_user",
                stream=False,
                trace_id=trace_id,
            )
            return result

    except SessionNotFoundError as exc:
        raise api_http_exception(404, "SESSION_NOT_FOUND", str(exc))
    except SessionUserMismatchError as exc:
        raise api_http_exception(403, "SESSION_USER_MISMATCH", str(exc))
    except RateLimitError as exc:
        raise api_http_exception(429, "RATE_LIMIT_EXCEEDED", str(exc))
    except LLMProviderError as exc:
        status_code = 503 if exc.retryable else 500
        raise api_http_exception(status_code, exc.__class__.__name__, str(exc))
    except Exception as exc:
        logger.exception("Unhandled error in chat endpoint")
        raise api_http_exception(500, "INTERNAL_ERROR", "An unexpected error occurred.")


@router.get(
    "/sessions/{session_id}/messages",
    summary="Get conversation history for a session",
)
async def get_session_messages(
    session_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(ai_authoring_enabled),
):
    """Get the message history for an AI session.

    Useful for context recovery when the user reloads the chat UI.
    Returns messages ordered by creation time (oldest first).
    """
    from app.repositories.ai_chat_repo import AISessionMessageRepository
    repo = AISessionMessageRepository(session)
    messages = await repo.list_by_session(
        session_id, limit=limit, offset=offset
    )
    total = await repo.count_by_session(session_id)
    return {
        "session_id": session_id,
        "messages": [m.to_dict() for m in messages],
        "total_messages": total,
        "has_more": (offset + limit) < total,
    }


@router.get(
    "/sessions/{session_id}/tokens",
    summary="Get token usage for a session",
)
async def get_session_token_usage(
    session_id: str,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(ai_authoring_enabled),
):
    """Get token usage and estimated cost for a session."""
    from app.repositories.ai_chat_repo import AITelemetryEventRepository
    repo = AITelemetryEventRepository(session)
    usage = await repo.aggregate_token_usage(session_id)
    total_tokens = usage["input_tokens"] + usage["output_tokens"]
    # Rough pricing: $3/M input, $15/M output for Claude Sonnet
    cost_estimate = (
        usage["input_tokens"] * 3.0 / 1_000_000
        + usage["output_tokens"] * 15.0 / 1_000_000
    )
    return {
        "session_id": session_id,
        "total_input_tokens": usage["input_tokens"],
        "total_output_tokens": usage["output_tokens"],
        "total_tokens": total_tokens,
        "estimated_cost_usd": round(cost_estimate, 6),
    }
```

### 2.8 Main Application Registration

**In `app/main.py`, add to imports:**
```python
from app.routers import ai_chat  # new import
```

**In the router registration section:**
```python
api_router.include_router(ai_chat.router)
```

**In the `lifespan` startup section, add to the ORM model imports:**
```python
import app.models.ai_chat  # noqa: F401 — register ORM model
```

**In `app/models/__init__.py`, add:**
```python
from app.models.ai_chat import (
    AISessionMessageRecord,
    AIToolCallLogRecord,
    AITelemetryEventRecord,
    AIRateLimitRecord,
)
```

### 2.9 Tool Registry Integration (US-AI-005)

The `ToolExecutor` must be initialized with the tool definitions from the tool contract registry (US-AI-005). Each tool's `handler` method maps to one of the `_execute_*` methods in `ToolExecutor`:

| Tool Name | Handler Method | Scoping | Idempotent |
|---|---|---|---|
| `list_pages` | `_execute_list_pages` | Course | Yes |
| `fetch_page` | `_execute_fetch_page` | Course | Yes |
| `propose_create_page` | `_execute_propose_create_page` | Course | No |
| `propose_update_page` | `_execute_propose_update_page` | Course | No |
| `propose_delete_page` | `_execute_propose_delete_page` | Course | No |
| `apply_page_proposal` | `_execute_apply_page_proposal` | Course | Yes |
| `apply_update_proposal` | `_execute_apply_update_proposal` | Course | Yes |
| `confirm_delete_page` | `_execute_confirm_delete_page` | Course | No |
| `validate_course` | `_execute_validate_course` | Course | Yes |
| `query_similar_courses` | `_execute_query_similar_courses` | Org | Yes |

### 2.10 Environment Variables

Add to `.env` and `.env.example`:

```ini
# ============================================
# AI Chat & LLM Interaction Loop Configuration
# ============================================

# LLM Provider
AI_LLM_API_KEY=
AI_LLM_API_URL=https://api.anthropic.com/v1/messages
AI_LLM_TIMEOUT_SECONDS=60
AI_LLM_MAX_RETRIES=2
AI_LLM_MAX_TOKENS=4096

# Model Selection
AI_CHAT_MODEL=claude-sonnet-4-20250514
AI_CHAT_FALLBACK_MODEL=claude-haiku-3-5-20241022

# Chat Orchestration
AI_CHAT_MAX_TOOL_ROUNDS=10
AI_CHAT_CONTEXT_MESSAGE_LIMIT=20
AI_CHAT_CONTEXT_TOKEN_LIMIT=80000
AI_CHAT_MAX_MESSAGE_LENGTH=10000

# Rate Limits
AI_RATE_LIMIT_CHAT_PER_USER=100
AI_RATE_LIMIT_CHAT_PER_TENANT=1000
AI_RATE_LIMIT_WINDOW_SECONDS=3600

# System Prompt
AI_SYSTEM_PROMPT_VERSION=1.0
```

---

## 3. Non-Functional Requirements

### 3.1 Performance

| Requirement | Target | Measurement |
|---|---|---|
| Chat request acceptance (non-streaming) | < 200 ms p95 | Time to validate session + return |
| First SSE event (streaming) | < 500 ms p95 | Time to first event after request |
| Per-tool execution latency | < 100 ms p95 (read tools), < 500 ms p95 (write tools) | Tool handler execution time |
| LLM first-token latency | < 3 s p95 | Time from request to first token from provider |
| Full turn latency (3 tool rounds, no generation) | < 15 s p95 | Total turn time for simple edits |
| Concurrent chat sessions per tenant | <= 20 | In-process limit |
| Message persistence write | < 50 ms p95 | DB write time per message |

### 3.2 Security

| Requirement | Implementation |
|---|---|
| Session-gated access | Every chat request validates session ID, user ID, and course ID match |
| Tool scope enforcement | ToolExecutor checks every tool call's page_id belongs to session.course_id |
| Prompt injection resistance | User message text is escaped/truncated before prompt construction; HTML/script tags stripped |
| No raw SQL access | All DB access goes through repository layer; no `execute_sql` or `direct_query` tools |
| PII redaction in logs | Tool input/output logged with sensitive fields redacted (password, apiKey, token) |
| Rate limit enforcement | Per-user and per-tenant rate limits checked before LLM call |
| Feature flag gating | All AI chat endpoints require `AI_AUTHORING_ENABLED=true` |
| Turn-level idempotency | Duplicate message sends with same turn_id are idempotent (return existing result) |

### 3.3 Data Integrity

| Requirement | Implementation |
|---|---|
| Message durability | Every message is persisted to `ai_session_messages` before the LLM call proceeds |
| Tool call audit | Every tool call is logged to `ai_tool_call_logs` with input, output, status, duration |
| Proposal non-mutation | `propose_*` tools never mutate course data; only create `ai_proposals` records |
| Context pruning safety | Pruned messages are deleted from `ai_session_messages` only after summary is persisted |
| Session isolation | Sessions are scoped to a single course; messages from different sessions are never mixed |

### 3.4 Availability

| Requirement | Implementation |
|---|---|
| Model fallback | Primary model failure triggers automatic fallback to `AI_CHAT_FALLBACK_MODEL` |
| LLM timeout | Configurable timeout (`AI_LLM_TIMEOUT_SECONDS`); retried once, then fallback |
| Graceful degradation | If LLM is unavailable, chat returns `503 LLM_PROVIDER_UNAVAILABLE`; existing course editing is unaffected |
| Session persistence | If server restarts mid-turn, session context is recoverable from persisted messages |
| Rate limit transparency | Rate limit errors include `Retry-After` header and current usage info |

### 3.5 Observability

| Metric | Type | Tags |
|---|---|---|
| `ai_chat_requests_total` | Counter | session_id, stream, status |
| `ai_chat_turn_duration_seconds` | Histogram | model, tool_rounds |
| `ai_llm_calls_total` | Counter | model, status, fallback |
| `ai_llm_latency_seconds` | Histogram | model, stream |
| `ai_tool_calls_total` | Counter | tool_name, status |
| `ai_tool_call_duration_seconds` | Histogram | tool_name |
| `ai_context_prunes_total` | Counter | session_id |
| `ai_rate_limits_exceeded_total` | Counter | scope, endpoint |
| `ai_chat_tokens_total` | Counter | model, type (input/output) |
| `ai_active_sessions` | Gauge | tenant |

---

## 4. Current State

### 4.1 What Exists Today

1. **Session Management Foundation**: `ai_sessions` table design is defined in US-AI-006. The `AISessionRecord` model and `SessionManager` service exist with creation, expiry, and scope validation.

2. **Feature Flag Infrastructure**: `app/utils/feature_flags.py` provides `ai_authoring_enabled` dependency for gating AI endpoints. The `FEATURE_AI_SUGGESTIONS` flag exists but is separate from the authoring flag.

3. **Course/Page/Component CRUD**: Full CRUD via `app/routers/courses.py`, `app/routers/page_components.py` with corresponding repositories.

4. **Validation Pipeline**: `app/utils/validation.py` provides `CourseValidator` with business rules and the `validate_course_json` dependency.

5. **Error Envelope Pattern**: `app/utils/error_envelope.py` defines the normalized error response format used across all routers.

6. **WebSearch/Skill Tools**: The codebase uses Claude Code's built-in tools for its own development. The AI authoring feature needs its own set of domain tools.

### 4.2 What Is Missing

1. `ai_session_messages`, `ai_tool_call_logs`, `ai_telemetry_events`, `ai_rate_limits` tables with ORM models and Alembic migration.
2. `ChatOrchestrator` service — the main interaction loop engine.
3. `LLMClient` service — HTTP client for Anthropic Claude Messages API with streaming, timeout, retry, and fallback.
4. `ToolExecutor` service — routes and executes tool calls against domain services.
5. `ContextBuilder` service — builds system prompts, tool definitions, and manages conversation history.
6. Repositories for message, tool log, telemetry, and rate limit persistence.
7. Pydantic DTOs for chat request/response models and SSE event schema.
8. `POST /api/v1/ai/chat` endpoint with SSE streaming support.
9. `GET /api/v1/ai/sessions/{session_id}/messages` endpoint for context recovery.
10. `GET /api/v1/ai/sessions/{session_id}/tokens` endpoint for cost tracking.
11. Rate limit enforcement per-user and per-tenant.
12. Context pruning logic for managing context window limits.
13. Tool registry integration — wiring tool definitions from US-AI-005 into the LLM's tool definitions.
14. Registration in `app/main.py` (router + ORM model import).
15. Environment variables for all chat/LLM configuration.
16. Unit, integration, and E2E tests for the chat interaction loop.

### 4.3 Dependencies on Earlier Stories

| Story | Dependency |
|---|---|
| US-AI-002 | Feature flag for `AI_AUTHORING_ENABLED` |
| US-AI-003 | Isolated AI API module structure (`app/routers/ai_chat.py`, `app/services/ai/`) |
| US-AI-004 | AI persistence foundations (`ai_sessions` table, `SessionManager`) |
| US-AI-005 | Tool contract definitions and registry (`app/services/ai/tool_registry.py`) |
| US-AI-006 | AI session creation and lifecycle (`ai_sessions` CRUD, session validation) |
| US-AI-007 | Page list and fetch tools (`list_pages`, `fetch_page` handlers) |

---

## 5. Expansion Points

### 5.1 Multi-Turn Conversation Memory (Post-MVP)

The current implementation limits context to the last N messages. Future iterations should add semantic memory: the LLM can explicitly store and retrieve facts across turns (e.g., "the user prefers concise explanations"). This requires a persistent key-value store scoped to the session and an additional `store_memory` / `recall_memory` tool pair.

### 5.2 Streaming Generation of Tool Calls (Post-MVP)

Currently, the LLM generates all tool calls in a single response, and the server executes them serially. Future versions could stream tool calls as they are generated, reducing perceived latency for complex multi-tool turns. This requires the Claude API's streaming `content_block_start` events for `tool_use` blocks.

### 5.3 Parallel Tool Execution (Post-MVP)

Read-only tools (`list_pages`, `fetch_page`, `query_similar_courses`) can be executed in parallel when the LLM requests them in the same turn round. This reduces turn latency for information-gathering phases.

### 5.4 Human-in-the-Loop Tool Approval (Post-MVP)

For high-risk tools (delete, batch operations), the chat loop could pause mid-turn and wait for user confirmation before proceeding. This is more granular than the current proposal/apply pattern and would enable the LLM to explain the proposed action before the confirmation modal appears.

### 5.5 Token Budget Enforcement (US-AI-036)

Once US-AI-036's cost tracking and token budget enforcement is available, the chat endpoint should check the user/organization's remaining token budget before each LLM call and refuse if the budget is exhausted.

### 5.6 A/B Testing System Prompts (US-AI-042)

The `ContextBuilder.build_system_prompt()` method should read the system prompt version from `AI_SYSTEM_PROMPT_VERSION` env var or a DB-stored configuration, enabling A/B testing of different system prompts (US-AI-042).

### 5.7 Multi-Provider Routing (US-AI-026)

Currently, the LLM client supports Anthropic Claude with a fallback. Future versions (US-AI-026) should support configurable provider routing (OpenAI, Google, AWS Bedrock) with latency-based and cost-based selection.

---

## 6. Validation and Test Scenarios

### 6.1 Unit Tests (Service Layer)

```python
# File: tests/test_chat_orchestrator.py

class TestProcessTurn:
    async def test_basic_chat_turn_happy_path(self, db_session, sample_ai_session):
        """A simple user message without tool calls returns an assistant reply."""
        pass

    async def test_chat_turn_with_list_pages_tool_call(self, db_session, sample_ai_session_with_pages, monkeypatch):
        """When the LLM calls list_pages, the executor returns pages from DB."""
        pass

    async def test_chat_turn_with_propose_create_page(self, db_session, sample_ai_session, monkeypatch):
        """When the LLM proposes a page, a proposal is created with PENDING_REVIEW status."""
        pass

    async def test_chat_turn_proposal_validation_error_retry(self, db_session, sample_ai_session, monkeypatch):
        """When a proposed page fails validation, the error is returned to the LLM for retry."""
        pass

    async def test_chat_turn_max_tool_rounds_exceeded(self, db_session, sample_ai_session, monkeypatch):
        """When MAX_TOOL_ROUNDS is exceeded, the loop stops and returns a summary."""
        pass

    async def test_chat_turn_permission_denied_unknown_page(self, db_session, sample_ai_session, monkeypatch):
        """When the LLM references a page outside the session's course, PERMISSION_DENIED is returned."""
        pass

    async def test_chat_turn_session_not_found(self, db_session):
        """A non-existent session ID returns SESSION_NOT_FOUND."""
        pass

    async def test_chat_turn_expired_session(self, db_session, sample_expired_ai_session):
        """An expired session returns SESSION_NOT_FOUND."""
        pass

    async def test_chat_turn_message_too_long(self, db_session, sample_ai_session):
        """A message exceeding 10000 chars returns a validation error."""
        pass

    async def test_chat_turn_llm_provider_timeout_triggers_fallback(self, db_session, sample_ai_session, monkeypatch):
        """When the primary model times out, the fallback model is used."""
        pass

    async def test_chat_turn_both_models_fail_returns_503(self, db_session, sample_ai_session, monkeypatch):
        """When both primary and fallback models fail, LLM_PROVIDER_UNAVAILABLE is returned."""
        pass

    async def test_chat_turn_persists_messages(self, db_session, sample_ai_session, monkeypatch):
        """After a turn completes, messages are persisted to ai_session_messages."""
        pass

    async def test_chat_turn_tool_call_logged(self, db_session, sample_ai_session, monkeypatch):
        """Each tool call execution is logged to ai_tool_call_logs."""
        pass

    async def test_chat_turn_telemetry_written(self, db_session, sample_ai_session, monkeypatch):
        """A telemetry event is written for the turn."""
        pass

    async def test_chat_turn_rate_limit_exceeded(self, db_session, sample_ai_session, monkeypatch):
        """When rate limit is exceeded, RATE_LIMIT_EXCEEDED is returned."""
        pass

    async def test_chat_turn_duplicate_turn_id_is_idempotent(self, db_session, sample_ai_session, monkeypatch):
        """Sending the same turn_id twice returns the existing result."""
        pass


class TestContextBuilder:
    async def test_build_system_prompt_includes_course_title(self, sample_ai_session):
        """The system prompt includes the course title."""
        pass

    async def test_build_system_prompt_includes_pending_proposals(self, db_session, sample_ai_session_with_proposal):
        """If there are pending proposals, they are listed in the system prompt."""
        pass

    async def test_tool_definitions_exclude_apply_when_no_proposals(self, sample_ai_session):
        """When no proposals exist, apply_* tools are excluded from tool definitions."""
        pass

    async def test_build_messages_array_trims_history(self, db_session, sample_ai_session_with_long_history):
        """When history exceeds max_messages, only the most recent messages are included."""
        pass

    async def test_prune_context_removes_oldest_pairs(self, db_session, sample_ai_session_with_many_messages):
        """When token count exceeds limit, oldest user/assistant pairs are removed."""
        pass

    async def test_prune_context_injects_summary(self, db_session, sample_ai_session_with_many_messages):
        """When substantive context is pruned, a summary message is injected."""
        pass

    async def test_build_summary_message_has_role_user(self):
        """The summary message has role='user' and contains a summary of removed messages."""
        pass


class TestLLMClient:
    async def test_call_basic_text_response(self, monkeypatch):
        """A basic text response from the LLM is returned as a dict with content."""
        pass

    async def test_call_with_tool_calls(self, monkeypatch):
        """When the LLM returns tool_use blocks, they are included in the response."""
        pass

    async def test_call_with_streaming(self, monkeypatch):
        """Streaming response yields events in the expected order."""
        pass

    async def test_call_timeout_triggers_retry(self, monkeypatch):
        """A timeout triggers a retry with backoff."""
        pass

    async def test_call_non_retryable_error_raises_immediately(self, monkeypatch):
        """A 400 error from the API raises LLMProviderError immediately without retry."""
        pass

    async def test_with_fallback_primary_succeeds(self, monkeypatch):
        """When primary model succeeds, fallback is not called."""
        pass

    async def test_with_fallback_primary_fails_fallback_succeeds(self, monkeypatch):
        """When primary model fails, fallback model is called and the response includes fallback_triggered=True."""
        pass

    async def test_rejects_unsupported_model(self, monkeypatch):
        """An unsupported model ID raises LLMProviderError."""
        pass


class TestToolExecutor:
    async def test_list_pages_returns_pages(self, db_session, sample_ai_session_with_pages):
        """list_pages returns all pages for the session's course."""
        pass

    async def test_fetch_page_returns_full_page_data(self, db_session, sample_ai_session_with_pages):
        """fetch_page returns page with components."""
        pass

    async def test_fetch_page_wrong_course_returns_permission_denied(self, db_session, sample_ai_session):
        """fetch_page for a page in a different course returns PERMISSION_DENIED."""
        pass

    async def test_propose_create_page_creates_proposal(self, db_session, sample_ai_session):
        """propose_create_page creates an ai_proposals record with PENDING_REVIEW."""
        pass

    async def test_propose_delete_page_creates_proposal_with_confirmation(self, db_session, sample_ai_session_with_pages):
        """propose_delete_page creates a proposal with confirmation required."""
        pass

    async def test_apply_page_proposal_requires_existing_proposal(self, db_session, sample_ai_session):
        """apply_page_proposal with a non-existent proposalId returns PROPOSAL_NOT_FOUND."""
        pass

    async def test_apply_page_proposal_not_pending_returns_409(self, db_session, sample_ai_session_with_applied_proposal):
        """apply_page_proposal for an already-applied proposal returns PROPOSAL_ALREADY_APPLIED."""
        pass

    async def test_validate_course_returns_validation_errors(self, db_session, sample_ai_session):
        """validate_course returns any validation errors for the current course state."""
        pass

    async def test_input_validation_rejects_missing_required_fields(self, db_session, sample_ai_session):
        """Missing required fields in tool input return validation errors."""
        pass
```

### 6.2 Integration Tests (API Layer)

```python
# File: tests/test_ai_chat_api.py

class TestChatAPI:
    async def test_chat_endpoint_returns_200_with_reply(self, async_client, sample_ai_session, monkeypatch):
        """POST /api/v1/ai/chat returns 200 with assistant reply."""
        pass

    async def test_chat_endpoint_streaming_returns_sse(self, async_client, sample_ai_session, monkeypatch):
        """When stream=true, response has Content-Type: text/event-stream."""
        pass

    async def test_chat_endpoint_with_tool_call_creates_proposal(self, async_client, sample_ai_session, monkeypatch):
        """A chat turn that calls propose_create_page creates an ai_proposals record."""
        pass

    async def test_chat_endpoint_invalid_session_returns_404(self, async_client):
        """A non-existent session ID returns 404."""
        pass

    async def test_chat_endpoint_message_too_long_returns_422(self, async_client, sample_ai_session):
        """A message exceeding 10000 chars returns 422."""
        pass

    async def test_chat_endpoint_feature_flag_disabled_returns_404(self, async_client, monkeypatch):
        """When AI_AUTHORING_ENABLED=false, endpoint returns 404."""
        pass

    async def test_chat_endpoint_rate_limited_returns_429(self, async_client, sample_ai_session, monkeypatch):
        """When rate limit is exceeded, endpoint returns 429 with Retry-After header."""
        pass

    async def test_chat_endpoint_response_shape(self, async_client, sample_ai_session, monkeypatch):
        """Response includes turn_id, session_id, reply, proposals, token_usage."""
        pass


class TestSessionMessagesAPI:
    async def test_get_messages_returns_history(self, async_client, sample_ai_session_with_messages):
        """GET /api/v1/ai/sessions/{session_id}/messages returns stored messages."""
        pass

    async def test_get_messages_empty_session_returns_empty_list(self, async_client, sample_ai_session):
        """A session with no messages returns an empty messages array."""
        pass

    async def test_get_messages_pagination(self, async_client, sample_ai_session_with_messages):
        """The limit and offset parameters correctly paginate results."""
        pass


class TestSessionTokensAPI:
    async def test_get_tokens_returns_usage(self, async_client, sample_ai_session_with_telemetry):
        """GET /api/v1/ai/sessions/{session_id}/tokens returns token counts and cost."""
        pass

    async def test_get_tokens_no_usage_returns_zero(self, async_client, sample_ai_session):
        """A session with no activity returns zero tokens."""
        pass
```

### 6.3 E2E Scenarios

**Scenario 1: Simple chat edit (no tool calls)**
1. Frontend calls `POST /api/v1/ai/sessions` to create a session.
2. Frontend calls `POST /api/v1/ai/chat` with `message: "What pages are in this course?"`.
3. LLM responds with text: "This course currently has 3 pages: Welcome, Content, and Quiz."
4. Frontend renders the AI response in the chat panel.
5. No proposals are created.

**Scenario 2: Chat with single tool call**
1. Frontend sends `message: "Create a new content page called 'Module 2: Advanced Topics'."`.
2. LLM responds with tool call `propose_create_page(title="Module 2: Advanced Topics", templateType="content-text", data={...})`.
3. ToolExecutor creates a proposal and returns success with preview.
4. LLM generates final text: "I've created a proposal for a new page 'Module 2: Advanced Topics'. Here's a preview: ... Please review and confirm when ready."
5. Frontend shows the proposal preview with a confirm button.
6. User clicks confirm; frontend sends `POST /api/v1/ai/tools/apply_page_proposal`.

**Scenario 3: Multi-round tool calling (list_pages -> propose_update_page)**
1. User sends: "Update the course welcome page to mention Python 3.12."
2. LLM calls `list_pages()` to find the welcome page.
3. ToolExecutor returns `{pages: [{pageId: "page_1", title: "Welcome to Python", ...}]}`.
4. LLM calls `propose_update_page(pageId="page_1", patch={title: "Welcome to Python 3.12"})`.
5. ToolExecutor creates a proposal and returns diff.
6. LLM generates text: "I found the welcome page and have proposed an update to mention Python 3.12. Here's the change: ..."
7. User confirms.

**Scenario 4: LLM validation error recovery**
1. User sends: "Create a quiz with 2 questions about Python lists."
2. LLM generates an MCQ page but question 2 has no correct answer marked.
3. ToolExecutor validates and returns `VALIDATION_ERROR: "Question 2 must have exactly one correct answer"`.
4. Backend returns error to LLM without stopping the turn.
5. LLM retries with fixed data (adds `isCorrect: true` to option 2b).
6. Validation passes.
7. LLM: "I created a quiz with 2 questions. However, please review question 2's options..."

**Scenario 5: Max tool rounds exceeded**
1. LLM enters a loop of: fetch_page -> propose_update -> error -> fetch_page -> propose_update -> error...
2. After 10 rounds, the orchestrator stops the loop.
3. Returns error: "The AI assistant exceeded the maximum number of tool call rounds. Please simplify your request."
4. No proposals are created.

### 6.4 Safety Invariant Tests

```python
# Invariant: chat never mutates course data directly
async def test_invariant_chat_never_mutates_course(test_client, sample_ai_session):
    """A chat turn that creates proposals does not create or modify CourseRecord/PageRecord."""
    response = await test_client.post("/api/v1/ai/chat", json={
        "session_id": sample_ai_session["session_id"],
        "message": "Create a new page called 'Test'",
        "stream": False,
    })
    assert response.status_code == 200
    # Verify no CourseRecord or PageRecord was created
    courses_response = await test_client.get("/api/v1/courses")
    assert len(courses_response.json()) == original_course_count

# Invariant: chat never applies proposals without explicit user confirmation
async def test_invariant_no_auto_apply(test_client, sample_ai_session):
    """Proposal-creation tool calls never automatically apply proposals."""
    pass

# Invariant: tool calls never reference out-of-scope resources
async def test_invariant_no_cross_course_access(test_client, sample_ai_session, second_course_session):
    """A tool call referencing a page from another course is rejected."""
    pass

# Invariant: expired sessions reject all tool calls
async def test_invariant_expired_session_rejects_tools(test_client, sample_expired_ai_session):
    """Tool calls on expired sessions return SESSION_NOT_FOUND."""
    pass
```

### 6.5 Concurrency Tests

```python
async def test_concurrent_chat_turns_same_session(test_client, sample_ai_session):
    """Two concurrent chat turns for the same session are processed sequentially."""
    pass

async def test_concurrent_tool_calls_different_sessions(test_client, sample_ai_session, second_ai_session):
    """Tool calls from different sessions do not interfere."""
    pass

async def test_rate_limit_independent_per_user(test_client, sample_ai_session, different_user_session):
    """Rate limits are scoped per user; two users do not share counters."""
    pass
```

---

## 7. Definition of Done

### 7.1 Code Complete

- [ ] `app/models/ai_chat.py` — ORM models for `AISessionMessageRecord`, `AIToolCallLogRecord`, `AITelemetryEventRecord`, `AIRateLimitRecord`.
- [ ] `app/repositories/ai_chat_repo.py` — Repositories for all four new models with full CRUD + query methods.
- [ ] `app/services/ai/chat_orchestrator.py` — `ChatOrchestrator` with `process_turn`, `_execute_llm_loop`, `_execute_tool`, `_call_llm`, `_persist_messages`, `_prune_context_if_needed`, `_write_telemetry`, `_check_rate_limits`.
- [ ] `app/services/ai/llm_client.py` — `LLMClient` with `call`, `call_stream`, `_attempt_call`, `with_fallback` supporting Anthropic Claude Messages API.
- [ ] `app/services/ai/tool_executor.py` — `ToolExecutor` with handlers for all 10 tools: `list_pages`, `fetch_page`, `propose_create_page`, `propose_update_page`, `propose_delete_page`, `apply_page_proposal`, `apply_update_proposal`, `confirm_delete_page`, `validate_course`, `query_similar_courses`.
- [ ] `app/services/ai/context_builder.py` — `ContextBuilder` with `build_system_prompt`, `build_tool_definitions`, `build_messages_array`, `prune_context`, `build_summary_message`.
- [ ] `app/routers/ai_chat_dtos.py` — All Pydantic DTOs for chat request/response and supporting types.
- [ ] `app/routers/ai_chat.py` — Router with `POST /api/v1/ai/chat` (SSE + JSON), `GET /api/v1/ai/sessions/{session_id}/messages`, `GET /api/v1/ai/sessions/{session_id}/tokens`.
- [ ] Alembic migration for `ai_session_messages`, `ai_tool_call_logs`, `ai_telemetry_events`, `ai_rate_limits` tables.
- [ ] Registration in `app/main.py` (router + ORM model import in lifespan).
- [ ] Registration in `app/models/__init__.py`.
- [ ] Environment variables added to `.env` and `.env.example`.

### 7.2 Tests Pass

- [ ] All unit tests pass (30+ tests across `test_chat_orchestrator.py`, `test_context_builder.py`, `test_llm_client.py`, `test_tool_executor.py`).
- [ ] All integration tests pass (12+ tests in `test_ai_chat_api.py`).
- [ ] All safety invariant tests pass (4 tests).
- [ ] All concurrency tests pass (3 tests).
- [ ] Existing session, course, page, and proposal CRUD tests still pass (regression).
- [ ] Coverage >= 85% for new code.

### 7.3 Documentation

- [ ] API contracts for `POST /api/v1/ai/chat`, `GET /api/v1/ai/sessions/{session_id}/messages`, `GET /api/v1/ai/sessions/{session_id}/tokens` documented in OpenAPI spec.
- [ ] SSE event stream contract documented.
- [ ] Environment variables documented in `.env.example`.
- [ ] Flow diagrams in `docs/AI_Implemenation/01_SystemArchitecture/` updated to include the chat interaction loop.

### 7.4 Security

- [ ] All chat endpoints gated by `AI_AUTHORING_ENABLED=true`.
- [ ] Session ID + user ID validation on every request.
- [ ] Tool scope enforcement (page_id must belong to session's course_id).
- [ ] User message length limited to `AI_CHAT_MAX_MESSAGE_LENGTH` (10000).
- [ ] Prompt injection resistance: user messages truncated and sanitized before prompt construction.
- [ ] No auto-apply of proposals; user confirmation required.
- [ ] Rate limits enforced per-user and per-tenant.
- [ ] All tool calls logged to `ai_tool_call_logs` for audit.

### 7.5 Operational Readiness

- [ ] Feature flag `AI_AUTHORING_ENABLED` gates all chat endpoints.
- [ ] Primary model fallback to `AI_CHAT_FALLBACK_MODEL` on timeout/failure.
- [ ] Max tool rounds (`AI_CHAT_MAX_TOOL_ROUNDS`) enforced to prevent infinite loops.
- [ ] Context window pruning (`AI_CHAT_CONTEXT_TOKEN_LIMIT`) prevents token limit exceeded errors.
- [ ] Rate limits (`AI_RATE_LIMIT_CHAT_PER_USER`, `AI_RATE_LIMIT_CHAT_PER_TENANT`) enforced with `Retry-After` header.
- [ ] Telemetry events written for every chat turn, LLM call, and tool execution.
- [ ] Metrics counters for chat requests, LLM calls, tool calls, rate limit exceedances.

---

## 8. Tasks

### Task 1: Create ORM Models for Chat Persistence

**Files to create/modify:**
- `app/models/ai_chat.py` (new)
- `app/models/__init__.py` (add import)

**Acceptance:**
- `AISessionMessageRecord` has all columns: message_id, session_id (FK to ai_sessions), turn_id, role (system/user/assistant/tool_result), content, tool_calls (JSONB), tool_call_id, tool_name, tool_result (JSONB), input_tokens, output_tokens, created_at.
- `AIToolCallLogRecord` has all columns: log_id, session_id, turn_id, tool_call_id, tool_name, input_args (JSONB), output_data (JSONB), error_message, status, retry_count, execution_duration_ms, created_at.
- `AITelemetryEventRecord` has all columns: event_id, session_id, turn_id, trace_id, event_type, payload (JSONB), input_tokens, output_tokens, latency_ms, model_id, created_at.
- `AIRateLimitRecord` has all columns: scope, scope_id, endpoint, window_start, request_count, created_at.
- `to_dict()` serializes all fields with correct key naming.
- All models registered in `app/models/__init__.py`.

**Effort:** 3 hours
**Dependencies:** US-AI-004 (ai_sessions table for FK)

---

### Task 2: Create Chat Repositories

**File to create:**
- `app/repositories/ai_chat_repo.py` (new)

**Acceptance:**
- `AISessionMessageRepository` supports: create, bulk_create, list_by_session (with pagination and role filter), count_by_session, delete_by_session, get_oldest_messages_for_pruning.
- `AIToolCallLogRepository` supports: create, update_status, list_by_turn, list_by_session.
- `AITelemetryEventRepository` supports: create, list_by_session, aggregate_token_usage.
- `AIRateLimitRepository` supports: increment_and_check (with upsert pattern for window_start), reset_window.
- All methods follow the established repository pattern (AsyncSession, select(), execute(), commit()).

**Effort:** 3 hours
**Dependencies:** Task 1

---

### Task 3: Implement LLMClient

**File to create:**
- `app/services/ai/llm_client.py` (new)

**Acceptance:**
- `call()` sends POST request to `AI_LLM_API_URL` with Anthropic Messages API format.
- Supports `tools` parameter for native tool-calling.
- Supports `stream: True` mode yielding events via `call_stream()` async generator.
- Implements timeout via configurable `AI_LLM_TIMEOUT_SECONDS`.
- Implements retry with exponential backoff (1s, 2s, 4s) on HTTP 429, 5xx, and timeout errors.
- `with_fallback()` tries primary model, catches errors, tries fallback model, returns response with `fallback_triggered` flag.
- Non-retryable errors (HTTP 4xx except 429) raise `LLMProviderError` immediately.
- Raises `LLMProviderError` with `retryable` flag for transient errors.
- Raises `LLMTimeoutError` when timeout is exceeded.
- All calls logged with model, prompt length, response length, latency_ms.
- API key loaded from `AI_LLM_API_KEY` env var (never logged).
- `close()` method for graceful httpx client cleanup.
- Unit tests mock `httpx.AsyncClient` to avoid real HTTP calls.

**Effort:** 6 hours
**Dependencies:** None (standalone HTTP client)

---

### Task 4: Implement ContextBuilder

**File to create:**
- `app/services/ai/context_builder.py` (new)

**Acceptance:**
- `build_system_prompt()` returns a string with: course metadata (title, description, page count), list of pending proposals, tool usage rules (propose before apply, re-fetch before edit), current date, system prompt version from env.
- `build_tool_definitions()` reads tool schemas from the tool registry (US-AI-005) and returns a filtered set based on context (exclude apply tools if no pending proposals).
- `build_messages_array()` constructs the messages array: [system_prompt] + [history (trimmed)] + [user_message].
- `prune_context()` counts approximate tokens (len/4), removes oldest user/assistant pairs until under `CONTEXT_TOKEN_LIMIT`, injects a summary message if more than 2 pairs were removed.
- `build_summary_message()` creates a user-role message summarizing the removed conversation.
- `count_tokens()` returns `len(text) // 4` as a rough approximation.
- System prompt content is injectable via env or DB for future A/B testing (US-AI-042).

**Effort:** 5 hours
**Dependencies:** US-AI-005 (tool registry for tool definitions)

---

### Task 5: Implement ToolExecutor

**File to create:**
- `app/services/ai/tool_executor.py` (new)

**Acceptance:**
- `execute()` method: validates input args against tool schema, checks permission scope, calls the handler method, returns ToolResult dict, writes audit log to `ai_tool_call_logs`.
- `_validate_input()` checks required fields, field types, and constraints against the tool's input_schema. Returns list of error messages.
- `_check_permission()`: For list_pages/fetch_page — verifies course_id matches session. For propose/apply tools — verifies page_id belongs to session's course_id. Raises `PermissionDeniedError` on violation.
- `_execute_list_pages()`: Calls `PageRepository.list_by_course()`, returns pages array with metadata.
- `_execute_fetch_page()`: Calls `PageRepository.get_by_page_id()` with `include_components=True`, returns full page data.
- `_execute_propose_create_page()`: Validates page data against template schema, creates `ai_proposals` record with status `PENDING_REVIEW`, returns proposal_id + preview + validation status.
- `_execute_propose_update_page()`: Computes diff between current page state and proposed patch, creates `ai_proposals` record with diff preview.
- `_execute_propose_delete_page()`: Creates `ai_proposals` record with `confirmation_required=True`, returns proposal_id + page preview.
- `_execute_apply_page_proposal()`: Loads proposal, verifies `PENDING_REVIEW` status, calls `PageRepository.create()` (or returns existing if already applied for idempotency).
- `_execute_apply_update_proposal()`: Loads proposal, verifies `PENDING_REVIEW`, applies patch to existing page via `PageRepository.update()`.
- `_execute_confirm_delete_page()`: Loads proposal with confirmation token, verifies token validity, deletes page via `PageRepository.delete_record()`.
- `_execute_validate_course()`: Runs full course validation via CourseValidator, returns errors/warnings/passed.
- `_execute_query_similar_courses()`: Calls RAG service (US-AI-015), returns similar course examples or empty list if RAG not configured.
- All handlers include timing (`execution_duration_ms`) and error handling.

**Effort:** 8 hours
**Dependencies:** Task 2 (repository), US-AI-005 (tool schemas), US-AI-007 (list_pages/fetch_page handlers), US-AI-008 (course validation)

---

### Task 6: Implement ChatOrchestrator — Core Interaction Loop

**File to create:**
- `app/services/ai/chat_orchestrator.py` (new)

**Acceptance:**
- `process_turn()`: Loads session context, calls `_execute_llm_loop()`, persists messages, writes telemetry, returns ChatResponse or SSE generator.
- `_load_session_context()`: Loads `ai_sessions` record (validates not expired, correct user), loads `CourseRecord` with pages, loads pending proposals, loads recent messages.
- `_build_messages()`: Calls ContextBuilder to construct messages array and tool definitions.
- `_execute_llm_loop()`:
  - Sends messages+tools to `_call_llm()`.
  - If response has text content: stream text delta, return final response.
  - If response has tool_use blocks: for each block:
    1. Call `_execute_tool()` with the tool name and input.
    2. Stream tool_call_start and tool_call_result/error events.
    3. Append tool result to messages array.
  - After all tool blocks processed, send updated messages+tools to LLM for next round.
  - Count rounds; if > MAX_TOOL_ROUNDS, stop and return max-rounds-exceeded message.
- `_execute_tool()`: Calls `ToolExecutor.execute()`, writes tool call log, returns structured result.
- `_call_llm()`: Calls `LLMClient.with_fallback()` for model resilience.
- `_persist_messages()`: Saves user message, all assistant messages (text + tool calls), and tool results to `ai_session_messages` via repository.
- `_prune_context_if_needed()`: Checks if context window is approaching limit, calls ContextBuilder.prune_context() on stored messages, saves the pruning action.
- `_write_telemetry()`: Creates and persists `AITelemetryEventRecord` for turn start, turn complete, LLM calls, tool executions.
- `_check_rate_limits()`: Calls `AIRateLimitRepository.increment_and_check()`, raises `RateLimitError` if exceeded.
- SSE streaming mode yields events: `turn_start`, `tool_call_start`, `tool_call_result`, `tool_call_error`, `text_delta`, `turn_complete`, `turn_error`, `[DONE]`.
- Non-streaming mode accumulates all events and returns final ChatResponse.

**Effort:** 12 hours
**Dependencies:** Tasks 3 (LLMClient), 4 (ContextBuilder), 5 (ToolExecutor), 2 (repositories)

---

### Task 7: Create Pydantic DTOs

**File to create:**
- `app/routers/ai_chat_dtos.py` (new)

**Acceptance:**
- `ChatRequest`: session_id, message (1-10000 chars), stream (default true), context_refresh (default false).
- `ChatResponse`: turn_id, session_id, reply (optional), proposals list, tool_calls_executed, tool_rounds, token_usage, latency_ms, status.
- `ChatErrorResponse`: code, message, retryable, turn_id (optional), details.
- `ToolDefinition`: name, description, input_schema, output_schema (optional), idempotent.
- `ToolCallRequest`: tool_call_id, tool_name, input.
- `ToolCallResult`: tool_call_id, tool_name, status, output, error, error_code, retryable, execution_duration_ms.
- `ChatContext`: turn_id, session_status, pages_in_course, pending_proposals, token_usage, model.
- All models use descriptive Field() descriptions for OpenAPI schema generation.

**Effort:** 1.5 hours
**Dependencies:** None

---

### Task 8: Create API Router and Wire Endpoints

**Files to create/modify:**
- `app/routers/ai_chat.py` (new)
- `app/main.py` (register router + ORM model import)
- `app/models/__init__.py` (add import)

**Acceptance:**
- `POST /api/v1/ai/chat`:
  - When `stream: true`, returns `StreamingResponse` with `Content-Type: text/event-stream`, SSE events as specified in Section 1.5.
  - When `stream: false`, returns `ChatResponse` JSON.
  - Validates session before proceeding.
  - Applies feature flag gating via `ai_authoring_enabled` dependency.
  - Applies rate limit check before proceeding.
  - Error responses use the error envelope pattern from `app/utils/error_envelope.py`.
  - SSE response includes `X-Trace-ID` header, `Cache-Control: no-cache`, `Connection: keep-alive`.
- `GET /api/v1/ai/sessions/{session_id}/messages`:
  - Returns conversation history ordered by created_at (oldest first).
  - Supports pagination via `limit` (max 200) and `offset`.
  - Returns `has_more` boolean for frontend to load more.
- `GET /api/v1/ai/sessions/{session_id}/tokens`:
  - Returns aggregated token usage for the session.
  - Returns estimated cost based on token counts and model pricing.
- Router is registered in `api_router` under `/api/v1` prefix.
- ORM model is imported during startup so `create_all` creates the tables.

**Effort:** 4 hours
**Dependencies:** Tasks 6 (ChatOrchestrator), 7 (DTOs)

---

### Task 9: Create Alembic Migration

**File to create:**
- `alembic/versions/20260614_0003_add_ai_chat_tables.py`

**Acceptance:**
- Creates `ai_session_messages` table with all columns as specified in section 2.1.
- Creates `ai_tool_call_logs` table with all columns as specified in section 2.1.
- Creates `ai_telemetry_events` table with all columns as specified in section 2.1.
- Creates `ai_rate_limits` table with all columns as specified in section 2.1.
- All indexes as specified: `idx_asm_session`, `idx_asm_turn`, `idx_asm_created`, `idx_atcl_session`, `idx_atcl_turn`, `idx_atcl_tool`, `idx_ate_session`, `idx_ate_trace`, `idx_ate_type`, `idx_ate_created`, `idx_arl_lookup`.
- Foreign keys with correct ON DELETE CASCADE/SET NULL behavior.
- `downgrade()` drops all four tables.
- Migration runs cleanly against both SQLite (dev) and PostgreSQL (prod).

**Effort:** 1.5 hours
**Dependencies:** Tasks 1 (table column definitions)

---

### Task 10: Write Unit Tests for Service Layer

**Files to create:**
- `tests/test_chat_orchestrator.py`
- `tests/test_llm_client.py`
- `tests/test_tool_executor.py`

**Acceptance:**
- All test scenarios from Section 6.1 are covered.
- Safety invariant tests from Section 6.4 pass.
- Tests use in-memory SQLite test fixtures.
- LLM calls are mocked via `monkeypatch` or mock `httpx` responses.
- Mock LLM responses cover: text-only, tool_use, streaming, timeout, HTTP errors.
- Tool executor tests cover: all 10 tools, permission scope violations, input validation errors, idempotent retries.
- Coverage >= 85% for `chat_orchestrator.py`, `llm_client.py`, `tool_executor.py`, `context_builder.py`.

**Effort:** 10 hours
**Dependencies:** Tasks 3, 4, 5, 6

---

### Task 11: Write Integration Tests for API Layer

**File to create:**
- `tests/test_ai_chat_api.py`

**Acceptance:**
- All test scenarios from Section 6.2 are covered.
- Tests use `TestClient` with async httpx support.
- Test fixtures include: `sample_ai_session`, `sample_ai_session_with_pages`, `sample_ai_session_with_messages`, `sample_ai_session_with_proposal`, `sample_expired_ai_session`, `second_course_session`.
- Existing session, course, and page CRUD tests still pass.
- Tests verify SSE event stream format for streaming mode.
- Tests cover success, error, feature-flag-disabled, and rate-limited paths.
- Tests verify message persistence by querying the messages endpoint after a chat turn.

**Effort:** 6 hours
**Dependencies:** Task 8

---

### Task 12: Add Environment Variables and Configuration

**Files to modify:**
- `.env.example`
- `.env`

**Acceptance:**
- All environment variables from Section 2.10 are documented in `.env.example`.
- Default values are provided for all non-secret variables.
- `AI_LLM_API_KEY` is documented as a required secret (no default).
- Configuration is read at module level in each service file.
- Missing optional variables log a warning and use the documented default.

**Effort:** 0.5 hours
**Dependencies:** Tasks 3, 4, 6

---

### Task 13: Rate Limit Middleware Integration

**File to modify:**
- `app/services/ai/chat_orchestrator.py` — `_check_rate_limits()`
- `app/repositories/ai_chat_repo.py` — `AIRateLimitRepository`

**Acceptance:**
- `AIRateLimitRepository.increment_and_check()` supports per-user and per-tenant scoping.
- Uses upsert pattern: if a row exists for `(scope, scope_id, endpoint, window_start)`, increment `request_count`; otherwise insert with count=1.
- Window is aligned to `window_seconds` boundaries (e.g., for 3600s window, window_start is `NOW() - (NOW() % 3600)`).
- `_check_rate_limits()` is called at the start of `process_turn()`, before any LLM calls.
- Rate limit exceeded raises `RateLimitError` with current usage and limit info.
- API router catches `RateLimitError` and returns 429 with `Retry-After` header.

**Effort:** 2 hours
**Dependencies:** Task 2 (repository), Task 6 (orchestrator)

---

### Task 14: Documentation and Review

**Files to modify:**
- `docs/AI_Implemenation/00_User_StoriesUseCases/USER_STORIES.md` (update status)
- `docs/API.md` or OpenAPI spec (add new endpoints)
- `docs/AI_Implemenation/01_SystemArchitecture/` (update diagrams)

**Acceptance:**
- API contracts for all 3 endpoints are documented.
- SSE event stream contract is documented.
- Environment variables are documented in `.env.example` and the story.
- Flow diagrams updated to reflect the chat interaction loop.
- Story is marked complete in the canonical user stories list.

**Effort:** 2 hours
**Dependencies:** Tasks 8, 10, 11, 12

---

### Task 15: Code Review and Merge

**Acceptance:**
- All CI checks pass.
- Two approvals on the PR.
- No regression in existing tests (session, course, page, proposal CRUD).
- Feature flag `AI_AUTHORING_ENABLED` defaults to `false`.
- LLM provider API key is not committed; loaded from environment.
- Migration runs without errors on a fresh database.
- SSE streaming tested manually with `curl -N` to verify event flow.

**Effort:** 2 hours
**Dependencies:** All prior tasks

---

## Summary

| Metric | Value |
|---|---|
| New files | 8 |
| Modified files | 3 |
| New tables | 4 |
| New API endpoints | 3 |
| New services | 4 (ChatOrchestrator, LLMClient, ToolExecutor, ContextBuilder) |
| Total estimated effort | ~66.5 hours |
| Key safety invariant | Chat turns never mutate course data; all mutations go through proposal/apply pattern |
| Key risk | LLM provider availability and latency; fallback model mitigates transient failures |
